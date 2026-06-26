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

    def render_visual_spec(self, plan: PatternPlan) -> VisualSpec:
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
            motif.region = self._normalize_region(motif.region)
            motif.params = self._normalize_params(motif.effect, motif.params)
            self._normalize_side_band_motif(motif)
        # 只在非随机来源时执行强修复，避免杀死随机多样性
        is_random = any(
            h.get("source") in ("random",) for h in plan.history
        )
        if not is_random:
            self._repair_complex_layer_links(plan)
        self._infer_missing_parent_links(plan)
        # 无论编辑来源（LLM/启发式），统一钳制边框厚度
        self._clamp_border_thickness(plan, user_input=user_input)
        return plan

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
                    motif.motif_type in {"panel", "allover"} or "hex" in rid or "honeycomb" in rid
                ):
                    if motif.role in {"center", "main"}:
                        motif.motif_type = "hexagon"
                        motif.region.setdefault("shape", "hexagon")

        if any(k in text for k in ["三角", "三角形", "triangle"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
                if "triangle" in rid or "三角" in rid or motif.region.get("shape") == "triangle":
                    motif.region["shape"] = "triangle"
                    if motif.motif_type in {"mesh", "panel", "allover"} and motif.effect in {"plain", "honeycomb", "lace", "relief", "seed"}:
                        motif.motif_type = "triangle"

        if any(k in text for k in ["圆形", "圆形结构", "圆内部", "circle", "round"]):
            for motif in plan.motifs:
                rid = motif.motif_id.lower()
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
            return PatternPlan.from_dict(data)

        if "operation" in data:
            plan = copy.deepcopy(current_plan) if current_plan is not None else PatternPlan()
            self._apply_operation(plan, data)
            return plan

        if "regions" in data:
            return self._visual_spec_data_to_plan(data)

        return None

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

    def _normalize_region(self, region: Dict[str, Any]) -> Dict[str, Any]:
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
            role_penalty = 0 if m.role == "center" else 2
            rid = m.motif_id.lower()
            frame_penalty = 2 if (
                m.role == "border"
                or m.motif_type == "frame"
                or any(k in rid for k in ["frame", "border", "边框", "outer"])
            ) else 0
            try:
                size = int(m.region.get("size", 0))
            except Exception:
                size = 0
            return (role_penalty, frame_penalty, -size)

        return sorted(candidates, key=score)[0]

    def _repair_complex_layer_links(self, plan: PatternPlan) -> None:
        containers = {
            m.motif_id: m for m in plan.motifs
            if m.motif_type in {"diamond", "circle", "triangle", "hexagon", "polygon", "heart", "star", "rectangle"}
            and m.role in {"center", "border"}
        }
        central = self._best_central_container(plan)
        if central is None:
            return

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
            if motif.effect in {"wave_tuck", "lace", "relief", "honeycomb", "seed"}:
                rid = motif.motif_id.lower()
                looks_inner = any(k in rid for k in ["inner", "inside", "fill", "mesh", "wave", "内部", "里面"])
                shape_hint = str(motif.region.get("shape", "")).lower()
                if looks_inner and (
                    bad_parent
                    or parent is None
                    or shape_hint == central.motif_type
                    or shape_hint in {"frame", "border", "stripe", "column"}
                ):
                    motif.parent_id = central.motif_id
                    motif.region["shape"] = central.motif_type

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
        placement.setdefault("center", [20, 20])
        placement.setdefault("size", 16)
        placement.setdefault("shape", self._motif_to_visual_shape(motif.motif_type))
        if motif.parent_id:
            placement["parent_id"] = motif.parent_id
            placement["clip_to_parent"] = True
        if motif.motif_type == "frame":
            explicit_shape = placement.get("shape") or placement.get("mask_shape")
            if explicit_shape:
                placement["shape"] = self._motif_to_visual_shape(explicit_shape)
                placement["mask_shape"] = placement["shape"]
            else:
                placement["mask_shape"] = "rectangle"
                placement["shape"] = "rectangle"
        return placement

    def _motif_to_visual_shape(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {
            "eyelet": "mesh",
            "lace": "mesh",
            "border": "frame",
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
        return key if key in {"center", "ground", "border", "side_band", "allover"} else "center"

    def _normalize_role(self, raw: str) -> str:
        key = str(raw or "").lower().strip()
        mapping = {
            "frame": "border",
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
        return mapping.get(key, key)

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
            if motif.role in {"side_band", "allover"}:
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

    def _next_id(self, plan: PatternPlan, prefix: Any) -> str:
        stem = re.sub(r"[^a-zA-Z0-9_]+", "_", str(prefix or "motif")).strip("_") or "motif"
        existing = {m.motif_id for m in plan.motifs}
        idx = 1
        while f"{stem}_{idx}" in existing:
            idx += 1
        return f"{stem}_{idx}"
