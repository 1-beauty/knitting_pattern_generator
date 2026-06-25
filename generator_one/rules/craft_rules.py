"""
工艺规则 + 张力过渡 + 语义层连接检查（v7.1）

这些规则违反不会导致机器损坏，但会影响织物质量。
可以由 LLM 修复代理做更智能的修复。

规则清单：
  C1: 同列 front/back loop 直接切换（需隐含 transfer）
      收紧条件：
      - 附近无 transfer/split 过渡
      - 垂直方向连续 >= 2 行才报
  C2: Cable 左右位移负载不平衡
  C3: 含床间移针的行缺少 tuck/miss/b_knit 支撑
  C4: CABLE/TUCK 区域外围缺少 STRUCTURE 边框（语义层检查）
  C5: 相邻 VOID 区域未隔离（语义层检查）
  C6: TUCK 与 CABLE 直接相邻（语义层检查）

  T1: 张力过渡（软约束）
"""

import numpy as np
from typing import List, Set, Tuple, Dict

from config import GRID_SIZE
from core import actions
from core.semantic_types import StitchType, TENSION, NEEDS_BORDER, get_name
from rules.physical_rules import Violation


# ============================================================
# 动作层工艺规则
# ============================================================

def check_action_grid(grid: np.ndarray) -> List[Violation]:
    """
    在动作索引网格上检查工艺规则。

    C1: 同列 front/back loop 直接切换
        收紧条件：
        - 只看 loop 类动作
        - 附近 2 行 × 2 列内没有任何 transfer/split
        - 同一列垂直方向连续出现 >= 2 次才报

    C2: Cable 左右位移负载不平衡
    C3: 含床间移针的行缺少 tuck/miss/b_knit 支撑
    """
    violations: List[Violation] = []
    rows, cols = grid.shape

    _LEFT = actions.left_transfer_ids()
    _RIGHT = actions.right_transfer_ids()
    _BED = actions.bed_transfer_ids()
    _TUCK = actions.tuck_ids()
    _MISS = actions.miss_ids()
    _LOOP = actions.loop_ids()
    _SPLIT = actions.split_ids()
    _XFER = actions.transfer_ids()

    # ------------------------------------------------------------
    # C2 / C3：按行检查
    # ------------------------------------------------------------
    for i in range(rows):
        row_vals = grid[i, :].astype(int)

        # C2: Cable 左右负载平衡
        left_cols = [j for j, x in enumerate(row_vals) if x in _LEFT]
        right_cols = [j for j, x in enumerate(row_vals) if x in _RIGHT]

        if left_cols and right_cols:
            left_load = sum(abs(actions.offset(int(row_vals[j]))) for j in left_cols)
            right_load = sum(abs(actions.offset(int(row_vals[j]))) for j in right_cols)

            if abs(left_load - right_load) > 2:
                violations.append(Violation(
                    "CRAFT", "C2", i, 0,
                    f"左右位移负载不平衡: L={left_load} R={right_load}",
                    "使 cable 左右位移尽量成对"
                ))

        # C3: 床间移针行缺少支撑
        has_bed_xfer = any(x in _BED for x in row_vals)
        has_support = any(
            (x in _TUCK) or (x in _MISS) or (x == actions.idx_safe("b_knit"))
            for x in row_vals
        )
        if has_bed_xfer and not has_support:
            violations.append(Violation(
                "CRAFT", "C3", i, 0,
                "含床间移针但缺少 tuck/miss/b_knit 支撑",
                "补入 b_tuck 或 miss"
            ))

    # ------------------------------------------------------------
    # C1: 精确版 front/back loop 切换检查
    # ------------------------------------------------------------
    def _has_transition_nearby(row: int, col: int) -> bool:
        """
        检查该位置附近是否已有 transfer/split 做过渡
        范围：上下 [-1, +2] 行，左右 [-2, +2] 列
        """
        for di in range(-1, 3):
            ni = row + di
            if not (0 <= ni < rows):
                continue
            for dj in range(-2, 3):
                nj = col + dj
                if not (0 <= nj < cols):
                    continue
                val = int(grid[ni, nj])
                if val in _SPLIT or val in _XFER:
                    return True
        return False

    # 对每一列统计“连续切换 streak”
    col_streak: Dict[int, int] = {}
    col_prev_row: Dict[int, int] = {}
    col_max_streak: Dict[int, int] = {}
    col_max_streak_start: Dict[int, int] = {}

    for i in range(rows - 1):
        for j in range(cols):
            curr = int(grid[i, j])
            below = int(grid[i + 1, j])

            # 只看 loop 类动作
            if curr not in _LOOP or below not in _LOOP:
                col_streak[j] = 0
                continue

            bed_curr = actions.bed(curr)
            bed_below = actions.bed(below)

            # bed 信息不存在，或相同，不报
            if not bed_curr or not bed_below or bed_curr == bed_below:
                col_streak[j] = 0
                continue

            # 附近已有 split / transfer 过渡，不报
            if _has_transition_nearby(i, j):
                col_streak[j] = 0
                continue

            # streak 统计
            prev = col_prev_row.get(j, -99)
            if i - prev == 1:
                col_streak[j] = col_streak.get(j, 0) + 1
            else:
                col_streak[j] = 1

            col_prev_row[j] = i

            # 记录最大 streak
            if col_streak[j] > col_max_streak.get(j, 0):
                col_max_streak[j] = col_streak[j]
                col_max_streak_start[j] = i - col_streak[j] + 1

    for j, streak in col_max_streak.items():
        if streak >= 3:
            start_row = col_max_streak_start.get(j, 0)
            violations.append(Violation(
                "CRAFT", "C1", start_row, j,
                f"col={j} 连续 {streak} 行 front/back loop 切换，附近无过渡动作",
                "在切换处插入 f_split / b_split 过渡"
            ))

    return violations


