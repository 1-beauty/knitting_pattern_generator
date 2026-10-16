"""
knitting/evaluate_full_image.py
全图级统一评估脚本

作用：
1. 用完整色码图生成完整仿真图（160x160）
2. 与真实 full-image 仿真图比较
3. 输出 full-image 指标 + 自定义结构指标

推荐用法：

# 先快速跑 20 张图调试
python knitting/evaluate_full_image.py --all --num_images 20

# 正式跑 50 张图
python knitting/evaluate_full_image.py --all --num_images 50

说明：
- Stage 1 使用 independent noise
- Stage 2/3/4 默认使用 global_correlated noise
- 默认 solver=midpoint, steps=300
"""

import os
import sys
import json
import argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PIL import Image

try:
    from pytorch_msssim import ssim as ssim_fn
    HAS_SSIM = True
except Exception:
    HAS_SSIM = False
    print("⚠️  pytorch_msssim 不可用，SSIM 将跳过")

import torch

try:
    import lpips as lpips_lib
    HAS_LPIPS = True
except Exception:
    HAS_LPIPS = False
    print("⚠️  lpips 不可用，LPIPS 将跳过 (pip install lpips)")

try:
    from scipy.ndimage import sobel as scipy_sobel
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False
    print("⚠️  scipy 不可用，Edge/Boundary 指标将跳过")

from knitting.inference import generate_full_image


# ══════════════════════════════════════════════════════════════════
# 数据配对与 split（必须和 preprocess.py 保持一致）
# ══════════════════════════════════════════════════════════════════

def collect_pairs(color_map_dir, simulation_dir):
    pairs = []
    for category in sorted(os.listdir(color_map_dir)):
        cat_color_dir = os.path.join(color_map_dir, category)
        cat_sim_dir   = os.path.join(simulation_dir, category)

        if not os.path.isdir(cat_color_dir):
            continue
        if not os.path.isdir(cat_sim_dir):
            continue

        for fname in sorted(os.listdir(cat_color_dir)):
            if not fname.endswith('.png'):
                continue
            color_path = os.path.join(cat_color_dir, fname)
            stem       = os.path.splitext(fname)[0]
            sim_path   = os.path.join(cat_sim_dir, stem + '.jpg')
            if not os.path.exists(sim_path):
                continue
            pairs.append((color_path, sim_path, category, stem))
    return pairs


def split_pairs_like_preprocess(pairs, val_ratio=0.1, seed=42):
    rng = np.random.RandomState(seed)
    indices = rng.permutation(len(pairs))
    n_val_imgs = int(len(pairs) * val_ratio)
    val_img_indices = set(indices[:n_val_imgs].tolist())

    train_pairs, val_pairs = [], []
    for i, p in enumerate(pairs):
        if i in val_img_indices:
            val_pairs.append(p)
        else:
            train_pairs.append(p)
    return train_pairs, val_pairs


def sample_pairs(pairs, num_images=50, seed=42):
    if num_images is None or num_images >= len(pairs):
        return pairs
    rng = np.random.RandomState(seed)
    idx = rng.choice(len(pairs), size=num_images, replace=False)
    idx = sorted(idx.tolist())
    return [pairs[i] for i in idx]


# ══════════════════════════════════════════════════════════════════
# 图像 / id_matrix 处理
# ══════════════════════════════════════════════════════════════════

def load_gt_image_01(sim_path, target_size=None):
    img = Image.open(sim_path).convert('RGB')
    if target_size is not None and img.size != target_size:
        img = img.resize(target_size, Image.BICUBIC)
    arr = np.array(img, dtype=np.float32) / 255.0
    return arr


