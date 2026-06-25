"""
LLM 输出解析器 v9.0

解析 LLM 输出的 VisualSpec JSON。
同时提供兼容旧 schema 的降级解析。
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field as dc_field

from generation.visual_types import (
    VisualSpec,
    VisualRegion,
    VALID_VISUAL_SHAPES,
    VALID_VISUAL_EFFECTS,
    VALID_LAYOUT_ROLES,
    VALID_LAYOUT_TYPES,
)
from utils.logger import logger


class DesignParser:
    def __init__(self):
        self.default_center = [20, 20]
        self.default_size = 16

    def parse(self, llm_output: str) -> VisualSpec:
        json_str = self._extract_json(llm_output)
        if not json_str:
            logger.warning("No valid JSON found, using default VisualSpec")
            return self.default_spec()

        try:
            data = json.loads(json_str)
        except Exception:
            try:
                data = json.loads(self._fix_json(json_str))
            except Exception:
                logger.warning("JSON parse failed, using default VisualSpec")
                return self.default_spec()

        return self._to_visual_spec(data)

    def default_spec(self) -> VisualSpec:
        return VisualSpec(
            layout_type="centered",
            regions=[
                VisualRegion(
                    region_id="ground",
                    visual_shape="panel",
                    visual_effect="plain",
                    layout_role="ground",
                    placement={"type": "full"},
                    params={},
                    symmetry="none",
                    allow_refinement=False,
                ),
                VisualRegion(
                    region_id="main",
                    visual_shape="diamond",
                    visual_effect="plain",
                    layout_role="center",
                    placement={"center": [20, 20], "size": 16, "shape": "diamond"},
                    params={},
                    symmetry="mirror_lr",
                    allow_refinement=False,
                ),
            ],
        )

    # ============================================================
    # 主解析
    # ============================================================

    def _to_visual_spec(self, data: Dict) -> VisualSpec:
        # 检测 schema 版本
        raw_regions = data.get("regions", [])

        if raw_regions and "visual_shape" in raw_regions[0]:
            return self._parse_visual_schema(data)

        # 旧 schema 兼容
        if raw_regions and "contour" in raw_regions[0]:
            return self._parse_morphology_compat(data)

        if raw_regions and "motif" in raw_regions[0]:
            return self._parse_motif_compat(data)

        if "elements" in data:
            return self._parse_elements_compat(data)

        return self.default_spec()

    def _parse_visual_schema(self, data: Dict) -> VisualSpec:
        layout_type = self._norm_layout_type(data.get("layout_type", "centered"))
        regions = []

        for idx, rd in enumerate(data.get("regions", [])):
            region = VisualRegion(
                region_id=str(rd.get("region_id", f"region_{idx}")),
                visual_shape=self._norm_visual_shape(rd.get("visual_shape", "panel")),
                visual_effect=self._norm_visual_effect(rd.get("visual_effect", "plain")),
                layout_role=self._norm_layout_role(rd.get("layout_role", "center")),
                placement=self._norm_placement(rd.get("placement", {})),
                params=dict(rd.get("params", {}) or {}),
                symmetry=str(rd.get("symmetry", "none")),
                allow_refinement=bool(rd.get("allow_refinement", True)),
            )
            regions.append(region)

        if not regions:
            return self.default_spec()

        if not any(r.layout_role == "ground" for r in regions):
            regions.insert(0, VisualRegion(
                region_id="ground",
                visual_shape="panel",
                visual_effect="plain",
                layout_role="ground",
                placement={"type": "full"},
                params={},
                allow_refinement=False,
            ))

        return VisualSpec(
            layout_type=layout_type,
            regions=regions,
            raw_json=data,
        )

    def _parse_morphology_compat(self, data: Dict) -> VisualSpec:
        """兼容旧 morphology schema（contour/skeleton/field）"""
        _SKELETON_TO_EFFECT = {
            "crossing": "cable",
            "diamond_path": "cable",
            "wave_path": "wave_tuck",
            "vertical_spine": "rib",
            "lattice": "relief",
            "none": "plain",
        }
        _FIELD_TO_EFFECT = {
            "rib": "rib",
            "links": "links",
            "mesh": "lace",
            "tuck_relief": "relief",
            "plain_front": "plain",
            "plain_back": "reverse",
        }
        _CONTOUR_TO_SHAPE = {
            "diamond": "diamond",
            "column": "column",
            "band": "stripe",
            "panel": "panel",
            "frame": "frame",
            "circle": "circle",
            "square": "panel",
        }

        regions = []
        for idx, rd in enumerate(data.get("regions", [])):
            skeleton = str(rd.get("skeleton", "none"))
            field = str(rd.get("field", "plain_front"))
            contour = str(rd.get("contour", "panel"))
            composition = str(rd.get("composition_role", "center"))

            effect = _SKELETON_TO_EFFECT.get(skeleton, "plain")
            if skeleton == "none":
                effect = _FIELD_TO_EFFECT.get(field, "plain")

            shape = _CONTOUR_TO_SHAPE.get(contour, "panel")
            role = self._norm_layout_role(composition)

            placement = self._norm_placement(rd.get("placement", {}))
            if contour in _CONTOUR_TO_SHAPE:
                placement["shape"] = _CONTOUR_TO_SHAPE[contour]

            regions.append(VisualRegion(
                region_id=str(rd.get("region_id", f"region_{idx}")),
                visual_shape=shape,
                visual_effect=effect,
                layout_role=role,
                placement=placement,
                params=dict(rd.get("params", {}) or {}),
                allow_refinement=bool(rd.get("allow_refinement", True)),
            ))

        if not any(r.layout_role == "ground" for r in regions):
            regions.insert(0, VisualRegion(
                region_id="ground",
                visual_shape="panel",
                visual_effect="plain",
                layout_role="ground",
                placement={"type": "full"},
                params={},
                allow_refinement=False,
            ))

        return VisualSpec(
            layout_type=self._norm_layout_type(data.get("layout_type", "centered")),
            regions=regions,
            raw_json=data,
        )

    def _parse_motif_compat(self, data: Dict) -> VisualSpec:
        _MOTIF_TO_VS = {
            "plain_front": ("panel", "plain"),
            "plain_back": ("panel", "reverse"),
            "links_ground": ("panel", "links"),
            "rib_support_band": ("stripe", "rib"),
            "tuck_wave_5x4": ("panel", "wave_tuck"),
            "staggered_tuck_relief": ("panel", "relief"),
            "honeycomb_tuck": ("panel", "honeycomb"),
            "mesh_panel": ("panel", "lace"),
            "cable_simple": ("panel", "cable"),
            "diamond_cable_panel": ("diamond", "cable"),
            "support_border": ("stripe", "reverse"),
        }

        regions = []
        for idx, rd in enumerate(data.get("regions", [])):
            motif = str(rd.get("motif", "plain_front"))
            shape, effect = _MOTIF_TO_VS.get(motif, ("panel", "plain"))
            role = self._norm_layout_role(rd.get("layout_role", "center"))

            placement = self._norm_placement(rd.get("placement", {}))
            placement["shape"] = shape

            regions.append(VisualRegion(
                region_id=str(rd.get("region_id", f"region_{idx}")),
                visual_shape=shape,
                visual_effect=effect,
                layout_role=role,
                placement=placement,
                params=dict(rd.get("params", {}) or {}),
                allow_refinement=bool(rd.get("allow_refinement", True)),
            ))

        if not any(r.layout_role == "ground" for r in regions):
            regions.insert(0, VisualRegion(
                region_id="ground",
                visual_shape="panel",
                visual_effect="plain",
                layout_role="ground",
                placement={"type": "full"},
                params={},
                allow_refinement=False,
            ))

        return VisualSpec(
            layout_type=self._norm_layout_type(data.get("layout_type", "centered")),
            regions=regions,
            raw_json=data,
        )

    def _parse_elements_compat(self, data: Dict) -> VisualSpec:
        _SC_TO_EFFECT = {
            "cable": "cable", "tuck": "wave_tuck", "mesh": "lace",
            "void": "lace", "double_bed": "rib", "links": "links",
            "hem": "rib", "active": "plain", "background": "plain",
            "support": "reverse", "degree": "relief", "miss": "lace",
        }
        _TYPE_TO_SHAPE = {
            "diamond": "diamond", "circle": "circle", "square": "rectangle",
            "line": "stripe", "zigzag": "zigzag", "triangle": "triangle",
            "cross": "cross", "hexagon": "hexagon", "heart": "heart", "star": "star",
        }

        regions = [VisualRegion(
            region_id="ground", visual_shape="panel", visual_effect="plain",
            layout_role="ground", placement={"type": "full"}, params={},
            allow_refinement=False,
        )]

        for idx, ed in enumerate(data.get("elements", [])):
            sc = str(ed.get("stitch_class", "plain")).lower()
            shape_raw = str(ed.get("type", "diamond")).lower()
            shape = _TYPE_TO_SHAPE.get(shape_raw, "panel")
            effect = _SC_TO_EFFECT.get(sc, "plain")

            center = ed.get("center", [20, 20])
            if isinstance(center, list) and len(center) >= 2:
                center = [int(center[0]), int(center[1])]
            else:
                center = [20, 20]

            regions.append(VisualRegion(
                region_id=f"elem_{idx}",
                visual_shape=shape,
                visual_effect=effect,
                layout_role="center",
                placement={"center": center, "size": int(ed.get("size", 16)), "shape": shape},
                params={},
                allow_refinement=True,
            ))

        return VisualSpec(
            layout_type="centered",
            regions=regions,
            raw_json=data,
        )

    # ============================================================
    # 规范化
    # ============================================================

    def _norm_layout_type(self, raw: str) -> str:
        key = (raw or "").strip().lower()
        if key in VALID_LAYOUT_TYPES:
            return key
        mapping = {
            "center": "centered", "center_panel": "centered",
            "allover": "allover_repeat", "repeat": "allover_repeat",
            "frame": "framed", "framed_panel": "framed",
            "bands": "side_bands", "mirror": "mirror_pair",
            "vertical": "vertical_repeat",
        }
        return mapping.get(key, "centered")

    def _norm_visual_shape(self, raw: str) -> str:
        key = (raw or "").strip().lower()
        if key in VALID_VISUAL_SHAPES:
            return key
        mapping = {
            "rectangle": "panel", "rect": "panel", "square": "panel",
            "line": "stripe", "band": "stripe",
            "oval": "circle",
            "triangle": "triangle", "tri": "triangle",
            "hexagon": "hexagon", "hex": "hexagon",
            "polygon": "polygon",
            "heart": "heart", "star": "star",
            "chevron": "chevron", "zigzag": "zigzag", "cross": "cross",
        }
        return mapping.get(key, "panel")

    def _norm_visual_effect(self, raw: str) -> str:
        key = (raw or "").strip().lower()
        if key in VALID_VISUAL_EFFECTS:
            return key
        mapping = {
            "cable_knit": "cable", "twist": "cable", "braid": "cable",
            "stockinette": "plain", "jersey": "plain", "knit": "plain",
            "purl": "reverse", "reverse_stockinette": "reverse",
            "garter": "links",
            "tuck": "wave_tuck", "ripple": "wave_tuck",
            "honeycomb_tuck": "honeycomb",
            "mesh": "lace", "openwork": "lace", "eyelet": "lace",
            "embossed": "relief", "texture": "relief",
        }
        return mapping.get(key, "plain")

    def _norm_layout_role(self, raw: str) -> str:
        key = (raw or "").strip().lower()
        if key in VALID_LAYOUT_ROLES:
            return key
        mapping = {
            "background": "ground", "base": "ground",
            "main": "center", "panel": "center", "center_panel": "center",
            "frame": "border", "edge": "border",
            "band": "side_band", "side": "side_band",
            "repeat": "allover", "allover_repeat": "allover",
        }
        return mapping.get(key, "center")

    def _norm_placement(self, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        out = dict(raw)
        center = out.get("center")
        if isinstance(center, list) and len(center) >= 2:
            out["center"] = [int(max(0, min(40, center[0]))), int(max(0, min(40, center[1])))]
        if "size" in out:
            try:
                out["size"] = int(out["size"])
            except Exception:
                out["size"] = self.default_size
        return out

    # ============================================================
    # JSON 提取
    # ============================================================

    def _extract_json(self, text: str) -> Optional[str]:
        text = text.strip()
        if text.startswith("{"):
            depth = 0
            for i, ch in enumerate(text):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[:i + 1]
            return text

        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            m = re.search(pattern, text)
            if m:
                s = m.group(1).strip()
                if s.startswith("{"):
                    return s

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return text[start:end + 1]
        return None

    def _fix_json(self, s: str) -> str:
        s = re.sub(r",\s*}", "}", s)
        s = re.sub(r",\s*]", "]", s)
        s = s.replace("'", '"')
        return s
