"""
主入口脚本 v8.0 (morphology-aware)
"""

import argparse
import json
import sys
from pathlib import Path

from utils.logger import logger


def main():
    parser = argparse.ArgumentParser(
        description="Knitting Pattern Generator v8.0 (Morphology-Aware)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 生成图案
  python main.py generate "中心麻花菱形"
  python main.py generate "整幅波浪吊目纹理"
  python main.py generate "中间柱状纹理两侧罗纹边带"
  python main.py generate "带边框的网眼菱形"

  # 指定输出目录
  python main.py generate "中心麻花菱形" -o outputs/images

  # 保存中间结果
  python main.py generate "中心麻花菱形" --save-intermediate

  # 禁用 refinement
  python main.py generate "中心麻花菱形" --no-refinement

  # 禁用 aesthetic pass
  python main.py generate "中心麻花菱形" --no-aesthetic

  # 禁用 LLM repair
  python main.py generate "中心麻花菱形" --no-repair
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ========== generate 子命令 ==========
    gen_parser = subparsers.add_parser("generate", help="生成图案")
    gen_parser.add_argument(
        "prompt",
        type=str,
        help="文本描述（中文或英文）"
    )
    gen_parser.add_argument(
        "--output", "-o",
        type=str,
        default="outputs/images",
        help="输出目录（默认 outputs/images）"
    )
    gen_parser.add_argument(
        "--prefix",
        type=str,
        default="pattern",
        help="输出文件前缀（默认 pattern）"
    )
    gen_parser.add_argument(
        "--save-intermediate",
        action="store_true",
        help="保存中间结果"
    )
    gen_parser.add_argument(
        "--no-refinement",
        action="store_true",
        help="禁用 refinement 编译"
    )
    gen_parser.add_argument(
        "--no-aesthetic",
        action="store_true",
        help="禁用 aesthetic pass"
    )
    gen_parser.add_argument(
        "--no-repair",
        action="store_true",
        help="禁用 LLM repair"
    )
    gen_parser.add_argument(
        "--plan-in",
        type=str,
        default=None,
        help="读取已有 pattern_plan.json，用于增量修改"
    )
    gen_parser.add_argument(
        "--no-plan",
        action="store_true",
        help="[基线] 跳过 PatternPlan 层次化结构计划，直接使用扁平 VisualSpec"
    )

    # ========== random 子命令 ==========
    random_parser = subparsers.add_parser("random", help="随机生成图案")
    random_parser.add_argument(
        "prompt",
        nargs="?",
        default="随机生成一个针织图案",
        help="可选风格描述"
    )
    random_parser.add_argument("--output", "-o", type=str, default="outputs/images")
    random_parser.add_argument("--prefix", type=str, default="pattern")
    random_parser.add_argument("--save-intermediate", action="store_true")
    random_parser.add_argument("--no-refinement", action="store_true")
    random_parser.add_argument("--no-aesthetic", action="store_true")
    random_parser.add_argument("--no-repair", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command in {"generate", "random"}:
        run_generation(args)
    else:
        parser.print_help()


def run_generation(args):
    """运行生成"""
    from llm.client import LLMClient
    from pipeline import KnittingPipeline, PipelineConfig
    from generation.pattern_plan import PatternPlan

    logger.info("=" * 60)
    logger.info("Knitting Pattern Generator v8.0")
    prompt = args.prompt
    if args.command == "random" and "随机" not in prompt and "random" not in prompt.lower():
        prompt = f"随机生成：{prompt}"
    logger.info(f"Prompt: {prompt}")
    logger.info("=" * 60)

    # 对齐 v8.0 的 PipelineConfig
    config = PipelineConfig(
        enable_refinement=not args.no_refinement,
        enable_aesthetic=not args.no_aesthetic,
        enable_llm_repair=not args.no_repair,
        save_intermediate=args.save_intermediate,
        skip_pattern_plan=getattr(args, 'no_plan', False),
    )

    llm_client = LLMClient()
    pipeline = KnittingPipeline(
        llm_client=llm_client,
        rasterizer=None,   # v8.0 主路线不依赖旧 rasterizer
        config=config,
    )

    current_plan = None
    plan_in = getattr(args, "plan_in", None)
    if plan_in:
        plan_in = Path(plan_in)
        if not plan_in.is_absolute() and not plan_in.exists():
            project_plan_in = Path(__file__).resolve().parents[1] / plan_in
            if project_plan_in.exists():
                plan_in = project_plan_in
        with open(plan_in, "r", encoding="utf-8") as f:
            current_plan = PatternPlan.from_dict(json.load(f))
        logger.info(f"Loaded current pattern plan: {plan_in}")

    result = pipeline.generate(prompt, current_plan=current_plan)

    output_dir = Path(args.output)
    pipeline.save_results(result, output_dir, prefix=args.prefix)

    # 输出统计
    logger.info("=" * 60)
    logger.info("Generation completed!")
    logger.info(f"Output dir: {output_dir}")
    logger.info(f"Execution time: {result.execution_time:.2f}s")

    dist = result.statistics.get("distribution", {})
    if dist:
        logger.info("Action distribution:")
        for name, count in sorted(dist.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {name}: {count}")

    tension = result.statistics.get("tension_score")
    if tension is not None:
        logger.info(f"Tension score: {tension:.4f}")

    schema = result.statistics.get("schema_version", "unknown")
    layout = result.statistics.get("layout_type", "unknown")
    logger.info(f"Schema: {schema}, Layout: {layout}")

    zones = result.statistics.get("zones")
    if zones:
        logger.info(f"Zones: {zones}")

    skeletons = result.statistics.get("skeletons")
    if skeletons:
        logger.info(f"Skeletons: {skeletons}")

    regions = result.statistics.get("regions")
    if regions:
        logger.info(f"Regions: {regions}")

    violations = result.statistics.get("violations", {})
    if violations:
        logger.info(
            f"Violations: hard={violations.get('hard_after', 0)}, "
            f"craft={violations.get('craft_after', 0)}"
        )

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
