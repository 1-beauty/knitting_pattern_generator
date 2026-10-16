"""区域结构指标评估脚本：Region IoU / 纹理泄漏率 / 父子包含率 / 波浪配对完整率。

针对第三轮评审"结构控制缺少真正空间指标"的意见，在现有运行产物上离线计算：

1. Region IoU（逐纹理 motif）
       IoU(z) = |closure(R̂_z) ∩ Ω'(z)| / |closure(R̂_z) ∪ Ω'(z)|
   其中 Ω'(z) 为 motif 的有效作用域（几何 mask ∩ 父级 mask），R̂_z 为归属到
   该 motif 的非底布动作格。由于纹理事件本身稀疏（周期性发射），对 R̂_z 先做
   形态学闭运算（默认 5×5）得到生成区域估计，再与期望作用域比较。
2. 纹理泄漏率（逐 motif 与全局）
       Leakage(z) = |R̂_z \ Ω'(z)| / |R̂_z|      （原始格，不做闭运算）
       Leakage_global = |T \ U| / |T|
   T 为全部非底布动作格，U 为所有纹理 motif 有效作用域的并集。
3. 父子包含率（仅有 parent_id 的 motif）
       Containment(z) = |R̂_z ∩ Ω(parent(z))| / |R̂_z|
4. 波浪配对完整率：最终网格中每个 f_split 在同行右侧 pair_delta 位置
   存在 f_tuck 的比例（pair_delta 取 motif params 的
   tuck_col_offset - split_col_offset，缺省为 1）。

非底布格归属规则：先归属到面积最小的包含其位置的作用域（子区域优先）；
落在所有作用域之外的格归属到 Chebyshev 距离最近的作用域（该距离同时计入
泄漏）。全部指标只依赖 PatternPlan JSON 与最终动作网格 npy，无需重跑管线。

用法（仓库根目录运行；--runs 接受多个目录或 glob）：
    python scripts/region_metrics.py \
        --runs "outputs/runs/ablation/*_full" "outputs/runs/edit/edt_00" \
        --out outputs/analysis/region_metrics.csv

输出：逐 motif CSV + 终端逐案例 Markdown 汇总。
"""
from __future__ import annotations

import argparse
import csv
import glob as globlib
import json
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from eval_edit_locality import _frame_thickness, build_motif_mask  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
BASE_ABBRS = ("f_knit", "b_knit")
PLAIN_EFFECTS = {"plain", "", "none", "stockinette"}


def load_abbr_to_idx() -> dict[str, int]:
    """动作 abbr → 索引。直接读 instruction_info.json，避免依赖包导入。"""
    info_path = REPO_ROOT / "generator_one" / "data" / "instruction_info.json"
    with info_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return {item["abbr"]: i for i, item in enumerate(data.get("instructions", []))}


def rect_mask(top_left, bottom_right, grid_size: int) -> np.ndarray:
    mask = np.zeros((grid_size, grid_size), dtype=bool)
    r0, c0 = int(top_left[0]), int(top_left[1])
    r1, c1 = int(bottom_right[0]), int(bottom_right[1])
    mask[max(r0, 0):min(r1, grid_size - 1) + 1, max(c0, 0):min(c1, grid_size - 1) + 1] = True
    return mask


def motif_mask(motif: dict, grid_size: int) -> np.ndarray:
    """几何 mask；在 eval_edit_locality 基础上补充 ring 区域类型。"""
    region = motif.get("region") or {}
    if region.get("type") == "ring":
        outer_spec = region.get("outer") or {}
        if "top_left" in outer_spec and "bottom_right" in outer_spec:
            outer = rect_mask(outer_spec["top_left"], outer_spec["bottom_right"], grid_size)
        else:
            outer = build_motif_mask({"region": outer_spec, "motif_type": ""}, grid_size)
        inner_spec = region.get("inner") or {}
        inner_motif = {
            "region": {
                "center": inner_spec.get("center", region.get("center")),
                "size": inner_spec.get("size", region.get("size")),
                "shape": inner_spec.get("shape", region.get("shape", "circle")),
            },
            "motif_type": "",
        }
        inner = build_motif_mask(inner_motif, grid_size)
        return outer & ~inner
    return build_motif_mask(motif, grid_size)


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr == 0 and dc == 0:
                continue
            shifted = np.zeros_like(mask)
            rs, re = max(dr, 0), mask.shape[0] + min(dr, 0)
            cs, ce = max(dc, 0), mask.shape[1] + min(dc, 0)
            shifted[rs:re, cs:ce] = mask[rs - dr:re - dr, cs - dc:ce - dc]
            out |= shifted
    return out


def binary_close(mask: np.ndarray, radius: int) -> np.ndarray:
    if not mask.any():
        return mask
    return ~dilate(~dilate(mask, radius), radius)


