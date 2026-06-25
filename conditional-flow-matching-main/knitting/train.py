"""
训练脚本（DDP版）
支持 Stage 1 / 2 / 3 / 4，通过 yaml 里的 stage 字段切换。

启动方式：
  torchrun --nproc_per_node=2 knitting/train.py
  torchrun --nproc_per_node=2 knitting/train.py --config configs/stage4_final.yaml
"""

import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml
import json
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader
from torch.utils.data.distributed import DistributedSampler
from torch.optim import Adam
from torch.optim.lr_scheduler import LambdaLR
import numpy as np

from torchcfm.conditional_flow_matching import ConditionalFlowMatcher
from torchcfm.models.unet import UNetModel
from data.dataset import KnittingWindowDataset, worker_init_fn
from knitting.models import NeighborAwareConditioner


# ══════════════════════════════════════════════════════════════════
# DDP 辅助
# ══════════════════════════════════════════════════════════════════

def setup_ddp():
    if 'LOCAL_RANK' not in os.environ:
        return 0, 1, False
    dist.init_process_group(backend='nccl')
    local_rank = int(os.environ['LOCAL_RANK'])
    world_size = dist.get_world_size()
    torch.cuda.set_device(local_rank)
    return local_rank, world_size, True


def cleanup_ddp(is_ddp):
    if is_ddp:
        dist.destroy_process_group()


def is_main_process(local_rank):
    return local_rank == 0


def reduce_loss(loss, world_size):
    if world_size == 1:
        return loss
    loss_tensor = torch.tensor(loss).cuda()
    dist.all_reduce(loss_tensor, op=dist.ReduceOp.SUM)
    return (loss_tensor / world_size).item()


# ══════════════════════════════════════════════════════════════════
# 损失函数
# ══════════════════════════════════════════════════════════════════

class GradientLoss(nn.Module):
    def __init__(self):
        super().__init__()
        sobel_x = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=torch.float32)
        sobel_y = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=torch.float32)
        self.register_buffer('kernel_x', sobel_x.view(1, 1, 3, 3).repeat(3, 1, 1, 1))
        self.register_buffer('kernel_y', sobel_y.view(1, 1, 3, 3).repeat(3, 1, 1, 1))

    def forward(self, pred, target):
        gxp = F.conv2d(pred,   self.kernel_x, padding=1, groups=3)
        gyp = F.conv2d(pred,   self.kernel_y, padding=1, groups=3)
        gxt = F.conv2d(target, self.kernel_x, padding=1, groups=3)
        gyt = F.conv2d(target, self.kernel_y, padding=1, groups=3)
        return F.l1_loss(gxp, gxt) + F.l1_loss(gyp, gyt)


class FFTLoss(nn.Module):
    def forward(self, pred, target):
        return F.l1_loss(
            torch.abs(torch.fft.fft2(pred,   norm='ortho')),
            torch.abs(torch.fft.fft2(target, norm='ortho')),
        )


class TextureContrastLoss(nn.Module):
    """
    Weighted high-frequency reconstruction loss.

    This keeps fine structures such as waves and stripes visible without
    changing the dataset.  The weight map is derived from the target patch, so
    it naturally focuses on existing texture instead of hallucinating new one.
    """

    def __init__(self, gamma=2.0, eps=1e-6):
        super().__init__()
        self.gamma = gamma
        self.eps = eps
        lap = torch.tensor([
            [0,  1, 0],
            [1, -4, 1],
            [0,  1, 0],
        ], dtype=torch.float32)
        self.register_buffer('lap_kernel', lap.view(1, 1, 3, 3).repeat(3, 1, 1, 1))

    def forward(self, pred, target):
        target_hf = F.conv2d(target, self.lap_kernel, padding=1, groups=3).abs().mean(dim=1, keepdim=True)
        denom = target_hf.mean(dim=(2, 3), keepdim=True) + self.eps
        weight = (target_hf / denom).clamp(0.0, 4.0)
        weight = 1.0 + self.gamma * weight
        return (torch.abs(pred - target) * weight).mean()


class BoundaryLoss(nn.Module):
    """
    只在 patch 边界带区域计算重建损失
    直接约束块间连接自然性
    """

    def __init__(self, band_width=3, patch_size=16):
        super().__init__()
        self.band_width = band_width
        self.patch_size = patch_size

    def build_boundary_map(self, neighbor_ids):
        B = neighbor_ids.shape[0]
        device = neighbor_ids.device
        bw = self.band_width

        center_id = neighbor_ids[:, 1, 1]
        boundary_map = torch.zeros(B, 1, self.patch_size, self.patch_size, device=device)

        top_diff = (neighbor_ids[:, 0, 1] != center_id).float().view(B, 1, 1, 1)
        bottom_diff = (neighbor_ids[:, 2, 1] != center_id).float().view(B, 1, 1, 1)
        left_diff = (neighbor_ids[:, 1, 0] != center_id).float().view(B, 1, 1, 1)
        right_diff = (neighbor_ids[:, 1, 2] != center_id).float().view(B, 1, 1, 1)

        tl_diff = ((neighbor_ids[:, 0, 0] != center_id) |
                   (neighbor_ids[:, 0, 1] != center_id) |
                   (neighbor_ids[:, 1, 0] != center_id)).float().view(B, 1, 1, 1)
        tr_diff = ((neighbor_ids[:, 0, 2] != center_id) |
                   (neighbor_ids[:, 0, 1] != center_id) |
                   (neighbor_ids[:, 1, 2] != center_id)).float().view(B, 1, 1, 1)
        bl_diff = ((neighbor_ids[:, 2, 0] != center_id) |
                   (neighbor_ids[:, 2, 1] != center_id) |
                   (neighbor_ids[:, 1, 0] != center_id)).float().view(B, 1, 1, 1)
        br_diff = ((neighbor_ids[:, 2, 2] != center_id) |
                   (neighbor_ids[:, 2, 1] != center_id) |
                   (neighbor_ids[:, 1, 2] != center_id)).float().view(B, 1, 1, 1)

        boundary_map[:, :, :bw,  :] = torch.maximum(boundary_map[:, :, :bw,  :], top_diff)
        boundary_map[:, :, -bw:, :] = torch.maximum(boundary_map[:, :, -bw:, :], bottom_diff)
        boundary_map[:, :, :, :bw]  = torch.maximum(boundary_map[:, :, :, :bw], left_diff)
        boundary_map[:, :, :, -bw:] = torch.maximum(boundary_map[:, :, :, -bw:], right_diff)

        boundary_map[:, :, :bw,  :bw]  = torch.maximum(boundary_map[:, :, :bw,  :bw], tl_diff)
        boundary_map[:, :, :bw,  -bw:] = torch.maximum(boundary_map[:, :, :bw,  -bw:], tr_diff)
        boundary_map[:, :, -bw:, :bw]  = torch.maximum(boundary_map[:, :, -bw:, :bw], bl_diff)
        boundary_map[:, :, -bw:, -bw:] = torch.maximum(boundary_map[:, :, -bw:, -bw:], br_diff)

        boundary_map = F.avg_pool2d(boundary_map, kernel_size=3, stride=1, padding=1)
        boundary_map = boundary_map.clamp(0.0, 1.0)
        return boundary_map

    def forward(self, pred, target, neighbor_ids):
        boundary_map = self.build_boundary_map(neighbor_ids)
        diff = torch.abs(pred - target) * boundary_map
        denom = boundary_map.sum() * pred.shape[1] + 1e-6
        return diff.sum() / denom


