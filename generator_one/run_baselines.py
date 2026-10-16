"""
Unified baseline evaluation script.

Runs all methods (Ours, Ours w/o PatternPlan, LLM-Direct) on the same test
set and outputs a comparison table for paper section 4.10.

Usage:
    cd generator_one
    python run_baselines.py
    python run_baselines.py --output ../outputs/runs/baseline_comparison
    python run_baselines.py --methods ours no_plan llm_direct
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

import numpy as np

# Add parent to path so we can import from generator_one
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import GRID_SIZE
from core import actions
from rules import check_physical, check_craft_actions, tension_score
from llm.client import LLMClient
from pipeline import KnittingPipeline, PipelineConfig, action_grid_to_rgb
from baselines.llm_direct import LLMDirectPipeline
from utils.logger import logger
from utils.file_io import save_image


# ============================================================
# Test set
# ============================================================

TEST_PROMPTS = [
    {
        "id": "test_01",
        "prompt": "圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼",
        "expected_texture": ["f_split", "f_tuck"],  # wave actions
    },
    {
        "id": "test_02",
        "prompt": "矩形边框包裹圆形，圆形内部为稀疏蜂巢吊目",
        "expected_texture": ["f_tuck", "b_tuck"],  # honeycomb actions
    },
    {
        "id": "test_03",
        "prompt": "矩形边框包裹中心圆形，圆形内部为波浪吊目，背景为平针",
        "expected_texture": ["f_split", "f_tuck"],
    },
    {
        "id": "test_04",
        "prompt": "菱形主体，内部蜂巢纹理，背景平针",
        "expected_texture": ["f_tuck", "b_tuck"],
    },
    {
        "id": "test_05",
        "prompt": "六边形结构，内部波浪吊目，背景稀疏网眼",
        "expected_texture": ["f_split", "f_tuck"],
    },
    {
        "id": "test_06",
        "prompt": "三角形区域，内部镂空蕾丝，背景平针",
        "expected_texture": ["f_tuck", "b_tuck"],
    },
    {
        "id": "test_07",
        "prompt": "心形图案居中，内部浮雕凸起，背景稀疏网眼",
        "expected_texture": ["f_tuck", "f_split"],
    },
    {
        "id": "test_08",
        "prompt": "菱形内部绞花麻花，背景蜂巢纹理",
        "expected_texture": ["xfer_l1", "xfer_r1", "f_tuck", "b_tuck"],
    },
    {
        "id": "test_09",
        "prompt": "矩形框架，内部竖条纹填充，边框罗纹",
        "expected_texture": ["f_knit", "b_knit"],
    },
    {
        "id": "test_10",
        "prompt": "双菱形并排，左菱形内蜂巢，右菱形内波浪，背景平针",
        "expected_texture": ["f_tuck", "b_tuck", "f_split"],
    },
]


# ============================================================
# Evaluation metrics
# ============================================================

def evaluate_grid(grid: np.ndarray, expected_texture: List[str] = None) -> Dict[str, Any]:
    """Compute all evaluation metrics for a single grid."""
    hard = check_physical(grid)
    craft = check_craft_actions(grid)
    tension = tension_score(grid)

    uniq, counts = np.unique(grid, return_counts=True)
    distribution = {actions.abbr(int(i)): int(c) for i, c in zip(uniq, counts)}

    # Semantic fidelity: check if expected texture actions are present
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


# ============================================================
# Method runners
# ============================================================

def run_ours(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Run the full system (Ours)."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=True,
        save_intermediate=False,
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


def run_no_plan(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Run baseline: Ours w/o PatternPlan (flat hierarchy)."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=True,
        save_intermediate=False,
        skip_pattern_plan=True,
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


def run_llm_direct(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Run baseline: LLM directly outputs 40x40 grid."""
    pipeline = LLMDirectPipeline(llm_client)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result["action_grid"],
        "execution_time": result["execution_time"],
        "success": result["success"],
    }


