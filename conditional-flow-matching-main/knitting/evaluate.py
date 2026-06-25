"""
knitting/evaluate.py
统一评估脚本：对所有 Stage 的 checkpoint 计算同一组指标

使用方式：
  # 评估所有 Stage
  python knitting/evaluate.py --all

  # 评估单个 Stage
  python knitting/evaluate.py --stage 2

依赖：
  pip install pytorch-msssim lpips
"""

import os
import sys
import json
import argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import torch
import torch.nn.functional as F
import numpy as np
from torch.utils.data import DataLoader

try:
    from pytorch_msssim import ssim as ssim_fn
    HAS_SSIM = True
except ImportError:
    HAS_SSIM = False
    print("⚠️  未安装 pytorch_msssim，SSIM/PSNR 将跳过")
    print("   pip install pytorch-msssim")

try:
    import lpips
    HAS_LPIPS = True
except Exception:
    # ImportError 或 RuntimeError（torchvision 版本不兼容）都跳过
    HAS_LPIPS = False
    print("⚠️  LPIPS 不可用（可能是 torchvision 版本不兼容），已跳过")

from data.dataset import KnittingWindowDataset, worker_init_fn


# ══════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════

def denormalize(x):
    """[-1,1] → [0,1]"""
    return (x + 1.0) / 2.0


def compute_psnr(pred, target):
    """pred, target: (B,C,H,W) 范围[0,1]，返回 batch 平均 PSNR"""
    mse  = torch.mean((pred - target) ** 2, dim=[1, 2, 3])
    mse  = torch.clamp(mse, min=1e-10)
    psnr = 10 * torch.log10(torch.ones_like(mse) / mse)
    return psnr.mean().item()


def load_model(stage, ckpt_path, device, json_path='assets/instructions.json'):
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)

    if stage == 1:
        from knitting.train import Stage1ConditionedUNet
        model = Stage1ConditionedUNet(num_classes=15)
    elif stage == 2:
        from knitting.train import Stage2NeighborAwareUNet
        model = Stage2NeighborAwareUNet(num_classes=15, embed_dim=256, num_heads=8)
    elif stage == 3:
        from knitting.train import Stage3PhysicsAwareUNet
        model = Stage3PhysicsAwareUNet(
            json_path=json_path, num_classes=15, embed_dim=256, num_heads=8
        )
    elif stage == 4:
        from knitting.train import Stage4AdaptiveSIUNet
        model = Stage4AdaptiveSIUNet(
            json_path=json_path, num_classes=15, embed_dim=256, num_heads=8
        )
    else:
        raise ValueError(f"未知 stage: {stage}")

    model.load_state_dict(ckpt['model_state'], strict=True)
    model.eval().to(device)

    epoch    = ckpt.get('epoch', 'N/A')
    val_loss = ckpt.get('val_loss', None)
    print(f"  ✅ Stage {stage} 加载完成: epoch={epoch}"
          + (f", val_loss={val_loss:.4f}" if val_loss else ""))
    return model


# ══════════════════════════════════════════════════════════════════
# 核心评估：用 Euler ODE 生成 x1 预测
# ══════════════════════════════════════════════════════════════════

