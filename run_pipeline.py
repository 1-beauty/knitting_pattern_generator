"""
Unified entry point for the knitting pattern project.

Modes:
  color       text prompt -> color-code map
  simulate   color-code map -> simulation image
  all        text prompt -> color-code map -> simulation image
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GENERATOR_DIR = ROOT / "generator_one"
SIMULATOR_DIR = ROOT / "conditional-flow-matching-main"


def has_cuda():
    try:
        import torch
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def resolve_device(requested):
    if requested == "auto":
        return "cuda" if has_cuda() else "cpu"
    if requested == "cuda" and not has_cuda():
        print("Warning: CUDA was requested but is not available. Falling back to CPU.")
        return "cpu"
    return requested


def run_command(cmd, cwd):
    print("\n" + "=" * 80)
    print("cwd:", cwd)
    print("cmd:", " ".join(str(x) for x in cmd))
    print("=" * 80)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def inference_supports_arg(arg_name):
    inference_path = SIMULATOR_DIR / "knitting" / "inference.py"
    if not inference_path.exists():
        return False
    try:
        return arg_name in inference_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return arg_name in inference_path.read_text(encoding="utf-8", errors="ignore")


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_dir_from_sim_input(input_path):
    """Derive the run directory from a sim_input.png path.

    Supports both flat (outputs/runs/<name>/color_map/...) and
    nested (outputs/runs/<category>/<name>/color_map/...) layouts.
    """
    try:
        rel = input_path.resolve().relative_to((ROOT / "outputs" / "runs").resolve())
    except ValueError:
        return None
    parts = rel.parts
    # Find the 'color_map' segment; everything before it is the run name
    try:
        cm_idx = list(parts).index("color_map")
    except ValueError:
        return None
    if cm_idx >= 1:
        return ROOT / "outputs" / "runs" / Path(*parts[:cm_idx])
    return None


def generate_color_map(args, run_dir):
    color_dir = run_dir / "color_map"
    prefix = args.prefix or "pattern"

    cmd = [
        sys.executable,
        "main.py",
        "generate",
        args.prompt,
        "--output",
        str(color_dir),
        "--prefix",
        prefix,
    ]

    if args.save_intermediate:
        cmd.append("--save-intermediate")
    if args.no_refinement:
        cmd.append("--no-refinement")
    if args.no_aesthetic:
        cmd.append("--no-aesthetic")
    if args.no_repair:
        cmd.append("--no-repair")
    if getattr(args, "no_plan", False):
        cmd.append("--no-plan")
    fixed_plan = getattr(args, "fixed_plan", None)
    if fixed_plan:
        fp = Path(fixed_plan)
        if not fp.is_absolute():
            fp = (ROOT / fp).resolve()
        cmd.extend(["--fixed-plan", str(fp)])
    if getattr(args, "plan_in", None):
        plan_in = Path(args.plan_in)
        if not plan_in.is_absolute():
            plan_in = (ROOT / plan_in).resolve()
        cmd.extend(["--plan-in", str(plan_in)])

    run_command(cmd, GENERATOR_DIR)

    color_path = color_dir / f"{prefix}_output.bmp"
    if not color_path.exists():
        raise FileNotFoundError(f"Color map was not created: {color_path}")

    sim_input_path = color_dir / f"{prefix}_sim_input.png"
    if not sim_input_path.exists():
        raise FileNotFoundError(f"Simulation input PNG was not created: {sim_input_path}")
    return color_path, sim_input_path


def simulate_color_map(args, input_path, run_dir):
    input_path = Path(input_path)
    if not input_path.is_absolute():
        input_path = (ROOT / input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(
            "Color-map input does not exist. Replace the example path with a real file, "
            f"for example: {ROOT / 'outputs' / 'runs' / '20260601_154724' / 'color_map' / 'pattern_output.bmp'}\n"
            f"Missing path: {input_path}"
        )

    json_path = Path(args.json_path)
    if not json_path.is_absolute():
        json_path = (ROOT / json_path).resolve()
    if not json_path.exists():
        raise FileNotFoundError(f"instructions.json does not exist: {json_path}")

    sim_dir = run_dir / "simulation"
    sim_dir.mkdir(parents=True, exist_ok=True)

    if args.num_candidates > 1:
        output_path = sim_dir / f"stage{args.stage}_candidates_grid.png"
        candidate_dir = sim_dir / f"stage{args.stage}_candidates"
    else:
        output_path = sim_dir / f"stage{args.stage}_result.png"
        candidate_dir = None

    checkpoint = args.checkpoint
    if checkpoint is None:
        checkpoint = SIMULATOR_DIR / "checkpoints" / f"stage{args.stage}" / "best.pt"
    checkpoint = Path(checkpoint)
    if not checkpoint.is_absolute():
        checkpoint = (ROOT / checkpoint).resolve()
    if not checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint does not exist: {checkpoint}")

    device = resolve_device(args.device)

    cmd = [
        sys.executable,
        "knitting/inference.py",
        "--stage",
        str(args.stage),
        "--checkpoint",
        str(checkpoint),
        "--input",
        str(input_path),
        "--input_source",
        "stage1" if run_dir_from_sim_input(input_path) is not None else "dataset",
        "--output",
        str(output_path),
        "--json_path",
        str(json_path),
        "--device",
        device,
        "--seed",
        str(args.seed),
        "--num_candidates",
        str(args.num_candidates),
        "--seed_stride",
        str(args.seed_stride),
        "--noise_mode",
        args.noise_mode,
    ]

    if args.num_steps is not None:
        cmd.extend(["--num_steps", str(args.num_steps)])
    if args.solver is not None:
        cmd.extend(["--solver", args.solver])
    if args.perturb_scale is not None:
        cmd.extend(["--perturb_scale", str(args.perturb_scale)])
    if args.batch_size is not None and inference_supports_arg("--batch_size"):
        cmd.extend(["--batch_size", str(args.batch_size)])
    if args.num_candidates > 1:
        cmd.extend(["--candidate_dir", str(candidate_dir), "--save_grid"])

    run_command(cmd, SIMULATOR_DIR)

    if not output_path.exists() and args.num_candidates == 1:
        raise FileNotFoundError(f"Simulation image was not created: {output_path}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run color-map generation, simulation, or both.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run-name", default=None, help="Output folder name under outputs/runs")
    common.add_argument("--stage", type=int, default=4, choices=[1, 2, 3, 4])
    common.add_argument("--checkpoint", type=Path, default=None)
    common.add_argument(
        "--json_path",
        type=Path,
        default=SIMULATOR_DIR / "assets" / "instructions.json",
    )
    common.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    common.add_argument("--seed", type=int, default=42)
    common.add_argument("--num_candidates", type=int, default=1)
    common.add_argument("--seed_stride", type=int, default=1)
    common.add_argument(
        "--noise_mode",
        default="auto",
        choices=["auto", "independent", "global_correlated", "region_correlated"],
    )
    common.add_argument("--num_steps", type=int, default=None)
    common.add_argument("--solver", default=None, choices=["euler", "midpoint", "rk4"])
    common.add_argument("--perturb_scale", type=float, default=None)
    common.add_argument("--batch_size", type=int, default=100)

    color = subparsers.add_parser("color", parents=[common], help="Generate color map only")
    color.add_argument("prompt")
    color.add_argument("--prefix", default=None)
    color.add_argument("--save-intermediate", action="store_true")
    color.add_argument("--no-refinement", action="store_true")
    color.add_argument("--no-aesthetic", action="store_true")
    color.add_argument("--no-repair", action="store_true")
    color.add_argument("--plan-in", type=Path, default=None)
    color.add_argument("--no-plan", action="store_true",
                       help="[基线] 跳过 PatternPlan 层次化结构计划")
    color.add_argument("--fixed-plan", type=Path, default=None,
                       help="[消融] 加载固定 plan，跳过 LLM")

    sim = subparsers.add_parser("simulate", parents=[common], help="Run simulation only")
    sim.add_argument("--input", required=True, type=Path, help="Existing color map path")

    all_mode = subparsers.add_parser("all", parents=[common], help="Generate color map and simulation")
    all_mode.add_argument("prompt")
    all_mode.add_argument("--prefix", default=None)
    all_mode.add_argument("--save-intermediate", action="store_true")
    all_mode.add_argument("--no-refinement", action="store_true")
    all_mode.add_argument("--no-aesthetic", action="store_true")
    all_mode.add_argument("--no-repair", action="store_true")
    all_mode.add_argument("--plan-in", type=Path, default=None)
    all_mode.add_argument("--no-plan", action="store_true",
                          help="[基线] 跳过 PatternPlan 层次化结构计划")
    all_mode.add_argument("--fixed-plan", type=Path, default=None,
                          help="[消融] 加载固定 plan，跳过 LLM")

    return parser.parse_args()


def main():
    args = parse_args()
    if args.mode == "simulate" and args.run_name is None:
        inferred = run_dir_from_sim_input(Path(args.input))
        run_dir = inferred if inferred is not None else ROOT / "outputs" / "runs" / timestamp()
    else:
        run_name = args.run_name or timestamp()
        run_dir = ROOT / "outputs" / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "color":
        color_path, sim_input_path = generate_color_map(args, run_dir)
        print(f"\nColor map: {color_path}")
        print(f"Simulation input: {sim_input_path}")
    elif args.mode == "simulate":
        sim_path = simulate_color_map(args, args.input, run_dir)
        print(f"\nSimulation: {sim_path}")
    elif args.mode == "all":
        color_path, sim_input_path = generate_color_map(args, run_dir)
        sim_path = simulate_color_map(args, sim_input_path, run_dir)
        print(f"\nColor map:        {color_path}")
        print(f"Simulation input: {sim_input_path}")
        print(f"Simulation:       {sim_path}")
    else:
        raise ValueError(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
