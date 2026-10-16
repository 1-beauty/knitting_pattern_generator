"""
视觉目标 -> 色码实现方案 v11.0

这是最关键的翻译层：
把"仿真图想长什么样"翻译成"色码图应该怎么排列动作"。

核心原则：
- 仿真图形状 ≠ 色码图形状
- 这一层负责理解这种"非一一对应关系"
- 输出的是 RealizationPlan，不是直接的动作

v10.0 改进：Shape 标准化（处理 circle, square 等非标准 shape）
v11.0 改进：保守工艺编译。闭合几何形状只生成可解释轮廓；
未知或不支持的效果不再自动升级为纹理事件。
"""

from generation.visual_types import (
    VisualSpec,
    VisualRegion,
    RealizationPlan,
    RealizationRegion,
)
from utils.logger import logger
from generation.mask_utils import resolve_side_band_side


# ============================================================
# 视觉效果 → 色码实现映射表
# ============================================================

_EFFECT_TO_REALIZATION = {

    # plain / reverse
    ("plain", "panel"):     ("plain_front", "none", "none"),
    ("plain", "rectangle"): ("plain_front", "back_loop_outline", "none"),
    ("plain", "diamond"):   ("plain_front", "back_loop_outline", "none"),
    ("plain", "circle"):    ("plain_front", "back_loop_outline", "none"),
    ("plain", "triangle"):  ("plain_front", "back_loop_outline", "none"),
    ("plain", "hexagon"):   ("plain_front", "back_loop_outline", "none"),
    ("plain", "polygon"):   ("plain_front", "back_loop_outline", "none"),
    ("plain", "heart"):     ("plain_front", "back_loop_outline", "none"),
    ("plain", "star"):      ("plain_front", "back_loop_outline", "none"),
    ("plain", "chevron"):   ("plain_front", "back_loop_outline", "none"),
    ("plain", "zigzag"):    ("plain_front", "back_loop_outline", "none"),
    ("plain", "cross"):     ("plain_front", "back_loop_outline", "none"),
    ("plain", "frame"):     ("plain_front", "back_loop_outline", "none"),
    ("plain", "allover"):   ("plain_front", "none", "none"),
    ("plain", "stripe"):    ("plain_front", "none", "none"),
    ("plain", "column"):    ("plain_front", "none", "none"),
    ("reverse", "diamond"): ("plain_back", "back_loop_outline", "none"),
    ("reverse", "circle"):  ("plain_back", "back_loop_outline", "none"),
    ("reverse", "rectangle"): ("plain_back", "back_loop_outline", "none"),
    ("reverse", "triangle"): ("plain_back", "back_loop_outline", "none"),
    ("reverse", "hexagon"):  ("plain_back", "back_loop_outline", "none"),
    ("reverse", "polygon"):  ("plain_back", "back_loop_outline", "none"),
    ("reverse", "heart"):    ("plain_back", "back_loop_outline", "none"),
    ("reverse", "star"):      ("plain_back", "back_loop_outline", "none"),
    ("reverse", "chevron"):  ("plain_back", "back_loop_outline", "none"),
    ("reverse", "zigzag"):   ("plain_back", "back_loop_outline", "none"),
    ("reverse", "cross"):    ("plain_back", "back_loop_outline", "none"),
    ("reverse", "panel"):   ("plain_back", "none", "none"),

    # cable / 麻花
    # 闭合几何里的 cable 使用 column_xfer 柱状麻花模式，通过掩码裁剪到形状内部
    ("cable", "diamond"):   ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "circle"):    ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "panel"):     ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "column"):    ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "stripe"):    ("plain_front", "back_loop_outline", "column_xfer"),  # 横条也可用列麻花
    ("cable", "star"):      ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "heart"):     ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "hexagon"):   ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "triangle"):  ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "polygon"):   ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "rectangle"): ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "cross"):     ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "chevron"):   ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "zigzag"):    ("plain_front", "back_loop_outline", "column_xfer"),

    # wave_tuck / 波浪集圈
    # 纹理效果不默认带轮廓：轮廓决策延迟到 _resolve_border_styles 后处理，
    # 该阶段拥有完整层级上下文，可区分 standalone 与 child texture。
    ("wave_tuck", "panel"):     ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "rectangle"): ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "allover"):   ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "diamond"):   ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "triangle"):  ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "hexagon"):   ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "polygon"):   ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "circle"):    ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "heart"):     ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "star"):      ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "chevron"):   ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "zigzag"):    ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "cross"):     ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "wave"):      ("plain_front", "none", "diagonal_wave"),
    ("wave_tuck", "stripe"):    ("plain_front", "none", "diagonal_wave"),  # 条纹内波浪
    ("wave_tuck", "column"):    ("plain_front", "none", "diagonal_wave"),  # 柱状内波浪

    # rib / 罗纹
    ("rib", "panel"):       ("rib", "none", "none"),
    ("rib", "stripe"):      ("rib", "none", "none"),           # 竖条纹不需要额外事件，rib底布已表达
    ("rib", "column"):      ("rib", "none", "diagonal_wave"),  # column 形状的 rib 生成对角波纹
    ("rib", "rectangle"):   ("rib", "none", "none"),            # 矩形内竖条纹
    ("rib", "frame"):       ("rib", "none", "none"),            # 框架内竖条纹

    # links / 正反交替
    ("links", "panel"):     ("links", "none", "none"),
    ("links", "allover"):   ("links", "none", "none"),

    # lace / 网眼
    ("lace", "panel"):      ("plain_front", "none", "lattice_miss"),
    ("lace", "rectangle"):  ("plain_front", "none", "lattice_miss"),
    ("lace", "circle"):     ("plain_front", "none", "lattice_miss"),
    ("lace", "diamond"):    ("plain_front", "none", "lattice_miss"),
    ("lace", "triangle"):   ("plain_front", "none", "lattice_miss"),
    ("lace", "hexagon"):    ("plain_front", "none", "lattice_miss"),
    ("lace", "polygon"):    ("plain_front", "none", "lattice_miss"),
    ("lace", "heart"):      ("plain_front", "none", "lattice_miss"),
    ("lace", "star"):       ("plain_front", "none", "lattice_miss"),
    ("lace", "chevron"):    ("plain_front", "none", "lattice_miss"),
    ("lace", "zigzag"):     ("plain_front", "none", "lattice_miss"),
    ("lace", "cross"):      ("plain_front", "none", "lattice_miss"),
    ("lace", "mesh"):       ("plain_front", "none", "lattice_miss"),

    # relief / 浮雕
    ("relief", "panel"):    ("plain_front", "none", "staggered_tuck"),
    ("relief", "diamond"):  ("plain_front", "none", "staggered_tuck"),
    ("relief", "triangle"): ("plain_front", "none", "staggered_tuck"),
    ("relief", "hexagon"):  ("plain_front", "none", "staggered_tuck"),
    ("relief", "polygon"):  ("plain_front", "none", "staggered_tuck"),
    ("relief", "circle"):   ("plain_front", "none", "staggered_tuck"),
    ("relief", "heart"):    ("plain_front", "none", "staggered_tuck"),
    ("relief", "star"):     ("plain_front", "none", "staggered_tuck"),
    ("relief", "chevron"):   ("plain_front", "none", "staggered_tuck"),
    ("relief", "zigzag"):    ("plain_front", "none", "staggered_tuck"),
    ("relief", "cross"):     ("plain_front", "none", "staggered_tuck"),
    ("relief", "allover"):  ("plain_front", "none", "staggered_tuck"),

    # honeycomb / 蜂巢
    ("honeycomb", "panel"):     ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "diamond"):   ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "triangle"):  ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "hexagon"):   ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "polygon"):   ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "circle"):    ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "heart"):     ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "star"):      ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "chevron"):    ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "zigzag"):     ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "cross"):      ("plain_front", "none", "honeycomb_tuck"),
    ("honeycomb", "allover"):   ("plain_front", "none", "honeycomb_tuck"),

    # seed / 种子针
    ("seed", "panel"):      ("plain_front", "none", "seed_tuck"),
    ("seed", "diamond"):    ("plain_front", "none", "seed_tuck"),
    ("seed", "triangle"):   ("plain_front", "none", "seed_tuck"),
    ("seed", "hexagon"):    ("plain_front", "none", "seed_tuck"),
    ("seed", "polygon"):    ("plain_front", "none", "seed_tuck"),
    ("seed", "circle"):     ("plain_front", "none", "seed_tuck"),
    ("seed", "heart"):      ("plain_front", "none", "seed_tuck"),
    ("seed", "star"):       ("plain_front", "none", "seed_tuck"),
    ("seed", "chevron"):     ("plain_front", "none", "seed_tuck"),
    ("seed", "zigzag"):      ("plain_front", "none", "seed_tuck"),
    ("seed", "cross"):       ("plain_front", "none", "seed_tuck"),
    ("seed", "allover"):    ("plain_front", "none", "seed_tuck"),
}