@torch.no_grad()
def evaluate_stage(
    stage,
    ckpt_path,
    h5_path,
    device,
    json_path='assets/instructions.json',
    batch_size=128,
    num_workers=2,
    n_steps=50,           # 评估用较少步数加速
    max_batches=None,     # None=全量，调试时设小值
):
    """
    评估单个 Stage，返回统一指标字典。

    关键设计：
    - 所有 Stage 用相同的 Euler ODE（不用 torchdiffeq）
    - 所有 Stage 从相同的高斯噪声出发（固定 seed）
    - 所有 Stage 用相同的评估指标
    → 保证比较公平
    """
    print(f"\n{'='*55}")
    print(f"评估 Stage {stage}")
    print(f"Checkpoint: {ckpt_path}")
    print(f"ODE 步数:   {n_steps}")
    print(f"{'='*55}")

    model = load_model(stage, ckpt_path, device, json_path)

    val_dataset = KnittingWindowDataset(h5_path, split='val')
    val_loader  = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
        worker_init_fn=worker_init_fn,
    )

    # 初始化 LPIPS
    lpips_fn = None
    if HAS_LPIPS:
        lpips_fn = lpips.LPIPS(net='alex').to(device)
        lpips_fn.eval()

    # 累积统计
    metrics_sum   = defaultdict(float)
    per_class_mse = defaultdict(list)
    n_batches     = 0

    for batch_idx, batch in enumerate(val_loader):
        if max_batches is not None and batch_idx >= max_batches:
            break

        center_sim    = batch['center_sim'].to(device)
        neighbor_ids  = batch['neighbor_ids'].to(device)
        neighbor_mask = batch['neighbor_mask'].to(device)
        B = center_sim.shape[0]

        # ── 所有 Stage 统一使用独立高斯噪声 ──────────────────────
        torch.manual_seed(batch_idx)   # 固定 seed 保证可复现
        x = torch.randn_like(center_sim)

        # ── Euler ODE（所有 Stage 统一） ──────────────────────────
        dt = 1.0 / n_steps
        for i in range(n_steps):
            t_val = i / n_steps
            t     = torch.full((B,), t_val, device=device)

            if stage == 1:
                center_id = neighbor_ids[:, 1, 1]
                v = model(x, t, center_id)
            elif stage in (3, 4):
                v = model(x, t, neighbor_ids, neighbor_mask, return_aux=False)
            else:
                v = model(x, t, neighbor_ids, neighbor_mask)

            x = x + v * dt

        x1_pred = x.clamp(-1, 1)
        x1_true = center_sim

        # ── 转到 [0,1] ────────────────────────────────────────────
        pred_01 = denormalize(x1_pred).clamp(0, 1)
        true_01 = denormalize(x1_true).clamp(0, 1)

        # ── 1. MSE ────────────────────────────────────────────────
        mse = torch.mean((pred_01 - true_01) ** 2).item()
        metrics_sum['MSE'] += mse

        # ── 2. L1 ─────────────────────────────────────────────────
        l1 = torch.mean(torch.abs(pred_01 - true_01)).item()
        metrics_sum['L1'] += l1

        # ── 3. SSIM ───────────────────────────────────────────────
        if HAS_SSIM:
            ssim_val = ssim_fn(
                pred_01, true_01, data_range=1.0, size_average=True
            ).item()
            metrics_sum['SSIM'] += ssim_val

        # ── 4. PSNR ───────────────────────────────────────────────
        metrics_sum['PSNR'] += compute_psnr(pred_01, true_01)

        # ── 5. LPIPS ──────────────────────────────────────────────
        if HAS_LPIPS and lpips_fn is not None:
            lp = lpips_fn(
                x1_pred.clamp(-1, 1), x1_true.clamp(-1, 1)
            ).mean().item()
            metrics_sum['LPIPS'] += lp

        # ── 6. 每类别 MSE ─────────────────────────────────────────
        center_ids  = neighbor_ids[:, 1, 1].cpu().numpy()
        mse_per_smp = torch.mean(
            (pred_01 - true_01) ** 2, dim=[1, 2, 3]
        ).cpu().numpy()
        for cid, m in zip(center_ids, mse_per_smp):
            per_class_mse[int(cid)].append(float(m))

        n_batches += 1

        if batch_idx % 20 == 0:
            print(f"  进度: {batch_idx+1}/{len(val_loader)}")

    # ── 计算均值 ──────────────────────────────────────────────────
    metrics = {k: v / n_batches for k, v in metrics_sum.items()}
    metrics['per_class_MSE'] = {
        cid: float(np.mean(vals))
        for cid, vals in per_class_mse.items()
    }

    print(f"\nStage {stage} 结果：")
    print(f"  MSE:   {metrics.get('MSE',  float('nan')):.4f}")
    print(f"  L1:    {metrics.get('L1',   float('nan')):.4f}")
    if HAS_SSIM:
        print(f"  SSIM:  {metrics.get('SSIM', float('nan')):.4f}")
    print(f"  PSNR:  {metrics.get('PSNR', float('nan')):.2f} dB")
    if HAS_LPIPS:
        print(f"  LPIPS: {metrics.get('LPIPS',float('nan')):.4f}")

    return metrics


