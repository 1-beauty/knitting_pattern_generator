"""
knitting/inference.py
统一推理脚本：支持 Stage 1 / 2 / 3 / 4

当前版本原则：
1. 回到稳定原版推理逻辑
2. 不做任何自动后处理 / prototype / 对齐 / 修图
3. 只增加多 seed 候选导出，方便人工选择

推荐（Stage 4）：
python knitting/inference.py \
    --stage 4 \
    --solver midpoint \
    --num_steps 300 \
    --noise_mode global_correlated \
    --perturb_scale 0.03 \
    --num_candidates 4 \
    --save_grid \
    --seed 42
"""

import os
import sys
import math
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from torchdiffeq import odeint

from data.preprocess import parse_color_map, load_color_table
from data.stage1_adapter import parse_stage1_color_map


# 设备解析工具：支持传入 'cuda', 'cuda:0', 'cpu'，并在 CUDA 不可用时友好回退
def resolve_device(device_str):
    try:
        if isinstance(device_str, torch.device):
            return device_str
        ds = str(device_str)
        if ds.startswith('cuda'):
            if torch.cuda.is_available():
                try:
                    return torch.device(ds)
                except Exception:
                    return torch.device('cuda')
            else:
                print(f"Warning: requested device '{ds}' but CUDA is not available. Falling back to CPU.")
                return torch.device('cpu')
        else:
            return torch.device('cpu')
    except Exception:
        return torch.device('cpu')


# ══════════════════════════════════════════════════════════════════
# 模型加载
# ══════════════════════════════════════════════════════════════════

