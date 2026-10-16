"""
动作构建器 v9.0

职责：
- 输入：RealizationPlan + EventPoint 列表
- 输出：40×40 ActionGrid

流程：
1. 初始化底布（base field）
2. 绘制边界（border style）
3. 写入事件点（event points）
4. 求解过渡（transition solver）
"""

import numpy as np
from typing import List, Tuple

from generation.visual_types import RealizationPlan, RealizationRegion, EventPoint
from generation.transition_solver import TransitionSolver
from generation.mask_utils import (
    point_in_mask, get_mask_shape, has_mask_shape,
    resolve_side_band_side, is_excluded_by_foreground,
)
from generation.layer_utils import layer_mask_contains, parent_scan_bbox, region_by_id
from core import actions
from utils.logger import logger


_FIELD_ACTION: dict = {
    "plain_front": "f_knit",
    "plain_back": "b_knit",
    "rib": None,        # 按列交替
    "links": None,      # 按行交替
    "mesh": "f_knit",
}


class ActionBuilder:
    def __init__(self, grid_size: int = 40):
        self.grid_size = grid_size
        self._f_knit = actions.idx_safe("f_knit", default=0)
        self._b_knit = actions.idx_safe("b_knit", default=0)
        self._transition_solver = TransitionSolver()
        self._regions_by_id = {}

    def build(
        self,
        realization_plan: RealizationPlan,
        events: List[EventPoint],
    ) -> np.ndarray:
        self._regions_by_id = region_by_id(realization_plan.regions)
        grid = np.full(
            (self.grid_size, self.grid_size),
            self._f_knit,
            dtype=np.uint8
        )

        # 确定区域 mask 和优先级
        sorted_regions = self._sort_regions(realization_plan.regions)

        # Step 1: 按优先级填底布 + 边界
        for region in sorted_regions:
            self._fill_base(grid, region)
            self._draw_border(grid, region)

        # Step 2: 写入事件点
        event_counts = {}
        region_map = {r.region_id: r for r in realization_plan.regions}
        _rejected_by_region = {}
        _rejection_reasons = {}  # track WHY events are rejected
        for event in events:
            try:
                r = int(event.row)
                c = int(event.col)
            except Exception:
                logger.warning(f"  invalid event coordinates: row={event.row} col={event.col}")
                continue

            if not (0 <= r < self.grid_size and 0 <= c < self.grid_size):
                logger.warning(f"  event out of bounds: ({r},{c})")
                continue

            region = region_map.get(event.region_id)
            if region is not None:
                try:
                    _in_region = self._event_in_region(r, c, region)
                except Exception as _exc:
                    if event.region_id not in _rejection_reasons:
                        _rejection_reasons[event.region_id] = f"EXCEPTION: {_exc}"
                    _rejected_by_region[event.region_id] = _rejected_by_region.get(event.region_id, 0) + 1
                    continue
                if not _in_region:
                    _rejected_by_region[event.region_id] = _rejected_by_region.get(event.region_id, 0) + 1
                    # Log first rejection per region with detailed reason
                    if event.region_id not in _rejection_reasons:
                        try:
                            _rejection_reasons[event.region_id] = self._debug_rejection_reason(r, c, region)
                        except Exception as _dbg_exc:
                            _rejection_reasons[event.region_id] = f"DEBUG_EXCEPTION: {_dbg_exc}"
                    continue
            elif region is None:
                if event.region_id not in _rejection_reasons:
                    _rejection_reasons[event.region_id] = f"REGION_NOT_FOUND in region_map (keys={list(region_map.keys())})"

            # 边框像素保护（纵深防御）: event_planner 已精确排除边框环像素，
            # 此处作为安全网，防止过渡求解或 LLM repair 引入的新事件覆盖边框。
            if region is not None and region.border_style != "none":
                try:
                    if self._is_on_border_outline(r, c, region):
                        continue
                except Exception:
                    pass

            # resolve action index safely
            action_idx = actions.idx_safe(event.action_abbr, default=self._f_knit)
            if action_idx is None:
                action_idx = self._f_knit
            grid[r, c] = action_idx
            event_counts[event.action_abbr] = event_counts.get(event.action_abbr, 0) + 1

        logger.info(f"  action builder: events placed: {event_counts}")
        if _rejected_by_region:
            logger.warning(f"  action builder: rejected by _event_in_region: {_rejected_by_region}")
            for rid, reason in _rejection_reasons.items():
                _r = region_map.get(rid)
                _p = getattr(_r, 'placement', {}) or {} if _r else {}
                logger.warning(
                    f"    [{rid}] first rejection reason: {reason} | "
                    f"placement: shape={_p.get('shape','?')} mask={_p.get('mask_shape','?')} "
                    f"size={_p.get('size','?')} center={_p.get('center','?')} "
                    f"type={_p.get('type','?')} parent={_p.get('parent_id','none')} "
                    f"ie={_p.get('inner_exclude','none')}"
                )

        # Step 3: 过渡求解
        # 只对 transition_policy == local_only 的 region 启用
        region_transition_policy = {
            r.region_id: r.transition_policy
            for r in realization_plan.regions
        }

        transition_events = [
            e for e in events
            if region_transition_policy.get(e.region_id, "none") == "local_only"
        ]

        grid = self._transition_solver.solve(grid, transition_events)

        # Step 4: transfer 稳定化
        pruned, balanced = self._stabilize_transfers(grid)
        logger.info(f"  action builder: transfer pruned={pruned}, balanced={balanced}")

        # Step 5: parent-mask hard clipping. Transition solving and later
        # stabilization may create support actions just outside a child mask;
        # for nested motifs those spillovers must be removed before aesthetic
        # and rule passes see the grid.
        clipped = self._clip_child_region_spillovers(grid, realization_plan)
        if clipped:
            logger.info(f"  action builder: clipped child spillovers={clipped}")

        # Step 6: 边框保护修复。过渡求解和 spillover 裁剪可能意外覆盖
        # border 像素，这里重新绘制所有 border region 的边框轮廓。
        self._restore_border_pixels(grid, realization_plan)

        self._regions_by_id = {}
        # Store rejection info for pipeline diagnostics
        self._last_rejection_info = {
            "rejected_by_region": _rejected_by_region,
            "rejection_reasons": _rejection_reasons,
            "events_placed": dict(event_counts),
        }
        return grid

    # ============================================================
    # Dense 编译（Plan-Grid 基线）
    # 绕过稀疏事件规划：在区域自身几何 mask 内按周期逐格写入纹理动作。
    # 与完整方法的差异（刻意保留，用于隔离贡献）：
    #   - 不成组（无 split/tuck 配对检查、无 cable 支撑针）
    #   - 不做父级作用域交集 Ω'(z)=Ω(z)∩Ω(parent(z))
    #   - 不做边框环排除 / edge_fade
    #   - 不做过渡求解 / transfer 稳定化 / spillover 裁剪 / 边框恢复
    # ============================================================

    def build_dense(self, realization_plan: RealizationPlan) -> np.ndarray:
        self._regions_by_id = region_by_id(realization_plan.regions)
        grid = np.full(
            (self.grid_size, self.grid_size),
            self._f_knit,
            dtype=np.uint8
        )

        sorted_regions = self._sort_regions(realization_plan.regions)

        # Step 1: 底布 + 边界（与 event 模式共用）
        for region in sorted_regions:
            self._fill_base(grid, region)
            self._draw_border(grid, region)

        # Step 2: 按区域优先级逐格密集写入纹理动作
        written_counts = {}
        for region in sorted_regions:
            n = self._dense_fill_pattern(grid, region)
            if n:
                written_counts[region.region_id] = n

        logger.info(f"  action builder[dense]: pattern cells written: {written_counts}")
        self._regions_by_id = {}
        self._last_rejection_info = {
            "rejected_by_region": {},
            "rejection_reasons": {},
            "events_placed": dict(written_counts),
        }
        return grid

    def _dense_fill_pattern(self, grid: np.ndarray, region: RealizationRegion) -> int:
        """按 event_pattern 的周期公式在区域 mask 内逐格写入动作，返回写入格数。"""
        pattern = str(region.event_pattern or "none").lower()
        if pattern in ("none", ""):
            return 0

        params = region.event_params or {}
        placement = region.placement or {}
        row_min, row_max, col_min, col_max = self._dense_scan_bounds(region)

        center = placement.get("center", [20, 20])
        try:
            center_row, center_col = int(center[0]), int(center[1])
        except Exception:
            center_row, center_col = 20, 20

        written = 0

        def _put(r: int, c: int, abbr: str):
            nonlocal written
            if not self._dense_in_region(r, c, region):
                return
            idx = actions.idx_safe(abbr, default=self._f_knit)
            grid[r, c] = idx if idx is not None else self._f_knit
            written += 1

        if pattern == "diagonal_wave":
            period_y = max(1, int(params.get("period_y", 4)))
            period_x = max(2, int(params.get("period_x", 5)))
            phase_y = int(params.get("phase_y", 1))
            split_off = int(params.get("split_col_offset", 2)) % period_x
            tuck_off = int(params.get("tuck_col_offset", 3)) % period_x
            if split_off == tuck_off:
                tuck_off = (split_off + 1) % period_x
            for r in range(row_min, row_max):
                if (r - center_row + phase_y) % period_y != 0:
                    continue
                for c in range(col_min, col_max):
                    off = (c - center_col) % period_x
                    if off == split_off:
                        _put(r, c, "f_split")
                    elif off == tuck_off:
                        _put(r, c, "f_tuck")

        elif pattern in ("honeycomb_tuck", "staggered_tuck"):
            period_x = max(2, int(params.get("period_x", 4)))
            period_y = max(2, int(params.get("period_y", 4)))
            stagger = bool(params.get("stagger", True))
            for r in range(row_min, row_max):
                if (r - row_min) % period_y != 1:
                    continue
                row_phase = (r - row_min) // period_y
                s = (period_x // 2) * (row_phase % 2) if stagger else 0
                for c in range(col_min, col_max):
                    if (c - col_min + s) % period_x == 0:
                        _put(r, c, "f_tuck")

        elif pattern == "lattice_miss":
            period_x = max(2, int(params.get("period_x", 4)))
            period_y = max(2, int(params.get("period_y", 4)))
            stagger = bool(params.get("stagger", True))
            for r in range(row_min, row_max):
                if (r - row_min) % period_y != 1:
                    continue
                row_phase = (r - row_min) // period_y
                s = (period_x // 2) * (row_phase % 2) if stagger else 0
                abbr = "xfer_f_b" if (r // period_y) % 2 == 0 else "xfer_b_f"
                for c in range(col_min, col_max):
                    if (c - col_min + s) % period_x == 1:
                        _put(r, c, abbr)

        elif pattern == "seed_tuck":
            for r in range(row_min, row_max):
                for c in range(col_min, col_max):
                    if (r + c) % 2 == 0:
                        _put(r, c, "b_knit")

        elif pattern == "column_xfer":
            cable_period = max(1, int(params.get("cable_period", 6)))
            side_offset = max(1, int(params.get("side_offset", 2)))
            for r in range(row_min, row_max):
                if (r - center_row) % cable_period != 0:
                    continue
                _put(r, center_col - side_offset, "xfer_l1")
                _put(r, center_col + side_offset, "xfer_r1")

        else:
            logger.info(f"  [dense] unsupported event_pattern={pattern}, keep base field only")

        return written

    def _dense_scan_bounds(self, region: RealizationRegion) -> Tuple[int, int, int, int]:
        """扫描边界（不做父级 bbox 交集，与 event 模式的差异点之一）。"""
        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()

        if role in {"ground", "allover"} or placement.get("type") in {"full", "repeat"}:
            return 0, self.grid_size, 0, self.grid_size

        if role == "side_band":
            side = resolve_side_band_side(placement, region.region_id, self.grid_size)
            try:
                width = int(placement.get("width", placement.get("size", 6)))
            except Exception:
                width = 6
            width = max(1, min(self.grid_size // 2, width))
            if side == "left":
                return 0, self.grid_size, 0, width
            return 0, self.grid_size, self.grid_size - width, self.grid_size

        center = placement.get("center", [20, 20])
        try:
            cr, cc = int(center[0]), int(center[1])
        except Exception:
            cr, cc = 20, 20
        try:
            size = int(placement.get("size", self.grid_size // 3))
        except Exception:
            size = self.grid_size // 3
        return (
            max(0, cr - size), min(self.grid_size, cr + size + 1),
            max(0, cc - size), min(self.grid_size, cc + size + 1),
        )

    def _dense_in_region(self, r: int, c: int, region: RealizationRegion) -> bool:
        """区域自身几何判定：仅用区域 mask（含 inner_exclude / 前景排除），
        不做父级作用域交集，不做边框环排除，不做 edge_fade。"""
        if not (0 <= r < self.grid_size and 0 <= c < self.grid_size):
            return False

        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()

        if role == "ground":
            return not is_excluded_by_foreground(r, c, placement, self.grid_size)

        if is_excluded_by_foreground(r, c, placement, self.grid_size):
            return False

        if role == "side_band":
            side = resolve_side_band_side(placement, region.region_id, self.grid_size)
            try:
                width = int(placement.get("width", placement.get("size", 6)))
            except Exception:
                width = 6
            width = max(1, min(self.grid_size // 2, width))
            return c < width if side == "left" else c >= self.grid_size - width

        if (placement.get("type") == "full" or role == "allover") and not has_mask_shape(placement):
            return True

        if has_mask_shape(placement):
            try:
                if not point_in_mask(r, c, placement, self.grid_size):
                    return False
                inner_excl = placement.get("inner_exclude")
                if isinstance(inner_excl, dict) and inner_excl:
                    try:
                        if point_in_mask(r, c, inner_excl, self.grid_size):
                            return False
                    except Exception:
                        pass
                return True
            except Exception:
                pass

        center = placement.get("center", [20, 20])
        try:
            cr, cc = int(center[0]), int(center[1])
        except Exception:
            cr, cc = 20, 20
        try:
            size = int(placement.get("size", self.grid_size // 3))
        except Exception:
            size = self.grid_size // 3
        return abs(r - cr) <= size and abs(c - cc) <= size

    # ============================================================
    # 区域优先级
    # ============================================================

    def _sort_regions(self, regions: List[RealizationRegion]) -> List[RealizationRegion]:
        priority = {
            "ground": 0,
            "allover": 1,
            "center": 2,
            "side_band": 3,
            "border": 4,
        }
        return sorted(regions, key=lambda r: priority.get(r.layout_role, 2))

    # ============================================================
    # 底布填充
    # ============================================================

    def _fill_base(self, grid: np.ndarray, region: RealizationRegion):
        if region.layout_role == "ground":
            self._fill_rect(
                grid, 0, 0, self.grid_size - 1, self.grid_size - 1,
                region.base_field
            )
            return

        if region.layout_role == "side_band":
            self._fill_side_band(grid, region)
            return

        if region.layout_role == "border":
            return

        r0, c0, r1, c1 = self._get_bbox(region)
        shape = self._get_shape(region)

        for r in range(max(0, r0), min(self.grid_size, r1 + 1)):
            for c in range(max(0, c0), min(self.grid_size, c1 + 1)):
                if self._is_excluded_by_foreground(r, c, region.placement or {}):
                    continue
                # inner_exclude：跳过内圈排除区域（ring / difference 类型）
                inner_excl = (region.placement or {}).get("inner_exclude")
                if isinstance(inner_excl, dict) and inner_excl:
                    try:
                        if point_in_mask(r, c, inner_excl, self.grid_size):
                            continue
                    except Exception:
                        pass
                if self._inside_shape(shape, r, c, region):
                    if not self._inside_layer_stack(r, c, region):
                        continue
                    a = self._field_action(region.base_field, r, c)
                    grid[r, c] = a

    def _fill_rect(self, grid, r0, c0, r1, c1, field: str):
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                grid[r, c] = self._field_action(field, r, c)

    def _fill_side_band(self, grid: np.ndarray, region: RealizationRegion):
        placement = region.placement or {}
        side = self._resolve_side_band_side(region)
        try:
            width = int(placement.get("width", 5))
        except Exception:
            width = 5
        width = max(1, min(self.grid_size // 2, width))

        if side == "left":
            col_range = range(0, width)
        else:
            col_range = range(self.grid_size - width, self.grid_size)

        for r in range(self.grid_size):
            for c in col_range:
                grid[r, c] = self._field_action(region.base_field, r, c)

    # ============================================================
    # 边界绘制
    # ============================================================

    def _draw_border(self, grid: np.ndarray, region: RealizationRegion):
        if region.border_style == "none":
            return

        thickness = region.border_thickness
        shape = self._get_shape(region)
        center_row, center_col, size = self._get_center_size(region)
        r0, c0, r1, c1 = self._get_bbox(region)

        for r in range(max(0, r0), min(self.grid_size, r1 + 1)):
            for c in range(max(0, c0), min(self.grid_size, c1 + 1)):
                if not self._inside_shape(shape, r, c, region):
                    continue
                if not self._inside_layer_stack(r, c, region):
                    continue
                if self._is_border(shape, r, c, region, thickness):
                    if region.border_style == "back_loop_outline":
                        grid[r, c] = self._b_knit
                    elif region.border_style == "rib_border":
                        grid[r, c] = self._b_knit if c % 2 == 0 else self._f_knit

        if has_mask_shape(region.placement or {}):
            self._repair_discrete_border(grid, region)

    # ============================================================
    # 形状判断
    # ============================================================

    def _get_shape(self, region: RealizationRegion) -> str:
        from generation.visual_types import VALID_VISUAL_SHAPES
        placement = region.placement or {}
        shape = get_mask_shape(placement) or "diamond"
        if shape not in VALID_VISUAL_SHAPES:
            if region.layout_role == "center":
                shape = "diamond"
            else:
                shape = "panel"
        return shape

    def _inside_shape(self, shape: str, r: int, c: int, region: RealizationRegion) -> bool:
        center_row, center_col, size = self._get_center_size(region)
        dr = abs(r - center_row)
        dc = abs(c - center_col)
        # 如果 region 指定了通用掩码（mask_shape/shape），优先使用 point_in_mask
        placement = region.placement or {}
        if has_mask_shape(placement):
            try:
                return point_in_mask(r, c, placement, self.grid_size)
            except Exception:
                # 回退到简单几何判断
                pass

        if shape == "diamond":
            return (dr + dc) <= size
        if shape == "circle":
            return (dr * dr + dc * dc) <= size * size
        if shape in ("square", "panel", "mesh", "rectangle", "frame", "rect"):
            return dr <= size and dc <= size
        if shape == "column":
            return dc <= size
        if shape == "stripe":
            return dr <= size
        return dr <= size and dc <= size

    def _is_border(self, shape: str, r: int, c: int, region: RealizationRegion, thickness: int) -> bool:
        if not self._inside_shape(shape, r, c, region):
            return False
        center_row, center_col, size = self._get_center_size(region)
        dr = abs(r - center_row)
        dc = abs(c - center_col)
        # 如果 region 指定了通用掩码（mask_shape/shape），使用掩码内外差判断边界
        placement = region.placement or {}
        if has_mask_shape(placement):
            try:
                mask_shape = get_mask_shape(placement)
                if mask_shape in {"diamond", "rhombus"}:
                    try:
                        p_size = int(placement.get("size", size))
                    except Exception:
                        p_size = size
                    manhattan = dr + dc
                    return p_size - thickness < manhattan <= p_size

                outer_inside = point_in_mask(r, c, placement, self.grid_size)
                # 构造内层 placement（size 减去 thickness）
                inner_placement = dict(placement)
                try:
                    inner_size = max(0, int(placement.get("size", size)) - thickness)
                except Exception:
                    inner_size = max(0, size - thickness)
                inner_placement["size"] = inner_size
                inner_inside = False
                if inner_size > 0:
                    inner_inside = point_in_mask(r, c, inner_placement, self.grid_size)
                return outer_inside and (not inner_inside)
            except Exception:
                # 回退到简单几何判断
                pass

        if shape == "diamond":
            return (dr + dc) >= size - thickness + 1
        if shape == "circle":
            dist_sq = dr * dr + dc * dc
            inner_sq = max(0, size - thickness) ** 2
            outer_sq = size * size
            return inner_sq <= dist_sq <= outer_sq
        if shape in ("square", "panel", "mesh", "rectangle", "frame", "rect"):
            return (
                dr >= size - thickness or
                dc >= size - thickness
            )
        return (
            dr >= size - thickness or
            dc >= size - thickness
        )

    def _repair_discrete_border(self, grid: np.ndarray, region: RealizationRegion):
        """Fill one-cell gaps on rasterized geometric outlines."""
        placement = region.placement or {}
        mask_shape = get_mask_shape(placement)
        if mask_shape in {"diamond", "rhombus", "hexagon", "hex"}:
            return
        r0, c0, r1, c1 = self._get_bbox(region)
        border_action = self._b_knit
        coords = []

        for r in range(max(0, r0), min(self.grid_size, r1 + 1)):
            for c in range(max(0, c0), min(self.grid_size, c1 + 1)):
                if not self._inside_layer_stack(r, c, region):
                    continue
                try:
                    if not point_in_mask(r, c, placement, self.grid_size):
                        continue
                    touches_outside = False
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = r + dr, c + dc
                            if not (0 <= nr < self.grid_size and 0 <= nc < self.grid_size):
                                touches_outside = True
                            elif not point_in_mask(nr, nc, placement, self.grid_size):
                                touches_outside = True
                    if touches_outside:
                        coords.append((r, c))
                except Exception:
                    continue

        for r, c in coords:
            grid[r, c] = border_action

        # Bridge single-cell holes between same-row or same-column border pixels.
        # For curved shapes (circle/oval/heart/star), skip diagonal bridging:
        # the midpoint between two diagonal border pixels often falls inside the
        # shape interior, causing the border to appear artificially thickened
        # in high-curvature areas (e.g. bottom-right of a circle).
        border_set = set(coords)
        diagonal_offsets = () if mask_shape in {
            "circle", "oval", "round", "circular", "ellipse",
            "heart", "star",
        } else ((1, 1), (1, -1))
        for r, c in list(border_set):
            for dr, dc in ((0, 2), (2, 0)) + diagonal_offsets:
                r2, c2 = r + dr, c + dc
                mid = (r + dr // 2, c + dc // 2)
                if (r2, c2) in border_set:
                    mr, mc = mid
                    if 0 <= mr < self.grid_size and 0 <= mc < self.grid_size:
                        try:
                            if point_in_mask(mr, mc, placement, self.grid_size):
                                grid[mr, mc] = border_action
                        except Exception:
                            pass

    # ============================================================
    # 工具
    # ============================================================

    def _field_action(self, field: str, r: int, c: int) -> int:
        if field == "plain_front":
            return self._f_knit
        if field == "plain_back":
            return self._b_knit
        if field == "rib":
            return self._f_knit if c % 2 == 0 else self._b_knit
        if field == "links":
            return self._f_knit if r % 2 == 0 else self._b_knit
        return self._f_knit

    def _get_center_size(self, region: RealizationRegion) -> Tuple[int, int, int]:
        placement = region.placement or {}
        
        # 如果是 side_band，返回合理的默认值
        if region.layout_role == "side_band":
            side = self._resolve_side_band_side(region)
            width = int(placement.get("width", 5))
            width = max(1, min(self.grid_size // 2, width))
            if side == "left":
                return 20, width // 2, width
            else:
                return 20, self.grid_size - width // 2, width
        
        center = placement.get("center", [20, 20])
        try:
            if isinstance(center, (list, tuple)) and len(center) >= 2:
                cr, cc = int(center[0]), int(center[1])
            else:
                cr, cc = 20, 20
        except Exception:
            cr, cc = 20, 20
        try:
            size = int(placement.get("size", self.grid_size // 3))
        except Exception:
            size = self.grid_size // 3
        if region.layout_role == "border":
            shape = str(get_mask_shape(placement) or placement.get("shape", "") or "").lower()
            if shape in {"rectangle", "rect", "frame", "border", "panel", "box", "square"}:
                margin = max(2, int(getattr(region, "border_thickness", 1) or 1))
                cr = min(max(cr, margin), self.grid_size - 1 - margin)
                cc = min(max(cc, margin), self.grid_size - 1 - margin)
                size = min(size, cr - margin, cc - margin, self.grid_size - 1 - margin - cr, self.grid_size - 1 - margin - cc)
                size = max(1, size)
        return cr, cc, size

    def _get_bbox(self, region: RealizationRegion) -> Tuple[int, int, int, int]:
        cr, cc, size = self._get_center_size(region)
        r0, c0, r1, c1 = (
            max(0, cr - size),
            max(0, cc - size),
            min(self.grid_size - 1, cr + size),
            min(self.grid_size - 1, cc + size),
        )
        parent_bbox = parent_scan_bbox(region, self._regions_by_id, self.grid_size)
        if parent_bbox is not None:
            pr0, pc0, pr1, pc1 = parent_bbox
            r0, c0, r1, c1 = max(r0, pr0), max(c0, pc0), min(r1, pr1), min(c1, pc1)
        return r0, c0, r1, c1

    def _stabilize_transfers(self, grid: np.ndarray):
        rows, cols = grid.shape
        pruned = 0
        balanced = 0
        _XFER = actions.transfer_ids()
        _LEFT = actions.left_transfer_ids()
        _RIGHT = actions.right_transfer_ids()

        for i in range(rows):
            target_map = {}
            for j in range(cols):
                a = int(grid[i, j])
                if a not in _XFER:
                    continue
                off = actions.offset(a)
                target = j + off
                if not (0 <= target < cols):
                    grid[i, j] = actions.idx_safe("f_split", default=self._f_knit)
                    pruned += 1
                    continue
                target_map.setdefault(target, []).append(j)

            center = (cols - 1) / 2.0
            for target, srcs in target_map.items():
                if len(srcs) <= 1:
                    continue
                keep = min(srcs, key=lambda x: abs(x - center))
                for s in srcs:
                    if s != keep:
                        grid[i, s] = actions.idx_safe("f_split", default=self._f_knit)
                        pruned += 1

            left_cols = [j for j in range(cols) if int(grid[i, j]) in _LEFT]
            right_cols = [j for j in range(cols) if int(grid[i, j]) in _RIGHT]
            while abs(len(left_cols) - len(right_cols)) > 1:
                if len(left_cols) > len(right_cols):
                    rm = max(left_cols, key=lambda x: abs(x - center))
                    grid[i, rm] = actions.idx_safe("f_split", default=self._f_knit)
                    left_cols.remove(rm)
                else:
                    rm = max(right_cols, key=lambda x: abs(x - center))
                    grid[i, rm] = actions.idx_safe("f_split", default=self._f_knit)
                    right_cols.remove(rm)
                balanced += 1

        return pruned, balanced

    def _event_in_region(self, r: int, c: int, region: RealizationRegion) -> bool:
        if not self._inside_layer_stack(r, c, region):
            return False

        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()

        if role == "ground":
            return True

        if self._is_excluded_by_foreground(r, c, placement):
            return False

        # inner_exclude：ring / difference 类型的事件不应落入内圈区域
        inner_excl = placement.get("inner_exclude")
        if isinstance(inner_excl, dict) and inner_excl:
            try:
                if point_in_mask(r, c, inner_excl, self.grid_size):
                    return False
            except Exception:
                pass

        if role == "side_band":
            side = self._resolve_side_band_side(region)
            try:
                width = int(placement.get("width", placement.get("size", 6)))
            except Exception:
                width = 6
            width = max(1, min(self.grid_size // 2, width))
            if side == "left":
                return c < width
            return c >= self.grid_size - width

        if (placement.get("type") == "full" or role == "allover") and not has_mask_shape(placement):
            return True

        cr, cc, size = self._get_center_size(region)
        # 如果 region 指定了 mask（mask_shape/shape 或者更多参数），使用通用掩码检测
        if has_mask_shape(placement):
            try:
                return point_in_mask(r, c, placement, self.grid_size)
            except Exception:
                return (abs(r - cr) <= size) and (abs(c - cc) <= size)

        return (abs(r - cr) <= size) and (abs(c - cc) <= size)

    def _is_excluded_by_foreground(self, r: int, c: int, placement: dict) -> bool:
        return is_excluded_by_foreground(r, c, placement, self.grid_size)

    def _inside_layer_stack(self, r: int, c: int, region: RealizationRegion) -> bool:
        return layer_mask_contains(r, c, region, self._regions_by_id, self.grid_size)

    def _debug_rejection_reason(self, r: int, c: int, region: RealizationRegion) -> str:
        """Return a human-readable reason why (r,c) was rejected for region."""
        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()
        # 1) layer stack
        if not self._inside_layer_stack(r, c, region):
            # drill down: which parent fails?
            current = region
            chain = []
            seen = set()
            while current is not None:
                rid = str(getattr(current, "region_id", ""))
                if rid in seen:
                    break
                seen.add(rid)
                p = getattr(current, "placement", {}) or {}
                cur_role = str(getattr(current, "layout_role", "center") or "center").lower()
                ok = True
                if (cur_role not in {"ground", "side_band"}
                        and p.get("type") != "full"
                        and has_mask_shape(p)):
                    try:
                        if not point_in_mask(r, c, p, self.grid_size):
                            ok = False
                    except Exception:
                        ok = False
                chain.append(f"{rid}(shape={p.get('shape','?')},size={p.get('size','?')},ok={ok})")
                parent_id = p.get("parent_id")
                current = self._regions_by_id.get(str(parent_id)) if parent_id else None
            return f"layer_stack_fail: chain=[{' -> '.join(chain)}]"
        # 2) exclude masks
        if self._is_excluded_by_foreground(r, c, placement):
            return "excluded_by_foreground"
        # 3) inner_exclude
        inner_excl = placement.get("inner_exclude")
        if isinstance(inner_excl, dict) and inner_excl:
            try:
                if point_in_mask(r, c, inner_excl, self.grid_size):
                    return f"inner_exclude(ie_size={inner_excl.get('size','?')})"
            except Exception:
                pass
        # 4) mask shape
        if has_mask_shape(placement):
            try:
                if not point_in_mask(r, c, placement, self.grid_size):
                    cr, cc, size = self._get_center_size(region)
                    return f"mask_shape_fail(shape={placement.get('shape','?')},size={size},center=({cr},{cc}),pt=({r},{c}))"
            except Exception as e:
                return f"mask_shape_exception: {e}"
        return "unknown"

    def _clip_child_region_spillovers(self, grid: np.ndarray, realization_plan: RealizationPlan) -> int:
        regions = getattr(realization_plan, "regions", []) or []
        clipped = 0
        special = (
            actions.transfer_ids()
            | actions.split_ids()
            | actions.tuck_ids()
            | actions.miss_ids()
            | actions.refinement_action_ids()
        )

        child_regions = []
        border_regions = []
        for region in regions:
            placement = getattr(region, "placement", {}) or {}
            if placement.get("clip_to_parent") or placement.get("parent_id"):
                child_regions.append(region)
            if region.border_style != "none":
                border_regions.append(region)

        if not child_regions:
            return 0

        for region in child_regions:
            placement = region.placement or {}
            if not has_mask_shape(placement):
                continue
            r0, c0, r1, c1 = self._get_bbox(region)

            # Include a one-cell halo because transition actions are inserted
            # adjacent to event points and can be just outside the child mask.
            for r in range(max(0, r0 - 1), min(self.grid_size, r1 + 2)):
                for c in range(max(0, c0 - 1), min(self.grid_size, c1 + 2)):
                    if int(grid[r, c]) not in special:
                        continue
                    if self._event_in_region(r, c, region):
                        continue
                    # 兄弟区域保护：如果该像素属于另一个 child region，
                    # 不裁剪（避免大 bbox 的 ring 区域误删兄弟圆形内的事件）
                    _belongs_to_sibling = False
                    for _sib in child_regions:
                        if _sib.region_id == region.region_id:
                            continue
                        if self._event_in_region(r, c, _sib):
                            _belongs_to_sibling = True
                            break
                    if _belongs_to_sibling:
                        continue
                    # 保护边框像素：如果该像素属于任何 border region 的边框环，
                    # 恢复为 b_knit 而不是 f_knit
                    restored = False
                    for br in border_regions:
                        if self._is_on_border_outline(r, c, br):
                            grid[r, c] = self._b_knit
                            restored = True
                            break
                    if not restored:
                        grid[r, c] = self._f_knit
                    clipped += 1

        return clipped

    def _is_on_border_outline(self, r: int, c: int, border_region: RealizationRegion) -> bool:
        """检查像素 (r,c) 是否位于指定 border region 的边框轮廓上。"""
        if border_region.border_style == "none":
            return False
        shape = self._get_shape(border_region)
        if not self._inside_shape(shape, r, c, border_region):
            return False
        if not self._inside_layer_stack(r, c, border_region):
            return False
        thickness = border_region.border_thickness
        return self._is_border(shape, r, c, border_region, thickness)

    def _restore_border_pixels(self, grid: np.ndarray, realization_plan: RealizationPlan):
        """在所有事件写入和裁剪后，重新绘制所有带边框的区域的轮廓。
        确保过渡求解、spillover 裁剪等不会破坏边框像素。
        
        覆盖范围：所有 border_style != "none" 的区域（不限于 layout_role=="border"），
        因为 center 角色的几何形状（三角形、圆形等）同样需要边框恢复。
        
        关键修复：不覆盖任何 child texture region 内的像素，避免
        边框恢复时意外吞掉圆形/多边形内部的纹理事件。
        """
        border_regions = [
            r for r in (realization_plan.regions or [])
            if r.border_style != "none"
        ]
        if not border_regions:
            return

        restored = 0
        for region in border_regions:
            shape = self._get_shape(region)
            thickness = region.border_thickness
            r0, c0, r1, c1 = self._get_bbox(region)

            # 收集 child texture regions（排除覆盖整个边框区域的 child）
            # 如果 child 的 mask 完全包含 border 区域的 bbox，说明 child 覆盖了
            # 整个边框，保护它等于阻止所有边框恢复，这不合理
            child_texture_placements = []
            for r_other in (realization_plan.regions or []):
                if r_other.region_id == region.region_id:
                    continue  # 跳过自身
                placement = getattr(r_other, "placement", {}) or {}
                if (placement.get("clip_to_parent") or placement.get("parent_id")) and r_other.layout_role != "border":
                    if has_mask_shape(placement):
                        # 检查 child 是否完全包含 border 区域的 bbox
                        try:
                            _c_center = placement.get("center", [20, 20])
                            _c_size = int(placement.get("size", 0))
                            _cr, _cc = int(_c_center[0]), int(_c_center[1])
                            _child_fully_contains = (
                                _cr - _c_size <= r0 and _cc - _c_size <= c0 and
                                _cr + _c_size >= r1 and _cc + _c_size >= c1
                            )
                        except Exception:
                            _child_fully_contains = False
                        if _child_fully_contains:
                            continue  # child 覆盖整个边框，不保护
                        child_texture_placements.append(placement)

            for r in range(max(0, r0), min(self.grid_size, r1 + 1)):
                for c in range(max(0, c0), min(self.grid_size, c1 + 1)):
                    if not self._inside_shape(shape, r, c, region):
                        continue
                    if not self._inside_layer_stack(r, c, region):
                        continue
                    # 保护：如果该像素位于任何 child texture region 内，跳过
                    inside_child = False
                    for child_placement in child_texture_placements:
                        try:
                            if point_in_mask(r, c, child_placement, self.grid_size):
                                inside_child = True
                                break
                        except Exception:
                            pass
                    if inside_child:
                        continue
                    if self._is_border(shape, r, c, region, thickness):
                        if grid[r, c] != self._b_knit:
                            grid[r, c] = self._b_knit
                            restored += 1

        if restored:
            logger.info(f"  border restoration: {restored} pixels restored")


    def _resolve_side_band_side(self, region: RealizationRegion) -> str:
        return resolve_side_band_side(
            region.placement or {}, region.region_id, self.grid_size,
        )