class ContextAwareStructureLoss(nn.Module):
    """
    上下文感知复合结构损失（基于当前样本自己的 GT）
    内部包含三部分：
      1) ridge / width term（Laplacian）
      2) low-texture suppression term
      3) directional term（可选，Phase 1 默认关闭）

    设计原则：
    - 不依赖类别模板
    - 只依赖当前样本 GT 生成结构 mask
    - 高结构区做二阶结构匹配
    - 低结构区抑制额外纹理/额外线条
    """

    def __init__(
        self,
        mask_k=0.60,
        mask_temp=0.03,
        low_margin=0.015,
        low_allow_scale=0.50,
        low_ratio=0.75,
        directional_ratio=0.0,
    ):
        super().__init__()
        self.mask_k = mask_k
        self.mask_temp = mask_temp
        self.low_margin = low_margin
        self.low_allow_scale = low_allow_scale
        self.low_ratio = low_ratio
        self.directional_ratio = directional_ratio

        lap = torch.tensor([
            [0,  1, 0],
            [1, -4, 1],
            [0,  1, 0],
        ], dtype=torch.float32)

        dir_0 = torch.tensor([
            [-1, 0, 1],
            [-2, 0, 2],
            [-1, 0, 1],
        ], dtype=torch.float32)

        dir_90 = torch.tensor([
            [-1, -2, -1],
            [ 0,  0,  0],
            [ 1,  2,  1],
        ], dtype=torch.float32)

        dir_45 = torch.tensor([
            [-2, -1,  0],
            [-1,  0,  1],
            [ 0,  1,  2],
        ], dtype=torch.float32)

        dir_135 = torch.tensor([
            [ 0,  1,  2],
            [-1,  0,  1],
            [-2, -1,  0],
        ], dtype=torch.float32)

        self.register_buffer('lap_kernel', lap.view(1, 1, 3, 3).repeat(3, 1, 1, 1))
        self.register_buffer('dir0_kernel', dir_0.view(1, 1, 3, 3).repeat(3, 1, 1, 1))
        self.register_buffer('dir45_kernel', dir_45.view(1, 1, 3, 3).repeat(3, 1, 1, 1))
        self.register_buffer('dir90_kernel', dir_90.view(1, 1, 3, 3).repeat(3, 1, 1, 1))
        self.register_buffer('dir135_kernel', dir_135.view(1, 1, 3, 3).repeat(3, 1, 1, 1))

    def _conv(self, x, kernel):
        return F.conv2d(x, kernel, padding=1, groups=3)

    def _build_masks(self, target):
        lap_t = self._conv(target, self.lap_kernel)
        struct_mag = lap_t.abs().mean(dim=1, keepdim=True)

        mu = struct_mag.mean(dim=(2, 3), keepdim=True)
        std = struct_mag.std(dim=(2, 3), keepdim=True, unbiased=False)

        thresh = mu + self.mask_k * std
        temp = max(self.mask_temp, 1e-6)

        high_mask = torch.sigmoid((struct_mag - thresh) / temp)
        low_mask = 1.0 - high_mask
        return high_mask, low_mask, lap_t, struct_mag

    def _directional_term(self, pred, target, high_mask):
        if self.directional_ratio <= 0:
            return pred.new_tensor(0.0)

        denom = high_mask.sum() * pred.shape[1] + 1e-6
        kernels = [
            self.dir0_kernel,
            self.dir45_kernel,
            self.dir90_kernel,
            self.dir135_kernel,
        ]

        loss = pred.new_tensor(0.0)
        for kernel in kernels:
            rp = self._conv(pred, kernel)
            rt = self._conv(target, kernel)
            loss = loss + (((rp - rt).abs()) * high_mask).sum() / denom

        return loss / len(kernels)

    def forward(self, pred, target):
        high_mask, low_mask, lap_t, target_struct = self._build_masks(target)
        lap_p = self._conv(pred, self.lap_kernel)

        # Part A: ridge / width term
        denom_high = high_mask.sum() * pred.shape[1] + 1e-6
        loss_ridge = (((lap_p - lap_t).abs()) * high_mask).sum() / denom_high

        # Part B: low-texture suppression term
        pred_struct = lap_p.abs().mean(dim=1, keepdim=True)
        allowance = self.low_allow_scale * target_struct + self.low_margin
        excess = F.relu(pred_struct - allowance)
        loss_low = (excess * low_mask).sum() / (low_mask.sum() + 1e-6)

        # Part C: directional term（Phase 1 默认关闭）
        loss_dir = self._directional_term(pred, target, high_mask)

        total = loss_ridge + self.low_ratio * loss_low + self.directional_ratio * loss_dir

        stats = {
            'ridge': loss_ridge.detach(),
            'low': loss_low.detach(),
            'dir': loss_dir.detach(),
            'high_mask_mean': high_mask.mean().detach(),
        }
        return total, stats


# ══════════════════════════════════════════════════════════════════
# Stage 1：Baseline
# ══════════════════════════════════════════════════════════════════

class Stage1ConditionedUNet(nn.Module):
    def __init__(self, num_classes=15, patch_size=16):
        super().__init__()
        self.unet = UNetModel(
            dim=(3, patch_size, patch_size), num_channels=64, num_res_blocks=2,
            channel_mult=(1, 2, 2), class_cond=True, num_classes=num_classes,
            attention_resolutions='8,4', num_heads=4, num_head_channels=32, dropout=0.1,
        )

    def forward(self, x, t, center_id):
        return self.unet(t, x, y=center_id)


# ══════════════════════════════════════════════════════════════════
# Stage 2：邻居感知
# ══════════════════════════════════════════════════════════════════

