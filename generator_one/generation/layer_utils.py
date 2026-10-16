"""Layer-style mask helpers for Stage I composition.

The pattern plan can describe a motif as a child of another motif.  In that
case the child should behave like a Photoshop layer clipped to its parent:
all drawing operations remain visible only inside the parent mask.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from generation.mask_utils import point_in_mask, has_mask_shape, get_center_size


def region_by_id(regions: Iterable) -> Dict[str, object]:
    return {str(getattr(region, "region_id", "")): region for region in regions}


def get_parent_region(region, regions_by_id: Dict[str, object]) -> Optional[object]:
    placement = getattr(region, "placement", {}) or {}
    parent_id = placement.get("parent_id")
    if not parent_id:
        return None
    return regions_by_id.get(str(parent_id))


def layer_mask_contains(
    r: int,
    c: int,
    region,
    regions_by_id: Dict[str, object],
    grid_size: int,
) -> bool:
    """Return True when a point is visible through region and its parents."""
    current = region
    source_region = region
    seen = set()
    while current is not None:
        rid = str(getattr(current, "region_id", ""))
        if rid in seen:
            break
        seen.add(rid)

        placement = getattr(current, "placement", {}) or {}
        role = str(getattr(current, "layout_role", "center") or "center").lower()
        if (
            role not in {"ground", "side_band"}
            and placement.get("type") != "full"
            and has_mask_shape(placement)
        ):
            mask_placement = placement
            if current is not source_region:
                mask_placement = _parent_clip_placement(current, source_region)
            try:
                if not point_in_mask(r, c, mask_placement, grid_size):
                    return False
            except Exception:
                return False

        current = get_parent_region(current, regions_by_id)
    return True


def _parent_clip_placement(parent, child) -> dict:
    """Use the parent's inner drawable area for child clipping.

    A parent outline is part of the container boundary.  Child content should
    not overwrite or touch that outline, so the parent mask is shrunk by the
    visible border thickness plus an optional clip margin.
    """
    placement = dict(getattr(parent, "placement", {}) or {})
    child_placement = getattr(child, "placement", {}) or {}
    try:
        parent_size = int(placement.get("size", 0))
    except Exception:
        parent_size = 0
    if parent_size <= 0:
        return placement

    try:
        border_thickness = int(getattr(parent, "border_thickness", 1) or 1)
    except Exception:
        border_thickness = 1
    try:
        clip_margin = int(child_placement.get("parent_clip_margin", 0))
    except Exception:
        clip_margin = 0

    shrink = max(1, border_thickness + clip_margin)
    placement["size"] = max(0, parent_size - shrink)
    return placement


def parent_scan_bbox(region, regions_by_id: Dict[str, object], grid_size: int) -> Optional[Tuple[int, int, int, int]]:
    """Return the immediate parent's bbox as inclusive bounds, if available."""
    parent = get_parent_region(region, regions_by_id)
    if parent is None:
        return None
    placement = getattr(parent, "placement", {}) or {}
    if placement.get("type") == "full":
        return 0, 0, grid_size - 1, grid_size - 1
    cr, cc, size = get_center_size(placement, grid_size)
    return (
        max(0, cr - size),
        max(0, cc - size),
        min(grid_size - 1, cr + size),
        min(grid_size - 1, cc + size),
    )