# ══════════════════════════════════════════════════════════════════
# 多 Stage 对比
# ══════════════════════════════════════════════════════════════════

def compare_all_stages(
    stage_configs,
    h5_path,
    device,
    output_dir='outputs/evaluation',
    json_path='assets/instructions.json',
    **kwargs,
):
    os.makedirs(output_dir, exist_ok=True)
    all_metrics = {}

    for stage_id, ckpt_path in stage_configs:
        if not os.path.exists(ckpt_path):
            print(f"⚠️  Stage {stage_id} checkpoint 不存在，跳过")
            continue
        metrics = evaluate_stage(
            stage=stage_id,
            ckpt_path=ckpt_path,
            h5_path=h5_path,
            device=device,
            json_path=json_path,
            **kwargs,
        )
        all_metrics[f'Stage {stage_id}'] = metrics

    if not all_metrics:
        print("❌ 没有可评估的 checkpoint")
        return

    # ── 打印对比表格 ──────────────────────────────────────────────
    keys = ['MSE', 'L1', 'SSIM', 'PSNR', 'LPIPS']
    print(f"\n{'='*65}")
    print("四阶段消融实验对比（统一评估协议）")
    print(f"{'='*65}")
    header = f"{'Stage':<12}" + "".join(f"{k:>10}" for k in keys)
    print(header)
    print("─" * 65)

    rows = {}
    for sname, metrics in all_metrics.items():
        row_data = {}
        row = f"{sname:<12}"
        for k in keys:
            v = metrics.get(k, float('nan'))
            row_data[k] = v
            if k == 'PSNR':
                row += f"{v:>10.2f}"
            else:
                row += f"{v:>10.4f}"
        rows[sname] = row_data
        print(row)
    print(f"{'='*65}")

    # ── 相对 Stage 1 的改进 ───────────────────────────────────────
    if 'Stage 1' in rows and len(rows) > 1:
        print("\n相对 Stage 1 的改进：")
        baseline = rows['Stage 1']
        for sname, row_data in rows.items():
            if sname == 'Stage 1':
                continue
            parts = []
            for k in ['MSE', 'L1', 'LPIPS']:
                bv = baseline.get(k, float('nan'))
                cv = row_data.get(k, float('nan'))
                if not (np.isnan(bv) or np.isnan(cv)) and bv > 1e-8:
                    pct = (bv - cv) / bv * 100
                    parts.append(f"{k}: {pct:+.1f}%")
            for k in ['SSIM']:
                bv = baseline.get(k, float('nan'))
                cv = row_data.get(k, float('nan'))
                if not (np.isnan(bv) or np.isnan(cv)):
                    parts.append(f"{k}: +{cv-bv:.4f}")
            for k in ['PSNR']:
                bv = baseline.get(k, float('nan'))
                cv = row_data.get(k, float('nan'))
                if not (np.isnan(bv) or np.isnan(cv)):
                    parts.append(f"{k}: +{cv-bv:.2f}dB")
            print(f"  {sname}: {', '.join(parts)}")

    # ── 保存结果 ──────────────────────────────────────────────────
    save_metrics    = {}
    per_class_all   = {}
    for sname, metrics in all_metrics.items():
        save_metrics[sname] = {
            k: v for k, v in metrics.items() if k != 'per_class_MSE'
        }
        per_class_all[sname] = {
            str(k): v for k, v in metrics.get('per_class_MSE', {}).items()
        }

    with open(os.path.join(output_dir, 'metrics.json'), 'w') as f:
        json.dump(save_metrics, f, indent=2)

    with open(os.path.join(output_dir, 'per_class_metrics.json'), 'w') as f:
        json.dump(per_class_all, f, indent=2)

    print(f"\n✅ 结果已保存至: {output_dir}/")

    # ── 打印每类别 MSE 对比 ───────────────────────────────────────
    all_classes = sorted(set(
        int(k)
        for sd in per_class_all.values()
        for k in sd.keys()
    ))
    if all_classes:
        print(f"\n每类别 MSE 对比：")
        cls_header = f"{'Class':<8}" + "".join(
            f"{sn:>12}" for sn in all_metrics.keys()
        )
        print(cls_header)
        print("─" * (8 + 12 * len(all_metrics)))
        for cid in all_classes:
            row = f"{cid:<8}"
            for sname in all_metrics.keys():
                v = per_class_all.get(sname, {}).get(str(cid), float('nan'))
                row += f"{v:>12.4f}"
            print(row)

    return all_metrics


