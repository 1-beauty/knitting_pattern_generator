"""
Baseline: LLM outputs structured shape descriptions, code rasterizes to 40x40 grid.

This baseline tests whether an LLM can describe a valid knitting pattern layout
without any structured intermediate representation (PatternPlan) or constraint
enforcement. The LLM outputs compact JSON describing shapes + actions, and a
simple rasterizer converts it to a 40x40 grid. No rule engine, no refinement,
no repair.
"""

import json
import re
import time
import math
import numpy as np
from typing import Dict, Any, Optional, List, Tuple

from config import GRID_SIZE
from core import actions
from rules import check_physical, check_craft_actions, tension_score
from llm.client import LLMClient
from utils.logger import logger


# ============================================================
# Prompt — compact structured output, NOT 1600 raw integers
# ============================================================

LLM_DIRECT_SYSTEM_PROMPT = """你是一个针织纹样布局描述器。

给定用户的针织图案描述，你需要输出一个紧凑的 JSON 布局描述，包含若干形状区域和对应的动作编号。
代码会将你的描述光栅化为 40x40 的动作网格。

## 动作编号表
0: 前床成圈（正针）
1: 后床成圈（反针）
2: 移针：前至后
3: 移针：后至前
4: 后床集圈
5: 空针背景（不织）— 用作画布外围安全背景
6: 移针并左移1针
7: 前床集圈
8: 前床劈针
9: 后床劈针
10: 前床集圈变体
11: 前后落布
12: 劈针变体
13: 后床集圈变体
14: 移针并右移1针

## 支持的形状类型
- "circle": 圆形，参数 center=[col,row], radius
- "rectangle": 矩形，参数 center=[col,row], width, height
- "diamond": 菱形，参数 center=[col,row], half_w, half_h
- "hexagon": 六边形，参数 center=[col,row], radius
- "triangle": 三角形，参数 center=[col,row], width, height
- "full": 覆盖整个画布

## 画布坐标系
- 画布大小 40x40，坐标范围 col=0..39, row=0..39
- center 格式为 [col, row]，通常居中在 [20, 20]

## 输出格式
输出一个 JSON 对象，包含 "regions" 数组。每个 region 有：
- "shape": 形状类型
- "center": [col, row]（"full" 形状不需要此字段）
- "params": 形状参数（radius / width+height / half_w+half_h 等）
- "fill_action": 区域内部填充的动作编号（0-14 整数）
- "border_action": 区域边框的动作编号（0-14 整数，可选）
- "border_width": 边框宽度（整数，默认1，可选）

## 关键规则
1. **必须使用多种动作编号**：至少使用 4 种不同的 fill_action。
2. **区域必须分层**：先定义的背景区域（如 full 形状），再定义内部形状。后面的区域会覆盖前面的。
3. **最外层背景**：第一个 region 应为 shape="full", fill_action=0（主体成圈）或 5（空针背景）。
4. **外围安全边框**：确保最外侧 2 圈为动作 5（可在第一个 full region 中设置 fill_action=5，然后用一个稍小的 shape 覆盖内部）。
5. **禁止偷懒**：不允许所有区域都用同一个 fill_action。

## 示例
描述：圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼
输出：
{
  "regions": [
    {"shape": "full", "fill_action": 5},
    {"shape": "rectangle", "center": [20, 20], "params": {"width": 34, "height": 34}, "fill_action": 0, "border_action": 1, "border_width": 2},
    {"shape": "circle", "center": [20, 20], "params": {"radius": 10}, "fill_action": 7, "border_action": 8, "border_width": 1},
    {"shape": "circle", "center": [20, 20], "params": {"radius": 5}, "fill_action": 4}
  ]
}

只输出 JSON，不要输出其他内容。"""


def build_llm_direct_user_prompt(user_input: str) -> str:
    return f"""请根据以下针织图案描述，输出布局 JSON。

描述：{user_input}

请输出包含 regions 数组的 JSON。"""


# ============================================================
# Rasterizer — convert shape descriptions to 40x40 grid
# ============================================================

def _draw_circle_mask(rows: int, cols: int, cr: int, cc: int, radius: float) -> np.ndarray:
    """Return boolean mask for a filled circle."""
    yy, xx = np.ogrid[:rows, :cols]
    return ((xx - cc) ** 2 + (yy - cr) ** 2) <= radius ** 2


def _draw_diamond_mask(rows: int, cols: int, cr: int, cc: int, hw: float, hh: float) -> np.ndarray:
    """Return boolean mask for a filled diamond."""
    yy, xx = np.ogrid[:rows, :cols]
    return (np.abs(xx - cc) / max(hw, 0.5) + np.abs(yy - cr) / max(hh, 0.5)) <= 1.0