def load_color_table(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    table = []
    for inst in data['instructions']:
        hex_color = inst['color'].lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        table.append((r, g, b))
    return np.array(table, dtype=np.int32)


def rgb_to_id_vectorized(rgb_array, color_table):
    diff = rgb_array[:, :, None, :].astype(np.int32) - color_table[None, None, :, :]
    dist = np.sum(diff ** 2, axis=-1)
    return np.argmin(dist, axis=-1).astype(np.int32)


def parse_color_map_to_id_matrix(png_path, color_table):
    img = Image.open(png_path).convert('RGB')
    if img.size != (20, 20):
        img = img.resize((20, 20), Image.NEAREST)
    arr = np.array(img)
    full_id_map = rgb_to_id_vectorized(arr, color_table)
    id_matrix = full_id_map[::2, ::2]   # (10,10)
    return id_matrix


def image_to_tensor_01(arr_hwc):
    # (H,W,C) [0,1] -> (1,C,H,W)
    return torch.from_numpy(arr_hwc).permute(2, 0, 1).unsqueeze(0).float()


def full_psnr(pred_01, gt_01):
    mse = np.mean((pred_01 - gt_01) ** 2)
    mse = max(mse, 1e-10)
    return 10.0 * np.log10(1.0 / mse)


def patch_mean_map(img_01, patch_size=16):
    """
    img_01: (H, W, 3)  H = grid_h * patch_size, W = grid_w * patch_size
    return: (grid_h, grid_w) patch mean
    """
    H, W = img_01.shape[:2]
    gh, gw = H // patch_size, W // patch_size
    blocks = img_01.reshape(gh, patch_size, gw, patch_size, 3).transpose(0, 2, 1, 3, 4)
    return blocks.mean(axis=(2, 3, 4))


# ══════════════════════════════════════════════════════════════════
# 自定义 full-image 指标
# ══════════════════════════════════════════════════════════════════

def seam_errors(pred_01, gt_01, id_matrix, patch_size=16):
    """
    计算接缝误差：
      - SeamErr_same: 同ID相邻块的接缝误差
      - SeamErr_diff: 异ID相邻块的边界误差

    做法：
      对每条接缝，计算 pred 的边界差值 和 gt 的边界差值，
      再取绝对差的平均。
    """
    same_errs = []
    diff_errs = []
    gh, gw = id_matrix.shape

    def seam_diff_vertical(img, row, col_boundary):
        r0, r1 = row * patch_size, (row + 1) * patch_size
        c = col_boundary * patch_size
        left  = img[r0:r1, c - 1, :]
        right = img[r0:r1, c, :]
        return np.mean(np.abs(left - right))

    def seam_diff_horizontal(img, row_boundary, col):
        c0, c1 = col * patch_size, (col + 1) * patch_size
        r = row_boundary * patch_size
        up   = img[r - 1, c0:c1, :]
        down = img[r, c0:c1, :]
        return np.mean(np.abs(up - down))

    # 横向相邻（左右）
    for r in range(gh):
        for c in range(gw - 1):
            pred_diff = seam_diff_vertical(pred_01, r, c + 1)
            gt_diff   = seam_diff_vertical(gt_01,   r, c + 1)
            err = abs(pred_diff - gt_diff)

            if id_matrix[r, c] == id_matrix[r, c + 1]:
                same_errs.append(err)
            else:
                diff_errs.append(err)

    # 纵向相邻（上下）
    for r in range(gh - 1):
        for c in range(gw):
            pred_diff = seam_diff_horizontal(pred_01, r + 1, c)
            gt_diff   = seam_diff_horizontal(gt_01,   r + 1, c)
            err = abs(pred_diff - gt_diff)

            if id_matrix[r, c] == id_matrix[r + 1, c]:
                same_errs.append(err)
            else:
                diff_errs.append(err)

    seam_same = float(np.mean(same_errs)) if len(same_errs) > 0 else 0.0
    seam_diff = float(np.mean(diff_errs)) if len(diff_errs) > 0 else 0.0
    return seam_same, seam_diff


def find_connected_components(id_matrix):
    """
    在 10x10 id_matrix 上按 4-邻域找同ID连通区域
    返回：
      components: List[List[(r,c)]]
    """
    H, W = id_matrix.shape
    visited = np.zeros((H, W), dtype=bool)
    components = []
    directions = [(-1,0), (1,0), (0,-1), (0,1)]

    for r in range(H):
        for c in range(W):
            if visited[r, c]:
                continue

            target_id = id_matrix[r, c]
            stack = [(r, c)]
            visited[r, c] = True
            cells = []

            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))

                for dr, dc in directions:
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < H and 0 <= nc < W:
                        if (not visited[nr, nc]) and id_matrix[nr, nc] == target_id:
                            visited[nr, nc] = True
                            stack.append((nr, nc))

            components.append(cells)

    return components


