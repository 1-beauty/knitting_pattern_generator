"""
Baseline: Random Valid Action Map.

生成满足硬约束（H1-H8）的随机动作网格，验证"合法 ≠ 语义一致"。
流程：
1. 随机生成 40x40 动作网格（以安全动作为主）
2. 通过硬约束检查，不通过则重新生成
3. 计算工艺违例、语义保真度等指标
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GRID_SIZE
from core import actions
from rules import check_physical, check_craft_actions, tension_score
from utils.logger import logger
from utils.file_io import save_image


TEST_PROMPTS = [
    {"id": "test_01", "prompt": "圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_02", "prompt": "矩形边框包裹圆形，圆形内部为稀疏蜂巢吊目", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_03", "prompt": "矩形边框包裹中心圆形，圆形内部为波浪吊目，背景为平针", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_04", "prompt": "菱形主体，内部蜂巢纹理，背景平针", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_05", "prompt": "六边形结构，内部波浪吊目，背景稀疏网眼", "expected_texture": ["f_split", "f_tuck"]},
]


def generate_random_valid_grid(rng: np.random.Generator, max_attempts: int = 100) -> np.ndarray:
    """Generate a random 40x40 action grid that passes hard constraints.

    Strategy: use mostly safe actions (f_knit, b_knit) with sparse texture
    actions (tuck, split) placed randomly. Retry if hard constraints fail.
    """
    # Safe actions: loop (f_knit=0, b_knit=1) and tuck (f_tuck, b_tuck)
    safe_actions = list(actions.loop_ids() | actions.tuck_ids())
    # Add some split actions for diversity
    all_actions = safe_actions + list(actions.split_ids())

    for _ in range(max_attempts):
        # Generate random grid: 85% safe actions, 15% any action
        grid = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                if rng.random() < 0.85:
                    grid[r, c] = rng.choice(list(safe_actions))
                else:
                    grid[r, c] = rng.choice(list(all_actions))

        # Check hard constraints
        hard = check_physical(grid)
        if len(hard) == 0:
            return grid

    # Fallback: return all f_knit (always valid but degenerate)
    logger.warning("Random valid grid: failed to find valid grid after max attempts, using fallback")
    return np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)


def evaluate_grid(grid: np.ndarray, expected_texture: List[str] = None) -> Dict[str, Any]:
    hard = check_physical(grid)
    craft = check_craft_actions(grid)
    tension = tension_score(grid)

    uniq, counts = np.unique(grid, return_counts=True)
    distribution = {actions.abbr(int(i)): int(c) for i, c in zip(uniq, counts)}

    semantic_score = -1.0
    if expected_texture:
        expected_ids = set()
        for abbr in expected_texture:
            idx = actions.idx_safe(abbr, default=-1)
            if idx >= 0:
                expected_ids.add(idx)
        if expected_ids:
            present = sum(1 for a in expected_ids if a in uniq)
            semantic_score = present / len(expected_ids)

    return {
        "hard_violations": len(hard),
        "craft_violations": len(craft),
        "tension_score": round(tension, 4),
        "action_diversity": len(uniq),
        "semantic_fidelity": round(semantic_score, 4) if semantic_score >= 0 else "N/A",
        "distribution": distribution,
    }


def main():
    parser = argparse.ArgumentParser(description="Random Valid Action Map baseline")
    parser.add_argument("--output", "-o", type=str, default="../outputs/runs/baseline/random_valid")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-attempts", type=int, default=100)
    parser.add_argument("--inputs-file", type=str, default=None,
                        help="Path to JSON file with test prompts (overrides built-in TEST_PROMPTS)")
    args = parser.parse_args()

    # Load test prompts from file if provided
    prompts = TEST_PROMPTS
    if args.inputs_file:
        inputs_path = Path(args.inputs_file)
        if not inputs_path.exists():
            print(f"Error: inputs file not found: {inputs_path}")
            sys.exit(1)
        with open(inputs_path, "r", encoding="utf-8") as f:
            prompts = json.load(f)
        print(f"Loaded {len(prompts)} test prompts from {inputs_path}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed)
    all_results = []

    for test in prompts:
        test_id = test["id"]
        prompt = test["prompt"]
        expected = test.get("expected_texture", [])

        print(f"\n{'='*60}")
        print(f"Test: {test_id} | Prompt: {prompt}")
        print(f"{'='*60}")

        t0 = time.time()
        grid = generate_random_valid_grid(rng, max_attempts=args.max_attempts)
        exec_time = time.time() - t0

        metrics = evaluate_grid(grid, expected)
        metrics["method"] = "random_valid"
        metrics["method_name"] = "Random Valid Action Map"
        metrics["test_id"] = test_id
        metrics["prompt"] = prompt
        metrics["execution_time"] = round(exec_time, 4)
        metrics["success"] = True

        # Save
        test_dir = output_dir / test_id
        test_dir.mkdir(parents=True, exist_ok=True)
        save_image(grid, test_dir / "action_grid.bmp", palette=actions.build_palette_256())
        from pipeline import action_grid_to_rgb
        rgb = action_grid_to_rgb(grid)
        save_image(rgb, test_dir / "action_grid.png")

        print(f"  hard={metrics['hard_violations']} craft={metrics['craft_violations']} "
              f"tension={metrics['tension_score']} diversity={metrics['action_diversity']} "
              f"semantic={metrics['semantic_fidelity']} time={metrics['execution_time']}s")

        all_results.append(metrics)

    # Summary
    print(f"\n{'='*100}")
    print("RANDOM VALID ACTION MAP BASELINE SUMMARY")
    print(f"{'='*100}")

    hard_avg = np.mean([r["hard_violations"] for r in all_results])
    craft_avg = np.mean([r["craft_violations"] for r in all_results])
    tension_avg = np.mean([r["tension_score"] for r in all_results])
    div_avg = np.mean([r["action_diversity"] for r in all_results])
    sem_vals = [r["semantic_fidelity"] for r in all_results if isinstance(r.get("semantic_fidelity"), (int, float))]
    sem_avg = np.mean(sem_vals) if sem_vals else "N/A"
    time_avg = np.mean([r["execution_time"] for r in all_results])

    print(f"{'Method':<30} {'Success':>8} {'Hard↓':>8} {'Craft↓':>8} {'Tension↓':>10} {'Diversity':>10} {'Semantic↑':>10} {'Time(s)↓':>10}")
    print(f"{'Random Valid Action Map':<30} {len(all_results)}/{len(all_results):>8} {hard_avg:>8.1f} {craft_avg:>8.1f} {tension_avg:>10.4f} {div_avg:>10.1f} {str(sem_avg):>10} {time_avg:>10.4f}")

    # Save
    serializable = []
    for r in all_results:
        r_copy = dict(r)
        if "distribution" in r_copy:
            r_copy["distribution"] = dict(r_copy["distribution"])
        serializable.append(r_copy)

    with open(output_dir / "random_valid_results.json", "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_dir / 'random_valid_results.json'}")


if __name__ == "__main__":
    main()