def _draw_rectangle_mask(rows: int, cols: int, cr: int, cc: int, w: float, h: float) -> np.ndarray:
    """Return boolean mask for a filled rectangle."""
    half_w, half_h = w / 2, h / 2
    r0 = max(0, int(cr - half_h))
    r1 = min(rows, int(cr + half_h) + 1)
    c0 = max(0, int(cc - half_w))
    c1 = min(cols, int(cc + half_w) + 1)
    mask = np.zeros((rows, cols), dtype=bool)
    mask[r0:r1, c0:c1] = True
    return mask


def _draw_hexagon_mask(rows: int, cols: int, cr: int, cc: int, radius: float) -> np.ndarray:
    """Return boolean mask for a flat-top hexagon."""
    yy, xx = np.ogrid[:rows, :cols]
    dx = np.abs(xx - cc)
    dy = np.abs(yy - cr)
    # Flat-top hexagon: |dx| <= r, |dy| <= r*sqrt(3)/2, |dx|/r + |dy|/(r*sqrt(3)/2) <= ... simplified
    r = max(radius, 0.5)
    return (dx <= r) & (dy <= r * 0.866) & (dx / r + dy / (r * 0.866) <= 1.5)


def _draw_triangle_mask(rows: int, cols: int, cr: int, cc: int, w: float, h: float) -> np.ndarray:
    """Return boolean mask for an upward triangle."""
    mask = np.zeros((rows, cols), dtype=bool)
    half_w = w / 2
    for y in range(rows):
        t = (y - (cr - h / 2)) / max(h, 0.5)
        if 0 <= t <= 1:
            span = half_w * t
            c0 = max(0, int(cc - span))
            c1 = min(cols, int(cc + span) + 1)
            mask[y, c0:c1] = True
    return mask


def _get_shape_mask(shape: str, params: dict, center: list, rows: int, cols: int) -> np.ndarray:
    """Get boolean mask for a shape."""
    cc = center[0] if center else cols // 2
    cr = center[1] if center else rows // 2

    if shape == "full":
        return np.ones((rows, cols), dtype=bool)
    elif shape == "circle":
        return _draw_circle_mask(rows, cols, cr, cc, params.get("radius", 8))
    elif shape == "rectangle":
        return _draw_rectangle_mask(rows, cols, cr, cc, params.get("width", 16), params.get("height", 16))
    elif shape == "diamond":
        return _draw_diamond_mask(rows, cols, cr, cc, params.get("half_w", 8), params.get("half_h", 8))
    elif shape == "hexagon":
        return _draw_hexagon_mask(rows, cols, cr, cc, params.get("radius", 8))
    elif shape == "triangle":
        return _draw_triangle_mask(rows, cols, cr, cc, params.get("width", 16), params.get("height", 16))
    else:
        logger.warning(f"Unknown shape '{shape}', falling back to full")
        return np.ones((rows, cols), dtype=bool)


def _erode_mask(mask: np.ndarray, width: int) -> np.ndarray:
    """Erode a boolean mask by `width` pixels (for border extraction)."""
    from scipy.ndimage import binary_erosion
    if width <= 0:
        return mask
    return binary_erosion(mask, iterations=width)