def region_outlier_ratio(pred_01, id_matrix, min_region_size=4, patch_size=16):
    """
    在同ID连通区域内统计 patch mean 的异常块比例
    用于刻画：
      - 背景中的空白洞
      - 凭空长出的细线
      - 同类区域内部的异常跳变
    """
    pmap = patch_mean_map(pred_01, patch_size=patch_size)  # (grid_h, grid_w)
    comps = find_connected_components(id_matrix)

    outlier_count = 0
    total_count = 0

    for cells in comps:
        if len(cells) < min_region_size:
            continue

        vals = np.array([pmap[r, c] for r, c in cells], dtype=np.float32)
        median = np.median(vals)
        mad = np.median(np.abs(vals - median))
        thresh = max(0.02, 2.5 * 1.4826 * mad)

        outliers = np.abs(vals - median) > thresh
        outlier_count += int(outliers.sum())
        total_count += len(vals)

    if total_count == 0:
        return 0.0
    return float(outlier_count / total_count)


def region_variance_gap(pred_01, gt_01, id_matrix, min_region_size=4, patch_size=16):
    """
    比较同ID连通区域内 patch mean 方差的差距
    反映：
      - 粗细不均匀
      - 区域内部稳定性不如 GT
    """
    pmap = patch_mean_map(pred_01, patch_size=patch_size)
    gmap = patch_mean_map(gt_01, patch_size=patch_size)
    comps = find_connected_components(id_matrix)

    gaps = []
    for cells in comps:
        if len(cells) < min_region_size:
            continue

        pvals = np.array([pmap[r, c] for r, c in cells], dtype=np.float32)
        gvals = np.array([gmap[r, c] for r, c in cells], dtype=np.float32)

        gaps.append(abs(np.var(pvals) - np.var(gvals)))

    if len(gaps) == 0:
        return 0.0
    return float(np.mean(gaps))


# ══════════════════════════════════════════════════════════════════
# 补充感知与纹理指标（更适合 Stage 4 评估）
# ══════════════════════════════════════════════════════════════════

_lpips_model = None

def _get_lpips_model():
    global _lpips_model
    if _lpips_model is None and HAS_LPIPS:
        _lpips_model = lpips_lib.LPIPS(net='alex')
        _lpips_model.eval()
        for p in _lpips_model.parameters():
            p.requires_grad = False
    return _lpips_model


def compute_lpips(pred_01, gt_01):
    """LPIPS 感知距离 (AlexNet)。越低表示感知质量越好。"""
    model = _get_lpips_model()
    if model is None:
        return None
    pred_t = torch.from_numpy(pred_01).permute(2, 0, 1).unsqueeze(0).float() * 2 - 1
    gt_t   = torch.from_numpy(gt_01).permute(2, 0, 1).unsqueeze(0).float() * 2 - 1
    with torch.no_grad():
        return float(model(pred_t, gt_t).item())


