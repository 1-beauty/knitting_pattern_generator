"""
端到端生成管线 v9.0

流程：
1. LLM 解析 -> VisualSpec
2. 视觉 -> 色码实现 -> RealizationPlan
3. 事件规划 -> EventPoint 列表
4. 动作构建 -> BaseActionGrid
5. Refinement
6. Aesthetic
7. Compiler guard + 规则检查
8. LLM 修复（可选）
9. 输出 BMP
"""

import time
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field as dc_field
from typing import Optional, Dict, Any, List

from config import GRID_SIZE
from core import actions

from llm.prompts import PromptBuilder
from llm.design_parser import DesignParser
from llm.repair_agent import RepairAgent

from generation.visual_types import VisualSpec, RealizationPlan, EventPoint
from generation.pattern_plan import PatternPlan, PatternPlanEngine
from generation.visual_to_realization import VisualToRealizationConverter
from generation.event_planner import EventPlanner
from generation.action_builder import ActionBuilder
from generation.refinement_compiler import RefinementCompiler
from generation.aesthetic_pass import AestheticPass
from generation.layer_utils import layer_mask_contains, region_by_id
from generation.mask_utils import point_in_mask, has_mask_shape

from rules import (
    check_physical,
    fix_physical,
    check_craft_actions,
    tension_score,
)

from utils.logger import logger
from utils.file_io import save_image


def action_grid_to_rgb(action_grid: np.ndarray) -> np.ndarray:
    rows, cols = action_grid.shape
    rgb = np.zeros((rows, cols, 3), dtype=np.uint8)
    for i in range(actions.NUM_ACTIONS):
        rgb[action_grid == i] = actions.color_rgb(i)
    rgb[~np.isin(action_grid, list(actions.ALL_ACTION_INDICES))] = (255, 255, 255)
    return rgb


def action_grid_to_machine_rgb(action_grid: np.ndarray) -> np.ndarray:
    rows, cols = action_grid.shape
    rgb = np.zeros((rows, cols, 3), dtype=np.uint8)
    for i in range(actions.NUM_ACTIONS):
        rgb[action_grid == i] = actions.machine_color_rgb(i)
    rgb[~np.isin(action_grid, list(actions.ALL_ACTION_INDICES))] = (255, 255, 255)
    return rgb


@dataclass
class PipelineConfig:
    num_few_shot_examples: int = 4
    enable_refinement: bool = True
    enable_aesthetic: bool = True
    auto_fix_physical: bool = True
    enable_llm_repair: bool = True
    max_repair_rounds: int = 1
    output_scale: int = 1
    save_intermediate: bool = False


@dataclass
class PipelineResult:
    action_grid_40x40: np.ndarray
    rgb_image: np.ndarray
    visual_spec: Optional[VisualSpec] = None
    pattern_plan: Optional[PatternPlan] = None
    realization_plan: Optional[RealizationPlan] = None
    events: Optional[List[EventPoint]] = None
    statistics: Dict[str, Any] = dc_field(default_factory=dict)
    execution_time: float = 0.0


