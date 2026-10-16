"""
通用掩码工具函数

提供 `point_in_mask(r, c, placement, grid_size)`，用于判断网格点是否落在
placement 指定的几何掩码内。支持圆/椭圆、正多边形（triangle/square/hexagon/diamond）等，
且支持通过 `placement` 指定 `sides`、`rotation`（度）和 `aspect`（宽高比）。
"""
from typing import Tuple
import math


_SHAPE_PRIORITY = ("mask_shape", "shape")


def get_mask_shape(placement: dict) -> str:
    placement = placement or {}
    for key in _SHAPE_PRIORITY:
        value = str(placement.get(key, "") or "").strip().lower()
        if value:
            return value
    return ""


def has_mask_shape(placement: dict) -> bool:
    return bool(get_mask_shape(placement))


def get_center_size(placement: dict, grid_size: int) -> Tuple[int, int, int]:
    """Extract (center_row, center_col, size) from a placement dict.

    Shared utility used by event_planner, action_builder, and layer_utils.
    """
    placement = placement or {}
    if placement.get("type") == "full":
        return grid_size // 2, grid_size // 2, grid_size // 2
    center = placement.get("center", [grid_size // 2, grid_size // 2])
    try:
        cr, cc = int(center[0]), int(center[1])
    except Exception:
        cr, cc = grid_size // 2, grid_size // 2
    try:
        size = int(placement.get("size", grid_size // 3))
    except Exception:
        size = grid_size // 3
    return cr, cc, size


def resolve_side_band_side(placement: dict, region_id: str, grid_size: int) -> str:
    """Determine whether a side_band region is on the 'left' or 'right'.

    Shared utility used by visual_to_realization, event_planner, action_builder.
    """
    placement = placement or {}
    side_raw = str(placement.get("side", "")).strip().lower()
    if side_raw in {"left", "right"}:
        return side_raw

    rid = str(region_id or "").lower()
    if any(k in rid for k in ["right", "r_", "_r", "\u53f3"]):
        return "right"
    if any(k in rid for k in ["left", "l_", "_l", "\u5de6"]):
        return "left"

    center = placement.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            return "right" if int(center[1]) >= grid_size // 2 else "left"
        except Exception:
            pass

    return "left"


def is_excluded_by_foreground(
    r: int, c: int, placement: dict, grid_size: int,
) -> bool:
    """Check if point (r,c) falls inside any foreground exclusion mask.

    Shared utility used by event_planner, action_builder, and pipeline.
    """
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
                cr, cc, size = get_center_size(mask, grid_size)
                if abs(r - cr) <= size and abs(c - cc) <= size:
                    return True
        except Exception:
            continue
    return False


def point_in_mask(r: int, c: int, placement: dict, grid_size: int) -> bool:
    """
    判断点 (r,c) 是否位于 placement 指定的掩码内。

    placement 可包含字段：
    - mask_shape 或 shape: 值如 'circle','oval','hexagon','diamond','square','triangle','polygon'
    - size: 半径/尺度
    - center: [row, col]
    - sides: 对于正多边形，边数（覆盖 diamond/hexagon/triangle）
    - rotation: 以度计的旋转角
    - aspect: 宽高比 (width/height)，用于椭圆
    """
    placement = placement or {}
    shape = get_mask_shape(placement)
    if not shape:
        return True

    if placement.get("repeat"):
        return _point_in_repeated_mask(r, c, placement, grid_size)

    cr, cc, size = get_center_size(placement, grid_size)

    # Grid diamond: use Manhattan distance so all four vertices connect cleanly
    # on discrete knitting grids.
    if shape in {"diamond", "rhombus"}:
        return abs(r - cr) + abs(c - cc) <= int(size)

    if shape in {"hexagon", "hex"}:
        return _point_in_grid_hexagon(r, c, cr, cc, int(size))

    # 轴对齐矩形/面板/边框
    if shape in {"rectangle", "rect", "frame", "border", "panel", "box"}:
        aspect = float(placement.get("aspect", 1.0)) or 1.0
        half_w = max(1, int(round(size * max(0.5, aspect))))
        half_h = max(1, int(size))
        return (abs(r - cr) <= half_h) and (abs(c - cc) <= half_w)

    # 圆/椭圆
    if shape in {"circle", "oval", "round", "circular", "ellipse"}:
        aspect = float(placement.get("aspect", 1.0)) or 1.0
        try:
            dr = r - cr
            dc = c - cc
            # aspect >1 表示宽比高大；将列方向缩放
            dc_scaled = dc / aspect
            return (dr * dr + dc_scaled * dc_scaled) <= (int(size) * int(size))
        except Exception:
            return (abs(r - cr) <= size) and (abs(c - cc) <= size)

    # 多边形：使用正多边形近似，允许通过 placement.sides 覆盖
    poly_map = {
        "triangle": 3, "tri": 3,
        "square": 4,
        "polygon": 6,
    }
    if shape in poly_map or placement.get("sides"):
        n_sides = int(placement.get("sides", poly_map.get(shape, 6)))
        default_rotation = -90.0 if shape in {"triangle", "tri"} else 45.0 if shape == "square" else 0.0
        rotation_deg = float(placement.get("rotation", default_rotation))
        rotation = math.radians(rotation_deg)
        return _point_in_regular_polygon(r, c, cr, cc, int(size), n_sides, rotation)

    if shape in {"chevron", "zigzag"}:
        dr = r - cr
        dc = abs(c - cc)
        thickness = max(1, int(placement.get("thickness", 2)))
        return abs(abs(dr) - dc) <= thickness and dc <= size

    if shape == "cross":
        thickness = max(1, int(placement.get("thickness", 2)))
        return (abs(r - cr) <= thickness and abs(c - cc) <= size) or (
            abs(c - cc) <= thickness and abs(r - cr) <= size
        )

    if shape == "heart":
        y = -(r - cr) / max(1.0, float(size))
        x = (c - cc) / max(1.0, float(size))
        return (x * x + y * y - 0.35) ** 3 - x * x * y ** 3 <= 0

    if shape == "star":
        angle = math.atan2(r - cr, c - cc)
        radius = ((r - cr) ** 2 + (c - cc) ** 2) ** 0.5
        max_radius = size * (0.68 + 0.32 * math.cos(5 * angle))
        return radius <= max_radius

    # 其他未知形状：回退到方形边界
    return (abs(r - cr) <= size) and (abs(c - cc) <= size)


def _point_in_grid_hexagon(r: int, c: int, cr: int, cc: int, size: int) -> bool:
    """Discrete flat-top hexagon with exact left/right symmetry.

    The regular-polygon ray test is visually reasonable at high resolution but
    can rasterize asymmetrically on a 40x40 knitting grid. This row-width rule
    keeps every row centered on ``cc`` and mirrors exactly across the center
    column.
    """
    if size <= 0:
        return False

    dr = abs(r - cr)
    if dr > size:
        return False

    shoulder = max(1, size // 2)
    if dr <= shoulder:
        half_width = size
    else:
        half_width = max(0, size - (dr - shoulder))
    return abs(c - cc) <= half_width


def _point_in_repeated_mask(r: int, c: int, placement: dict, grid_size: int) -> bool:
    """Evaluate a motif mask repeated on a regular grid."""
    try:
        period_x = int(placement.get("period_x", placement.get("period", 10)))
        period_y = int(placement.get("period_y", placement.get("period", 10)))
    except Exception:
        period_x, period_y = 10, 10
    period_x = max(1, period_x)
    period_y = max(1, period_y)

    base_center = placement.get("center", [grid_size // 2, grid_size // 2])
    try:
        base_r, base_c = int(base_center[0]), int(base_center[1])
    except Exception:
        base_r, base_c = grid_size // 2, grid_size // 2

    row_index = int(round((r - base_r) / float(period_y)))
    col_index = int(round((c - base_c) / float(period_x)))
    candidate = dict(placement)
    candidate.pop("repeat", None)
    candidate["center"] = [base_r + row_index * period_y, base_c + col_index * period_x]
    return point_in_mask(r, c, candidate, grid_size)


def _point_in_regular_polygon(r: int, c: int, cr: int, cc: int, size: int, n_sides: int, rotation: float = 0.0) -> bool:
    """
    生成正 n 边形顶点（中心 cr,cc，半径 size，旋转 rotation），使用射线法判断点内。
    顶点以 (row, col) 对应 (y, x) 顺序生成。
    """
    if n_sides < 3 or size <= 0:
        return False

    verts = []
    for k in range(n_sides):
        theta = 2.0 * math.pi * k / n_sides + rotation
        x = cc + size * math.cos(theta)
        y = cr + size * math.sin(theta)
        verts.append((y, x))

    inside = False
    j = len(verts) - 1
    py = float(r); px = float(c)
    for i in range(len(verts)):
        yi, xi = verts[i]
        yj, xj = verts[j]
        intersect = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside
