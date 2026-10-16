"""
Baseline: Text-to-Image + Color Quantization.

流程：
1. 用 Stable Diffusion 2.1 从文本描述生成针织视觉图
2. Resize 到 40x40
3. 最近邻颜色量化映射到 15 色动作空间
4. 计算 H1-H8、C1-C6、语义保真度等指标

这个基线直接验证论文核心论点：通用视觉图像不能直接变成针织动作图。
"""

import argparse
import json
import os
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


# ============================================================
# Test prompts (same as run_baselines.py)
# ============================================================

TEST_PROMPTS = [
    {"id": "test_01", "prompt": "圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_02", "prompt": "矩形边框包裹圆形，圆形内部为稀疏蜂巢吊目", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_03", "prompt": "矩形边框包裹中心圆形，圆形内部为波浪吊目，背景为平针", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_04", "prompt": "菱形主体，内部蜂巢纹理，背景平针", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_05", "prompt": "六边形结构，内部波浪吊目，背景稀疏网眼", "expected_texture": ["f_split", "f_tuck"]},
]


# ============================================================
# Color quantization: RGB image -> action grid
# ============================================================

def _build_action_palette() -> np.ndarray:
    """Build (15, 3) array of action RGB colors."""
    palette = np.zeros((actions.NUM_ACTIONS, 3), dtype=np.float64)
    for i in range(actions.NUM_ACTIONS):
        palette[i] = actions.color_rgb(i)
    return palette


def rgb_to_action_grid(image_rgb: np.ndarray) -> np.ndarray:
    """Quantize RGB image to 40x40 action grid via nearest-neighbor color matching.

    Args:
        image_rgb: RGB image, shape (H, W, 3), dtype uint8

    Returns:
        grid: action indices, shape (40, 40), dtype uint8
    """
    palette = _build_action_palette()  # (15, 3)

    # Resize to 40x40 using nearest neighbor
    from PIL import Image
    pil_img = Image.fromarray(image_rgb)
    pil_img = pil_img.resize((GRID_SIZE, GRID_SIZE), Image.NEAREST)
    img = np.array(pil_img).astype(np.float64)  # (40, 40, 3)

    # Compute distance from each pixel to each palette color
    # img: (40, 40, 3), palette: (15, 3)
    # dists: (40, 40, 15)
    dists = np.linalg.norm(img[:, :, None, :] - palette[None, None, :, :], axis=-1)
    grid = np.argmin(dists, axis=-1).astype(np.uint8)

    return grid


# ============================================================
# T2I generation
# ============================================================

def generate_t2i_image(prompt: str, model, pipe_kwargs: Dict) -> np.ndarray:
    """Generate an image from text prompt using Stable Diffusion.

    Returns:
        image_rgb: RGB image, shape (H, W, 3), dtype uint8
    """
    # English translation hint for better T2I results
    # SD models work better with English prompts
    en_prompt = _translate_hint(prompt)

    image = model(
        prompt=en_prompt,
        **pipe_kwargs,
    ).images[0]

    return np.array(image.convert("RGB"))


def _translate_hint(cn_prompt: str) -> str:
    """Provide English hint for T2I model.

    Since we don't have a translator, use a generic knitting texture prompt
    that captures the key visual elements.
    """
    # Map common Chinese knitting terms to English visual descriptions
    hints = {
        "圆形": "circular pattern",
        "矩形边框": "rectangular border frame",
        "矩形框架": "rectangular frame",
        "菱形": "diamond shape",
        "六边形": "hexagon shape",
        "三角形": "triangle shape",
        "心形": "heart shape",
        "波浪吊目": "wave tuck texture with raised bumps",
        "蜂巢吊目": "honeycomb texture pattern",
        "蜂巢纹理": "honeycomb texture",
        "绞花麻花": "cable knit crossover texture",
        "麻花": "cable knit texture",
        "镂空网眼": "lace openwork mesh pattern",
        "网眼": "mesh openwork pattern",
        "稀疏网眼": "sparse mesh pattern",
        "条纹": "vertical stripe pattern",
        "竖条纹": "vertical stripes",
        "罗纹": "ribbed knit texture",
        "平针": "plain jersey knit background",
        "背景平针": "plain knit background",
        "背景": "background",
        "包裹": "surrounding",
        "居中": "centered",
        "内部": "inner",
        "外部": "outer",
        "双菱形并排": "two diamonds side by side",
        "浮雕凸起": "raised relief texture",
        "密集": "dense",
        "稀疏": "sparse",
    }

    # Build English prompt by keyword matching
    en_parts = ["knitted fabric texture close-up photo, "]
    matched = False
    for cn, en in hints.items():
        if cn in cn_prompt:
            en_parts.append(en + ", ")
            matched = True

    if not matched:
        en_parts.append("textured knitted fabric pattern, ")

    en_parts.append("high detail, realistic textile photography")
    return "".join(en_parts)


# ============================================================
# Evaluation
# ============================================================

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


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="T2I + Color Quantization baseline")
    parser.add_argument("--output", "-o", type=str, default="../outputs/runs/baseline/t2i_quantization")
    parser.add_argument("--model-id", type=str, default="runwayml/stable-diffusion-v1-5",
                        help="HuggingFace model ID for T2I generation")
    parser.add_argument("--local-model", type=str, default=None,
                        help="Local model path (bypass download, use for offline servers)")
    parser.add_argument("--num-inference-steps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
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

    # Lazy import diffusers (not a project dependency)
    try:
        import torch
        from diffusers import StableDiffusionPipeline
    except ImportError:
        print("ERROR: diffusers not installed. Run: pip install diffusers transformers accelerate")
        print("Then download the model: python -c 'from diffusers import StableDiffusionPipeline; StableDiffusionPipeline.from_pretrained(\"runwayml/stable-diffusion-v1-5\")'")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model
    model_source = args.local_model or args.model_id
    print(f"Loading T2I model: {model_source}")
    if args.local_model:
        print("(Using local model path)")
    else:
        print("(First run will download ~2.6GB model weights)")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    pipe = StableDiffusionPipeline.from_pretrained(
        model_source,
        torch_dtype=dtype,
        safety_checker=None,
    )
    pipe = pipe.to(device)
    print(f"Model loaded on {device}")

    pipe_kwargs = {
        "num_inference_steps": args.num_inference_steps,
        "generator": torch.Generator(device=device).manual_seed(args.seed),
    }

    all_results = []

    for test in prompts:
        test_id = test["id"]
        prompt = test["prompt"]
        expected = test.get("expected_texture", [])

        print(f"\n{'='*60}")
        print(f"Test: {test_id} | Prompt: {prompt}")
        print(f"{'='*60}")

        try:
            t0 = time.time()

            # Step 1: Generate image from text
            en_hint = _translate_hint(prompt)
            print(f"  EN hint: {en_hint[:80]}...")
            image_rgb = generate_t2i_image(prompt, pipe, pipe_kwargs)
            print(f"  Generated image: {image_rgb.shape}")

            # Step 2: Quantize to action grid
            grid = rgb_to_action_grid(image_rgb)
            print(f"  Action grid: {grid.shape}, unique actions: {len(np.unique(grid))}")

            exec_time = time.time() - t0

            # Step 3: Evaluate
            metrics = evaluate_grid(grid, expected)
            metrics["method"] = "t2i_quantization"
            metrics["method_name"] = "T2I + Color Quantization"
            metrics["test_id"] = test_id
            metrics["prompt"] = prompt
            metrics["execution_time"] = round(exec_time, 2)
            metrics["success"] = True

            # Save outputs
            test_dir = output_dir / test_id
            test_dir.mkdir(parents=True, exist_ok=True)
            save_image(grid, test_dir / "action_grid.bmp", palette=actions.build_palette_256())
            from pipeline import action_grid_to_rgb
            rgb = action_grid_to_rgb(grid)
            save_image(rgb, test_dir / "action_grid.png")
            save_image(image_rgb, test_dir / "t2i_raw.png")

            print(f"  hard={metrics['hard_violations']} craft={metrics['craft_violations']} "
                  f"tension={metrics['tension_score']} diversity={metrics['action_diversity']} "
                  f"semantic={metrics['semantic_fidelity']} time={metrics['execution_time']}s")

        except Exception as e:
            print(f"  FAILED: {e}")
            metrics = {
                "method": "t2i_quantization",
                "method_name": "T2I + Color Quantization",
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

    # Summary
    print(f"\n{'='*100}")
    print("T2I + COLOR QUANTIZATION BASELINE SUMMARY")
    print(f"{'='*100}")

    success_results = [r for r in all_results if r.get("success")]
    if success_results:
        hard_avg = np.mean([r["hard_violations"] for r in success_results])
        craft_avg = np.mean([r["craft_violations"] for r in success_results])
        tension_avg = np.mean([r["tension_score"] for r in success_results])
        div_avg = np.mean([r["action_diversity"] for r in success_results])
        sem_vals = [r["semantic_fidelity"] for r in success_results if isinstance(r.get("semantic_fidelity"), (int, float))]
        sem_avg = np.mean(sem_vals) if sem_vals else "N/A"
        time_avg = np.mean([r["execution_time"] for r in success_results])

        print(f"{'Method':<30} {'Success':>8} {'Hard↓':>8} {'Craft↓':>8} {'Tension↓':>10} {'Diversity':>10} {'Semantic↑':>10} {'Time(s)↓':>10}")
        print(f"{'T2I + Color Quantization':<30} {len(success_results)}/{len(all_results):>8} {hard_avg:>8.1f} {craft_avg:>8.1f} {tension_avg:>10.4f} {div_avg:>10.1f} {str(sem_avg):>10} {time_avg:>10.1f}")

    # Save results
    serializable = []
    for r in all_results:
        r_copy = dict(r)
        if "distribution" in r_copy:
            r_copy["distribution"] = dict(r_copy["distribution"])
        serializable.append(r_copy)

    with open(output_dir / "t2i_baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_dir / 't2i_baseline_results.json'}")


if __name__ == "__main__":
    main()
