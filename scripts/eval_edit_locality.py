"""编辑局部性定量评估脚本。

针对可编辑生成实验（outputs/runs/edit/edt_XX），以基准案例（默认 edt_00）
为参照，对每个编辑变体计算两项论文指标：

1. 非目标区域保持率 Preserve_non-target
       = 1 - |{p ∉ R : A_p ≠ A'_p}| / |Ω \ R|
2. 目标区域编辑有效率 EditEffect_target
       = |{p ∈ R : A_p ≠ A'_p}| / |R|

其中目标区域 R 由基准与变体 PatternPlan 的差异自动推导：
- 逐 motif（按归一化 role 匹配）比较 motif_type / effect / params / region；
- 发生变化的 motif，其在两份 plan 中的几何 mask 取并集作为 R
  （形状替换、边框加粗等几何变化因此同时覆盖新旧区域）；
- 若变化 motif 的 region 为 full 类型（背景替换），R 取
  “画布 \ 变体 plan 中其余 motif mask 的并集”，即背景可作用区域。

几何 mask 语义与 generator_one/generation/mask_utils.py 保持一致：
- circle:  dr^2 + dc^2 <= size^2（size 为半径）
- diamond: |dr| + |dc| <= size
- rect/square（实心）: max(|dr|, |dc|) <= size
- frame/border（环形）: size - thickness < max(|dr|, |dc|) <= size

用法（远程 Linux 环境，仓库根目录下运行）：
    python scripts/eval_edit_locality.py \
        --edit-root outputs/runs/edit --baseline edt_00 \
        --out outputs/analysis/edit_locality.csv

输出：逐案例 CSV + 终端 Markdown 汇总表（可直接贴入论文表格）。
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

GRID_SIZE = 40

# role 归一化：不同变体中同一层次 motif 的 role 命名存在别名
_ROLE_ALIASES = {
    "border": "border",
    "inner_shape": "inner",
    "inner_boundary": "inner",
    "inner_frame": "inner",
    "center": "center",
    "allover": "background",
    "background": "background",
}


def normalize_role(motif: dict) -> str:
    role = str(motif.get("role", "")).strip().lower()
    return _ROLE_ALIASES.get(role, role or str(motif.get("motif_id", "")))


def is_implicit_plain_bg(motif: dict) -> bool:
    """全画布 plain 背景与基准的隐式平针背景等价，视为无变化。

    LLM 重新解析时可能显式输出 effect=plain 的 full 背景 motif，
    语义上与省略该 motif 完全等价，不应被判为背景编辑。
    """
    region = motif.get("region") or {}
    effect = str(motif.get("effect", "")).strip().lower()
    return region.get("type") == "full" and effect in {"plain", ""}


def _frame_thickness(motif: dict) -> int:
    """归一化边框厚度：不同 plan 中同一语义可能写在
    params.border_thickness / params.thickness / region.thickness。"""
    region = motif.get("region") or {}
    params = motif.get("params") or {}
    for value in (params.get("border_thickness"), params.get("thickness"), region.get("thickness")):
        if value is not None:
            return int(value)
    return 2


def motif_signature(motif: dict) -> str:
    """用于差异检测的规范化签名（忽略 motif_id、字段位置等非结构差异）。"""
    region = dict(motif.get("region") or {})
    params = dict(motif.get("params") or {})
    motif_type = str(motif.get("motif_type", "")).strip().lower()

    if motif_type == "frame" or region.get("type") == "border":
        # 边框：只比较规范化后的几何要素，避免厚度字段位置/margin 写法差异误报
        payload = {
            "motif_type": "frame",
            "effect": motif.get("effect"),
            "center": region.get("center"),
            "size": region.get("size"),
            "thickness": _frame_thickness(motif),
        }
    else:
        for key in ("border_thickness",):
            params.pop(key, None)
        payload = {
            "motif_type": motif.get("motif_type"),
            "effect": motif.get("effect"),
            "region": region,
            "params": params,
        }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def build_motif_mask(motif: dict, grid_size: int = GRID_SIZE) -> np.ndarray:
    """按 mask_utils.py 的几何语义构建单个 motif 的布尔 mask。"""
    region = motif.get("region") or {}
    mask = np.zeros((grid_size, grid_size), dtype=bool)

    if region.get("type") == "full":
        mask[:, :] = True
        return mask

    center = region.get("center", [grid_size // 2, grid_size // 2])
    cr, cc = int(center[0]), int(center[1])
    size = int(region.get("size", grid_size // 3))
    shape = str(region.get("shape", "")).strip().lower()
    motif_type = str(motif.get("motif_type", "")).strip().lower()

    rr, cc_grid = np.mgrid[0:grid_size, 0:grid_size]
    dr = rr - cr
    dc = cc_grid - cc

    if motif_type == "frame" or region.get("type") == "border":
        # 环形边框：外沿 size，厚度取归一化后的 thickness
        thickness = _frame_thickness(motif)
        cheb = np.maximum(np.abs(dr), np.abs(dc))
        return (cheb <= size) & (cheb > size - thickness)

    if shape in {"circle", "oval", "round", "circular", "ellipse"} or motif_type == "circle":
        return (dr * dr + dc * dc) <= size * size

    if shape in {"diamond", "rhombus"} or motif_type == "diamond":
        return (np.abs(dr) + np.abs(dc)) <= size

    # 其余形状回退为实心方形边界（与 mask_utils 的 fallback 一致）
    return (np.abs(dr) <= size) & (np.abs(dc) <= size)


def load_plan(case_dir: Path) -> dict:
    plan_path = next(case_dir.glob("color_map/*_pattern_plan.json"))
    with plan_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_grid(case_dir: Path) -> np.ndarray:
    npy_path = next(case_dir.glob("color_map/intermediate/*_action.npy"))
    return np.load(npy_path)


def load_stats(case_dir: Path) -> dict:
    stats_path = next(case_dir.glob("color_map/*_stats.json"), None)
    if stats_path is None:
        return {}
    with stats_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def derive_target_mask(base_plan: dict, var_plan: dict, grid_size: int) -> tuple[np.ndarray, list[str]]:
    """比较两份 PatternPlan，返回目标编辑区域 R 与变化 motif 的说明。"""
    # 隐式 plain 背景与显式 plain 背景等价，先行过滤避免误报背景编辑
    base_by_role: dict[str, dict] = {
        normalize_role(m): m for m in base_plan.get("motifs", []) if not is_implicit_plain_bg(m)
    }
    var_by_role: dict[str, dict] = {
        normalize_role(m): m for m in var_plan.get("motifs", []) if not is_implicit_plain_bg(m)
    }

    changed_notes: list[str] = []
    mask = np.zeros((grid_size, grid_size), dtype=bool)
    bg_changed = False

    for role in sorted(set(base_by_role) | set(var_by_role)):
        base_m = base_by_role.get(role)
        var_m = var_by_role.get(role)
        if base_m is not None and var_m is not None and motif_signature(base_m) == motif_signature(var_m):
            continue  # 未变化
        for m, tag in ((base_m, "base"), (var_m, "variant")):
            if m is None:
                continue
            if (m.get("region") or {}).get("type") == "full":
                bg_changed = True
            else:
                mask |= build_motif_mask(m, grid_size)
        desc = f"{role}: " + (
            "added" if base_m is None else "removed" if var_m is None else "modified"
        )
        changed_notes.append(desc)

    if bg_changed:
        # 背景替换：目标区域 = 画布减去两份 plan 中其余（非 full）motif 的 mask 并集，
        # 即背景纹理真正可作用的区域；不将整张画布计入目标，否则非目标集合为空
        occupied = np.zeros((grid_size, grid_size), dtype=bool)
        for plan in (base_plan, var_plan):
            for m in plan.get("motifs", []):
                if (m.get("region") or {}).get("type") == "full":
                    continue
                occupied |= build_motif_mask(m, grid_size)
        mask |= ~occupied

    return mask, changed_notes


def evaluate_case(base_dir: Path, var_dir: Path, grid_size: int) -> dict:
    base_plan, var_plan = load_plan(base_dir), load_plan(var_dir)
    grid_a, grid_b = load_grid(base_dir), load_grid(var_dir)
    assert grid_a.shape == grid_b.shape, "基准与变体动作网格尺寸不一致"

    target, changed_notes = derive_target_mask(base_plan, var_plan, grid_size)
    diff = grid_a != grid_b

    n_target = int(target.sum())
    n_nontarget = int((~target).sum())
    changed_in = int((diff & target).sum())
    changed_out = int((diff & ~target).sum())

    stats = load_stats(var_dir)
    violations = stats.get("violations", {}) or {}
    repair = stats.get("llm_repair", {}) or {}
    # 注意：violations.*_after 是进入 LLM 修复前的状态，最终值在 llm_repair.final_*
    vh_final = repair.get("final_hard", violations.get("hard_after", ""))
    vc_final = repair.get("final_craft", violations.get("craft_after", ""))

    return {
        "case": var_dir.name,
        "input": (var_plan.get("history") or [{}])[0].get("input", ""),
        "changed_motifs": "; ".join(changed_notes),
        "target_cells": n_target,
        "changed_in_target": changed_in,
        "changed_out_target": changed_out,
        "edit_effect_target": changed_in / n_target if n_target else float("nan"),
        "preserve_non_target": 1.0 - changed_out / n_nontarget if n_nontarget else float("nan"),
        "V_h_after": vh_final,
        "V_c_after": vc_final,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="编辑局部性定量评估")
    parser.add_argument("--edit-root", type=Path, default=Path("outputs/runs/edit"))
    parser.add_argument("--baseline", type=str, default="edt_00")
    parser.add_argument("--grid", type=int, default=GRID_SIZE)
    parser.add_argument("--out", type=Path, default=Path("outputs/analysis/edit_locality.csv"))
    args = parser.parse_args()

    base_dir = args.edit_root / args.baseline
    if not base_dir.exists():
        raise SystemExit(f"基准案例不存在: {base_dir}")

    rows = []
    for var_dir in sorted(p for p in args.edit_root.iterdir() if p.is_dir()):
        if var_dir.name == args.baseline:
            continue
        rows.append(evaluate_case(base_dir, var_dir, args.grid))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # 终端 Markdown 汇总表
    print("\n| 案例 | 目标区域格数 | EditEffect_target | Preserve_non-target | $V_h$ | $V_c$ |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(
            f"| {r['case']} | {r['target_cells']} | {r['edit_effect_target']:.3f} "
            f"| {r['preserve_non_target']:.3f} | {r['V_h_after']} | {r['V_c_after']} |"
        )
    effects = [r["edit_effect_target"] for r in rows]
    preserves = [r["preserve_non_target"] for r in rows]
    print(
        f"\n均值: EditEffect_target={np.nanmean(effects):.3f}, "
        f"Preserve_non-target={np.nanmean(preserves):.3f}"
    )
    print(f"逐案例结果已写入 {args.out}")


if __name__ == "__main__":
    main()