# ============================================================
# 语义层连接规则
# ============================================================

def check_stitch_grid(stitch_grid: np.ndarray, grid_size: int = GRID_SIZE) -> List[Violation]:
    """在语义针法网格上检查连接规则"""
    violations: List[Violation] = []
    rows, cols = stitch_grid.shape

    # C4: CABLE/TUCK 边框检查
    for st_val in [StitchType.CABLE, StitchType.TUCK]:
        if not NEEDS_BORDER.get(st_val, False):
            continue

        positions = set(zip(*np.where(stitch_grid == int(st_val))))
        if not positions:
            continue

        border = _get_border(positions, grid_size)
        bg_border = [
            p for p in border
            if StitchType(stitch_grid[p[0], p[1]]) == StitchType.BACKGROUND
        ]

        if bg_border:
            sample = list(bg_border)[0]
            violations.append(Violation(
                "CRAFT", "C4", sample[0], sample[1],
                f"{get_name(st_val)} 区域外围 {len(bg_border)} 处缺少 STRUCTURE 边框",
                "将外围背景格改为 STRUCTURE"
            ))

    # C5: 相邻 VOID 隔离
    void_positions = set(zip(*np.where(stitch_grid == int(StitchType.VOID))))
    if void_positions:
        regions = _flood_fill_regions(stitch_grid, StitchType.VOID, grid_size)
        for i in range(len(regions)):
            for k in range(i + 1, len(regions)):
                if _regions_adjacent(regions[i], regions[k]):
                    sample = list(regions[i])[0]
                    violations.append(Violation(
                        "CRAFT", "C5", sample[0], sample[1],
                        "相邻 VOID 区域未隔离",
                        "在交界处插入 STRUCTURE 隔离格"
                    ))

    # C6: TUCK 与 CABLE 直接相邻
    tuck_positions = set(zip(*np.where(stitch_grid == int(StitchType.TUCK))))
    cable_positions = set(zip(*np.where(stitch_grid == int(StitchType.CABLE))))
    if tuck_positions and cable_positions:
        tuck_border = _get_border(tuck_positions, grid_size)
        adjacent = tuck_border & cable_positions
        if adjacent:
            sample = list(adjacent)[0]
            violations.append(Violation(
                "CRAFT", "C6", sample[0], sample[1],
                f"TUCK 与 CABLE 直接相邻 {len(adjacent)} 处",
                "在交界处插入 STRUCTURE 或 DEGREE 缓冲"
            ))

    return violations


# ============================================================
# 张力评分
# ============================================================

def tension_score(grid: np.ndarray) -> float:
    """计算动作网格的平均相邻张力差"""
    rows, cols = grid.shape
    total_diff = 0.0
    count = 0

    for i in range(rows):
        for j in range(cols):
            t = actions.tension(int(grid[i, j]))

            if j + 1 < cols:
                total_diff += abs(t - actions.tension(int(grid[i, j + 1])))
                count += 1
            if i + 1 < rows:
                total_diff += abs(t - actions.tension(int(grid[i + 1, j])))
                count += 1

    return total_diff / max(count, 1)


# ============================================================
# 语义层自动修复（保守版）
# ============================================================