class KnittingPipeline:
    def __init__(
        self,
        llm_client,
        rasterizer=None,
        config: Optional[PipelineConfig] = None,
    ):
        self.llm_client = llm_client
        self.config = config or PipelineConfig()

        self.prompt_builder = PromptBuilder(max_examples=self.config.num_few_shot_examples)
        self.design_parser = DesignParser()
        self.plan_engine = PatternPlanEngine()
        self.repair_agent = RepairAgent(self.llm_client, self.prompt_builder)

        self.v2r = VisualToRealizationConverter()
        self.event_planner = EventPlanner(grid_size=GRID_SIZE)
        self.action_builder = ActionBuilder(grid_size=GRID_SIZE)
        self.refinement_compiler = RefinementCompiler()
        self.aesthetic_pass = AestheticPass()

    def generate(self, user_input: str, current_plan: Optional[PatternPlan] = None) -> PipelineResult:
        start = time.time()

        result = PipelineResult(
            action_grid_40x40=np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
            rgb_image=np.zeros((GRID_SIZE, GRID_SIZE, 3), dtype=np.uint8),
            statistics={},
        )

        logger.info("=" * 60)
        logger.info(f"Generate: {user_input}")
        logger.info("=" * 60)

        # Step 1: LLM/heuristics -> editable PatternPlan -> VisualSpec
        pattern_plan, visual_spec = self._step1_design(user_input, current_plan=current_plan)
        result.pattern_plan = pattern_plan
        result.visual_spec = visual_spec
        result.statistics["pattern_plan"] = pattern_plan.to_dict()
        result.statistics["layout_type"] = visual_spec.layout_type
        result.statistics["num_regions"] = len(visual_spec.regions)

        # Step 2: VisualSpec -> RealizationPlan
        realization_plan = self._step2_realization(visual_spec)
        result.realization_plan = realization_plan

        # Step 3: RealizationPlan -> EventPoints
        events = self._step3_events(realization_plan)
        result.events = events
        result.statistics["total_events"] = len(events)

        # Step 4: Build ActionGrid
        action_grid = self._step4_build(realization_plan, events)

        # Step 5: Refinement
        action_grid = self._step5_refinement(action_grid, events)

        # Step 6: Aesthetic
        action_grid = self._step6_aesthetic(action_grid, realization_plan)

        # Step 6.25: enforce clipped layer composition after post-processing.
        action_grid, layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
        result.statistics["layer_clip"] = layer_clip_stats

        # Step 6.5: Compiler guard
        action_grid, guard_stats = self._step6_5_compiler_guard(action_grid)
        result.statistics["compiler_guard"] = guard_stats

        # Step 7: Rules
        action_grid, violation_report = self._step7_rules(action_grid)
        result.statistics["violations"] = violation_report

        # Step 8: LLM Repair
        if self.config.enable_llm_repair:
            action_grid, repair_stats = self._step8_repair(user_input, action_grid, violation_report)
            result.statistics["llm_repair"] = repair_stats
            action_grid, post_repair_guard_stats = self._step6_5_compiler_guard(action_grid)
            result.statistics["post_repair_compiler_guard"] = post_repair_guard_stats
            action_grid, post_repair_layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
            result.statistics["post_repair_layer_clip"] = post_repair_layer_clip_stats

        action_grid, final_layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
        result.statistics["final_layer_clip"] = final_layer_clip_stats
        result.statistics["layer_clip_audit"] = self._audit_layer_clip(action_grid, realization_plan)
        action_grid, canvas_margin_stats = self._step6_75_canvas_margin(action_grid)
        result.statistics["canvas_margin"] = canvas_margin_stats
        action_grid, wave_pair_stats = self._step6_9_wave_pair_guard(action_grid, realization_plan)
        result.statistics["wave_pair_guard"] = wave_pair_stats

        # 边框保护：最终防线，在所有 pass 完成后确保边框像素完整
        action_grid = self._protect_border_pixels(action_grid, realization_plan)

        result.action_grid_40x40 = action_grid
        result.rgb_image = action_grid_to_rgb(action_grid)
        result.statistics["distribution"] = self._distribution(action_grid)
        result.statistics["tension_score"] = tension_score(action_grid)
        result.execution_time = time.time() - start

        logger.info(f"Pipeline finished in {result.execution_time:.2f}s")
        return result

    # ============================================================
    # Steps
    # ============================================================

    def _step1_design(
        self,
        user_input: str,
        current_plan: Optional[PatternPlan] = None,
    ) -> tuple[PatternPlan, VisualSpec]:
        logger.info("[1/8] Pattern plan design/edit...")

        # 随机模式：直接调用随机生成器，不走 LLM。
        # LLM 对随机指令的输出偏向固定模板（菱形+矩形框），
        # 而 random_plan() 的候选池有 60+ 种组合，多样性更好。
        is_random_mode = (
            current_plan is None
            and any(k in user_input for k in ["随机", "随便", "生成一些", "灵感"])
            or "random" in user_input.lower()
        )
        if is_random_mode:
            logger.info("  Random mode detected, using random_plan() directly")
            pattern_plan = self.plan_engine.from_prompt(user_input, current_plan=current_plan)
        else:
            messages = self.prompt_builder.build_pattern_plan_messages(user_input, current_plan=current_plan)
            response = self.llm_client.chat(messages)

            if not response.success:
                logger.error(f"LLM failed: {response.error}")
                pattern_plan = self.plan_engine.from_prompt(user_input, current_plan=current_plan)
            else:
                pattern_plan = self.plan_engine.parse_or_fallback(
                    response.content,
                    user_input=user_input,
                    current_plan=current_plan,
                )

        spec = self.plan_engine.render_visual_spec(pattern_plan)

        logger.info(f"  plan motifs: {len(pattern_plan.motifs)}")
        for m in pattern_plan.motifs:
            logger.info(
                f"  motif [{m.motif_id}] type={m.motif_type} "
                f"effect={m.effect} role={m.role} region={m.region} params={m.params}"
            )
        for r in spec.regions:
            logger.info(
                f"  [{r.region_id}] shape={r.visual_shape} "
                f"effect={r.visual_effect} role={r.layout_role}"
            )
        return pattern_plan, spec

    def _step2_realization(self, visual_spec: VisualSpec) -> RealizationPlan:
        logger.info("[2/8] Visual -> Realization...")
        return self.v2r.convert(visual_spec)

    def _step3_events(self, realization_plan: RealizationPlan) -> List[EventPoint]:
        logger.info("[3/8] Event planning...")
        return self.event_planner.plan(realization_plan)

    def _step4_build(
        self,
        realization_plan: RealizationPlan,
        events: List[EventPoint],
    ) -> np.ndarray:
        logger.info("[4/8] Action build...")
        return self.action_builder.build(realization_plan, events)

    def _step5_refinement(
        self,
        action_grid: np.ndarray,
        events: List[EventPoint],
    ) -> np.ndarray:
        if not self.config.enable_refinement:
            logger.info("[5/8] Refinement SKIPPED")
            return action_grid

        logger.info("[5/8] Refinement...")
        rows, cols = action_grid.shape
        refine_mask = np.ones((rows, cols), dtype=bool)
        return self.refinement_compiler.refine(
            action_grid=action_grid,
            refinement_mask=refine_mask,
        )

    def _step6_aesthetic(self, action_grid: np.ndarray, realization_plan: RealizationPlan) -> np.ndarray:
        if not self.config.enable_aesthetic:
            logger.info("[6/8] Aesthetic SKIPPED")
            return action_grid

        logger.info("[6/8] Aesthetic pass...")
        return self.aesthetic_pass.apply(action_grid, realization_plan=realization_plan)

    def _step6_25_layer_clip(self, action_grid: np.ndarray, realization_plan: RealizationPlan):
        logger.info("[6.25/8] Layer clipping...")
        clipped = action_grid.copy()
        regions = getattr(realization_plan, "regions", []) or []
        regions_by_id = region_by_id(regions)
        affected_regions = [
            r for r in regions
            if (getattr(r, "placement", {}) or {}).get("clip_to_parent")
            or (getattr(r, "placement", {}) or {}).get("parent_id")
        ]
        if not affected_regions:
            return clipped, {"clipped_actions": 0}

        child_actions = (
            actions.transfer_ids()
            | actions.split_ids()
            | actions.tuck_ids()
            | actions.miss_ids()
            | actions.refinement_action_ids()
        )
        # Ordinary knit actions are also used by parent outlines/base fields, so
        # they are not globally clipped here. Child overlap with the parent
        # border is prevented by the shrunken parent clip mask in layer_utils.
        removed = 0
        rows, cols = clipped.shape
        for r in range(rows):
            for c in range(cols):
                if int(clipped[r, c]) not in child_actions:
                    continue
                inside_any_child = any(
                    layer_mask_contains(r, c, region, regions_by_id, rows)
                    for region in affected_regions
                )
                if inside_any_child:
                    continue
                clipped[r, c] = actions.DEFAULT_BG
                removed += 1

        stats = {"clipped_actions": removed}
        logger.info(f"  layer clipping: {stats}")
        return clipped, stats

    def _audit_layer_clip(self, action_grid: np.ndarray, realization_plan: RealizationPlan) -> Dict[str, int]:
        regions = getattr(realization_plan, "regions", []) or []
        regions_by_id = region_by_id(regions)
        affected_regions = [
            r for r in regions
            if (getattr(r, "placement", {}) or {}).get("clip_to_parent")
            or (getattr(r, "placement", {}) or {}).get("parent_id")
        ]
        texture_actions = (
            actions.transfer_ids()
            | actions.split_ids()
            | actions.tuck_ids()
            | actions.miss_ids()
            | actions.refinement_action_ids()
        )
        outside = 0
        total = 0
        rows, cols = action_grid.shape
        for r in range(rows):
            for c in range(cols):
                if int(action_grid[r, c]) not in texture_actions:
                    continue
                total += 1
                if any(layer_mask_contains(r, c, region, regions_by_id, rows) for region in affected_regions):
                    continue
                outside += 1
        stats = {"texture_actions": total, "texture_actions_outside_child_layers": outside}
        logger.info(f"  layer clipping audit: {stats}")
        return stats

    def _step6_5_compiler_guard(self, action_grid: np.ndarray):
        """
        Enforce compiler-level invariants for low-level knitting operations.

        Special transfer/miss operations are machine operations, not decorative
        pixels. Tuck and split actions are also legitimate sparse texture marks,
        so this guard keeps them and lets the physical/craft rules decide if
        they are invalid.
        """
        logger.info("[6.5/8] Compiler guard...")
        guarded = action_grid.copy()
        rows, cols = guarded.shape
        bg = actions.DEFAULT_BG
        guarded_special = actions.left_transfer_ids() | actions.right_transfer_ids()
        support_special = (
            actions.transfer_ids()
            | actions.split_ids()
            | actions.tuck_ids()
            | actions.miss_ids()
            | actions.refinement_action_ids()
        )
        border_anchor = {actions.idx_safe("b_knit", default=bg)}
        removed = 0

        for r in range(rows):
            for c in range(cols):
                a = int(guarded[r, c])
                if a not in guarded_special:
                    continue

                same_neighbors = 0
                support_neighbors = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if not (0 <= nr < rows and 0 <= nc < cols):
                            continue
                        n = int(guarded[nr, nc])
                        if n == a:
                            same_neighbors += 1
                        if n in support_special or n in border_anchor:
                            support_neighbors += 1

                # Transfers require either a paired/same operation or clear
                # border/structure context. A single transfer in plain ground is
                # never a valid visual structure.
                if a in actions.transfer_ids():
                    keep = same_neighbors >= 1 or support_neighbors >= 2
                else:
                    keep = same_neighbors >= 1

                if not keep:
                    guarded[r, c] = bg
                    removed += 1

        stats = {"removed_contextless_special_actions": removed}
        logger.info(f"  compiler guard: {stats}")
        return guarded, stats

    def _protect_border_pixels(self, action_grid: np.ndarray, realization_plan: RealizationPlan) -> np.ndarray:
        """在所有后处理完成后，重新确保所有 border region 的边框像素完整。

        这是边框保护的最终防线。refinement、aesthetic、layer_clip 等 pass
        可能意外修改 border 像素，这里通过重新计算边框环并强制写入 b_knit
        来确保边框完整性。
        """
        border_regions = [
            r for r in (getattr(realization_plan, "regions", []) or [])
            if r.layout_role == "border" and getattr(r, "border_style", "none") != "none"
        ]
        if not border_regions:
            return action_grid

        guarded = action_grid.copy()
        rows, cols = guarded.shape
        b_knit = actions.idx_safe("b_knit", default=0)
        restored = 0

        for region in border_regions:
            placement = getattr(region, "placement", {}) or {}
            shape = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
            if not shape:
                continue
            thickness = int(getattr(region, "border_thickness", 1) or 1)
            center = placement.get("center", [20, 20])
            try:
                cr, cc = int(center[0]), int(center[1])
                size = int(placement.get("size", 17))
            except Exception:
                continue

            # 对矩形边框使用简单坐标算法（不依赖 point_in_mask）
            if shape in {"rectangle", "rect", "frame", "border", "panel", "box", "square"}:
                # 外圈: [cr-size, cr+size] x [cc-size, cc+size]
                # 内圈: [cr-size+t, cr+size-t] x [cc-size+t, cc+size-t]
                outer_r0 = max(0, cr - size)
                outer_r1 = min(rows - 1, cr + size)
                outer_c0 = max(0, cc - size)
                outer_c1 = min(cols - 1, cc + size)
                inner_r0 = cr - size + thickness
                inner_r1 = cr + size - thickness
                inner_c0 = cc - size + thickness
                inner_c1 = cc + size - thickness

                for r in range(outer_r0, outer_r1 + 1):
                    for c in range(outer_c0, outer_c1 + 1):
                        # 在 outer 内但不在 inner 内 = 边框环
                        in_outer = (outer_r0 <= r <= outer_r1) and (outer_c0 <= c <= outer_c1)
                        in_inner = (inner_r0 <= r <= inner_r1) and (inner_c0 <= c <= inner_c1)
                        if in_outer and not in_inner:
                            if guarded[r, c] != b_knit:
                                guarded[r, c] = b_knit
                                restored += 1
            else:
                # 其他形状使用 point_in_mask
                for r in range(max(0, cr - size), min(rows, cr + size + 1)):
                    for c in range(max(0, cc - size), min(cols, cc + size + 1)):
                        if point_in_mask(r, c, placement, rows):
                            inner_placement = dict(placement)
                            inner_placement["size"] = max(0, size - thickness)
                            if size - thickness > 0 and point_in_mask(r, c, inner_placement, rows):
                                continue
                            if guarded[r, c] != b_knit:
                                guarded[r, c] = b_knit
                                restored += 1

        if restored:
            logger.info(f"  border protection: {restored} pixels restored")
        return guarded

    def _step6_75_canvas_margin(self, action_grid: np.ndarray, margin: int = 1):
        """Keep the final image boundary as plain background.

        The downstream simulator renders the 40x40 code map at 160x160. Any
        structure on the outermost code cells becomes a hard visual artifact at
        the image edge, especially for allover repeats.
        """
        guarded = action_grid.copy()
        rows, cols = guarded.shape
        margin = max(0, min(int(margin), rows // 2, cols // 2))
        if margin <= 0:
            return guarded, {"margin": 0, "cleared_actions": 0}

        bg = actions.DEFAULT_BG
        before = guarded.copy()
        guarded[:margin, :] = bg
        guarded[rows - margin:, :] = bg
        guarded[:, :margin] = bg
        guarded[:, cols - margin:] = bg
        cleared = int(np.count_nonzero(before != guarded))
        stats = {"margin": margin, "cleared_actions": cleared}
        logger.info(f"  canvas margin: {stats}")
        return guarded, stats

    def _step6_9_wave_pair_guard(self, action_grid: np.ndarray, realization_plan: RealizationPlan):
        """Remove final wave cells whose split/tuck partner was lost.

        Diagonal wave/tuck texture is represented by same-row f_split/f_tuck
        pairs. Later passes can remove one side near canvas edges or excluded
        foreground masks, so enforce the pair invariant again immediately
        before saving.
        """
        logger.info("[6.9/8] Wave pair guard...")
        guarded = action_grid.copy()
        rows, cols = guarded.shape
        bg = actions.DEFAULT_BG
        f_split = actions.idx_safe("f_split", default=bg)
        f_tuck = actions.idx_safe("f_tuck", default=bg)
        wave_regions = [
            r for r in (getattr(realization_plan, "regions", []) or [])
            if getattr(r, "event_pattern", "") == "diagonal_wave"
        ]
        if not wave_regions:
            return guarded, {"removed_unpaired_wave_cells": 0}

        removed_unpaired = 0

        for region in wave_regions:
            params = getattr(region, "event_params", {}) or {}
            try:
                split_offset = int(params.get("split_col_offset", 2))
                tuck_offset = int(params.get("tuck_col_offset", 3))
            except Exception:
                split_offset, tuck_offset = 2, 3
            pair_delta = tuck_offset - split_offset
            if pair_delta == 0:
                continue

            placement = getattr(region, "placement", {}) or {}
            for r in range(rows):
                for c in range(cols):
                    a = int(guarded[r, c])
                    if a not in {f_split, f_tuck}:
                        continue

                    if self._is_excluded_by_foreground(r, c, placement, rows):
                        # Foreground motifs can legitimately use f_tuck/f_split
                        # for their own texture, e.g. honeycomb inside a
                        # hexagon.  Background wave regions should already be
                        # excluded earlier, so do not delete foreground cells
                        # here.
                        continue

                    if a == f_split:
                        pc = c + pair_delta
                        partner = f_tuck
                    else:
                        pc = c - pair_delta
                        partner = f_split

                    if 0 <= pc < cols and int(guarded[r, pc]) == partner:
                        continue

                    guarded[r, c] = bg
                    removed_unpaired += 1

        honeycomb_removed = self._prune_unpaired_honeycomb_cells(guarded, realization_plan)

        stats = {
            "removed_unpaired_wave_cells": removed_unpaired,
            "removed_unpaired_honeycomb_cells": honeycomb_removed,
        }
        logger.info(f"  wave pair guard: {stats}")
        return guarded, stats

    def _prune_unpaired_honeycomb_cells(self, grid: np.ndarray, realization_plan: RealizationPlan) -> int:
        rows, cols = grid.shape
        bg = actions.DEFAULT_BG
        f_tuck = actions.idx_safe("f_tuck", default=bg)
        b_tuck = actions.idx_safe("b_tuck", default=bg)
        removed = 0

        for region in getattr(realization_plan, "regions", []) or []:
            if getattr(region, "event_pattern", "") != "honeycomb_tuck":
                continue
            placement = getattr(region, "placement", {}) or {}
            if not has_mask_shape(placement):
                continue
            for r in range(rows):
                for c in range(cols):
                    try:
                        if not point_in_mask(r, c, placement, rows):
                            continue
                    except Exception:
                        continue
                    a = int(grid[r, c])
                    if a == f_tuck:
                        if not (c + 1 < cols and int(grid[r, c + 1]) == b_tuck):
                            grid[r, c] = bg
                            removed += 1
                    elif a == b_tuck:
                        if not (c - 1 >= 0 and int(grid[r, c - 1]) == f_tuck):
                            grid[r, c] = bg
                            removed += 1
        return removed

    def _is_excluded_by_foreground(self, r: int, c: int, placement: dict, grid_size: int) -> bool:
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
                if has_mask_shape(mask) and point_in_mask(r, c, mask, grid_size):
                    return True
                if not has_mask_shape(mask):
                    center = mask.get("center", [grid_size // 2, grid_size // 2])
                    cr, cc = int(center[0]), int(center[1])
                    size = int(mask.get("size", grid_size // 3))
                    if abs(r - cr) <= size and abs(c - cc) <= size:
                        return True
            except Exception:
                continue
        return False

    def _step7_rules(self, action_grid: np.ndarray):
        logger.info("[7/8] Rules check...")
        hard = check_physical(action_grid)
        craft = check_craft_actions(action_grid)

        logger.info(f"  hard violations: {len(hard)}")
        logger.info(f"  craft violations: {len(craft)}")

        fixed = action_grid.copy()
        if hard and self.config.auto_fix_physical:
            fixed = fix_physical(fixed, hard)

        hard_after = check_physical(fixed)
        craft_after = check_craft_actions(fixed)

        report = {
            "hard_before": len(hard),
            "craft_before": len(craft),
            "hard_after": len(hard_after),
            "craft_after": len(craft_after),
            "hard": [self._v2d(v) for v in hard_after[:20]],
            "craft": [self._v2d(v) for v in craft_after[:20]],
        }
        return fixed, report

    def _step8_repair(self, user_input: str, action_grid: np.ndarray, violation_report: Dict):
        logger.info("[8/8] LLM repair...")
        stats = {"rounds": 0, "edits": 0, "final_hard": 0, "final_craft": 0}

        total = violation_report.get("hard_after", 0) + violation_report.get("craft_after", 0)
        if self.config.max_repair_rounds <= 0 or total == 0:
            logger.info(f"  Repair skipped (violations={total})")
            stats["final_hard"] = violation_report.get("hard_after", 0)
            stats["final_craft"] = violation_report.get("craft_after", 0)
            return action_grid, stats

        current = action_grid.copy()
        for _ in range(self.config.max_repair_rounds):
            hard = check_physical(current)
            craft = check_craft_actions(current)
            if not hard and not craft:
                break
            summary = {
                "distribution": self._distribution(current),
                "tension_score": tension_score(current),
            }
            report = {
                "hard_count": len(hard), "craft_count": len(craft),
                "hard": [self._v2d(v) for v in hard[:20]],
                "craft": [self._v2d(v) for v in craft[:20]],
            }
            plan = self.repair_agent.propose(
                user_input=user_input,
                violation_report=report,
                summary=summary,
            )
            if plan.action_edits:
                current = self.repair_agent.apply_action_plan(current, plan)
                stats["edits"] += len(plan.action_edits)
            stats["rounds"] += 1

        final_hard = check_physical(current)
        final_craft = check_craft_actions(current)
        stats["final_hard"] = len(final_hard)
        stats["final_craft"] = len(final_craft)
        logger.info(
            f"  Repair: rounds={stats['rounds']} edits={stats['edits']} "
            f"hard={stats['final_hard']} craft={stats['final_craft']}"
        )
        return current, stats

    # ============================================================
    # 保存
    # ============================================================

    def save_results(self, result: PipelineResult, output_dir: Path, prefix: str = "pattern"):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        bmp_path = output_dir / f"{prefix}_output.bmp"
        save_image(
            result.action_grid_40x40,
            bmp_path,
            palette=actions.build_palette_256(),
        )
        logger.info(f"Saved BMP to {bmp_path}")

        machine_bmp_path = output_dir / f"{prefix}_machine_output.bmp"
        save_image(
            result.action_grid_40x40,
            machine_bmp_path,
            palette=actions.build_machine_palette_256(),
        )
        logger.info(f"Saved machine BMP to {machine_bmp_path}")

        machine_report_path = output_dir / f"{prefix}_machine_export_report.json"
        with open(machine_report_path, "w", encoding="utf-8") as f:
            json.dump(
                self._machine_export_report(result.action_grid_40x40),
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"Saved machine export report to {machine_report_path}")

        sim_png_path = output_dir / f"{prefix}_sim_input.png"
        save_image(result.rgb_image, sim_png_path)
        logger.info(f"Saved simulation input PNG to {sim_png_path}")

        if self.config.save_intermediate:
            inter = output_dir / "intermediate"
            inter.mkdir(exist_ok=True)
            np.save(inter / f"{prefix}_action.npy", result.action_grid_40x40)
            if result.rgb_image is not None:
                save_image(result.rgb_image, inter / f"{prefix}_preview.bmp")

        if result.pattern_plan is not None:
            plan_path = output_dir / f"{prefix}_pattern_plan.json"
            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(result.pattern_plan.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"Saved pattern plan to {plan_path}")

        stats_path = output_dir / f"{prefix}_stats.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(self._serializable(result.statistics), f, ensure_ascii=False, indent=2)

    # ============================================================
    # 工具
    # ============================================================

    def _distribution(self, grid: np.ndarray) -> Dict[str, int]:
        uniq, counts = np.unique(grid, return_counts=True)
        return {actions.abbr(int(i)): int(c) for i, c in zip(uniq, counts)}

    def _machine_export_report(self, grid: np.ndarray) -> Dict[str, Any]:
        uniq, counts = np.unique(grid, return_counts=True)
        mapped = []
        requires_confirmation = []
        unmapped = []
        for idx, count in zip(uniq, counts):
            action_idx = int(idx)
            item = {
                "abbr": actions.abbr(action_idx),
                "count": int(count),
                "internal_color": actions.color_hex(action_idx),
                "export_color": actions.machine_color_hex(action_idx),
                "machine_export_safe": actions.machine_export_safe(action_idx),
                "machine_export_requires_confirmation": actions.machine_export_requires_confirmation(action_idx),
                "machine_action_id": actions.machine_action_id(action_idx),
                "machine_action_name": actions.machine_action_name(action_idx),
            }
            issue = actions.machine_export_issue(action_idx)
            if issue:
                item["issue"] = issue
            if not actions.machine_action_id(action_idx) and actions.machine_action_id(action_idx) != 0:
                item["issue"] = issue or "没有机器宏映射。"
                unmapped.append(item)
            elif actions.machine_export_requires_confirmation(action_idx):
                requires_confirmation.append(item)
            else:
                mapped.append(item)

        return {
            "summary": {
                "safe_action_kinds": len(mapped),
                "requires_confirmation_action_kinds": len(requires_confirmation),
                "unmapped_action_kinds": len(unmapped),
                "requires_confirmation_cell_count": sum(item["count"] for item in requires_confirmation),
                "unmapped_cell_count": sum(item["count"] for item in unmapped),
                "note": "机器 BMP 使用恒强机器色表颜色；requires_confirmation 动作需要打版师确认宏参数、度目或速度后再上机。",
            },
            "mapped_actions": mapped,
            "requires_confirmation_actions": requires_confirmation,
            "unmapped_actions": unmapped,
        }

    def _v2d(self, v) -> Dict:
        return {
            "level": getattr(v, "level", ""),
            "rule": getattr(v, "rule", ""),
            "row": int(getattr(v, "row", -1)),
            "col": int(getattr(v, "col", -1)),
            "detail": getattr(v, "detail", ""),
        }

    def _serializable(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {str(k): self._serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._serializable(v) for v in obj]
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if hasattr(obj, "__dict__"):
            return self._serializable(obj.__dict__)
        return obj