class Stage2NeighborAwareUNet(nn.Module):
    def __init__(self, num_classes=15, embed_dim=256, num_heads=8, patch_size=16):
        super().__init__()
        self.patch_size = patch_size
        self.conditioner = NeighborAwareConditioner(
            num_classes=num_classes, embed_dim=embed_dim, num_heads=num_heads,
        )
        self.unet = UNetModel(
            dim=(3, patch_size, patch_size), num_channels=128, num_res_blocks=3,
            channel_mult=(1, 2, 2), class_cond=False, num_classes=None,
            attention_resolutions='8,4', num_heads=num_heads, num_head_channels=32, dropout=0.1,
        )
        time_embed_dim = 128 * 4
        self.cond_to_time = nn.Sequential(
            nn.Linear(embed_dim, time_embed_dim), nn.SiLU(),
            nn.Linear(time_embed_dim, time_embed_dim),
        )
        self.cond_to_spatial = nn.Sequential(nn.Linear(embed_dim, patch_size * patch_size), nn.SiLU())
        self.spatial_fusion = nn.Conv2d(4, 3, kernel_size=1)

    def forward(self, x, t, neighbor_ids, neighbor_mask):
        cond = self.conditioner(neighbor_ids, neighbor_mask)
        cond_embed = self.cond_to_time(cond)
        B = x.shape[0]
        cond_spatial = self.cond_to_spatial(cond).view(B, 1, self.patch_size, self.patch_size)
        x_aug = self.spatial_fusion(torch.cat([x, cond_spatial], dim=1))
        return self._unet_forward_with_cond(x_aug, t, cond_embed)

    def _unet_forward_with_cond(self, x, t, cond_embed):
        from torchcfm.models.unet.nn import timestep_embedding
        unet = self.unet
        emb = unet.time_embed(timestep_embedding(t, unet.model_channels)) + cond_embed
        h = x.type(unet.dtype)
        hs = []
        for module in unet.input_blocks:
            h = module(h, emb)
            hs.append(h)
        h = unet.middle_block(h, emb)
        for module in unet.output_blocks:
            h = torch.cat([h, hs.pop()], dim=1)
            h = module(h, emb)
        return unet.out(h.type(x.dtype))


# ══════════════════════════════════════════════════════════════════
# Stage 3：物理特征编码
# ══════════════════════════════════════════════════════════════════

class PhysicsFeatureEncoder(nn.Module):
    def __init__(self, json_path, embed_dim=256):
        super().__init__()
        self.embed_dim = embed_dim
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        instructions = data['instructions']

        semantic_types = ['LOOP', 'TUCK', 'TRANSFER', 'SPLIT', 'MISS', 'DROP', 'CARRIER']
        bed_types = ['front', 'back', 'none']

        features = []
        for inst in instructions:
            feat = []
            feat.append(inst.get('tension', 5.0) / 10.0)
            feat.append(inst.get('elasticity', 0.5))
            feat.append(inst.get('stability', 0.5))
            feat.append(1.0 if 'offset' in inst else 0.0)
            feat.append(inst.get('offset', 0) / 2.0 + 0.5)

            sem = inst.get('semantic', 'LOOP')
            for s in semantic_types:
                feat.append(1.0 if sem == s else 0.0)

            bed = inst.get('bed', 'none')
            for b in bed_types:
                feat.append(1.0 if bed == b else 0.0)

            from_bed = inst.get('from_bed', 'none')
            for b in bed_types:
                feat.append(1.0 if from_bed == b else 0.0)

            to_bed = inst.get('to_bed', 'none')
            for b in bed_types:
                feat.append(1.0 if to_bed == b else 0.0)

            feat.append(1.0 if inst.get('variant', False) else 0.0)
            features.append(feat)

        features = torch.tensor(features, dtype=torch.float32)
        self.register_buffer('raw_features', features)
        self.raw_dim = features.shape[1]
        self.projector = nn.Sequential(
            nn.Linear(self.raw_dim, embed_dim), nn.SiLU(),
            nn.Linear(embed_dim, embed_dim),
        )

    def get_raw_features(self, class_ids):
        return self.raw_features[class_ids]

    def forward(self, class_ids):
        return self.projector(self.get_raw_features(class_ids))


class Stage3PhysicsAwareUNet(nn.Module):
    def __init__(self, json_path, num_classes=15, embed_dim=256, num_heads=8, patch_size=16):
        super().__init__()
        self.patch_size = patch_size
        self.physics_encoder = PhysicsFeatureEncoder(json_path, embed_dim)
        self.position_embedding = nn.Parameter(torch.randn(8, embed_dim) * 0.02)
        self.neighbor_self_attn = nn.MultiheadAttention(
            embed_dim=embed_dim, num_heads=num_heads, batch_first=True, dropout=0.1,
        )
        self.norm1 = nn.LayerNorm(embed_dim)
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=embed_dim, num_heads=num_heads, batch_first=True, dropout=0.1,
        )
        self.norm2 = nn.LayerNorm(embed_dim)
        self.fusion = nn.Sequential(
            nn.LayerNorm(embed_dim * 2),
            nn.Linear(embed_dim * 2, embed_dim * 2), nn.SiLU(), nn.Dropout(0.1),
            nn.Linear(embed_dim * 2, embed_dim),
        )
        self.physics_pred_head = nn.Sequential(
            nn.LayerNorm(embed_dim),
            nn.Linear(embed_dim, embed_dim), nn.SiLU(),
            nn.Linear(embed_dim, self.physics_encoder.raw_dim),
        )
        self.unet = UNetModel(
            dim=(3, patch_size, patch_size), num_channels=128, num_res_blocks=3,
            channel_mult=(1, 2, 2), class_cond=False, num_classes=None,
            attention_resolutions='8,4', num_heads=num_heads, num_head_channels=32, dropout=0.1,
        )
        time_embed_dim = 128 * 4
        self.cond_to_time = nn.Sequential(
            nn.Linear(embed_dim, time_embed_dim), nn.SiLU(),
            nn.Linear(time_embed_dim, time_embed_dim),
        )
        self.cond_to_spatial = nn.Sequential(nn.Linear(embed_dim, patch_size * patch_size), nn.SiLU())
        self.spatial_fusion = nn.Conv2d(4, 3, kernel_size=1)

    def forward(self, x, t, neighbor_ids, neighbor_mask, return_aux=False):
        center_id = neighbor_ids[:, 1, 1]
        NP = [(0,0), (0,1), (0,2), (1,0), (1,2), (2,0), (2,1), (2,2)]
        neighbors = torch.stack([neighbor_ids[:, r, c] for r, c in NP], dim=1)
        neighbors_mask = torch.stack([neighbor_mask[:, r, c] for r, c in NP], dim=1)

        center_feat = self.physics_encoder(center_id)
        neighbor_feat = self.physics_encoder(neighbors) + self.position_embedding.unsqueeze(0)
        attn_mask = ~neighbors_mask

        attn_out, _ = self.neighbor_self_attn(
            neighbor_feat, neighbor_feat, neighbor_feat, key_padding_mask=attn_mask,
        )
        neighbor_feat = self.norm1(neighbor_feat + attn_out)

        attended, _ = self.cross_attention(
            center_feat.unsqueeze(1), neighbor_feat, neighbor_feat, key_padding_mask=attn_mask,
        )
        attended = self.norm2(center_feat + attended.squeeze(1))

        cond = self.fusion(torch.cat([center_feat, attended], dim=-1))

        physics_pred = self.physics_pred_head(cond)
        physics_target = self.physics_encoder.get_raw_features(center_id)

        cond_embed = self.cond_to_time(cond)
        B = x.shape[0]
        cond_spatial = self.cond_to_spatial(cond).view(B, 1, self.patch_size, self.patch_size)
        x_aug = self.spatial_fusion(torch.cat([x, cond_spatial], dim=1))
        vt = self._unet_forward_with_cond(x_aug, t, cond_embed)

        if return_aux:
            return vt, {'physics_pred': physics_pred, 'physics_target': physics_target}
        return vt

    def _unet_forward_with_cond(self, x, t, cond_embed):
        from torchcfm.models.unet.nn import timestep_embedding
        unet = self.unet
        emb = unet.time_embed(timestep_embedding(t, unet.model_channels)) + cond_embed
        h = x.type(unet.dtype)
        hs = []
        for module in unet.input_blocks:
            h = module(h, emb)
            hs.append(h)
        h = unet.middle_block(h, emb)
        for module in unet.output_blocks:
            h = torch.cat([h, hs.pop()], dim=1)
            h = module(h, emb)
        return unet.out(h.type(x.dtype))