def auto_fix_stitch_grid(
    stitch_grid: np.ndarray,
    violations: List[Violation],
    grid_size: int = GRID_SIZE,
) -> np.ndarray:
    """修复语义层连接规则违反"""
    fixed = stitch_grid.copy()

    for v in violations:
        # C4: 补 STRUCTURE 边框
        if v.rule == "C4":
            for st_val in [StitchType.CABLE, StitchType.TUCK]:
                positions = set(zip(*np.where(fixed == int(st_val))))
                if not positions:
                    continue
                border = _get_border(positions, grid_size)
                for bi, bj in border:
                    if StitchType(fixed[bi, bj]) == StitchType.BACKGROUND:
                        fixed[bi, bj] = int(StitchType.STRUCTURE)

        # C5: VOID 隔离
        elif v.rule == "C5":
            regions = _flood_fill_regions(fixed, StitchType.VOID, grid_size)
            for i in range(len(regions)):
                for k in range(i + 1, len(regions)):
                    if _regions_adjacent(regions[i], regions[k]):
                        boundary = _find_boundary(regions[i], regions[k])
                        for bi, bj in boundary:
                            fixed[bi, bj] = int(StitchType.STRUCTURE)

        # C6: TUCK/CABLE 隔离
        elif v.rule == "C6":
            tuck_pos = set(zip(*np.where(fixed == int(StitchType.TUCK))))
            cable_pos = set(zip(*np.where(fixed == int(StitchType.CABLE))))
            tuck_border = _get_border(tuck_pos, grid_size)
            for pos in tuck_border & cable_pos:
                fixed[pos[0], pos[1]] = int(StitchType.STRUCTURE)

    return fixed


# ============================================================
# 动作层自动修复（保守版）
# 不再滥用 split_v，改用 f_split / b_tuck 等 primary actions
# ============================================================

def auto_fix_action_grid(
    grid: np.ndarray,
    violations: List[Violation],
) -> np.ndarray:
    """修复动作层工艺违反（保守版）"""
    fixed = grid.copy()
    _f_split = actions.idx_safe("f_split")
    _b_tuck = actions.idx_safe("b_tuck")

    for v in violations:
        if v.rule == "C1":
            fixed[v.row, v.col] = _f_split

        elif v.rule == "C2":
            row_vals = fixed[v.row, :].astype(int)
            left_cols = [j for j, x in enumerate(row_vals) if x in actions.left_transfer_ids()]
            right_cols = [j for j, x in enumerate(row_vals) if x in actions.right_transfer_ids()]

            if len(left_cols) > len(right_cols) + 1:
                extra = len(left_cols) - len(right_cols) - 1
                for j in left_cols[-extra:]:
                    fixed[v.row, j] = _f_split

            elif len(right_cols) > len(left_cols) + 1:
                extra = len(right_cols) - len(left_cols) - 1
                for j in right_cols[-extra:]:
                    fixed[v.row, j] = _f_split

        elif v.rule == "C3":
            row_vals = fixed[v.row, :].astype(int)
            bed_cols = [j for j, x in enumerate(row_vals) if x in actions.bed_transfer_ids()]
            if bed_cols:
                mid = bed_cols[len(bed_cols) // 2]
                fixed[v.row, mid] = _b_tuck

    return fixed


# ============================================================
# 辅助
# ============================================================

def _get_border(positions: Set[Tuple[int, int]], grid_size: int) -> Set[Tuple[int, int]]:
    border = set()
    for i, j in positions:
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ni, nj = i + di, j + dj
            if 0 <= ni < grid_size and 0 <= nj < grid_size:
                if (ni, nj) not in positions:
                    border.add((ni, nj))
    return border


def _flood_fill_regions(
    grid: np.ndarray,
    target: StitchType,
    grid_size: int,
) -> List[Set[Tuple[int, int]]]:
    visited = np.zeros((grid_size, grid_size), dtype=bool)
    regions: List[Set[Tuple[int, int]]] = []

    for i in range(grid_size):
        for j in range(grid_size):
            if visited[i, j] or StitchType(grid[i, j]) != target:
                continue

            region: Set[Tuple[int, int]] = set()
            stack = [(i, j)]

            while stack:
                ci, cj = stack.pop()
                if ci < 0 or ci >= grid_size or cj < 0 or cj >= grid_size:
                    continue
                if visited[ci, cj] or StitchType(grid[ci, cj]) != target:
                    continue

                visited[ci, cj] = True
                region.add((ci, cj))
                stack.extend([
                    (ci - 1, cj),
                    (ci + 1, cj),
                    (ci, cj - 1),
                    (ci, cj + 1),
                ])

            regions.append(region)

    return regions


def _regions_adjacent(r1: Set[Tuple[int, int]], r2: Set[Tuple[int, int]]) -> bool:
    for i, j in r1:
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (i + di, j + dj) in r2:
                return True
    return False


def _find_boundary(
    r1: Set[Tuple[int, int]],
    r2: Set[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    boundary = []
    for i, j in r1:
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (i + di, j + dj) in r2:
                boundary.append((i, j))
                break
    return boundary