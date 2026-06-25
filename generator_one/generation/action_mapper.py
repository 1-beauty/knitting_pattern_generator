"""
动作编译器 v7.1（motif-aware）

职责：
- 将 StitchTypeGrid 编译为 ActionGrid
- 支持 motif compilation result 优先覆盖
- base mapping 只使用 primary structural actions
- refinement actions 不在此产出

说明：
- 如果上游提供了 explicit_action_grid（来自 motif_compiler），
  非 fallback 的格子直接使用，不再走 base mapping
- transition / corner 只处理 fallback 区域，不覆盖 motif core
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from core import actions
from core.semantic_types import StitchType, compatibility, TENSION
from utils.logger import logger


@dataclass
class MappingConfig:
    cable_twist_period: int = 6
    double_bed_width: int = 2
    tuck_spacing: int = 3
    mesh_period: int = 4


@dataclass
class MappingStatistics:
    total_cells: int = 0
    mapped_cells: int = 0
    motif_cells: int = 0
    fallback_cells: int = 0
    transition_cells: int = 0
    distribution: Dict[int, int] = field(default_factory=dict)


class ActionMapper:
    def __init__(
        self,
        config: Optional[MappingConfig] = None,
        handle_transitions: bool = True,
    ):
        self.config = config or MappingConfig()
        self.handle_transitions = handle_transitions
        self.stats = MappingStatistics()
    
    def _has_neighbor_type(
        self,
        stitch_grid: np.ndarray,
        row: int,
        col: int,
        target: StitchType,
    ) -> bool:
        rows, cols = stitch_grid.shape
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ni, nj = row + di, col + dj
            if 0 <= ni < rows and 0 <= nj < cols:
                if StitchType(stitch_grid[ni, nj]) == target:
                    return True
        return False

    def map(
        self,
        stitch_grid: np.ndarray,
        explicit_action_grid: Optional[np.ndarray] = None,
        motif_source_map: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        主入口。

        Args:
            stitch_grid: (H, W) StitchType 值
            explicit_action_grid: (H, W) int16, -1 = fallback（来自 motif_compiler）
            motif_source_map: (H, W) str, motif 名或 "fallback"
        """
        rows, cols = stitch_grid.shape
        grid = np.zeros((rows, cols), dtype=np.uint8)
        self.stats = MappingStatistics(total_cells=rows * cols)

        has_explicit = explicit_action_grid is not None

        # 第一遍：填入 motif explicit 或 base fallback
        for i in range(rows):
            for j in range(cols):
                if has_explicit and explicit_action_grid[i, j] >= 0:
                    grid[i, j] = int(explicit_action_grid[i, j])
                    self.stats.motif_cells += 1
                else:
                    st = StitchType(stitch_grid[i, j])
                    grid[i, j] = self._base_action(stitch_grid, i, j, st)
                    self.stats.fallback_cells += 1

                self.stats.mapped_cells += 1

        # 第二遍：只在 fallback 区域做 transition 平滑
        if self.handle_transitions:
            self._smooth_fallback_transitions(grid, stitch_grid, explicit_action_grid)

        self.stats.distribution = self._distribution(grid)
        self._log_stats()
        return grid

    # ============================================================
    # 基础映射（只用 primary actions，保守 fallback）
    # ============================================================

    def _base_action(
        self,
        stitch_grid: np.ndarray,
        row: int,
        col: int,
        st: StitchType,
    ) -> int:
        if st == StitchType.BACKGROUND:
            return actions.idx("f_knit")

        if st == StitchType.ACTIVE:
            return actions.idx("f_knit")

        if st == StitchType.STRUCTURE:
            # 如果 structure 紧贴 cable，稀疏插入 split 作为边界过渡，
            # 打断 front/back loop 的连续切换 streak，缓解 C1
            if self._has_neighbor_type(stitch_grid, row, col, StitchType.CABLE):
                if row % 5 == 2:
                    return actions.idx("f_split")
            return actions.idx("b_knit")

        if st == StitchType.SUPPORT:
            return actions.idx("b_knit")

        if st == StitchType.DEGREE:
            if (row + col) % 2 == 0:
                return actions.idx("f_split")
            return actions.idx("b_split")

        if st == StitchType.DOUBLE_BED:
            w = max(1, self.config.double_bed_width)
            band = (col // w) % 2
            return actions.idx("f_knit" if band == 0 else "b_knit")

        if st == StitchType.TUCK:
            spacing = max(2, self.config.tuck_spacing)
            if col % spacing == 0:
                return actions.idx("f_tuck" if row % 2 == 0 else "b_tuck")
            return actions.idx("f_knit")

        if st == StitchType.CABLE:
            return self._cable_fallback(stitch_grid, row, col)

        if st == StitchType.VOID:
            phase = (row + col) % max(2, self.config.mesh_period)
            if phase == 1:
                return actions.idx("miss")
            return actions.idx("f_knit")

        return actions.idx("f_knit")

    def _cable_fallback(self, stitch_grid: np.ndarray, row: int, col: int) -> int:
        """极简 cable fallback：不再画骨架，只做安全映射"""
        return actions.idx("f_knit")

    # ============================================================
    # fallback 区域 transition 平滑
    # ============================================================

    def _smooth_fallback_transitions(
        self,
        grid: np.ndarray,
        stitch_grid: np.ndarray,
        explicit_action_grid: Optional[np.ndarray],
    ):
        """只在 fallback 区域的语义边界做简单平滑"""
        rows, cols = grid.shape

        for i in range(rows):
            for j in range(cols):
                # 跳过 motif 区域
                if explicit_action_grid is not None and explicit_action_grid[i, j] >= 0:
                    continue

                curr_st = StitchType(stitch_grid[i, j])
                if curr_st == StitchType.BACKGROUND:
                    continue

                # 检查是否在语义边界
                is_boundary = False
                for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    ni, nj = i + di, j + dj
                    if 0 <= ni < rows and 0 <= nj < cols:
                        nb_st = StitchType(stitch_grid[ni, nj])
                        if nb_st != curr_st and compatibility(curr_st, nb_st) < 0.8:
                            is_boundary = True
                            break

                if is_boundary:
                    grid[i, j] = self._safe_transition_action(curr_st)
                    self.stats.transition_cells += 1

    def _safe_transition_action(self, st: StitchType) -> int:
        """安全过渡动作：只用 primary actions"""
        if st in {StitchType.CABLE, StitchType.TUCK}:
            return actions.idx("f_split")
        if st == StitchType.VOID:
            return actions.idx("b_knit")
        if st == StitchType.DOUBLE_BED:
            return actions.idx("b_knit")
        if st == StitchType.SUPPORT:
            return actions.idx("b_knit")
        return actions.idx("f_knit")

    # ============================================================
    # 工具
    # ============================================================

    def _distribution(self, grid: np.ndarray) -> Dict[int, int]:
        uniq, counts = np.unique(grid, return_counts=True)
        return dict(zip(uniq.astype(int), counts.astype(int)))

    def _log_stats(self):
        logger.info("  action mapping done")
        logger.info(f"    total: {self.stats.total_cells}")
        logger.info(f"    motif: {self.stats.motif_cells}")
        logger.info(f"    fallback: {self.stats.fallback_cells}")
        logger.info(f"    transitions: {self.stats.transition_cells}")

    def get_statistics(self):
        return self.stats


def action_grid_to_rgb(action_grid: np.ndarray) -> np.ndarray:
    rows, cols = action_grid.shape
    rgb = np.zeros((rows, cols, 3), dtype=np.uint8)
    for i in range(actions.NUM_ACTIONS):
        rgb[action_grid == i] = actions.color_rgb(i)
    rgb[~np.isin(action_grid, list(actions.ALL_ACTION_INDICES))] = (255, 255, 255)
    return rgb


def upscale_for_display(action_grid: np.ndarray, scale: int = 2) -> np.ndarray:
    return np.repeat(np.repeat(action_grid, scale, axis=0), scale, axis=1)