_DEFAULT_REALIZATION = ("plain_front", "none", "none")
_GEOMETRIC_SHAPES = {
    "rectangle", "diamond", "circle", "triangle", "hexagon", "polygon",
    "heart", "star", "chevron", "zigzag", "cross",
}
_TEXTURE_EVENT_BY_EFFECT = {
    "wave_tuck": "diagonal_wave",
    "lace": "lattice_miss",
    "relief": "staggered_tuck",
    "honeycomb": "honeycomb_tuck",
    "seed": "seed_tuck",
}

# ============================================================
# Shape 别名映射：处理 LLM 输出的各种非标准 shape 名称
# 第一步：将非标准名称（circle、oval、rect等）转换为标准名称
# ============================================================
_SHAPE_ALIAS_MAP = {
    # 圆形相关别名
    "circle":     "circle",
    "circular":   "circle",
    "round":      "circle",
    "oval":       "circle",
    "ellipse":    "circle",
    
    # 矩形相关别名
    "rect":       "rectangle",
    "rectangle":  "rectangle",
    "box":        "rectangle",
    "square":     "rectangle",
    "quad":       "rectangle",
    
    # 六边形及多边形别名
    "hexagon":    "hexagon",
    "hex":        "hexagon",
    "polygon":    "polygon",
    "triangle":   "triangle",
    "tri":        "triangle",
    "heart":      "heart",
    "star":       "star",
    "chevron":    "chevron",
    "zigzag":     "zigzag",
    "cross":      "cross",
    
    # 注意：stripe 和 column 保持原形态，不进行别名替换，以保持几何语义
    # 这样 (wave_tuck, stripe) 和 (wave_tuck, column) 可以直接在映射表查询
    # "stripes": "stripe",  # 不替换，保持 stripe
    # "striped": "stripe",  # 不替换
    # "bands": "stripe",    # 不替换
    # "horizontal": "stripe",  # 不替换
    # "vertical": "column",  # 不替换
    
    # 其他别名
    "full":       "allover",
    "overall":    "allover",
    "all-over":   "allover",
    # 菱形相关别名（中文 + 英文）
    "diamond":    "diamond",
    "rhombus":    "diamond",
    "菱形":        "diamond",
    "菱格":        "diamond",
    "菱":          "diamond",
    # frame -> rectangle for mask compatibility
    "frame":      "rectangle",
    "border":     "rectangle",
}