def load_model(stage, model_path, json_path, device):
    """
    按 stage 加载对应模型结构，并载入 checkpoint 权重
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Checkpoint 不存在: {model_path}")

    ckpt = torch.load(model_path, map_location=device, weights_only=False)
    patch_size = int(ckpt.get('patch_size', 16))

    if stage == 1:
        from knitting.train import Stage1ConditionedUNet
        model = Stage1ConditionedUNet(num_classes=15, patch_size=patch_size)

    elif stage == 2:
        from knitting.train import Stage2NeighborAwareUNet
        model = Stage2NeighborAwareUNet(
            num_classes=15, embed_dim=256, num_heads=8, patch_size=patch_size
        )

    elif stage == 3:
        from knitting.train import Stage3PhysicsAwareUNet
        model = Stage3PhysicsAwareUNet(
            json_path=json_path,
            num_classes=15,
            embed_dim=256,
            num_heads=8,
            patch_size=patch_size,
        )

    elif stage == 4:
        from knitting.train import Stage4AdaptiveSIUNet
        model = Stage4AdaptiveSIUNet(
            json_path=json_path,
            num_classes=15,
            embed_dim=256,
            num_heads=8,
            patch_size=patch_size,
        )

    else:
        raise ValueError(f"未知 stage: {stage}，应为 1/2/3/4")

    model.load_state_dict(ckpt['model_state'], strict=True)
    model.eval().to(device)

    epoch = ckpt.get('epoch', 'N/A')
    val_loss = ckpt.get('val_loss', None)
    if val_loss is not None:
        print(f"✅ 加载 checkpoint: stage={stage}, epoch={epoch}, patch_size={patch_size}, val_loss={val_loss:.4f}")
    else:
        print(f"✅ 加载 checkpoint: stage={stage}, epoch={epoch}, patch_size={patch_size}")

    return model


# ══════════════════════════════════════════════════════════════════
# 邻居输入构造
# ══════════════════════════════════════════════════════════════════

def build_neighbor_inputs(id_matrix, device):
    """
    根据 10x10 id_matrix 构造全图邻域输入
    与 preprocess.py 保持一致

    返回：
        all_neighbor_ids:  (100, 3, 3) long
        all_neighbor_mask: (100, 3, 3) bool
    """
    H, W = id_matrix.shape
    if H <= 0 or W <= 0:
        raise ValueError(f"id_matrix shape invalid: {id_matrix.shape}")

    num_blocks = H * W
    all_neighbor_ids = np.zeros((num_blocks, 3, 3), dtype=np.int64)
    all_neighbor_mask = np.zeros((num_blocks, 3, 3), dtype=np.bool_)

    for idx in range(num_blocks):
        row, col = idx // W, idx % W

        all_neighbor_mask[idx, 1, 1] = True

        for dr in range(-1, 2):
            for dc in range(-1, 2):
                nr, nc = row + dr, col + dc
                if 0 <= nr < H and 0 <= nc < W:
                    all_neighbor_ids[idx, dr + 1, dc + 1] = id_matrix[nr, nc]
                    all_neighbor_mask[idx, dr + 1, dc + 1] = True

    all_neighbor_ids = torch.tensor(all_neighbor_ids, dtype=torch.long, device=device)
    all_neighbor_mask = torch.tensor(all_neighbor_mask, dtype=torch.bool, device=device)

    return all_neighbor_ids, all_neighbor_mask


def save_id_matrix_debug(id_matrix, output_path, color_table=None):
    """Save the 10x10 condition seen by the model next to the output image."""
    if not output_path:
        return
    out_dir = os.path.dirname(output_path)
    if not out_dir:
        return
    os.makedirs(out_dir, exist_ok=True)

    txt_path = os.path.join(out_dir, "id_matrix.txt")
    np.savetxt(txt_path, id_matrix.astype(np.int32), fmt="%02d")

    if color_table is not None:
        clipped = np.clip(id_matrix.astype(np.int32), 0, len(color_table) - 1)
        rgb = color_table[clipped].astype(np.uint8)
    else:
        max_id = max(1, int(id_matrix.max()))
        gray = (id_matrix.astype(np.float32) / max_id * 255).astype(np.uint8)
        rgb = np.stack([gray, gray, gray], axis=-1)

    img = Image.fromarray(rgb, mode="RGB").resize((160, 160), Image.Resampling.NEAREST)
    img.save(os.path.join(out_dir, "id_matrix_preview.png"))


def find_connected_components(id_matrix):
    """
    在 10x10 id_matrix 上按 4-邻域找同ID连通区域
    返回：
      components: List[List[(r, c)]]
    """
    H, W = id_matrix.shape
    visited = np.zeros((H, W), dtype=bool)
    components = []

    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

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


# ══════════════════════════════════════════════════════════════════
# 初始噪声构造
# ══════════════════════════════════════════════════════════════════

def build_initial_noise(stage, id_matrix, device,
                        noise_mode='auto',
                        perturb_scale=0.03,
                        region_alpha=0.88,
                        seed=42,
                        patch_size=16):
    """
    构造初始噪声 x0

    noise_mode:
      - independent: 完全独立噪声
      - global_correlated: 全图共享一个 base noise
      - region_correlated: 每个连通区域共享一个 base noise
      - auto:
          Stage 1 -> independent
          Stage 2/3/4 -> global_correlated
    """
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    H, W = id_matrix.shape
    num_blocks = H * W

    if noise_mode == 'auto':
        if stage == 1:
            noise_mode = 'independent'
        else:
            noise_mode = 'global_correlated'

    # 1) 完全独立噪声
    if noise_mode == 'independent':
        return torch.randn(num_blocks, 3, patch_size, patch_size, device=device), noise_mode

    # 2) 全图相关噪声（当前最稳）
    if noise_mode == 'global_correlated':
        base_noise = torch.randn(1, 3, patch_size, patch_size, device=device)
        jitter = torch.randn(num_blocks, 3, patch_size, patch_size, device=device) * perturb_scale
        return base_noise + jitter, noise_mode

    # 3) 区域相关噪声（保留，但当前不推荐）
    if noise_mode == 'region_correlated':
        x0 = torch.zeros(num_blocks, 3, patch_size, patch_size, device=device)
        components = find_connected_components(id_matrix)

        for cells in components:
            comp_size = len(cells)

            if comp_size >= 6:
                alpha = region_alpha
            elif comp_size >= 3:
                alpha = min(region_alpha, 0.82)
            else:
                alpha = min(region_alpha, 0.70)

            base = torch.randn(1, 3, patch_size, patch_size, device=device)

            for r, c in cells:
                idx = r * W + c
                indep = torch.randn(1, 3, patch_size, patch_size, device=device)

                mixed = alpha * base + (max(1.0 - alpha ** 2, 1e-6) ** 0.5) * indep
                jitter = torch.randn(1, 3, patch_size, patch_size, device=device) * perturb_scale
                x0[idx:idx + 1] = mixed + jitter

        return x0, noise_mode

    raise ValueError(f"未知 noise_mode: {noise_mode}")


# ══════════════════════════════════════════════════════════════════
# 单次生成
# ══════════════════════════════════════════════════════════════════

@torch.no_grad()
def generate_single_image(
    model,
    id_matrix,
    all_neighbor_ids,
    all_neighbor_mask,
    stage=4,
    device='cuda',
    num_steps=300,
    solver='midpoint',
    noise_mode='global_correlated',
    perturb_scale=0.03,
    region_alpha=0.88,
    seed=42,
    batch_size=100,
):
    """
    单个 seed 生成一张完整图
    """
    device = resolve_device(device)
    patch_size = int(getattr(model, 'patch_size', 16))

    x0, resolved_noise_mode = build_initial_noise(
        stage=stage,
        id_matrix=id_matrix,
        device=device,
        noise_mode=noise_mode,
        perturb_scale=perturb_scale,
        region_alpha=region_alpha,
        seed=seed,
        patch_size=patch_size,
    )

    outputs = []
    num_blocks = x0.shape[0]
    batch_size = max(1, int(batch_size or num_blocks))

    for start in range(0, num_blocks, batch_size):
        end = min(num_blocks, start + batch_size)
        x0_batch = x0[start:end]
        neighbor_ids_batch = all_neighbor_ids[start:end]
        neighbor_mask_batch = all_neighbor_mask[start:end]

        def ode_func(t, x):
            t_batch = t.expand(x.shape[0])

            if stage == 1:
                center_ids = neighbor_ids_batch[:, 1, 1]
                return model(x, t_batch, center_ids)

            elif stage in (3, 4):
                return model(
                    x, t_batch, neighbor_ids_batch, neighbor_mask_batch,
                    return_aux=False,
                )

            else:
                return model(x, t_batch, neighbor_ids_batch, neighbor_mask_batch)

        t_span = torch.linspace(0, 1, num_steps, device=device)
        trajectory = odeint(ode_func, x0_batch, t_span, method=solver)
        outputs.append(trajectory[-1].clamp(-1, 1))

    x1 = torch.cat(outputs, dim=0)

    blocks = x1.permute(0, 2, 3, 1).cpu().numpy()
    blocks = np.clip((blocks + 1.0) * 127.5, 0, 255).astype(np.uint8)

    num_blocks = blocks.shape[0]
    grid_h, grid_w = id_matrix.shape
    output = np.zeros((grid_h * patch_size, grid_w * patch_size, 3), dtype=np.uint8)
    for idx in range(num_blocks):
        row, col = idx // grid_w, idx % grid_w
        output[
            row * patch_size:(row + 1) * patch_size,
            col * patch_size:(col + 1) * patch_size,
        ] = blocks[idx]

    result = Image.fromarray(output)
    return result, resolved_noise_mode


# ══════════════════════════════════════════════════════════════════
# 候选拼图
# ══════════════════════════════════════════════════════════════════

def safe_load_default_font():
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def make_labeled_tile(img, label, tile_size=(160, 160), label_h=20):
    img = img.resize(tile_size, Image.Resampling.NEAREST)
    canvas = Image.new('RGB', (tile_size[0], tile_size[1] + label_h), (255, 255, 255))
    canvas.paste(img, (0, label_h))

    draw = ImageDraw.Draw(canvas)
    font = safe_load_default_font()
    draw.rectangle([0, 0, tile_size[0], label_h], fill=(240, 240, 240))
    draw.text((4, 3), label, fill=(0, 0, 0), font=font)
    return canvas


def build_candidate_grid(input_path, candidate_images, candidate_labels, cols=3):
    """
    构建候选拼图：
      第一张放原始色码图（nearest resize 到 160x160）
      后面放不同 seed 的结果图
    """
    tiles = []
    tile_size = candidate_images[0].size if candidate_images else (160, 160)

    try:
        input_img = Image.open(input_path).convert('RGB').resize(tile_size, Image.Resampling.NEAREST)
        tiles.append(make_labeled_tile(input_img, "input_color_map", tile_size=tile_size))
    except Exception:
        pass

    for img, label in zip(candidate_images, candidate_labels):
        tiles.append(make_labeled_tile(img, label, tile_size=tile_size))

    if len(tiles) == 0:
        raise RuntimeError("没有可用于拼图的 tile")

    cols = max(1, cols)
    rows = math.ceil(len(tiles) / cols)

    tile_w, tile_h = tiles[0].size
    pad = 8

    grid_w = cols * tile_w + (cols + 1) * pad
    grid_h = rows * tile_h + (rows + 1) * pad

    grid = Image.new('RGB', (grid_w, grid_h), (255, 255, 255))

    for i, tile in enumerate(tiles):
        r = i // cols
        c = i % cols
        x = pad + c * (tile_w + pad)
        y = pad + r * (tile_h + pad)
        grid.paste(tile, (x, y))

    return grid


# ══════════════════════════════════════════════════════════════════
# 统一准备
# ══════════════════════════════════════════════════════════════════

def resolve_input_source(input_path, input_source):
    if input_source != 'auto':
        return input_source
    norm = os.path.normpath(os.path.abspath(input_path)).lower()
    if os.path.sep + 'outputs' + os.path.sep + 'runs' + os.path.sep in norm:
        return 'stage1'
    return 'dataset'


def prepare_generation(stage, checkpoint, input_path, json_path, device, input_source='auto', output_path=None):
    """
    模型、色码图、邻域输入一次准备好，供多 seed 复用
    """
    device = resolve_device(device)
    print(f"使用设备: {device}")

    model = load_model(stage, checkpoint, json_path, device)

    color_table = load_color_table(json_path)
    resolved_source = resolve_input_source(input_path, input_source)
    if resolved_source == 'stage1':
        id_matrix = parse_stage1_color_map(input_path, color_table)
    elif resolved_source == 'dataset':
        id_matrix = parse_color_map(input_path, color_table)
    else:
        raise ValueError(f"未知 input_source: {input_source}")
    print(
        f"色码图解析完成: source={resolved_source}, "
        f"shape={id_matrix.shape}, id范围=[{id_matrix.min()}, {id_matrix.max()}]"
    )
    uniq, counts = np.unique(id_matrix, return_counts=True)
    dist = ", ".join(f"{int(i)}:{int(c)}" for i, c in zip(uniq, counts))
    print(f"id_matrix 分布: {dist}")
    save_id_matrix_debug(id_matrix, output_path, color_table=color_table)

    all_neighbor_ids, all_neighbor_mask = build_neighbor_inputs(id_matrix, device)
    return device, model, id_matrix, all_neighbor_ids, all_neighbor_mask


# ══════════════════════════════════════════════════════════════════
# 命令行参数
# ══════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description='针织仿真图统一推理脚本（稳定版 + 多 seed 候选导出）',
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '--stage', type=int, required=True, choices=[1, 2, 3, 4],
        help='Stage 编号：1=baseline, 2=邻居感知, 3=物理特征, 4=自适应SI'
    )
    parser.add_argument(
        '--checkpoint', type=str, default=None,
        help='checkpoint 路径（默认：checkpoints/stage{N}/best.pt）'
    )
    parser.add_argument(
        '--input', type=str,
        default='dataset_raw/color_maps/Cable/Cable1_001_0_0.png',
        help='输入色码图路径（20x20 PNG）'
    )
    parser.add_argument(
        '--input_source', type=str, default='auto',
        choices=['auto', 'dataset', 'stage1'],
        help='输入来源：dataset=原始训练数据解析；stage1=第一阶段输出适配；auto=按路径自动判断'
    )
    parser.add_argument(
        '--output', type=str, default=None,
        help='输出路径：\n'
             '  - 单图时保存结果图\n'
             '  - 多候选时保存候选拼图'
    )
    parser.add_argument(
        '--json_path', type=str,
        default='assets/instructions.json',
        help='instructions.json 路径'
    )
    parser.add_argument(
        '--device', type=str, default='cuda',
        help='cuda / cpu'
    )
    parser.add_argument(
        '--num_steps', type=int, default=None,
        help='ODE 积分步数（Stage4 默认 300）'
    )
    parser.add_argument(
        '--solver', type=str, default=None,
        choices=['euler', 'midpoint', 'rk4'],
        help='ODE solver（Stage4 默认 midpoint）'
    )
    parser.add_argument(
        '--noise_mode', type=str, default='auto',
        choices=['auto', 'independent', 'global_correlated', 'region_correlated'],
        help='噪声模式'
    )
    parser.add_argument(
        '--perturb_scale', type=float, default=None,
        help='噪声扰动强度（Stage4 推荐 0.03）'
    )
    parser.add_argument(
        '--region_alpha', type=float, default=0.88,
        help='区域相关噪声强度（仅 region_correlated 有效）'
    )
    parser.add_argument(
        '--seed', type=int, default=42,
        help='基础随机种子'
    )

    # 多候选
    parser.add_argument(
        '--num_candidates', type=int, default=1,
        help='候选数量；>1 时会导出多张候选图'
    )
    parser.add_argument(
        '--seed_stride', type=int, default=1,
        help='相邻候选 seed 的间隔'
    )
    parser.add_argument(
        '--candidate_dir', type=str, default=None,
        help='候选图保存目录（num_candidates>1 时有效）'
    )
    parser.add_argument(
        '--save_grid', action='store_true',
        help='num_candidates>1 时，额外保存候选拼图'
    )
    parser.add_argument(
        '--grid_cols', type=int, default=3,
        help='候选拼图列数'
    )
    parser.add_argument(
        '--batch_size', type=int, default=100,
        help='Stage I 40x40 输入分批推理的 patch 数量'
    )

    args = parser.parse_args()

    if args.checkpoint is None:
        args.checkpoint = os.path.join(ROOT, f'checkpoints/stage{args.stage}/best.pt')

    if args.num_steps is None:
        args.num_steps = 300 if args.stage == 4 else 200

    if args.solver is None:
        args.solver = 'midpoint' if args.stage >= 2 else 'euler'

    if args.perturb_scale is None:
        args.perturb_scale = 0.03 if args.stage == 4 else 0.05

    if args.output is None:
        if args.num_candidates > 1:
            args.output = os.path.join(ROOT, f'outputs/stage{args.stage}_candidates_grid.png')
        else:
            args.output = os.path.join(ROOT, f'outputs/stage{args.stage}_result.png')

    if args.candidate_dir is None and args.num_candidates > 1:
        args.candidate_dir = os.path.join(ROOT, f'outputs/stage{args.stage}_candidates')

    return args


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    args = parse_args()

    print("=" * 72)
    print(f"Stage:           {args.stage}")
    print(f"Input:           {args.input}")
    print(f"Checkpoint:      {args.checkpoint}")
    print(f"Solver:          {args.solver} ({args.num_steps} steps)")
    print(f"Noise:           {args.noise_mode} (perturb_scale={args.perturb_scale}, region_alpha={args.region_alpha})")
    print(f"Seed:            {args.seed}")
    print(f"Num Candidates:  {args.num_candidates}")
    if args.num_candidates > 1:
        print(f"Seed Stride:     {args.seed_stride}")
        print(f"Candidate Dir:   {args.candidate_dir}")
        print(f"Save Grid:       {args.save_grid}")
    print(f"Output:          {args.output}")
    print("=" * 72)

    device, model, id_matrix, all_neighbor_ids, all_neighbor_mask = prepare_generation(
        stage=args.stage,
        checkpoint=args.checkpoint,
        input_path=args.input,
        json_path=args.json_path,
        device=args.device,
        input_source=args.input_source,
        output_path=args.output,
    )

    # 单图模式
    if args.num_candidates == 1:
        result, resolved_noise_mode = generate_single_image(
            model=model,
            id_matrix=id_matrix,
            all_neighbor_ids=all_neighbor_ids,
            all_neighbor_mask=all_neighbor_mask,
            stage=args.stage,
            device=device,
            num_steps=args.num_steps,
            solver=args.solver,
            noise_mode=args.noise_mode,
            perturb_scale=args.perturb_scale,
            region_alpha=args.region_alpha,
            seed=args.seed,
            batch_size=args.batch_size,
        )

        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        result.save(args.output)
        print(f"\n✅ 生成完成: {args.output}")
        print(f"   noise_mode={resolved_noise_mode}")

    # 多候选模式
    else:
        os.makedirs(args.candidate_dir, exist_ok=True)

        candidate_images = []
        candidate_labels = []

        for i in range(args.num_candidates):
            cur_seed = args.seed + i * args.seed_stride
            print(f"\n--- 生成候选 {i+1}/{args.num_candidates} | seed={cur_seed} ---")

            result, resolved_noise_mode = generate_single_image(
                model=model,
                id_matrix=id_matrix,
                all_neighbor_ids=all_neighbor_ids,
                all_neighbor_mask=all_neighbor_mask,
                stage=args.stage,
                device=device,
                num_steps=args.num_steps,
                solver=args.solver,
                noise_mode=args.noise_mode,
                perturb_scale=args.perturb_scale,
                region_alpha=args.region_alpha,
                seed=cur_seed,
                batch_size=args.batch_size,
            )

            candidate_path = os.path.join(args.candidate_dir, f'seed_{cur_seed}.png')
            result.save(candidate_path)

            candidate_images.append(result)
            candidate_labels.append(f'seed={cur_seed}')

            print(f"  已保存候选: {candidate_path}")
            print(f"  noise_mode={resolved_noise_mode}")

        if args.save_grid:
            out_dir = os.path.dirname(args.output)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            grid = build_candidate_grid(
                input_path=args.input,
                candidate_images=candidate_images,
                candidate_labels=candidate_labels,
                cols=args.grid_cols,
            )
            grid.save(args.output)
            print(f"\n✅ 候选拼图已保存: {args.output}")

        print(f"\n✅ 多候选生成完成，候选目录: {args.candidate_dir}")
