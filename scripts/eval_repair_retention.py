"""修复前后语义保留率评估脚本。

回答评审关切：约束修复是否以牺牲纹理语义为代价换取合法性。

支持两种模式：

模式 A（paired，推荐）：对比同一输入在 full 与 no_repair 两种设置下的
最终动作网格（no_repair 网格近似"未修复"状态），统计修复引起的事件级变化：
- cell_agreement      两网格逐格一致率
- event_retained      no_repair 中的非底布事件在 full 中保持同一动作的比例
- event_downgraded    变为其他非底布动作（降级/替换）的比例
- event_deleted       变为底布成圈动作（删除）的比例
- texture_area_ratio  full 非底布格数 / no_repair 非底布格数
并结合两侧 stats.json 报告 V_h / V_c 对照。

模式 B（single）：读取单次运行 stats.json，报告三个阶段的违例数：
- violations.hard_before/craft_before   规则修复流水线前（首次检测）
- violations.hard_after/craft_after     进入 LLM 修复前（规则流水线后）
- llm_repair.final_hard/final_craft     最终状态（与论文表格口径一致）
另报告 llm_repair.rounds/edits 与修复触发率。
（注：若需真正的"修复前网格"，需在管线中导出 pre-repair 网格，
见 docs/补实验方案.md 第 4 节。）

底布动作默认取 {f_knit, b_knit}；其索引优先通过 generator_one.core.actions
解析（需在仓库根目录运行），失败时回退为 {0, 1}。

用法（远程 Linux 环境，仓库根目录下运行）：
    # 模式 A：full vs no_repair（消融运行目录，dir 命名为 <case>_<setting>）
    python scripts/eval_repair_retention.py paired \
        --root outputs/runs/ablation --setting-a full --setting-b no_repair \
        --out outputs/analysis/repair_retention.csv

    # 模式 B：单设置内 before/after 违例统计
    python scripts/eval_repair_retention.py single \
        --root outputs/runs/stress_test --out outputs/analysis/repair_single.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

BASE_ABBRS = {"f_knit", "b_knit"}


def resolve_base_ids() -> set[int]:
    """解析底布动作索引；优先使用 generator_one 的动作定义。"""
    repo_root = Path(__file__).resolve().parents[1]
    gen_one = repo_root / "generator_one"
    for p in (str(gen_one), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from core import actions  # generator_one/core/actions.py

        return {actions.idx(a) for a in BASE_ABBRS}
    except Exception:
        print("[warn] 无法导入 generator_one.core.actions，底布索引回退为 {0, 1}")
        return {0, 1}


def final_violations(stats: dict) -> tuple:
    """提取最终违例数（与论文表格口径一致）。

    注意：violations.hard_after/craft_after 是规则修复流水线后、LLM 修复前
    的状态；最终状态在 llm_repair.final_hard/final_craft（若无 LLM 修复轮次
    则两者等价，回退到 *_after）。
    """
    v = stats.get("violations", {}) or {}
    repair = stats.get("llm_repair", {}) or {}
    hard = repair.get("final_hard", v.get("hard_after", ""))
    craft = repair.get("final_craft", v.get("craft_after", ""))
    return hard, craft


def find_grid(case_dir: Path) -> np.ndarray | None:
    npy = next(case_dir.glob("color_map/intermediate/*_action.npy"), None)
    return np.load(npy) if npy is not None else None


def find_stats(case_dir: Path) -> dict:
    stats = next(case_dir.glob("color_map/*_stats.json"), None)
    if stats is None:
        return {}
    with stats.open("r", encoding="utf-8") as f:
        return json.load(f)


def pair_cases(root: Path, setting_a: str, setting_b: str) -> list[tuple[str, Path, Path]]:
    """按 <case>_<setting> 命名规则配对运行目录（忽略 _s123 等种子后缀目录）。"""
    pairs = []
    pattern = re.compile(r"^(?P<case>.+)_(?P<setting>" + re.escape(setting_a) + r")$")
    for dir_a in sorted(p for p in root.iterdir() if p.is_dir()):
        m = pattern.match(dir_a.name)
        if not m:
            continue
        case = m.group("case")
        dir_b = root / f"{case}_{setting_b}"
        if dir_b.is_dir():
            pairs.append((case, dir_a, dir_b))
    return pairs


def evaluate_pair(case: str, dir_a: Path, dir_b: Path, base_ids: set[int]) -> dict:
    grid_a, grid_b = find_grid(dir_a), find_grid(dir_b)
    stats_a, stats_b = find_stats(dir_a), find_stats(dir_b)
    vh_a, vc_a = final_violations(stats_a)
    vh_b, vc_b = final_violations(stats_b)
    row: dict = {
        "case": case,
        "V_h_a": vh_a,
        "V_c_a": vc_a,
        "V_h_b": vh_b,
        "V_c_b": vc_b,
    }
    if grid_a is None or grid_b is None:
        # 运行失败的案例（如 stress_22 no_repair）保留在表中并显式标记，
        # 统计均值时不应静默剔除（见 docs/补实验方案.md）。
        row.update({
            "valid": False, "cell_agreement": "", "event_retained": "",
            "event_downgraded": "", "event_deleted": "", "event_added": "",
            "texture_area_ratio": "",
        })
        return row

    base_mask_a = np.isin(grid_a, list(base_ids))
    base_mask_b = np.isin(grid_b, list(base_ids))
    events_b = ~base_mask_b  # 未修复侧的非底布事件格
    n_events_b = int(events_b.sum())

    same = grid_a == grid_b
    retained = int((events_b & same).sum())
    deleted = int((events_b & base_mask_a).sum())
    downgraded = n_events_b - retained - deleted  # 变为其他非底布动作
    added = int((~base_mask_a & base_mask_b).sum())

    row.update({
        "valid": True,
        "cell_agreement": round(float(same.mean()), 4),
        "event_retained": round(retained / n_events_b, 4) if n_events_b else 1.0,
        "event_downgraded": round(downgraded / n_events_b, 4) if n_events_b else 0.0,
        "event_deleted": round(deleted / n_events_b, 4) if n_events_b else 0.0,
        "event_added": added,
        "texture_area_ratio": round(
            float((~base_mask_a).sum()) / n_events_b, 4
        ) if n_events_b else "",
    })
    return row


def run_paired(args: argparse.Namespace) -> list[dict]:
    base_ids = resolve_base_ids()
    pairs = pair_cases(args.root, args.setting_a, args.setting_b)
    if not pairs:
        raise SystemExit(f"未在 {args.root} 找到 {args.setting_a}/{args.setting_b} 配对目录")
    rows = [evaluate_pair(case, a, b, base_ids) for case, a, b in pairs]

    print(f"\n| 案例 | 一致率 | 事件保留 | 事件降级 | 事件删除 | 面积比 | $V_h$/$V_c$({args.setting_a}) | $V_h$/$V_c$({args.setting_b}) |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        if r["valid"]:
            print(
                f"| {r['case']} | {r['cell_agreement']:.3f} | {r['event_retained']:.3f} "
                f"| {r['event_downgraded']:.3f} | {r['event_deleted']:.3f} "
                f"| {r['texture_area_ratio']} | {r['V_h_a']}/{r['V_c_a']} | {r['V_h_b']}/{r['V_c_b']} |"
            )
        else:
            print(f"| {r['case']} | — | — | — | — | — | {r['V_h_a']}/{r['V_c_a']} | 运行失败 |")

    valid = [r for r in rows if r["valid"]]
    if valid:
        print(
            f"\n有效配对 {len(valid)}/{len(rows)}；均值: "
            f"事件保留={np.mean([r['event_retained'] for r in valid]):.3f}, "
            f"降级={np.mean([r['event_downgraded'] for r in valid]):.3f}, "
            f"删除={np.mean([r['event_deleted'] for r in valid]):.3f}"
        )
    return rows


def run_single(args: argparse.Namespace) -> list[dict]:
    rows = []
    for case_dir in sorted(p for p in args.root.iterdir() if p.is_dir()):
        stats = find_stats(case_dir)
        if not stats:
            rows.append({"case": case_dir.name, "valid": False})
            continue
        v = stats.get("violations", {})
        repair = stats.get("llm_repair", {}) or {}
        vh_final, vc_final = final_violations(stats)
        rows.append({
            "case": case_dir.name,
            "valid": True,
            "V_h_detect": v.get("hard_before", ""),
            "V_c_detect": v.get("craft_before", ""),
            "V_h_pre_llm": v.get("hard_after", ""),
            "V_c_pre_llm": v.get("craft_after", ""),
            "V_h_final": vh_final,
            "V_c_final": vc_final,
            "repair_rounds": repair.get("rounds", 0),
            "repair_edits": repair.get("edits", 0),
        })

    valid = [r for r in rows if r.get("valid")]
    triggered = [
        r for r in valid
        if (r["V_h_pre_llm"] or 0) + (r["V_c_pre_llm"] or 0) > 0 or r["repair_rounds"] > 0
    ]
    print(f"\n有效案例 {len(valid)}/{len(rows)}；LLM 修复触发率 {len(triggered)}/{len(valid)}")
    if triggered:
        print(
            f"触发案例均值: V_h {np.mean([r['V_h_pre_llm'] for r in triggered]):.2f}"
            f"→{np.mean([r['V_h_final'] for r in triggered]):.2f}, "
            f"V_c {np.mean([r['V_c_pre_llm'] for r in triggered]):.2f}"
            f"→{np.mean([r['V_c_final'] for r in triggered]):.2f}, "
            f"平均修复编辑数 {np.mean([r['repair_edits'] for r in triggered]):.2f}"
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="修复前后语义保留率评估")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_pair = sub.add_parser("paired", help="full vs no_repair 网格对比")
    p_pair.add_argument("--root", type=Path, default=Path("outputs/runs/ablation"))
    p_pair.add_argument("--setting-a", type=str, default="full")
    p_pair.add_argument("--setting-b", type=str, default="no_repair")
    p_pair.add_argument("--out", type=Path, default=Path("outputs/analysis/repair_retention.csv"))

    p_single = sub.add_parser("single", help="单设置 before/after 违例统计")
    p_single.add_argument("--root", type=Path, required=True)
    p_single.add_argument("--out", type=Path, default=Path("outputs/analysis/repair_single.csv"))

    args = parser.parse_args()
    rows = run_paired(args) if args.mode == "paired" else run_single(args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"结果已写入 {args.out}")


if __name__ == "__main__":
    main()
