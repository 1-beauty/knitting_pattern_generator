"""
语义针法类型定义 - 精简版

9 类 StitchType 枚举 + 属性 + 词映射。
不再维护独立的张力表，张力从 core.actions 动态计算。
"""
from enum import IntEnum
from typing import Dict, Optional, List


class StitchType(IntEnum):
    BACKGROUND = 0
    VOID       = 1
    ACTIVE     = 2
    DOUBLE_BED = 3
    STRUCTURE  = 4
    DEGREE     = 5
    TUCK       = 6
    CABLE      = 7
    SUPPORT    = 8


# ============================================================
# 属性（语义层粗略值）
# ============================================================

TENSION: Dict[StitchType, float] = {
    StitchType.BACKGROUND: 5.8,
    StitchType.VOID:       3.5,
    StitchType.ACTIVE:     5.8,
    StitchType.DOUBLE_BED: 5.7,
    StitchType.STRUCTURE:  6.2,
    StitchType.DEGREE:     5.9,
    StitchType.TUCK:       3.0,
    StitchType.CABLE:      6.8,
    StitchType.SUPPORT:    3.5,
}

NEEDS_BORDER: Dict[StitchType, bool] = {
    StitchType.VOID: True,
    StitchType.TUCK: True,
    StitchType.CABLE: True,
}

SAFE_DOWNGRADE: Dict[StitchType, StitchType] = {
    StitchType.CABLE:   StitchType.STRUCTURE,
    StitchType.TUCK:    StitchType.DEGREE,
    StitchType.VOID:    StitchType.STRUCTURE,
    StitchType.ACTIVE:  StitchType.DEGREE,
    StitchType.SUPPORT: StitchType.DEGREE,
}

NAMES: Dict[StitchType, str] = {
    StitchType.BACKGROUND: "背景底布",
    StitchType.VOID:       "空针孔洞",
    StitchType.ACTIVE:     "主体活动",
    StitchType.DOUBLE_BED: "双床四平",
    StitchType.STRUCTURE:  "结构压针",
    StitchType.DEGREE:     "度目缓冲",
    StitchType.TUCK:       "集圈吊目",
    StitchType.CABLE:      "绞花交叉",
    StitchType.SUPPORT:    "支撑辅助",
}

# ============================================================
# 应用类别 → 语义针法
# ============================================================

APP_TO_PRIMARY: Dict[str, StitchType] = {
    "move":  StitchType.ACTIVE,
    "cable": StitchType.CABLE,
    "miss":  StitchType.SUPPORT,
    "links": StitchType.DOUBLE_BED,
    "tuck":  StitchType.TUCK,
    "hem":   StitchType.DOUBLE_BED,
    "mesh":  StitchType.VOID,
}

# ============================================================
# 关键词 → 语义针法（唯一一份，不再重复）
# ============================================================

_KEYWORDS: Dict[str, StitchType] = {
    # BACKGROUND
    "背景": StitchType.BACKGROUND, "底布": StitchType.BACKGROUND,
    "background": StitchType.BACKGROUND, "base": StitchType.BACKGROUND,

    # VOID
    "空针": StitchType.VOID, "孔洞": StitchType.VOID,
    "镂空": StitchType.VOID, "网眼": StitchType.VOID,
    "void": StitchType.VOID, "mesh": StitchType.VOID,
    "openwork": StitchType.VOID,

    # ACTIVE
    "主体": StitchType.ACTIVE, "平针": StitchType.ACTIVE,
    "大身": StitchType.ACTIVE, "active": StitchType.ACTIVE,
    "move": StitchType.ACTIVE, "main": StitchType.ACTIVE,

    # DOUBLE_BED
    "双床": StitchType.DOUBLE_BED, "四平": StitchType.DOUBLE_BED,
    "罗纹": StitchType.DOUBLE_BED, "正反针": StitchType.DOUBLE_BED,
    "下摆": StitchType.DOUBLE_BED, "袖口": StitchType.DOUBLE_BED,
    "领口": StitchType.DOUBLE_BED, "links": StitchType.DOUBLE_BED,
    "hem": StitchType.DOUBLE_BED, "rib": StitchType.DOUBLE_BED,

    # STRUCTURE
    "结构": StitchType.STRUCTURE, "压针": StitchType.STRUCTURE,
    "边框": StitchType.STRUCTURE, "轮廓": StitchType.STRUCTURE,
    "structure": StitchType.STRUCTURE, "frame": StitchType.STRUCTURE,

    # DEGREE
    "度目": StitchType.DEGREE, "缓冲": StitchType.DEGREE,
    "过渡": StitchType.DEGREE, "degree": StitchType.DEGREE,
    "buffer": StitchType.DEGREE,

    # TUCK
    "吊目": StitchType.TUCK, "集圈": StitchType.TUCK,
    "紧吊": StitchType.TUCK, "蜂巢": StitchType.TUCK,
    "tuck": StitchType.TUCK, "honeycomb": StitchType.TUCK,

    # CABLE
    "绞花": StitchType.CABLE, "麻花": StitchType.CABLE,
    "交叉": StitchType.CABLE, "扭针": StitchType.CABLE,
    "cable": StitchType.CABLE, "twist": StitchType.CABLE,

    # SUPPORT
    "假针": StitchType.SUPPORT, "浮针": StitchType.SUPPORT,
    "miss": StitchType.SUPPORT, "support": StitchType.SUPPORT,
    "索骨": StitchType.SUPPORT, "float": StitchType.SUPPORT,
}

# 兼容旧词
_LEGACY: Dict[str, str] = {
    "stockinette": "active", "jersey": "active", "plain": "active",
    "ribbing": "double_bed", "elastic": "double_bed",
    "lace": "void", "eyelet": "void",
    "textured": "degree", "seed": "degree",
    "intarsia": "active", "jacquard": "active",
    "sinker": "structure", "press": "structure", "edge": "structure",
    "transfer": "cable", "xfer": "cable", "split": "degree",
    "carrier": "support", "drop": "void",
}


def parse(name: str) -> Optional[StitchType]:
    """解析任意中英文关键词为 StitchType"""
    if not name:
        return None
    key = name.strip().lower()

    # 直接匹配
    if key in _KEYWORDS:
        return _KEYWORDS[key]

    # 枚举名
    for st in StitchType:
        if key == st.name.lower():
            return st

    # 旧词兼容
    if key in _LEGACY:
        return parse(_LEGACY[key])

    # 应用类别
    if key in APP_TO_PRIMARY:
        return APP_TO_PRIMARY[key]

    # 子串匹配
    for kw, st in _KEYWORDS.items():
        if kw in key or key in kw:
            return st

    return None


def get_name(st: StitchType) -> str:
    return NAMES.get(st, str(st))


def tension_diff(a: StitchType, b: StitchType) -> float:
    return abs(TENSION.get(a, 5.0) - TENSION.get(b, 5.0))


def needs_transition(a: StitchType, b: StitchType, threshold: float = 1.5) -> bool:
    return tension_diff(a, b) > threshold


def compatibility(a: StitchType, b: StitchType) -> float:
    """简化版兼容性：基于张力差"""
    diff = tension_diff(a, b)
    if diff < 1.0:
        return 1.0
    elif diff < 2.0:
        return 0.8
    elif diff < 3.0:
        return 0.6
    else:
        return 0.4