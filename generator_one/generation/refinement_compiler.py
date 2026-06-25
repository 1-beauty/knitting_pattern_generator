"""
Refinement 编译器 v7.1

职责：
- 在 base action grid 上做稀疏、受控的低频动作替换
- 只替换 primary → refinement：
  - f_tuck → f_tuck_2
  - b_tuck → b_tuck_2
  - f_split / b_split → split_v（仅 junction）
- 受 refinement_mask 和使用预算约束

说明：
- split_v 只在 zone_type=transition/boundary 且相邻涉及 bed/semantic 切换时使用
- tuck_2 在细纹理区、张力补偿区稀疏使用
- 所有替换不得破坏硬性规则
"""

import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field

from core import actions
from utils.logger import logger


@dataclass
class RefinementConfig:
    # tuck variant 替换概率 / 密度
    tuck_variant_ratio: float = 0.15       # 允许替换的 tuck 格中最多替换 15%
    # split_v 全图最大使用量
    split_v_max_budget: int = 6            # 40×40 上最多 6 格 split_v
    # 最小邻域 semantic 差异才触发 split_v
    split_v_min_neighbor_diff: int = 2     # 至少 2 个不同 semantic 邻居


@dataclass
class RefinementStatistics:
    tuck_to_tuck2: int = 0
    split_to_splitv: int = 0
    total_candidates: int = 0
    budget_remaining: int = 0


class RefinementCompiler:
    def __init__(self, config: Optional[RefinementConfig] = None):
        self.config = config or RefinementConfig()

    def refine(
        self,
        action_grid: np.ndarray,
        refinement_mask: np.ndarray,
        stitch_grid: Optional[np.ndarray] = None,
        role_grid=None,
    ) -> np.ndarray:
        """
        在 action_grid 上做局部精修替换。

        Args:
            action_grid: (H, W) uint8
            refinement_mask: (H, W) bool, True = 允许 refinement
            stitch_grid: (H, W) 语义类型（可选，用于 split_v 判断）
            role_grid: RoleGrid（可选，用于 zone_type 判断）
        """
        result = action_grid.copy()
        rows, cols = result.shape
        stats = RefinementStatistics()

        # 验证 mask 形状
        if refinement_mask is None or refinement_mask.shape != action_grid.shape:
            logger.warning("refinement_mask shape mismatch or None; using full-true mask")
            refinement_mask = np.ones_like(action_grid, dtype=bool)

        # ============================================================
        # Phase 1: tuck → tuck_2 替换
        # ============================================================
        _f_tuck = actions.idx_safe("f_tuck", default=0)
        _b_tuck = actions.idx_safe("b_tuck", default=0)
        _f_tuck_2 = actions.idx_safe("f_tuck_2", default=_f_tuck)
        _b_tuck_2 = actions.idx_safe("b_tuck_2", default=_b_tuck)

        tuck_candidates = []
        for i in range(rows):
            for j in range(cols):
                if not refinement_mask[i, j]:
                    continue
                a = int(result[i, j])
                if a == _f_tuck or a == _b_tuck:
                    tuck_candidates.append((i, j, a))

        stats.total_candidates += len(tuck_candidates)

        # 按 phase 周期稀疏选择
        max_tuck_replacements = max(1, int(len(tuck_candidates) * self.config.tuck_variant_ratio))
        replaced = 0

        for idx, (i, j, a) in enumerate(tuck_candidates):
            if replaced >= max_tuck_replacements:
                break

            # 稀疏策略：每隔几个替换一个
            if idx % max(1, len(tuck_candidates) // max_tuck_replacements) != 0:
                continue

            # 检查邻域：优先在非核心位置替换
            zone = "core"
            if role_grid is not None:
                zone = getattr(role_grid[i, j], "zone_type", "core")

            # 核心区不替换，只替换边缘/support/transition
            if zone == "core":
                # 但如果是细纹理 motif，允许少量核心区替换
                motif_name = ""
                if role_grid is not None:
                    motif_name = getattr(role_grid[i, j], "motif_name", "")
                if motif_name not in {"staggered_tuck_relief", "tuck_wave_5x4"}:
                    continue

            if a == _f_tuck:
                result[i, j] = _f_tuck_2
            elif a == _b_tuck:
                result[i, j] = _b_tuck_2

            replaced += 1
            stats.tuck_to_tuck2 += 1

        # ============================================================
        # Phase 2: split → split_v（junction only）
        # ============================================================
        _f_split = actions.idx_safe("f_split", default=0)
        _b_split = actions.idx_safe("b_split", default=0)
        _split_v = actions.idx_safe("split_v", default=_f_split)

        budget = self.config.split_v_max_budget

        for i in range(rows):
            if budget <= 0:
                break
            for j in range(cols):
                if budget <= 0:
                    break
                if not refinement_mask[i, j]:
                    continue

                a = int(result[i, j])
                if a != _f_split and a != _b_split:
                    continue

                # 检查 zone_type：只在 transition / boundary 触发
                zone = "core"
                if role_grid is not None:
                    zone = getattr(role_grid[i, j], "zone_type", "core")

                if zone not in {"transition", "boundary"}:
                    continue

                # 检查邻域 semantic 差异
                if stitch_grid is not None:
                    neighbor_semantics = set()
                    curr_sem = int(stitch_grid[i, j])
                    for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ni, nj = i + di, j + dj
                        if 0 <= ni < rows and 0 <= nj < cols:
                            neighbor_semantics.add(int(stitch_grid[ni, nj]))

                    # 除去自身，需要有足够的差异
                    neighbor_semantics.discard(curr_sem)
                    if len(neighbor_semantics) < self.config.split_v_min_neighbor_diff:
                        continue

                result[i, j] = _split_v
                budget -= 1
                stats.split_to_splitv += 1

        stats.budget_remaining = budget

        logger.info(f"  refinement done")
        logger.info(f"    tuck->tuck_2: {stats.tuck_to_tuck2}")
        logger.info(f"    split->split_v: {stats.split_to_splitv}")
        logger.info(f"    split_v budget remaining: {stats.budget_remaining}")

        return result

    def get_statistics(self) -> Dict:
        return {}