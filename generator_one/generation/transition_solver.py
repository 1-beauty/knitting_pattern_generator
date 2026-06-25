"""
过渡求解器 v9.0

职责：
- 输入：基础 ActionGrid + EventPoint 列表
- 输出：在主事件点相邻格（仅相邻）按需插入过渡动作

关键原则：
1. 过渡必须是局部、相邻、紧凑的
2. 只有当相邻格存在真实动作冲突时才插过渡
3. 不会主动去"填充图案"
4. 过渡动作来自主事件点向外扩散一格，不超过一格
"""

import numpy as np
from typing import List, Dict, Set, Tuple

from generation.visual_types import EventPoint
from core import actions
from utils.logger import logger


class TransitionSolver:
    """
    基于相邻关系，在必要位置插入过渡动作。
    """

    def __init__(self):
        self._f_knit = actions.idx_safe("f_knit", default=0)
        self._b_knit = actions.idx_safe("b_knit", default=0)
        self._f_split = actions.idx_safe("f_split", default=0)
        self._b_split = actions.idx_safe("b_split", default=0)
        self._TRANSFER = actions.transfer_ids()
        self._TUCK = actions.tuck_ids()
        self._MISS = actions.miss_ids()

    def solve(
        self,
        action_grid: np.ndarray,
        events: List[EventPoint],
    ) -> np.ndarray:
        grid = action_grid.copy()
        rows, cols = grid.shape
        inserted = 0

        # 收集所有主事件位置（不允许被过渡覆盖），并过滤无效项
        event_positions: Set[Tuple[int, int]] = set()
        for e in events:
            try:
                r = int(e.row)
                c = int(e.col)
            except Exception:
                continue
            if 0 <= r < rows and 0 <= c < cols:
                event_positions.add((r, c))

        for event in events:
            try:
                r = int(event.row)
                c = int(event.col)
            except Exception:
                logger.warning(f"transition_solver: invalid event coords {event}")
                continue

            if not (0 <= r < rows and 0 <= c < cols):
                logger.debug(f"transition_solver: skipping out-of-bounds event ({r},{c})")
                continue

            a = int(grid[r, c])

            # 只对 transfer 类动作做局部过渡插入
            if a not in self._TRANSFER:
                continue

            # 判断 transfer 方向
            off = actions.offset(a)
            is_left = (off < 0)

            split_action = self._f_split if is_left else self._b_split

            # 只在上下相邻格（不是左右）插过渡
            for nr, nc in [(r - 1, c), (r + 1, c)]:
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue

                # 不允许覆盖其他主事件点
                if (nr, nc) in event_positions:
                    continue

                nb = int(grid[nr, nc])

                # 只有当相邻格是底布（f_knit）时才可能插过渡
                if nb != self._f_knit:
                    continue

                # 检查是否真的存在局部冲突：
                # 1. 张力差过大
                t_event = actions.tension(a)
                t_nb = actions.tension(nb)
                tension_diff = abs(t_event - t_nb)

                # 2. transfer 本身需要 requires_support
                needs_support = actions.requires_support(a)

                if tension_diff > 1.5 or needs_support:
                    grid[nr, nc] = split_action
                    inserted += 1

        logger.info(f"  transition solver: {inserted} transitions inserted")
        return grid