# ============================================================
# Shape 标准化表：处理 LLM 输出的非标准 shape
# ============================================================
# 对于每个 visual_effect，定义可用 shape 的优先级列表
# 如果 (effect, shape) 不在映射表，会尝试此列表中的shape
_EFFECT_SHAPE_PRIORITY = {
    "plain":       ["rectangle", "circle", "diamond", "triangle", "hexagon", "polygon", "heart", "star", "chevron", "zigzag", "cross", "panel", "allover", "stripe", "column", "frame"],
    "reverse":     ["rectangle", "circle", "diamond", "triangle", "hexagon", "polygon", "panel"],
    "wave_tuck":   ["wave", "diamond", "triangle", "hexagon", "polygon", "circle", "rectangle", "panel", "allover", "stripe", "column", "chevron", "zigzag", "cross"],
    "cable":       ["circle", "diamond", "star", "heart", "hexagon", "triangle", "polygon", "rectangle", "cross", "chevron", "zigzag", "column", "stripe", "panel"],
    "rib":         ["panel", "stripe", "column"],
    "links":       ["panel", "allover"],
    "lace":        ["panel", "diamond", "triangle", "hexagon", "polygon", "circle", "rectangle", "heart", "star", "mesh", "chevron", "zigzag", "cross"],
    "relief":      ["panel", "allover", "diamond", "triangle", "hexagon", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
    "honeycomb":   ["panel", "allover", "hexagon", "diamond", "triangle", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
    "seed":        ["panel", "allover", "diamond", "triangle", "hexagon", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
}

# ============================================================
# 通用effect fallback：处理未知的effect
# 未知 effect 默认降级为 plain，避免凭空生成特殊动作。
# ============================================================
_KNOWN_EFFECTS = {"plain", "reverse", "wave_tuck", "cable", "rib", "links",
                  "lace", "relief", "honeycomb", "seed"}


class VisualToRealizationConverter:
    """
    把 VisualSpec 转成 RealizationPlan。
    
    v10.2 改进：
    - 完整的shape标准化系统 + 别名映射
    - 参数缓存系统：加速shape/effect重复标准化
    - 增强的启发式纠正规则
    - 为未知effect提供默认行为
    """
    
    def __init__(self):
        """初始化缓存系统"""
        # shape 标准化缓存：(effect, shape) -> normalized_shape
        self._shape_cache = {}
        # effect 标准化缓存：effect -> normalized_effect
        self._effect_cache = {}

    def convert(self, visual_spec: VisualSpec) -> RealizationPlan:
        logger.info("  visual -> realization conversion")

        plan = RealizationPlan(
            layout_type=visual_spec.layout_type,
            regions=[],
        )

        non_ground_count = sum(1 for r in visual_spec.regions if r.layout_role != "ground")

        for vr in visual_spec.regions:
            rr = self._convert_region(vr, non_ground_count=non_ground_count)
            plan.regions.append(rr)
            status = "✓" if rr.event_pattern != "none" else "(no pattern)"
            logger.info(
                f"    [{vr.region_id}] {vr.visual_shape}+{vr.visual_effect} {status} "
                f"-> base={rr.base_field} border={rr.border_style} event={rr.event_pattern}"
            )

        # 预处理：解析 LLM 的 exclude 字段（如 fill 类型引用其他 motif）
        try:
            self._resolve_region_excludes(plan)
        except Exception:
            logger.debug("  region exclude resolution failed, continuing")

        # 后处理：对可能的嵌套关系做对齐（例如 frame/border 外围 + 中心 region）
        try:
            self._align_nested_regions(plan)
        except Exception:
            # 不阻塞主流程
            logger.debug("  nested region alignment failed, continuing")

        # 轮廓决策：在父子层级建立后，统一决定 border_style
        try:
            self._resolve_border_styles(plan)
        except Exception:
            logger.debug("  border style resolution failed, continuing")

        try:
            self._protect_child_textures_from_parent(plan)
        except Exception:
            logger.debug("  parent/child texture protection failed, continuing")

        try:
            self._protect_foreground_from_allover(plan)
        except Exception:
            logger.debug("  foreground protection failed, continuing")

        self._cleanup_alignment_markers(plan)
        return plan

    def _cleanup_alignment_markers(self, plan: RealizationPlan):
        for r in getattr(plan, "regions", []) or []:
            placement = r.placement or {}
            if not isinstance(placement, dict):
                continue
            placement.pop("_user_center", None)
            placement.pop("_user_size", None)
            placement.pop("_requested_size", None)
            placement.pop("_ring_fixed", None)
            for item in placement.get("exclude_masks", []) or []:
                if not isinstance(item, dict):
                    continue
                mask = item.get("placement")
                if isinstance(mask, dict):
                    mask.pop("_user_center", None)
                    mask.pop("_user_size", None)
                    mask.pop("_requested_size", None)
            r.placement = placement

    def _protect_foreground_from_allover(self, plan: RealizationPlan):
        """Keep full-canvas textures from flooding named foreground motifs.

        Foreground = any region that is NOT ground/allover/side_band and has
        a non-full placement.  Border regions are ALWAYS foreground regardless
        of event_pattern, because allover textures (lace mesh, etc.) must not
        appear inside border frames.
        """
        foreground = []
        for r in plan.regions:
            placement = r.placement or {}
            if r.layout_role in {"ground", "allover", "side_band"}:
                continue
            if not placement or placement.get("type") == "full":
                continue
            # Border regions are always foreground — allover textures must not
            # flood into border frames even when the border has no events.
            foreground.append({
                "region_id": r.region_id,
                "placement": dict(placement),
            })

        if not foreground:
            return

        for r in plan.regions:
            placement = r.placement or {}
            if r.layout_role != "allover" and placement.get("type") != "full":
                continue
            existing = list(placement.get("exclude_masks") or [])
            seen = {str(item.get("region_id")) for item in existing if isinstance(item, dict)}
            for item in foreground:
                if item["region_id"] in seen:
                    continue
                existing.append(item)
            placement["exclude_masks"] = existing
            r.placement = placement

    def _protect_child_textures_from_parent(self, plan: RealizationPlan):
        """Prevent parent texture events from flooding a child texture region.

        When both parent and child have different texture event patterns,
        the parent's events can overwrite the child's area, causing the
        child texture to be invisible.  Adding the child as an exclude_mask
        on the parent keeps the parent's events out of the child's space.

        This applies to ANY incompatible parent/child event pair, not just
        the specific lace+wave case.
        """
        regions = getattr(plan, "regions", []) or []
        by_id = {str(r.region_id): r for r in regions}

        for child in regions:
            c_placement = child.placement or {}
            parent_id = c_placement.get("parent_id")
            if not parent_id:
                continue
            parent = by_id.get(str(parent_id))
            if parent is None:
                continue

            child_event = str(getattr(child, "event_pattern", "") or "")
            parent_event = str(getattr(parent, "event_pattern", "") or "")
            if child_event == "none" or parent_event == "none":
                continue
            # Same event pattern: no conflict (both use the same texture).
            if child_event == parent_event:
                continue

            p_placement = parent.placement or {}
            existing = list(p_placement.get("exclude_masks") or [])
            seen = {str(item.get("region_id")) for item in existing if isinstance(item, dict)}
            if str(child.region_id) not in seen:
                existing.append({
                    "region_id": child.region_id,
                    "placement": dict(c_placement),
                })
                p_placement["exclude_masks"] = existing
                parent.placement = p_placement
                logger.info(
                    f"  [{parent.region_id}] excluded child [{child.region_id}] "
                    f"to protect {child_event} from parent {parent_event}"
                )

    def _resolve_region_excludes(self, plan: RealizationPlan):
        """Resolve LLM's ``exclude`` field in region placement.

        Some LLM outputs use ``exclude: [motif_id, ...]`` to express "fill
        everywhere EXCEPT these motifs".  This method converts the exclude
        list into ``inner_exclude`` (geometry) so downstream ring handler,
        event planner, and action builder can consume it.
        """
        region_by_id = {r.region_id: r for r in plan.regions}

        for r in plan.regions:
            placement = r.placement or {}
            exclude_ids = placement.get("exclude")
            if not isinstance(exclude_ids, list) or not exclude_ids:
                continue
            if placement.get("type") in {"ring", "difference"}:
                continue
            if placement.get("inner_exclude"):
                continue

            # Resolve exclude IDs to actual region placements
            resolved = []
            for eid in exclude_ids:
                eid = str(eid).strip()
                target = region_by_id.get(eid)
                if target and target.placement and target.region_id != r.region_id:
                    resolved.append((eid, target))
            if not resolved:
                continue

            # Find the largest non-border excluded region → inner_exclude
            inner_target = None
            inner_size = -1
            for eid, target in resolved:
                t_placement = target.placement or {}
                t_size = int(t_placement.get("size", 0))
                t_role = str(getattr(target, "layout_role", "")).lower()
                if t_role not in {"border", "frame"} and t_size > inner_size:
                    inner_target = target
                    inner_size = t_size

            # Find frame/border for outer size reference
            frame_target = None
            for eid, target in resolved:
                t_role = str(getattr(target, "layout_role", "")).lower()
                if t_role in {"border", "frame"}:
                    frame_target = target
                    break

            if inner_target is not None:
                inner_p = dict(inner_target.placement or {})
                # Convert to ring type with inner_exclude
                placement["type"] = "ring"
                placement["inner_exclude"] = {
                    "center": list(inner_p.get("center", [20, 20])),
                    "size": int(inner_p.get("size", 0)),
                    "shape": str(inner_p.get("shape", inner_p.get(
                        "mask_shape", "circle"))).lower(),
                }
                # Expand size to cover area between inner and frame
                if frame_target:
                    frame_size = int(
                        (frame_target.placement or {}).get("size", 20))
                    frame_bt = int(
                        getattr(frame_target, "border_thickness",
                            (frame_target.placement or {}).get("thickness",
                                (frame_target.placement or {}).get("border_thickness", 2))) or 2)
                    expanded = frame_size + frame_bt * 2 + 2
                else:
                    expanded = int(inner_p.get("size", 0)) + 4
                placement["size"] = max(
                    int(placement.get("size", 0)), expanded)
                # Clear parent_id pointing to excluded motif
                pid = placement.get("parent_id")
                if pid and any(str(eid) == str(pid) for eid, _ in resolved):
                    placement.pop("parent_id", None)
                    placement.pop("clip_to_parent", None)
                # Set exclude_masks for foreground exclusion
                masks = []
                for eid, target in resolved:
                    masks.append({
                        "region_id": target.region_id,
                        "placement": dict(target.placement or {}),
                    })
                placement["exclude_masks"] = masks
                placement["_ring_fixed"] = True
                r.placement = placement
                logger.info(
                    f"  [{r.region_id}] resolved exclude → "
                    f"ring(inner={inner_target.region_id} "
                    f"size={inner_p.get('size', 0)})")

    def _align_nested_regions(self, plan: RealizationPlan):
        """
        Align child regions to their parent mask.

        Examples:
        - "菱形图案，内部波浪花纹" should produce a diamond parent and a
          wave_tuck child clipped to the diamond mask, not a rectangular wave
          patch sitting on top of the diamond.
        - Explicit `placement.parent_id` / `clip_to_parent` takes precedence.
          Without that, a single border region is treated as the parent for
          other centered regions.
        """
        border_roles = {"border", "frame"}
        borders = [r for r in plan.regions if r.layout_role in border_roles]
        region_by_id = {r.region_id: r for r in plan.regions}
        if not borders and not any((r.placement or {}).get("parent_id") for r in plan.regions):
            return

        for r in plan.regions:
            if r.layout_role in {"ground", "allover", "side_band", "corner", "transition", "surround"}:
                continue

            placement = r.placement or {}
            parent = None
            parent_id = placement.get("parent_id")
            inferred_parent = False
            if parent_id:
                parent = region_by_id.get(str(parent_id))
            elif borders and r.region_id != borders[0].region_id and r.layout_role != "border":
                # 始终挂到边框下（由后续 size 调整代码处理尺寸钳制）。
                # 跳过嵌套会导致子区域无父级裁剪，圆形/纹理凸出到边框外。
                parent = borders[0]
                inferred_parent = True

            if parent is None or parent.region_id == r.region_id:
                continue

            o_placement = parent.placement or {}
            try:
                o_center = o_placement.get("center", [20, 20])
                o_cr, o_cc = int(o_center[0]), int(o_center[1])
            except Exception:
                o_cr, o_cc = 20, 20
            try:
                o_size = int(o_placement.get("size", 12))
            except Exception:
                o_size = 12

            parent_border_thickness = int(getattr(parent, "border_thickness", 1) or 1)
            parent_role = str(getattr(parent, "layout_role", "") or "").lower()
            # 外框是独立视觉层，不应被中心几何/纹理顶到边上。给自动挂到
            # 外框下的中心层额外留一圈安全间距，避免仿真和色码图里看起来
            # 像中心图案把矩形框“顶破”。
            frame_clearance = 2 if inferred_parent and parent_role in {"border", "frame"} else 0
            inner_max = max(1, o_size - parent_border_thickness - frame_clearance)
            user_center = bool(placement.get("_user_center"))
            user_size = bool(placement.get("_user_size"))
            clip_to_parent = bool(placement.get("clip_to_parent", parent_id or inferred_parent))

            explicit = False
            center = placement.get("center") if user_center else None
            if isinstance(center, (list, tuple)) and len(center) >= 2:
                try:
                    cr, cc = int(center[0]), int(center[1])
                    explicit = True
                except Exception:
                    explicit = False

            if explicit and (abs(cr - o_cr) > o_size or abs(cc - o_cc) > o_size):
                # Child center outside parent bbox — try to find a better parent
                # whose bbox actually contains the child, instead of blindly
                # resetting the center to the (wrong) parent's center.
                best_parent = None
                best_dist = float('inf')
                for candidate in borders:
                    if candidate.region_id == r.region_id:
                        continue
                    cp = candidate.placement or {}
                    try:
                        ccr, ccc = int((cp.get("center", [20, 20]))[0]), int((cp.get("center", [20, 20]))[1])
                        cs = int(cp.get("size", 12))
                    except Exception:
                        continue
                    if abs(cr - ccr) <= cs and abs(cc - ccc) <= cs:
                        d = abs(cr - ccr) + abs(cc - ccc)
                        if d < best_dist:
                            best_dist = d
                            best_parent = candidate
                if best_parent is not None and best_parent.region_id != (parent.region_id if parent else None):
                    parent = best_parent
                    parent_id = parent.region_id
                    placement["parent_id"] = parent_id
                    inferred_parent = False
                    o_placement = parent.placement or {}
                    try:
                        o_center = o_placement.get("center", [20, 20])
                        o_cr, o_cc = int(o_center[0]), int(o_center[1])
                    except Exception:
                        o_cr, o_cc = 20, 20
                    try:
                        o_size = int(o_placement.get("size", 12))
                    except Exception:
                        o_size = 12
                    parent_border_thickness = int(getattr(parent, "border_thickness", 1) or 1)
                    parent_role = str(getattr(parent, "layout_role", "") or "").lower()
                    frame_clearance = 2 if inferred_parent and parent_role in {"border", "frame"} else 0
                    inner_max = max(1, o_size - parent_border_thickness - frame_clearance)
                    clip_to_parent = bool(placement.get("clip_to_parent", True))
                    logger.warning(
                        f"  [{r.region_id}] re-parented to {parent.region_id} "
                        f"(child center [{cr},{cc}] was outside old parent bbox)"
                    )
                else:
                    placement["center"] = [o_cr, o_cc]
                    cr, cc = o_cr, o_cc
            elif not explicit:
                # No user-specified center → default to parent's center
                placement["center"] = [o_cr, o_cc]
                cr, cc = o_cr, o_cc
            elif inferred_parent or parent_id:
                radius_hint = int(placement.get("size", 1))
                # 正确几何约束：子区域边缘不超过父区域边缘
                # |offset| + radius <= parent_inner → |offset| <= parent_inner - radius
                parent_inner = max(1, o_size - parent_border_thickness)
                max_row_offset = max(0, parent_inner - radius_hint)
                max_col_offset = max(0, parent_inner - radius_hint)
                cr = max(o_cr - max_row_offset, min(o_cr + max_row_offset, cr))
                cc = max(o_cc - max_col_offset, min(o_cc + max_col_offset, cc))
                placement["center"] = [cr, cc]
            # Child texture inside a container should fill the container's
            # drawable area.  A smaller LLM-provided size often makes the
            # texture appear as a tiny center patch instead of an interior fill.
            child_shape = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
            safe_size = inner_max
            if explicit:
                try:
                    cr2, cc2 = int(placement["center"][0]), int(placement["center"][1])
                    safe_size = min(inner_max, max(1, o_size - parent_border_thickness - abs(cr2 - o_cr)), max(1, o_size - parent_border_thickness - abs(cc2 - o_cc)))
                except Exception:
                    safe_size = inner_max

            # ring / difference 类型：保留外圈/内圈尺寸关系，不能缩小到 inner_exclude 之下
            _placement_type = str(placement.get("type", "")).lower()
            _inner_excl = placement.get("inner_exclude")
            if _placement_type in {"ring", "difference"} and isinstance(_inner_excl, dict) and _inner_excl:
                self._adjust_ring_size(r, plan, placement, _inner_excl, safe_size)
            else:
                # All non-ring regions: cap size at safe_size.
                # For event-pattern regions this preserves the LLM-requested size
                # (no expansion to safe_size), while still preventing overflow.
                placement["size"] = min(int(placement.get("size", safe_size)), safe_size)

            outer_shape = str(o_placement.get("mask_shape", o_placement.get("shape", ""))).lower()
            if clip_to_parent and outer_shape:
                if outer_shape in {"frame", "border", "box"}:
                    outer_shape = "rectangle"
                if child_shape in {"", "panel", "allover", "wave", "mesh", "stripe", "column", "frame", "border"}:
                    placement["mask_shape"] = outer_shape
                    placement["shape"] = outer_shape
                placement["clip_to_parent"] = True
                placement["parent_id"] = parent.region_id
                placement.setdefault("parent_clip_margin", 0)
                if isinstance(r.event_params, dict):
                    # Parent clipping already keeps child events off the outer
                    # outline.  Do not shrink the child event field again, or
                    # interior textures collapse toward the center.
                    r.event_params["edge_fade"] = min(int(r.event_params.get("edge_fade", 0) or 0), 0)
                    r.event_params.setdefault("density_profile", "uniform")
                    # border_guard: keep events away from the parent border.
                    # Apply to ALL event patterns, not just diagonal_wave,
                    # to prevent cable/honeycomb/etc. events from appearing
                    # on or near the parent's border outline.
                    # Keep the guard small (1) so that small child regions
                    # (e.g. size=10) still have enough area for textures.
                    r.event_params.setdefault("border_guard", 1)

            placement.pop("_user_center", None)
            placement.pop("_user_size", None)
            placement.pop("_requested_size", None)
            r.placement = placement

    def _adjust_ring_size(
        self, region, plan: RealizationPlan,
        placement: dict, inner_excl: dict, safe_size: int,
    ):
        """Adjust ring/difference region size and inner exclusion.

        Ring regions have an outer boundary and an inner exclusion zone.
        This method:
        1. Clamps outer size to safe_size (preserving ring integrity)
        2. Proportionally scales inner exclusion when outer is clamped
        3. Matches inner exclusion to sibling region size to avoid gaps
        """
        ie_size = int(inner_excl.get("size", 0))
        cur_size = int(placement.get("size", 0))
        orig_outer = cur_size
        orig_inner = ie_size
        ring_fixed = bool(placement.get("_ring_fixed"))

        # Clamp outer to safe_size
        if cur_size > safe_size:
            cur_size = max(safe_size, orig_inner + 4) if ring_fixed else safe_size
            placement["size"] = cur_size

        # Proportionally scale inner
        if orig_outer > 0 and cur_size < orig_outer and orig_inner > 0:
            ie_size = max(2, int(orig_inner * cur_size / orig_outer))

        # Sibling-aware adjustment: match inner_exclude to sibling size
        min_gap = 4
        if ring_fixed and placement.get("parent_id"):
            p_id = placement["parent_id"]
            rc = placement.get("center", [20, 20])
            try:
                rc0, rc1 = int(rc[0]), int(rc[1])
            except Exception:
                rc0, rc1 = 20, 20
            for sib in plan.regions:
                if sib.region_id == region.region_id:
                    continue
                sib_p = sib.placement or {}
                if sib_p.get("parent_id") != p_id:
                    continue
                if str(sib_p.get("type", "")).lower() in {"ring", "difference"}:
                    continue
                sib_size = int(sib_p.get("size", 0))
                sc = sib_p.get("center", [20, 20])
                try:
                    sc0, sc1 = int(sc[0]), int(sc[1])
                except Exception:
                    sc0, sc1 = 20, 20
                if sib_size > 0 and sc0 == rc0 and sc1 == rc1:
                    target_ie = max(ie_size, sib_size)
                    if target_ie != ie_size and target_ie < cur_size - min_gap:
                        logger.info(
                            f"  [{region.region_id}] ring inner_exclude "
                            f"{ie_size} -> {target_ie} to match "
                            f"sibling {sib.region_id}(size={sib_size})"
                        )
                        ie_size = target_ie
                    break

        # Inner must be strictly smaller than outer
        if ie_size >= cur_size:
            ie_size = max(2, cur_size - min_gap)
        inner_excl["size"] = ie_size
        placement.pop("_ring_fixed", None)

    def _resolve_border_styles(self, plan: RealizationPlan):
        """统一的轮廓决策后处理。

        在 _align_nested_regions 建立完整父子层级后，统一决定每个区域的
        border_style。替代之前散落在查找表、_convert_region 内的分散逻辑。

        规则：
        1. ground/allover/side_band → 不加轮廓
        2. border 角色 → 保持已有值
        3. 查找表或用户已设置 border_style != "none" → 保持
        4. standalone 几何形状 (无父级) → 加 back_loop_outline
        5. child (有父级) + 无纹理 (plain/reverse) → 不加轮廓
        6. child (有父级) + 有纹理 (honeycomb/lace/cable等) → 加 back_loop_outline
           （让几何形状边界可见，如"大圆内蜂巢"中的圆形轮廓）
        """
        for r in getattr(plan, "regions", []) or []:
            if r.layout_role in {"ground", "allover", "side_band"}:
                continue
            if r.layout_role == "border":
                continue

            placement = r.placement or {}
            shape = str(placement.get("mask_shape", placement.get("shape", "")) or "").lower()

            # ── 尊重 LLM 语义：不覆盖 LLM 决定的边框 ──────────────────────
            # LLM 决定了什么形状、什么边框，代码不应基于硬编码逻辑覆盖
            # 直接检查查找表是否已设置边框
            current_border = str(getattr(r, "border_style", "none") or "none").lower()
            if current_border != "none":
                # 查找表或 LLM 已设置了轮廓，保持
                continue

            # Geometric shapes get a border outline, UNLESS they are ring regions
            # (have inner_exclude). Ring regions are the space between two circles;
            # their boundaries are already defined by the inner/outer circle borders.
            # Adding a border here creates a visible "third circle" artifact.
            # 根据 motif_type 判断是否是几何形状，而不是 shape 字段
            _motif_type = str(placement.get("motif_type", "") or "").lower()
            _is_geometric_motif = _motif_type in _GEOMETRIC_SHAPES
            
            if _is_geometric_motif and shape in _GEOMETRIC_SHAPES:
                _has_inner_excl = isinstance(placement.get("inner_exclude"), dict) and placement.get("inner_exclude")
                if _has_inner_excl:
                    logger.info(
                        f"  [{r.region_id}] _resolve_border_styles: "
                        f"ring region (has inner_exclude) -> no border"
                    )
                    continue
                r.border_style = "back_loop_outline"
                logger.info(
                    f"  [{r.region_id}] _resolve_border_styles: "
                    f"geometric {shape} (motif_type={_motif_type}) with event={r.event_pattern} -> back_loop_outline"
                )
                continue

            # Non-geometric regions with texture events: no border — texture
            # events themselves define the visual, extra border would compete.
            if r.event_pattern != "none":
                continue

            # standalone 无事件几何形状：加轮廓（仅限几何形状的 motif）
            if _is_geometric_motif:
                r.border_style = "back_loop_outline"
                logger.info(
                    f"  [{r.region_id}] _resolve_border_styles: "
                    f"standalone {shape} (motif_type={_motif_type}) -> back_loop_outline"
                )

    def _normalize_shape(self, effect: str, shape: str) -> str:
        """
        只做同义词归一，不做几何降级。

        用户指定的形状是硬语义：diamond/triangle/hexagon/circle 等
        不能因为某个 effect 暂无专用映射就被改成 rectangle/panel。
        
        使用缓存加速重复调用。
        
        Args:
            effect: visual_effect (wave_tuck, cable等)
            shape: 原始shape (circle, square等)
        
        Returns:
            别名归一后的 shape。
        """
        # 检查缓存
        cache_key = (effect, shape)
        if cache_key in self._shape_cache:
            return self._shape_cache[cache_key]
        
        normalized_shape = shape
        
        # 步骤1：别名解析（circle/oval -> circle, rect/square -> rectangle 等）
        shape_lower = str(shape or "").lower().strip()
        if shape_lower in _SHAPE_ALIAS_MAP:
            alias_target = _SHAPE_ALIAS_MAP[shape_lower]
            if alias_target != shape_lower:
                logger.warning(
                    f"Shape alias: ({effect}, {shape}) -> ({effect}, {alias_target})"
                )
            normalized_shape = alias_target
        
        self._shape_cache[cache_key] = normalized_shape  # 缓存
        return normalized_shape

    def _fallback_realization_for_shape(self, effect: str, shape: str):
        """Preserve geometry when an effect/shape pair has no explicit mapping."""
        if shape in _GEOMETRIC_SHAPES:
            event_pattern = _TEXTURE_EVENT_BY_EFFECT.get(effect, "none")
            # 根据 effect 确定正确的 base_field，避免 fallback 到 plain_front 导致纹理丢失
            base = "rib" if effect == "rib" else "plain_front"
            logger.warning(
                f"Unsupported effect/shape pair ({effect}, {shape}); "
                f"preserving shape with base={base}, event={event_pattern}"
            )
            return (base, "back_loop_outline", event_pattern)

        if shape in {"stripe", "column"} and effect in {"wave_tuck", "rib"}:
            # stripe + rib → 竖条纹不需要额外事件；column + rib → 列状罗纹不需要额外事件
            # stripe/column + wave_tuck → 对角波绞
            ep = "diagonal_wave" if effect == "wave_tuck" else "none"
            return ("plain_front" if effect == "wave_tuck" else "rib", "none", ep)

        if shape in {"allover", "panel"}:
            event_pattern = _TEXTURE_EVENT_BY_EFFECT.get(effect, "none")
            base = "rib" if effect == "rib" else "plain_front"
            return (base, "none", event_pattern)

        return _DEFAULT_REALIZATION

    def _lookup_realization(self, effect: str, shape: str):
        key = (effect, shape)
        if key in _EFFECT_TO_REALIZATION:
            return _EFFECT_TO_REALIZATION[key]
        return self._fallback_realization_for_shape(effect, shape)

    def _normalize_effect(self, effect: str) -> str:
        """
        验证 effect 是否被支持，如果不支持则降级为 plain。
        使用缓存加速重复调用。
        """
        if effect in self._effect_cache:
            return self._effect_cache[effect]

        # 检查是否有该effect的任何映射
        any_mapping_exists = any(k[0] == effect for k in _EFFECT_TO_REALIZATION.keys())

        if any_mapping_exists:
            self._effect_cache[effect] = effect
            return effect

        # 未知 effect 降级为 plain
        if effect != "plain":
            logger.warning(
                f"Unknown effect '{effect}', using fallback 'plain' instead"
            )
        self._effect_cache[effect] = "plain"
        return "plain"

    def _resolve_side_band_side(self, vr: VisualRegion) -> str:
        return resolve_side_band_side(
            vr.placement or {}, vr.region_id, 40,  # grid_size=40 is the standard
        )

    def _prepare_region_placement(self, vr: VisualRegion, non_ground_count: int) -> dict:
        """Prepare placement dict: defaults, mask_shape extraction, side_band fallback.
    
        Returns the placement dict with temporary flags (_user_center, etc.).
        """
        placement = dict(vr.placement or {})
        has_user_center = "center" in placement
        has_user_size = "size" in placement
        requested_size = placement.get("size") if has_user_size else None
        if vr.layout_role not in {"ground", "allover"} and placement.get("type") != "full":
            placement.setdefault("center", [20, 20])
            placement.setdefault("size", 12)
    
        # Save original shape as mask info for downstream geometric clipping
        try:
            original_shape_lower = str(vr.visual_shape or "").strip().lower()
        except Exception:
            original_shape_lower = ""
        placement_shape_lower = str(placement.get("mask_shape", placement.get("shape", "")) or "").strip().lower()
        if original_shape_lower in {"panel", "allover"} and placement_shape_lower in _GEOMETRIC_SHAPES:
            original_shape_lower = placement_shape_lower
            vr.visual_shape = placement_shape_lower
        if original_shape_lower in {
            "circle", "oval", "round", "circular", "ellipse",
            "diamond", "rhombus", "triangle", "tri", "hexagon", "hex",
            "square", "rect", "rectangle", "polygon", "heart", "star",
            "chevron", "zigzag", "cross",
        }:
            placement.setdefault("mask_shape", original_shape_lower)
            placement.setdefault("shape", original_shape_lower)
        placement["_user_center"] = has_user_center
        placement["_user_size"] = has_user_size
        if requested_size is not None:
            placement["_requested_size"] = requested_size
    
        # side_band without side hint → fallback to center
        if vr.layout_role == "side_band":
            side_raw = str(placement.get("side", "")).strip().lower()
            rid = str(vr.region_id or "").lower()
            has_side_hint = side_raw in {"left", "right"} or any(
                k in rid for k in ["left", "right", "\u5de6", "\u53f3", "l_", "r_", "_l", "_r"]
            )
            if non_ground_count == 1 and not has_side_hint:
                logger.warning(
                    f"  [{vr.region_id}] single-shape side_band without side hint -> fallback to center"
                )
                vr.layout_role = "center"
                placement.pop("side", None)
    
        return placement
    
    def _normalize_region_semantics(self, vr: VisualRegion):
        """Normalize effect/shape and lookup realization mapping.
    
        Returns (base_field, border_style, event_pattern).
        """
        # Pre-normalize semantic correction (must run before shape normalization)
        original_shape = str(vr.visual_shape or "").lower()
        original_effect = str(vr.visual_effect or "").lower()
        region_id_lower = str(vr.region_id or "").lower()
        if original_effect in {"plain", "reverse"}:
            if original_shape == "wave" or "wave" in region_id_lower:
                logger.warning(
                    f"  [{vr.region_id}] pre-normalize correction: "
                    f"({vr.visual_effect}, {vr.visual_shape}) -> (wave_tuck, wave)"
                )
                vr.visual_effect = "wave_tuck"
                vr.visual_shape = "wave"
            elif original_shape in {"mesh", "lace", "eyelet"} or any(
                k in region_id_lower for k in ["mesh", "lace", "eyelet", "\u9542\u7a7a", "\u7f51\u773c"]
            ):
                logger.warning(
                    f"  [{vr.region_id}] pre-normalize correction: "
                    f"({vr.visual_effect}, {vr.visual_shape}) -> (lace, mesh)"
                )
                vr.visual_effect = "lace"
                vr.visual_shape = "mesh"
    
        # Effect normalization
        normalized_effect = self._normalize_effect(vr.visual_effect)
        if normalized_effect != vr.visual_effect:
            logger.debug(f"  [{vr.region_id}] normalized effect: {vr.visual_effect} -> {normalized_effect}")
            vr.visual_effect = normalized_effect
    
        # Shape normalization
        normalized_shape = self._normalize_shape(vr.visual_effect, vr.visual_shape)
        if normalized_shape != vr.visual_shape:
            logger.debug(f"  [{vr.region_id}] normalized shape: {vr.visual_shape} -> {normalized_shape}")
            vr.visual_shape = normalized_shape
    
        # Lookup realization table
        base_field, border_style, event_pattern = self._lookup_realization(
            vr.visual_effect, vr.visual_shape
        )
    
        # Heuristic correction for unmatched patterns
        if event_pattern == "none" and (vr.visual_effect, vr.visual_shape) not in _EFFECT_TO_REALIZATION:
            if vr.visual_shape == "wave" and vr.visual_effect in ["plain", "reverse"]:
                logger.warning(
                    f"  [{vr.region_id}] correcting: "
                    f"({vr.visual_effect}, wave) -> (wave_tuck, wave)"
                )
                vr.visual_effect = "wave_tuck"
                base_field, border_style, event_pattern = self._lookup_realization(
                    vr.visual_effect, vr.visual_shape
                )
    
        return base_field, border_style, event_pattern
    
    def _compute_default_event_params(
        self, vr: VisualRegion, placement: dict,
        event_params: dict, event_pattern: str,
        border_style: str, border_thickness: int,
    ) -> dict:
        """Compute default event parameters based on effect type and shape.
    
        Returns the updated event_params dict.
        """
        effect = vr.visual_effect
        size = placement.get("size", 12) if isinstance(placement, dict) else 12
    
        # wave_tuck: period defaults based on size
        if effect == "wave_tuck" and not event_params.get("period_y"):
            size = placement.get("size", 12) if isinstance(placement, dict) else 12
            if size <= 8:
                event_params["period_y"] = 2
                event_params["period_x"] = 3
            elif size <= 15:
                event_params["period_y"] = 3
                event_params["period_x"] = 4
            else:
                event_params["period_y"] = 4
                event_params["period_x"] = 5
            if "edge_fade" not in event_params:
                try:
                    shape_hint = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
                except Exception:
                    shape_hint = ""
                if shape_hint in {"circle", "circular", "round", "oval", "ellipse"}:
                    event_params["edge_fade"] = 1
                    # 小圆形使用 uniform 密度，避免 center_dense 过度裁剪
                    _size = int(placement.get("size", 0))
                    if _size >= 12:
                        event_params.setdefault("density_profile", "center_dense")
                    else:
                        event_params.setdefault("density_profile", "uniform")
                elif shape_hint in {"rectangle", "rect", "frame", "border", "panel", "square", "box"}:
                    event_params["edge_fade"] = 2
                    event_params.setdefault("wave_direction", "diag_pos")
                    event_params.setdefault("density_profile", "uniform")
                else:
                    event_params["edge_fade"] = 1
            logger.info(
                f"  [{vr.region_id}] wave_tuck: added default params "
                f"period_y={event_params['period_y']}, period_x={event_params['period_x']} (size={size})"
            )
    
        # Shape-based aesthetic defaults
        try:
            shape_hint = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
        except Exception:
            shape_hint = ""
    
        # Polygons: fill interior uniformly (avoid radial gradient shrinking)
        if shape_hint in {"diamond", "rhombus", "hexagon", "hex", "triangle"}:
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("edge_fade", 0)
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("vertex_neighbor_threshold", 2)
            # border_guard for ALL textured geometric shapes.
            # _resolve_border_styles guarantees geometric shapes always get
            # back_loop_outline, so border_guard must be set regardless of
            # the current border_style value (which is "none" at this point).
            if event_pattern != "none":
                event_params.setdefault("border_guard", max(1, border_thickness))
    
        # Rectangle/panel: uniform with stronger edge fade
        if shape_hint in {"rectangle", "rect", "frame", "border", "panel", "square", "box"}:
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("edge_fade", max(int(event_params.get("edge_fade", 0) or 0), 2))
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
    
        # Stripe: horizontal consistency
        if shape_hint in {"stripe", "stripes"}:
            event_params.setdefault("wave_direction", "horizontal")
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("direction_consistency", True)
    
        # Column: vertical consistency
        if shape_hint == "column":
            event_params.setdefault("wave_direction", "vertical")
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("direction_consistency", True)

        # General: any geometric shape with border + texture events needs
        # border_guard to keep events off the border outline.
        # (Polygon-specific guard above already covers diamond/hex/triangle.)
        if shape_hint in {"circle", "circular", "round", "oval", "ellipse",
                          "heart", "star", "chevron", "zigzag", "cross"}:
            if event_pattern != "none":
                event_params.setdefault("border_guard", max(1, border_thickness))
    
        # Effect-specific defaults
        if effect == "relief" and not event_params.get("period_x"):
            event_params["period_x"] = 4
            event_params["period_y"] = 4
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] relief: added default params")
    
        if effect == "honeycomb" and not event_params.get("period_x"):
            event_params["period_x"] = 3
            event_params["period_y"] = 3
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] honeycomb: added default params")
    
        if effect == "lace" and not event_params.get("period_x"):
            event_params["period_x"] = 4
            event_params["period_y"] = 4
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] lace: added default params")

        # Size-based period adjustment for periodic textures on small regions.
        # Prevents overly dense patterns that look "tattered".
        # Target: ~3-4 events per row across the effective region width.
        if event_pattern in {"lattice_miss", "honeycomb_tuck", "staggered_tuck",
                             "seed_tuck", "seed_stitch"}:
            _px = int(event_params.get("period_x", 4))
            _py = int(event_params.get("period_y", 4))
            _eff_size = max(2, int(size) - 2 * max(1, border_thickness))
            _target_px = max(3, _eff_size // 4)
            if _px < _target_px:
                event_params["period_x"] = _target_px
            if _py < _target_px:
                event_params["period_y"] = _target_px
            if event_params.get("period_x") != _px or event_params.get("period_y") != _py:
                logger.info(
                    f"  [{vr.region_id}] {effect}: period adjusted "
                    f"({_px},{_py}) -> ({event_params['period_x']},{event_params['period_y']}) "
                    f"for size={size}"
                )
    
        return event_params
    
    def _convert_region(self, vr: VisualRegion, non_ground_count: int = 1) -> RealizationRegion:
        """Convert a single VisualRegion to a RealizationRegion.
    
        Pipeline:
        1. _prepare_region_placement: placement defaults, mask_shape, side_band fallback
        2. _normalize_region_semantics: effect/shape normalization + realization lookup
        3. Compute border_thickness and event_params defaults
        4. Apply role-based adjustments (ground/border/side_band)
        5. Apply user overrides and assemble final RealizationRegion
        """
        # Phase 1: Placement preparation
        placement = self._prepare_region_placement(vr, non_ground_count)
        vr.placement = placement
    
        # Phase 2: Semantic normalization + realization lookup
        base_field, border_style, event_pattern = self._normalize_region_semantics(vr)
    
        # Phase 3: Default parameters
        border_thickness = 1
        params = dict(vr.params or {})
        event_params = dict(params)
    
        try:
            border_thickness = int(
                params.get(
                    "border_thickness",
                    params.get("thickness",
                        placement.get("border_thickness",
                            placement.get("thickness", border_thickness))),
                )
            )
            border_thickness = max(1, min(3, border_thickness))
        except Exception:
            border_thickness = 1

        # ── 环形区域 border_thickness 自适应 ──────────────────────
        # 如果区域有 inner_exclude（环形），边框厚度不能超过环宽的一半
        _ie = placement.get("inner_exclude")
        if isinstance(_ie, dict) and _ie:
            try:
                _outer_size = int(placement.get("size", 12))
                _inner_size = int(_ie.get("size", 0))
                _ring_width = max(1, (_outer_size - _inner_size) // 2)
                # 边框最多占环宽的 1/3，留 2/3 给纹理
                border_thickness = min(border_thickness, max(1, _ring_width // 3))
            except Exception:
                pass
    
        event_params = self._compute_default_event_params(
            vr, placement, event_params, event_pattern, border_style, border_thickness,
        )
    
        # Transition policy
        transition_policy = "none" if vr.visual_effect == "cable" else "local_only"
    
        # Phase 4: Role-based adjustments
        if vr.layout_role == "ground":
            event_pattern = "none"
            border_style = "none"
            transition_policy = "none"
    
        if vr.layout_role == "border":
            # border 尺寸上限：确保 frame + border 不超出画布安全区域
            _canvas_size = 40  # 标准画布尺寸
            if border_thickness < 1:
                border_thickness = 1
            _border_max = max(_canvas_size // 2 - border_thickness - 1, 8)
            try:
                placement["size"] = min(int(placement.get("size", 20)), _border_max)
            except Exception:
                placement["size"] = 20
            placement.setdefault("center", [20, 20])
    
            try:
                original_shape_lower = str(vr.visual_shape or "").strip().lower()
            except Exception:
                original_shape_lower = ""
            if original_shape_lower in {"frame", "border", "rect", "rectangle", "square", "box"}:
                border_style = "back_loop_outline"
                placement["shape"] = "rectangle"
                placement["mask_shape"] = "rectangle"
            elif original_shape_lower in _GEOMETRIC_SHAPES:
                # Geometric shapes (triangle, circle, diamond, etc.) used as
                # border-role motifs also need a visible outline.
                if border_style == "none":
                    border_style = "back_loop_outline"
    
        if vr.layout_role == "side_band":
            if not isinstance(vr.placement, dict):
                vr.placement = {}
            vr.placement["side"] = self._resolve_side_band_side(vr)
    
            width = None
            if isinstance(vr.placement, dict):
                width = vr.placement.get("width") or vr.placement.get("size")
            if width is None:
                width = params.get("width") or params.get("size") or 6
            try:
                width = int(width)
            except Exception:
                width = 6
    
            if width <= 2:
                event_pattern = "none"
            else:
                event_params.setdefault("local_only", True)
                if vr.visual_effect == "wave_tuck":
                    event_params.setdefault("period_x", 3 if width <= 6 else 4)
                    event_params.setdefault("period_y", max(2, width // 3))
                logger.info(
                    f"  [{vr.region_id}] side_band allowed events "
                    f"(side={vr.placement.get('side')}, width={width}), adjusted params: {event_params}"
                )
    
        # Phase 5: User overrides + final assembly
        if "base_field" in params:
            base_field = str(params.get("base_field") or base_field)
        if "border_style" in params:
            _bs = str(params.get("border_style") or "").strip().lower()
            if _bs:  # 包括 "none" 在内的任何非空值都尊重
                border_style = _bs
        if "event_pattern" in params:
            event_pattern = str(params.get("event_pattern") or event_pattern)
        if "transition_policy" in params:
            transition_policy = str(params.get("transition_policy") or transition_policy)
    
        # Wave direction from user params
        if vr.visual_effect == "wave_tuck":
            wave_direction = params.get("wave_direction", params.get("direction"))
            if wave_direction:
                event_params["wave_direction"] = str(wave_direction).lower()
            density_profile = params.get("density_profile")
            if density_profile:
                event_params["density_profile"] = str(density_profile).lower()
    
        # Ensure shape/mask_shape consistency in placement
        if isinstance(placement, dict) and placement.get("type") != "full":
            placement.setdefault("shape", vr.visual_shape)
            placement.setdefault("mask_shape", placement.get("mask_shape", vr.visual_shape))
        vr.placement = placement
    
        return RealizationRegion(
            region_id=vr.region_id,
            layout_role=vr.layout_role,
            placement=dict(placement or {}),
            base_field=base_field,
            border_style=border_style,
            border_thickness=border_thickness,
            event_pattern=event_pattern,
            event_params=event_params,
            transition_policy=transition_policy,
            allow_refinement=vr.allow_refinement,
        )
    