def rasterize_regions(regions: List[Dict], grid_size: int = GRID_SIZE) -> np.ndarray:
    """Convert a list of region descriptions to a 40x40 action grid.

    Regions are drawn in order; later regions overwrite earlier ones.
    Each region has: shape, center, params, fill_action, border_action (optional), border_width (optional).
    """
    grid = np.full((grid_size, grid_size), 5, dtype=np.uint8)  # default background

    for region in regions:
        shape = region.get("shape", "full")
        center = region.get("center", [grid_size // 2, grid_size // 2])
        params = region.get("params", {})
        fill_action = int(np.clip(region.get("fill_action", 0), 0, 14))
        border_action = region.get("border_action", None)
        border_width = int(region.get("border_width", 1))

        mask = _get_shape_mask(shape, params, center, grid_size, grid_size)

        if border_action is not None and border_width > 0:
            border_action = int(np.clip(border_action, 0, 14))
            inner_mask = _erode_mask(mask, border_width)
            border_only = mask & ~inner_mask
            grid[border_only] = border_action
            grid[inner_mask] = fill_action
        else:
            grid[mask] = fill_action

    return grid


# ============================================================
# Parser
# ============================================================

def _strip_markdown(text: str) -> str:
    """Remove markdown code fences."""
    text = re.sub(r'```(?:json|python|raw)?\s*', '', text)
    return text.strip()


def parse_llm_direct_layout(llm_output: str) -> Optional[List[Dict]]:
    """Parse LLM output into a list of region dicts."""
    cleaned = _strip_markdown(llm_output)

    # Try json.loads
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict) and "regions" in obj:
            return obj["regions"]
        if isinstance(obj, list):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass

    # Try regex to extract JSON object with "regions"
    match = re.search(r'\{[^{}]*"regions"\s*:\s*\[.+\]\s*\}', cleaned, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if "regions" in obj:
                return obj["regions"]
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to find any JSON array of objects
    match = re.search(r'\[\s*\{.*\}\s*\]', cleaned, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group())
            if isinstance(arr, list) and all(isinstance(x, dict) for x in arr):
                return arr
        except (json.JSONDecodeError, TypeError):
            pass

    return None


# ============================================================
# Pipeline
# ============================================================

class LLMDirectPipeline:
    """Baseline: LLM outputs compact shape layout, code rasterizes to grid."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate(self, user_input: str) -> Dict[str, Any]:
        """Run the LLM-Direct baseline.

        Returns a dict with:
        - action_grid: np.ndarray (40, 40)
        - success: bool (whether grid was parsed)
        - hard_violations: int
        - craft_violations: int
        - tension: float
        - action_diversity: int
        - execution_time: float
        - distribution: dict
        """
        start = time.time()

        messages = [
            {"role": "system", "content": LLM_DIRECT_SYSTEM_PROMPT},
            {"role": "user", "content": build_llm_direct_user_prompt(user_input)},
        ]

        response = self.llm_client.chat(
            messages,
            temperature=0.1,
            max_tokens=4096,
            timeout=120,
        )

        if not response.success:
            logger.error(f"LLM-Direct: LLM call failed: {response.error}")
            return self._empty_result(time.time() - start, error=response.error)

        # Parse the compact layout description
        regions = parse_llm_direct_layout(response.content)
        if regions is None:
            logger.error("LLM-Direct: Failed to parse region layout from LLM output")
            logger.info(f"LLM-Direct: output first 500 chars:\n{response.content[:500]}")
            return self._empty_result(time.time() - start, error="parse_failed")

        # Rasterize regions to 40x40 grid
        grid = rasterize_regions(regions)

        logger.info(f"LLM-Direct: parsed {len(regions)} regions")

        # Reject grids with insufficient action diversity
        uniq_vals = np.unique(grid)
        if len(uniq_vals) < 3:
            logger.error(
                f"LLM-Direct: Grid only has {len(uniq_vals)} distinct action(s) "
                f"{uniq_vals.tolist()}, rejected as degenerate"
            )
            return self._empty_result(time.time() - start, error="degenerate_grid")

        # Run constraint checks (same as main pipeline)
        hard = check_physical(grid)
        craft = check_craft_actions(grid)
        tension = tension_score(grid)

        # Distribution
        uniq, counts = np.unique(grid, return_counts=True)
        distribution = {actions.abbr(int(i)): int(c) for i, c in zip(uniq, counts)}

        execution_time = time.time() - start

        result = {
            "action_grid": grid,
            "success": True,
            "hard_violations": len(hard),
            "craft_violations": len(craft),
            "tension_score": tension,
            "action_diversity": len(uniq),
            "execution_time": execution_time,
            "distribution": distribution,
            "hard_details": [self._v2d(v) for v in hard[:20]],
            "craft_details": [self._v2d(v) for v in craft[:20]],
        }

        logger.info(
            f"LLM-Direct: hard={len(hard)} craft={len(craft)} "
            f"tension={tension:.4f} diversity={len(uniq)} time={execution_time:.2f}s"
        )
        return result

    def _empty_result(self, execution_time: float, error: str = "") -> Dict[str, Any]:
        return {
            "action_grid": np.full((GRID_SIZE, GRID_SIZE), 5, dtype=np.uint8),  # all background
            "success": False,
            "hard_violations": -1,
            "craft_violations": -1,
            "tension_score": -1.0,
            "action_diversity": 0,
            "execution_time": execution_time,
            "distribution": {},
            "error": error,
        }

    def _v2d(self, v) -> Dict:
        return {
            "level": getattr(v, "level", ""),
            "rule": getattr(v, "rule", ""),
            "row": int(getattr(v, "row", -1)),
            "col": int(getattr(v, "col", -1)),
            "detail": getattr(v, "detail", ""),
        }
