"""图 S3：内部基线 Plan-Grid 与完整系统的区域结构差异可视化（协议 B 真实归档产物）。

三行案例，每行对应表 6 / 4.3.2 节叙事中的一个差异维度：
- ABL-03 fill_mesh：泄漏格高亮（红描边），泄漏率 0.667 → 0.000
- ABL-06（框外波浪背景）：未配对 f_split 高亮（红圈），成组完整率 0.857 → 1.000
- ABL-05 diamond_main：有效作用域轮廓（黄色虚线）叠加，Region IoU 0.003 → 0.106

指标复用 scripts/region_metrics.py 的同一套归属与闭运算逻辑离线重算，
确保图上数值与表 S16c 完全一致；色码图直接读取运行归档的 output.bmp。

输出：docs/figures/fig_internal_baseline_leakage.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import region_metrics as rm  # noqa: E402

CASES = [
    ("abl_03", "fill_mesh", "leak", "ABL-03 · fill_mesh"),
    ("abl_06", "fill_stripe", "pair", "ABL-06 · 框外波浪背景"),
    ("abl_05", "diamond_main", "scope", "ABL-05 · diamond_main"),
]
METHODS = [
    ("outputs/runs/internal_baseline/{c}_plangrid", "Plan-Grid"),
    ("outputs/runs/ablation/{c}_full", "Ours（完整系统）"),
]
CLOSE_RADIUS = 2  # 5×5 闭运算，与表 S16c 口径一致


def load_case(case_id: str, dir_pattern: str):
    case_dir = REPO / dir_pattern.format(c=case_id)
    files = rm.find_case_files(case_dir)
    if files is None:
        raise FileNotFoundError(f"{case_dir} 缺 plan 或 npy")
    plan_path, grid_path = files
    with plan_path.open(encoding="utf-8") as f:
        plan = json.load(f)
    grid = np.load(grid_path)
    bmp = Image.open(case_dir / "color_map" / f"{case_id}_output.bmp").convert("RGB")
    return plan, grid, bmp


def analyze(plan: dict, grid: np.ndarray, abbr_to_idx: dict, motif_id: str) -> dict:
    """与 region_metrics.evaluate_case 同一口径：归属、闭运算 IoU、原始格泄漏、配对率。"""
    grid_size = grid.shape[0]
    base_ids = {abbr_to_idx[a] for a in rm.BASE_ABBRS if a in abbr_to_idx}
    nonbase = ~np.isin(grid, list(base_ids))
    motifs = plan.get("motifs", [])
    by_id = {m.get("motif_id"): m for m in motifs}
    textured = [m for m in motifs if rm.is_textured(m)]
    scoped = [m for m in textured if (m.get("region") or {}).get("type") != "full"]
    scopes = [rm.effective_scope(m, by_id, grid_size) for m in scoped]
    attributed = rm.attribute_cells(nonbase, scopes)
    idx = next(i for i, m in enumerate(scoped) if m.get("motif_id") == motif_id)
    scope, cells = scopes[idx], attributed[idx]

    closure = rm.binary_close(cells, CLOSE_RADIUS) & rm.dilate(cells, CLOSE_RADIUS)
    union = int((closure | scope).sum())
    iou = int((closure & scope).sum()) / union if union else float("nan")
    n_cells = int(cells.sum())
    leak = int((cells & ~scope).sum()) / n_cells if n_cells else float("nan")

    pair_delta = 1
    for m in textured:
        params = m.get("params") or {}
        if "split_col_offset" in params or "tuck_col_offset" in params:
            pair_delta = int(params.get("tuck_col_offset", 3)) - int(
                params.get("split_col_offset", 2))
            break
    split_idx, tuck_idx = abbr_to_idx["f_split"], abbr_to_idx["f_tuck"]
    splits = np.argwhere(grid == split_idx)
    unpaired = [(int(r), int(c)) for r, c in splits
                if not (c + pair_delta < grid.shape[1]
                        and grid[r, c + pair_delta] == tuck_idx)]
    pair_rate = 1 - len(unpaired) / len(splits) if len(splits) else float("nan")
    return {
        "scope": scope, "leak_cells": cells & ~scope, "iou": iou, "leak": leak,
        "unpaired": unpaired, "pair_rate": pair_rate, "n_split": len(splits),
    }


def draw_leak(ax, leak_cells: np.ndarray) -> None:
    for r, c in np.argwhere(leak_cells):
        ax.add_patch(Rectangle((c, r), 1, 1, fill=False,
                               edgecolor="#D62728", linewidth=1.5))


def draw_unpaired(ax, unpaired: list[tuple[int, int]]) -> None:
    for r, c in unpaired:
        ax.add_patch(Rectangle((c - 0.15, r - 0.15), 1.3, 1.3, fill=False,
                               edgecolor="#D62728", linewidth=1.4))


def draw_scope(ax, scope: np.ndarray) -> None:
    ax.contour(scope.astype(float), levels=[0.5], colors=["#FFD400"],
               linewidths=1.2, linestyles="--")


def save_cell(case_id: str, dir_pattern: str, method_key: str, mode: str,
              motif_id: str, abbr_to_idx: dict) -> str:
    """单格叠加图 → assets_real/leakmap_{case}_{key}.png（600×600），返回指标串。"""
    plan, grid, bmp = load_case(case_id, dir_pattern)
    an = analyze(plan, grid, abbr_to_idx, motif_id)
    fig = plt.figure(figsize=(2, 2), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(bmp, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if mode == "leak":
        draw_leak(ax, an["leak_cells"])
        metric = f"Region IoU {an['iou']:.3f}｜泄漏率 {an['leak']:.3f}"
    elif mode == "pair":
        draw_unpaired(ax, an["unpaired"])
        matched = an["n_split"] - len(an["unpaired"])
        metric = f"成组完整率 {an['pair_rate']:.3f}（{matched}/{an['n_split']}）"
    else:
        draw_scope(ax, an["scope"])
        metric = f"Region IoU {an['iou']:.3f}｜泄漏率 {an['leak']:.3f}"
    out = REPO / "docs" / "figures" / "assets_real" / f"leakmap_{case_id}_{method_key}.png"
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)
    return metric


def main() -> None:
    abbr_to_idx = rm.load_abbr_to_idx()
    report = []

    for case_id, motif_id, mode, label in CASES:
        for dir_pattern, method_name, key in [
            (METHODS[0][0], METHODS[0][1], "pg"),
            (METHODS[1][0], METHODS[1][1], "ours"),
        ]:
            metric = save_cell(case_id, dir_pattern, key, mode, motif_id, abbr_to_idx)
            report.append((case_id, motif_id, method_name, metric))
            print(f"[saved] leakmap_{case_id}_{key}.png")

    print("\n图上指标（应与表 S16c 一致）:")
    for case_id, motif_id, method_name, metric in report:
        print(f"  {case_id} {motif_id:14s} {method_name:12s} {metric}")


if __name__ == "__main__":
    main()