# ══════════════════════════════════════════════════════════════════
# Stage 4：自适应 Stochastic Interpolants
# ══════════════════════════════════════════════════════════════════

class AdaptiveFlowMatcher:
    """
    像素级自适应 sigma
    - patch 内部区域：sigma_inner（更确定）
    - patch 边界区域：sigma_boundary（更随机，允许自然过渡）
    """

    def __init__(self, sigma_inner=0.005, sigma_boundary=0.06, band_width=3, patch_size=16):
        self.sigma_inner = sigma_inner
        self.sigma_boundary = sigma_boundary
        self.band_width = band_width
        self.patch_size = patch_size

    def compute_boundary_map(self, neighbor_ids):
        B = neighbor_ids.shape[0]
        device = neighbor_ids.device
        bw = self.band_width

        center_id = neighbor_ids[:, 1, 1]
        boundary_map = torch.zeros(B, 1, self.patch_size, self.patch_size, device=device)

        top_diff = (neighbor_ids[:, 0, 1] != center_id).float().view(B, 1, 1, 1)
        bottom_diff = (neighbor_ids[:, 2, 1] != center_id).float().view(B, 1, 1, 1)
        left_diff = (neighbor_ids[:, 1, 0] != center_id).float().view(B, 1, 1, 1)
        right_diff = (neighbor_ids[:, 1, 2] != center_id).float().view(B, 1, 1, 1)

        tl_diff = ((neighbor_ids[:, 0, 0] != center_id) |
                   (neighbor_ids[:, 0, 1] != center_id) |
                   (neighbor_ids[:, 1, 0] != center_id)).float().view(B, 1, 1, 1)
        tr_diff = ((neighbor_ids[:, 0, 2] != center_id) |
                   (neighbor_ids[:, 0, 1] != center_id) |
                   (neighbor_ids[:, 1, 2] != center_id)).float().view(B, 1, 1, 1)
        bl_diff = ((neighbor_ids[:, 2, 0] != center_id) |
                   (neighbor_ids[:, 2, 1] != center_id) |
                   (neighbor_ids[:, 1, 0] != center_id)).float().view(B, 1, 1, 1)
        br_diff = ((neighbor_ids[:, 2, 2] != center_id) |
                   (neighbor_ids[:, 2, 1] != center_id) |
                   (neighbor_ids[:, 1, 2] != center_id)).float().view(B, 1, 1, 1)

        boundary_map[:, :, :bw,  :] = torch.maximum(boundary_map[:, :, :bw,  :], top_diff)
        boundary_map[:, :, -bw:, :] = torch.maximum(boundary_map[:, :, -bw:, :], bottom_diff)
        boundary_map[:, :, :, :bw]  = torch.maximum(boundary_map[:, :, :, :bw], left_diff)
        boundary_map[:, :, :, -bw:] = torch.maximum(boundary_map[:, :, :, -bw:], right_diff)

        boundary_map[:, :, :bw,  :bw]  = torch.maximum(boundary_map[:, :, :bw,  :bw], tl_diff)
        boundary_map[:, :, :bw,  -bw:] = torch.maximum(boundary_map[:, :, :bw,  -bw:], tr_diff)
        boundary_map[:, :, -bw:, :bw]  = torch.maximum(boundary_map[:, :, -bw:, :bw], bl_diff)
        boundary_map[:, :, -bw:, -bw:] = torch.maximum(boundary_map[:, :, -bw:, -bw:], br_diff)

        boundary_map = F.avg_pool2d(boundary_map, kernel_size=3, stride=1, padding=1)
        return boundary_map.clamp(0.0, 1.0)

    def sample_location_and_conditional_flow(self, x0, x1, neighbor_ids=None):
        B = x0.shape[0]
        device = x0.device

        t = torch.rand(B, device=device)
        t_expand = t.view(B, 1, 1, 1)

        if neighbor_ids is not None:
            boundary_map = self.compute_boundary_map(neighbor_ids)
        else:
            boundary_map = torch.zeros(B, 1, self.patch_size, self.patch_size, device=device)

        sigma_map = self.sigma_inner + (self.sigma_boundary - self.sigma_inner) * boundary_map
        noise = torch.randn_like(x0)
        std = sigma_map * torch.sqrt(t_expand * (1 - t_expand) + 1e-8)

        xt = (1 - t_expand) * x0 + t_expand * x1 + std * noise
        ut = x1 - x0

        return t, xt, ut