def run_no_layer_clip(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Run baseline: disable layer clipping (父子层级裁剪)."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=True,
        save_intermediate=False,
        no_layer_clip=True,
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


def run_no_wave_pair(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Run baseline: disable wave pair guard (波浪配对约束)."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=True,
        save_intermediate=False,
        no_wave_pair_guard=True,
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


def run_plan_grid(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Internal baseline: Plan-Grid（dense 密集编译，无修复）."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=False,
        save_intermediate=False,
        compile_mode="dense",
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


def run_plan_grid_repair(llm_client: LLMClient, prompt: str) -> Dict[str, Any]:
    """Internal baseline: Plan-Grid+Repair（dense 密集编译 + 同一 checker/修复）."""
    config = PipelineConfig(
        enable_refinement=True,
        enable_aesthetic=True,
        enable_llm_repair=True,
        save_intermediate=False,
        compile_mode="dense",
    )
    pipeline = KnittingPipeline(llm_client=llm_client, config=config)
    result = pipeline.generate(prompt)
    return {
        "action_grid": result.action_grid_40x40,
        "execution_time": result.execution_time,
        "statistics": result.statistics,
    }


METHODS = {
    "ours": ("Ours (Full)", run_ours),
    "no_plan": ("Ours w/o PatternPlan", run_no_plan),
    "llm_direct": ("LLM-Direct", run_llm_direct),
    "no_layer_clip": ("No Layer Clipping", run_no_layer_clip),
    "no_wave_pair": ("No Wave Pair Guard", run_no_wave_pair),
    "plan_grid": ("Plan-Grid", run_plan_grid),
    "plan_grid_repair": ("Plan-Grid+Repair", run_plan_grid_repair),
}


# ============================================================
# Main evaluation loop
# ============================================================

def run_evaluation(
    methods: List[str],
    output_dir: Path,
) -> List[Dict[str, Any]]:
    """Run all methods on all test prompts and collect results."""
    llm_client = LLMClient()
    all_results = []

    for test in TEST_PROMPTS:
        test_id = test["id"]
        prompt = test["prompt"]
        expected = test.get("expected_texture", [])

        logger.info(f"\n{'='*60}")
        logger.info(f"Test: {test_id} | Prompt: {prompt}")
        logger.info(f"{'='*60}")

        for method_key in methods:
            method_name, method_fn = METHODS[method_key]
            logger.info(f"\n--- Method: {method_name} ---")

            try:
                t0 = time.time()
                result = method_fn(llm_client, prompt)
                grid = result["action_grid"]
                exec_time = result.get("execution_time", time.time() - t0)

                metrics = evaluate_grid(grid, expected)
                metrics["method"] = method_key
                metrics["method_name"] = method_name
                metrics["test_id"] = test_id
                metrics["prompt"] = prompt
                metrics["execution_time"] = round(exec_time, 2)
                metrics["success"] = True

                # Save output
                test_dir = output_dir / test_id / method_key
                test_dir.mkdir(parents=True, exist_ok=True)
                save_image(grid, test_dir / "output.bmp", palette=actions.build_palette_256())
                rgb = action_grid_to_rgb(grid)
                save_image(rgb, test_dir / "output.png")

                logger.info(
                    f"  hard={metrics['hard_violations']} craft={metrics['craft_violations']} "
                    f"tension={metrics['tension_score']} diversity={metrics['action_diversity']} "
                    f"semantic={metrics['semantic_fidelity']} time={metrics['execution_time']}s"
                )

            except Exception as e:
                logger.error(f"  Method {method_name} failed: {e}")
                metrics = {
                    "method": method_key,
                    "method_name": method_name,
                    "test_id": test_id,
                    "prompt": prompt,
                    "success": False,
                    "error": str(e),
                    "hard_violations": -1,
                    "craft_violations": -1,
                    "tension_score": -1.0,
                    "action_diversity": 0,
                    "semantic_fidelity": "N/A",
                    "execution_time": -1,
                }

            all_results.append(metrics)

    return all_results


def print_summary_table(results: List[Dict[str, Any]]):
    """Print a summary comparison table."""
    # Aggregate by method
    method_stats: Dict[str, Dict[str, List]] = {}
    for r in results:
        mk = r["method"]
        if mk not in method_stats:
            method_stats[mk] = {
                "name": r["method_name"],
                "hard": [], "craft": [], "tension": [],
                "diversity": [], "semantic": [], "time": [],
                "success": 0, "total": 0,
            }
        method_stats[mk]["total"] += 1
        if not r.get("success", True):
            continue
        if r["hard_violations"] >= 0:
            method_stats[mk]["hard"].append(r["hard_violations"])
            method_stats[mk]["craft"].append(r["craft_violations"])
            method_stats[mk]["tension"].append(r["tension_score"])
            method_stats[mk]["diversity"].append(r["action_diversity"])
            method_stats[mk]["time"].append(r["execution_time"])
        if r["hard_violations"] == 0:
            method_stats[mk]["success"] += 1
        if isinstance(r.get("semantic_fidelity"), (int, float)) and r["semantic_fidelity"] >= 0:
            method_stats[mk]["semantic"].append(r["semantic_fidelity"])

    # Print table
    print("\n" + "=" * 100)
    print("BASELINE COMPARISON SUMMARY")
    print("=" * 100)
    header = f"{'Method':<25} {'Success':>8} {'Hard↓':>8} {'Craft↓':>8} {'Tension↓':>10} {'Diversity':>10} {'Semantic↑':>10} {'Time(s)↓':>10}"
    print(header)
    print("-" * 100)

    for mk in ["ours", "no_plan", "llm_direct", "no_layer_clip", "no_wave_pair", "plan_grid", "plan_grid_repair"]:
        if mk not in method_stats:
            continue
        s = method_stats[mk]
        name = s["name"]
        success_rate = f"{s['success']}/{s['total']}"
        hard_avg = f"{np.mean(s['hard']):.1f}" if s["hard"] else "N/A"
        craft_avg = f"{np.mean(s['craft']):.1f}" if s["craft"] else "N/A"
        tension_avg = f"{np.mean(s['tension']):.4f}" if s["tension"] else "N/A"
        div_avg = f"{np.mean(s['diversity']):.1f}" if s["diversity"] else "N/A"
        sem_avg = f"{np.mean(s['semantic']):.2f}" if s["semantic"] else "N/A"
        time_avg = f"{np.mean(s['time']):.1f}" if s["time"] else "N/A"
        print(f"{name:<25} {success_rate:>8} {hard_avg:>8} {craft_avg:>8} {tension_avg:>10} {div_avg:>10} {sem_avg:>10} {time_avg:>10}")

    print("=" * 100)


def save_results_json(results: List[Dict[str, Any]], output_dir: Path):
    """Save full results to JSON."""
    # Convert numpy arrays to lists for JSON serialization
    serializable = []
    for r in results:
        r_copy = dict(r)
        if "action_grid" in r_copy:
            r_copy.pop("action_grid")
        if "distribution" in r_copy:
            r_copy["distribution"] = dict(r_copy["distribution"])
        serializable.append(r_copy)

    with open(output_dir / "baseline_comparison.json", "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\nFull results saved to: {output_dir / 'baseline_comparison.json'}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run baseline comparison experiments for paper section 4.10"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="../outputs/runs/baseline_comparison",
        help="Output directory (default: ../outputs/runs/baseline_comparison)",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["ours", "no_plan", "llm_direct", "no_layer_clip", "no_wave_pair"],
        choices=list(METHODS.keys()),
        help="Methods to evaluate (default: all three)",
    )
    parser.add_argument(
        "--inputs-file",
        type=str,
        default=None,
        help="Path to JSON file with test prompts (overrides built-in TEST_PROMPTS)",
    )
    args = parser.parse_args()

    # Load test prompts from file if provided
    global TEST_PROMPTS
    if args.inputs_file:
        inputs_path = Path(args.inputs_file)
        if not inputs_path.exists():
            print(f"Error: inputs file not found: {inputs_path}")
            sys.exit(1)
        with open(inputs_path, "r", encoding="utf-8") as f:
            TEST_PROMPTS = json.load(f)
        print(f"Loaded {len(TEST_PROMPTS)} test prompts from {inputs_path}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nBaseline comparison evaluation")
    print(f"Methods: {args.methods}")
    print(f"Test prompts: {len(TEST_PROMPTS)}")
    print(f"Output: {output_dir}")
    print()

    results = run_evaluation(args.methods, output_dir)
    print_summary_table(results)
    save_results_json(results, output_dir)


if __name__ == "__main__":
    main()
