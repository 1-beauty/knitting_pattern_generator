"""从真实运行产物复放编译前段，提取中间表示 schema 示例（补充材料 E 用）。

选用协议 B 嵌套消融运行 nest_01_frame_diamond_wave_full（矩形框架内嵌菱形、
菱形内波浪吊目，含两级父子层级）的 PatternPlan JSON，确定性地复放：
    PatternPlan -> render -> VisualSpec -> v2r -> RealizationPlan -> planner -> EventPoint
三步均不调用 LLM，产物与论文运行使用的编译输入一致。

用法（在 generator_one 目录下运行）：
    python scripts/../generator_one/../scripts/extract_schema_examples.py
输出：
    outputs/analysis/schema_examples_nest01.json
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GEN_ONE = REPO_ROOT / "generator_one"
sys.path.insert(0, str(GEN_ONE))

from generation.pattern_plan import PatternPlan, PatternPlanEngine  # noqa: E402
from generation.visual_to_realization import VisualToRealizationConverter  # noqa: E402
from generation.event_planner import EventPlanner  # noqa: E402

PLAN_PATH = REPO_ROOT / "outputs/runs/event_ablation/nest_01_frame_diamond_wave_full/color_map"
OUT_PATH = REPO_ROOT / "outputs/analysis/schema_examples_nest01.json"
GRID_SIZE = 40


def main() -> None:
    plan_file = next(PLAN_PATH.glob("*_pattern_plan.json"))
    with plan_file.open(encoding="utf-8") as f:
        plan_dict = json.load(f)
    pattern_plan = PatternPlan.from_dict(plan_dict)

    engine = PatternPlanEngine()
    visual_spec = engine.render_visual_spec(pattern_plan)
    realization_plan = VisualToRealizationConverter().convert(visual_spec)
    events = EventPlanner(grid_size=GRID_SIZE).plan(realization_plan)

    payload = {
        "source_run": str(plan_file.relative_to(REPO_ROOT)),
        "pattern_plan": plan_dict,
        "visual_spec": {
            "layout_type": visual_spec.layout_type,
            "regions": [dataclasses.asdict(r) for r in visual_spec.regions],
        },
        "realization_plan": {
            "layout_type": realization_plan.layout_type,
            "grid_size": realization_plan.grid_size,
            "regions": [dataclasses.asdict(r) for r in realization_plan.regions],
        },
        "event_points": {
            "total": len(events),
            "examples_first_10": [dataclasses.asdict(e) for e in events[:10]],
            "count_by_region": {},
        },
    }
    by_region: dict[str, int] = {}
    for e in events:
        by_region[e.region_id] = by_region.get(e.region_id, 0) + 1
    payload["event_points"]["count_by_region"] = by_region

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"来源 PatternPlan: {payload['source_run']}")
    print(f"VisualSpec regions: {len(visual_spec.regions)}")
    print(f"RealizationPlan regions: {len(realization_plan.regions)}")
    print(f"EventPoint total: {len(events)}, by region: {by_region}")
    print(f"已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
