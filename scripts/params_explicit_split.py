"""Params 准确率的显式/默认拆分统计（回应审稿意见：Params 100% 依赖默认值不计分口径）。

协议：语义解析测试输入中的参数信息以定性修饰词形式出现（如"稀疏网眼"
"密集蜂巢""边框加粗"），不含数值参数。本脚本用可复现的词法规则在
100 条 prompt 原文中检测两类修饰词，并绑定到对应 motif 的参数字段：

1. 密度修饰词（稀疏/密集/稠密/满花）+ 纹理名（网眼/镂空/蜂巢/波浪/
   绞花/麻花/吊目），绑定该纹理 motif 的周期类参数
   （period_x / period_y / stagger / spacing / density）；
2. 粗细修饰词（加粗/较粗/粗），绑定边框 motif 的厚度类参数
   （thickness / border_thickness）。

其余参数字段均由 schema 默认值填充。检测结果与逐案例人工评分
（outputs/runs/semantic/scoring_sheet.json，params 字段）交叉：人工评分
只对显式参数计分，故显式字段的匹配情况由该评分给出。作为数值旁证，
脚本另按"稀疏/密集/未提及"三组统计解析产物中 period 参数的均值，
验证显式修饰词确实驱动了不同的参数取值。

用法：
    python scripts/params_explicit_split.py
输出：
    outputs/analysis/params_explicit_split.csv + 终端 Markdown 汇总
"""
from __future__ import annotations

import csv
import glob as globlib
import json
import re
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEET = REPO_ROOT / "outputs/runs/semantic/scoring_sheet.json"
SEM_ROOT = REPO_ROOT / "outputs/runs/semantic"
OUT = REPO_ROOT / "outputs/analysis/params_explicit_split.csv"

DENSITY_WORDS = "稀疏|密集|稠密|满花"
EFFECT_WORDS = {
    "lace": ["网眼", "镂空"],
    "honeycomb": ["蜂巢"],
    "wave_tuck": ["波浪", "吊目"],
    "cable": ["绞花", "麻花"],
}
DENSITY_PARAMS = {"period_x", "period_y", "stagger", "spacing", "density"}
THICK_PARAMS = {"thickness", "border_thickness"}
# 密度修饰词与纹理名之间允许最多 4 个非断句字符（如"稀疏[背景]网眼"）
DENSITY_RE = re.compile(rf"({DENSITY_WORDS})[^，。;\s]{{0,4}}?(网眼|镂空|蜂巢|波浪|吊目|绞花|麻花)")
THICK_RE = re.compile(r"边框[^，。;\s]{0,2}?(加粗|较粗|粗)|(加粗|较粗)[^，。;\s]{0,2}?边框")


def effect_of_word(word: str) -> str:
    for eff, words in EFFECT_WORDS.items():
        if word in words:
            return eff
    return ""


def load_plan_params(sem_id: str) -> dict[str, dict]:
    """motif_id -> params 实际取值（从 pattern_plan.json）。"""
    pattern = str(SEM_ROOT / sem_id / "color_map" / "*_pattern_plan.json")
    matches = globlib.glob(pattern)
    if not matches:
        return {}
    with open(matches[0], encoding="utf-8") as f:
        plan = json.load(f)
    return {m.get("motif_id", ""): (m.get("params") or {}) for m in plan.get("motifs", [])}


def main() -> None:
    with SHEET.open(encoding="utf-8") as f:
        sheet = json.load(f)

    rows: list[dict] = []
    n_explicit = n_default = 0
    cases_with_explicit: set[str] = set()
    # 数值旁证：按 (effect, 修饰词类型) 收集 period_x 取值
    period_by_group: dict[tuple[str, str], list[float]] = {}

    for item in sheet:
        sem_id, prompt = item["id"], item["prompt"]
        params_score = item["scoring"].get("params")
        plan_params = load_plan_params(sem_id)

        # 案例级修饰词检测
        density_hits = [(m.group(1), effect_of_word(m.group(2))) for m in DENSITY_RE.finditer(prompt)]
        thick_hit = bool(THICK_RE.search(prompt))
        hit_effects = {eff: word for word, eff in density_hits if eff}

        for motif in item["motifs"]:
            eff = motif["effect"]
            is_border = motif["motif_type"] == "frame" or "frame" in motif["motif_id"] or "border" in motif["motif_id"]
            for key in motif["param_keys"]:
                explicit_by = ""
                if key in DENSITY_PARAMS and eff in hit_effects:
                    explicit_by = f"密度词[{hit_effects[eff]}]"
                elif key in THICK_PARAMS and thick_hit and is_border:
                    explicit_by = "粗细词"
                if explicit_by:
                    n_explicit += 1
                    cases_with_explicit.add(sem_id)
                else:
                    n_default += 1
                value = load_value = plan_params.get(motif["motif_id"], {}).get(key, "")
                rows.append({
                    "case": sem_id, "motif_id": motif["motif_id"], "effect": eff,
                    "param_key": key, "value": load_value,
                    "explicit": 1 if explicit_by else 0, "explicit_by": explicit_by,
                    "params_score": params_score,
                })
                if key == "period_x" and eff in EFFECT_WORDS:
                    word = hit_effects.get(eff, "")
                    group = "稀疏" if word == "稀疏" else ("密集/满花" if word in ("密集", "稠密", "满花") else "未提及")
                    if value != "":
                        period_by_group.setdefault((eff, group), []).append(float(value))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = n_explicit + n_default
    all_scored = all(item["scoring"].get("params") == 1 for item in sheet)
    print(f"参数字段总数: {total}")
    print(f"显式给出（修饰词绑定）: {n_explicit} ({n_explicit / total:.1%})，涉及 {len(cases_with_explicit)} 条输入")
    print(f"默认值填充: {n_default} ({n_default / total:.1%})")
    print(f"人工评分 params 全部为 1: {all_scored}")

    print("\n数值旁证：period_x 均值（按 effect × 修饰词分组）")
    print("| effect | 稀疏 | 密集/满花 | 未提及 |")
    print("| --- | ---: | ---: | ---: |")
    for eff in EFFECT_WORDS:
        cells = []
        for grp in ("稀疏", "密集/满花", "未提及"):
            vals = period_by_group.get((eff, grp), [])
            cells.append(f"{np.mean(vals):.2f} (n={len(vals)})" if vals else "—")
        print(f"| {eff} | {cells[0]} | {cells[1]} | {cells[2]} |")

    print(f"\n逐字段结果已写入 {OUT}")


if __name__ == "__main__":
    main()