class Stage4AdaptiveSIUNet(nn.Module):
    """Stage 4：最终结构感知模型，物理特征编码 + 自适应 SI"""

    def __init__(self, json_path, num_classes=15, embed_dim=256, num_heads=8, patch_size=16):
        super().__init__()
        self.patch_size = patch_size
        self.physics_encoder = PhysicsFeatureEncoder(json_path, embed_dim)
        self.position_embedding = nn.Parameter(torch.randn(8, embed_dim) * 0.02)
        self.neighbor_self_attn = nn.MultiheadAttention(
            embed_dim=embed_dim, num_heads=num_heads, batch_first=True, dropout=0.1,
        )
        self.norm1 = nn.LayerNorm(embed_dim)
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=embed_dim, num_heads=num_heads, batch_first=True, dropout=0.1,
        )
        self.norm2 = nn.LayerNorm(embed_dim)
        self.fusion = nn.Sequential(
            nn.LayerNorm(embed_dim * 2),
            nn.Linear(embed_dim * 2, embed_dim * 2), nn.SiLU(), nn.Dropout(0.1),
            nn.Linear(embed_dim * 2, embed_dim),
        )
        self.physics_pred_head = nn.Sequential(
            nn.LayerNorm(embed_dim),
            nn.Linear(embed_dim, embed_dim), nn.SiLU(),
            nn.Linear(embed_dim, self.physics_encoder.raw_dim),
        )
        self.unet = UNetModel(
            dim=(3, patch_size, patch_size), num_channels=128, num_res_blocks=3,
            channel_mult=(1, 2, 2), class_cond=False, num_classes=None,
            attention_resolutions='8,4', num_heads=num_heads, num_head_channels=32, dropout=0.1,
        )
        time_embed_dim = 128 * 4
        self.cond_to_time = nn.Sequential(
            nn.Linear(embed_dim, time_embed_dim), nn.SiLU(),
            nn.Linear(time_embed_dim, time_embed_dim),
        )
        self.cond_to_spatial = nn.Sequential(nn.Linear(embed_dim, patch_size * patch_size), nn.SiLU())
        self.spatial_fusion = nn.Conv2d(4, 3, kernel_size=1)

    def forward(self, x, t, neighbor_ids, neighbor_mask, return_aux=False):
        center_id = neighbor_ids[:, 1, 1]
        NP = [(0,0), (0,1), (0,2), (1,0), (1,2), (2,0), (2,1), (2,2)]
        neighbors = torch.stack([neighbor_ids[:, r, c] for r, c in NP], dim=1)
        neighbors_mask = torch.stack([neighbor_mask[:, r, c] for r, c in NP], dim=1)

        center_feat = self.physics_encoder(center_id)
        neighbor_feat = self.physics_encoder(neighbors) + self.position_embedding.unsqueeze(0)
        attn_mask = ~neighbors_mask

        attn_out, _ = self.neighbor_self_attn(
            neighbor_feat, neighbor_feat, neighbor_feat, key_padding_mask=attn_mask,
        )
        neighbor_feat = self.norm1(neighbor_feat + attn_out)

        attended, _ = self.cross_attention(
            center_feat.unsqueeze(1), neighbor_feat, neighbor_feat, key_padding_mask=attn_mask,
        )
        attended = self.norm2(center_feat + attended.squeeze(1))

        cond = self.fusion(torch.cat([center_feat, attended], dim=-1))

        physics_pred = self.physics_pred_head(cond)
        physics_target = self.physics_encoder.get_raw_features(center_id)

        cond_embed = self.cond_to_time(cond)
        B = x.shape[0]
        cond_spatial = self.cond_to_spatial(cond).view(B, 1, self.patch_size, self.patch_size)
        x_aug = self.spatial_fusion(torch.cat([x, cond_spatial], dim=1))
        vt = self._unet_forward_with_cond(x_aug, t, cond_embed)

        if return_aux:
            return vt, {'physics_pred': physics_pred, 'physics_target': physics_target}
        return vt

    def _unet_forward_with_cond(self, x, t, cond_embed):
        from torchcfm.models.unet.nn import timestep_embedding
        unet = self.unet
        emb = unet.time_embed(timestep_embedding(t, unet.model_channels)) + cond_embed
        h = x.type(unet.dtype)
        hs = []
        for module in unet.input_blocks:
            h = module(h, emb)
            hs.append(h)
        h = unet.middle_block(h, emb)
        for module in unet.output_blocks:
            h = torch.cat([h, hs.pop()], dim=1)
            h = module(h, emb)
        return unet.out(h.type(x.dtype))


# ══════════════════════════════════════════════════════════════════
# 数据加载（DDP版）
# ══════════════════════════════════════════════════════════════════

class DistributedWeightedSampler(torch.utils.data.Sampler):
    def __init__(self, weights, num_samples, num_replicas, rank,
                 replacement=True, seed=0):
        self.weights = torch.as_tensor(weights, dtype=torch.float)
        self.num_samples_total = num_samples
        self.num_replicas = num_replicas
        self.rank = rank
        self.replacement = replacement
        self.seed = seed
        self.epoch = 0
        self.num_samples = num_samples // num_replicas

    def __iter__(self):
        g = torch.Generator()
        g.manual_seed(self.seed + self.epoch)
        all_idx = torch.multinomial(
            self.weights, self.num_samples_total,
            replacement=self.replacement, generator=g,
        ).tolist()
        return iter(all_idx[self.rank::self.num_replicas][:self.num_samples])

    def __len__(self):
        return self.num_samples

    def set_epoch(self, epoch):
        self.epoch = epoch


def get_ddp_dataloaders(processed_dir, batch_size, num_workers,
                        world_size, rank,
                        use_weighted_sampling=True,
                        sampling_strategy='three_tier',
                        expected_patch_size=None,
                        load_to_memory=False):
    h5_path = os.path.join(processed_dir, 'dataset.h5')
    if not os.path.exists(h5_path):
        raise FileNotFoundError(f"找不到HDF5：{h5_path}")

    train_dataset = KnittingWindowDataset(
        h5_path,
        'train',
        load_to_memory=load_to_memory,
        expected_patch_size=expected_patch_size,
    )
    val_dataset = KnittingWindowDataset(
        h5_path,
        'val',
        load_to_memory=load_to_memory,
        expected_patch_size=expected_patch_size,
    )

    if use_weighted_sampling:
        weights = train_dataset.get_sample_weights(sampling_strategy)
        train_sampler = DistributedWeightedSampler(
            weights=weights, num_samples=len(train_dataset),
            num_replicas=world_size, rank=rank,
        )
    else:
        train_sampler = DistributedSampler(
            train_dataset, num_replicas=world_size, rank=rank, shuffle=True,
        )

    val_sampler = DistributedSampler(
        val_dataset, num_replicas=world_size, rank=rank, shuffle=False,
    )

    kw = dict(
        pin_memory=True,
        persistent_workers=(num_workers > 0),
        worker_init_fn=worker_init_fn,
    )
    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, sampler=train_sampler,
        num_workers=num_workers, drop_last=True, **kw,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=batch_size, sampler=val_sampler,
        num_workers=num_workers, drop_last=False, **kw,
    )
    return train_loader, val_loader, train_sampler


# ══════════════════════════════════════════════════════════════════
# 预训练权重加载
# ══════════════════════════════════════════════════════════════════

def load_pretrained_weights(model, pretrained_path, is_main=True):
    """
    跨 stage 热启动：
    - Stage2 → Stage3/4：conditioner.* 重映射为顶层模块名
    - Stage3 → Stage4：key 名完全一致，直接加载
    形状不匹配的参数会自动跳过
    """
    if not os.path.exists(pretrained_path):
        if is_main:
            print(f"⚠️  预训练路径不存在，跳过: {pretrained_path}")
        return

    ckpt = torch.load(pretrained_path, map_location='cpu', weights_only=False)
    src_state = ckpt['model_state']

    remap_prefixes = [
        ('conditioner.position_embedding', 'position_embedding'),
        ('conditioner.neighbor_self_attn.', 'neighbor_self_attn.'),
        ('conditioner.norm1.',              'norm1.'),
        ('conditioner.cross_attention.',    'cross_attention.'),
        ('conditioner.norm2.',              'norm2.'),
        ('conditioner.fusion.',             'fusion.'),
    ]

    remapped = {}
    for k, v in src_state.items():
        new_k = k
        for old_prefix, new_prefix in remap_prefixes:
            if k.startswith(old_prefix):
                new_k = new_prefix + k[len(old_prefix):]
                break
        remapped[new_k] = v

    model_state = model.state_dict()
    loadable = {
        k: v for k, v in remapped.items()
        if k in model_state and model_state[k].shape == v.shape
    }
    skipped = [k for k in model_state if k not in loadable]

    model_state.update(loadable)
    model.load_state_dict(model_state, strict=False)

    if is_main:
        print(f"已加载预训练权重: {pretrained_path}")
        print(f"  成功加载: {len(loadable)} / {len(model_state)}")
        if skipped:
            print(f"  跳过（新增/不匹配）: {len(skipped)}")
            for s in skipped[:10]:
                print(f"    - {s}")
            if len(skipped) > 10:
                print(f"    ... 还有 {len(skipped) - 10} 个")