def compute_edge_consistency(pred_01, gt_01):
    """边缘一致性：梯度幅值误差 + 梯度方向余弦距离。"""
    if not HAS_SCIPY:
        return None
    pred_g = np.mean(pred_01, axis=2)
    gt_g   = np.mean(gt_01, axis=2)

    gx_p = scipy_sobel(pred_g, axis=1)
    gy_p = scipy_sobel(pred_g, axis=0)
    mag_p = np.sqrt(gx_p**2 + gy_p**2 + 1e-10)

    gx_g = scipy_sobel(gt_g, axis=1)
    gy_g = scipy_sobel(gt_g, axis=0)
    mag_g = np.sqrt(gx_g**2 + gy_g**2 + 1e-10)

    grad_err = float(np.mean(np.abs(mag_p - mag_g)))
    cos_sim  = float(np.mean((gx_p * gx_g + gy_p * gy_g) / (mag_p * mag_g)))
    return {'edge_grad_err': grad_err, 'edge_cos_sim': cos_sim}


def compute_boundary_f1(pred_01, gt_01, id_matrix, patch_size=16, tol=2):
    """边界 F1：生成图是否捕获了区域边界过渡。"""
    if not HAS_SCIPY:
        return None
    H, W = id_matrix.shape
    gt_boundary = np.zeros((H * patch_size, W * patch_size), dtype=bool)

    for r in range(H):
        for c in range(W):
            if c + 1 < W and id_matrix[r, c] != id_matrix[r, c + 1]:
                col_px = (c + 1) * patch_size
                gt_boundary[:, max(0, col_px - tol):min(gt_boundary.shape[1], col_px + tol)] = True
            if r + 1 < H and id_matrix[r, c] != id_matrix[r + 1, c]:
                row_px = (r + 1) * patch_size
                gt_boundary[max(0, row_px - tol):min(gt_boundary.shape[0], row_px + tol), :] = True

    pred_gray = np.mean(pred_01, axis=2)
    edges = scipy_sobel(pred_gray, axis=0)**2 + scipy_sobel(pred_gray, axis=1)**2
    thresh = np.percentile(edges[edges > 0], 75) if np.any(edges > 0) else 0
    pred_boundary = edges > thresh

    tp = int(np.sum(pred_boundary & gt_boundary))
    fp = int(np.sum(pred_boundary & ~gt_boundary))
    fn = int(np.sum(~pred_boundary & gt_boundary))

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {'boundary_precision': prec, 'boundary_recall': rec, 'boundary_f1': f1}


def compute_texture_spectrum_sim(pred_01, gt_01):
    """纹理频谱相似度：径向平均功率谱的归一化互相关。"""
    pred_g = np.mean(pred_01, axis=2).astype(np.float64)
    gt_g   = np.mean(gt_01, axis=2).astype(np.float64)

    F_p = np.fft.fft2(pred_g - pred_g.mean())
    F_g = np.fft.fft2(gt_g - gt_g.mean())

    P_p = np.log(np.abs(F_p)**2 + 1e-10)
    P_g = np.log(np.abs(F_g)**2 + 1e-10)

    H, W = P_p.shape
    cy, cx = H // 2, W // 2
    Y, X = np.mgrid[0:H, 0:W]
    R = np.sqrt((Y - cy)**2 + (X - cx)**2).astype(int)
    max_r = min(cy, cx)

    spec_p = np.zeros(max_r)
    spec_g = np.zeros(max_r)
    counts = np.zeros(max_r)
    for r in range(max_r):
        mask = R == r
        spec_p[r] = P_p[mask].mean()
        spec_g[r] = P_g[mask].mean()
        counts[r] = mask.sum()

    valid = counts >= 10
    if valid.sum() < 5:
        return None
    sp, sg = spec_p[valid], spec_g[valid]
    sp = (sp - sp.mean()) / (sp.std() + 1e-10)
    sg = (sg - sg.mean()) / (sg.std() + 1e-10)
    return float(np.mean(sp * sg))


# ══════════════════════════════════════════════════════════════════
# 单个 stage 的 full-image 评估
# ══════════════════════════════════════════════════════════════════

