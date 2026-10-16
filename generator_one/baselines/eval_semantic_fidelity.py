"""
语义保真度 F 复合指标评估脚本
================================
将原始单一 F 指标拆分为 3 个子指标 + 1 个综合分：

  - Texture-F  (召回率)：期望纹理动作中有多少出现在输出中
  - Region-F   (精确率)：非背景动作中有多少是期望的纹理动作
  - Noise-F    (噪声率)：非背景动作中有多少是不相关的（↓ 越低越好）
  - Overall-F  (综合分)：Texture-F × Region-F（F1 风格几何均值）

背景动作定义：f_knit, b_knit, miss, drop, carrier
非背景动作：f_tuck, b_tuck, f_split, b_split, xfer_* 等

用法：
  python generator_one/baselines/eval_semantic_fidelity.py
"""

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 背景动作 = LOOP + MISS + DROP + CARRIER（不承载纹理语义）
BACKGROUND_ABBRS = {"f_knit", "b_knit", "miss", "drop", "carrier"}

# 测试输入定义（与 run_baselines.py 保持一致）
TEST_PROMPTS = [
    {"id": "test_01", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_02", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_03", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_04", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_05", "expected_texture": ["f_split", "f_tuck"]},
    {"id": "test_06", "expected_texture": ["f_tuck", "b_tuck"]},
    {"id": "test_07", "expected_texture": ["f_tuck", "f_split"]},
    {"id": "test_08", "expected_texture": ["xfer_l1", "xfer_r1", "f_tuck", "b_tuck"]},
    {"id": "test_09", "expected_texture": ["f_knit", "b_knit"]},
    {"id": "test_10", "expected_texture": ["f_tuck", "b_tuck", "f_split"]},
]


def compute_sub_metrics(distribution: dict, expected_texture: list, test_id: str) -> dict:
    """从动作分布计算 3 个语义保真度子指标 + 综合分。"""
    total_pixels = sum(distribution.values())
    if total_pixels == 0:
        return {"Texture_F": 0.0, "Region_F": 0.0, "Noise_F": 1.0, "Overall_F": 0.0}

    # test_09 特殊处理：纹理动作是 knit 类
    if test_id == "test_09":
        bg_set = BACKGROUND_ABBRS - {"f_knit", "b_knit"}
    else:
        bg_set = BACKGROUND_ABBRS

    bg_pixels = sum(distribution.get(a, 0) for a in bg_set if a in distribution)
    non_bg_pixels = total_pixels - bg_pixels

    # Texture-F (召回率)
    expected_set = set(expected_texture)
    present_count = sum(1 for a in expected_set if distribution.get(a, 0) > 0)
    texture_f = present_count / len(expected_set) if expected_set else 0.0

    # Region-F (精确率) + Noise-F (噪声率)
    expected_pixels = sum(distribution.get(a, 0) for a in expected_set)
    if non_bg_pixels > 0:
        region_f = expected_pixels / non_bg_pixels
        noise_f = 1.0 - region_f
    else:
        region_f = 0.0
        noise_f = 1.0

    # Overall-F: Texture_F × Region_F 的几何均值（类似 F1）
    if texture_f > 0 and region_f > 0:
        overall_f = math.sqrt(texture_f * region_f)
    else:
        overall_f = 0.0

    return {
        "Texture_F": round(texture_f, 4),
        "Region_F": round(region_f, 4),
        "Noise_F": round(noise_f, 4),
        "Overall_F": round(overall_f, 4),
    }


def main():
    data_path = PROJECT_ROOT / "outputs" / "runs" / "baseline" / "baseline_comparison" / "baseline_comparison.json"
    if not data_path.exists():
        print(f"Error: {data_path} not found")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    expected_map = {t["id"]: t["expected_texture"] for t in TEST_PROMPTS}

    results = []
    for rec in records:
        test_id = rec["test_id"]
        method = rec["method"]
        method_name = rec["method_name"]
        dist = rec["distribution"]
        expected = expected_map.get(test_id, [])

        sub = compute_sub_metrics(dist, expected, test_id)
        row = {
            "test_id": test_id,
            "method": method,
            "method_name": method_name,
            "old_F": rec.get("semantic_fidelity", "N/A"),
            **sub,
            "V_h": rec["hard_violations"],
        }
        results.append(row)

    # 输出
    out_dir = PROJECT_ROOT / "outputs" / "runs" / "baseline" / "semantic_fidelity_sub"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "semantic_fidelity_sub.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # 均值汇总
    methods = ["ours", "no_plan", "llm_direct"]
    summary = []
    for m in methods:
        rows = [r for r in results if r["method"] == m]
        if not rows:
            continue
        avg = {
            "method": m,
            "method_name": rows[0]["method_name"],
            "count": len(rows),
            "old_F_avg": round(sum(r["old_F"] for r in rows if isinstance(r["old_F"], (int, float))) / len(rows), 4),
            "Texture_F_avg": round(sum(r["Texture_F"] for r in rows) / len(rows), 4),
            "Region_F_avg": round(sum(r["Region_F"] for r in rows) / len(rows), 4),
            "Noise_F_avg": round(sum(r["Noise_F"] for r in rows) / len(rows), 4),
            "Overall_F_avg": round(sum(r["Overall_F"] for r in rows) / len(rows), 4),
            "avg_V_h": round(sum(r["V_h"] for r in rows) / len(rows), 1),
        }
        summary.append(avg)

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 打印
    print("=" * 100)
    print("语义保真度 F 复合指标评估结果")
    print("=" * 100)
    print(f"{'Method':<20} {'old_F':>6} {'Tex-F↑':>7} {'Reg-F↑':>7} {'Noise↓':>7} {'Over-F↑':>8} {'V_h':>6}")
    print("-" * 100)
    for s in summary:
        print(f"{s['method_name']:<20} {s['old_F_avg']:>6.4f} {s['Texture_F_avg']:>7.4f} "
              f"{s['Region_F_avg']:>7.4f} {s['Noise_F_avg']:>7.4f} {s['Overall_F_avg']:>8.4f} {s['avg_V_h']:>6.1f}")
    print("-" * 100)
    print(f"\n详细结果 → {out_dir / 'semantic_fidelity_sub.json'}")
    print(f"均值汇总 → {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
