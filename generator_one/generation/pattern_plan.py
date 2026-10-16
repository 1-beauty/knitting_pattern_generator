"""Editable pattern planning layer for Stage I.

This layer sits above VisualSpec. It keeps user-facing motif intent as a
structured, editable plan, then renders that plan into the existing VisualSpec
pipeline. The goal is to preserve small user edits such as "make the wave
bigger" or "add eyelets" instead of remapping the whole prompt to the same
coarse module each time.
"""

from __future__ import annotations

import copy
import json
import random
import re
from dataclasses import asdict, dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from generation.visual_types import VisualRegion, VisualSpec
from utils.logger import logger


SHAPE_ALIASES = {
    "波浪": "wave",
    "水波": "wave",
    "起伏": "wave",
    "菱形": "diamond",
    "菱格": "diamond",
    "钻石": "diamond",
    "镂空": "mesh",
    "网眼": "mesh",
    "孔洞": "mesh",
    "蕾丝": "mesh",
    "边框": "frame",
    "花边": "frame",
    "条纹": "stripe",
    "横条": "stripe",
    "竖条": "column",
    "柱状": "column",
    "圆": "circle",
    "圆形": "circle",
    "三角": "triangle",
    "三角形": "triangle",
    "六边形": "hexagon",
    "六角形": "hexagon",
    "多边形": "polygon",
    "心形": "heart",
    "爱心": "heart",
    "星形": "star",
    "星星": "star",
    "人字": "chevron",
    "V形": "chevron",
    "v形": "chevron",
    "锯齿": "zigzag",
    "折线": "zigzag",
    "十字": "cross",
    "diamond": "diamond",
    "rhombus": "diamond",
    "wave": "wave",
    "lace": "mesh",
    "eyelet": "mesh",
    "mesh": "mesh",
    "frame": "frame",
    "border": "frame",
    "stripe": "stripe",
    "column": "column",
    "circle": "circle",
    "triangle": "triangle",
    "tri": "triangle",
    "hexagon": "hexagon",
    "hex": "hexagon",
    "polygon": "polygon",
    "heart": "heart",
    "star": "star",
    "chevron": "chevron",
    "zigzag": "zigzag",
    "cross": "cross",
}

EFFECT_ALIASES = {
    "麻花": "cable",
    "绞花": "cable",
    "扭针": "cable",
    "波浪": "wave_tuck",
    "吊目": "wave_tuck",
    "集圈": "wave_tuck",
    "镂空": "lace",
    "网眼": "lace",
    "孔洞": "lace",
    "蕾丝": "lace",
    "罗纹": "rib",
    "双床": "rib",
    "蜂巢": "honeycomb",
    "浮雕": "relief",
    "凸起": "relief",
    "种子": "seed",
    "cable": "cable",
    "twist": "cable",
    "tuck": "wave_tuck",
    "wave": "wave_tuck",
    "lace": "lace",
    "eyelet": "lace",
    "mesh": "lace",
    "rib": "rib",
    "honeycomb": "honeycomb",
    "relief": "relief",
    "seed": "seed",
}

RELATIVE_SCALE = {
    "一点": 1.15,
    "稍微": 1.15,
    "小幅": 1.15,
    "更": 1.3,
    "明显": 1.4,
    "大幅": 1.6,
    "非常": 1.7,
}


@dataclass
class PatternMotif:
    motif_id: str
    motif_type: str
    effect: str = "plain"
    region: Dict[str, Any] = dc_field(default_factory=dict)
    params: Dict[str, Any] = dc_field(default_factory=dict)
    role: str = "center"
    symmetry: str = "none"
    allow_refinement: bool = True
    parent_id: Optional[str] = None


@dataclass
class PatternPlan:
    schema_version: str = "pattern_plan/v1"
    canvas: Dict[str, int] = dc_field(default_factory=lambda: {"width": 40, "height": 40})
    layout_type: str = "centered"
    motifs: List[PatternMotif] = dc_field(default_factory=list)
    history: List[Dict[str, Any]] = dc_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternPlan":
        motifs = []
        for item in data.get("motifs", []) or []:
            motifs.append(PatternMotif(
                motif_id=str(item.get("motif_id", item.get("id", f"motif_{len(motifs)+1}"))),
                motif_type=str(item.get("motif_type", item.get("type", "panel"))),
                effect=str(item.get("effect", "plain")),
                region=dict(item.get("region", {}) or {}),
                params=dict(item.get("params", {}) or {}),
                role=str(item.get("role", item.get("layout_role", "center"))),
                symmetry=str(item.get("symmetry", "none")),
                allow_refinement=bool(item.get("allow_refinement", True)),
                parent_id=item.get("parent_id"),
            ))
        return cls(
            schema_version=str(data.get("schema_version", "pattern_plan/v1")),
            canvas=dict(data.get("canvas", {"width": 40, "height": 40}) or {}),
            layout_type=str(data.get("layout_type", "centered")),
            motifs=motifs,
            history=list(data.get("history", []) or []),
        )

    def get_motif(self, motif_id: str) -> Optional[PatternMotif]:
        for motif in self.motifs:
            if motif.motif_id == motif_id:
                return motif
        return None