def evaluate_full_image_stage(
    stage,
    ckpt_path,
    val_pairs,
    json_path,
    device='cuda',
    num_steps=300,
    solver='midpoint',
    noise_mode_nonstage1='global_correlated',
    perturb_scale=0.03,
    region_alpha=0.88,
    seed=42,
):
    print(f"\n{'='*60}")
    print(f"Full-image 评估 Stage {stage}")
    print(f"Checkpoint: {ckpt_path}")
    print(f"Images:     {len(val_pairs)}")
    print(f"Solver:     {solver}, steps={num_steps}")
    print(f"{'='*60}")

    color_table = load_color_table(json_path)

    metrics_sum = defaultdict(float)
    n = 0

    for idx, (color_path, sim_path, category, stem) in enumerate(val_pairs):
        stage_seed = seed + idx

        if stage == 1:
            noise_mode = 'independent'
        else:
            noise_mode = noise_mode_nonstage1

        pred_img = generate_full_image(
            color_map_path=color_path,
            model_path=ckpt_path,
            json_path=json_path,
            stage=stage,
            device=device,
            num_steps=num_steps,
            solver=solver,
            noise_mode=noise_mode,
            perturb_scale=perturb_scale,
            region_alpha=region_alpha,
            seed=stage_seed,
        )

        pred_01 = np.array(pred_img, dtype=np.float32) / 255.0
        gt_01   = load_gt_image_01(sim_path, target_size=pred_img.size)
        id_mat  = parse_color_map_to_id_matrix(color_path, color_table)

        # 动态推导 patch_size（不同 stage 可能不同，如 stage4=8）
        ps = pred_01.shape[0] // id_mat.shape[0]

        # ── base full-image metrics ───────────────────────────────
        mse = np.mean((pred_01 - gt_01) ** 2)
        l1  = np.mean(np.abs(pred_01 - gt_01))
        psnr = full_psnr(pred_01, gt_01)

        metrics_sum['Full_MSE']  += float(mse)
        metrics_sum['Full_L1']   += float(l1)
        metrics_sum['Full_PSNR'] += float(psnr)

        if HAS_SSIM:
            pred_t = image_to_tensor_01(pred_01)
            gt_t   = image_to_tensor_01(gt_01)
            ssim_v = ssim_fn(pred_t, gt_t, data_range=1.0, size_average=True).item()
            metrics_sum['Full_SSIM'] += float(ssim_v)

        # ── custom full-image metrics ─────────────────────────────
        seam_same, seam_diff = seam_errors(pred_01, gt_01, id_mat, patch_size=ps)
        outlier_ratio = region_outlier_ratio(pred_01, id_mat, patch_size=ps)
        var_gap = region_variance_gap(pred_01, gt_01, id_mat, patch_size=ps)

        metrics_sum['SeamErr_same']  += seam_same
        metrics_sum['SeamErr_diff']  += seam_diff
        metrics_sum['RegionOutlier'] += outlier_ratio
        metrics_sum['RegionVarGap']  += var_gap

        # ── perceptual & texture metrics ──────────────────────────
        if HAS_LPIPS:
            lpips_v = compute_lpips(pred_01, gt_01)
            if lpips_v is not None:
                metrics_sum['LPIPS'] += lpips_v

        if HAS_SCIPY:
            edge_v = compute_edge_consistency(pred_01, gt_01)
            if edge_v is not None:
                metrics_sum['EdgeGradErr']  += edge_v['edge_grad_err']
                metrics_sum['EdgeCosSim']   += edge_v['edge_cos_sim']

            bnd_v = compute_boundary_f1(pred_01, gt_01, id_mat, patch_size=ps)
            if bnd_v is not None:
                metrics_sum['BoundaryF1'] += bnd_v['boundary_f1']

            tex_v = compute_texture_spectrum_sim(pred_01, gt_01)
            if tex_v is not None:
                metrics_sum['TextureSim'] += tex_v

        n += 1

        if idx % 5 == 0:
            print(f"  进度: {idx+1}/{len(val_pairs)}  ({category}/{stem})")

    metrics = {k: v / n for k, v in metrics_sum.items()}

    print(f"\nStage {stage} full-image 指标：")
    for k, v in metrics.items():
        if 'PSNR' in k:
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v:.4f}")

    return metrics


