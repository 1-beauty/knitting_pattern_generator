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
    # 闭合几何里的 cable 不能用孤立 transfer 点冒充。没有连续骨架实现时只保留轮廓。
    ("cable", "diamond"):   ("plain_front", "back_loop_outline", "none"),
    ("cable", "circle"):    ("plain_front", "back_loop_outline", "none"),
    ("cable", "panel"):     ("plain_front", "back_loop_outline", "none"),
    ("cable", "column"):    ("plain_front", "back_loop_outline", "column_xfer"),
    ("cable", "stripe"):    ("plain_front", "back_loop_outline", "column_xfer"),  # 横条也可用列麻花

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
    ("rib", "stripe"):      ("rib", "none", "diagonal_wave"),  # stripe 形状的 rib 生成对角波纹
    ("rib", "column"):      ("rib", "none", "diagonal_wave"),  # column 形状的 rib 生成对角波纹

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
    # Closed geometric honeycomb marks are easy to misread as broken wave
    # cells on the color map. Keep the shape clean; allover honeycomb still
    # uses the tuck texture below.
    ("honeycomb", "hexagon"):   ("plain_front", "none", "none"),
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
    "cable":       ["circle", "diamond", "column", "stripe", "panel"],
    "rib":         ["panel", "stripe", "column"],
    "links":       ["panel", "allover"],
    "lace":        ["panel", "diamond", "triangle", "hexagon", "polygon", "circle", "rectangle", "heart", "star", "mesh", "chevron", "zigzag", "cross"],
    "relief":      ["panel", "allover", "diamond", "triangle", "hexagon", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
    "honeycomb":   ["panel", "allover", "hexagon", "diamond", "triangle", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
    "seed":        ["panel", "allover", "diamond", "triangle", "hexagon", "polygon", "circle", "heart", "star", "chevron", "zigzag", "cross"],
}

# ============================================================
# 通用effect fallback：处理未知的effect
# ============================================================
_EFFECT_FALLBACK = {
    "plain":     "plain",
    "wave_tuck": "wave_tuck",    # 保持不变
    "cable":     "cable",        # 保持不变
    "rib":       "rib",          # 保持不变
    "relief":    "relief",       # 保持不变
    "lace":      "lace",         # 保持不变
    "honeycomb": "honeycomb",    # 保持不变
    # 未知 effect 默认降级为 plain，避免凭空生成特殊动作。
}


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
        """Keep full-canvas textures from flooding named foreground motifs."""
        foreground = []
        for r in plan.regions:
            placement = r.placement or {}
            if r.layout_role in {"ground", "allover", "side_band"}:
                continue
            if not placement or placement.get("type") == "full":
                continue
            if r.layout_role == "border" and str(getattr(r, "event_pattern", "") or "") == "none":
                continue
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
        """Prevent parent texture events from filling a child texture region.

        Example: "圆形镂空结构，内部加入细密波浪" should keep lace outside
        the inner wave area.  Otherwise the parent's lattice/miss events can
        occupy the same mask and the final map reads as holes instead of waves.
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

            # Strong rule for the current failure mode: lace parent + wave
            # child must not overlap at the event layer.
            if not (parent_event == "lattice_miss" and child_event == "diagonal_wave"):
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
            if r.layout_role in {"ground", "allover", "side_band"}:
                continue

            placement = r.placement or {}
            parent = None
            parent_id = placement.get("parent_id")
            inferred_parent = False
            if parent_id:
                parent = region_by_id.get(str(parent_id))
            elif borders and r.region_id != borders[0].region_id and r.layout_role != "border":
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

            if not explicit or abs(cr - o_cr) > o_size or abs(cc - o_cc) > o_size:
                placement["center"] = [o_cr, o_cc]
                cr, cc = o_cr, o_cc
            elif inferred_parent or parent_id:
                radius_hint = int(placement.get("size", 1))
                max_row_offset = max(0, inner_max - radius_hint)
                max_col_offset = max(0, inner_max - radius_hint)
                cr = max(o_cr - max_row_offset, min(o_cr + max_row_offset, cr))
                cc = max(o_cc - max_col_offset, min(o_cc + max_col_offset, cc))
                placement["center"] = [cr, cc]
            # Child texture inside a container should fill the container's
            # drawable area.  A smaller LLM-provided size often makes the
            # texture appear as a tiny center patch instead of an interior fill.
            child_shape = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
            child_has_own_outline = r.border_style != "none" and child_shape not in {
                "", "panel", "allover", "wave", "mesh", "stripe", "column", "frame", "border"
            }
            requested_size = placement.get("_requested_size")
            safe_size = inner_max
            if explicit:
                try:
                    cr2, cc2 = int(placement["center"][0]), int(placement["center"][1])
                    safe_size = min(inner_max, max(1, o_size - parent_border_thickness - abs(cr2 - o_cr)), max(1, o_size - parent_border_thickness - abs(cc2 - o_cc)))
                except Exception:
                    safe_size = inner_max

            if user_size and child_shape in {"circle", "circular", "round", "oval", "ellipse"}:
                placement["size"] = min(int(placement.get("size", safe_size)), safe_size)
            elif child_has_own_outline and requested_size is not None:
                try:
                    placement["size"] = min(int(requested_size), safe_size)
                except Exception:
                    placement["size"] = min(int(placement.get("size", safe_size)), safe_size)
            elif r.event_pattern != "none" and not (user_size and child_has_own_outline):
                placement["size"] = safe_size
            elif not user_size:
                placement["size"] = min(safe_size, int(placement.get("size", safe_size)))
            else:
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
                    if r.event_pattern == "diagonal_wave":
                        if r.border_style != "none":
                            r.event_params.setdefault(
                                "border_guard",
                                max(1, int(getattr(r, "border_thickness", 1) or 1)),
                            )

            placement.pop("_user_center", None)
            placement.pop("_user_size", None)
            placement.pop("_requested_size", None)
            r.placement = placement

    def _resolve_border_styles(self, plan: RealizationPlan):
        """统一的轮廓决策后处理。

        在 _align_nested_regions 建立完整父子层级后，统一决定每个区域的
        border_style。替代之前散落在查找表、_convert_region 内的分散逻辑。

        规则：
        1. ground/allover/side_band → 不加轮廓
        2. border 角色 → 保持已有值
        3. 查找表或用户已设置 border_style != "none" → 保持
        4. standalone 几何形状 (无父级) → 加 back_loop_outline
        5. child (有父级) → 不加轮廓（纹理本身定义形状边界）
        """
        for r in getattr(plan, "regions", []) or []:
            if r.layout_role in {"ground", "allover", "side_band"}:
                continue
            if r.layout_role == "border":
                continue

            current_border = str(getattr(r, "border_style", "none") or "none").lower()
            if current_border != "none":
                # 查找表或用户已设置了轮廓（plain/reverse/cable/显式覆盖），保持
                continue

            # 检查是否是几何形状
            placement = r.placement or {}
            shape = str(placement.get("mask_shape", placement.get("shape", "")) or "").lower()
            if shape not in _GEOMETRIC_SHAPES:
                continue

            # 检查是否是 child (parent_id/clip_to_parent 已由 _align_nested_regions 设置)
            is_child = bool(placement.get("parent_id") or placement.get("clip_to_parent"))
            if is_child:
                # child 不加轮廓：纹理本身定义形状边界，
                # 父级 border 已提供外部轮廓
                continue

            # standalone 几何形状：加轮廓
            r.border_style = "back_loop_outline"
            logger.info(
                f"  [{r.region_id}] _resolve_border_styles: "
                f"standalone {shape} -> back_loop_outline"
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
            logger.warning(
                f"Unsupported effect/shape pair ({effect}, {shape}); "
                f"preserving shape with generic event={event_pattern}"
            )
            return ("plain_front", "back_loop_outline", event_pattern)

        if shape in {"stripe", "column"} and effect in {"wave_tuck", "rib"}:
            return ("plain_front" if effect == "wave_tuck" else "rib", "none", "diagonal_wave")

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
        验证 effect 是否被支持，如果不支持则使用默认effect。
        使用缓存加速重复调用。
        
        Args:
            effect: visual_effect 值
        
        Returns:
            支持的effect值，或默认的effect
        """
        # 检查缓存
        if effect in self._effect_cache:
            return self._effect_cache[effect]
        
        # 检查是否有该effect的任何映射
        any_mapping_exists = any(k[0] == effect for k in _EFFECT_TO_REALIZATION.keys())
        
        if any_mapping_exists:
            self._effect_cache[effect] = effect  # 缓存
            return effect  # 支持这个effect
        
        # 如果effect未知，使用fallback
        fallback_effect = _EFFECT_FALLBACK.get(effect, "plain")
        if fallback_effect != effect:
            logger.warning(
                f"Unknown effect '{effect}', using fallback '{fallback_effect}' instead"
            )
        self._effect_cache[effect] = fallback_effect  # 缓存
        return fallback_effect

    def _resolve_side_band_side(self, vr: VisualRegion) -> str:
        placement = vr.placement or {}
        side_raw = str(placement.get("side", "")).strip().lower()
        if side_raw in {"left", "right"}:
            return side_raw

        rid = str(vr.region_id or "").lower()
        if any(k in rid for k in ["right", "r_", "_r", "右"]):
            return "right"
        if any(k in rid for k in ["left", "l_", "_l", "左"]):
            return "left"

        center = placement.get("center")
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            try:
                return "right" if int(center[1]) >= 20 else "left"
            except Exception:
                pass

        return "left"

    def _convert_region(self, vr: VisualRegion, non_ground_count: int = 1) -> RealizationRegion:
        # 默认居中策略：所有非ground区域若未显式给出center，默认落在色码图中心。
        placement = dict(vr.placement or {})
        has_user_center = "center" in placement
        has_user_size = "size" in placement
        requested_size = placement.get("size") if has_user_size else None
        if vr.layout_role not in {"ground", "allover"} and placement.get("type") != "full":
            placement.setdefault("center", [20, 20])
            placement.setdefault("size", 12)

        # 保存原始shape作为mask信息，便于后续planner进行几何裁剪（例如圆形掩码）
        try:
            original_shape_lower = str(vr.visual_shape or "").strip().lower()
        except Exception:
            original_shape_lower = ""
        placement_shape_lower = str(placement.get("mask_shape", placement.get("shape", "")) or "").strip().lower()
        if original_shape_lower in {"panel", "allover"} and placement_shape_lower in _GEOMETRIC_SHAPES:
            original_shape_lower = placement_shape_lower
            vr.visual_shape = placement_shape_lower
        # 仅在原始shape具有几何语义时保存mask_shape
        if original_shape_lower in {
            "circle", "oval", "round", "circular", "ellipse",
            "diamond", "rhombus", "triangle", "tri", "hexagon", "hex",
            "square", "rect", "rectangle", "polygon", "heart", "star",
            "chevron", "zigzag", "cross",
        }:
            # 保存为 mask_shape 以供通用掩码检测使用，同时将原始几何语义写入 "shape" 以兼容旧逻辑
            placement.setdefault("mask_shape", original_shape_lower)
            placement.setdefault("shape", original_shape_lower)
        placement["_user_center"] = has_user_center
        placement["_user_size"] = has_user_size
        if requested_size is not None:
            placement["_requested_size"] = requested_size

        # 若只有一个主形状却被解析为 side_band 且无左右信息，则回退为 center。
        if vr.layout_role == "side_band":
            side_raw = str(placement.get("side", "")).strip().lower()
            rid = str(vr.region_id or "").lower()
            has_side_hint = side_raw in {"left", "right"} or any(
                k in rid for k in ["left", "right", "左", "右", "l_", "r_", "_l", "_r"]
            )
            if non_ground_count == 1 and not has_side_hint:
                logger.warning(
                    f"  [{vr.region_id}] single-shape side_band without side hint -> fallback to center"
                )
                vr.layout_role = "center"
                placement.pop("side", None)

        vr.placement = placement

        # 0) 语义纠正前置：必须在shape标准化之前执行
        # 否则 (plain, wave) 会先被改写成 (plain, panel)，丢失“波浪”语义。
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
                k in region_id_lower for k in ["mesh", "lace", "eyelet", "镂空", "网眼"]
            ):
                logger.warning(
                    f"  [{vr.region_id}] pre-normalize correction: "
                    f"({vr.visual_effect}, {vr.visual_shape}) -> (lace, mesh)"
                )
                vr.visual_effect = "lace"
                vr.visual_shape = "mesh"

        # 第一步：Effect 标准化（处理未知的effect类型）
        normalized_effect = self._normalize_effect(vr.visual_effect)
        if normalized_effect != vr.visual_effect:
            logger.debug(f"  [{vr.region_id}] normalized effect: {vr.visual_effect} -> {normalized_effect}")
            vr.visual_effect = normalized_effect
        
        # 第二步：Shape 标准化（处理 circle, square 等 LLM 输出的非标准 shape）
        normalized_shape = self._normalize_shape(vr.visual_effect, vr.visual_shape)
        original_shape = vr.visual_shape
        if normalized_shape != original_shape:
            logger.debug(f"  [{vr.region_id}] normalized shape: {original_shape} -> {normalized_shape}")
            vr.visual_shape = normalized_shape
        
        # 第三步：检查映射表中是否存在
        base_field, border_style, event_pattern = self._lookup_realization(
            vr.visual_effect, vr.visual_shape
        )
        
        # 第四步：如果是默认值（=无匹配），尝试启发式纠正
        if event_pattern == "none" and (vr.visual_effect, vr.visual_shape) not in _EFFECT_TO_REALIZATION:
            corrected = False
            
            # 纠正 1：如果声称是 wave 形状但效果是 plain/reverse，应该是 wave_tuck
            if vr.visual_shape == "wave" and vr.visual_effect in ["plain", "reverse"]:
                logger.warning(
                    f"  [{vr.region_id}] correcting: "
                    f"({vr.visual_effect}, wave) -> (wave_tuck, wave)"
                )
                vr.visual_effect = "wave_tuck"
                # shape 保持 wave，映射表已支持 (wave_tuck, wave)
                corrected = True
            
            if corrected:
                base_field, border_style, event_pattern = self._lookup_realization(
                    vr.visual_effect, vr.visual_shape
                )

        border_thickness = 1
        params = dict(vr.params or {})
        event_params = dict(params)

        # 边框厚度可控：支持从 params 或 placement 读取
        try:
            border_thickness = int(
                params.get(
                    "border_thickness",
                    params.get("thickness", placement.get("border_thickness", border_thickness)),
                )
            )
            border_thickness = max(1, min(3, border_thickness))
        except Exception:
            border_thickness = 1
        
        # 为缺失的 event_params 添加合理的默认值（根据 effect 类型）
        if vr.visual_effect == "wave_tuck" and not event_params.get("period_y"):
            # 根据 placement size 推荐参数
            size = 12  # 默认假设
            if isinstance(vr.placement, dict):
                size = vr.placement.get("size", 12)
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
                    event_params.setdefault("density_profile", "center_dense")
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

        # 针对一些 shape 提供审美默认参数，增强普适性
        try:
            shape_hint = str(placement.get("mask_shape", placement.get("shape", ""))).lower()
        except Exception:
            shape_hint = ""

        # 多边形类（diamond/hexagon/triangle）默认应铺满内部。此前径向渐变
        # 和边缘退缩会把纹理压成中心小块，导致用户看到“缺块/镂空”。
        if shape_hint in {"diamond", "rhombus", "hexagon", "hex", "triangle"}:
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("edge_fade", 0)
            # 参数热加载：多边形的邻域阈值可调
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("vertex_neighbor_threshold", 2)  # 顶点缓和阈值
            if event_pattern == "diagonal_wave":
                if border_style != "none":
                    event_params.setdefault("border_guard", max(1, border_thickness))

        # 矩形/panel 保持 uniform，但更强的边缘淡化
        if shape_hint in {"rectangle", "rect", "frame", "border", "panel", "square", "box"}:
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("edge_fade", max(int(event_params.get("edge_fade", 0) or 0), 2))
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)

        # 条带与柱状优先方向一致性
        if shape_hint in {"stripe", "stripes"}:
            event_params.setdefault("wave_direction", "horizontal")
            event_params.setdefault("density_profile", "uniform")
            # 参数热加载：条带的孤立特殊动作回退阈值
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("direction_consistency", True)  # 保证水平方向一致性

        if shape_hint == "column":
            event_params.setdefault("wave_direction", "vertical")
            event_params.setdefault("density_profile", "uniform")
            event_params.setdefault("smoothing_threshold", 1)
            event_params.setdefault("vertex_smoothing", False)
            event_params.setdefault("direction_consistency", True)  # 保证竖直方向一致性
        
        if vr.visual_effect == "relief" and not event_params.get("period_x"):
            event_params["period_x"] = 4
            event_params["period_y"] = 4
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] relief: added default params")
        
        if vr.visual_effect == "honeycomb" and not event_params.get("period_x"):
            event_params["period_x"] = 3
            event_params["period_y"] = 3
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] honeycomb: added default params")
        
        if vr.visual_effect == "lace" and not event_params.get("period_x"):
            event_params["period_x"] = 4
            event_params["period_y"] = 4
            event_params["stagger"] = True
            logger.info(f"  [{vr.region_id}] lace: added default params")

        # 默认：
        # - cable 不自动插 transition
        # - 其他纹理类（wave/lace/relief等）允许 local_only
        if vr.visual_effect == "cable":
            transition_policy = "none"
        else:
            transition_policy = "local_only"

        # ground 区域永远不设事件
        if vr.layout_role == "ground":
            event_pattern = "none"
            border_style = "none"
            transition_policy = "none"

        # 边框角色优先保证外轮廓可见，不让标准化把 frame/rectangle 吃掉
        if vr.layout_role == "border":
            if original_shape_lower in {"frame", "border", "rect", "rectangle", "square", "box"}:
                border_style = "back_loop_outline"
                # 尊重 pattern plan 中指定的 border_thickness，不强制覆盖
                # 原代码 border_thickness = max(border_thickness, 2) 会强制最小 2
                # 但现在 pattern plan 层已经通过 _clamp_border_thickness 控制厚度
                # 这里只需确保不为 0 即可
                if border_thickness < 1:
                    border_thickness = 1
                placement["center"] = [20, 20]
                # 边框尺寸安全限制：40x40 画布上，边框 size 最大 17
                # 这确保边框不会太接近画布边缘（至少留 3 行边距）
                # 原代码 min(size, 17) 是必要的，不能移除
                try:
                    placement["size"] = min(int(placement.get("size", 17)), 17)
                except Exception:
                    placement["size"] = 17
                placement["shape"] = "rectangle"
                placement["mask_shape"] = "rectangle"

        # 轮廓决策已移至 _resolve_border_styles 后处理，此处不再做隐式轮廓设置
        # （旧代码为 textured/plain circle 加 back_loop_outline，现已由统一后处理负责）

        # side_band 区域特殊处理
        # 不再无条件禁止 side_band 事件。根据 placement/params 中的 width/size 决定是否允许事件，
        # 并在窄列上自动调整周期参数以避免事件跨列扩散。
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

            # 如果列非常窄（<=2），无法生成有意义事件
            if width <= 2:
                event_pattern = "none"
            else:
                # 允许事件，但限制其影响范围
                # 标记 local_only 以便下游planner/solver可选地限制传播
                event_params.setdefault("local_only", True)

                # 对 wave_tuck 在窄列上使用更小周期
                if vr.visual_effect == "wave_tuck":
                    event_params.setdefault("period_x", 3 if width <= 6 else 4)
                    event_params.setdefault("period_y", max(2, width // 3))

                # 对 relief/honeycomb 等也可根据宽度微调（保留可扩展点）
                logger.info(
                    f"  [{vr.region_id}] side_band allowed events "
                    f"(side={vr.placement.get('side')}, width={width}), adjusted params: {event_params}"
                )

        # 从 params 里读用户覆盖（防止 None）
        if "base_field" in params:
            base_field = str(params.get("base_field") or base_field)
        if "border_style" in params:
            border_style = str(params.get("border_style") or border_style)
        if "event_pattern" in params:
            event_pattern = str(params.get("event_pattern") or event_pattern)
        if "transition_policy" in params:
            transition_policy = str(params.get("transition_policy") or transition_policy)

        # 轮廓决策已统一在 _resolve_border_styles 后处理中，不再在 _convert_region 内做 child texture 判断
        # （旧代码因 parent_id 尚未设置，is_child_texture 永远为 False，是死代码）

        # 波浪方向与密度参数（可由上游显式传入）
        if vr.visual_effect == "wave_tuck":
            wave_direction = params.get("wave_direction", params.get("direction"))
            if wave_direction:
                event_params["wave_direction"] = str(wave_direction).lower()
            density_profile = params.get("density_profile")
            if density_profile:
                event_params["density_profile"] = str(density_profile).lower()

        # 确保 placement 中 shape/mask_shape 与标准化结果一致，便于下游统一使用
        try:
            if isinstance(placement, dict):
                # Full-canvas allover regions must remain unmasked.  Giving
                # them mask_shape=allover makes the planner clip them to a
                # small fallback square.
                if placement.get("type") != "full":
                    placement.setdefault("shape", vr.visual_shape)
                    placement.setdefault("mask_shape", placement.get("mask_shape", vr.visual_shape))
                vr.placement = placement
        except Exception:
            pass

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