class PatternPlanEngine:
    def parse_or_fallback(self, llm_output: str, user_input: str, current_plan: Optional[PatternPlan] = None) -> PatternPlan:
        data = self._extract_json(llm_output)
        if data:
            plan = self._data_to_plan(data, current_plan=current_plan)
            if plan is not None:
                # 当 LLM 输出全量 motifs 时，说明 LLM 已经理解了编辑意图并
                # 直接给出了调整后的值，不应再叠加启发式调整（否则 border
                # thickness 会被二次 +1）。只有当 LLM 输出 operation 格式
                # （增量修改）时才运行 _apply_structured_edit。
                is_full_plan = "motifs" in data or "regions" in data
                if (
                    current_plan is not None
                    and self._looks_like_edit(user_input)
                    and not is_full_plan
                ):
                    self._apply_structured_edit(plan, user_input)
                self._repair_plan_from_text(plan, user_input)
                plan.history.append({"input": user_input, "source": "llm"})
                return self.validate(plan, user_input=user_input)

        logger.warning("PatternPlan parse failed; using heuristic planner")
        return self.from_prompt(user_input, current_plan=current_plan)

    def from_prompt(self, user_input: str, current_plan: Optional[PatternPlan] = None) -> PatternPlan:
        text = user_input.lower()
        if current_plan is not None and self._looks_like_edit(user_input):
            plan = copy.deepcopy(current_plan)
            self._apply_heuristic_edit(plan, user_input)
            plan.history.append({"input": user_input, "source": "heuristic_edit"})
            return self.validate(plan, user_input=user_input)

        if any(k in user_input for k in ["随机", "随便", "生成一些", "灵感"]) or "random" in text:
            hints = self._parse_prompt_hints(user_input)
            plan = self.random_plan(prompt_hints=hints)
            plan.history.append({"input": user_input, "source": "random"})
            return self.validate(plan, user_input=user_input)

        motifs = self._motifs_from_text(user_input)
        plan = PatternPlan(layout_type=self._infer_layout(user_input), motifs=motifs)
        self._repair_plan_from_text(plan, user_input)
        plan.history.append({"input": user_input, "source": "heuristic_new"})
        return self.validate(plan, user_input=user_input)

    @staticmethod
    def _parse_prompt_hints(user_input: str) -> Dict[str, bool]:
        """从用户 prompt 中解析结构偏好关键词，用于偏置随机生成。"""
        text = user_input
        hints: Dict[str, bool] = {}
        if any(k in text for k in ["几何", "主体", "轮廓", "形状"]):
            hints["need_geometry"] = True
        if any(k in text for k in ["边框", "外框", "框"]):
            hints["need_border"] = True
        if any(k in text for k in ["纹理", "吊目", "网眼", "蜂巢", "麻花", "浮雕"]):
            hints["need_texture"] = True
        if any(k in text for k in ["侧边", "边带", "两侧", "左右"]):
            hints["need_side_bands"] = True
        if any(k in text for k in ["稀疏", "稀疏"]):
            hints["sparse"] = True
        if any(k in text for k in ["密集", "密实", "密"]):
            hints["dense"] = True
        return hints

    def random_plan(self, seed: Optional[int] = None, prompt_hints: Optional[Dict[str, bool]] = None) -> PatternPlan:
        """Generate a random pattern plan.

        Args:
            seed: Optional random seed for reproducibility.
            prompt_hints: Optional dict parsed from user prompt with keys:
                - need_geometry: user mentioned 几何主体/几何形状/几何/主体
                - need_border: user mentioned 边框/外框
                - need_texture: user mentioned 纹理/吊目/网眼/蜂巢
                - need_side_bands: user mentioned 侧边/边带/两侧
                - sparse: user mentioned 稀疏/稀疏
                - dense: user mentioned 密集/密
        """
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        hints = prompt_hints or {}

        # ── 根据 prompt 关键词偏置布局选择 ──
        if hints.get("need_geometry"):
            # 用户要求几何主体，强制 centered/framed（不允许 allover 覆盖）
            layout = rng.choice(["centered", "centered", "framed", "framed", "side_bands"])
        elif hints.get("need_border"):
            # 用户要求边框，强制 framed
            layout = rng.choice(["framed", "framed", "framed", "centered"])
        elif hints.get("need_side_bands"):
            layout = rng.choice(["side_bands", "side_bands", "side_bands", "centered", "framed"])
        else:
            layout = rng.choice([
                "centered", "centered",
                "framed", "framed",
                "allover_repeat", "allover_repeat",
                "side_bands",
                "side_bands",
            ])

        # ── 大幅扩充候选池，避免默认偏好 ──
        center_pool = [
            # 几何形状 × 纹理效果 组合
            ("circle", "wave_tuck"),
            ("circle", "lace"),
            ("circle", "relief"),
            ("circle", "honeycomb"),
            ("circle", "cable"),
            ("circle", "seed"),
            ("diamond", "cable"),
            ("diamond", "wave_tuck"),
            ("diamond", "lace"),
            ("diamond", "relief"),
            ("diamond", "honeycomb"),
            ("diamond", "seed"),
            ("hexagon", "honeycomb"),
            ("hexagon", "lace"),
            ("hexagon", "relief"),
            ("hexagon", "wave_tuck"),
            ("hexagon", "cable"),
            ("triangle", "lace"),
            ("triangle", "wave_tuck"),
            ("triangle", "relief"),
            ("triangle", "honeycomb"),
            ("polygon", "relief"),
            ("polygon", "wave_tuck"),
            ("polygon", "lace"),
            ("polygon", "honeycomb"),
            ("heart", "seed"),
            ("heart", "lace"),
            ("heart", "wave_tuck"),
            ("heart", "relief"),
            ("star", "relief"),
            ("star", "lace"),
            ("star", "wave_tuck"),
            ("star", "honeycomb"),
            ("chevron", "wave_tuck"),
            ("chevron", "rib"),
            ("chevron", "lace"),
            ("zigzag", "wave_tuck"),
            ("zigzag", "rib"),
            ("zigzag", "lace"),
            ("cross", "relief"),
            ("cross", "lace"),
            ("cross", "wave_tuck"),
            ("wave", "wave_tuck"),
            ("wave", "lace"),
            ("wave", "rib"),
            ("stripe", "rib"),
            ("stripe", "wave_tuck"),
            ("stripe", "lace"),
            ("stripe", "links"),
            ("column", "rib"),
            ("column", "wave_tuck"),
            ("column", "cable"),
            ("column", "lace"),
            ("panel", "wave_tuck"),
            ("panel", "honeycomb"),
            ("panel", "lace"),
            ("panel", "relief"),
            ("panel", "cable"),
            ("panel", "seed"),
            ("panel", "links"),
        ]
        border_pool = [
            ("frame", "reverse"),
            ("frame", "plain"),
            ("frame", "rib"),
            ("frame", "lace"),
            ("stripe", "rib"),
            ("stripe", "wave_tuck"),
            ("stripe", "links"),
            ("column", "rib"),
            ("column", "wave_tuck"),
            ("diamond", "reverse"),
            ("diamond", "rib"),
            ("circle", "reverse"),
            ("circle", "lace"),
        ]
        background_pool = [
            ("panel", "plain"),
            ("panel", "lace"),
            ("panel", "wave_tuck"),
            ("panel", "honeycomb"),
            ("panel", "relief"),
            ("panel", "seed"),
            ("panel", "rib"),
            ("panel", "links"),
            ("panel", "reverse"),
        ]

        # ── 根据 prompt 偏置候选池 ──
        if hints.get("need_geometry"):
            # 用户要求几何主体，只保留几何形状（排除 panel/stripe/column/wave）
            _geo_shapes = {"circle", "diamond", "hexagon", "triangle", "polygon",
                           "heart", "star", "chevron", "zigzag", "cross"}
            geo_pool = [(s, e) for s, e in center_pool if s in _geo_shapes]
            motif_type, effect = rng.choice(geo_pool)
        else:
            motif_type, effect = rng.choice(center_pool)

        size = rng.choice([8, 10, 12, 14, 16, 18, 20])
        # 中心位置加入轻微随机偏移，避免所有图案都严格居中
        center_r = rng.choice([18, 19, 20, 20, 20, 21, 22])
        center_c = rng.choice([18, 19, 20, 20, 20, 21, 22])
        # 稀疏/密集偏好影响参数
        base_params = self._default_params(effect, user_input="random")
        if hints.get("sparse"):
            base_params["period_x"] = rng.choice([6, 7, 8, 10])
            base_params["period_y"] = rng.choice([5, 6, 7, 8])
        elif hints.get("dense"):
            base_params["period_x"] = rng.choice([2, 3, 3])
            base_params["period_y"] = rng.choice([2, 2, 3])

        motifs = [
            PatternMotif(
                motif_id="main",
                motif_type=motif_type,
                effect=effect,
                region={"center": [center_r, center_c], "size": size},
                params=base_params,
                role="allover" if motif_type in {"stripe", "column"} else "center",
                symmetry=rng.choice(["none", "none", "mirror_lr", "mirror_ud"]),
            )
        ]

        if layout == "framed":
            border_type, border_effect = rng.choice(border_pool)
            border_shape = "rectangle"
            if border_type == "diamond":
                border_shape = "diamond"
            elif border_type == "circle":
                border_shape = "circle"
            # 边框尺寸限制：最大 17，确保在 40x40 画布上有足够边距
            border_size = min(17, size + rng.choice([2, 3, 4, 5]))
            motifs.append(PatternMotif(
                motif_id="border",
                motif_type=border_type,
                effect=border_effect,
                region={
                    "center": [20, 20],
                    "size": border_size,
                    "shape": border_shape,
                },
                params={"border_thickness": rng.choice([1, 1, 2])},
                role="border",
                allow_refinement=False,
            ))
        elif layout == "allover_repeat":
            bg_type, bg_effect = rng.choice(background_pool)
            motifs[0].motif_type = bg_type
            motifs[0].effect = bg_effect
            motifs[0].region = {"type": "full"}
            motifs[0].role = "allover"
            motifs[0].params = self._default_params(bg_effect, user_input="random")
        elif layout == "side_bands":
            band_effect = rng.choice(["rib", "wave_tuck", "lace", "links", "reverse"])
            band_width = rng.choice([3, 4, 5, 6])
            motifs = [
                PatternMotif(
                    motif_id="left_band",
                    motif_type="stripe",
                    effect=band_effect,
                    region={"x_range": [0, band_width], "y_range": [0, 40]},
                    params={"period_x": band_width, "period_y": 4},
                    role="side_band",
                ),
                PatternMotif(
                    motif_id="main",
                    motif_type=motif_type,
                    effect=effect,
                    region={"center": [20, 20], "size": size},
                    params=self._default_params(effect, user_input="random"),
                    role="center",
                    symmetry=rng.choice(["none", "mirror_lr", "mirror_ud"]),
                ),
                PatternMotif(
                    motif_id="right_band",
                    motif_type="stripe",
                    effect=band_effect,
                    region={"x_range": [40 - band_width, 40], "y_range": [0, 40]},
                    params={"period_x": band_width, "period_y": 4},
                    role="side_band",
                ),
            ]
        else:
            # centered — 有概率加背景纹理
            if rng.random() < 0.35:
                bg_type, bg_effect = rng.choice(background_pool)
                motifs.append(PatternMotif(
                    motif_id="bg_texture",
                    motif_type=bg_type,
                    effect=bg_effect,
                    region={"type": "full"},
                    params=self._default_params(bg_effect, user_input="random"),
                    role="allover",
                    allow_refinement=True,
                ))

        return PatternPlan(layout_type=layout, motifs=motifs)

    def from_visual_spec_flat(self, spec: VisualSpec) -> PatternPlan:
        """Create a flat PatternPlan directly from VisualSpec (no hierarchy).

        Used as baseline: each VisualSpec region becomes an independent motif
        without parent-child relationships or refinement flags.
        """
        motifs = []
        for region in spec.regions:
            if region.layout_role == "ground":
                continue
            motif_type = SHAPE_ALIASES.get(region.visual_shape, region.visual_shape)
            effect = EFFECT_ALIASES.get(region.visual_effect, region.visual_effect)
            motifs.append(PatternMotif(
                motif_id=region.region_id,
                motif_type=motif_type,
                effect=effect,
                region=dict(region.placement),
                params=dict(region.params),
                role=region.layout_role,
                symmetry="none",
                allow_refinement=False,
                parent_id=None,
            ))
        return PatternPlan(
            layout_type=spec.layout_type,
            motifs=motifs,
            history=[{"source": "flat_visual_spec_baseline"}],
        )

    def _preprocess_ring_motifs(self, plan: PatternPlan) -> None:
        """修正 ring motif 的 parent_id，确保指向外框而非内圈 motif。

        LLM 经常将 fill_mesh 的 parent_id 设为内圈圆，但 ring 应该
        挂在外部容器（border/frame）下。 不修正会导致 _align_nested_regions
        把 ring 的 outer 钳到内圈 motif 的 safe_size，使 ring 宽度归零。

        注意：不在此处修改 size / outer_size，因为这些可能残留了上次运行
        的脏值（如 outer_size=38）。下游 ring handler + _align_nested_regions
        会通过 _ring_fixed 标记做正确的比例缩放。
        """
        border_motifs = [
            m for m in plan.motifs
            if m.role in {"border", "frame"}
            or m.motif_type in {"frame"}
        ]
        for motif in plan.motifs:
            if motif.region.get("type") != "ring":
                continue
            pid = motif.parent_id
            # parent_id 指向非边框 motif → 重新挂到边框
            if pid and border_motifs:
                parent_candidate = next(
                    (m for m in plan.motifs if m.motif_id == pid), None
                )
                if parent_candidate and parent_candidate.role not in {"border", "frame"}:
                    frame = border_motifs[0]
                    if frame.motif_id != motif.motif_id:
                        logger.warning(
                            f"  [{motif.motif_id}] ring parent_id '{pid}' is not a border, "
                            f"re-parenting to '{frame.motif_id}'"
                        )
                        motif.parent_id = frame.motif_id
            # 始终标记 _ring_fixed，让下游 _region_to_placement 和
            # _align_nested_regions 知道这是需要保护的 ring 几何
            motif.region["_ring_fixed"] = True

    def render_visual_spec(self, plan: PatternPlan) -> VisualSpec:
        # Pre-pass: fix ring motifs before rendering
        self._preprocess_ring_motifs(plan)

        regions = [VisualRegion(
            region_id="ground",
            visual_shape="panel",
            visual_effect="plain",
            layout_role="ground",
            placement={"type": "full"},
            params={},
            symmetry="none",
            allow_refinement=False,
        )]

        for motif in plan.motifs:
            placement = self._region_to_placement(motif)
            visual_shape = self._motif_to_visual_shape(motif.motif_type)
            placement_shape = str(placement.get("shape", placement.get("mask_shape", ""))).lower()
            if visual_shape in {"panel", "allover"} and placement_shape in {
                "diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star",
                "rectangle", "chevron", "zigzag", "cross",
            }:
                visual_shape = placement_shape

            regions.append(VisualRegion(
                region_id=motif.motif_id,
                visual_shape=visual_shape,
                visual_effect=self._effect_to_visual_effect(motif.effect),
                layout_role=self._role_to_layout_role(motif.role),
                placement=placement,
                params=dict(motif.params),
                symmetry=motif.symmetry,
                allow_refinement=motif.allow_refinement,
            ))

        return VisualSpec(layout_type=plan.layout_type, regions=regions, raw_json=plan.to_dict())

    def validate(self, plan: PatternPlan, user_input: str = "") -> PatternPlan:
        if not plan.motifs:
            plan.motifs = self._motifs_from_text("中心菱形")
        seen = set()
        for idx, motif in enumerate(plan.motifs, start=1):
            if not motif.motif_id or motif.motif_id in seen:
                motif.motif_id = f"motif_{idx}"
            seen.add(motif.motif_id)
            motif.motif_type = self._motif_to_visual_shape(motif.motif_type)
            motif.effect = self._effect_to_visual_effect(motif.effect)
            motif.role = self._normalize_role(motif.role)
            motif.region = self._normalize_region(motif.region, motif_role=motif.role, motif_type=motif.motif_type)
            motif.params = self._normalize_params(motif.effect, motif.params)
            self._normalize_side_band_motif(motif)
        # 只在非随机来源时执行修复（精简：只保留必要的空间适配修复）
        is_random = any(
            h.get("source") in ("random",) for h in plan.history
        )
        if not is_random:
            self._repair_ring_motifs(plan)              # 修复 LLM 误生成 panel 的环形 motif
            self._repair_ring_role_motifs(plan)         # ring 尺寸 + inner_exclude
            self._validate_coordinate_convention(plan, user_input)  # 先修复坐标交换，再做尺寸适配
            self._repair_motif_shape_from_name(plan)    # 修复 LLM ID与type不一致（如 ID=diamond 但 type=circle）
            self._merge_same_shape_border(plan)         # 同形边框合并：border与center同形状时合为一体
            self._repair_plain_center_effect(plan, user_input)  # 修复 center effect=plain 但 prompt 有纹理关键词
        else:
            self._validate_coordinate_convention(plan, user_input)
        self._separate_coincident_positions(plan, user_input)
        self._setup_transition_regions(plan)
        self._infer_missing_parent_links(plan)
        self._validate_parent_assignments(plan)
        self._clamp_border_thickness(plan, user_input=user_input)
        # 清理坐标交换标记
        for m in plan.motifs:
            if isinstance(m.region, dict):
                m.region.pop("_coord_swapped", None)
        return plan

    def _validate_coordinate_convention(self, plan: PatternPlan, user_input: str = "") -> None:
        """Detect and fix LLM coordinate swap.

        The system uses center=[row, col] where row=vertical, col=horizontal.
        LLMs often generate center=[x, y] (Cartesian) which swaps the axes.

        Heuristic: if motifs named with left/right keywords have different
        row but same col, the coordinates are likely swapped — auto-fix.
        """
        _LR_KEYS = {"left", "right", "左", "右"}
        _TB_KEYS = {"top", "bottom", "upper", "lower", "上", "下"}

        def _has_key(name: str, keys: set) -> bool:
            nl = name.lower().replace("_", "").replace("-", "")
            return any(k in nl for k in keys)

        lr_motifs = [m for m in plan.motifs if _has_key(m.motif_id, _LR_KEYS)]
        tb_motifs = [m for m in plan.motifs if _has_key(m.motif_id, _TB_KEYS)]

        # Skip if any motif was already swapped in a previous pass
        if any(m.region.get("_coord_swapped") for m in plan.motifs if isinstance(m.region, dict)):
            return

        # Fallback: if no tb/lr motifs found by ID, try to detect from prompt
        # Pattern: "上方X...下方Y" or "左方X...右方Y" where X/Y are shape names
        _CN_EN = {
            "圆形": "circle", "圆": "circle",
            "菱形": "diamond", "菱": "diamond",
            "矩形": "rectangle", "方形": "rectangle", "方框": "rectangle",
            "三角形": "triangle", "三角": "triangle",
            "心形": "heart", "心": "heart",
            "星形": "star", "星": "star",
            "六角形": "hexagon", "六角": "hexagon",
        }

        def _shape_matches(shape_cn: str, motif_type: str) -> bool:
            mt = (motif_type or "").lower()
            if shape_cn in mt or mt in shape_cn:
                return True
            en = _CN_EN.get(shape_cn, "")
            if en and en in mt:
                return True
            # Also try stripping trailing chars
            for suffix in ["形", "状"]:
                stripped = shape_cn.rstrip(suffix)
                if stripped and (stripped in mt or mt.startswith(stripped)):
                    return True
            return False

        if user_input and not tb_motifs:
            import re as _re
            # Match patterns like "上方...圆形" / "下方...菱形"
            _tb_pattern = _re.compile(
                r'(?:上方|上面|上部|上)\s*(\S{1,6}?)(?:内|里|中|的|,)'
                r'.*?'
                r'(?:下方|下面|下部|下)\s*(\S{1,6}?)(?:内|里|中|的|,|$)'
            )
            m_tb = _tb_pattern.search(user_input)
            if m_tb:
                shape_top = m_tb.group(1).strip()
                shape_bot = m_tb.group(2).strip()
                # Find motifs matching these shape names
                for m in plan.motifs:
                    if _shape_matches(shape_top, m.motif_type):
                        tb_motifs.append(m)
                    elif _shape_matches(shape_bot, m.motif_type):
                        tb_motifs.append(m)
                if tb_motifs:
                    logger.info(
                        f"  tb_motifs detected from prompt: "
                        f"top_shape='{shape_top}', bot_shape='{shape_bot}', "
                        f"motifs={[m.motif_id for m in tb_motifs]}"
                    )

        if user_input and not lr_motifs:
            import re as _re
            _lr_pattern = _re.compile(
                r'(?:左方|左边|左侧|左)\s*(\S{1,6}?)(?:内|里|中|的|,)'
                r'.*?'
                r'(?:右方|右边|右侧|右)\s*(\S{1,6}?)(?:内|里|中|的|,|$)'
            )
            m_lr = _lr_pattern.search(user_input)
            if m_lr:
                shape_left = m_lr.group(1).strip()
                shape_right = m_lr.group(2).strip()
                for m in plan.motifs:
                    if _shape_matches(shape_left, m.motif_type):
                        lr_motifs.append(m)
                    elif _shape_matches(shape_right, m.motif_type):
                        lr_motifs.append(m)
                if lr_motifs:
                    logger.info(
                        f"  lr_motifs detected from prompt: "
                        f"left_shape='{shape_left}', right_shape='{shape_right}', "
                        f"motifs={[m.motif_id for m in lr_motifs]}"
                    )

        # Detect swap in left/right motifs: should differ in col (center[1]),
        # not in row (center[0]).
        if len(lr_motifs) >= 2:
            rows = set()
            cols = set()
            for m in lr_motifs:
                c = m.region.get("center", [20, 20])
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    rows.add(c[0])
                    cols.add(c[1])
            if len(rows) > 1 and len(cols) <= 1:
                logger.warning(
                    f"  coordinate swap detected: left/right motifs have "
                    f"different rows {rows} but same cols {cols}. "
                    f"Swapping center[0] <-> center[1]."
                )
                for m in lr_motifs:
                    c = m.region.get("center", [20, 20])
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        m.region["center"] = [c[1], c[0]]
                        m.region["_coord_swapped"] = True

        # Detect swap in top/bottom motifs: should differ in row (center[0]),
        # not in col (center[1]).
        if len(tb_motifs) >= 2:
            rows = set()
            cols = set()
            for m in tb_motifs:
                c = m.region.get("center", [20, 20])
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    rows.add(c[0])
                    cols.add(c[1])
            if len(cols) > 1 and len(rows) <= 1:
                # Case 1: different cols, same rows → LLM used [x,y] format, swap needed
                logger.warning(
                    f"  coordinate swap detected: top/bottom motifs have "
                    f"different cols {cols} but same rows {rows}. "
                    f"Swapping center[0] <-> center[1]."
                )
                for m in tb_motifs:
                    c = m.region.get("center", [20, 20])
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        m.region["center"] = [c[1], c[0]]
                        m.region["_coord_swapped"] = True
            # NOTE: different rows + same cols is CORRECT for top/bottom layout, no swap needed

    def _separate_coincident_positions(self, plan: PatternPlan, user_input: str = "") -> None:
        """当多个 border motif 共享同一中心位置时，根据 motif_id 中的方位词分散它们及其子 motif。

        LLM 有时将“并排”“左右”等空间关系理解为同一位置，导致圆形完全重叠。
        本方法检测同位置冲突，并按方位关键词重新分配坐标，同时移动关联的子 motif。
        """
        CANVAS = 40
        # 只处理非背景 motif
        content_motifs = [
            m for m in plan.motifs
            if m.role not in {"allover", "background", "ground"}
        ]
        # 按 (size, center) 分组——只有尺寸和位置都相同才算冲突
        center_groups: dict = {}
        for m in content_motifs:
            c = m.region.get("center")
            if not isinstance(c, (list, tuple)) or len(c) < 2:
                continue
            try:
                key = (int(c[0]), int(c[1]))
            except (TypeError, ValueError):
                continue
            center_groups.setdefault(key, []).append(m)

        # 检查是否有同位置冲突
        has_conflict = any(len(g) > 1 for g in center_groups.values())
        if not has_conflict:
            return

        # 按方位词前缀分组（left/right/top/bottom）
        direction_groups: dict = {}
        for m in content_motifs:
            mid = m.motif_id.lower()
            if any(k in mid for k in ["left", "左"]):
                direction_groups.setdefault("left", []).append(m)
            elif any(k in mid for k in ["right", "右"]):
                direction_groups.setdefault("right", []).append(m)
            elif any(k in mid for k in ["top", "上"]):
                direction_groups.setdefault("top", []).append(m)
            elif any(k in mid for k in ["bottom", "下"]):
                direction_groups.setdefault("bottom", []).append(m)

        # 左右分布
        if "left" in direction_groups and "right" in direction_groups:
            left_max_size = max(int(m.region.get("size", 10)) for m in direction_groups["left"])
            right_max_size = max(int(m.region.get("size", 10)) for m in direction_groups["right"])
            # 查找 frame 边界
            frame_center_c = CANVAS // 2
            frame_inner_half = CANVAS // 2 - 2
            for fm in plan.motifs:
                if fm.role in {"border", "frame"} and isinstance(fm.region, dict):
                    fc = fm.region.get("center", [20, 20])
                    fs = int(fm.region.get("size", 17))
                    bt = int(fm.params.get("border_thickness", 2) or 2)
                    try:
                        frame_center_c = int(fc[1])
                    except (TypeError, ValueError):
                        frame_center_c = 20
                    frame_inner_half = max(3, (fs - bt) // 2)
                    break
            new_left_col = frame_center_c - max(left_max_size // 2 + 1, frame_inner_half // 2)
            new_right_col = frame_center_c + max(right_max_size // 2 + 1, frame_inner_half // 2)
            for m in direction_groups["left"]:
                old = list(m.region["center"])
                m.region["center"][1] = new_left_col
                logger.warning(f"  [{m.motif_id}] separated left: col {old[1]} -> {new_left_col}")
            for m in direction_groups["right"]:
                old = list(m.region["center"])
                m.region["center"][1] = new_right_col
                logger.warning(f"  [{m.motif_id}] separated right: col {old[1]} -> {new_right_col}")

        # 上下分布
        elif "top" in direction_groups and "bottom" in direction_groups:
            top_max_size = max(int(m.region.get("size", 10)) for m in direction_groups["top"])
            bottom_max_size = max(int(m.region.get("size", 10)) for m in direction_groups["bottom"])
            # 查找包含这些 motif 的 frame，用 frame 边界代替画布边界
            frame_center_r = CANVAS // 2
            frame_inner_half = CANVAS // 2 - 2  # 默认值
            for fm in plan.motifs:
                if fm.role in {"border", "frame"} and isinstance(fm.region, dict):
                    fc = fm.region.get("center", [20, 20])
                    fs = int(fm.region.get("size", 17))
                    bt = int(fm.params.get("border_thickness", 2) or 2)
                    try:
                        frame_center_r = int(fc[0])
                    except (TypeError, ValueError):
                        frame_center_r = 20
                    frame_inner_half = max(3, (fs - bt) // 2)
                    break
            # 布局：圆形位于 frame 内 1/4 和 3/4 处，保证不重叠且尽量大
            sep_offset = max(3, frame_inner_half // 2)
            new_top_row = frame_center_r - sep_offset
            new_bottom_row = frame_center_r + sep_offset
            for m in direction_groups["top"]:
                old = list(m.region["center"])
                m.region["center"][0] = new_top_row
                logger.warning(f"  [{m.motif_id}] separated top: row {old[0]} -> {new_top_row}")
            for m in direction_groups["bottom"]:
                old = list(m.region["center"])
                m.region["center"][0] = new_bottom_row
                logger.warning(f"  [{m.motif_id}] separated bottom: row {old[0]} -> {new_bottom_row}")

            # 分离后不重新计算尺寸：frame 缩放已给出合理尺寸，分离只调整位置

    def _clamp_border_thickness(self, plan: PatternPlan, user_input: str = "") -> None:
        """根据当前编辑指令推断允许的最大边框厚度，并钗制所有 border motif 的 thickness。
    
        优先级策略：
        - 用户明确说"很粗/非常粗"：max_t = 4
        - 用户明确说"加粗"（非轻微）：max_t = 3
        - 用户说"轻微加粗/稍微加粗"：max_t = 2
        - 用户未提及任何粗度关键词：max_t = 2（初始创建默认值）
    
        优先使用传入的 user_input（当前指令），若为空则回退到最后一条 history。
        """
        if user_input:
            latest_text = user_input
        elif plan.history:
            latest_text = plan.history[-1].get("input", "")
        else:
            latest_text = ""
    
        # 检测粗度关键词
        is_mild = any(k in latest_text for k in ["轻微", "稍微", "一点", "少量", "稍稍", "略"])
        has_thicken_kw = any(k in latest_text for k in ["加粗", "很粗", "非常粗", "粗边框", "粗框"])
        is_strong = has_thicken_kw and not is_mild
    
        # 分层阈值：
        # - 很粗/非常粗（强加粗）：max 4
        # - 加粗（非轻微）：max 3
        # - 轻微加粗：max 2
        # - 未提及粗度：max 2（默认创建）
        if is_strong:
            # 检查是否为"非常粗/很粗"级别
            if any(k in latest_text for k in ["很粗", "非常粗"]):
                max_t = 4
            else:
                max_t = 3
        elif has_thicken_kw and is_mild:
            # 轻微加粗
            max_t = 2
        else:
            # 未提及粗度关键词，使用默认细边框
            max_t = 2

        for motif in plan.motifs:
            if motif.role != "border":
                continue
            for key in ("border_thickness", "thickness"):
                val = motif.params.get(key)
                if val is not None and isinstance(val, (int, float)):
                    motif.params[key] = max(1, min(int(max_t), int(val)))

    def _repair_plan_from_text(self, plan: PatternPlan, user_input: str) -> None:
        text = user_input or ""
        # 先修复坐标交换，再做尺寸适配
        self._validate_coordinate_convention(plan, text)

        self._repair_allover_geometry_semantics(plan, text)

        if any(k in text for k in ["双层菱形", "两层菱形", "菱形结构", "菱形边框"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                if motif.motif_type == "frame" and (
                    "outer" in rid or "frame" in rid or "border" in rid or motif.role == "border"
                ):
                    motif.motif_type = "diamond"
                    motif.region["shape"] = "diamond"

        if any(k in text for k in ["背景", "周围", "底纹", "background"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                if motif.role in {"background", "allover"} or "background" in rid or "背景" in rid or rid.endswith("_bg") or "bg" in rid:
                    motif.role = "allover"
                    motif.region = {"type": "full"}
                    motif.parent_id = None

        if any(k in text for k in ["六边形", "六角形", "hexagon"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                if motif.effect in {"honeycomb", "relief", "wave_tuck", "lace", "plain"} and (
                    motif.motif_type in {"panel", "allover", "circle"} or "hex" in rid or "honeycomb" in rid
                ):
                    if motif.role in {"center", "main"}:
                        motif.motif_type = "hexagon"
                        motif.region.setdefault("shape", "hexagon")

        if any(k in text for k in ["三角", "三角形", "triangle"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                if "triangle" in rid or "三角" in rid or motif.region.get("shape") == "triangle":
                    motif.region["shape"] = "triangle"
                    if motif.motif_type in {"mesh", "panel", "allover", "circle"} and motif.effect in {"plain", "honeycomb", "lace", "relief", "seed"}:
                        motif.motif_type = "triangle"

        if any(k in text for k in ["圆形", "圆形结构", "圆内部", "circle", "round"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                # Skip motifs explicitly identified as non-circle shapes
                if any(s in rid for s in ["triangle", "三角", "hexagon", "六角", "六边", "heart", "心形", "star", "星形", "cross", "十字", "chevron", "人字"]):
                    continue
                is_outer_frame = motif.role == "border" or any(k in rid for k in ["frame", "border", "边框", "outer"])
                is_texture = motif.effect in {"wave_tuck", "lace", "relief", "honeycomb", "seed"}
                is_center_like = motif.role in {"center", "main"} or any(k in rid for k in ["inner", "inside", "内部", "wave", "mesh", "circle"])
                if is_outer_frame:
                    continue
                if motif.role in {"allover", "background", "ground"}:
                    continue
                if is_center_like or is_texture:
                    motif.motif_type = "circle"
                    motif.region["shape"] = "circle"

        self._repair_directional_accent_positions(plan, text)
        self._repair_frame_contains_children(plan, text)

        # Complex prompts often describe a container first and an interior
        # texture later.  If the LLM points the interior to a frame/side band,
        # repair it to the central geometric container.
        if any(k in text for k in ["内部", "里面", "内含", "内有"]):
            central = self._best_central_container(plan)
            requested_inner_shape = "circle" if any(k in text for k in ["圆形", "圆形结构", "圆内部", "circle", "round"]) else None
            if central is not None:
                for motif in plan.motifs:
                    rid = motif.motif_id.lower()
                    if self._is_background_motif(motif):
                        continue
                    is_side = motif.role == "side_band" or any(k in rid for k in ["left", "right", "左", "右", "side", "band"])
                    if is_side:
                        continue
                    is_inner = any(k in rid for k in ["inner", "inside", "fill", "内部", "mesh", "wave"])
                    is_texture = motif.effect in {"wave_tuck", "lace", "relief", "honeycomb", "seed"}
                    if motif is central or not (is_inner or is_texture):
                        continue
                    if motif.parent_id and central.motif_type == "circle" and motif.motif_type == "circle":
                        continue
                    explicit_shape = str(motif.region.get("shape", "")).lower()
                    if explicit_shape in {"triangle", "hexagon", "circle", "heart", "star", "cross"}:
                        if explicit_shape == central.motif_type or explicit_shape == requested_inner_shape:
                            motif.parent_id = central.motif_id
                        continue
                    motif.parent_id = central.motif_id
                    motif.region["shape"] = requested_inner_shape or central.motif_type
                    if requested_inner_shape:
                        motif.motif_type = requested_inner_shape

        self._repair_allover_geometry_semantics(plan, text)
        self._detach_background_motifs(plan)
        self._repair_frame_contains_children(plan, text)

    def _repair_frame_contains_children(self, plan: PatternPlan, text: str) -> None:
        if not any(k in text for k in ["边框内", "框内", "内包含", "包含", "里面包含"]):
            return
        frame = None
        for motif in plan.motifs:
            rid = motif.motif_id.lower()
            if motif.role == "border" and (
                motif.motif_type in {"frame", "rectangle", "border"}
                or str(motif.region.get("shape", "")).lower() in {"rectangle", "rect", "frame", "border", "box"}
                or any(k in rid for k in ["frame", "rect", "border", "边框", "外框"])
            ):
                frame = motif
                break
        if frame is None:
            return

        for motif in plan.motifs:
            if motif is frame or self._is_background_motif(motif):
                continue
            if motif.role in {"side_band", "border"}:
                continue
            if motif.motif_type in {"circle", "diamond", "triangle", "hexagon", "polygon", "heart", "star", "rectangle", "wave", "mesh", "panel"}:
                motif.parent_id = frame.motif_id
                motif.region.setdefault("parent_clip_margin", 1)

        circles = [
            m for m in plan.motifs
            if m.parent_id == frame.motif_id and m.motif_type == "circle"
        ]
        if len(circles) == 2 and any(k in text for k in ["两个", "两处", "左右", "靠近边界"]):
            try:
                center = frame.region.get("center", [20, 20])
                fr, fc = int(center[0]), int(center[1])
                frame_size = int(frame.region.get("size", 16))
            except Exception:
                fr, fc, frame_size = 20, 20, 16
            try:
                radius = max(int(c.region.get("size", 6)) for c in circles)
            except Exception:
                radius = 6
            margin = max(2, int(frame.params.get("thickness", frame.params.get("frame_width", 2))) + 2)
            gap = 2
            inner_half = max(4, frame_size - margin)
            max_radius = max(4, inner_half - 1)
            if radius > max_radius:
                radius = max_radius
            offset = max(radius, inner_half - radius)
            circles = sorted(circles, key=lambda m: str(m.motif_id))
            circles[0].parent_id = frame.motif_id
            circles[1].parent_id = frame.motif_id
            circles[0].region["center"] = [fr - offset, fc - offset]
            circles[1].region["center"] = [fr + offset, fc + offset]
            circles[0].region["size"] = radius
            circles[1].region["size"] = radius

    def _repair_allover_geometry_semantics(self, plan: PatternPlan, text: str) -> None:
        """Keep background layers as cloth, and recover misplaced center shapes.

        LLM plans sometimes encode "圆形结构" as an allover/full circle.  In this
        system allover/full means background fill; a named geometric structure
        must be a centered container so inner textures can be clipped to it.
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        background_ids = {"bg", "background", "ground", "底", "背景"}
        requested_shape = self._find_outer_shape_alias(text, default="")
        mentions_background = any(k in text for k in ["背景", "底纹", "底布", "background", "ground"])

        for motif in plan.motifs:
            rid = motif.motif_id.lower()
            shape_hint = str(motif.region.get("shape", motif.region.get("mask_shape", "")) or "").lower()
            is_named_background = any(k in rid for k in background_ids)
            is_plain_allover = motif.role in {"allover", "background", "ground"} and motif.effect in {"plain", "reverse"}
            has_geometry = motif.motif_type in geometry or shape_hint in geometry

            if is_plain_allover and is_named_background:
                motif.motif_type = "panel"
                motif.region = {"type": "full"}
                continue

            if (
                is_plain_allover
                and has_geometry
                and not is_named_background
                and requested_shape in geometry
                and (motif.motif_type == requested_shape or shape_hint == requested_shape)
            ):
                motif.role = "center"
                motif.motif_type = requested_shape
                motif.region = {
                    "center": motif.region.get("center", [20, 20]),
                    "size": int(motif.region.get("size", 14)),
                    "shape": requested_shape,
                }
                continue

            if is_plain_allover and mentions_background and not has_geometry:
                motif.motif_type = "panel"
                motif.region = {"type": "full"}

    def _is_background_motif(self, motif: PatternMotif) -> bool:
        rid = str(motif.motif_id or "").lower()
        bg_tokens = {"bg", "background", "ground", "base", "backdrop"}
        rid_tokens = {token for token in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", rid) if token}
        return (
            motif.role in {"allover", "background", "ground"}
            or bool(bg_tokens & rid_tokens)
            or "背景" in rid
            or "底纹" in rid
        )

    def _detach_background_motifs(self, plan: PatternPlan) -> None:
        for motif in plan.motifs:
            if not self._is_background_motif(motif):
                continue
            motif.role = "allover"
            motif.parent_id = None
            motif.motif_type = "panel"
            motif.region = {"type": "full"}

    def _data_to_plan(self, data: Dict[str, Any], current_plan: Optional[PatternPlan]) -> Optional[PatternPlan]:
        if "motifs" in data:
            plan = PatternPlan.from_dict(data)
            self._validate_motif_effect_compatibility(plan)
            self._validate_parent_ids(plan)
            self._validate_size_constraints(plan)
            return plan

        if "operation" in data:
            plan = copy.deepcopy(current_plan) if current_plan is not None else PatternPlan()
            self._apply_operation(plan, data)
            return plan

        if "regions" in data:
            return self._visual_spec_data_to_plan(data)

        return None

    def _validate_motif_effect_compatibility(self, plan: PatternPlan) -> None:
        """检查并修正 motif_type 与 effect 的不兼容组合。
        当 LLM 输出形状类 motif_type（如 stripe）但 effect="plain" 时，
        自动映射到合适的纹理 effect，避免渲染出无纹理的空白区域。
        """
        _SHAPE_TO_EFFECT = {
            "stripe": "rib",
            "column": "rib",
            "wave": "wave_tuck",
            "zigzag": "wave_tuck",
            "chevron": "wave_tuck",
        }
        for motif in plan.motifs:
            if motif.effect != "plain":
                continue
            if motif.role in {"border", "ground", "allover"}:
                continue
            mt = str(motif.motif_type or "").lower()
            if mt in _SHAPE_TO_EFFECT:
                corrected = _SHAPE_TO_EFFECT[mt]
                logger.warning(
                    f"  [{motif.motif_id}] motif_type='{mt}' + effect='plain' "
                    f"→ 自动修正 effect='{corrected}'"
                )
                motif.effect = corrected

    def _validate_parent_ids(self, plan: PatternPlan) -> None:
        """检查并修正不合理的 parent_id 关系。
        规则：
        1. 子 motif 的 size 不应明显大于父 motif 的 size（子不应比父大）
        2. 如果子比父大，清除 parent_id 并记录警告
        """
        motifs_by_id = {m.motif_id: m for m in plan.motifs}
        for motif in plan.motifs:
            if not motif.parent_id:
                continue
            parent = motifs_by_id.get(motif.parent_id)
            if parent is None:
                logger.warning(f"  [{motif.motif_id}] parent_id='{motif.parent_id}' 不存在，清除")
                motif.parent_id = None
                continue
            child_size = motif.region.get("size", 0)
            parent_size = parent.region.get("size", 0)
            child_center = motif.region.get("center", [20, 20])
            parent_center = parent.region.get("center", [20, 20])
            # 子不应比父大超过 2
            if child_size > parent_size + 2 and parent.role not in {"border", "frame"}:
                logger.warning(
                    f"  [{motif.motif_id}] size={child_size} > parent [{parent.motif_id}] "
                    f"size={parent_size}，父子关系不合理，清除 parent_id"
                )
                motif.parent_id = None
            # 同心圆/同形状重叠：如果父子中心相同且都是相同形状，
            # 子被父包含没有意义，清除 parent_id
            elif (
                child_center == parent_center
                and child_size <= parent_size
                and str(motif.region.get("shape", motif.motif_type)).lower()
                    == str(parent.region.get("shape", parent.motif_type)).lower()
                and parent.role not in {"border", "frame"}
            ):
                logger.warning(
                    f"  [{motif.motif_id}] 与父 [{parent.motif_id}] 同心同形，"
                    f"父子关系无意义，清除 parent_id"
                )
                motif.parent_id = None

    def _validate_size_constraints(self, plan: PatternPlan) -> None:
        """验证并修正尺寸约束。只做一件事：确保 frame 足够大以容纳子区域。
            
        双向适应：外框扩展 + 子区域等比缩小，互相适应融合。
        """
        canvas_size = int(plan.canvas.get("width", 40))
            
        for motif in plan.motifs:
            if motif.role not in {"border", "frame"}:
                continue
            frame_size = int(motif.region.get("size", 16))
            frame_center = motif.region.get("center", [20, 20])
            try:
                fcr, fcc = int(frame_center[0]), int(frame_center[1])
            except Exception:
                fcr, fcc = 20, 20
            border_thickness = int(motif.params.get("border_thickness", 2) or 2)
    
            # 收集子区域：优先用 parent_id，否则收集空间上在 frame 内部的几何 motif
            children = [m for m in plan.motifs if m.parent_id == motif.motif_id]
            if not children:
                frame_half = frame_size / 2.0
                for m in plan.motifs:
                    if m is motif or m.role in {"ground", "allover"} or m.motif_type == "panel":
                        continue
                    if m.motif_type not in {"circle", "diamond", "triangle", "hexagon", "heart", "star", "rectangle", "polygon", "frame"}:
                        continue
                    c = (m.region if isinstance(m.region, dict) else {}).get("center")
                    if not c or len(c) < 2:
                        continue
                    try:
                        cr2, cc2 = int(c[0]), int(c[1])
                    except Exception:
                        continue
                    if abs(cr2 - fcr) <= frame_half and abs(cc2 - fcc) <= frame_half:
                        children.append(m)
            if not children:
                continue
    
            # Step 1: 先 cap frame 到画布安全上限
            safe_max = max(canvas_size // 2 - border_thickness - 1, 8)
            if frame_size > safe_max:
                logger.info(
                    f"  [{motif.motif_id}] frame size={frame_size} exceeds safe max={safe_max} "
                    f"(canvas={canvas_size}, border={border_thickness}), capping"
                )
                motif.region["size"] = safe_max
                motif.region.pop("top_left", None)
                motif.region.pop("bottom_right", None)
                motif.region.pop("bounds", None)
                frame_size = safe_max

            # Step 2: 计算需要的最小 frame 尺寸，尝试扩展（不超过 safe_max）
            min_frame_size = frame_size
            for child in children:
                child_size = int(child.region.get("size", 0))
                cr = child.region.get("center", frame_center) if isinstance(child.region, dict) else frame_center
                try:
                    offset = max(abs(int(cr[0]) - fcr), abs(int(cr[1]) - fcc))
                except Exception:
                    offset = 0
                # frame_size >= 2*offset + child_size + border_thickness
                needed = 2 * offset + child_size + border_thickness
                min_frame_size = max(min_frame_size, needed)
    
            # 扩展 frame（不超过 safe_max）
            target_frame_size = min(min_frame_size, safe_max)
            if target_frame_size > frame_size:
                logger.warning(
                    f"  [{motif.motif_id}] frame size={frame_size} too small for children "
                    f"(needs {min_frame_size}), expanding to {target_frame_size}"
                )
                motif.region["size"] = target_frame_size
                motif.region.pop("top_left", None)
                motif.region.pop("bottom_right", None)
                motif.region.pop("bounds", None)
                frame_size = target_frame_size
    
            # 子区域适配：先缩放位置，再最大化尺寸
            inner_half = max(1, (frame_size - border_thickness) / 2.0)
            needs_adjust = False
            for child in children:
                cr = child.region.get("center", [fcr, fcc]) if isinstance(child.region, dict) else [fcr, fcc]
                try:
                    ccr, ccc = int(cr[0]), int(cr[1])
                except Exception:
                    ccr, ccc = fcr, fcc
                child_size = int(child.region.get("size", 0)) if isinstance(child.region, dict) else 0
                max_off = max(0, inner_half - child_size / 2.0)
                if abs(ccr - fcr) > max_off or abs(ccc - fcc) > max_off:
                    needs_adjust = True
                    break
    
            if needs_adjust:
                # Phase 1: 计算位置缩放因子（仅缩放位置，不缩放尺寸）
                pos_scales = []
                for child in children:
                    cr = child.region.get("center", [fcr, fcc]) if isinstance(child.region, dict) else [fcr, fcc]
                    try:
                        ccr, ccc = int(cr[0]), int(cr[1])
                    except Exception:
                        ccr, ccc = fcr, fcc
                    child_size = int(child.region.get("size", 0)) if isinstance(child.region, dict) else 0
                    offset = max(abs(ccr - fcr), abs(ccc - fcc))
                    max_off = max(0, inner_half - child_size / 2.0)
                    if offset > max_off and offset > 0:
                        pos_scales.append(max(0.5, max_off / offset))
                    else:
                        pos_scales.append(1.0)
                min_pos_scale = min(pos_scales) if pos_scales else 1.0
                logger.info(f"  [{motif.motif_id}] children pos_scale={min_pos_scale:.2f}")

                # Phase 2: 缩放位置，计算新位置
                new_positions = []  # [(new_r, new_c, child_index)]
                for child in children:
                    cr = child.region.get("center", [fcr, fcc]) if isinstance(child.region, dict) else [fcr, fcc]
                    try:
                        ccr, ccc = int(cr[0]), int(cr[1])
                    except Exception:
                        ccr, ccc = fcr, fcc
                    new_r = int(fcr + (ccr - fcr) * min_pos_scale)
                    new_c = int(fcc + (ccc - fcc) * min_pos_scale)
                    new_positions.append((new_r, new_c))

                # Phase 3: 最大化尺寸（仅 frame 边界约束，兄弟约束由分离后重新计算）
                for i, child in enumerate(children):
                    child_size = int(child.region.get("size", 0)) if isinstance(child.region, dict) else 0
                    new_r, new_c = new_positions[i]
                    # Frame 边界约束
                    new_offset = max(abs(new_r - fcr), abs(new_c - fcc))
                    max_size = max(4, int(2 * (inner_half - new_offset)))
                    new_size = max(4, min(child_size, max_size))
                    if new_size != child_size:
                        child.region["size"] = new_size
                    child.region["center"] = [new_r, new_c]
    
    def _visual_spec_data_to_plan(self, data: Dict[str, Any]) -> PatternPlan:
        motifs = []
        for idx, region in enumerate(data.get("regions", []) or []):
            if str(region.get("layout_role", "")) == "ground":
                continue
            placement = dict(region.get("placement", {}) or {})
            motifs.append(PatternMotif(
                motif_id=str(region.get("region_id", f"motif_{idx}")),
                motif_type=str(region.get("visual_shape", placement.get("shape", "panel"))),
                effect=str(region.get("visual_effect", "plain")),
                region=placement,
                params=dict(region.get("params", {}) or {}),
                role=str(region.get("layout_role", "center")),
                symmetry=str(region.get("symmetry", "none")),
                allow_refinement=bool(region.get("allow_refinement", True)),
                parent_id=placement.get("parent_id"),
            ))
        return PatternPlan(layout_type=str(data.get("layout_type", "centered")), motifs=motifs)

    def _apply_operation(self, plan: PatternPlan, op: Dict[str, Any]) -> None:
        action = str(op.get("operation", "modify")).lower()
        if action == "add":
            motif_data = op.get("motif", {}) or {}
            motif_data.setdefault("motif_id", self._next_id(plan, motif_data.get("motif_type", motif_data.get("type", "motif"))))
            plan.motifs.append(PatternMotif(
                motif_id=str(motif_data.get("motif_id")),
                motif_type=str(motif_data.get("motif_type", motif_data.get("type", "panel"))),
                effect=str(motif_data.get("effect", "plain")),
                region=dict(motif_data.get("region", {}) or {}),
                params=dict(motif_data.get("params", {}) or {}),
                role=str(motif_data.get("role", "center")),
                symmetry=str(motif_data.get("symmetry", "none")),
                allow_refinement=bool(motif_data.get("allow_refinement", True)),
                parent_id=motif_data.get("parent_id"),
            ))
            return

        target = str(op.get("target", "main"))
        motif = plan.get_motif(target) or self._last_editable_motif(plan)
        if motif is None:
            return
        if action == "delete":
            plan.motifs = [m for m in plan.motifs if m.motif_id != motif.motif_id]
            return
        changes = dict(op.get("changes", {}) or {})
        for key, value in changes.items():
            if key in {"motif_type", "type"}:
                motif.motif_type = str(value)
            elif key == "effect":
                motif.effect = str(value)
            elif key == "role":
                motif.role = str(value)
            elif key == "region":
                motif.region.update(dict(value or {}))
            elif key == "params":
                motif.params.update(dict(value or {}))
            elif key in motif.region:
                motif.region[key] = value
            else:
                motif.params[key] = value

    def _apply_heuristic_edit(self, plan: PatternPlan, user_input: str) -> None:
        if self._apply_structured_edit(plan, user_input):
            return

        motif = self._target_motif(plan, user_input)
        if motif is None:
            return
        factor = self._relative_factor(user_input)
        size_cap = 20
        if any(k in user_input for k in ["大", "宽", "粗", "放大"]):
            step = 1  # 默认只加 1 层，避免过度加宽
            motif.region["size"] = min(size_cap, int(motif.region.get("size", 16)) + step)
            # 对边框类 motif 限制厚度上限
            if motif.role == "border" or motif.motif_type in {"frame", "rectangle"}:
                max_t = 3
                motif.params["thickness"] = max(1, min(max_t, int(motif.params.get("thickness", 2)) + 1))
            else:
                motif.params["thickness"] = max(1, min(4, int(motif.params.get("thickness", 2)) + 1))
        if any(k in user_input for k in ["小", "窄", "细", "缩小"]):
            motif.region["size"] = int(round(int(motif.region.get("size", 16)) / factor))
            motif.params["thickness"] = max(1, int(round(int(motif.params.get("thickness", 2)) / factor)))
        if any(k in user_input for k in ["密", "更多", "多一点"]):
            motif.params["period_x"] = max(2, int(round(int(motif.params.get("period_x", 5)) / factor)))
            motif.params["period_y"] = max(2, int(round(int(motif.params.get("period_y", 4)) / factor)))
        if any(k in user_input for k in ["疏", "少一点", "稀"]):
            motif.params["period_x"] = min(12, int(round(int(motif.params.get("period_x", 5)) * factor)))
            motif.params["period_y"] = min(12, int(round(int(motif.params.get("period_y", 4)) * factor)))
        if any(k in user_input for k in ["镂空", "网眼", "孔洞"]):
            plan.motifs.append(PatternMotif(
                motif_id=self._next_id(plan, "eyelet"),
                motif_type="mesh",
                effect="lace",
                region=dict(motif.region),
                params={"period_x": 4, "period_y": 4, "stagger": True},
                role=motif.role,
                parent_id=motif.motif_id,
            ))
        if "上" in user_input:
            self._move(motif, dr=-2)
        if "下" in user_input:
            self._move(motif, dr=2)
        if "左" in user_input:
            self._move(motif, dc=-2)
        if "右" in user_input:
            self._move(motif, dc=2)

    def _apply_structured_edit(self, plan: PatternPlan, user_input: str) -> bool:
        changed = False
        factor = self._relative_factor(user_input)

        if any(k in user_input for k in ["外部", "外面", "外围", "外层"]) and any(k in user_input for k in ["矩形", "方框", "边框", "框"]):
            self._add_outer_rectangle_frame(plan, user_input)
            changed = True

        border_motifs = [
            m for m in plan.motifs
            if m.role == "border" or m.motif_type in {"frame", "rectangle"} or any(k in m.motif_id.lower() for k in ["border", "frame", "outer"])
        ]
        texture_motifs = [
            m for m in plan.motifs
            if m.role != "border" and (
                m.effect in {"wave_tuck", "lace", "relief", "honeycomb", "seed", "rib", "links"}
                or m.motif_type in {"wave", "mesh", "stripe", "column"}
            )
        ]

        if any(k in user_input for k in ["边框", "框", "外框"]) and any(k in user_input for k in ["粗", "加粗", "厚", "加宽", "宽"]):
            for motif in border_motifs:
                current = int(motif.params.get("border_thickness", motif.params.get("thickness", 1)))
                # 智能步长：用户说"明显/大幅/加粗很多"才用 2，否则默认 1
                if any(k in user_input for k in ["明显", "大幅", "很多", "大大", "非常"]):
                    step = 2
                elif any(k in user_input for k in ["稍微", "一点", "轻微", "少量", "稍稍"]):
                    step = 1
                else:
                    step = 1  # 默认只加 1 层，避免过度加宽
                # 边框厚度上限：3（普通）/ 4（明确说"加粗"）
                max_thickness = 4 if any(k in user_input for k in ["加粗", "很粗", "非常粗"]) else 3
                motif.params["border_thickness"] = max(1, min(max_thickness, current + step))
                motif.params["thickness"] = motif.params["border_thickness"]
            changed = True

        if any(k in user_input for k in ["边框", "框", "外框"]) and any(k in user_input for k in ["细", "变细", "薄"]):
            for motif in border_motifs:
                current = int(motif.params.get("border_thickness", motif.params.get("thickness", 2)))
                motif.params["border_thickness"] = max(1, min(current - 1, int(round(current / factor))))
                motif.params["thickness"] = motif.params["border_thickness"]
            changed = True

        if any(k in user_input for k in ["内部", "里面", "纹理", "花纹"]) and any(k in user_input for k in ["疏", "稀", "少一点"]):
            for motif in texture_motifs:
                px = int(motif.params.get("period_x", 5))
                py = int(motif.params.get("period_y", 4))
                motif.params["period_x"] = min(12, max(px + 1, int(round(px * factor))))
                motif.params["period_y"] = min(12, max(py + 1, int(round(py * factor))))
            changed = True

        if any(k in user_input for k in ["内部", "里面", "纹理", "花纹"]) and any(k in user_input for k in ["密", "更多", "多一点"]):
            for motif in texture_motifs:
                px = int(motif.params.get("period_x", 5))
                py = int(motif.params.get("period_y", 4))
                motif.params["period_x"] = max(2, min(px - 1, int(round(px / factor))))
                motif.params["period_y"] = max(2, min(py - 1, int(round(py / factor))))
            changed = True

        return changed

    def _add_outer_rectangle_frame(self, plan: PatternPlan, user_input: str) -> None:
        existing = {m.motif_id for m in plan.motifs}
        motif_id = "outer_rectangle_frame"
        idx = 2
        while motif_id in existing:
            motif_id = f"outer_rectangle_frame_{idx}"
            idx += 1

        thickness = 2 if any(k in user_input for k in ["粗", "加粗", "厚"]) else 1
        thickness = min(thickness, 3)  # 边框厚度上限
        plan.motifs.insert(0, PatternMotif(
            motif_id=motif_id,
            motif_type="frame",
            effect="reverse",
            region={"center": [20, 20], "size": 17, "shape": "rectangle"},
            params={"border_thickness": thickness, "thickness": thickness},
            role="border",
            allow_refinement=False,
        ))
        plan.layout_type = "framed"

        # Keep existing content away from the 40x40 edge so the new frame has
        # visible right/bottom sides after clipping and simulation.
        for motif in plan.motifs[1:]:
            if motif.region.get("type") == "full":
                continue
            motif.region["center"] = [20, 20]
            try:
                motif.region["size"] = min(int(motif.region.get("size", 16)), 15)
            except Exception:
                motif.region["size"] = 15

    def _motifs_from_text(self, user_input: str) -> List[PatternMotif]:
        shape = self._find_alias(user_input, SHAPE_ALIASES, default="panel")
        effect = self._find_alias(user_input, EFFECT_ALIASES, default="plain")
        if any(k in user_input for k in ["中心六边形", "六边形蜂巢", "六角形蜂巢"]):
            shape = "hexagon"
            effect = "honeycomb"
        elif any(k in user_input for k in ["中心圆形", "圆形结构", "圆形内部", "圆内部"]):
            shape = "circle"
        elif any(k in user_input for k in ["中心菱形", "菱形结构", "菱形内部"]):
            shape = "diamond"
        if shape == "mesh" and effect == "plain":
            effect = "lace"
        if shape == "wave" and effect == "plain":
            effect = "wave_tuck"

        role = "allover" if any(k in user_input for k in ["整幅", "满地", "全图", "allover"]) else "center"
        region = {"type": "full"} if role == "allover" else {"center": [20, 20], "size": self._size_from_text(user_input)}
        motifs = [PatternMotif(
            motif_id="main",
            motif_type=shape,
            effect=effect,
            role=role,
            region=region,
            params=self._default_params(effect, user_input),
            symmetry="mirror_lr" if any(k in user_input for k in ["对称", "菱形"]) else "none",
        )]
        if self._looks_like_inner_composition(user_input):
            outer_shape = self._find_outer_shape_alias(user_input, default=shape)
            inner_effect = "wave_tuck" if any(k in user_input for k in ["波浪", "水波", "起伏"]) else effect
            inner_shape = "wave" if inner_effect == "wave_tuck" else shape
            outer_size = self._size_from_text(user_input)
            motifs = [
                PatternMotif(
                    motif_id="outer",
                    motif_type=outer_shape,
                    effect="reverse",
                    role="border",
                    region={"center": [20, 20], "size": outer_size, "shape": outer_shape},
                    params={"border_thickness": 1},
                    symmetry="mirror_lr" if outer_shape == "diamond" else "none",
                    allow_refinement=False,
                ),
                PatternMotif(
                    motif_id="inner",
                    motif_type=inner_shape,
                    effect=inner_effect,
                    role="center",
                    region={"center": [20, 20], "size": max(4, outer_size - 2), "shape": outer_shape},
                    params=self._default_params(inner_effect, user_input),
                    symmetry="mirror_lr" if outer_shape == "diamond" else "none",
                    parent_id="outer",
                ),
            ]
        if any(k in user_input for k in ["边框", "框", "花边"]):
            motifs.insert(0, PatternMotif(
                motif_id="border",
                motif_type="frame",
                effect="reverse",
                role="border",
                region={"center": [20, 20], "size": min(19, self._size_from_text(user_input) + 3)},
                allow_refinement=False,
            ))
        bg_motif = self._background_motif_from_text(user_input)
        if bg_motif is not None:
            motifs.insert(0, bg_motif)
        return motifs

    def _background_motif_from_text(self, user_input: str) -> Optional[PatternMotif]:
        has_bg = any(k in user_input for k in ["背景", "周围", "底纹", "底布", "background"])
        if not has_bg:
            return None
        effect = None
        motif_type = "panel"
        if any(k in user_input for k in ["稀疏网眼", "网眼", "镂空", "孔洞", "蕾丝"]):
            effect = "lace"
        elif any(k in user_input for k in ["波浪", "水波", "起伏"]):
            effect = "wave_tuck"
            motif_type = "wave"
        elif any(k in user_input for k in ["蜂巢"]):
            effect = "honeycomb"
        elif any(k in user_input for k in ["浮雕", "凸起"]):
            effect = "relief"
        if effect is None:
            return None
        params = self._default_params(effect, user_input)
        if effect == "lace" and any(k in user_input for k in ["稀疏", "疏", "稀"]):
            params["period_x"] = max(int(params.get("period_x", 6)), 8)
            params["period_y"] = max(int(params.get("period_y", 6)), 8)
        return PatternMotif(
            motif_id="bg_texture",
            motif_type=motif_type,
            effect=effect,
            role="allover",
            region={"type": "full"},
            params=params,
            allow_refinement=True,
        )

    def _looks_like_inner_composition(self, text: str) -> bool:
        has_outer = any(k in text for k in [
            "菱形", "菱格", "diamond", "圆形", "圆", "三角", "六边形",
            "多边形", "心形", "星形", "边框", "框",
        ])
        has_inner = any(k in text for k in ["内部", "里面", "中间", "内含", "内有"])
        has_texture = any(k in text for k in ["波浪", "镂空", "网眼", "孔洞", "蜂巢", "浮雕", "罗纹"])
        return has_outer and has_inner and has_texture

    def _default_params(self, effect: str, user_input: str) -> Dict[str, Any]:
        dense = any(k in user_input for k in ["密", "细密", "小"])
        loose = any(k in user_input for k in ["疏", "大", "宽"])
        period_x = 4 if dense else 6 if loose else 5
        period_y = 3 if dense else 5 if loose else 4
        if effect == "wave_tuck":
            return {"period_x": period_x, "period_y": period_y, "split_col_offset": 2, "tuck_col_offset": 3}
        if effect == "lace":
            return {"period_x": max(3, period_x), "period_y": max(3, period_y), "stagger": True}
        if effect == "cable":
            return {"cable_period": 5, "cable_pairs": 2, "side_ratio": 0.3}
        if effect in {"relief", "honeycomb"}:
            return {"period_x": max(3, period_x - 1), "period_y": max(3, period_y - 1), "stagger": True}
        if effect == "rib":
            # rib 效果需要 period_x/period_y 来控制纹理周期
            return {"period_x": period_x, "period_y": period_y}
        if effect == "seed":
            return {"period_x": max(3, period_x), "period_y": max(3, period_y)}
        if effect == "links":
            return {"period_x": period_x, "period_y": period_y}
        if effect == "reverse":
            return {"period_x": period_x, "period_y": period_y}
        return {}

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
        raw = match.group(1) if match else None
        if raw is None:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                raw = text[start:end + 1]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _looks_like_edit(self, text: str) -> bool:
        return any(k in text for k in ["一点", "更", "加", "改", "调整", "放大", "缩小", "上移", "下移", "左移", "右移", "不要", "删除", "加宽", "变宽", "变粗", "变厚"])

    def _target_motif(self, plan: PatternPlan, text: str) -> Optional[PatternMotif]:
        for motif in plan.motifs:
            if motif.motif_type in text or motif.effect in text or motif.motif_id in text:
                return motif
        return self._last_editable_motif(plan)

    def _last_editable_motif(self, plan: PatternPlan) -> Optional[PatternMotif]:
        for motif in reversed(plan.motifs):
            if motif.role != "ground":
                return motif
        return plan.motifs[-1] if plan.motifs else None

    def _relative_factor(self, text: str) -> float:
        for key, value in RELATIVE_SCALE.items():
            if key in text:
                return value
        return 1.25

    def _move(self, motif: PatternMotif, dr: int = 0, dc: int = 0) -> None:
        center = motif.region.get("center", [20, 20])
        if not isinstance(center, list) or len(center) < 2:
            center = [20, 20]
        motif.region["center"] = [int(center[0]) + dr, int(center[1]) + dc]

    def _repair_directional_accent_positions(self, plan: PatternPlan, text: str) -> None:
        """Correct common row/col swaps from relative Chinese placement words."""
        if not text:
            return

        containers = [
            m for m in plan.motifs
            if m.motif_type in {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
            and m.role in {"center", "border"}
        ]
        anchor = None
        if containers:
            anchor = self._best_central_container(plan) or containers[0]
            base_center = anchor.region.get("center", [20, 20])
            try:
                base_r, base_c = int(base_center[0]), int(base_center[1])
                base_size = int(anchor.region.get("size", 16))
            except Exception:
                base_r, base_c, base_size = 20, 20, 16
        else:
            base_r, base_c, base_size = 20, 20, 16

        directions = []
        if any(k in text for k in ["下方", "下面", "下侧", "底部", "下部", "下边"]):
            directions.append("bottom")
        if any(k in text for k in ["上方", "上面", "上侧", "顶部", "上部", "上边"]):
            directions.append("top")
        if any(k in text for k in ["左侧", "左边", "左方"]):
            directions.append("left")
        if any(k in text for k in ["右侧", "右边", "右方"]):
            directions.append("right")
        if not directions:
            return

        accent_words = {"accent", "decoration", "decor", "eyelet", "lace", "mesh", "triangle", "三角", "镂空", "装饰"}
        for motif in plan.motifs:
            if anchor is not None and motif.motif_id == anchor.motif_id:
                continue
            if motif.parent_id:
                continue
            rid = motif.motif_id.lower()
            if any(k in rid for k in ["inner", "inside", "fill", "wave", "内部", "里面"]):
                continue
            looks_accent = (
                motif.effect in {"lace", "seed", "relief", "honeycomb"}
                or motif.motif_type in {"triangle", "mesh", "circle", "star", "heart"}
                or any(word in rid for word in accent_words)
            )
            if not looks_accent:
                continue

            center = motif.region.get("center", [base_r, base_c])
            if not isinstance(center, list) or len(center) < 2:
                center = [base_r, base_c]
            try:
                r, c = int(center[0]), int(center[1])
            except Exception:
                r, c = base_r, base_c
            try:
                size = int(motif.region.get("size", 6))
            except Exception:
                size = 6

            gap = max(2, min(6, size // 2))
            if "bottom" in directions:
                r = min(39, base_r + base_size // 2 + gap)
                c = base_c
            elif "top" in directions:
                r = max(0, base_r - base_size // 2 - gap)
                c = base_c
            elif "left" in directions:
                c = min(c, max(0, base_c - base_size // 2 - gap))
                r = base_r if abs(r - base_r) > max(2, base_size // 2) else r
            elif "right" in directions:
                c = max(c, min(39, base_c + base_size // 2 + gap))
                r = base_r if abs(r - base_r) > max(2, base_size // 2) else r

            motif.region["center"] = [max(0, min(39, r)), max(0, min(39, c))]

    def _find_alias(self, text: str, aliases: Dict[str, str], default: str) -> str:
        lower = text.lower()
        for key, value in aliases.items():
            if key in text or key in lower:
                return value
        return default

    def _find_outer_shape_alias(self, text: str, default: str) -> str:
        container_aliases = {
            "菱形": "diamond",
            "菱格": "diamond",
            "钻石": "diamond",
            "diamond": "diamond",
            "rhombus": "diamond",
            "星形": "star",
            "星星": "star",
            "star": "star",
            "圆形": "circle",
            "圆": "circle",
            "circle": "circle",
            "三角形": "triangle",
            "三角": "triangle",
            "triangle": "triangle",
            "六边形": "hexagon",
            "六角形": "hexagon",
            "hexagon": "hexagon",
            "多边形": "polygon",
            "polygon": "polygon",
            "心形": "heart",
            "爱心": "heart",
            "heart": "heart",
            "矩形": "rectangle",
            "方形": "rectangle",
            "正方形": "rectangle",
            "rectangle": "rectangle",
            "square": "rectangle",
        }
        return self._find_alias(text, container_aliases, default)

    def _infer_layout(self, text: str) -> str:
        if any(k in text for k in ["整幅", "满地", "全图"]):
            return "allover_repeat"
        if any(k in text for k in ["边框", "框", "花边"]):
            return "framed"
        if any(k in text for k in ["两侧", "边带"]):
            return "side_bands"
        return "centered"

    def _size_from_text(self, text: str) -> int:
        if any(k in text for k in ["大", "宽", "明显"]):
            return 18
        if any(k in text for k in ["小", "细"]):
            return 12
        return 16

    def _normalize_region(self, region: Dict[str, Any], motif_role: str = "", motif_type: str = "") -> Dict[str, Any]:
        region = dict(region or {})
        if region.get("type") == "full":
            full = {"type": "full"}
            for key in ("shape", "mask_shape", "center", "size", "period_x", "period_y"):
                if key in region:
                    full[key] = region[key]
            return full
        if (
            "x_range" in region or "x_start" in region or "x_end" in region
            or "x1" in region or "x2" in region or "start" in region or "end" in region
        ):
            try:
                inclusive = False
                if "x_range" in region and isinstance(region["x_range"], list):
                    x0, x1 = int(region["x_range"][0]), int(region["x_range"][1])
                elif "x1" in region or "x2" in region:
                    x0, x1 = int(region.get("x1", 0)), int(region.get("x2", 0))
                elif isinstance(region.get("start"), list) and isinstance(region.get("end"), list):
                    x0, x1 = int(region["start"][0]), int(region["end"][0])
                    inclusive = True
                else:
                    x0, x1 = int(region.get("x_start", 0)), int(region.get("x_end", 0))
                region["width"] = max(1, abs(x1 - x0) + (1 if inclusive else 0))
                region["side"] = "left" if min(x0, x1) < 20 else "right"
            except Exception:
                pass
        if (
            "y_range" in region or "y_start" in region or "y_end" in region
            or "y1" in region or "y2" in region or "start" in region or "end" in region
        ):
            try:
                inclusive = False
                if "y_range" in region and isinstance(region["y_range"], list):
                    y0, y1 = int(region["y_range"][0]), int(region["y_range"][1])
                elif "y1" in region or "y2" in region:
                    y0, y1 = int(region.get("y1", 0)), int(region.get("y2", 40))
                elif isinstance(region.get("start"), list) and isinstance(region.get("end"), list):
                    y0, y1 = int(region["start"][1]), int(region["end"][1])
                    inclusive = True
                else:
                    y0, y1 = int(region.get("y_start", 0)), int(region.get("y_end", 40))
                region["height"] = max(1, abs(y1 - y0) + (1 if inclusive else 0))
            except Exception:
                pass
        center = region.get("center", [20, 20])
        if not isinstance(center, list) or len(center) < 2:
            center = [20, 20]
        # frame/border 类型不受 size=20 上限限制，它们需要足够大以容纳子区域
        _is_frame = motif_role in {"border", "frame"} or motif_type == "frame"
        if _is_frame:
            size = max(4, int(region.get("size", 16)))  # 只限制下限，不限制上限
        else:
            size = max(4, min(20, int(region.get("size", 16))))
        region["center"] = [max(0, min(39, int(center[0]))), max(0, min(39, int(center[1])))]
        region["size"] = size
        return region

    def _normalize_side_band_motif(self, motif: PatternMotif) -> None:
        rid = motif.motif_id.lower()
        has_side_geometry = any(k in motif.region for k in ["x_range", "x_start", "x_end", "start", "end", "side", "width"])
        has_side_name = any(k in rid for k in ["left", "right", "左", "右", "side", "band"])
        if motif.motif_type in {"stripe", "column"} and (has_side_geometry or has_side_name):
            motif.role = "side_band"
            if "right" in rid or "右" in rid:
                motif.region["side"] = "right"
            elif "left" in rid or "左" in rid:
                motif.region["side"] = "left"
            motif.region.setdefault("width", int(motif.region.get("size", 5)))
            # Side bands should not become parent containers for central
            # motifs, but they may still sit visually inside an outer frame.
            if motif.parent_id and motif.parent_id != "frame":
                motif.parent_id = None

    def _best_central_container(self, plan: PatternPlan) -> Optional[PatternMotif]:
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        candidates = [
            m for m in plan.motifs
            if m.role in {"center", "border"} and m.motif_type in geometry
        ]
        if not candidates:
            return None
    
        def score(m: PatternMotif) -> tuple:
            rid = m.motif_id.lower()
            frame_penalty = 2 if (
                m.motif_type == "frame"
                or any(k in rid for k in ["frame", "border", "\u8fb9\u6846", "outer"])
            ) else 0
            try:
                size = int(m.region.get("size", 0))
            except Exception:
                size = 0
            # 最大尺寸优先：嵌套几何形状中，最大的是自然容器
            # 不再对 border 角色加 penalty，因为外层容器通常是 border 角色
            return (-size, frame_penalty)
    
        return sorted(candidates, key=score)[0]

    def _repair_complex_layer_links(self, plan: PatternPlan) -> None:
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        containers = {
            m.motif_id: m for m in plan.motifs
            if m.motif_type in geometry
            and m.role in {"center", "border"}
        }
        central = self._best_central_container(plan)
        if central is None:
            return

        texture_effects = {"wave_tuck", "lace", "relief", "honeycomb", "seed", "rib", "links", "cable"}
        for motif in plan.motifs:
            if motif is central:
                continue
            if motif.role in {"side_band", "allover", "background", "ground"}:
                motif.parent_id = None
                continue
            parent = containers.get(str(motif.parent_id)) if motif.parent_id else None
            bad_parent = False
            if motif.parent_id and parent is None:
                bad_parent = True
            if parent is not None and parent.role == "side_band":
                bad_parent = True

            rid = motif.motif_id.lower()
            looks_inner = any(k in rid for k in ["inner", "inside", "fill", "mesh", "wave", "cable", "内部", "里面"])
            is_texture = motif.effect in texture_effects
            is_geometric = motif.motif_type in geometry

            # 几何形状或纹理效果的内层 motif，若无有效父级，链接到 central
            if (is_texture or is_geometric) and looks_inner:
                shape_hint = str(motif.region.get("shape", "")).lower()
                if (
                    bad_parent
                    or parent is None
                    or shape_hint == central.motif_type
                    or shape_hint in {"frame", "border", "stripe", "column"}
                ):
                    motif.parent_id = central.motif_id
                    motif.region["shape"] = central.motif_type

    def _flatten_redundant_containers(self, plan: PatternPlan) -> None:
        """消除多余的 plain 容器层。

        当 LLM 创建了一个 plain 容器（如 inner_circle）只包含一个同形状的
        更小兄弟（如 cable_center）时，移除该容器，让内容直接挂到祖父级。
        例如：outer_circle → inner_circle(plain) → cable_center(cable)
        变为：outer_circle → cable_center(cable)
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        to_remove = set()

        for motif in plan.motifs:
            # 只处理 plain 几何容器
            if motif.effect not in {"plain", "none", ""}:
                continue
            if motif.motif_type not in geometry:
                continue
            if not motif.parent_id:
                continue

            # 查找该容器的子级
            children = [
                m for m in plan.motifs
                if m.parent_id == motif.motif_id
                and m.motif_type in geometry
            ]
            if len(children) != 1:
                continue

            child = children[0]
            # 检查是否同形状
            parent_shape = str(motif.region.get("shape", motif.motif_type)).lower()
            child_shape = str(child.region.get("shape", child.motif_type)).lower()
            if parent_shape != child_shape:
                continue

            # 移除冗余容器，将子级挂到祖父级
            grandparent_id = motif.parent_id
            child.parent_id = grandparent_id
            to_remove.add(motif.motif_id)
            logger.info(
                f"[flatten] removed redundant container {motif.motif_id}, "
                f"{child.motif_id} now child of {grandparent_id}"
            )

        # 从 plan.motifs 中移除冗余容器
        if to_remove:
            plan.motifs = [m for m in plan.motifs if m.motif_id not in to_remove]

    def _repair_motif_shape_from_name(self, plan: PatternPlan) -> None:
        """根据 motif_id 中的几何形状关键词修正 motif_type 和 region.shape。

        LLM 常将菱形、三角形等创建为 circle，但名称中包含正确的形状关键词。
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        _shape_keywords = {
            "diamond": "diamond",
            "菱形": "diamond",
            "triangle": "triangle",
            "三角形": "triangle",
            "hexagon": "hexagon",
            "六边形": "hexagon",
            "heart": "heart",
            "心形": "heart",
            "star": "star",
            "星形": "star",
            "rectangle": "rectangle",
            "矩形": "rectangle",
            "方形": "rectangle",
        }
        for motif in plan.motifs:
            mid = motif.motif_id.lower()
            # 检查名称中是否包含形状关键词
            detected_shape = None
            for keyword, shape_name in _shape_keywords.items():
                if keyword in mid:
                    detected_shape = shape_name
                    break
            if detected_shape is None:
                continue
            # 如果 motif_type 已经是正确的形状，跳过
            if motif.motif_type == detected_shape:
                continue
            # 修正 motif_type 和 region.shape
            old_type = motif.motif_type
            motif.motif_type = detected_shape
            if isinstance(motif.region, dict):
                motif.region["shape"] = detected_shape
            logger.info(
                f"[shape_repair] {motif.motif_id}: {old_type} -> {detected_shape} "
                f"(name contains '{detected_shape}')"
            )

    def _merge_same_shape_border(self, plan: PatternPlan) -> None:
        """同形边框合并：当 border motif 与 center motif 形状相同时，转为边框环带事件源。
    
        用户说“圆形内竖条纹，边框波浪吊目”时，意图是一个圆形：
        - 内部：竖条纹（rib）
        - 边界：波浪（wave_tuck）
        而不是两个同心圆。当 LLM 将边框创建为独立的同形 border motif 时，
        将 border 转为环带事件源：去掉填充和轮廓，只保留事件，
        并通过 inner_exclude 让事件只出现在边框环带上。
    
        合并策略：
        - 保留 center motif（内部效果）
        - 吸收 border 的 border_thickness
        - 用 border 的 size（通常稍大）更新 center 的 size
        - border motif 转为环带事件源：去掉 border_style，添加 inner_exclude
        """
        border_motifs = [m for m in plan.motifs if m.role == "border"]
        center_motifs = [m for m in plan.motifs if m.role == "center"]
    
        for border in border_motifs:
            # 查找同形状的 center motif
            matching_center = None
            for center in center_motifs:
                if center.motif_type == border.motif_type:
                    matching_center = center
                    break
    
            if matching_center is None:
                continue
    
            # 合并：吸收 border 的属性到 center
            border_thickness = int(border.params.get("border_thickness", 2) or 2)
            matching_center.params["border_thickness"] = border_thickness
    
            # 用 border 的 size 更新 center（border 通常稍大）
            border_size = int(border.region.get("size", 0)) if isinstance(border.region, dict) else 0
            center_size = int(matching_center.region.get("size", 0)) if isinstance(matching_center.region, dict) else 0
            if border_size > center_size and isinstance(matching_center.region, dict):
                matching_center.region["size"] = border_size
    
            # 将 border 转为环带事件源：
            # 1. 去掉 border_style，避免渲染第二个轮廓
            border.params["border_style"] = "none"
            border.params["border_thickness"] = 0
    
            # 2. 添加 inner_exclude 排除内部区域，事件只出现在边框环带
            inner_size = max(0, border_size - border_thickness)
            center_pos = border.region.get("center", [20, 20]) if isinstance(border.region, dict) else [20, 20]
            border.region["inner_exclude"] = {
                "shape": border.motif_type,
                "center": list(center_pos),
                "size": inner_size,
            }
    
            logger.info(
                f"[border_merge] {border.motif_id} ({border.motif_type}) -> ring event source: "
                f"size={border_size}, inner_exclude size={inner_size}, border_thickness={border_thickness}"
            )
            break  # 只合并第一个匹配的 border

    def _setup_transition_regions(self, plan: PatternPlan) -> None:
        """为 transition 角色区域设置 inner_exclude，形成环形过渡带。

        用户说“圆形外稀疏平针过渡”时，LLM 生成 role=transition 的区域。
        该区域应是圆形与背景之间的环形带。本方法为 transition 区域
        添加 inner_exclude（排除内部圆形），使其成为环形。
        """
        transition_motifs = [m for m in plan.motifs if m.role in ("transition", "surround")]
        if not transition_motifs:
            return

        center_motifs = [m for m in plan.motifs if m.role == "center"]

        for trans in transition_motifs:
            if not isinstance(trans.region, dict):
                continue

            # 始终确保 transition/surround 不画边框
            trans.params["border_style"] = "none"

            if trans.region.get("inner_exclude"):
                continue  # 已有 inner_exclude，跳过设置

            trans_center = trans.region.get("center", [20, 20])
            trans_size = int(trans.region.get("size", 0))

            # 查找同中心的最大 center motif 作为 inner_exclude
            best_center = None
            best_size = 0
            for cm in center_motifs:
                if not isinstance(cm.region, dict):
                    continue
                cm_center = cm.region.get("center", [20, 20])
                cm_size = int(cm.region.get("size", 0))
                # 检查是否同中心（允许小偏差）
                if abs(cm_center[0] - trans_center[0]) <= 2 and abs(cm_center[1] - trans_center[1]) <= 2:
                    if cm_size < trans_size and cm_size > best_size:
                        best_center = cm
                        best_size = cm_size

            if best_center is None:
                continue

            # 设置 inner_exclude
            inner_shape = best_center.motif_type
            inner_center = best_center.region.get("center", [20, 20])
            trans.region["inner_exclude"] = {
                "shape": inner_shape,
                "center": list(inner_center),
                "size": best_size,
            }
            # 确保 transition 的 shape 与内部形状一致
            if trans.motif_type == "frame":
                trans.motif_type = best_center.motif_type
            # 不画边框（环形区域的边界由内部/外部形状定义）
            trans.params["border_style"] = "none"
            logger.info(
                f"[transition_setup] {trans.motif_id}: inner_exclude "
                f"{inner_shape} size={best_size} (from {best_center.motif_id})"
            )

    # prompt 纹理关键词 → effect 映射
    _TEXTURE_KEYWORDS = {
        "竖条纹": "rib", "条纹": "rib", "rib": "rib",
        "波浪": "wave_tuck", "wave": "wave_tuck",
        "蜂巢": "honeycomb", "蜂窝": "honeycomb", "honeycomb": "honeycomb",
        "网眼": "mesh", "mesh": "mesh",
        "麻花": "cable", "菱形": "cable", "cable": "cable",
        "罗纹": "rib",
    }

    def _repair_plain_center_effect(self, plan: PatternPlan, user_input: str) -> None:
        """修复 center motif 的 effect=plain，当 prompt 明确指定了纹理时。

        LLM 有时将"竖条纹"等纹理错误映射为 plain，导致圆形内部无纹理。
        本方法从 prompt 中检测纹理关键词，修复 center 的 effect。
        """
        if not user_input:
            return

        # 查找 effect=plain 的 center motif
        for motif in plan.motifs:
            if motif.role != "center":
                continue
            if motif.effect not in ("plain", "none", ""):
                continue  # 已有纹理，不覆盖

            # 在 prompt 中查找纹理关键词
            detected_effect = None
            for keyword, effect in self._TEXTURE_KEYWORDS.items():
                if keyword in user_input:
                    detected_effect = effect
                    break

            if detected_effect is None:
                continue

            # 修复 effect
            old_effect = motif.effect
            motif.effect = detected_effect
            # 确保有默认参数
            defaults = self._default_params(detected_effect, user_input or "")
            for pk, pv in defaults.items():
                motif.params.setdefault(pk, pv)
            logger.info(
                f"[effect_repair] {motif.motif_id}: effect {old_effect} -> {detected_effect} "
                f"(prompt keyword matched)"
            )
            break  # 只修复第一个 center

    def _repair_ring_motifs(self, plan: PatternPlan) -> None:
        """修复被 LLM 误解为 allover/panel 的环形 motif。

        当 prompt 包含 "环形区域" 时，LLM 常将环形纹理创建为 allover/panel，
        导致整个画布都是该纹理。本方法检测并修复此类 motif：
        1. 名称包含 "ring" 或 "环"
        2. 当前是 panel/allover（非几何形状）
        3. 存在嵌套的圆形容器

        修复后：转换为 circle/center，size 取外层容器和内层容器的中间值，
        并添加 inner_exclude 排除内层容器。
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        # 查找环形 motif：名称包含 ring/环，且当前不是几何形状
        ring_motif = None
        for motif in plan.motifs:
            mid = motif.motif_id.lower()
            if "ring" in mid or "环" in mid:
                if motif.motif_type not in geometry:
                    ring_motif = motif
                    break
        if ring_motif is None:
            return

        # 查找嵌套的圆形容器
        circles = [
            m for m in plan.motifs
            if m.motif_type == "circle" and m.role in {"center", "border"}
        ]
        if len(circles) < 2:
            return

        # 按 size 降序排列
        def get_size(m: PatternMotif) -> int:
            try:
                return int(m.region.get("size", 0))
            except Exception:
                return 0
        circles_sorted = sorted(circles, key=get_size, reverse=True)
        outer = circles_sorted[0]  # 最大圆
        inner = circles_sorted[1]  # 次大圆

        outer_size = get_size(outer)
        inner_size = get_size(inner)

        # 计算环形 size：取外层和内层的中间值
        ring_size = (outer_size + inner_size) // 2
        if ring_size <= inner_size:
            ring_size = inner_size + 2

        # 获取中心坐标
        center = outer.region.get("center", [20, 20])

        # 修复 ring motif：标记为 ring 类型而非 circle
        # 这样下游知道这是环形区域（2个圆之间的空间），不是第三个圆
        ring_motif.motif_type = "circle"  # 几何形状仍是 circle，但 type=ring
        ring_motif.role = "center"
        ring_motif.region = {
            "type": "ring",  # 关键：标记为 ring 类型
            "center": list(center),
            "size": ring_size,
            "shape": "circle",
            "inner_exclude": {
                "shape": inner.motif_type,
                "center": list(inner.region.get("center", [20, 20])),
                "size": inner_size,
            },
        }
        logger.info(
            f"[ring_repair] {ring_motif.motif_id}: panel/allover -> ring/center "
            f"size={ring_size} (between outer={outer_size} and inner={inner_size})"
        )

    def _distribute_overlapping_siblings(self, plan: PatternPlan) -> None:
        """分布同形状且中心重叠的兄弟 motif。

        LLM 常将多个同形状 motif 放在同一中心（如三个圆形都在 [20,20]）。
        本方法检测此类重叠并根据名称中的位置关键词重新分布。
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        # 位置关键词映射（相对于画布中心的偏移比例）
        _position_offsets = {
            # 水平分布
            "left": (-0.35, 0), "左": (-0.35, 0),
            "center": (0, 0), "中": (0, 0),
            "right": (0.35, 0), "右": (0.35, 0),
            # 垂直分布
            "top": (0, -0.3), "上": (0, -0.3),
            "bottom": (0, 0.3), "下": (0, 0.3),
            # 组合位置
            "top_left": (-0.3, -0.25), "左上": (-0.3, -0.25),
            "top_right": (0.3, -0.25), "右上": (0.3, -0.25),
            "bottom_left": (-0.3, 0.25), "左下": (-0.3, 0.25),
            "bottom_right": (0.3, 0.25), "右下": (0.3, 0.25),
        }
        # 按 (shape, parent_id) 分组
        groups: Dict[tuple, list] = {}
        for motif in plan.motifs:
            if motif.motif_type not in geometry:
                continue
            region = motif.region if isinstance(motif.region, dict) else {}
            center = region.get("center")
            if not center or len(center) < 2:
                continue
            try:
                size = int(region.get("size", 0))
            except Exception:
                size = 0
            if size <= 0:
                continue
            key = (motif.motif_type, motif.parent_id or "")
            groups.setdefault(key, []).append(motif)

        for (shape, parent_id), siblings in groups.items():
            if len(siblings) < 2:
                continue
            # 检测中心重叠的簇
            centers = []
            for m in siblings:
                r = m.region if isinstance(m.region, dict) else {}
                c = r.get("center", [20, 20])
                centers.append((int(c[0]), int(c[1])))
            # 检查是否所有中心都相同或非常接近
            unique_centers = set(centers)
            if len(unique_centers) <= 1:
                # 所有 motif 在同一中心，需要分布
                # 从 plan.canvas 获取画布尺寸
                canvas_w = int(plan.canvas.get("width", 40))
                canvas_h = int(plan.canvas.get("height", 40))
                canvas_center_r = canvas_h // 2
                canvas_center_c = canvas_w // 2
                # 根据名称中的位置关键词分配偏移
                distributed = False
                for m in siblings:
                    mid = m.motif_id.lower()
                    offset = None
                    for keyword, off in _position_offsets.items():
                        if keyword in mid:
                            offset = off
                            break
                    if offset is not None:
                        # 应用偏移
                        new_r = int(canvas_center_r + offset[0] * canvas_h)
                        new_c = int(canvas_center_c + offset[1] * canvas_w)
                        # 确保在画布内
                        new_r = max(5, min(canvas_h - 5, new_r))
                        new_c = max(5, min(canvas_w - 5, new_c))
                        if isinstance(m.region, dict):
                            m.region["center"] = [new_r, new_c]
                        distributed = True
                        logger.info(
                            f"[sibling_dist] {m.motif_id}: center [{centers[0]}] -> [{new_r}, {new_c}] "
                            f"(keyword='{keyword}')"
                        )
                # 如果没有匹配到位置关键词，自动水平分布
                if not distributed and len(siblings) >= 2:
                    spacing = canvas_w // (len(siblings) + 1)
                    for i, m in enumerate(siblings):
                        new_c = spacing * (i + 1)
                        new_r = canvas_center_r
                        if isinstance(m.region, dict):
                            m.region["center"] = [new_r, new_c]
                        logger.info(
                            f"[sibling_dist] {m.motif_id}: center [{centers[0]}] -> [{new_r}, {new_c}] "
                            f"(auto horizontal)"
                        )

    def _add_sibling_exclusion_masks(self, plan: PatternPlan) -> None:
        """为嵌套的同中心兄弟区域添加 inner_exclude 掩码。

        当两个兄弟区域共享同一父级且形状相同时，较大的区域应排除较小区域的
        空间，形成环形结构。例如：mesh_ring(size=14) 和 inner_circle(size=10)
        都是 outer_circle 的子级，mesh_ring 应排除 inner_circle 的区域。
        """
        geometry = {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
        # 按 parent_id 分组
        children_by_parent: Dict[str, list] = {}
        for motif in plan.motifs:
            pid = motif.parent_id
            if not pid:
                continue
            if motif.motif_type not in geometry:
                continue
            children_by_parent.setdefault(pid, []).append(motif)

        for pid, children in children_by_parent.items():
            if len(children) < 2:
                continue
            # 按 size 降序排列
            def get_size(m: PatternMotif) -> int:
                try:
                    return int(m.region.get("size", 0))
                except Exception:
                    return 0
            children_sorted = sorted(children, key=get_size, reverse=True)
            # 对每个较大的区域，排除所有比它小的同中心兄弟
            for i, larger in enumerate(children_sorted):
                for smaller in children_sorted[i + 1:]:
                    larger_size = get_size(larger)
                    smaller_size = get_size(smaller)
                    if smaller_size >= larger_size:
                        continue
                    # 检查是否同中心（距离 < 2）
                    try:
                        lc = larger.region.get("center", [20, 20])
                        sc = smaller.region.get("center", [20, 20])
                        dist = abs(int(lc[0]) - int(sc[0])) + abs(int(lc[1]) - int(sc[1]))
                    except Exception:
                        continue
                    if dist > 2:
                        continue
                    # 检查形状是否相同
                    larger_shape = str(larger.region.get("shape", "")).lower()
                    smaller_shape = str(smaller.region.get("shape", "")).lower()
                    if larger_shape and smaller_shape and larger_shape != smaller_shape:
                        continue
                    # 只有当 larger 自身有纹理事件时，才应排除 smaller
                    # 如果 larger 是 plain（无事件），它只是 smaller 的容器，不应变成环形
                    _no_event_effects = {"plain", "none", ""}
                    if larger.effect in _no_event_effects:
                        continue
                    # 为 larger 添加 inner_exclude 掩码
                    exclude = {
                        "shape": smaller.motif_type,
                        "center": smaller.region.get("center", [20, 20]),
                        "size": smaller_size,
                    }
                    larger.region.setdefault("inner_exclude", exclude)
                    logger.debug(
                        f"[sibling_exclude] {larger.motif_id} excludes {smaller.motif_id} "
                        f"(size {smaller_size} inside {larger_size})"
                    )

    def _repair_ring_role_motifs(self, plan: PatternPlan) -> None:
        """为 role=ring 或 region.type=ring 的 motif 自动设置 inner_exclude 和外层尺寸。

        当 LLM 创建环形区域（如"矩形内套小矩形，环形区域网眼"）时，
        ring motif 可能没有 inner_exclude，或者尺寸不正确。
        本方法：
        1. 找同中心的较大 frame 作为 ring 的外层边界（设置 ring 的 size）
        2. 找同中心的较小 motif 作为 inner_exclude（形成环形）
        """
        for motif in plan.motifs:
            # 检查是否是 ring 类型
            is_ring = (
                motif.role == "ring"
                or str(motif.region.get("type", "")).lower() == "ring"
                or "ring" in motif.motif_id.lower()
            )
            if not is_ring:
                continue
            ring_center = motif.region.get("center", [20, 20])
            try:
                ring_r, ring_c = int(ring_center[0]), int(ring_center[1])
            except Exception:
                ring_r, ring_c = 20, 20
            ring_size = int(motif.region.get("size", 0))
            
            # 如果 ring 已有 outer_size 字段，用它作为外层尺寸
            outer_size_field = motif.region.get("outer_size")
            if outer_size_field is not None:
                try:
                    outer_sz = int(outer_size_field)
                    if outer_sz > ring_size:
                        motif.region["size"] = outer_sz
                        ring_size = outer_sz
                except Exception:
                    pass
            
            # 找同中心的较大 frame 作为外层边界（仅当没有 outer_size 字段时）
            if outer_size_field is None:
                best_outer = None
                best_outer_size = ring_size
                for other in plan.motifs:
                    if other is motif:
                        continue
                    if other.role not in {"border", "frame"}:
                        continue
                    other_center = other.region.get("center", [20, 20])
                    try:
                        or2, oc2 = int(other_center[0]), int(other_center[1])
                    except Exception:
                        continue
                    if abs(or2 - ring_r) + abs(oc2 - ring_c) > 3:
                        continue
                    other_size = int(other.region.get("size", 0))
                    if other_size > best_outer_size:
                        best_outer_size = other_size
                        best_outer = other
                
                # 扩展 ring 的 size 到外层 frame 的 size
                if best_outer is not None and best_outer_size > ring_size:
                    motif.region["size"] = best_outer_size
                    logger.info(
                        f"[ring_repair] {motif.motif_id}: expanded size {ring_size} -> {best_outer_size} "
                        f"(matching outer frame {best_outer.motif_id})"
                    )
                    ring_size = best_outer_size
            
            # 已有 inner_exclude 则跳过
            if motif.region.get("inner_exclude"):
                continue
            
            # 优先使用 inner_size/ring_inner_size/outer_size 字段构造 inner_exclude
            inner_size_field = motif.region.get("inner_size") or motif.region.get("ring_inner_size")
            if inner_size_field is not None:
                try:
                    inner_sz = int(inner_size_field)
                except Exception:
                    inner_sz = 0
                if inner_sz > 0:
                    # 找同中心且尺寸匹配的 motif 作为 inner_exclude 的形状参考
                    inner_shape = "rectangle"  # 默认
                    for other in plan.motifs:
                        if other is motif:
                            continue
                        other_center = other.region.get("center", [20, 20])
                        try:
                            or2 = int(other_center[0])
                            oc2 = int(other_center[1])
                        except Exception:
                            continue
                        if abs(or2 - ring_r) + abs(oc2 - ring_c) > 3:
                            continue
                        other_sz = int(other.region.get("size", 0))
                        if abs(other_sz - inner_sz) <= 2:
                            inner_shape = str(other.region.get("shape", other.motif_type)).lower()
                            break
                    motif.region["inner_exclude"] = {
                        "shape": inner_shape,
                        "center": [ring_r, ring_c],
                        "size": inner_sz,
                    }
                    logger.info(
                        f"[ring_repair] {motif.motif_id}: inner_exclude from inner_size={inner_sz} "
                        f"(shape={inner_shape})"
                    )
                    continue
            
            # 回退：找同中心的较小兄弟 motif 作为 inner_exclude
            best_inner = None
            best_inner_size = 0
            for other in plan.motifs:
                if other is motif:
                    continue
                if other.role in {"ground", "allover"}:
                    continue
                if other.motif_type == "panel":
                    continue
                other_center = other.region.get("center", [20, 20])
                try:
                    or2, oc2 = int(other_center[0]), int(other_center[1])
                except Exception:
                    continue
                if abs(or2 - ring_r) + abs(oc2 - ring_c) > 3:
                    continue
                other_size = int(other.region.get("size", 0))
                if other_size >= ring_size:
                    continue
                # 形状兼容检查
                ring_shape = str(motif.region.get("shape", motif.motif_type)).lower()
                other_shape = str(other.region.get("shape", other.motif_type)).lower()
                if other_shape and ring_shape and other_shape != ring_shape:
                    _rect_aliases = {"frame", "border", "rectangle", "rect", "box"}
                    if not (other_shape in _rect_aliases and ring_shape in _rect_aliases):
                        continue
                if other_size > best_inner_size:
                    best_inner_size = other_size
                    best_inner = other
            
            if best_inner is not None:
                exclude = {
                    "shape": best_inner.motif_type,
                    "center": list(best_inner.region.get("center", [20, 20])),
                    "size": best_inner_size,
                }
                motif.region["inner_exclude"] = exclude
                logger.info(
                    f"[ring_repair] {motif.motif_id}: added inner_exclude -> "
                    f"{best_inner.motif_id} (size={best_inner_size})"
                )

    def _repair_nested_frame_borders(self, plan: PatternPlan, user_input: str = "") -> None:
        """修复嵌套边框语义：当 prompt 描述"大X内套小X"时，确保内部 X 有可见边框。
        
        LLM 可能将内层边框错误地生成为 type=panel 或没有 border_thickness，
        此方法根据 prompt 语义自动修复。
        """
        import re
        prompt_lower = user_input.lower()
        
        # 检测嵌套语义模式
        # "大矩形内套小矩形" / "大圆内套小圆" / "外框内嵌内框" 等
        nested_patterns = [
            r"大(.{1,3})内套小\1",  # 大X内套小X
            r"外(.{1,3})内嵌内\1",  # 外X内嵌内X
            r"(.{1,3})内嵌套\1",    # X内嵌套X
            r"(.{1,3})里套(.{1,3})",  # X里套Y
        ]
        
        has_nested_semantic = False
        for pattern in nested_patterns:
            if re.search(pattern, prompt_lower):
                has_nested_semantic = True
                break
        
        if not has_nested_semantic:
            return
        
        # 查找 border/frame 角色的 motif 作为外层
        outer_frames = [m for m in plan.motifs if m.role in {"border", "frame"} and m.motif_type == "frame"]
        if not outer_frames:
            return
        
        # 查找中心区域的 motif 作为内层（应该是边框）
        for motif in plan.motifs:
            if motif.role not in {"center"}:
                continue
            if motif.motif_type in {"frame", "panel"}:
                # 检查是否同中心（嵌套关系）
                is_nested = False
                for outer in outer_frames:
                    outer_center = outer.region.get("center", [20, 20])
                    motif_center = motif.region.get("center", [20, 20])
                    try:
                        dist = abs(int(outer_center[0]) - int(motif_center[0])) + abs(int(outer_center[1]) - int(motif_center[1]))
                        if dist <= 3:  # 同中心或接近
                            is_nested = True
                            break
                    except Exception:
                        continue
                
                if is_nested:
                    # 修复：确保内层有边框
                    if motif.motif_type == "panel":
                        motif.motif_type = "frame"
                        logger.info(
                            f"[nested_frame_repair] {motif.motif_id}: type panel -> frame "
                            f"(nested frame semantic detected)"
                        )
                    
                    # 确保有 border_thickness
                    if not motif.params.get("border_thickness"):
                        motif.params["border_thickness"] = 1
                        logger.info(
                            f"[nested_frame_repair] {motif.motif_id}: added border_thickness=1"
                        )
                    
                    # 确保 region 有 shape
                    if not motif.region.get("shape"):
                        motif.region["shape"] = "rectangle"

    def _normalize_params(self, effect: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params or {})
        defaults = self._default_params(effect, "")
        defaults.update(params)
        for key in ("period_x", "period_y", "cable_period"):
            if key in defaults:
                defaults[key] = max(2, min(12, int(defaults[key])))
        if "cable_pairs" in defaults:
            defaults["cable_pairs"] = max(1, min(4, int(defaults["cable_pairs"])))
        return defaults

    def _region_to_placement(self, motif: PatternMotif) -> Dict[str, Any]:
        placement = dict(motif.region)
        # 保留 motif_type 供下游边框决策使用
        placement["motif_type"] = motif.motif_type
        if motif.role in {"allover", "background", "ground"}:
            return {"type": "full"}
        if placement.get("type") == "full":
            shape = placement.get("shape") or self._motif_to_visual_shape(motif.motif_type)
            params = dict(motif.params or {})
            repeat_shape = shape if shape not in {"panel", "allover", "mesh", "wave"} else None
            if repeat_shape is not None:
                repeat = {
                    "type": "repeat",
                    "repeat": True,
                    "shape": repeat_shape or shape,
                    "mask_shape": repeat_shape or shape,
                    "center": placement.get("center", [20, 20]),
                    "size": int(params.get("size", placement.get("size", 5))),
                    "period_x": int(params.get("period_x", placement.get("period_x", 10))),
                    "period_y": int(params.get("period_y", placement.get("period_y", 10))),
                }
                if motif.parent_id:
                    repeat["parent_id"] = motif.parent_id
                    repeat["clip_to_parent"] = True
                return repeat
            return {"type": "full"}
        # difference 类型：外区减去内区 → 转换为完整布局 + 内圈排除
        if placement.get("type") == "difference":
            outer = placement.get("outer", {})
            inner = placement.get("inner", {})
            outer_shape = str(placement.get("shape", "rectangle")).lower()
            outer_center = outer.get("center", placement.get("center", [20, 20]))
            # 从 outer bounds 推导 size
            ob = outer.get("bounds", {})
            if ob:
                try:
                    bw = abs(int(ob.get("x2", 39)) - int(ob.get("x1", 0)))
                    bh = abs(int(ob.get("y2", 39)) - int(ob.get("y1", 0)))
                    outer_size = max(bw, bh) // 2 + 1  # +1 保证覆盖边界像素
                except Exception:
                    outer_size = 20
            else:
                outer_size = int(outer.get("size", placement.get("size", 20)))
            inner_center = inner.get("center", outer_center)
            inner_size = int(inner.get("size", 10))
            inner_shape = str(inner.get("shape", outer_shape)).lower()
            # 外圈必须大于内圈至少4（每侧≥2 cells），否则环形区域不可见
            if outer_size <= inner_size + 3:
                _orig_outer = outer_size
                outer_size = inner_size + 4
                logger.warning(
                    f"  [{motif.motif_id}] difference outer_size({_orig_outer}) 与 inner_size({inner_size}) "
                    f"间距不足，已调整为 outer_size={outer_size}"
                )
            placement["type"] = "full" if outer_size >= 19 else "local"
            placement["center"] = outer_center
            placement["size"] = outer_size
            placement["shape"] = outer_shape
            placement["mask_shape"] = outer_shape
            placement["inner_exclude"] = {
                "center": inner_center,
                "size": inner_size,
                "shape": inner_shape,
            }
            logger.info(
                f"  [{motif.motif_id}] difference → outer({outer_shape}, size={outer_size}) "
                f"- inner({inner_shape}, size={inner_size})"
            )
        # ring 类型：转换为外圈形状 + 内圈排除
        if placement.get("type") == "ring":
            outer_shape = str(placement.get("shape", "circle")).lower()
            outer_center = placement.get("outer_center", placement.get("center", [20, 20]))
            inner_center = placement.get("inner_center", [20, 20])

            # inner_size: 支持 inner_size / inner_radius / inner_diameter 三种字段名
            inner_size = placement.get("inner_size")
            if inner_size is None:
                ir = placement.get("inner_radius")
                if ir is not None:
                    inner_size = int(ir) * 2
                else:
                    inner_size = placement.get("inner_diameter", 16)
            inner_size = int(inner_size)

            # outer_size: 支持 outer_size / outer_radius / outer_border 推导
            outer_size = placement.get("outer_size")
            if outer_size is None:
                # outer_radius → 直径（与 inner_radius 对称）
                outer_radius = placement.get("outer_radius")
                if outer_radius is not None:
                    outer_size = int(outer_radius) * 2
                else:
                    ob = placement.get("outer_border")
                    if ob is not None:
                        outer_size = inner_size + int(ob) * 2
                    else:
                        # 回退到 region 的 size 字段（即 LLM 指定的整体大小）
                        outer_size = placement.get("size", 20)
            outer_size = int(outer_size)

            # 外圈必须大于内圈至少4（每侧≥2 cells），否则环形区域不可见
            # _ring_fixed 也可能已由 _preprocess_ring_motifs 设为 True
            _ring_fixed = bool(placement.get("_ring_fixed"))
            if outer_size <= inner_size + 3:
                _orig_outer = outer_size
                outer_size = inner_size + 4
                _ring_fixed = True
                logger.warning(
                    f"  [{motif.motif_id}] ring outer_size({_orig_outer}) 与 inner_size({inner_size}) "
                    f"间距不足，已调整为 outer_size={outer_size}"
                )

            placement["center"] = outer_center
            placement["size"] = outer_size
            placement["shape"] = outer_shape
            placement["mask_shape"] = outer_shape
            placement["inner_exclude"] = {
                "center": inner_center,
                "size": inner_size,
                "shape": outer_shape,
            }
            if _ring_fixed:
                placement["_ring_fixed"] = True
        placement.setdefault("center", [20, 20])
        placement.setdefault("size", 16)
        placement.setdefault("shape", self._motif_to_visual_shape(motif.motif_type))
        # 修正：从 top_left/bottom_right 或 bounds 重新计算 size
        tl = placement.get("top_left")
        br = placement.get("bottom_right")
        center = placement.get("center")
        bounds = motif.region.get("bounds")
        if bounds and not tl:
            # bounds 格式: {x1, y1, x2, y2}
            try:
                tl = [int(bounds.get("x1", 0)), int(bounds.get("y1", 0))]
                br = [int(bounds.get("x2", 39)), int(bounds.get("y2", 39))]
            except Exception:
                tl = br = None
        if tl and br and center:
            try:
                w = abs(int(br[0]) - int(tl[0]))
                h = abs(int(br[1]) - int(tl[1]))
                correct_size = (max(w, h) + 1) // 2
                old_size = int(placement.get("size", 16))
                if correct_size != old_size:
                    logger.warning(
                        f"  [{motif.motif_id}] size={old_size} 与坐标范围 "
                        f"推导的 size={correct_size} 不一致，已修正"
                    )
                    placement["size"] = correct_size
            except Exception:
                pass
        if motif.parent_id:
            placement["parent_id"] = motif.parent_id
            placement["clip_to_parent"] = True
        # 形状标准化：确保 "frame"/"border" 等语义词转为 "rectangle"
        _FRAME_TO_RECT = {"frame", "border", "rect", "square", "box"}
        cur_shape = str(placement.get("shape", "")).lower()
        cur_mask = str(placement.get("mask_shape", "")).lower()
        if cur_shape in _FRAME_TO_RECT:
            placement["shape"] = "rectangle"
        if cur_mask in _FRAME_TO_RECT:
            placement["mask_shape"] = "rectangle"
        # motif_type == "frame" 的边框特殊处理
        if motif.motif_type == "frame":
            region_shape = str(motif.region.get("shape", "")).lower()
            if region_shape and region_shape not in _FRAME_TO_RECT | {"rectangle", ""}:
                placement["shape"] = region_shape
                placement["mask_shape"] = region_shape
            else:
                placement["mask_shape"] = "rectangle"
                placement["shape"] = "rectangle"
        return placement

    def _motif_to_visual_shape(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {
            "eyelet": "mesh",
            "lace": "mesh",
            "rect": "rectangle",
            "square": "rectangle",
        }
        key = mapping.get(key, key)
        valid = {
            "diamond", "wave", "column", "stripe", "panel", "frame",
            "rectangle", "mesh", "circle", "triangle", "hexagon",
            "polygon", "heart", "star", "chevron", "zigzag", "cross",
            "allover",
        }
        return key if key in valid else "panel"

    def _effect_to_visual_effect(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {"eyelet": "lace", "mesh": "lace", "tuck": "wave_tuck", "wave": "wave_tuck"}
        key = mapping.get(key, key)
        return key if key in {"plain", "reverse", "cable", "wave_tuck", "rib", "links", "lace", "relief", "honeycomb", "seed"} else "plain"

    def _role_to_layout_role(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {"main": "center", "frame": "border", "fill": "center", "inner": "center", "accent": "center", "decoration": "center", "repeat": "allover", "background": "allover", "bg": "allover"}
        key = mapping.get(key, key)
        return key if key in {"center", "ground", "border", "side_band", "allover", "corner", "transition", "surround"} else "center"

    def _normalize_role(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {
            "frame": "border",
            "frame_outer": "border",
            "frame_inner": "border",
            "outline": "border",
            "outer": "border",
            "fill": "center",
            "inner": "center",
            "inside": "center",
            "main": "center",
            "accent": "center",
            "decoration": "center",
            "repeat": "allover",
            "background": "allover",
            "bg": "allover",
        }
        if key in mapping:
            return mapping[key]
        # LLM 常将方位词用作 role（如 "left"/"right"/"inner_left"）
        # 含 inner/inside 前缀 → center；纯方位词 → border
        if any(k in key for k in ["inner", "inside", "fill"]):
            return "center"
        if key in {"left", "right", "top", "bottom"}:
            return "border"
        return key

    def _infer_missing_parent_links(self, plan: PatternPlan) -> None:
        """Recover common layer relations when the LLM omits parent_id.

        Prompts such as "菱形内部波浪" often return two motifs but forget to
        connect the inner texture to the outer shape.  Without this link the
        downstream layer mask cannot clip the child.
        """
        containers = [
            m for m in plan.motifs
            if m.parent_id is None and (
                m.role == "border"
                or m.motif_type in {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
            )
        ]
        if not containers:
            return

        texture_types = {"wave", "mesh", "stripe", "column", "chevron", "zigzag"}
        texture_effects = {"wave_tuck", "lace", "relief", "honeycomb", "seed", "rib", "links"}
        for motif in plan.motifs:
            if motif.parent_id is not None:
                continue
            if motif.role in {"side_band", "allover", "corner", "transition", "surround"}:
                continue
            if motif in containers:
                continue
            rid = motif.motif_id.lower()
            looks_inner = any(k in rid for k in ["inner", "inside", "fill", "内部", "里面"])
            looks_texture = motif.motif_type in texture_types or motif.effect in texture_effects
            if not (looks_inner or looks_texture):
                continue

            center = motif.region.get("center", [20, 20])
            size = int(motif.region.get("size", 16))
            best = None
            best_size = 999
            for parent in containers:
                p_center = parent.region.get("center", [20, 20])
                p_size = int(parent.region.get("size", 16))
                if p_size < size:
                    continue
                try:
                    dist = abs(int(center[0]) - int(p_center[0])) + abs(int(center[1]) - int(p_center[1]))
                except Exception:
                    dist = 0
                if dist <= max(4, p_size // 2) and p_size < best_size:
                    best = parent
                    best_size = p_size
            if best is not None:
                motif.parent_id = best.motif_id
                motif.region.setdefault("shape", best.motif_type)

    def _validate_parent_assignments(self, plan: PatternPlan) -> None:
        """验证已有 parent_id 的空间合理性，修正 LLM 的错误父子指派。

        LLM 可能基于名称匹配（如 'inside_right' -> 'wave_inside_left'）而非空间包含关系
        来设置 parent_id。本方法检测并修正此类错误：如果另一个容器与 motif 的中心距离
        明显更近（不足当前父节点距离的一半），则重新指派父节点。
        """
        texture_effects = {"wave_tuck", "lace", "relief", "honeycomb", "seed", "rib", "links", "mesh"}
        containers = [
            m for m in plan.motifs
            if (
                m.role in {"border", "frame"}
                or m.motif_type in {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
            )
            and m.effect not in texture_effects
            and m.role not in {"center", "allover", "ground"}
        ]
        if len(containers) < 2:
            return

        for motif in plan.motifs:
            if not motif.parent_id:
                continue
            if motif.role in {"allover", "background", "ground", "side_band"}:
                continue

            center = motif.region.get("center", [20, 20])
            try:
                cr, cc = int(center[0]), int(center[1])
            except (TypeError, ValueError):
                continue

            # 计算当前父节点的距离
            current_parent = None
            current_dist = 999
            for c in containers:
                if c.motif_id == motif.parent_id:
                    try:
                        pc = c.region.get("center", [20, 20])
                        current_dist = abs(cr - int(pc[0])) + abs(cc - int(pc[1]))
                    except (TypeError, ValueError):
                        pass
                    current_parent = c
                    break

            if current_parent is None:
                continue

            # 寻找更近的容器
            best_alternative = None
            best_dist = current_dist
            for c in containers:
                if c.motif_id == motif.parent_id:
                    continue
                try:
                    pc = c.region.get("center", [20, 20])
                    dist = abs(cr - int(pc[0])) + abs(cc - int(pc[1]))
                except (TypeError, ValueError):
                    continue
                p_size = int(c.region.get("size", 0))
                m_size = int(motif.region.get("size", 0))
                if p_size < m_size:
                    continue  # 容器必须能包含 motif
                if dist < best_dist:
                    best_dist = dist
                    best_alternative = c

            # 如果更近的容器距离不足当前父节点距离的一半，重新指派
            if best_alternative is not None and best_dist < current_dist * 0.5:
                logger.warning(
                    f"  [{motif.motif_id}] parent reassigned: "
                    f"{motif.parent_id} (dist={current_dist}) -> "
                    f"{best_alternative.motif_id} (dist={best_dist})"
                )
                motif.parent_id = best_alternative.motif_id

    def _next_id(self, plan: PatternPlan, prefix: Any) -> str:
        stem = re.sub(r"[^a-zA-Z0-9_]+", "_", str(prefix or "motif")).strip("_") or "motif"
        existing = {m.motif_id for m in plan.motifs}
        idx = 1
        while f"{stem}_{idx}" in existing:
            idx += 1
        return f"{stem}_{idx}"
