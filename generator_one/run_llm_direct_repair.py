# -*- coding: utf-8 -*-
"""LLM-Direct + 规则约束修复 基线（论文 4.3.1 新增行，表 5）。

协议：
- 复用 outputs/runs/baseline_comparison/test_XX/llm_direct/output.bmp 在案的
  LLM-Direct 原始输出（8-bit 调色板 BMP，像素值=动作索引）；
- 主协议（单轮）：与完整系统 pipeline._step7 完全一致的确定性修复——
  fix_physical 一次 + fix_craft_actions 一次，随后报告残余违例；
- 附加记录：30 轮迭代中违例最少的网格（best-of-30），用于正文说明
  后验修复在大面积镂空区域的 H2/H6 震荡与平台现象；
- 指标入口与 run_baselines.evaluate_grid 完全一致。

用法：
    cd generator_one
    python run_llm_direct_repair.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import actions
from rules import (
    check_physical,
    check_craft_actions,
    fix_physical,
    fix_craft_actions,
)
from run_baselines import TEST_PROMPTS, evaluate_grid
from pipeline import action_grid_to_rgb
from utils.file_io import save_image

BASE_DIR = Path(__file__).resolve().parent.parent / "outputs" / "runs" / "baseline_comparison"
METHOD_KEY = "llm_direct_repair"
METHOD_NAME = "LLM-Direct+Repair"
ITER_ROUNDS = 30


def load_grid(bmp_path: Path) -> np.ndarray:
    return np.array(Image.open(bmp_path)).astype(int)


def single_pass(grid: np.ndarray) -> np.ndarray:
    """与 pipeline._step7 一致的单轮确定性修复。"""
    fixed = grid.copy()
    hard = check_physical(fixed)
    if hard:
        fixed = fix_physical(fixed, hard)
    craft = check_craft_actions(fixed)
    if craft:
        fixed = fix_craft_actions(fixed, craft)
    return fixed


def best_of_rounds(grid: np.ndarray, rounds: int) -> tuple:
    """迭代修复并保留硬违例最少的网格；返回 (best_grid, best_hard, trajectory)。"""
    g = grid.copy()
    best_hard = len(check_physical(g))
    best = g.copy()
    traj = [best_hard]
    for _ in range(rounds):
        g = single_pass(g)
        h = len(check_physical(g))
        traj.append(h)
        if h < best_hard:
            best_hard = h
            best = g.copy()
    return best, best_hard, traj


def main():
    archived = json.load(open(BASE_DIR / "baseline_comparison.json", encoding="utf-8"))
    archived_llm = {r["test_id"]: r for r in archived if r["method"] == "llm_direct"}

    results = []
    header = "{:<8} {:>6} {:>7} {:>7} {:>6} {:>8} {:>4} {:>6} {:>8}".format(
        "test", "before", "single", "best30", "craft", "tension", "div", "sem", "match")
    print(header)
    for test in TEST_PROMPTS:
        test_id = test["id"]
        grid = load_grid(BASE_DIR / test_id / "llm_direct" / "output.bmp")

        before = evaluate_grid(grid, test.get("expected_texture", []))
        ref = archived_llm.get(test_id, {})
        match = (before["hard_violations"] == ref.get("hard_violations")
                 and before["tension_score"] == ref.get("tension_score")
                 and before["distribution"] == ref.get("distribution"))

        t0 = time.time()
        fixed = single_pass(grid)
        best, best_hard, traj = best_of_rounds(grid, ITER_ROUNDS)
        elapsed = time.time() - t0

        m = evaluate_grid(fixed, test.get("expected_texture", []))
        m.update({
            "method": METHOD_KEY,
            "method_name": METHOD_NAME,
            "test_id": test_id,
            "prompt": test["prompt"],
            "execution_time": round(elapsed, 2),
            "success": True,
            "hard_before": before["hard_violations"],
            "craft_before": before["craft_violations"],
            "hard_best30": best_hard,
            "hard_trajectory": traj,
            "metrics_match_archived": match,
        })
        results.append(m)

        out_dir = BASE_DIR / test_id / METHOD_KEY
        out_dir.mkdir(parents=True, exist_ok=True)
        save_image(fixed, out_dir / "output.bmp", palette=actions.build_palette_256())
        save_image(action_grid_to_rgb(fixed), out_dir / "output.png")
        save_image(best, out_dir / "output_best30.bmp", palette=actions.build_palette_256())
        save_image(action_grid_to_rgb(best), out_dir / "output_best30.png")

        print("{:<8} {:>6} {:>7} {:>7} {:>6} {:>8} {:>4} {:>6} {:>8}".format(
            test_id, before["hard_violations"], m["hard_violations"], best_hard,
            m["craft_violations"], m["tension_score"], m["action_diversity"],
            m["semantic_fidelity"], "OK" if match else "MISMATCH!"))

    out_json = BASE_DIR / "llm_direct_repair.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    def avg(key):
        vals = [r[key] for r in results if isinstance(r[key], (int, float))]
        return float(np.mean(vals))

    print("\n=== LLM-Direct+Repair（单轮协议，n=%d）===" % len(results))
    print("  hard: %.1f -> %.1f（zero: %d/10）; best-of-30 hard: %.1f（zero: %d/10）" % (
        avg("hard_before"), avg("hard_violations"),
        sum(1 for r in results if r["hard_violations"] == 0),
        avg("hard_best30"),
        sum(1 for r in results if r["hard_best30"] == 0)))
    print("  craft_avg: %.2f  tension_avg: %.4f  diversity_avg: %.2f  semantic_avg: %.4f  time_avg: %.3f" % (
        avg("craft_violations"), avg("tension_score"), avg("action_diversity"),
        avg("semantic_fidelity"), avg("execution_time")))
    print("保存:", out_json)


if __name__ == "__main__":
    main()
