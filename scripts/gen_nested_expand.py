# -*- coding: utf-8 -*-
"""Expand the CONTROLLED (Protocol-B) comparison on the HARD-NESTED regime.

The original controlled comparison used 8 hand-built nested cases (frame -> inner
shape -> texture), where dense Plan-Grid filling leaks badly. The 98 general
semantic inputs are mostly single-region/easy (leakage ~0.05) and dilute the
effect, so they are NOT a faithful expansion of THIS experiment.

Here we construct N additional hard-nested PatternPlans across pre-specified
structural-difficulty categories (nesting depth, inner shape, texture type,
border thickness, inner size), then compile each with the REAL pipeline twice
(event = Ours, dense = Plan-Grid), no LLM. Effect/param combos are restricted to
those proven valid in existing archived plans (wave_tuck, honeycomb).

Outputs mirror region_metrics.py's expected layout:
    outputs/runs/protocolB_nested/<case>_{event,dense}/color_map/{plan,intermediate/action}
"""
from __future__ import annotations
import itertools, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "generator_one"
sys.path.insert(0, str(GEN))

PLANS_DIR = REPO / "outputs/runs/protocolB_nested/plans"
OUT_ROOT = REPO / "outputs/runs/protocolB_nested"

WAVE_PARAMS = {"period_x": 5, "period_y": 4, "split_col_offset": 2, "tuck_col_offset": 3}
HONEY_PARAMS = {"period_x": 4, "period_y": 3, "stagger": True}

# pre-specified difficulty axes (systematic, not tuned per-result)
SHAPES = ["circle", "diamond", "hexagon", "rectangle"]
TEXTURES = [("wave_tuck", WAVE_PARAMS, "circle"), ("honeycomb", HONEY_PARAMS, "diamond")]
BORDERS = [1, 2, 3]
INNER_SIZES = [9, 12, 14]
DEPTHS = [2, 3]


def build_case(idx, shape, tex, border, inner_size, depth):
    tex_name, tex_params, _ = tex
    motifs = [{
        "motif_id": "frame_outer", "motif_type": "frame", "effect": "plain",
        "region": {"type": "border", "thickness": border, "center": [20, 20], "size": 17},
        "params": {"border_thickness": border}, "role": "border",
        "symmetry": "none", "allow_refinement": True, "parent_id": None,
    }]
    if depth == 3:
        # frame -> plain mid shape -> texture core (deeper nesting)
        motifs.append({
            "motif_id": "shape_mid", "motif_type": shape, "effect": "plain",
            "region": {"center": [20, 20], "size": inner_size + 3, "shape": shape},
            "params": {}, "role": "inner_shape",
            "symmetry": "none", "allow_refinement": True, "parent_id": "frame_outer",
        })
        parent = "shape_mid"
    else:
        parent = "frame_outer"
    motifs.append({
        "motif_id": "tex_core", "motif_type": shape, "effect": tex_name,
        "region": {"center": [20, 20], "size": inner_size, "shape": shape},
        "params": dict(tex_params), "role": "center",
        "symmetry": "none", "allow_refinement": True, "parent_id": parent,
    })
    return {
        "schema_version": "pattern_plan/v1",
        "canvas": {"width": 40, "height": 40},
        "layout_type": "framed",
        "motifs": motifs,
        "history": [{"input": f"NESTEXP-{idx:02d} hard-nested controlled input "
                              f"(depth={depth}, shape={shape}, tex={tex_name}, border={border}, "
                              f"inner={inner_size}); programmatically constructed fixed plan",
                     "source": "manual_edit"}],
    }


def gen_plans():
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    combos = list(itertools.product(SHAPES, TEXTURES, BORDERS, INNER_SIZES, DEPTHS))
    # systematic stride to a generous, balanced subset (~36 cases)
    stride = max(1, len(combos) // 36)
    chosen = combos[::stride][:36]
    ids = []
    for i, (shape, tex, border, inner_size, depth) in enumerate(chosen, 1):
        cid = f"nestexp_{i:02d}"
        plan = build_case(i, shape, tex, border, inner_size, depth)
        (PLANS_DIR / f"{cid}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        ids.append(cid)
    return ids


def run(ids):
    from pipeline import KnittingPipeline, PipelineConfig
    t = 0
    for cid in ids:
        pf = PLANS_DIR / f"{cid}.json"
        for mode in ("event", "dense"):
            out_dir = OUT_ROOT / f"{cid}_{mode}" / "color_map"
            cfg = PipelineConfig(
                enable_refinement=True, enable_aesthetic=True, enable_llm_repair=False,
                save_intermediate=True, skip_pattern_plan=False,
                fixed_plan_path=str(pf), compile_mode=mode,
                no_layer_clip=False, no_wave_pair_guard=False,
            )
            pipe = KnittingPipeline(llm_client=None, rasterizer=None, config=cfg)
            res = pipe.generate(cid)
            pipe.save_results(res, out_dir, prefix=cid)
            t += 1
    return t


if __name__ == "__main__":
    ids = gen_plans()
    print(f"[gen] {len(ids)} hard-nested plans -> {PLANS_DIR}")
    n = run(ids)
    print(f"[run] compiled {n} runs (event+dense) -> {OUT_ROOT}")
