# -*- coding: utf-8 -*-
"""
Plan-Grid+CSP 基线：密集周期目标 + CP-SAT 全局约束投影。

回应"补充 CSP/ILP 强约束生成基线"的评审意见。与 Plan-Grid 共享 PatternPlan
与区域实现（直接复用其归档运行产物作为密集周期目标网格），将 H1–H8 硬约束
编码为 CP-SAT 约束模型，以"与密集目标网格汉明距离最小"为目标函数做全局
最优投影。对比链：Plan-Grid（无约束处理）→ Plan-Grid+Repair（局部贪心修复）
→ Plan-Grid+CSP（全局约束投影）→ Ours（事件级编译，生成期维护约束）。

- 协议 A（test_01–10）：目标网格 = outputs/runs/baseline_comparison_internal/
  test_XX/plan_grid/output.bmp；产物写入同级 plan_grid_csp/ 目录，指标归档
  plangrid_csp.json（口径与 baseline_comparison.json 相同）。
- 协议 B（ABL-01–08）：目标网格 = outputs/runs/internal_baseline/
  abl_XX_plangrid/color_map/intermediate/abl_XX_action.npy；产物按运行目录
  结构写入 abl_XX_plangrid_csp/（复制同一份 pattern_plan.json），供
  scripts/region_metrics.py 直接评估结构级指标。

动作域设计（每格）：{目标动作} ∪ 同语义族动作 ∪ 安全底布动作（f_knit/b_knit）；
转移类动作额外允许 miss 作为语义退出。f_knit/b_knit 恒在域内，模型恒可行。
仅编码 H1–H8 硬约束，不编码 C1–C6 工艺启发式约束（与规则修复基线同口径）。

用法（在 generator_one 目录下运行）：
    python run_plangrid_csp.py            # 协议 A + 协议 B
    python run_plangrid_csp.py --only A   # 仅协议 A
    python run_plangrid_csp.py --only B   # 仅协议 B
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ortools.sat.python import cp_model

from core import actions
from rules import check_physical, check_craft_actions
from run_baselines import TEST_PROMPTS, evaluate_grid
from pipeline import action_grid_to_rgb
from utils.file_io import save_image

REPO = Path(__file__).resolve().parent.parent
PROTO_A_DIR = REPO / "outputs" / "runs" / "baseline_comparison_internal"
PROTO_B_DIR = REPO / "outputs" / "runs" / "internal_baseline"
METHOD_KEY = "plan_grid_csp"
METHOD_NAME = "Plan-Grid+CSP"
TIME_LIMIT = 60.0

_F_KNIT = actions.idx("f_knit")
_B_KNIT = actions.idx("b_knit")
_MISS = actions.idx("miss")
_TUCK = actions.tuck_ids()
_SPLIT = actions.split_ids()
_CARRIER = actions.idx("carrier")


def load_grid_bmp(bmp_path: Path) -> np.ndarray:
    return np.array(Image.open(bmp_path)).astype(int)


def build_domains(target: np.ndarray) -> dict:
    """每格动作域：{目标动作} ∪ 同语义族 ∪ {f_knit, b_knit}；转移类附加 miss。"""
    rows, cols = target.shape
    domains = {}
    for i in range(rows):
        for j in range(cols):
            a = int(target[i, j])
            sem = actions.semantic(a)
            if sem == "TUCK":
                dom = set(_TUCK) | {_F_KNIT, _B_KNIT}
            elif sem == "SPLIT":
                dom = set(_SPLIT) | {_F_KNIT, _B_KNIT}
            elif sem == "TRANSFER":
                dom = {a, _F_KNIT, _B_KNIT, _MISS}
            elif sem == "EMPTY":
                dom = {_MISS, _F_KNIT, _B_KNIT}
            else:  # LOOP / DROP(carrier) / 其他
                dom = {a, _F_KNIT, _B_KNIT}
            dom.add(a)
            # H4：移针目标越界 → 位置级域过滤
            dom = {x for x in dom if 0 <= j + actions.offset(x) < cols}
            domains[(i, j)] = sorted(dom)
    return domains


def solve_projection(target: np.ndarray, time_limit: float = TIME_LIMIT):
    """CP-SAT 全局投影：在满足 H1–H8 的可行空间中找与 target 汉明距离最小的网格。"""
    rows, cols = target.shape
    domains = build_domains(target)
    m = cp_model.CpModel()

    X, lit = {}, {}
    for (i, j), dom in domains.items():
        X[(i, j)] = m.NewIntVarFromDomain(
            cp_model.Domain.FromValues(dom), f"x_{i}_{j}")
        for a in dom:
            b = m.NewBoolVar(f"b_{i}_{j}_{a}")
            m.Add(X[(i, j)] == a).OnlyEnforceIf(b)
            m.Add(X[(i, j)] != a).OnlyEnforceIf(b.Not())
            lit[(i, j, a)] = b

    # H2：下方支撑（起针行=最后一行除外）
    for i in range(rows - 1):
        for j in range(cols):
            sup = [lit[(i + 1, j, s)] for s in domains[(i + 1, j)]
                   if actions.supports_above(s)]
            for a in domains[(i, j)]:
                if actions.requires_support(a):
                    m.AddBoolOr(sup).OnlyEnforceIf(lit[(i, j, a)])

    # H5：同行移针目标冲突（对目标列 t 的来源至多一个）
    xfer_sources = ((-1, "xfer_r1"), (1, "xfer_l1"), (0, "xfer_f_b"), (0, "xfer_b_f"))
    for i in range(rows):
        for t in range(cols):
            srcs = []
            for dj, ab in xfer_sources:
                j = t - dj if dj else t
                if 0 <= j < cols:
                    ai = actions.idx_safe(ab, -1)
                    if ai >= 0 and (i, j, ai) in lit:
                        srcs.append(lit[(i, j, ai)])
            if len(srcs) > 1:
                m.Add(sum(srcs) <= 1)

    # H6：同列连续 Tuck 不超过堆叠上限（窗口大小 = 上限+1）
    limit = actions.max_vertical_stack(next(iter(_TUCK))) or 3
    for j in range(cols):
        for i in range(rows - limit):
            m.Add(sum(lit[(k, j, a)] for k in range(i, i + limit + 1)
                      for a in domains[(k, j)] if a in _TUCK) <= limit)

    # H7：carrier（DROP 语义）上方不得存在可支撑动作
    for (i, j), dom in domains.items():
        if _CARRIER not in dom or i == 0:
            continue
        for up in range(i):
            for a in domains[(up, j)]:
                if actions.supports_above(a):
                    m.Add(lit[(up, j, a)] == 0).OnlyEnforceIf(lit[(i, j, _CARRIER)])

    # H8：同行不得同时存在两个方向的床间移针
    xfb, xbf = actions.idx("xfer_f_b"), actions.idx("xfer_b_f")
    for i in range(rows):
        fb = [lit[(i, j, xfb)] for j in range(cols) if (i, j, xfb) in lit]
        bf = [lit[(i, j, xbf)] for j in range(cols) if (i, j, xbf) in lit]
        if fb and bf:
            has_fb, has_bf = m.NewBoolVar(f"hfb_{i}"), m.NewBoolVar(f"hbf_{i}")
            m.Add(sum(fb) >= 1).OnlyEnforceIf(has_fb)
            m.Add(sum(fb) == 0).OnlyEnforceIf(has_fb.Not())
            m.Add(sum(bf) >= 1).OnlyEnforceIf(has_bf)
            m.Add(sum(bf) == 0).OnlyEnforceIf(has_bf.Not())
            m.Add(has_fb + has_bf <= 1)

    # 目标函数：与密集目标的匹配格数最大化（H1/H3 由动作域天然满足）
    m.Maximize(sum(lit[(i, j, int(target[i, j]))]
                   for i in range(rows) for j in range(cols)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    t0 = time.time()
    status = solver.Solve(m)
    elapsed = time.time() - t0

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT 不可行（状态={status}）——安全动作域被破坏")

    solved = np.zeros_like(target)
    for (i, j) in domains:
        solved[i, j] = solver.Value(X[(i, j)])
    changed = int((solved != target).sum())
    return solved, {
        "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        "objective_matches": int(solver.ObjectiveValue()),
        "changed_cells": changed,
        "solve_time": round(elapsed, 3),
    }


def run_protocol_a():
    print("=" * 70)
    print("协议 A：test_01–10，目标 = baseline_comparison_internal/*/plan_grid")
    print("=" * 70)
    results = []
    print("{:<8} {:>6} {:>6} {:>6} {:>8} {:>6} {:>6} {:>8} {:>7}".format(
        "test", "tgtVh", "cspVh", "craft", "tension", "div", "sem", "changed", "time"))
    for test in TEST_PROMPTS:
        test_id = test["id"]
        target = load_grid_bmp(PROTO_A_DIR / test_id / "plan_grid" / "output.bmp")
        solved, info = solve_projection(target)

        # 硬性核验：投影结果必须零硬违例
        hard_after = check_physical(solved)
        assert not hard_after, f"{test_id} 投影后仍有硬违例: {hard_after[:3]}"

        m = evaluate_grid(solved, test.get("expected_texture", []))
        tgt_hard = len(check_physical(target))
        m.update({
            "method": METHOD_KEY, "method_name": METHOD_NAME,
            "test_id": test_id, "prompt": test["prompt"],
            "execution_time": info["solve_time"], "success": True,
            "target_hard": tgt_hard, "solver_status": info["status"],
            "changed_cells": info["changed_cells"],
        })
        results.append(m)

        out_dir = PROTO_A_DIR / test_id / METHOD_KEY
        out_dir.mkdir(parents=True, exist_ok=True)
        save_image(solved, out_dir / "output.bmp", palette=actions.build_palette_256())
        save_image(action_grid_to_rgb(solved), out_dir / "output.png")

        print("{:<8} {:>6} {:>6} {:>6} {:>8} {:>6} {:>6} {:>8} {:>7}".format(
            test_id, tgt_hard, m["hard_violations"], m["craft_violations"],
            m["tension_score"], m["action_diversity"], m["semantic_fidelity"],
            info["changed_cells"], info["solve_time"]))

    out_json = PROTO_A_DIR / "plangrid_csp.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    avg = lambda k: float(np.mean([r[k] for r in results]))
    print("\n=== Plan-Grid+CSP 协议 A（n=%d）===" % len(results))
    print("  hard: 目标 %.1f -> 投影 %.1f（zero: %d/10）" % (
        avg("target_hard"), avg("hard_violations"),
        sum(1 for r in results if r["hard_violations"] == 0)))
    print("  craft %.2f | tension %.4f | diversity %.2f | semantic %.4f | changed %.1f | time %.3fs" % (
        avg("craft_violations"), avg("tension_score"), avg("action_diversity"),
        avg("semantic_fidelity"), avg("changed_cells"), avg("execution_time")))
    print("保存:", out_json)


def run_protocol_b():
    print("=" * 70)
    print("协议 B：ABL-01–08，复用 internal_baseline/abl_*_plangrid 同一份 plan")
    print("=" * 70)
    rows_out = []
    print("{:<10} {:>6} {:>6} {:>6} {:>8} {:>7}".format(
        "case", "tgtVh", "cspVh", "craft", "changed", "time"))
    for k in range(1, 9):
        case = f"abl_{k:02d}"
        src_dir = PROTO_B_DIR / f"{case}_plangrid" / "color_map"
        target = np.load(src_dir / "intermediate" / f"{case}_action.npy")
        solved, info = solve_projection(target)

        hard_after = check_physical(solved)
        assert not hard_after, f"{case} 投影后仍有硬违例: {hard_after[:3]}"

        tgt_hard = len(check_physical(target))
        craft_after = len(check_craft_actions(solved))

        out_dir = PROTO_B_DIR / f"{case}_{METHOD_KEY}" / "color_map"
        (out_dir / "intermediate").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_dir / f"{case}_pattern_plan.json",
                     out_dir / f"{case}_pattern_plan.json")
        np.save(out_dir / "intermediate" / f"{case}_action.npy", solved)
        save_image(solved, out_dir / f"{case}_output.bmp",
                   palette=actions.build_palette_256())
        save_image(action_grid_to_rgb(solved), out_dir / f"{case}_output.png")

        rows_out.append({
            "case": case, "target_hard": tgt_hard, "hard": len(hard_after),
            "craft": craft_after, "changed_cells": info["changed_cells"],
            "solve_time": info["solve_time"], "solver_status": info["status"],
        })
        print("{:<10} {:>6} {:>6} {:>6} {:>8} {:>7}".format(
            case, tgt_hard, len(hard_after), craft_after,
            info["changed_cells"], info["solve_time"]))

    out_json = PROTO_B_DIR / "plangrid_csp_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows_out, f, ensure_ascii=False, indent=2)
    avg = lambda k: float(np.mean([r[k] for r in rows_out]))
    print("\n=== Plan-Grid+CSP 协议 B（n=%d）===" % len(rows_out))
    print("  hard 均值 %.2f（zero: %d/8）| craft 均值 %.2f | changed %.1f | time %.3fs" % (
        avg("hard"), sum(1 for r in rows_out if r["hard"] == 0),
        avg("craft"), avg("changed_cells"), avg("solve_time")))
    print("保存:", out_json)
    print("结构级指标请运行: python scripts/region_metrics.py "
          "--runs \"outputs/runs/internal_baseline/abl_*_plan_grid_csp\"")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["A", "B"], default=None)
    args = parser.parse_args()
    if args.only in (None, "A"):
        run_protocol_a()
    if args.only in (None, "B"):
        run_protocol_b()


if __name__ == "__main__":
    main()
