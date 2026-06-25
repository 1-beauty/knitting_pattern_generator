"""
事件规划器 v9.0

职责：
- 输入：RealizationPlan + 40×40 空网格尺寸
- 输出：稀疏 EventPoint 列表

关键原则：
1. 只生成真正必要的工艺事件点（极度稀疏）
2. 不在不需要的地方凭空放色块
3. 事件点的分布严格遵循"仿真图效果 -> 色码图排列"规则
4. 中心、角点等"视觉感知位置"不一定是事件位置
"""

import numpy as np
from typing import List, Tuple

from generation.visual_types import RealizationPlan, RealizationRegion, EventPoint
from utils.logger import logger
from generation.mask_utils import point_in_mask, get_mask_shape, has_mask_shape
from generation.layer_utils import layer_mask_contains, parent_scan_bbox, region_by_id


class EventPlanner:
    """
    根据 RealizationPlan 生成稀疏 EventPoint 列表。
    """

    def __init__(self, grid_size: int = 40):
        self.grid_size = grid_size
        self._regions_by_id = {}

    def plan(self, realization_plan: RealizationPlan) -> List[EventPoint]:
        events: List[EventPoint] = []
        self._regions_by_id = region_by_id(realization_plan.regions)

        for region in realization_plan.regions:
            skip_reason = None

            if region.event_pattern == "none":
                skip_reason = (
                    f"event_pattern='none' "
                    f"(visual_effect may be '{region.event_pattern}', "
                    f"check if LLM understood the intended textile effect)"
                )
            elif region.layout_role == "ground":
                skip_reason = "layout_role='ground' (background region)"

            if skip_reason:
                logger.debug(f"    [{region.region_id}] ⊗ skipped: {skip_reason}")
                continue

            region_events = self._plan_region(region)
            region_events = self._clip_events_to_region(region_events, region)
            if region.event_pattern == "diagonal_wave":
                region_events = self._prune_unpaired_wave_events(region_events, region)
            if region_events:
                logger.info(
                    f"    [{region.region_id}] pattern={region.event_pattern} "
                    f"params={region.event_params} -> {len(region_events)} events"
                )
            else:
                logger.warning(
                    f"    [{region.region_id}] pattern={region.event_pattern} "
                    f"matched but generated 0 events (check params: {region.event_params})"
                )
            events.extend(region_events)

        if not events:
            logger.warning(
                "  ⚠️  EVENT PLANNING RETURNED 0 EVENTS! "
                "This usually means: 1) visual_effect output by LLM is wrong, "
                "2) all regions have event_pattern='none' or role='ground', "
                "or 3) event parameters are invalid. "
                "Check logs above for which regions were skipped."
            )

        logger.info(f"  event planning done: total {len(events)} events")
        self._regions_by_id = {}
        return events

    def _prune_unpaired_wave_events(
        self,
        events: List[EventPoint],
        region: RealizationRegion,
    ) -> List[EventPoint]:
        """Drop clipped wave cells whose split/tuck partner is missing.

        Diagonal wave texture is encoded as adjacent f_split/f_tuck pairs.  At
        mask edges one member can be clipped away; keeping the survivor creates
        isolated cells that read as broken holes instead of a wave.
        """
        if not events:
            return events

        params = region.event_params or {}
        try:
            split_offset = int(params.get("split_col_offset", 2))
            tuck_offset = int(params.get("tuck_col_offset", 3))
        except Exception:
            split_offset, tuck_offset = 2, 3
        pair_delta = tuck_offset - split_offset
        if pair_delta == 0:
            return events

        pairable = {
            "diagonal_wave split",
            "diagonal_wave tuck",
            "horizontal_wave split",
            "horizontal_wave tuck",
            "vertical_wave split",
            "vertical_wave tuck",
        }
        event_map = {
            (int(e.row), int(e.col), str(e.action_abbr)): e
            for e in events
            if e.reason in pairable and e.action_abbr in {"f_split", "f_tuck"}
        }

        kept: List[EventPoint] = []
        dropped = 0
        for e in events:
            if e.reason not in pairable or e.action_abbr not in {"f_split", "f_tuck"}:
                kept.append(e)
                continue

            if e.action_abbr == "f_split":
                partner_key = (int(e.row), int(e.col) + pair_delta, "f_tuck")
            else:
                partner_key = (int(e.row), int(e.col) - pair_delta, "f_split")

            if partner_key in event_map:
                kept.append(e)
            else:
                dropped += 1

        if dropped:
            logger.info(f"    [{region.region_id}] pruned {dropped} unpaired wave edge events")
        return kept

    # ============================================================
    # 区域事件规划
    # ============================================================

    def _plan_region(self, region: RealizationRegion) -> List[EventPoint]:
        pattern = region.event_pattern

        if pattern == "diamond_side_xfer":
            return self._pattern_diamond_side_xfer(region)

        if pattern == "contour_side_xfer":
            return self._pattern_contour_side_xfer(region)

        if pattern == "panel_center_xfer":
            return self._pattern_panel_center_xfer(region)

        if pattern == "column_xfer":
            return self._pattern_column_xfer(region)

        if pattern == "diagonal_wave":
            return self._pattern_diagonal_wave(region)

        if pattern == "lattice_miss":
            return self._pattern_lattice_miss(region)

        if pattern == "staggered_tuck":
            return self._pattern_staggered_tuck(region)

        if pattern == "honeycomb_tuck":
            return self._pattern_honeycomb_tuck(region)

        if pattern == "seed_tuck":
            return self._pattern_seed_tuck(region)

        return []

    # ============================================================
    # diamond_side_xfer：菱形麻花
    # 色码实现：xfer_l1 / xfer_r1 贴合菱形左右边骨架分布
    # 原则：不在中心，不在上下尖角，只在边界内侧的结构线上局部出现
    # ============================================================

    def _pattern_diamond_side_xfer(self, region: RealizationRegion) -> List[EventPoint]:
        """
        centered diamond cable 的事件规划。

        原则：
        1. transfer 事件贴着菱形左右边骨架，而不是落在几何中心
        2. 跳过上下尖角和中心行，避免孤立突兀色块
        3. 事件数量随 size 保守增长，保持线结构而不是填充结构
        4. 左右事件镜像成对出现，便于后续 transfer 稳定化
        """
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)

        if size < 4:
            return events

        pair_count = int(params.get("cable_pairs", 2))
        pair_count = max(1, min(3, pair_count))
        inset = int(params.get("edge_inset", 1))
        inset = max(1, min(3, inset))

        offsets = self._symmetric_nonzero_offsets(size=size, count=pair_count)
        for row_offset in offsets:
            r = center_row + row_offset
            if not (0 <= r < self.grid_size):
                continue

            half_width = size - abs(row_offset)
            if half_width <= inset + 1:
                continue

            left_col = center_col - half_width + inset
            right_col = center_col + half_width - inset

            if 0 <= left_col < self.grid_size and self._is_event_in_region(r, left_col, region):
                events.append(EventPoint(
                    row=r,
                    col=left_col,
                    action_abbr="xfer_l1",
                    region_id=region.region_id,
                    reason="diamond_side_xfer left edge"
                ))

            if 0 <= right_col < self.grid_size and self._is_event_in_region(r, right_col, region):
                events.append(EventPoint(
                    row=r,
                    col=right_col,
                    action_abbr="xfer_r1",
                    region_id=region.region_id,
                    reason="diamond_side_xfer right edge"
                ))

        return events

    def _symmetric_nonzero_offsets(self, size: int, count: int) -> List[int]:
        """Return row offsets away from the center line and away from vertices."""
        if count <= 1:
            base = max(2, int(round(size * 0.35)))
            return [-base, base]

        min_abs = max(2, int(round(size * 0.25)))
        max_abs = max(min_abs, int(round(size * 0.60)))
        values = np.linspace(min_abs, max_abs, count)
        offsets = []
        for v in values:
            off = int(round(v))
            if off <= 0:
                continue
            offsets.extend([-off, off])
        return sorted(set(offsets))

    def _pattern_contour_side_xfer(self, region: RealizationRegion) -> List[EventPoint]:
        """
        Cable-like events for rounded/contour shapes.

        Transfer points are attached to the left/right contour bands instead of
        the visual center. This keeps the color-code map sparse and structural:
        event points become part of the outline logic, not isolated center dots.
        """
        events = []
        params = region.event_params or {}
        placement = region.placement or {}
        center_row, center_col, size = self._get_placement(placement)
        if size < 4:
            return events

        pair_count = int(params.get("cable_pairs", 2))
        pair_count = max(1, min(3, pair_count))
        inset = int(params.get("edge_inset", 1))
        inset = max(1, min(3, inset))

        offsets = self._symmetric_nonzero_offsets(size=size, count=pair_count)
        for row_offset in offsets:
            r = center_row + row_offset
            if not (0 <= r < self.grid_size):
                continue

            # Circle/oval contour half-width at this row.
            y = abs(row_offset)
            half_width = int(round(max(0.0, (size * size - y * y) ** 0.5)))
            if half_width <= inset + 1:
                continue

            left_col = center_col - half_width + inset
            right_col = center_col + half_width - inset

            if 0 <= left_col < self.grid_size and self._is_event_in_region(r, left_col, region):
                events.append(EventPoint(
                    row=r,
                    col=left_col,
                    action_abbr="xfer_l1",
                    region_id=region.region_id,
                    reason="contour_side_xfer left edge"
                ))
            if 0 <= right_col < self.grid_size and self._is_event_in_region(r, right_col, region):
                events.append(EventPoint(
                    row=r,
                    col=right_col,
                    action_abbr="xfer_r1",
                    region_id=region.region_id,
                    reason="contour_side_xfer right edge"
                ))

        return events

    # ============================================================
    # panel_center_xfer：面板中心麻花
    # ============================================================

    def _pattern_panel_center_xfer(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)

        cable_period = int(params.get("cable_period", max(4, size // 3)))
        cable_pairs = int(params.get("cable_pairs", 2))
        side_offset = max(2, int(size * float(params.get("side_ratio", 0.25))))

        for k in range(cable_pairs):
            row_offset = (k - cable_pairs // 2) * cable_period
            r = center_row + row_offset

            if not (0 <= r < self.grid_size):
                continue

            cl = center_col - side_offset
            cr = center_col + side_offset

            if 0 <= cl < self.grid_size:
                events.append(EventPoint(
                    row=r, col=cl,
                    action_abbr="xfer_l1",
                    region_id=region.region_id,
                    reason="panel_center_xfer left"
                ))
            if 0 <= cr < self.grid_size:
                events.append(EventPoint(
                    row=r, col=cr,
                    action_abbr="xfer_r1",
                    region_id=region.region_id,
                    reason="panel_center_xfer right"
                ))

        return events

    # ============================================================
    # column_xfer：柱状麻花
    # ============================================================

    def _pattern_column_xfer(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)
        cable_period = int(params.get("cable_period", 6))
        side_offset = max(1, int(params.get("side_offset", 2)))

        for r in range(max(0, center_row - size), min(self.grid_size, center_row + size + 1)):
            if (r - center_row) % cable_period != 0:
                continue

            cl = center_col - side_offset
            cr = center_col + side_offset

            if 0 <= cl < self.grid_size:
                events.append(EventPoint(
                    row=r, col=cl,
                    action_abbr="xfer_l1",
                    region_id=region.region_id,
                    reason="column_xfer left"
                ))
            if 0 <= cr < self.grid_size:
                events.append(EventPoint(
                    row=r, col=cr,
                    action_abbr="xfer_r1",
                    region_id=region.region_id,
                    reason="column_xfer right"
                ))

        return events

    # ============================================================
    # diagonal_wave：斜向波浪
    # 仿真图里是波浪曲线，色码图里用 f_split + f_tuck 成对表示细密波浪。
    # ============================================================

    def _pattern_diagonal_wave(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params or {}
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)
        shape = get_mask_shape(placement)

        # 参数验证与默认值
        period_y = int(params.get("period_y", 4))
        period_x = int(params.get("period_x", 5))
        if period_y <= 0:
            logger.warning(f"  [{region.region_id}] Invalid period_y={period_y}, using default 4")
            period_y = 4
        if period_x <= 0:
            logger.warning(f"  [{region.region_id}] Invalid period_x={period_x}, using default 5")
            period_x = 5
        phase_y = int(params.get("phase_y", 1))
        split_col_offset = int(params.get("split_col_offset", 2))
        tuck_col_offset = int(params.get("tuck_col_offset", 3))
        if (
            split_col_offset < 0
            or tuck_col_offset < 0
            or split_col_offset >= period_x
            or tuck_col_offset >= period_x
            or split_col_offset == tuck_col_offset
        ):
            old_split, old_tuck = split_col_offset, tuck_col_offset
            split_col_offset = max(0, period_x - 2)
            tuck_col_offset = min(period_x - 1, split_col_offset + 1)
            if split_col_offset == tuck_col_offset and period_x > 1:
                split_col_offset = 0
                tuck_col_offset = 1
            logger.warning(
                f"  [{region.region_id}] invalid wave offsets "
                f"split={old_split}, tuck={old_tuck}, period_x={period_x}; "
                f"using split={split_col_offset}, tuck={tuck_col_offset}"
            )
        wave_direction = str(params.get("wave_direction", "diag_pos") or "diag_pos").lower()
        density_profile = str(params.get("density_profile", "") or "").lower()
        if not density_profile:
            if shape in {"circle", "circular", "round", "oval", "ellipse"}:
                density_profile = "center_dense"
            else:
                density_profile = "uniform"

        row_min, row_max, col_min, col_max = self._get_region_scan_bounds(region)
        centered_phase = self._choose_balanced_wave_phase(
            region=region,
            row_min=row_min,
            row_max=row_max,
            col_min=col_min,
            col_max=col_max,
            period_x=period_x,
            split_col_offset=split_col_offset,
            tuck_col_offset=tuck_col_offset,
            center_row=center_row,
            center_col=center_col,
        )

        pair_delta = tuck_col_offset - split_col_offset

        for r in range(row_min, row_max):
            if wave_direction in {"diag_pos", "diag_negative", "diag_neg", "diag"}:
                if (r - center_row + phase_y) % period_y != 0:
                    continue
            elif wave_direction in {"horizontal", "h", "left_right"}:
                if (r - center_row + phase_y) % period_y != 0:
                    continue
            elif wave_direction in {"vertical", "v", "up_down"}:
                pass
            else:
                if (r - center_row + phase_y) % period_y != 0:
                    continue

            for c in range(col_min, col_max):
                if not self._accept_wave_density(
                    r=r,
                    c=c,
                    center_row=center_row,
                    center_col=center_col,
                    size=size,
                    shape=shape,
                    density_profile=density_profile,
                ):
                    continue

                if wave_direction in {"vertical", "v", "up_down"}:
                    if (c - col_min + phase_y) % period_x != 0:
                        continue
                    row_in_period = (r - row_min) % period_y
                    if row_in_period != split_col_offset % period_y:
                        continue
                    tuck_col = c + pair_delta
                    if not self._wave_pair_fits(r, c, tuck_col, region):
                        continue
                    events.append(EventPoint(
                        row=r, col=c,
                        action_abbr="f_split",
                        region_id=region.region_id,
                        reason="vertical_wave split"
                    ))
                    events.append(EventPoint(
                        row=r, col=tuck_col,
                        action_abbr="f_tuck",
                        region_id=region.region_id,
                        reason="vertical_wave tuck"
                    ))
                    continue

                if wave_direction in {"diag_negative", "diag_neg"}:
                    col_in_period = (col_max - 1 - c) % period_x
                elif wave_direction in {"horizontal", "h", "left_right"}:
                    col_in_period = (c - center_col) % period_x
                else:
                    col_in_period = (c - center_col + centered_phase) % period_x

                if col_in_period != split_col_offset:
                    continue
                tuck_col = c + pair_delta
                if not self._wave_pair_fits(r, c, tuck_col, region):
                    continue
                events.append(EventPoint(
                    row=r, col=c,
                    action_abbr="f_split",
                    region_id=region.region_id,
                    reason="diagonal_wave split"
                ))
                events.append(EventPoint(
                    row=r, col=tuck_col,
                    action_abbr="f_tuck",
                    region_id=region.region_id,
                    reason="diagonal_wave tuck"
                ))

        if bool(params.get("edge_anchor", False)):
            events.extend(self._wave_edge_anchor_events(region, row_min, row_max, col_min, col_max))

        return events

    def _wave_pair_fits(
        self,
        row: int,
        split_col: int,
        tuck_col: int,
        region: RealizationRegion,
    ) -> bool:
        """Return True only when the planned wave pair fits on its grid line."""
        if not (0 <= split_col < self.grid_size and 0 <= tuck_col < self.grid_size):
            return False
        return self._is_event_in_region(row, split_col, region) and self._is_event_in_region(row, tuck_col, region)

    def _choose_balanced_wave_phase(
        self,
        region: RealizationRegion,
        row_min: int,
        row_max: int,
        col_min: int,
        col_max: int,
        period_x: int,
        split_col_offset: int,
        tuck_col_offset: int,
        center_row: int,
        center_col: int,
    ) -> int:
        """Pick the wave phase with the most balanced left/right visible pairs."""
        if str(region.layout_role or "").lower() not in {"allover", "ground"}:
            return 0

        period_x = max(1, int(period_x))
        pair_delta = int(tuck_col_offset) - int(split_col_offset)
        best_phase = 0
        best_score = None

        for phase in range(period_x):
            left_pairs = 0
            right_pairs = 0
            edge_penalty = 0
            total_pairs = 0
            for r in range(row_min, row_max):
                for c in range(col_min, col_max):
                    if (c - center_col + phase) % period_x != int(split_col_offset):
                        continue
                    tuck_col = c + pair_delta
                    if not (col_min <= tuck_col < col_max):
                        edge_penalty += 1
                        continue
                    if not self._is_event_in_region(r, c, region):
                        continue
                    if not self._is_event_in_region(r, tuck_col, region):
                        edge_penalty += 1
                        continue

                    total_pairs += 1
                    pair_center = (c + tuck_col) / 2.0
                    if pair_center < center_col:
                        left_pairs += 1
                    elif pair_center > center_col:
                        right_pairs += 1

            score = (abs(left_pairs - right_pairs), edge_penalty, -total_pairs)
            if best_score is None or score < best_score:
                best_score = score
                best_phase = phase

        return best_phase

    def _wave_edge_anchor_events(
        self,
        region: RealizationRegion,
        row_min: int,
        row_max: int,
        col_min: int,
        col_max: int,
    ) -> List[EventPoint]:
        """Do not synthesize extra seam events.

        The wave rows themselves are visually acceptable; extra border-adjacent
        split/tuck events have repeatedly simulated as holes at the seam.
        """
        return []

    def _accept_wave_density(
        self,
        r: int,
        c: int,
        center_row: int,
        center_col: int,
        size: int,
        shape: str,
        density_profile: str,
    ) -> bool:
        if density_profile in {"uniform", "none", "flat"}:
            return True

        # center_dense 原有行为（针对圆形）
        if density_profile == "center_dense":
            if size <= 0:
                return True
            dr = float(r - center_row)
            dc = float(c - center_col)
            rr = (dr * dr + dc * dc) / float(size * size)

            # 中心保留，中圈/外圈按周期稀疏化
            if rr <= 0.36:
                return True
            if rr <= 0.64:
                return ((r + c) % 2) == 0
            if rr <= 0.90:
                return ((r + 2 * c) % 3) == 0
            return False

        # radial_gradient: 更平滑的径向渐变，适用于任意形状
        if density_profile == "radial_gradient":
            if size <= 0:
                return True
            dr = float(r - center_row)
            dc = float(c - center_col)
            rr = (dr * dr + dc * dc) / float(size * size)
            # 计算一个基于 rr 的保留概率阈值（确定性近似）：
            # rr in [0,1] -> higher rr -> 更低保留率；用周期规则保证可重复
            if rr <= 0.25:
                return True
            if rr <= 0.50:
                return ((r + c) % 2) == 0
            if rr <= 0.75:
                return ((r + 2 * c) % 3) == 0
            return False

        return True

    # ============================================================
    # lattice_miss：网眼/镂空
    # 仿真图里是孔洞/网眼，色码图里用床间移针交替表达孔眼结构。
    # 不使用孤立 miss 作为主动作，因为下一行线圈会失去支撑并被物理修复抹掉。
    # ============================================================

    def _pattern_lattice_miss(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)

        period_x = int(params.get("period_x", 4))
        period_y = int(params.get("period_y", 4))
        stagger = bool(params.get("stagger", True))

        row_min, row_max, col_min, col_max = self._get_region_scan_bounds(region)

        for r in range(row_min, row_max):
            row_phase = (r - row_min) // period_y
            stagger_offset = (period_x // 2) * (row_phase % 2) if stagger else 0

            for c in range(col_min, col_max):
                if (r - row_min) % period_y == 1 and (c - col_min + stagger_offset) % period_x == 1:
                    action = "xfer_f_b" if (r // max(1, period_y)) % 2 == 0 else "xfer_b_f"
                    events.append(EventPoint(
                        row=r, col=c,
                        action_abbr=action,
                        region_id=region.region_id,
                        reason="lattice_eyelet_transfer"
                    ))

        return events

    # ============================================================
    # staggered_tuck：浮雕集圈
    # ============================================================

    def _pattern_staggered_tuck(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)

        period_x = int(params.get("period_x", 4))
        period_y = int(params.get("period_y", 4))
        stagger = bool(params.get("stagger", True))

        row_min, row_max, col_min, col_max = self._get_region_scan_bounds(region)

        for r in range(row_min, row_max):
            row_phase = (r - row_min) // period_y
            stagger_offset = (period_x // 2) * (row_phase % 2) if stagger else 0

            for c in range(col_min, col_max):
                if (r - row_min) % period_y == 1 and (c - col_min + stagger_offset) % period_x == 0:
                    events.append(EventPoint(
                        row=r, col=c,
                        action_abbr="f_tuck",
                        region_id=region.region_id,
                        reason="staggered_tuck"
                    ))

        return events

    # ============================================================
    # honeycomb_tuck：蜂巢集圈
    # ============================================================

    def _pattern_honeycomb_tuck(self, region: RealizationRegion) -> List[EventPoint]:
        # For closed geometric honeycomb motifs, keep the interior clean and
        # let the boundary/baseline communicate the shape. This avoids visual
        # confusion with wave cells or broken texture marks.
        placement = region.placement or {}
        shape = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
        if shape in {"hexagon", "hex"}:
            return []

        events = []
        params = region.event_params
        period_x = max(3, int(params.get("period_x", 4)))
        period_y = max(3, int(params.get("period_y", 4)))
        stagger = bool(params.get("stagger", True))

        row_min, row_max, col_min, col_max = self._get_region_scan_bounds(region)

        for r in range(row_min, row_max):
            if (r - row_min) % period_y != 1:
                continue
            row_phase = (r - row_min) // period_y
            stagger_offset = (period_x // 2) * (row_phase % 2) if stagger else 0

            for c in range(col_min, col_max):
                if (c - col_min + stagger_offset) % period_x != 0:
                    continue
                if self._is_event_in_region(r, c, region):
                    events.append(EventPoint(
                        row=r,
                        col=c,
                        action_abbr="f_tuck",
                        region_id=region.region_id,
                        reason="staggered_tuck",
                    ))

        return events

    # ============================================================
    # seed_tuck：种子针
    # ============================================================

    def _pattern_seed_tuck(self, region: RealizationRegion) -> List[EventPoint]:
        events = []
        params = region.event_params
        placement = region.placement

        center_row, center_col, size = self._get_placement(placement)

        row_min, row_max, col_min, col_max = self._get_region_scan_bounds(region)

        for r in range(row_min, row_max):
            for c in range(col_min, col_max):
                if (r + c) % 2 == 0:
                    events.append(EventPoint(
                        row=r, col=c,
                        action_abbr="b_knit",
                        region_id=region.region_id,
                        reason="seed_stitch"
                    ))

        return events

    # ============================================================
    # 工具
    # ============================================================

    def _get_placement(
        self,
        placement: dict,
    ) -> Tuple[int, int, int]:
        placement = placement or {}
        
        # 如果是满地布局
        if placement.get("type") == "full":
            return 20, 20, self.grid_size // 2
        
        center = placement.get("center", [20, 20])
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            cr, cc = int(center[0]), int(center[1])
        else:
            cr, cc = 20, 20
        size = int(placement.get("size", self.grid_size // 3))
        return cr, cc, size

    def _get_region_scan_bounds(self, region: RealizationRegion) -> Tuple[int, int, int, int]:
        """
        返回区域事件扫描边界（row_min,row_max,col_min,col_max）。
        row_max/col_max 为 Python range 的上界（开区间）。
        """
        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()

        # 满地/全图区域默认全图扫描；若携带 mask/repeat，仍然全图扫描后逐点裁剪。
        if role in {"ground", "allover"} or placement.get("type") in {"full", "repeat"}:
            return 0, self.grid_size, 0, self.grid_size

        # 侧栏：全高 + 指定列宽
        if role == "side_band":
            side = self._resolve_side_band_side(region)
            try:
                width = int(placement.get("width", placement.get("size", 6)))
            except Exception:
                width = 6
            width = max(1, min(self.grid_size // 2, width))
            if side == "left":
                return 0, self.grid_size, 0, width
            return 0, self.grid_size, self.grid_size - width, self.grid_size

        # 默认：中心/局部区域
        cr, cc, size = self._get_placement(placement)
        row_min = max(0, cr - size)
        row_max = min(self.grid_size, cr + size + 1)
        col_min = max(0, cc - size)
        col_max = min(self.grid_size, cc + size + 1)
        parent_bbox = parent_scan_bbox(region, self._regions_by_id, self.grid_size)
        if parent_bbox is not None:
            pr0, pc0, pr1, pc1 = parent_bbox
            row_min = max(row_min, pr0)
            row_max = min(row_max, pr1 + 1)
            col_min = max(col_min, pc0)
            col_max = min(col_max, pc1 + 1)
        return row_min, row_max, col_min, col_max

    def _clip_events_to_region(
        self,
        events: List[EventPoint],
        region: RealizationRegion,
    ) -> List[EventPoint]:
        """
        对事件做区域裁剪，防止越界或跨区域扩散。
        """
        if not events:
            return events

        clipped: List[EventPoint] = []
        dropped = 0
        for e in events:
            if self._is_event_in_region(e.row, e.col, region):
                clipped.append(e)
            else:
                dropped += 1

        if dropped > 0:
            logger.info(
                f"    [{region.region_id}] clipped {dropped} events outside region bounds"
            )
        return clipped

    def _is_event_in_region(self, r: int, c: int, region: RealizationRegion) -> bool:
        if not (0 <= r < self.grid_size and 0 <= c < self.grid_size):
            return False

        if not layer_mask_contains(r, c, region, self._regions_by_id, self.grid_size):
            return False

        placement = region.placement or {}
        role = str(region.layout_role or "center").lower()

        if role == "ground":
            return True

        if self._is_excluded_by_foreground(r, c, placement):
            return False

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

        cr, cc, size = self._get_placement(placement)
        # 如果 placement 中携带 mask_shape 或 shape，使用通用掩码检测
        if has_mask_shape(placement):
            try:
                if not point_in_mask(r, c, placement, self.grid_size):
                    return False

                border_guard = int(region.event_params.get("border_guard", 0) or 0)
                if border_guard > 0 and str(getattr(region, "border_style", "none") or "none").lower() != "none":
                    guarded = dict(placement)
                    try:
                        guarded["size"] = max(0, int(placement.get("size", size)) - border_guard)
                    except Exception:
                        guarded["size"] = max(0, size - border_guard)
                    if guarded.get("size", 0) > 0 and not point_in_mask(r, c, guarded, self.grid_size):
                        return False

                # 给几何区域留一点边缘缓冲，避免事件压到边框上导致“拼块感”
                edge_fade = int(region.event_params.get("edge_fade", 0) or 0)
                if edge_fade <= 0:
                    shape = get_mask_shape(placement)
                    if shape in {"circle", "circular", "round", "oval", "ellipse"}:
                        edge_fade = 1
                    elif shape in {"rectangle", "rect", "frame", "border", "panel", "square", "box"}:
                        edge_fade = 2

                if edge_fade > 0:
                    inner = dict(placement)
                    try:
                        inner["size"] = max(0, int(placement.get("size", size)) - edge_fade)
                    except Exception:
                        inner["size"] = max(0, size - edge_fade)
                    if inner.get("size", 0) > 0 and not point_in_mask(r, c, inner, self.grid_size):
                        return False
                return True
            except Exception:
                return (abs(r - cr) <= size) and (abs(c - cc) <= size)

        # 默认方形边界测试
        return (abs(r - cr) <= size) and (abs(c - cc) <= size)

    def _is_excluded_by_foreground(self, r: int, c: int, placement: dict) -> bool:
        masks = placement.get("exclude_masks") if isinstance(placement, dict) else None
        if not masks:
            return False
        for item in masks:
            if not isinstance(item, dict):
                continue
            mask = dict(item.get("placement") or {})
            if not mask:
                continue
            try:
                if has_mask_shape(mask) and point_in_mask(r, c, mask, self.grid_size):
                    return True
                if not has_mask_shape(mask):
                    cr, cc, size = self._get_placement(mask)
                    if abs(r - cr) <= size and abs(c - cc) <= size:
                        return True
            except Exception:
                continue
        return False

    def _resolve_side_band_side(self, region: RealizationRegion) -> str:
        placement = region.placement or {}
        side_raw = str(placement.get("side", "")).strip().lower()
        if side_raw in {"left", "right"}:
            return side_raw

        rid = str(region.region_id or "").lower()
        if any(k in rid for k in ["right", "r_", "_r", "右"]):
            return "right"
        if any(k in rid for k in ["left", "l_", "_l", "左"]):
            return "left"

        center = placement.get("center")
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            try:
                return "right" if int(center[1]) >= self.grid_size // 2 else "left"
            except Exception:
                pass

        return "left"

    def _point_in_regular_polygon(self, r: int, c: int, cr: int, cc: int, size: int, n_sides: int, rotation: float = 0.0) -> bool:
        """
        检查点 (r,c) 是否位于以 (cr,cc) 为中心、半径 size 的正 n 边形内部。
        使用射线法判断点是否在多边形内部。
        """
        import math

        if n_sides < 3 or size <= 0:
            return False

        verts = []
        for k in range(n_sides):
            theta = 2.0 * math.pi * k / n_sides + rotation
            x = cc + size * math.cos(theta)  # x 对应列
            y = cr + size * math.sin(theta)  # y 对应行
            verts.append((y, x))

        # 点-in-多边形（ray casting）
        inside = False
        j = len(verts) - 1
        py = float(r)
        px = float(c)
        for i in range(len(verts)):
            yi, xi = verts[i]
            yj, xj = verts[j]
            intersect = ((yi > py) != (yj > py)) and (
                px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
            )
            if intersect:
                inside = not inside
            j = i
        return inside
