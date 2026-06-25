"""
物理规则 + 制造约束

这些规则不可妥协，违反意味着织物无法成型或机器损坏。

规则清单：
  H1: 非法动作索引
  H2: 线圈下方缺少物理支撑（起针行除外）
  H3: 移针横向偏移超限（±2）
  H4: 移针目标越界
  H5: 同行移针目标冲突
  H6: 同列连续 Tuck 超过堆叠上限
  H7: Drop 后上方未清空
  H8: 同行移针方向冲突（不能同时前→后 和 后→前 作用于同一针位）
"""
import numpy as np
from typing import List, Set, Dict
from dataclasses import dataclass

from core import actions


@dataclass
class Violation:
    level: str        # "HARD" or "CRAFT"
    rule: str         # 规则编号
    row: int
    col: int
    detail: str
    suggestion: str = ""

    def __repr__(self):
        return f"[{self.level}] {self.rule} @({self.row},{self.col}): {self.detail}"


def check(grid: np.ndarray) -> List[Violation]:
    """
    运行全部物理 + 制造硬性规则检查。

    Args:
        grid: 40×40 动作索引网格，dtype=uint8，值 0~16

    Returns:
        违反列表（空列表 = 全部通过）
    """
    violations: List[Violation] = []
    rows, cols = grid.shape

    _VALID = actions.ALL_ACTION_INDICES
    _TRANSFER = actions.transfer_ids()
    _TUCK = actions.tuck_ids()
    _DROP = actions.drop_ids()
    _MAX_OFFSET = actions.executable_max_transfer_offset()

    for i in range(rows):
        # 同行移针目标碰撞检测
        row_targets: Dict[int, int] = {}

        for j in range(cols):
            a = int(grid[i, j])

            # H1: 非法索引
            if a not in _VALID:
                violations.append(Violation(
                    "HARD", "H1", i, j,
                    f"非法动作索引 {a}，合法范围 0~{actions.NUM_ACTIONS - 1}",
                    "检查 action_mapper 输出"
                ))
                continue

            # H2: 物理支撑（最后一行视为起针行，跳过）
            if actions.requires_support(a) and i < rows - 1:
                below = int(grid[i + 1, j])
                if below in _VALID and not actions.supports_above(below):
                    violations.append(Violation(
                        "HARD", "H2", i, j,
                        f"{actions.name(a)} 下方 {actions.name(below)} 无法提供支撑",
                        "下方应放置成圈/集圈/劈针等可支撑动作"
                    ))

            # H3 + H4 + H5: 移针约束
            if a in _TRANSFER:
                off = actions.offset(a)

                # H3: 偏移超限
                if abs(off) > _MAX_OFFSET:
                    violations.append(Violation(
                        "HARD", "H3", i, j,
                        f"{actions.name(a)} 偏移 {off} 超过 ±{_MAX_OFFSET}",
                        "降级为更小位移或改用 split"
                    ))

                # H4: 目标越界
                target = j + off
                if not (0 <= target < cols):
                    violations.append(Violation(
                        "HARD", "H4", i, j,
                        f"{actions.name(a)} 目标列 {target} 越界",
                        "改用更小位移或改用 split/knit"
                    ))
                else:
                    # H5: 目标碰撞
                    if target in row_targets:
                        violations.append(Violation(
                            "HARD", "H5", i, j,
                            f"移针目标 col={target} 冲突，来源 col={row_targets[target]} 和 col={j}",
                            "移除一个移针或调整间距"
                        ))
                    else:
                        row_targets[target] = j

            # H6: Tuck 垂直堆叠
            if a in _TUCK:
                # 只在连续段起点检测，避免重复报告
                if i == 0 or int(grid[i - 1, j]) not in _TUCK:
                    run = 1
                    k = i + 1
                    while k < rows and int(grid[k, j]) in _TUCK:
                        run += 1
                        k += 1
                    limit = actions.max_vertical_stack(a) or 3
                    if run > limit:
                        violations.append(Violation(
                            "HARD", "H6", i, j,
                            f"col={j} 连续 Tuck {run} 行，上限 {limit}",
                            "插入 knit/split 打断堆叠"
                        ))

            # H7: Drop 后上方应为空
            if a in _DROP:
                for up in range(0, i):
                    above = int(grid[up, j])
                    if above in _VALID and actions.supports_above(above):
                        violations.append(Violation(
                            "HARD", "H7", i, j,
                            f"Drop 上方 row={up} 仍有支撑结构 {actions.name(above)}",
                            "Drop 上方应保持空位直到新的起针"
                        ))
                        break

    # H8: 同行不能同时有冲突方向的床间移针
    _BED_XFER = actions.bed_transfer_ids()
    for i in range(rows):
        row_vals = grid[i, :].astype(int)
        bed_xfers = [int(x) for x in row_vals if x in _BED_XFER]
        if len(bed_xfers) >= 2:
            from_beds = set()
            for bx in bed_xfers:
                fb = actions.info(bx).get("from_bed")
                if fb:
                    from_beds.add(fb)
            if len(from_beds) > 1:
                violations.append(Violation(
                    "HARD", "H8", i, 0,
                    f"同行存在双向床间移针",
                    "拆到相邻行或只保留单方向"
                ))

    return violations


def auto_fix(grid: np.ndarray, violations: List[Violation]) -> np.ndarray:
    """
    自动修复硬性违反。

    修复策略保守：优先降级为安全动作。
    无法确定时退化为 f_knit。
    """
    fixed = grid.copy()
    _f_knit = actions.idx("f_knit")
    _b_knit = actions.idx("b_knit")
    _f_split = actions.idx("f_split")
    _miss = actions.idx("miss")

    for v in violations:
        i, j = v.row, v.col

        if v.rule == "H1":
            fixed[i, j] = _f_knit

        elif v.rule == "H2":
            # 补下方支撑。若下方是 miss，不直接覆盖它；miss 常用于
            # 镂空/浮线类结构，粗暴改成 b_knit 会把图案抹成背景。
            if i < grid.shape[0] - 1:
                below = int(fixed[i + 1, j])
                if below in actions.miss_ids():
                    fixed[i, j] = _miss
                else:
                    fixed[i + 1, j] = _b_knit
            else:
                fixed[i, j] = _f_knit

        elif v.rule in ("H3", "H4", "H5"):
            fixed[i, j] = _f_split

        elif v.rule == "H6":
            fixed[i, j] = _f_knit

        elif v.rule == "H7":
            fixed[i, j] = _miss

        elif v.rule == "H8":
            # 把该行所有 bed_transfer 改为 split_v
            for jj in range(grid.shape[1]):
                if int(fixed[i, jj]) in actions.bed_transfer_ids():
                    fixed[i, jj] = _f_split

        else:
            fixed[i, j] = _f_knit

    return fixed
