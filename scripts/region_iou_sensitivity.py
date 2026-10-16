"""Region IoU 闭运算敏感性分析（回应审稿意见：5x5 闭运算是否影响结论）。

对表 7 的两种设置（Ours = ablation/abl_0X_full，Plan-Grid = internal_baseline/
abl_0X_plangrid）在 radius = 0/1/2/3（对应 无闭运算/3x3/5x5/7x7）下重算
Region IoU，验证"事件级编译 > 密集填充"的结论对该形态学参数不敏感。
泄漏率与成组完整率不依赖闭运算（原始格计算），仅报告一次作对照。

用法：
    python scripts/region_iou_sensitivity.py
输出：
    outputs/analysis/region_iou_sensitivity.csv + 终端 Markdown 汇总
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from region_metrics import evaluate_case, load_abbr_to_idx  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
RADII = [0, 1, 2, 3]  # 0=无闭运算, 1=3x3, 2=5x5(论文默认), 3=7x7

SETTINGS = {
    "Ours": sorted((REPO_ROOT / "outputs/runs/ablation").glob("abl_0[1-8]_full")),
    "Plan-Grid": sorted((REPO_ROOT / "outputs/runs/internal_baseline").glob("abl_0[1-8]_plangrid")),
}


def main() -> None:
    abbr_to_idx = load_abbr_to_idx()
    for name, dirs in SETTINGS.items():
        print(f"[info] {name}: {len(dirs)} 个案例目录 -> {[d.name for d in dirs]}")

    all_rows: list[dict] = []
    summary: dict[tuple[str, int], list[float]] = {}
    leak_summary: dict[str, list[float]] = {}
    for name, dirs in SETTINGS.items():
        for radius in RADII:
            ious: list[float] = []
            for case_dir in dirs:
                for r in evaluate_case(case_dir, radius, abbr_to_idx):
                    if r["region_iou"]:
                        ious.append(float(r["region_iou"]))
                        all_rows.append({
                            "setting": name, "radius": radius,
                            "kernel": f"{2 * radius + 1}x{2 * radius + 1}" if radius else "none",
                            "case": r["case"], "motif_id": r["motif_id"],
                            "region_iou": r["region_iou"], "leakage": r["leakage"],
                        })
                    if radius == 0 and r["leakage"]:
                        leak_summary.setdefault(name, []).append(float(r["leakage"]))
            summary[(name, radius)] = ious

    out = REPO_ROOT / "outputs/analysis/region_iou_sensitivity.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    print("\n| 设置 | 无闭运算 | 3×3 | 5×5（正文） | 7×7 | 泄漏率（不受影响） |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name in SETTINGS:
        cells = " | ".join(
            f"{np.mean(summary[(name, r)]):.3f} (n={len(summary[(name, r)])})" for r in RADII
        )
        leak = np.mean(leak_summary[name])
        print(f"| {name} | {cells} | {leak:.3f} |")

    print("\n各档下 Ours − Plan-Grid 的 Region IoU 差值：")
    for r in RADII:
        d = np.mean(summary[("Ours", r)]) - np.mean(summary[("Plan-Grid", r)])
        kernel = f"{2 * r + 1}x{2 * r + 1}" if r else "none"
        print(f"  radius={r} ({kernel}): Δ = {d:+.3f}")
    print(f"\n逐 motif 结果已写入 {out}")


if __name__ == "__main__":
    main()