# ══════════════════════════════════════════════════════════════════
# 验证
# ══════════════════════════════════════════════════════════════════

def validate(model, fm, val_loader, device,
             grad_loss_fn, fft_loss_fn, boundary_loss_fn, structure_loss_fn, texture_loss_fn,
             mse_weight, l1_weight, grad_weight, fft_weight,
             physics_weight, boundary_weight, structure_weight, texture_weight, stage):
    model.eval()
    total_loss = 0.0
    n_batches = 0

    with torch.no_grad():
        for batch in val_loader:
            center_sim = batch['center_sim'].to(device, non_blocking=True)
            neighbor_ids = batch['neighbor_ids'].to(device, non_blocking=True)
            neighbor_mask = batch['neighbor_mask'].to(device, non_blocking=True)

            x0 = torch.randn_like(center_sim)
            x1 = center_sim

            if stage == 4:
                t, xt, ut = fm.sample_location_and_conditional_flow(x0, x1, neighbor_ids)
            else:
                t, xt, ut = fm.sample_location_and_conditional_flow(x0, x1)

            if stage == 1:
                center_id = neighbor_ids[:, 1, 1]
                vt = model(xt, t, center_id)
                aux = None
            elif stage in (3, 4):
                vt, aux = model(xt, t, neighbor_ids, neighbor_mask, return_aux=True)
            else:
                vt = model(xt, t, neighbor_ids, neighbor_mask)
                aux = None

            loss_mse = torch.mean((vt - ut) ** 2)
            loss_l1 = torch.mean(torch.abs(vt - ut))

            if stage == 1:
                loss = mse_weight * loss_mse + l1_weight * loss_l1
            else:
                t_expand = t.view(-1, 1, 1, 1)
                x1_pred = torch.clamp(xt + (1 - t_expand) * vt, -1, 1)

                loss_grad = grad_loss_fn(x1_pred, x1)
                loss_fft = fft_loss_fn(x1_pred, x1)

                loss = (mse_weight * loss_mse +
                        l1_weight  * loss_l1 +
                        grad_weight * loss_grad +
                        fft_weight  * loss_fft)

                if aux is not None and physics_weight > 0:
                    loss_physics = F.smooth_l1_loss(
                        aux['physics_pred'], aux['physics_target']
                    )
                    loss = loss + physics_weight * loss_physics

                if stage == 4 and boundary_weight > 0:
                    loss_boundary = boundary_loss_fn(x1_pred, x1, neighbor_ids)
                    loss = loss + boundary_weight * loss_boundary

                if stage == 4 and structure_weight > 0:
                    loss_struct, _ = structure_loss_fn(x1_pred, x1)
                    loss = loss + structure_weight * loss_struct

                if stage == 4 and texture_weight > 0:
                    loss_texture = texture_loss_fn(x1_pred, x1)
                    loss = loss + texture_weight * loss_texture

            total_loss += loss.item()
            n_batches += 1

    return total_loss / n_batches


# ══════════════════════════════════════════════════════════════════
# 训练主函数
# ══════════════════════════════════════════════════════════════════