def is_textured(motif: dict) -> bool:
    return str(motif.get("effect", "")).strip().lower() not in PLAIN_EFFECTS


def effective_scope(motif: dict, by_id: dict[str, dict], grid_size: int) -> np.ndarray:
    """Ω'(z) = 几何 mask ∩ 父级几何 mask（沿 parent 链逐级求交）。"""
    mask = motif_mask(motif, grid_size)
    seen = set()
    parent_id = motif.get("parent_id")
    while parent_id and parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        # 父级为环形边框时，其"内部"是子区域的合法容器，而非环本身
        if str(parent.get("motif_type", "")).lower() == "frame":
            region = parent.get("region") or {}
            size = int(region.get("size", grid_size // 2))
            center = region.get("center", [grid_size // 2, grid_size // 2])
            rr, cc = np.mgrid[0:grid_size, 0:grid_size]
            cheb = np.maximum(np.abs(rr - int(center[0])), np.abs(cc - int(center[1])))
            mask &= cheb <= size - _frame_thickness(parent)
        else:
            mask &= motif_mask(parent, grid_size)
        parent_id = parent.get("parent_id")
    return mask


def attribute_cells(nonbase: np.ndarray, scopes: list[np.ndarray]) -> list[np.ndarray]:
    """非底布格归属：包含者优先（面积小者优先），其余按最近作用域。"""
    grid_size = nonbase.shape[0]
    owner = np.full((grid_size, grid_size), -1, dtype=int)
    order = sorted(range(len(scopes)), key=lambda i: int(scopes[i].sum()))
    for idx in reversed(order):  # 大区域先写，小区域后写覆盖 → 子区域优先
        owner[scopes[idx]] = idx

    leftover = nonbase & (owner < 0)
    if leftover.any() and scopes:
        cells = np.argwhere(leftover)
        scope_pts = [np.argwhere(s) for s in scopes]
        for r, c in cells:
            best, best_d = 0, np.inf
            for i, pts in enumerate(scope_pts):
                if len(pts) == 0:
                    continue
                d = np.max(np.abs(pts - (r, c)), axis=1).min()
                if d < best_d:
                    best, best_d = i, d
            owner[r, c] = best

    return [nonbase & (owner == i) for i in range(len(scopes))]


def wave_pair_rate(grid: np.ndarray, abbr_to_idx: dict, pair_delta: int) -> tuple[str, int]:
    split_idx = abbr_to_idx.get("f_split")
    tuck_idx = abbr_to_idx.get("f_tuck")
    if split_idx is None or tuck_idx is None:
        return "", 0
    splits = np.argwhere(grid == split_idx)
    if len(splits) == 0:
        return "", 0
    matched = sum(
        1 for r, c in splits
        if c + pair_delta < grid.shape[1] and grid[r, c + pair_delta] == tuck_idx
    )
    return f"{matched / len(splits):.3f}", len(splits)


def find_case_files(case_dir: Path) -> tuple[Path, Path] | None:
    plan = next(case_dir.glob("color_map/*_pattern_plan.json"), None)
    grid = next(case_dir.glob("color_map/intermediate/*_action.npy"), None)
    if plan is None or grid is None:
        return None
    return plan, grid


def evaluate_case(case_dir: Path, close_radius: int, abbr_to_idx: dict) -> list[dict]:
    files = find_case_files(case_dir)
    if files is None:
        print(f"[skip] {case_dir.name}: 缺 pattern_plan 或 action npy")
        return []
    plan_path, grid_path = files
    with plan_path.open("r", encoding="utf-8") as f:
        plan = json.load(f)
    grid = np.load(grid_path)
    grid_size = grid.shape[0]

    base_ids = {abbr_to_idx[a] for a in BASE_ABBRS if a in abbr_to_idx} or {0, 1}
    nonbase = ~np.isin(grid, list(base_ids))

    motifs = plan.get("motifs", [])
    by_id = {m.get("motif_id"): m for m in motifs}
    textured = [m for m in motifs if is_textured(m)]

    rows: list[dict] = []
    full_textured = any((m.get("region") or {}).get("type") == "full" for m in textured)
    scoped = [m for m in textured if (m.get("region") or {}).get("type") != "full"]
    scopes = [effective_scope(m, by_id, grid_size) for m in scoped]

    n_nonbase = int(nonbase.sum())
    if full_textured or not scopes:
        leak_global = 0.0 if n_nonbase else float("nan")
    else:
        union = np.zeros_like(nonbase)
        for s in scopes:
            union |= s
        leak_global = int((nonbase & ~union).sum()) / n_nonbase if n_nonbase else float("nan")

    attributed = attribute_cells(nonbase, scopes) if scopes else []

    # 波浪配对完整率：pair_delta 取 plan 中波浪 motif 的偏移参数，缺省 1
    pair_delta = 1
    for m in textured:
        params = m.get("params") or {}
        if "split_col_offset" in params or "tuck_col_offset" in params:
            pair_delta = int(params.get("tuck_col_offset", 3)) - int(params.get("split_col_offset", 2))
            break
    pair_rate, n_split = wave_pair_rate(grid, abbr_to_idx, pair_delta)

    for m, scope, cells in zip(scoped, scopes, attributed):
        n_scope, n_cells = int(scope.sum()), int(cells.sum())
        closure = binary_close(cells, close_radius) & dilate(cells, close_radius)
        inter = int((closure & scope).sum())
        union_ = int((closure | scope).sum())
        leak = int((cells & ~scope).sum()) / n_cells if n_cells else float("nan")

        containment = ""
        parent = by_id.get(m.get("parent_id"))
        if parent is not None and n_cells:
            pmask = effective_scope(parent, by_id, grid_size) | motif_mask(parent, grid_size)
            if str(parent.get("motif_type", "")).lower() == "frame":
                region = parent.get("region") or {}
                size = int(region.get("size", grid_size // 2))
                center = region.get("center", [grid_size // 2, grid_size // 2])
                rr, cc = np.mgrid[0:grid_size, 0:grid_size]
                pmask = np.maximum(np.abs(rr - int(center[0])), np.abs(cc - int(center[1]))) <= size
            containment = f"{int((cells & pmask).sum()) / n_cells:.3f}"

        rows.append({
            "case": case_dir.name,
            "motif_id": m.get("motif_id", ""),
            "effect": m.get("effect", ""),
            "parent_id": m.get("parent_id") or "",
            "scope_cells": n_scope,
            "attributed_cells": n_cells,
            "region_iou": f"{inter / union_:.3f}" if union_ else "",
            "leakage": f"{leak:.3f}" if n_cells else "",
            "containment": containment,
            "leakage_global": f"{leak_global:.3f}" if not np.isnan(leak_global) else "",
            "wave_pair_rate": pair_rate,
            "n_split": n_split,
            "bg_textured_full": int(full_textured),
        })

    if not rows:
        rows.append({
            "case": case_dir.name, "motif_id": "(no scoped textured motif)",
            "effect": "", "parent_id": "", "scope_cells": 0, "attributed_cells": n_nonbase,
            "region_iou": "", "leakage": "", "containment": "",
            "leakage_global": f"{leak_global:.3f}" if not np.isnan(leak_global) else "",
            "wave_pair_rate": pair_rate, "n_split": n_split,
            "bg_textured_full": int(full_textured),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="区域结构指标评估")
    parser.add_argument("--runs", nargs="+", required=True,
                        help="运行目录或 glob（如 outputs/runs/ablation/*_full）")
    parser.add_argument("--close-radius", type=int, default=2,
                        help="闭运算结构元半径（2 即 5×5），匹配纹理事件周期")
    parser.add_argument("--out", type=Path, default=Path("outputs/analysis/region_metrics.csv"))
    args = parser.parse_args()

    case_dirs: list[Path] = []
    for pattern in args.runs:
        matches = sorted(globlib.glob(pattern))
        if matches:
            case_dirs.extend(Path(p) for p in matches if Path(p).is_dir())
        elif Path(pattern).is_dir():
            case_dirs.append(Path(pattern))
        else:
            print(f"[warn] 未匹配到目录: {pattern}")

    abbr_to_idx = load_abbr_to_idx()
    rows: list[dict] = []
    for case_dir in case_dirs:
        rows.extend(evaluate_case(case_dir, args.close_radius, abbr_to_idx))

    if not rows:
        raise SystemExit("没有可评估的案例")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n| 案例 | motif | effect | RegionIoU | 泄漏率 | 父子包含率 | 全局泄漏 | 波浪配对 |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(
            f"| {r['case']} | {r['motif_id']} | {r['effect']} | {r['region_iou'] or '—'} "
            f"| {r['leakage'] or '—'} | {r['containment'] or '—'} "
            f"| {r['leakage_global'] or '—'} | {r['wave_pair_rate'] or '—'} |"
        )

    ious = [float(r["region_iou"]) for r in rows if r["region_iou"]]
    leaks = [float(r["leakage"]) for r in rows if r["leakage"]]
    conts = [float(r["containment"]) for r in rows if r["containment"]]
    if ious:
        print(f"\n均值: RegionIoU={np.mean(ious):.3f}, Leakage={np.mean(leaks):.3f}"
              + (f", Containment={np.mean(conts):.3f}" if conts else ""))
    print(f"逐 motif 结果已写入 {args.out}")


if __name__ == "__main__":
    main()
