"""基于编译器内部事件归属的区域指标对照（回应审稿意见：几何事后归属是否可靠）。

正文的 Region IoU / 泄漏率采用"几何归属 + 闭运算"的事后估计：将最终动作
网格中的非底布格按几何 mask 归属到各纹理 motif。编译器内部本就维护每个
EventPoint 的 region_id（与 motif_id 同名），本脚本用内部归属直接重算一版
结构指标，与几何估计版对照：

1. 复放（不调用 LLM，确定性）：PatternPlan -> VisualSpec -> RealizationPlan
   -> EventPlanner，得到带 region_id 的事件点集合；
2. 内部归属版指标：R̂_int(z) = { (row,col) | event.region_id == z }，
   对其做与正文相同的 5×5 闭运算后计算 Region IoU 与泄漏率；
3. 逐格归属一致率：最终动作网格的非底布格中，与规划事件坐标重合的格，
   几何归属结果与该事件 region_id 一致的比例。

对象与表 7 相同：消融测试集 ABL-01–08 的完整系统运行
（outputs/runs/ablation/abl_0X_full，协议 B 固定 PatternPlan）。

注意：内部归属版的 R̂_int 是"事件规划footprint"，不含过渡求解、transfer
稳定化等后处理写入的辅助动作格；几何版基于最终网格。两版的差异同时
反映归属方式差异与后处理足迹，均如实报告。

用法：
    python scripts/region_internal_attribution.py
输出：
    outputs/analysis/region_internal_attribution.csv + 终端 Markdown 汇总
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
GEN_ONE = REPO_ROOT / "generator_one"
for p in (str(SCRIPT_DIR), str(GEN_ONE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from region_metrics import (  # noqa: E402
    load_abbr_to_idx, effective_scope, attribute_cells, binary_close, dilate,
    is_textured, find_case_files, BASE_ABBRS,
)
from generation.pattern_plan import PatternPlan, PatternPlanEngine  # noqa: E402
from generation.visual_to_realization import VisualToRealizationConverter  # noqa: E402
from generation.event_planner import EventPlanner  # noqa: E402

CASE_DIRS = sorted((REPO_ROOT / "outputs/runs/ablation").glob("abl_0[1-8]_full"))
GRID_SIZE = 40
CLOSE_RADIUS = 2  # 5×5，与正文一致
OUT = REPO_ROOT / "outputs/analysis/region_internal_attribution.csv"


def replay_events(plan_path: Path):
    with plan_path.open(encoding="utf-8") as f:
        plan_dict = json.load(f)
    pattern_plan = PatternPlan.from_dict(plan_dict)
    engine = PatternPlanEngine()
    visual_spec = engine.render_visual_spec(pattern_plan)
    realization_plan = VisualToRealizationConverter().convert(visual_spec)
    events = EventPlanner(grid_size=GRID_SIZE).plan(realization_plan)
    return plan_dict, events


def main() -> None:
    abbr_to_idx = load_abbr_to_idx()
    base_ids = {abbr_to_idx[a] for a in BASE_ABBRS if a in abbr_to_idx} or {0, 1}

    rows: list[dict] = []
    iou_geo_all, iou_int_all = [], []
    leak_geo_all, leak_int_all = [], []
    agree_num = agree_den = 0

    for case_dir in CASE_DIRS:
        files = find_case_files(case_dir)
        if files is None:
            print(f"[skip] {case_dir.name}: 缺 pattern_plan 或 action npy")
            continue
        plan_path, grid_path = files
        plan_dict, events = replay_events(plan_path)
        grid = np.load(grid_path)
        nonbase = ~np.isin(grid, list(base_ids))

        motifs = plan_dict.get("motifs", [])
        by_id = {m.get("motif_id"): m for m in motifs}
        scoped = [m for m in motifs
                  if is_textured(m) and (m.get("region") or {}).get("type") != "full"]
        scopes = [effective_scope(m, by_id, GRID_SIZE) for m in scoped]
        geo_cells = attribute_cells(nonbase, scopes) if scopes else []

        # 内部归属：事件坐标按 region_id 分桶
        int_cells = [np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool) for _ in scoped]
        scoped_ids = {m.get("motif_id"): i for i, m in enumerate(scoped)}
        for e in events:
            idx = scoped_ids.get(e.region_id)
            if idx is not None and 0 <= e.row < GRID_SIZE and 0 <= e.col < GRID_SIZE:
                int_cells[idx][e.row, e.col] = True

        # 逐格归属一致率：事件格 ∩ 最终非底布格上，几何归属 == region_id
        for i, (geo, ic) in enumerate(zip(geo_cells, int_cells)):
            both = ic & nonbase
            agree_den += int(both.sum())
            agree_num += int((both & geo).sum())

        for m, scope, geo, ic in zip(scoped, scopes, geo_cells, int_cells):
            row = {"case": case_dir.name, "motif_id": m.get("motif_id", ""),
                   "effect": m.get("effect", ""),
                   "geo_cells": int(geo.sum()), "int_cells": int(ic.sum())}
            for tag, cells, iou_list, leak_list in (
                ("geo", geo, iou_geo_all, leak_geo_all),
                ("int", ic, iou_int_all, leak_int_all),
            ):
                n_cells = int(cells.sum())
                closure = binary_close(cells, CLOSE_RADIUS) & dilate(cells, CLOSE_RADIUS)
                union = int((closure | scope).sum())
                iou = int((closure & scope).sum()) / union if union else float("nan")
                leak = int((cells & ~scope).sum()) / n_cells if n_cells else float("nan")
                row[f"iou_{tag}"] = f"{iou:.3f}" if not np.isnan(iou) else ""
                row[f"leak_{tag}"] = f"{leak:.3f}" if not np.isnan(leak) else ""
                if not np.isnan(iou):
                    iou_list.append(iou)
                if not np.isnan(leak):
                    leak_list.append(leak)
            rows.append(row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n| 案例 | motif | effect | IoU(几何) | IoU(内部) | 泄漏(几何) | 泄漏(内部) |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(f"| {r['case']} | {r['motif_id']} | {r['effect']} "
              f"| {r['iou_geo'] or '—'} | {r['iou_int'] or '—'} "
              f"| {r['leak_geo'] or '—'} | {r['leak_int'] or '—'} |")

    print(f"\n均值: IoU 几何={np.mean(iou_geo_all):.3f} vs 内部={np.mean(iou_int_all):.3f} "
          f"(n={len(iou_geo_all)})")
    print(f"均值: 泄漏 几何={np.mean(leak_geo_all):.3f} vs 内部={np.mean(leak_int_all):.3f}")
    print(f"逐格归属一致率: {agree_num}/{agree_den} = "
          f"{agree_num / agree_den:.1%}" if agree_den else "逐格归属一致率: 无可比格")
    print(f"逐 motif 结果已写入 {OUT}")


if __name__ == "__main__":
    main()