def train(config):
    local_rank, world_size, is_ddp = setup_ddp()
    is_main = is_main_process(local_rank)
    device = torch.device(
        f'cuda:{local_rank}' if torch.cuda.is_available() else 'cpu'
    )

    stage = config.get('stage', 2)
    patch_size = int(config['data'].get('patch_size', config['train'].get('patch_size', 16)))

    if is_main:
        print("=" * 60)
        print(f"Stage:      {stage}")
        print(f"Patch Size: {patch_size}")
        print(f"训练模式：  {'DDP' if is_ddp else '单进程'}")
        print(f"World Size: {world_size}")
        if torch.cuda.is_available():
            print(f"GPU:        {torch.cuda.get_device_name(local_rank)}")
        print("=" * 60)

    # ── 数据 ──────────────────────────────────────────────────────
    train_loader, val_loader, train_sampler = get_ddp_dataloaders(
        processed_dir=config['data']['processed_dir'],
        batch_size=config['train']['batch_size'],
        num_workers=config['train']['num_workers'],
        world_size=world_size, rank=local_rank,
        use_weighted_sampling=config['data'].get('use_weighted_sampling', True),
        sampling_strategy=config['data'].get('sampling_strategy', 'three_tier'),
        expected_patch_size=patch_size,
        load_to_memory=config['data'].get('load_to_memory', False),
    )

    # ── 模型 ──────────────────────────────────────────────────────
    json_path = config['data'].get('json_path', 'assets/instructions.json')

    if stage == 1:
        model = Stage1ConditionedUNet(num_classes=15, patch_size=patch_size).to(device)
    elif stage == 2:
        model = Stage2NeighborAwareUNet(
            num_classes=15, embed_dim=256, num_heads=8, patch_size=patch_size
        ).to(device)
    elif stage == 3:
        model = Stage3PhysicsAwareUNet(
            json_path=json_path, num_classes=15, embed_dim=256, num_heads=8,
            patch_size=patch_size,
        ).to(device)
    elif stage == 4:
        model = Stage4AdaptiveSIUNet(
            json_path=json_path, num_classes=15, embed_dim=256, num_heads=8,
            patch_size=patch_size,
        ).to(device)
    else:
        raise ValueError(f"未知 stage: {stage}")

    # ── 预训练权重 ────────────────────────────────────────────────
    pretrained_path = config['train'].get('pretrained_path', None)
    if pretrained_path:
        load_pretrained_weights(model, pretrained_path, is_main=is_main)

    if is_ddp:
        model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)

    if is_main:
        raw_model = model.module if is_ddp else model
        n_params = sum(p.numel() for p in raw_model.parameters())
        print(f"模型参数量：{n_params / 1e6:.2f}M")

    # ── Flow Matcher ──────────────────────────────────────────────
    if stage == 4:
        fm = AdaptiveFlowMatcher(
            sigma_inner=config['train'].get('sigma_inner', 0.005),
            sigma_boundary=config['train'].get('sigma_boundary', 0.06),
            band_width=config['train'].get('boundary_band_width', 3),
            patch_size=patch_size,
        )
    else:
        fm = ConditionalFlowMatcher(sigma=0.1)

    # ── 损失函数 ──────────────────────────────────────────────────
    grad_loss_fn = GradientLoss().to(device)
    fft_loss_fn = FFTLoss().to(device)
    boundary_loss_fn = BoundaryLoss(
        band_width=config['train'].get('boundary_band_width', 3),
        patch_size=patch_size,
    ).to(device)
    texture_loss_fn = TextureContrastLoss(
        gamma=config['train'].get('texture_gamma', 2.0),
    ).to(device)

    structure_loss_fn = ContextAwareStructureLoss(
        mask_k=config['train'].get('structure_mask_k', 0.60),
        mask_temp=config['train'].get('structure_mask_temp', 0.03),
        low_margin=config['train'].get('structure_low_margin', 0.015),
        low_allow_scale=config['train'].get('structure_low_allow_scale', 0.50),
        low_ratio=config['train'].get('structure_low_ratio', 0.75),
        directional_ratio=config['train'].get('structure_directional_ratio', 0.0),
    ).to(device)

    # ── 优化器 & 调度器 ───────────────────────────────────────────
    optimizer = Adam(model.parameters(), lr=config['train']['lr'])
    warmup_epochs = config['train'].get('warmup_epochs', 5)
    total_epochs = config['train']['epochs']

    def lr_lambda(epoch):
        if epoch < warmup_epochs:
            return (epoch + 1) / warmup_epochs
        progress = (epoch - warmup_epochs) / max(total_epochs - warmup_epochs, 1)
        return 0.5 * (1 + np.cos(np.pi * progress))

    scheduler = LambdaLR(optimizer, lr_lambda)

    # ── 损失权重 ──────────────────────────────────────────────────
    mse_weight = config['train'].get('mse_weight', 1.0)
    l1_weight = config['train'].get('l1_weight', 0.1)
    grad_weight = config['train'].get('grad_weight', 0.05)
    fft_weight = config['train'].get('fft_weight', 0.05)
    physics_weight = config['train'].get('physics_weight', 0.0)
    boundary_weight = config['train'].get('boundary_weight', 0.0)
    structure_weight = config['train'].get('structure_weight', 0.0)
    texture_weight = config['train'].get('texture_weight', 0.0)

    if is_main:
        if physics_weight > 0:
            print(f"物理一致性损失权重: {physics_weight}")
        if boundary_weight > 0:
            print(f"边界损失权重:       {boundary_weight}")
        if structure_weight > 0:
            print(f"结构复合损失权重:   {structure_weight}")
            print(f"  structure_low_ratio:         {config['train'].get('structure_low_ratio', 0.75)}")
            print(f"  structure_directional_ratio: {config['train'].get('structure_directional_ratio', 0.0)}")
            print(f"  structure_mask_k:            {config['train'].get('structure_mask_k', 0.60)}")
            print(f"  structure_mask_temp:         {config['train'].get('structure_mask_temp', 0.03)}")
            print(f"  structure_low_margin:        {config['train'].get('structure_low_margin', 0.015)}")
            print(f"  structure_low_allow_scale:   {config['train'].get('structure_low_allow_scale', 0.50)}")
        if texture_weight > 0:
            print(f"纹理对比损失权重:   {texture_weight}")
            print(f"  texture_gamma:              {config['train'].get('texture_gamma', 2.0)}")

    # ── Checkpoint 目录 ───────────────────────────────────────────
    ckpt_dir = config['train']['checkpoint_dir']
    if is_main:
        os.makedirs(ckpt_dir, exist_ok=True)

    best_val_loss = float('inf')
    log_every = int(config['train'].get('log_every', 100))

    # ══════════════════════════════════════════════════════════════
    # 训练循环
    # ══════════════════════════════════════════════════════════════
    for epoch in range(total_epochs):

        if is_ddp and hasattr(train_sampler, 'set_epoch'):
            train_sampler.set_epoch(epoch)

        model.train()

        total_loss = total_mse = total_l1 = total_grad = 0.0
        total_fft = total_physics = total_boundary = 0.0
        total_struct = total_struct_ridge = total_struct_low = total_struct_dir = 0.0
        total_texture = 0.0
        n_batches = 0
        if is_main:
            print(f"\nEpoch [{epoch+1:3d}/{total_epochs}] start, steps/rank={len(train_loader)}", flush=True)

        for batch in train_loader:
            if is_main and n_batches == 0:
                print("  first batch loaded", flush=True)

            center_sim = batch['center_sim'].to(device, non_blocking=True)
            neighbor_ids = batch['neighbor_ids'].to(device, non_blocking=True)
            neighbor_mask = batch['neighbor_mask'].to(device, non_blocking=True)

            x0 = torch.randn_like(center_sim)
            x1 = center_sim

            if stage == 4:
                t, xt, ut = fm.sample_location_and_conditional_flow(x0, x1, neighbor_ids)
            else:
                t, xt, ut = fm.sample_location_and_conditional_flow(x0, x1)

            # ── forward ───────────────────────────────────────
            if stage == 1:
                center_id = neighbor_ids[:, 1, 1]
                vt = model(xt, t, center_id)
                aux = None
            elif stage in (3, 4):
                vt, aux = model(xt, t, neighbor_ids, neighbor_mask, return_aux=True)
            else:
                vt = model(xt, t, neighbor_ids, neighbor_mask)
                aux = None

            # ── loss ──────────────────────────────────────────
            loss_mse = torch.mean((vt - ut) ** 2)
            loss_l1 = torch.mean(torch.abs(vt - ut))

            if stage == 1:
                loss = mse_weight * loss_mse + l1_weight * loss_l1
                loss_grad = torch.tensor(0.0, device=device)
                loss_fft = torch.tensor(0.0, device=device)
                loss_physics = torch.tensor(0.0, device=device)
                loss_boundary = torch.tensor(0.0, device=device)
                loss_struct = torch.tensor(0.0, device=device)
                loss_struct_ridge = torch.tensor(0.0, device=device)
                loss_struct_low = torch.tensor(0.0, device=device)
                loss_struct_dir = torch.tensor(0.0, device=device)
                loss_texture = torch.tensor(0.0, device=device)

            else:
                t_expand = t.view(-1, 1, 1, 1)
                x1_pred = torch.clamp(xt + (1 - t_expand) * vt, -1, 1)

                loss_grad = grad_loss_fn(x1_pred, x1)
                loss_fft = fft_loss_fn(x1_pred, x1)

                loss = (mse_weight * loss_mse +
                        l1_weight * loss_l1 +
                        grad_weight * loss_grad +
                        fft_weight * loss_fft)

                if aux is not None and physics_weight > 0:
                    loss_physics = F.smooth_l1_loss(
                        aux['physics_pred'], aux['physics_target']
                    )
                    loss = loss + physics_weight * loss_physics
                else:
                    loss_physics = torch.tensor(0.0, device=device)

                if stage == 4 and boundary_weight > 0:
                    loss_boundary = boundary_loss_fn(x1_pred, x1, neighbor_ids)
                    loss = loss + boundary_weight * loss_boundary
                else:
                    loss_boundary = torch.tensor(0.0, device=device)

                if stage == 4 and structure_weight > 0:
                    loss_struct, struct_stats = structure_loss_fn(x1_pred, x1)
                    loss = loss + structure_weight * loss_struct
                    loss_struct_ridge = struct_stats['ridge']
                    loss_struct_low = struct_stats['low']
                    loss_struct_dir = struct_stats['dir']
                else:
                    loss_struct = torch.tensor(0.0, device=device)
                    loss_struct_ridge = torch.tensor(0.0, device=device)
                    loss_struct_low = torch.tensor(0.0, device=device)
                    loss_struct_dir = torch.tensor(0.0, device=device)

                if stage == 4 and texture_weight > 0:
                    loss_texture = texture_loss_fn(x1_pred, x1)
                    loss = loss + texture_weight * loss_texture
                else:
                    loss_texture = torch.tensor(0.0, device=device)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            total_mse += loss_mse.item()
            total_l1 += loss_l1.item()
            total_grad += loss_grad.item()
            total_fft += loss_fft.item()
            total_physics += loss_physics.item()
            total_boundary += loss_boundary.item()
            total_struct += loss_struct.item()
            total_struct_ridge += loss_struct_ridge.item()
            total_struct_low += loss_struct_low.item()
            total_struct_dir += loss_struct_dir.item()
            total_texture += loss_texture.item()
            n_batches += 1
            if is_main and log_every > 0 and n_batches % log_every == 0:
                print(
                    f"  step [{n_batches:5d}/{len(train_loader)}] "
                    f"loss={total_loss / n_batches:.4f}",
                    flush=True,
                )

        # ── 跨卡平均 ──────────────────────────────────────────
        avg_loss = reduce_loss(total_loss / n_batches, world_size)
        avg_mse = reduce_loss(total_mse / n_batches, world_size)
        avg_l1 = reduce_loss(total_l1 / n_batches, world_size)
        avg_grad = reduce_loss(total_grad / n_batches, world_size)
        avg_fft = reduce_loss(total_fft / n_batches, world_size)
        avg_physics = reduce_loss(total_physics / n_batches, world_size)
        avg_boundary = reduce_loss(total_boundary / n_batches, world_size)
        avg_struct = reduce_loss(total_struct / n_batches, world_size)
        avg_struct_ridge = reduce_loss(total_struct_ridge / n_batches, world_size)
        avg_struct_low = reduce_loss(total_struct_low / n_batches, world_size)
        avg_struct_dir = reduce_loss(total_struct_dir / n_batches, world_size)
        avg_texture = reduce_loss(total_texture / n_batches, world_size)
        scheduler.step()

        # ── 验证 ──────────────────────────────────────────────
        if (epoch + 1) % config['train']['val_every'] == 0:
            val_loss = validate(
                model, fm, val_loader, device,
                grad_loss_fn, fft_loss_fn, boundary_loss_fn, structure_loss_fn,
                texture_loss_fn,
                mse_weight, l1_weight, grad_weight, fft_weight,
                physics_weight, boundary_weight, structure_weight, texture_weight, stage,
            )
            val_loss = reduce_loss(val_loss, world_size)

            if is_main:
                lr_now = scheduler.get_last_lr()[0]

                if stage == 1:
                    print(
                        f"Epoch [{epoch+1:3d}/{total_epochs}] "
                        f"Loss: {avg_loss:.4f} "
                        f"(MSE: {avg_mse:.4f}, L1: {avg_l1:.4f})  "
                        f"Val: {val_loss:.4f}  LR: {lr_now:.2e}"
                    )

                elif stage == 4 and structure_weight > 0:
                    print(
                        f"Epoch [{epoch+1:3d}/{total_epochs}] "
                        f"Loss: {avg_loss:.4f} "
                        f"(MSE: {avg_mse:.4f}, L1: {avg_l1:.4f}, "
                        f"Grad: {avg_grad:.4f}, FFT: {avg_fft:.4f}, "
                        f"Phys: {avg_physics:.4f}, Bound: {avg_boundary:.4f}, "
                        f"Struct: {avg_struct:.4f}, "
                        f"Ridge: {avg_struct_ridge:.4f}, Low: {avg_struct_low:.4f}, "
                        f"Dir: {avg_struct_dir:.4f}, Tex: {avg_texture:.4f})  "
                        f"Val: {val_loss:.4f}  LR: {lr_now:.2e}"
                    )

                elif stage == 4:
                    print(
                        f"Epoch [{epoch+1:3d}/{total_epochs}] "
                        f"Loss: {avg_loss:.4f} "
                        f"(MSE: {avg_mse:.4f}, L1: {avg_l1:.4f}, "
                        f"Grad: {avg_grad:.4f}, FFT: {avg_fft:.4f}, "
                        f"Phys: {avg_physics:.4f}, Bound: {avg_boundary:.4f}, Tex: {avg_texture:.4f})  "
                        f"Val: {val_loss:.4f}  LR: {lr_now:.2e}"
                    )

                elif physics_weight > 0:
                    print(
                        f"Epoch [{epoch+1:3d}/{total_epochs}] "
                        f"Loss: {avg_loss:.4f} "
                        f"(MSE: {avg_mse:.4f}, L1: {avg_l1:.4f}, "
                        f"Grad: {avg_grad:.4f}, FFT: {avg_fft:.4f}, "
                        f"Phys: {avg_physics:.4f})  "
                        f"Val: {val_loss:.4f}  LR: {lr_now:.2e}"
                    )

                else:
                    print(
                        f"Epoch [{epoch+1:3d}/{total_epochs}] "
                        f"Loss: {avg_loss:.4f} "
                        f"(MSE: {avg_mse:.4f}, L1: {avg_l1:.4f}, "
                        f"Grad: {avg_grad:.4f}, FFT: {avg_fft:.4f})  "
                        f"Val: {val_loss:.4f}  LR: {lr_now:.2e}"
                    )

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    raw_model = model.module if is_ddp else model
                    torch.save({
                        'epoch': epoch + 1,
                        'stage': stage,
                        'patch_size': patch_size,
                        'model_state': raw_model.state_dict(),
                        'optimizer_state': optimizer.state_dict(),
                        'val_loss': val_loss,
                    }, os.path.join(ckpt_dir, 'best.pt'))
                    print(f"  → 已保存最优模型 val_loss={val_loss:.4f}")

        if is_main and (epoch + 1) % config['train']['save_every'] == 0:
            raw_model = model.module if is_ddp else model
            torch.save({
                'epoch': epoch + 1,
                'stage': stage,
                'patch_size': patch_size,
                'model_state': raw_model.state_dict(),
            }, os.path.join(ckpt_dir, f'epoch_{epoch+1:04d}.pt'))

        if is_ddp:
            dist.barrier()

    cleanup_ddp(is_ddp)
    if is_main:
        print("\n训练完成！")


# ══════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config', type=str, default=None,
        help='配置文件路径，如 configs/stage4.yaml'
    )
    args = parser.parse_args()

    config_path = args.config if args.config else \
        os.path.join(ROOT, 'configs', 'stage4.yaml')

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    train(config)