# ══════════════════════════════════════════════════════════════════
# 所有 stage 对比
# ══════════════════════════════════════════════════════════════════

def compare_all_full_image_stages(
    stage_configs,
    color_map_dir,
    simulation_dir,
    json_path,
    device='cuda',
    output_dir='outputs/full_image_evaluation',
    val_ratio=0.1,
    split_seed=42,
    num_images=50,
    eval_seed=42,
    num_steps=300,
    solver='midpoint',
    noise_mode_nonstage1='global_correlated',
    perturb_scale=0.03,
    region_alpha=0.88,
):
    os.makedirs(output_dir, exist_ok=True)

    pairs = collect_pairs(color_map_dir, simulation_dir)
    _, val_pairs = split_pairs_like_preprocess(pairs, val_ratio=val_ratio, seed=split_seed)
    val_pairs = sample_pairs(val_pairs, num_images=num_images, seed=eval_seed)

    print(f"总配对图像: {len(pairs)}")
    print(f"val 图像数: {len(val_pairs)} (抽样后)")
    print(f"split_seed={split_seed}, eval_seed={eval_seed}")

    all_metrics = {}
    for stage_id, ckpt_path in stage_configs:
        if not os.path.exists(ckpt_path):
            print(f"⚠️  Stage {stage_id} checkpoint 不存在，跳过")
            continue

        metrics = evaluate_full_image_stage(
            stage=stage_id,
            ckpt_path=ckpt_path,
            val_pairs=val_pairs,
            json_path=json_path,
            device=device,
            num_steps=num_steps,
            solver=solver,
            noise_mode_nonstage1=noise_mode_nonstage1,
            perturb_scale=perturb_scale,
            region_alpha=region_alpha,
            seed=eval_seed,
        )
        all_metrics[f'Stage {stage_id}'] = metrics

    if not all_metrics:
        print("❌ 没有可评估的结果")
        return

    # ── 打印表格 ──────────────────────────────────────────────────
    keys = [
        'Full_MSE', 'Full_L1', 'Full_SSIM', 'Full_PSNR',
        'SeamErr_same', 'SeamErr_diff', 'RegionOutlier', 'RegionVarGap',
        'LPIPS', 'EdgeGradErr', 'EdgeCosSim', 'BoundaryF1', 'TextureSim',
    ]

    print(f"\n{'='*100}")
    print("Full-image 级别对比")
    print(f"{'='*100}")

    header = f"{'Stage':<12}" + "".join(f"{k:>14}" for k in keys)
    print(header)
    print("─" * 100)

    rows = {}
    for sname, metrics in all_metrics.items():
        row = f"{sname:<12}"
        row_data = {}
        for k in keys:
            v = metrics.get(k, float('nan'))
            row_data[k] = v
            if 'PSNR' in k:
                row += f"{v:>14.2f}"
            elif k in ('BoundaryF1', 'TextureSim', 'EdgeCosSim'):
                row += f"{v:>14.4f}"
            else:
                row += f"{v:>14.4f}"
        rows[sname] = row_data
        print(row)

    print(f"{'='*100}")

    # ── 保存 JSON ────────────────────────────────────────────────
    with open(os.path.join(output_dir, 'full_image_metrics.json'), 'w') as f:
        json.dump(all_metrics, f, indent=2)

    meta = {
        'num_images': len(val_pairs),
        'solver': solver,
        'num_steps': num_steps,
        'noise_mode_nonstage1': noise_mode_nonstage1,
        'perturb_scale': perturb_scale,
        'region_alpha': region_alpha,
        'split_seed': split_seed,
        'eval_seed': eval_seed,
        'val_ratio': val_ratio,
        'val_pairs': [
            {'color_map': p[0], 'simulation': p[1], 'category': p[2], 'stem': p[3]}
            for p in val_pairs
        ]
    }
    with open(os.path.join(output_dir, 'full_image_eval_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"✅ 已保存至: {output_dir}")

    return all_metrics


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description='Full-image 级别统一评估脚本')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--stage', type=int, default=None)
    parser.add_argument('--checkpoint', type=str, default=None)

    parser.add_argument('--color_map_dir', type=str,
                        default=os.path.join(ROOT, 'dataset_raw', 'color_maps'))
    parser.add_argument('--simulation_dir', type=str,
                        default=os.path.join(ROOT, 'dataset_raw', 'simulations'))
    parser.add_argument('--json_path', type=str,
                        default=os.path.join(ROOT, 'assets', 'instructions.json'))

    parser.add_argument('--output_dir', type=str,
                        default=os.path.join(ROOT, 'outputs', 'full_image_evaluation'))
    parser.add_argument('--device', type=str, default='cuda')

    parser.add_argument('--val_ratio', type=float, default=0.1)
    parser.add_argument('--split_seed', type=int, default=42)
    parser.add_argument('--eval_seed', type=int, default=42)

    parser.add_argument('--num_images', type=int, default=50,
                        help='从 val 全图中抽样多少张做 full-image 评估')
    parser.add_argument('--num_steps', type=int, default=300)
    parser.add_argument('--solver', type=str, default='midpoint',
                        choices=['euler', 'midpoint', 'rk4'])

    parser.add_argument('--noise_mode_nonstage1', type=str, default='global_correlated',
                        choices=['global_correlated', 'region_correlated', 'independent'])
    parser.add_argument('--perturb_scale', type=float, default=0.03)
    parser.add_argument('--region_alpha', type=float, default=0.88)

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    device = args.device if torch.cuda.is_available() else 'cpu'
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
                print(f"⏭️  Stage {s} checkpoint 不存在，跳过")

        compare_all_full_image_stages(
            stage_configs=stage_configs,
            color_map_dir=args.color_map_dir,
            simulation_dir=args.simulation_dir,
            json_path=args.json_path,
            device=device,
            output_dir=args.output_dir,
            val_ratio=args.val_ratio,
            split_seed=args.split_seed,
            num_images=args.num_images,
            eval_seed=args.eval_seed,
            num_steps=args.num_steps,
            solver=args.solver,
            noise_mode_nonstage1=args.noise_mode_nonstage1,
            perturb_scale=args.perturb_scale,
            region_alpha=args.region_alpha,
        )

    elif args.stage is not None:
        ckpt_path = args.checkpoint or os.path.join(
            ROOT, 'checkpoints', f'stage{args.stage}', 'best.pt'
        )

        pairs = collect_pairs(args.color_map_dir, args.simulation_dir)
        _, val_pairs = split_pairs_like_preprocess(
            pairs, val_ratio=args.val_ratio, seed=args.split_seed
        )
        val_pairs = sample_pairs(val_pairs, num_images=args.num_images, seed=args.eval_seed)

        metrics = evaluate_full_image_stage(
            stage=args.stage,
            ckpt_path=ckpt_path,
            val_pairs=val_pairs,
            json_path=args.json_path,
            device=device,
            num_steps=args.num_steps,
            solver=args.solver,
            noise_mode_nonstage1=args.noise_mode_nonstage1,
            perturb_scale=args.perturb_scale,
            region_alpha=args.region_alpha,
            seed=args.eval_seed,
        )

        os.makedirs(args.output_dir, exist_ok=True)
        with open(os.path.join(args.output_dir, f'stage{args.stage}_full_metrics.json'), 'w') as f:
            json.dump(metrics, f, indent=2)
        print("✅ 单阶段结果已保存")

    else:
        print("请指定 --all 或 --stage N")