# ══════════════════════════════════════════════════════════════════
# 命令行入口
# ══════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description='针织生成模型统一评估脚本')
    parser.add_argument('--stage',       type=int,  default=None, choices=[1, 2, 3, 4])
    parser.add_argument('--checkpoint',  type=str,  default=None)
    parser.add_argument('--all',         action='store_true')
    parser.add_argument('--h5',          type=str,
                        default=os.path.join(ROOT, 'dataset_processed', 'dataset.h5'))
    parser.add_argument('--json_path',   type=str,
                        default=os.path.join(ROOT, 'assets', 'instructions.json'))
    parser.add_argument('--output_dir',  type=str,
                        default=os.path.join(ROOT, 'outputs', 'evaluation'))
    parser.add_argument('--batch_size',  type=int,  default=128)
    parser.add_argument('--n_steps',     type=int,  default=50)
    parser.add_argument('--max_batches', type=int,  default=None,
                        help='调试时设小值，None=全量评估')
    parser.add_argument('--device',      type=str,  default='cuda')
    return parser.parse_args()


if __name__ == '__main__':
    args   = parse_args()
    device = torch.device(args.device if torch.cuda.is_available() else 'cpu')
    print(f"使用设备: {device}")

    if args.all:
        default_ckpts = {
            1: os.path.join(ROOT, 'checkpoints', 'stage1', 'best.pt'),
            2: os.path.join(ROOT, 'checkpoints', 'stage2', 'best.pt'),
            3: os.path.join(ROOT, 'checkpoints', 'stage3', 'best.pt'),
            4: os.path.join(ROOT, 'checkpoints', 'stage4', 'best.pt'),
        }
        stage_configs = []
        for s, path in default_ckpts.items():
            if os.path.exists(path):
                print(f"✅ 发现 Stage {s}: {path}")
                stage_configs.append((s, path))
            else:
                print(f"⏭️  Stage {s}: 不存在，跳过")

        compare_all_stages(
            stage_configs=stage_configs,
            h5_path=args.h5,
            device=device,
            output_dir=args.output_dir,
            json_path=args.json_path,
            batch_size=args.batch_size,
            n_steps=args.n_steps,
            max_batches=args.max_batches,
        )

    elif args.stage is not None:
        ckpt_path = args.checkpoint or os.path.join(
            ROOT, 'checkpoints', f'stage{args.stage}', 'best.pt'
        )
        metrics = evaluate_stage(
            stage=args.stage,
            ckpt_path=ckpt_path,
            h5_path=args.h5,
            device=device,
            json_path=args.json_path,
            batch_size=args.batch_size,
            n_steps=args.n_steps,
            max_batches=args.max_batches,
        )
        os.makedirs(args.output_dir, exist_ok=True)
        save = {k: v for k, v in metrics.items() if k != 'per_class_MSE'}
        with open(os.path.join(args.output_dir,
                               f'stage{args.stage}_metrics.json'), 'w') as f:
            json.dump(save, f, indent=2)
        print(f"✅ 结果已保存")

    else:
        print("请指定 --stage N 或 --all")
        print("示例：")
        print("  python knitting/evaluate.py --all")
        print("  python knitting/evaluate.py --stage 2")
        print("  python knitting/evaluate.py --all --max_batches 20  # 快速调试")
