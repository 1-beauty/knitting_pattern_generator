"""
批量运行针织色码图/仿真生成。

用法（在项目根目录下）：
    python scripts/run_batch.py              # 按下方 INSTRUCTIONS 逐条运行 all 模式
    python scripts/run_batch.py --color-only # 只生成色码图（跳过 Stage 4 视觉预览，更快）
    python scripts/run_batch.py --stage 2    # 指定视觉预览阶段（1-4，默认 4）
    python scripts/run_batch.py --repeat 3   # 每条指令重复运行 3 次（不同随机种子）

每次运行会在 outputs/runs/<run-name>/ 下生成：
    color_map/pattern_output.bmp          色码图
    color_map/pattern_sim_input.png       仿真输入（放大后的色码图）
    color_map/pattern_stitch_legend.json  针法说明（色块 → 针法物理含义，供人工对照工厂色卡）
    color_map/pattern_pattern_plan.json   PatternPlan 结构计划
    color_map/pattern_stats.json          统计信息
    simulation/stage4_result.png          结构感知视觉预览图（all 模式）

针法说明日志同时会打印到控制台。

前置条件：
    1. .env 中配置的 LLM API 可用（PatternPlan 语义解析需要）。
    2. all 模式需要 conditional-flow-matching-main/checkpoints/stage4/best.pt；
       若只想快速拿色码图与针法日志，用 --color-only 即可跳过。
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ==========================================================================
# 在这里增删指令：(run-name, prompt)
# run-name 会作为 outputs/runs/ 下的文件夹名，请保持唯一。
# ==========================================================================
INSTRUCTIONS = [
    ("batch_01", "圆形主体，内部浮雕纹理，背景平针"),
    ("batch_02", "菱形主体，内部蜂巢纹理，背景平针"),
    ("batch_03", "矩形面板，罗纹组织，背景平针"),
    ("batch_04", "心形图案，内部种子针纹理，背景反针"),
    ("batch_05", "星形主体，内部蜂巢纹理，外框罗纹边框"),
    ("batch_06", "椭圆形主体，内部波浪纹理，背景平针"),
    ("batch_07", "六边形主体，内部波纹起伏，背景平针"),
]


def build_cmd(mode, prompt, run_name, stage, seed):
    cmd = [
        sys.executable,
        "run_pipeline.py",
        mode,
        prompt,
        "--run-name",
        run_name,
        "--seed",
        str(seed),
    ]
    if mode == "all":
        cmd += ["--stage", str(stage)]
    return cmd


def main():
    parser = argparse.ArgumentParser(description="批量运行针织色码图/仿真生成")
    parser.add_argument("--color-only", action="store_true",
                        help="只生成色码图与针法日志，跳过 Stage 4 视觉预览")
    parser.add_argument("--stage", type=int, default=4, choices=[1, 2, 3, 4],
                        help="视觉预览阶段（all 模式，默认 4）")
    parser.add_argument("--repeat", type=int, default=1,
                        help="每条指令重复运行的次数（不同随机种子）")
    parser.add_argument("--seed", type=int, default=42, help="起始随机种子")
    args = parser.parse_args()

    mode = "color" if args.color_only else "all"
    results = []

    for run_name, prompt in INSTRUCTIONS:
        for r in range(args.repeat):
            seed = args.seed + r
            name = run_name if args.repeat == 1 else f"{run_name}_r{r + 1}"
            print("\n" + "=" * 80)
            print(f"[{name}] (mode={mode}, seed={seed}) {prompt}")
            print("=" * 80)
            cmd = build_cmd(mode, prompt, name, args.stage, seed)
            try:
                subprocess.run(cmd, cwd=str(ROOT), check=True)
                results.append((name, "OK"))
            except subprocess.CalledProcessError as exc:
                print(f"[ERROR] {name} 失败: returncode={exc.returncode}")
                results.append((name, f"FAIL(rc={exc.returncode})"))
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] {name} 异常: {exc}")
                results.append((name, f"FAIL({exc})"))

    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)
    for name, status in results:
        print(f"  {name}: {status}")
    ok = sum(1 for _, s in results if s == "OK")
    print(f"\n成功 {ok}/{len(results)}。")
    print("针法说明见各运行目录下 color_map/pattern_stitch_legend.json（也会打印在上方日志中）。")
    if ok < len(results):
        print('失败项可单独重跑：python run_pipeline.py all "<prompt>" --run-name <name>')


if __name__ == "__main__":
    main()
