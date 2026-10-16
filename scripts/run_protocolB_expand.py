# -*- coding: utf-8 -*-
"""Protocol-B controlled comparison expansion driver.

For each reusable PatternPlan (archived sem_XX run), compile the SAME plan twice:
  - event  -> "Ours (full system)"  (sparse event-level compilation)
  - dense  -> "Plan-Grid"           (dense periodic filling baseline)
No LLM is used (fixed_plan_path skips parsing; enable_llm_repair=False skips repair),
so results are deterministic and offline. Output mirrors main.py's save_results
structure so scripts/region_metrics.py can score it directly.

Usage:
    python scripts/run_protocolB_expand.py --ids sem_01 sem_02 ... --modes event dense
    python scripts/run_protocolB_expand.py --all --modes event dense
"""
from __future__ import annotations
import argparse, glob, json, os, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "generator_one"
sys.path.insert(0, str(GEN))

OUT_ROOT = REPO / "outputs" / "runs" / "protocolB_expand"
PLAIN = {"plain", "", "none", "stockinette"}


def plan_path(sem_id: str) -> Path | None:
    hits = glob.glob(str(REPO / "outputs/runs/semantic" / sem_id / "color_map" / "*_pattern_plan.json"))
    return Path(hits[0]) if hits else None


def has_scoped_textured(plan_file: Path) -> bool:
    try:
        plan = json.load(open(plan_file, encoding="utf-8"))
    except Exception:
        return False
    for m in plan.get("motifs", []):
        reg = m.get("region") or {}
        eff = str(m.get("effect", "")).strip().lower()
        if reg.get("type") == "full" or eff in PLAIN:
            continue
        return True
    return False


def all_candidate_ids() -> list[str]:
    ids = []
    for p in sorted(glob.glob(str(REPO / "outputs/runs/semantic/sem_*"))):
        sem_id = os.path.basename(p)
        pf = plan_path(sem_id)
        if pf and has_scoped_textured(pf):
            ids.append(sem_id)
    return ids


def run_one(sem_id: str, mode: str) -> bool:
    from pipeline import KnittingPipeline, PipelineConfig
    pf = plan_path(sem_id)
    if pf is None:
        print(f"[skip] {sem_id}: no plan"); return False
    # region_metrics.find_case_files expects <case_dir>/color_map/{plan,intermediate/action}
    out_dir = OUT_ROOT / f"{sem_id}_{mode}" / "color_map"
    cfg = PipelineConfig(
        enable_refinement=True, enable_aesthetic=True, enable_llm_repair=False,
        save_intermediate=True, skip_pattern_plan=False,
        fixed_plan_path=str(pf), compile_mode=mode,
        no_layer_clip=False, no_wave_pair_guard=False,
    )
    pipe = KnittingPipeline(llm_client=None, rasterizer=None, config=cfg)
    res = pipe.generate(sem_id)
    pipe.save_results(res, out_dir, prefix=sem_id)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--modes", nargs="+", default=["event", "dense"])
    args = ap.parse_args()

    ids = all_candidate_ids() if args.all else (args.ids or [])
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"[driver] {len(ids)} inputs x modes {args.modes}")
    t0 = time.time(); ok = 0; fail = []
    for i, sem_id in enumerate(ids, 1):
        for mode in args.modes:
            try:
                if run_one(sem_id, mode):
                    ok += 1
                else:
                    fail.append((sem_id, mode))
            except Exception as e:
                fail.append((sem_id, mode)); print(f"[FAIL] {sem_id}/{mode}: {type(e).__name__}: {e}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(ids)} done, {time.time()-t0:.1f}s")
    print(f"[driver] OK runs={ok} fail={len(fail)} time={time.time()-t0:.1f}s")
    if fail:
        print("[driver] failures:", fail[:20])


if __name__ == "__main__":
    main()
