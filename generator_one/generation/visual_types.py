"""
视觉目标类型定义 v9.0

用户描述的是"仿真图上想要的视觉形状/效果"。
这一层不涉及色码图排列，只描述视觉目标。

关键原则：
- 视觉形状 ≠ 色码图形状
- 波浪在仿真图里是曲线，在色码图里是斜向激活序列
- 麻花在仿真图里是绳股，在色码图里是局部移针 + 邻接过渡
"""

from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Any


# ============================================================
# 合法值
# ============================================================

VALID_VISUAL_SHAPES = {
    "diamond",          # 菱形
    "wave",             # 波浪
    "column",           # 柱状
    "stripe",           # 条纹
    "panel",            # 面板
    "frame",            # 边框
    "rectangle",        # 矩形
    "mesh",             # 网格
    "circle",           # 圆形
    "triangle",         # 三角形
    "hexagon",          # 六边形
    "polygon",          # 多边形
    "heart",            # 心形
    "star",             # 星形
    "chevron",          # V字/人字形
    "zigzag",           # 锯齿形
    "cross",            # 十字形
    "allover",          # 满地
}

VALID_VISUAL_EFFECTS = {
    "plain",            # 平针
    "reverse",          # 反针
    "cable",            # 麻花/绞花
    "wave_tuck",        # 波浪集圈
    "rib",              # 罗纹
    "links",            # 链接/正反交替
    "lace",             # 网眼/镂空
    "relief",           # 浮雕
    "honeycomb",        # 蜂巢
    "seed",             # 种子针
}

VALID_LAYOUT_ROLES = {
    "center",
    "ground",
    "border",
    "side_band",
    "allover",
}

VALID_LAYOUT_TYPES = {
    "centered",
    "allover_repeat",
    "framed",
    "side_bands",
    "vertical_repeat",
    "mirror_pair",
}


# ============================================================
# 单个视觉区域
# ============================================================

@dataclass
class VisualRegion:
    """
    描述仿真图中一个区域的视觉目标。

    例如"中心麻花菱形":
    - visual_shape = "diamond"
    - visual_effect = "cable"
    - layout_role = "center"
    """
    region_id: str
    visual_shape: str = "panel"
    visual_effect: str = "plain"
    layout_role: str = "center"
    placement: Dict[str, Any] = dc_field(default_factory=dict)
    params: Dict[str, Any] = dc_field(default_factory=dict)
    symmetry: str = "none"          # none / mirror_lr / mirror_tb / full
    allow_refinement: bool = True

    def validate(self):
        assert self.visual_shape in VALID_VISUAL_SHAPES, f"invalid shape: {self.visual_shape}"
        assert self.visual_effect in VALID_VISUAL_EFFECTS, f"invalid effect: {self.visual_effect}"
        assert self.layout_role in VALID_LAYOUT_ROLES, f"invalid role: {self.layout_role}"


# ============================================================
# 整体视觉设计方案
# ============================================================

@dataclass
class VisualSpec:
    """
    整体仿真目标设计方案。
    由 LLM 第一次调用产生。
    """
    layout_type: str = "centered"
    regions: List[VisualRegion] = dc_field(default_factory=list)
    raw_json: Dict = dc_field(default_factory=dict)

    def get_region(self, region_id: str) -> Optional[VisualRegion]:
        for r in self.regions:
            if r.region_id == region_id:
                return r
        return None


# ============================================================
# 色码实现方案
# ============================================================

@dataclass
class RealizationRegion:
    """
    描述"如何用色码图实现一个视觉效果"。

    这是 visual_to_realization 层的输出。
    每个 RealizationRegion 定义了：
    - 底布动作类型
    - 边界样式
    - 事件模式（主动作发生方式）
    - 过渡策略
    """
    region_id: str
    layout_role: str = "center"
    placement: Dict[str, Any] = dc_field(default_factory=dict)

    # 底布
    base_field: str = "plain_front"
    # 边界样式
    border_style: str = "none"      # none / back_loop_outline / rib_border
    border_thickness: int = 1

    # 事件模式
    event_pattern: str = "none"
    # none / diagonal_wave / diamond_side_xfer / vertical_rib /
    # lattice_tuck / mesh_miss / full_rib / full_links

    event_params: Dict[str, Any] = dc_field(default_factory=dict)

    # 过渡策略
    transition_policy: str = "local_only"
    # local_only: 只在主动作相邻格插过渡
    # none: 不插任何过渡

    allow_refinement: bool = True


@dataclass
class RealizationPlan:
    """
    整体色码实现方案。
    由 visual_to_realization 层产生。
    """
    layout_type: str = "centered"
    grid_size: int = 40
    regions: List[RealizationRegion] = dc_field(default_factory=list)

    def get_region(self, region_id: str) -> Optional[RealizationRegion]:
        for r in self.regions:
            if r.region_id == region_id:
                return r
        return None


# ============================================================
# 事件点
# ============================================================

@dataclass
class EventPoint:
    """
    单个工艺事件点。
    由 event_planner 产生，只包含必要、局部、有效的动作事件。
    """
    row: int
    col: int
    action_abbr: str        # 直接对应 instruction_info.json 里的 abbr
    region_id: str
    reason: str = ""        # 可选：为什么放这个动作（调试用）
