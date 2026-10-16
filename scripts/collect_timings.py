"""汇总各运行目录 stats.json 中的 timings 字段，生成论文运行时间表。

前置：pipeline.py 已在 statistics["timings"] 落盘逐阶段耗时（本次新增）。
旧运行产物没有 timings 字段会被自动跳过，因此需要在远程重跑目标案例后再执行。

用法（仓库根目录）：
    python scripts/collect_timings.py \
        --runs "outputs/runs/ablation/*_full" "outputs/runs/edit_native/edtp_*" \
        --out outputs/analysis/timings.csv
"""
from __future__ import annotations

import argparse
import csv
import glob as globlib
import json
from pathlib import Path

STAGE_KEYS = [
    "step1_design_llm",
    "step2_realization",
    "step3_event_planning",
    "step4_action_build",
    "step5_6_refine_aesthetic",
    "step7_rule_check",
    "step8_repair",
    "post_guards_final",
    "total",
]


def find_stats(case_dir: Path) -> Path | None:
    hits = sorted(case_dir.glob("**/*_stats.json"))
    return hits[0] if hits else None


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总管线逐阶段运行时间")
    parser.add_argument("--runs", nargs="+", required=True, help="运行目录或 glob")
    parser.add_argument("--out", type=Path, default=Path("outputs/analysis/timings.csv"))
    args = parser.parse_args()

    case_dirs: list[Path] = []
    for pattern in args.runs:
        expanded = globlib.glob(pattern)
        case_dirs.extend(Path(p) for p in sorted(expanded) if Path(p).is_dir())

    rows: list[dict] = []
    for case_dir in case_dirs:
        stats_path = find_stats(case_dir)
        if stats_path is None:
            print(f"[skip] {case_dir.name}: 无 stats.json")
            continue
        with stats_path.open("r", encoding="utf-8") as f:
            stats = json.load(f)
        timings = stats.get("timings")
        if not timings:
            print(f"[skip] {case_dir.name}: stats.json 无 timings 字段（旧运行，需重跑）")
            continue
        row = {"case": case_dir.name}
        row.update({k: timings.get(k, "") for k in STAGE_KEYS})
        # 修复迭代信息（若有）
        repair = stats.get("llm_repair") or {}
        row["repair_rounds"] = repair.get("rounds", repair.get("iterations", ""))
        rows.append(row)

    if not rows:
        print("无可汇总数据")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["case"] + STAGE_KEYS + ["repair_rounds"]
    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已写出 {len(rows)} 行 -> {args.out}")

    # 终端均值汇总（论文小表直接可用）
    print("\n| 阶段 | 均值 (s) |")
    print("| --- | ---: |")
    for k in STAGE_KEYS:
        vals = [float(r[k]) for r in rows if r.get(k) not in ("", None)]
        if vals:
            print(f"| {k} | {sum(vals) / len(vals):.3f} |")


if __name__ == "__main__":
    main()
