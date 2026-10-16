"""
动作定义层 - 单一数据源

从 instruction_info.json 加载 15 色动作定义。
所有其他文件通过本模块查询动作属性，不再各自维护张力表/颜色表。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from functools import lru_cache

from config import INSTRUCTION_INFO_PATH
from utils.logger import logger

_INFO_PATH = INSTRUCTION_INFO_PATH


def _load() -> Dict:
    try:
        with _INFO_PATH.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"instruction_info.json not found at {_INFO_PATH}, using empty defaults")
        return {"instructions": [], "semantic_layer": {}}
    except json.JSONDecodeError as exc:
        logger.warning(f"instruction_info.json is invalid JSON at {_INFO_PATH}: {exc}; using empty defaults")
        return {"instructions": [], "semantic_layer": {}}


_DATA = _load()
_INSTRUCTIONS: List[Dict] = _DATA.get("instructions", [])
_SEMANTIC_LAYER: Dict = _DATA.get("semantic_layer", {})

if not _INSTRUCTIONS:
    logger.warning("instruction_info.json 中未找到 instructions，使用空动作表")

NUM_ACTIONS: int = len(_INSTRUCTIONS)
ALL_ACTION_INDICES: Set[int] = set(range(NUM_ACTIONS))


# ============================================================
# 按 abbr 查索引
# ============================================================

_ABBR_TO_IDX: Dict[str, int] = {
    item["abbr"]: idx for idx, item in enumerate(_INSTRUCTIONS)
}


def idx(abbr: str) -> int:
    """abbr → 动作索引。找不到时报错。"""
    if abbr not in _ABBR_TO_IDX:
        raise KeyError(f"未知动作 abbr: {abbr}")
    return _ABBR_TO_IDX[abbr]


def idx_safe(abbr: str, default: int = 0) -> int:
    """abbr → 动作索引。找不到时返回默认值。"""
    return _ABBR_TO_IDX.get(abbr, default)


# ============================================================
# 按索引查属性
# ============================================================

def info(action_idx: int) -> Dict:
    if 0 <= action_idx < NUM_ACTIONS:
        return _INSTRUCTIONS[action_idx]
    return {}


def abbr(action_idx: int) -> str:
    return info(action_idx).get("abbr", f"unknown_{action_idx}")


def name(action_idx: int) -> str:
    return info(action_idx).get("name", f"unknown_{action_idx}")


def color_hex(action_idx: int) -> str:
    return info(action_idx).get("color", "#000000")


def _hex_to_rgb(h: str, action_idx: int, field_name: str) -> Tuple[int, int, int]:
    h = h or "#000000"
    h = str(h).lstrip("#")
    try:
        if len(h) != 6:
            raise ValueError("invalid length")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        logger.warning(f"Invalid {field_name} '{h}' for action_idx={action_idx}, using black")
        return (0, 0, 0)


def color_rgb(action_idx: int) -> Tuple[int, int, int]:
    return _hex_to_rgb(color_hex(action_idx), action_idx, "color")


def semantic(action_idx: int) -> str:
    return info(action_idx).get("semantic", "")


def bed(action_idx: int) -> Optional[str]:
    return info(action_idx).get("bed")


def offset(action_idx: int) -> int:
    return int(info(action_idx).get("offset", 0))


def tension(action_idx: int) -> float:
    return float(info(action_idx).get("tension", 5.0))


def frequency(action_idx: int) -> str:
    return info(action_idx).get("frequency", "low")


def is_variant(action_idx: int) -> bool:
    return bool(info(action_idx).get("variant", False))


# ============================================================
# 语义层属性
# ============================================================

def semantic_prop(sem: str, key: str, default=None):
    return _SEMANTIC_LAYER.get(sem, {}).get(key, default)


def creates_loop(action_idx: int) -> bool:
    return bool(semantic_prop(semantic(action_idx), "creates_loop", False))


def requires_support(action_idx: int) -> bool:
    return bool(semantic_prop(semantic(action_idx), "requires_support_below", False))


def supports_above(action_idx: int) -> bool:
    return bool(semantic_prop(semantic(action_idx), "supports_above", False))


def max_vertical_stack(action_idx: int) -> Optional[int]:
    sem = semantic(action_idx)
    if sem == "TUCK":
        return int(semantic_prop("TUCK", "max_vertical_stack", 3))
    return None


def max_transfer_offset() -> int:
    return int(semantic_prop("TRANSFER", "max_offset", 2))


# ============================================================
# 按语义分组
# ============================================================

@lru_cache(maxsize=1)
def _build_semantic_groups() -> Dict[str, Set[int]]:
    groups: Dict[str, Set[int]] = {}
    for i in range(NUM_ACTIONS):
        sem = semantic(i)
        if sem:
            groups.setdefault(sem, set()).add(i)
    return groups


def group(sem: str) -> Set[int]:
    """获取某语义类型的所有动作索引"""
    return _build_semantic_groups().get(sem, set())


LOOP = property(lambda _: group("LOOP"))
TUCK = property(lambda _: group("TUCK"))

# 直接暴露常用分组
def loop_ids() -> Set[int]: return group("LOOP")
def tuck_ids() -> Set[int]: return group("TUCK")
def transfer_ids() -> Set[int]: return group("TRANSFER")
def split_ids() -> Set[int]: return group("SPLIT")
def miss_ids() -> Set[int]: return group("EMPTY")
def drop_ids() -> Set[int]: return group("DROP")
def carrier_ids() -> Set[int]: return group("CARRIER")


def left_transfer_ids() -> Set[int]:
    return {i for i in transfer_ids() if offset(i) < 0}


def right_transfer_ids() -> Set[int]:
    return {i for i in transfer_ids() if offset(i) > 0}


def bed_transfer_ids() -> Set[int]:
    return {i for i in transfer_ids() if offset(i) == 0}


def loop_forming_ids() -> Set[int]:
    return loop_ids() | tuck_ids() | split_ids()


def supporting_ids() -> Set[int]:
    return loop_ids() | tuck_ids() | transfer_ids() | split_ids()


# ============================================================
# 默认动作
# ============================================================

DEFAULT_BG: int = idx_safe("f_knit", default=0)


# ============================================================
# 调色板
# ============================================================

def build_palette_256():
    """构建内部 15 色调色板，用于生成/第二阶段仿真输入。"""
    import numpy as np
    bg_color = color_rgb(DEFAULT_BG)
    palette = np.tile(np.array(bg_color, dtype=np.uint8), (256, 1))
    for i in range(NUM_ACTIONS):
        palette[i] = color_rgb(i)
    palette[255] = (255, 255, 255)
    return palette


# ============================================================
# v7.1 新增：基础/精修/元动作分组
# ============================================================

_PRIMARY_ABBRS = {
    "f_knit", "b_knit",
    "xfer_f_b", "xfer_b_f",
    "f_tuck", "b_tuck",
    "f_split", "b_split",
    "xfer_l1", "xfer_r1",
    "miss",
}

_REFINEMENT_ABBRS = {
    "f_tuck_2", "b_tuck_2", "split_v",
}

_META_ABBRS = {
    "carrier",
}


def primary_action_ids() -> Set[int]:
    """基础结构动作：motif / base compiler 直接使用"""
    return {_ABBR_TO_IDX[a] for a in _PRIMARY_ABBRS if a in _ABBR_TO_IDX}


def refinement_action_ids() -> Set[int]:
    """精修动作：只允许 refinement compiler 或显式 junction 使用"""
    return {_ABBR_TO_IDX[a] for a in _REFINEMENT_ABBRS if a in _ABBR_TO_IDX}


def meta_action_ids() -> Set[int]:
    """元动作：行级控制，不参与常规像素 fill"""
    return {_ABBR_TO_IDX[a] for a in _META_ABBRS if a in _ABBR_TO_IDX}


def is_primary(action_idx: int) -> bool:
    return action_idx in primary_action_ids()


def is_refinement(action_idx: int) -> bool:
    return action_idx in refinement_action_ids()


def is_meta(action_idx: int) -> bool:
    return action_idx in meta_action_ids()


def tuck_variant_ids() -> Set[int]:
    return {i for i in refinement_action_ids() if semantic(i) == "TUCK"}


def split_variant_ids() -> Set[int]:
    return {i for i in refinement_action_ids() if semantic(i) == "SPLIT"}


def executable_max_transfer_offset() -> int:
    """当前 palette 中实际存在的最大横向偏移"""
    offsets = [abs(offset(i)) for i in transfer_ids()]
    return max(offsets) if offsets else 0
