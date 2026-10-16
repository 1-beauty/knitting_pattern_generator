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
from typing import Optional, Dict, Any, List, Set, Tuple

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
from generation.mask_utils import (
    point_in_mask, has_mask_shape, is_excluded_by_foreground,
)

from rules import (
    check_physical,
    fix_physical,
    check_craft_actions,
    fix_craft_actions,
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
    skip_pattern_plan: bool = False  # Baseline: skip PatternPlan hierarchy
    fixed_plan_path: str = ""  # Ablation: reuse a fixed pattern_plan JSON, skip LLM
    no_layer_clip: bool = False  # Baseline: disable layer clipping
    no_wave_pair_guard: bool = False  # Baseline: disable wave pair guard
    compile_mode: str = "event"  # event: 稀疏事件编译（完整方法）/ dense: Plan-Grid 密集填充基线


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
        timings: Dict[str, float] = {}  # 逐阶段耗时（秒），随 stats.json 落盘

        result = PipelineResult(
            action_grid_40x40=np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
            rgb_image=np.zeros((GRID_SIZE, GRID_SIZE, 3), dtype=np.uint8),
            statistics={},
        )

        logger.info("=" * 60)
        logger.info(f"Generate: {user_input}")
        logger.info("=" * 60)

        # Step 1: LLM/heuristics -> editable PatternPlan -> VisualSpec
        _t = time.time()
        pattern_plan, visual_spec = self._step1_design(user_input, current_plan=current_plan)
        timings["step1_design_llm"] = time.time() - _t
        result.pattern_plan = pattern_plan
        result.visual_spec = visual_spec
        result.statistics["pattern_plan"] = pattern_plan.to_dict()
        result.statistics["layout_type"] = visual_spec.layout_type
        result.statistics["num_regions"] = len(visual_spec.regions)

        # Plan-Grid 基线：dense 模式绕过稀疏事件规划，并强制关闭
        # 层次作用域裁剪与成组守卫（见补实验方案 §1）。
        _dense = str(self.config.compile_mode or "event").lower() == "dense"
        result.statistics["compile_mode"] = "dense" if _dense else "event"

        # Step 2: VisualSpec -> RealizationPlan
        _t = time.time()
        realization_plan = self._step2_realization(visual_spec)
        timings["step2_realization"] = time.time() - _t
        result.realization_plan = realization_plan

        # Step 3: RealizationPlan -> EventPoints
        _t = time.time()
        if _dense:
            logger.info("[3/8] [BASELINE dense] skip sparse event planning")
            events = []
        else:
            events = self._step3_events(realization_plan)
        timings["step3_event_planning"] = time.time() - _t
        result.events = events
        result.statistics["total_events"] = len(events)

        # Step 4: Build ActionGrid
        _t = time.time()
        if _dense:
            action_grid = self.action_builder.build_dense(realization_plan)
        else:
            action_grid = self._step4_build(realization_plan, events)
        timings["step4_action_build"] = time.time() - _t
        # Capture rejection diagnostics from action builder
        _rej_info = getattr(self.action_builder, '_last_rejection_info', None)
        if _rej_info and _rej_info.get('rejected_by_region'):
            result.statistics['event_rejection'] = {
                'rejected_by_region': _rej_info.get('rejected_by_region', {}),
                'first_rejection_reasons': _rej_info.get('rejection_reasons', {}),
                'events_placed': _rej_info.get('events_placed', {}),
            }

        # Step 5: Refinement
        _t = time.time()
        action_grid = self._step5_refinement(action_grid, events)

        # Step 6: Aesthetic
        action_grid = self._step6_aesthetic(action_grid, realization_plan)
        timings["step5_6_refine_aesthetic"] = time.time() - _t

        # Step 6.25: enforce clipped layer composition after post-processing.
        if not self.config.no_layer_clip and not _dense:
            action_grid, layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
            result.statistics["layer_clip"] = layer_clip_stats
        else:
            result.statistics["layer_clip"] = {"clipped_actions": 0, "disabled": True}

        # Step 6.5: Compiler guard
        action_grid, guard_stats = self._step6_5_compiler_guard(action_grid)
        result.statistics["compiler_guard"] = guard_stats

        # Step 7: Rules
        _t = time.time()
        action_grid, violation_report = self._step7_rules(action_grid)
        timings["step7_rule_check"] = time.time() - _t
        result.statistics["violations"] = violation_report

        # Step 8: LLM Repair
        _t = time.time()
        if self.config.enable_llm_repair:
            action_grid, repair_stats = self._step8_repair(user_input, action_grid, violation_report)
            result.statistics["llm_repair"] = repair_stats
            action_grid, post_repair_guard_stats = self._step6_5_compiler_guard(action_grid)
            result.statistics["post_repair_compiler_guard"] = post_repair_guard_stats
            if not self.config.no_layer_clip and not _dense:
                action_grid, post_repair_layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
                result.statistics["post_repair_layer_clip"] = post_repair_layer_clip_stats
            if not _dense:
                action_grid, event_region_guard_stats = self._step6_30_event_region_guard(action_grid, realization_plan)
                result.statistics["post_repair_event_region_guard"] = event_region_guard_stats
        timings["step8_repair"] = time.time() - _t

        _t = time.time()
        if not self.config.no_layer_clip and not _dense:
            action_grid, final_layer_clip_stats = self._step6_25_layer_clip(action_grid, realization_plan)
            result.statistics["final_layer_clip"] = final_layer_clip_stats
        else:
            result.statistics["final_layer_clip"] = {"clipped_actions": 0, "disabled": True}
        result.statistics["layer_clip_audit"] = self._audit_layer_clip(action_grid, realization_plan)
        action_grid, canvas_margin_stats = self._step6_75_canvas_margin(action_grid)
        result.statistics["canvas_margin"] = canvas_margin_stats
        if not self.config.no_wave_pair_guard and not _dense:
            action_grid, wave_pair_stats = self._step6_9_wave_pair_guard(action_grid, realization_plan)
            result.statistics["wave_pair_guard"] = wave_pair_stats
        else:
            result.statistics["wave_pair_guard"] = {"disabled": True}

        # 最终规则验证：后处理 guards 可能引入新违规，统一检查并修复
        action_grid = self._final_rules_pass(action_grid)

        # 边框保护：最终防线，必须在 _final_rules_pass 之后，确保边框像素不被任何后处理破坏
        action_grid = self._protect_border_pixels(action_grid, realization_plan)
        timings["post_guards_final"] = time.time() - _t

        result.action_grid_40x40 = action_grid
        result.rgb_image = action_grid_to_rgb(action_grid)
        result.statistics["distribution"] = self._distribution(action_grid)
        result.statistics["tension_score"] = tension_score(action_grid)
        result.execution_time = time.time() - start
        timings["total"] = result.execution_time
        result.statistics["timings"] = {k: round(v, 4) for k, v in timings.items()}

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

        # Ablation 模式：直接加载固定 plan，跳过 LLM
        if self.config.fixed_plan_path:
            import json
            from pathlib import Path
            plan_file = Path(self.config.fixed_plan_path)
            logger.info(f"  [ABLATION] fixed_plan_path={plan_file}, skipping LLM")
            with open(plan_file, "r", encoding="utf-8") as f:
                pattern_plan = PatternPlan.from_dict(json.load(f))
        else:
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

        # Baseline: skip PatternPlan hierarchy
        if self.config.skip_pattern_plan:
            logger.info("  [BASELINE] skip_pattern_plan=True, using flat plan from VisualSpec")
            spec_full = self.plan_engine.render_visual_spec(pattern_plan)
            pattern_plan = self.plan_engine.from_visual_spec_flat(spec_full)

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
        regions = getattr(realization_plan, "regions", []) or []
        regions_by_id = region_by_id(regions)
        affected_regions = [
            r for r in regions
            if (getattr(r, "placement", {}) or {}).get("clip_to_parent")
            or (getattr(r, "placement", {}) or {}).get("parent_id")
        ]
        if not affected_regions:
            return action_grid, {"clipped_actions": 0}

        clipped = action_grid.copy()

        # 收集 allover/ground 区域，它们的特殊动作不应被裁剪
        allover_regions = [
            r for r in regions
            if getattr(r, "layout_role", "") in {"allover", "ground"}
            or (getattr(r, "placement", {}) or {}).get("type") in {"full", "repeat"}
        ]

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
                # allover/ground 区域的特殊动作也应保留（背景纹理）
                inside_allover = False
                for ar in allover_regions:
                    ap = getattr(ar, "placement", {}) or {}
                    if ap.get("type") in {"full"}:
                        inside_allover = True
                        break
                    if has_mask_shape(ap) and point_in_mask(r, c, ap, rows):
                        inside_allover = True
                        break
                if inside_allover:
                    continue
                clipped[r, c] = actions.DEFAULT_BG
                removed += 1

        stats = {"clipped_actions": removed}
        logger.info(f"  layer clipping: {stats}")
        return clipped, stats

    def _step6_30_event_region_guard(
        self, action_grid: np.ndarray, realization_plan: RealizationPlan,
    ):
        """Guard: remove special actions outside the actual event region.

        The layer clip (step 6.25) uses the full geometric mask, but events
        are planned with a border_guard that keeps them away from the mask
        boundary.  After LLM repair, new special actions (f_split, xfer, etc.)
        may be placed inside the geometric mask but outside the border-guarded
        event region, creating isolated color blocks at the border.

        This step shrinks each child region's mask by its border_guard value
        and removes any special actions that fall in the border zone.

        Pair awareness: composite textures (wave f_split+f_tuck, etc.) must
        appear or disappear together.  When an action is removed, its pair
        partner is also removed to prevent orphaned single cells.
        """
        logger.info("[6.3/8] Event region guard...")
        guarded = action_grid.copy()
        regions = getattr(realization_plan, "regions", []) or []
        rows, cols = guarded.shape
        bg = actions.DEFAULT_BG

        child_actions = (
            actions.transfer_ids()
            | actions.split_ids()
            | actions.tuck_ids()
            | actions.miss_ids()
            | actions.refinement_action_ids()
        )

        # Collect child regions that have events
        event_regions = [
            r for r in regions
            if getattr(r, "event_pattern", "none") != "none"
            and (
                (getattr(r, "placement", {}) or {}).get("parent_id")
                or (getattr(r, "placement", {}) or {}).get("clip_to_parent")
                or has_mask_shape(getattr(r, "placement", {}) or {})
            )
        ]

        if not event_regions:
            stats = {"removed_outside_event_region": 0}
            logger.info(f"  event region guard: {stats}")
            return guarded, stats

        # Pre-compute pair_delta for each event region (wave patterns)
        region_pair_delta: Dict[str, int] = {}
        for region in event_regions:
            ep = getattr(region, "event_params", {}) or {}
            try:
                split_off = int(ep.get("split_col_offset", 2))
                tuck_off = int(ep.get("tuck_col_offset", 3))
                delta = tuck_off - split_off
                if delta != 0:
                    region_pair_delta[region.region_id] = delta
            except Exception:
                pass

        # Pass 1: mark actions to remove (outside border-guarded event region)
        to_remove: Set[Tuple[int, int]] = set()
        for r_idx in range(rows):
            for c_idx in range(cols):
                a = int(guarded[r_idx, c_idx])
                if a not in child_actions:
                    continue

                for region in event_regions:
                    placement = getattr(region, "placement", {}) or {}
                    if not has_mask_shape(placement):
                        continue

                    if not point_in_mask(r_idx, c_idx, placement, rows):
                        continue

                    event_params = getattr(region, "event_params", {}) or {}
                    # 精确边框环排除：使用与 event_planner 相同的掩码差集逻辑
                    _border_style = str(getattr(region, "border_style", "none") or "none").lower()
                    if _border_style == "none":
                        continue
                    _bt = max(1, int(getattr(region, "border_thickness", 1) or 1))
                    shrunk = dict(placement)
                    try:
                        orig_size = int(shrunk.get("size", 0))
                        shrunk["size"] = max(0, orig_size - _bt)
                    except Exception:
                        continue

                    if shrunk.get("size", 0) > 0 and not point_in_mask(r_idx, c_idx, shrunk, rows):
                        to_remove.add((r_idx, c_idx))
                    break

        # Pass 2: pair-aware and period-aware propagation.
        # Composite textures must appear/disappear as complete units:
        #   - Wave (f_split + f_tuck): pair at (r,c) and (r, c+delta)
        #   - Periodic (honeycomb/lattice/staggered/seed): full period grid
        f_split_idx = actions.idx_safe("f_split", default=-1)
        f_tuck_idx = actions.idx_safe("f_tuck", default=-1)
        xfer_fb_idx = actions.idx_safe("xfer_f_b", default=-1)
        xfer_bf_idx = actions.idx_safe("xfer_b_f", default=-1)
        miss_idx_set = actions.miss_ids()
        pair_propagated = 0
        period_propagated = 0

        # --- Wave pair propagation ---
        if f_split_idx >= 0 and f_tuck_idx >= 0:
            changed = True
            while changed:
                changed = False
                for (r_idx, c_idx) in list(to_remove):
                    a = int(guarded[r_idx, c_idx])
                    if a not in (f_split_idx, f_tuck_idx):
                        continue

                    delta = None
                    for region in event_regions:
                        placement = getattr(region, "placement", {}) or {}
                        if has_mask_shape(placement) and point_in_mask(r_idx, c_idx, placement, rows):
                            delta = region_pair_delta.get(region.region_id)
                            break
                    if delta is None:
                        continue

                    if a == f_split_idx:
                        pr, pc = r_idx, c_idx + delta
                    else:
                        pr, pc = r_idx, c_idx - delta

                    if (pr, pc) in to_remove:
                        continue
                    if not (0 <= pr < rows and 0 <= pc < cols):
                        continue
                    partner_val = int(guarded[pr, pc])
                    expected_partner = f_tuck_idx if a == f_split_idx else f_split_idx
                    if partner_val == expected_partner:
                        to_remove.add((pr, pc))
                        pair_propagated += 1
                        changed = True

        # --- Periodic texture propagation ---
        # For honeycomb/lattice/staggered/seed: when any cell in a period
        # is removed, remove ALL cells of that period within the region.
        #
        # Region-aware: check the region's event_pattern to determine
        # expected action types, NOT a global action-level mapping.
        # (f_tuck appears in both staggered_tuck and honeycomb_tuck regions.)
        _periodic_patterns = {
            "honeycomb_tuck", "lattice_miss", "staggered_tuck",
            "seed_tuck", "seed_stitch",
        }
        _pattern_expected_actions: Dict[str, Set[int]] = {}
        for pat in _periodic_patterns:
            expected: Set[int] = set()
            if pat in ("staggered_tuck", "honeycomb_tuck") and f_tuck_idx >= 0:
                expected.add(f_tuck_idx)
            if pat == "lattice_miss":
                expected |= miss_idx_set
            if pat == "seed_tuck" and f_tuck_idx >= 0:
                expected.add(f_tuck_idx)
            if pat == "seed_stitch":
                _bk = actions.idx_safe("b_knit", default=-1)
                if _bk >= 0:
                    expected.add(_bk)
            if expected:
                _pattern_expected_actions[pat] = expected

        # Build per-region period info — only for periodic textures,
        # NOT for wave (handled by pair propagation above) or cable.
        region_period_info: Dict[str, Dict] = {}
        for region in event_regions:
            ep = getattr(region, "event_params", {}) or {}
            pattern = getattr(region, "event_pattern", "none") or "none"
            if pattern not in _periodic_patterns:
                continue
            px = int(ep.get("period_x", 4))
            py = int(ep.get("period_y", 4))
            stagger = bool(ep.get("stagger", True))
            if px <= 0 or py <= 0:
                continue
            region_period_info[region.region_id] = {
                "pattern": pattern,
                "period_x": px,
                "period_y": py,
                "stagger": stagger,
            }

        # For each removed cell that belongs to a periodic texture,
        # find all cells in the same period and mark them for removal too.
        changed = True
        while changed:
            changed = False
            for (r_idx, c_idx) in list(to_remove):
                a = int(guarded[r_idx, c_idx])

                # Find which region this cell belongs to (region-aware)
                target_region = None
                for region in event_regions:
                    placement = getattr(region, "placement", {}) or {}
                    if has_mask_shape(placement) and point_in_mask(r_idx, c_idx, placement, rows):
                        rid = region.region_id
                        if rid in region_period_info:
                            target_region = region
                            break
                if target_region is None:
                    continue

                rid = target_region.region_id
                pinfo = region_period_info[rid]

                # Check that this action type is expected for the region's pattern
                expected = _pattern_expected_actions.get(pinfo["pattern"], set())
                if a not in expected:
                    continue

                px, py = pinfo["period_x"], pinfo["period_y"]
                stagger = pinfo["stagger"]

                placement = getattr(target_region, "placement", {}) or {}
                if not has_mask_shape(placement):
                    continue

                # Get region bounds
                try:
                    cr = int(placement.get("center", [20, 20])[0])
                    cc = int(placement.get("center", [20, 20])[1])
                    sz = int(placement.get("size", 16))
                except Exception:
                    continue

                r_lo = max(0, cr - sz)
                r_hi = min(rows, cr + sz + 1)
                c_lo = max(0, cc - sz)
                c_hi = min(cols, cc + sz + 1)

                # Find all cells in the same period as (r_idx, c_idx)
                # A cell (r, c) is in the same period if:
                #   (r - r_idx) % py == 0  AND
                #   (c - c_idx - stagger_adjustment) % px == 0
                # where stagger_adjustment accounts for row-dependent offset
                for r in range(r_lo, r_hi):
                    if (r - r_idx) % py != 0:
                        continue
                    row_phase_diff = (r - r_idx) // py
                    stagger_adj = (px // 2) * (row_phase_diff % 2) if stagger else 0
                    for c in range(c_lo, c_hi):
                        if (c - c_idx - stagger_adj) % px != 0:
                            continue
                        if (r, c) == (r_idx, c_idx):
                            continue
                        if (r, c) in to_remove:
                            continue
                        if not point_in_mask(r, c, placement, rows):
                            continue
                        val = int(guarded[r, c])
                        if val == a:
                            to_remove.add((r, c))
                            period_propagated += 1
                            changed = True

        # --- Cross-period propagation for lattice_miss ---
        # lattice_miss composite holes span adjacent period bands:
        #   even band: xfer_f_b, odd band: xfer_b_f (or vice versa).
        # When one half is removed, the other half must also be removed
        # to prevent orphaned single transfers at the border.
        _xfer_indices = {i for i in (xfer_fb_idx, xfer_bf_idx) if i >= 0}
        if _xfer_indices:
            changed = True
            while changed:
                changed = False
                for (r_idx, c_idx) in list(to_remove):
                    a = int(guarded[r_idx, c_idx])
                    if a not in _xfer_indices:
                        continue

                    # Find lattice_miss region for this cell
                    target_region = None
                    for region in event_regions:
                        if getattr(region, "event_pattern", "") != "lattice_miss":
                            continue
                        placement = getattr(region, "placement", {}) or {}
                        if has_mask_shape(placement) and point_in_mask(r_idx, c_idx, placement, rows):
                            target_region = region
                            break
                    if target_region is None:
                        continue

                    pinfo = region_period_info.get(target_region.region_id)
                    if pinfo is None:
                        continue

                    py = pinfo["period_y"]
                    placement = getattr(target_region, "placement", {}) or {}

                    # Check adjacent period bands (±py rows, same column)
                    for dr in (-py, py):
                        pr, pc = r_idx + dr, c_idx
                        if not (0 <= pr < rows and 0 <= pc < cols):
                            continue
                        if (pr, pc) in to_remove:
                            continue
                        if not point_in_mask(pr, pc, placement, rows):
                            continue
                        partner_val = int(guarded[pr, pc])
                        # Partner should be the other transfer type
                        if partner_val in _xfer_indices and partner_val != a:
                            to_remove.add((pr, pc))
                            period_propagated += 1
                            changed = True

        # Apply removals
        for (r_idx, c_idx) in to_remove:
            guarded[r_idx, c_idx] = bg

        removed = len(to_remove)
        stats = {
            "removed_outside_event_region": removed,
            "pair_partner_removed": pair_propagated,
            "period_partner_removed": period_propagated,
        }
        logger.info(f"  event region guard: {stats}")
        return guarded, stats

    def _audit_layer_clip(self, action_grid: np.ndarray, realization_plan: RealizationPlan) -> Dict[str, int]:
        regions = getattr(realization_plan, "regions", []) or []
        regions_by_id = region_by_id(regions)
        affected_regions = [
            r for r in regions
            if (getattr(r, "placement", {}) or {}).get("clip_to_parent")
            or (getattr(r, "placement", {}) or {}).get("parent_id")
        ]
        allover_regions = [
            r for r in regions
            if getattr(r, "layout_role", "") in {"allover", "ground"}
            or (getattr(r, "placement", {}) or {}).get("type") in {"full", "repeat"}
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
                # 也检查 allover 区域
                inside_allover = any(
                    (getattr(ar, "placement", {}) or {}).get("type") == "full"
                    or (has_mask_shape(getattr(ar, "placement", {}) or {})
                        and point_in_mask(r, c, getattr(ar, "placement", {}), rows))
                    for ar in allover_regions
                )
                if inside_allover:
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
        """在所有后处理完成后，重新确保所有带边框区域的边框像素完整。

        这是边框保护的最终防线。refinement、aesthetic、layer_clip 等 pass
        可能意外修改 border 像素，这里通过重新计算边框环并强制写入 b_knit
        来确保边框完整性。
        
        覆盖范围：所有 border_style != "none" 的区域（不限于 layout_role=="border"），
        因为 center 角色的几何形状（三角形、圆形等）同样需要边框保护。
        
        关键修复：不覆盖任何 child texture region 内的像素。
        """
        border_regions = [
            r for r in (getattr(realization_plan, "regions", []) or [])
            if getattr(r, "border_style", "none") != "none"
        ]
        if not border_regions:
            return action_grid

        guarded = action_grid.copy()
        rows, cols = guarded.shape
        b_knit = actions.idx_safe("b_knit", default=0)
        restored = 0

        # 收集所有 child texture regions 的掩码信息
        child_texture_placements = []
        for r in (getattr(realization_plan, "regions", []) or []):
            placement = getattr(r, "placement", {}) or {}
            if (placement.get("clip_to_parent") or placement.get("parent_id")) and r.layout_role != "border":
                if has_mask_shape(placement):
                    child_texture_placements.append(placement)

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
                            # 保护：不覆盖 child texture region 内的像素
                            inside_child = False
                            for child_placement in child_texture_placements:
                                try:
                                    if point_in_mask(r, c, child_placement, rows):
                                        inside_child = True
                                        break
                                except Exception:
                                    pass
                            if inside_child:
                                continue
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
                            # 保护：不覆盖 child texture region 内的像素
                            inside_child = False
                            for child_placement in child_texture_placements:
                                try:
                                    if point_in_mask(r, c, child_placement, rows):
                                        inside_child = True
                                        break
                                except Exception:
                                    pass
                            if inside_child:
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
            # 有界区域（圆形/心形等）的边界细胞天然会丢失伙伴，跳过配对检查
            _shape = str(placement.get("shape", "")).lower()
            _is_bounded = any(
                s in _shape for s in
                ["circle", "round", "heart", "star", "hexagon", "oval", "ellipse",
                 "diamond", "triangle", "polygon"]
            )
            if _is_bounded:
                continue
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
            # 有界区域（圆形/心形等）的边界细胞天然会丢失伙伴，跳过配对检查
            _shape = str(placement.get("shape", "")).lower()
            _is_bounded = any(
                s in _shape for s in
                ["circle", "round", "heart", "star", "hexagon", "oval", "ellipse",
                 "diamond", "triangle", "polygon"]
            )
            if _is_bounded:
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
        return is_excluded_by_foreground(r, c, placement, grid_size)

    def _step7_rules(self, action_grid: np.ndarray):
        logger.info("[7/8] Rules check...")
        hard = check_physical(action_grid)
        craft = check_craft_actions(action_grid)

        logger.info(f"  hard violations: {len(hard)}")
        logger.info(f"  craft violations: {len(craft)}")

        fixed = action_grid.copy()
        if hard and self.config.auto_fix_physical:
            fixed = fix_physical(fixed, hard)

        # Auto-fix craft violations as fallback (LLM repair handles
        # complex cases, but the heuristic fixer catches simple ones).
        if craft:
            fixed = fix_craft_actions(fixed, craft)

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

    def _final_rules_pass(self, action_grid: np.ndarray) -> np.ndarray:
        """Post-processing guards may introduce new violations.
        Run one last check + auto-fix to ensure a clean output."""
        hard = check_physical(action_grid)
        craft = check_craft_actions(action_grid)
        if not hard and not craft:
            return action_grid

        logger.info(f"  final rules pass: hard={len(hard)} craft={len(craft)}")
        fixed = action_grid.copy()
        if hard and self.config.auto_fix_physical:
            fixed = fix_physical(fixed, hard)
        if craft:
            fixed = fix_craft_actions(fixed, craft)

        hard_after = check_physical(fixed)
        craft_after = check_craft_actions(fixed)
        logger.info(f"  final rules after fix: hard={len(hard_after)} craft={len(craft_after)}")
        return fixed

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

        legend = self._stitch_legend(result.action_grid_40x40)
        legend_path = output_dir / f"{prefix}_stitch_legend.json"
        with open(legend_path, "w", encoding="utf-8") as f:
            json.dump(legend, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved stitch legend to {legend_path}")
        self._log_stitch_legend(legend)

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

    def _stitch_legend(self, grid: np.ndarray) -> Dict[str, Any]:
        """统计色码图使用的色块及其针法物理含义，供人工对照工厂色卡。"""
        uniq, counts = np.unique(grid, return_counts=True)
        total = int(grid.size)
        entries = []
        for idx, count in zip(uniq, counts):
            action_idx = int(idx)
            if action_idx not in actions.ALL_ACTION_INDICES:
                continue
            sem = actions.semantic(action_idx)
            entries.append({
                "action_idx": action_idx,
                "abbr": actions.abbr(action_idx),
                "color": actions.color_hex(action_idx),
                "name": actions.name(action_idx),
                "bed": actions.bed(action_idx) or "",
                "semantic": sem,
                "semantic_name": actions.semantic_prop(sem, "name", sem),
                "description": actions.info(action_idx).get("description", ""),
                "count": int(count),
                "ratio": round(int(count) / total, 4) if total else 0.0,
            })
        entries.sort(key=lambda e: e["count"], reverse=True)
        return {
            "total_cells": total,
            "color_kinds": len(entries),
            "note": "本表列出色码图中每种色块对应的针法及物理含义，仅描述内部动作语义，可据此人工对照工厂色卡。",
            "stitches": entries,
        }

    def _log_stitch_legend(self, legend: Dict[str, Any]) -> None:
        logger.info(
            f"针法说明（色块 → 针法物理含义，共 {legend['color_kinds']} 种色块 / {legend['total_cells']} 格）:"
        )
        for e in legend["stitches"]:
            bed_part = ("/" + e["bed"]) if e["bed"] else ""
            logger.info(
                f"  {e['color']}  {e['abbr']:<8} {e['name']}  "
                f"[{e['semantic_name']}/{e['semantic']}{bed_part}]  "
                f"{e['count']} 格 ({e['ratio']:.1%})"
            )

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
