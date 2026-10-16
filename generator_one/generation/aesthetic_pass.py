"""
仿真感知美化层 v8.0

职责：
在 action grid 最终输出前，做轻量级的结构美化。
不改变图案逻辑，只做微调以确保仿真后的视觉质量。

说明：
- 在 rules check 之前执行
- 不使用 refinement actions（那些由 refinement_compiler 管）
- 只用 primary actions 做局部修饰
"""

import numpy as np
from typing import Dict
from core import actions
from utils.logger import logger
from generation.mask_utils import point_in_mask, get_mask_shape


class AestheticPass:
    """仿真感知美化"""

    def apply(self, action_grid: np.ndarray, realization_plan=None) -> np.ndarray:
        result = action_grid.copy()

        fixes = {
            "symmetry_fixes": 0,
            "border_smoothing": 0,
        }

        # Pass 1: 交叉对称性修正
        #
        # 只处理真正的移针结构。波浪吊目由 split+tuck 成对表达，
        # 如果在这里按“每行左右数量”硬裁，会把成对纹理剪成单点，
        # 仿真时就会变成明显破洞。
        fixes["symmetry_fixes"] = self._fix_crossing_symmetry(result)

        # Pass 2: 孤立特殊动作清理（已禁用，避免清掉骨架）
        # 由 compiler_guard 和 wave_pair_guard 在后处理中负责

        # Pass 3: 几何边缘微调
        if realization_plan is not None:
            fixes["border_smoothing"] += self._smooth_geometric_borders(result, realization_plan)

        logger.info(f"  aesthetic pass: {fixes}")
        return result

    def _smooth_geometric_borders(self, grid: np.ndarray, realization_plan) -> int:
        """针对 rectangle/circle 等几何掩码做轻量边缘修整，减少颗粒感。"""
        rows, cols = grid.shape
        fixes = 0
        _f_knit = actions.idx("f_knit")
        _b_knit = actions.idx("b_knit")
        _special = actions.split_ids() | actions.tuck_ids() | actions.miss_ids()
        child_masks_by_parent = self._child_masks_by_parent(realization_plan)

        for region in getattr(realization_plan, "regions", []) or []:
            placement = getattr(region, "placement", {}) or {}
            border_style = str(getattr(region, "border_style", "none") or "none").lower()
            if border_style == "none":
                continue
            shape = get_mask_shape(placement)
            # 扩展支持：多边形、菱形、六边形、三角、条带、柱状等
            if shape not in {
                "rectangle", "rect", "frame", "border", "panel", "square", "box",
                "circle", "oval", "ellipse",
                "diamond", "rhombus", "hexagon", "hex", "triangle",
                "stripe", "stripes", "column"
            }:
                continue

            # 从 event_params 读取参数热加载值
            event_params = getattr(region, "event_params", {}) or {}
            smoothing_threshold = int(event_params.get("smoothing_threshold", 1))
            vertex_smoothing = bool(event_params.get("vertex_smoothing", False))
            vertex_neighbor_threshold = int(event_params.get("vertex_neighbor_threshold", 2))

            try:
                size = int(placement.get("size", 0))
            except Exception:
                size = 0
            if size <= 1:
                continue

            inner = dict(placement)
            inner["size"] = max(0, size - 1)

            for r in range(rows):
                for c in range(cols):
                    in_outer = point_in_mask(r, c, placement, rows)
                    if not in_outer:
                        continue
                    in_inner = point_in_mask(r, c, inner, rows) if inner["size"] > 0 else False
                    is_ring = in_outer and (not in_inner)
                    if not is_ring:
                        continue

                    # 1) 边框环统一为 b_knit，避免断续锯齿
                    if int(grid[r, c]) != _b_knit:
                        grid[r, c] = _b_knit
                        fixes += 1

                    # 2) 紧贴边框的孤立特殊动作回退为 f_knit，减少颗粒
                    # 使用从 event_params 读取的 smoothing_threshold
                    neighbor_threshold = smoothing_threshold

                    for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ni, nj = r + di, c + dj
                        if not (0 <= ni < rows and 0 <= nj < cols):
                            continue
                        if int(grid[ni, nj]) not in _special:
                            continue
                        if self._is_inside_child_mask(ni, nj, region, child_masks_by_parent, rows):
                            continue

                        # split/tuck 是波浪吊目的成对色块，边缘处不能按
                        # “孤立同类邻居”单独删除，否则会留下半个波浪。
                        if int(grid[ni, nj]) in (actions.split_ids() | actions.tuck_ids()):
                            continue

                        same_special_neighbors = 0
                        for ddi, ddj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            xi, xj = ni + ddi, nj + ddj
                            if 0 <= xi < rows and 0 <= xj < cols and int(grid[xi, xj]) == int(grid[ni, nj]):
                                same_special_neighbors += 1
                        if same_special_neighbors <= neighbor_threshold:
                            grid[ni, nj] = _f_knit
                            fixes += 1

            # 3) 多边形顶点缓和：把那些仅有很少环邻居的角落附近的孤立特殊动作回退为 f_knit
            if vertex_smoothing and shape in {"diamond", "rhombus", "hexagon", "hex", "triangle"}:
                # 收集所有环上的坐标
                ring_coords = []
                inner = dict(placement)
                try:
                    inner["size"] = max(0, int(placement.get("size", 0)) - 1)
                except Exception:
                    inner["size"] = max(0, 0)

                for r in range(rows):
                    for c in range(cols):
                        in_outer = point_in_mask(r, c, placement, rows)
                        if not in_outer:
                            continue
                        in_inner = point_in_mask(r, c, inner, rows) if inner["size"] > 0 else False
                        is_ring = in_outer and (not in_inner)
                        if is_ring:
                            ring_coords.append((r, c))

                ring_set = set(ring_coords)
                for (rr, cc) in ring_coords:
                    # 统计环上邻居数量
                    neighbor_count = 0
                    for di in [-1, 0, 1]:
                        for dj in [-1, 0, 1]:
                            if di == 0 and dj == 0:
                                continue
                            ni, nj = rr + di, cc + dj
                            if (ni, nj) in ring_set:
                                neighbor_count += 1

                    # 若邻居 <= vertex_neighbor_threshold，说明是尖角区域，积极回退其内侧相邻的孤立特殊动作
                    if neighbor_count <= vertex_neighbor_threshold:
                        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            ni, nj = rr + di, cc + dj
                            if not (0 <= ni < rows and 0 <= nj < cols):
                                continue
                            if int(grid[ni, nj]) in _special:
                                # 若该特殊动作周围无同类邻居，则回退
                                same_special_neighbors = 0
                                for ddi, ddj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                                    xi, xj = ni + ddi, nj + ddj
                                    if 0 <= xi < rows and 0 <= xj < cols and int(grid[xi, xj]) == int(grid[ni, nj]):
                                        same_special_neighbors += 1
                                if same_special_neighbors <= 1:
                                    grid[ni, nj] = _f_knit
                                    fixes += 1

        return fixes

    def _fix_crossing_symmetry(self, grid: np.ndarray) -> int:
        """确保每行的 xfer_l1 和 xfer_r1 数量相等"""
        rows, cols = grid.shape
        fixes = 0
        _LEFT = actions.left_transfer_ids()
        _RIGHT = actions.right_transfer_ids()
        _f_knit = actions.idx("f_knit")

        for i in range(rows):
            left_count = sum(1 for j in range(cols) if int(grid[i, j]) in _LEFT)
            right_count = sum(1 for j in range(cols) if int(grid[i, j]) in _RIGHT)

            while left_count > right_count + 1:
                for j in range(cols - 1, -1, -1):
                    if int(grid[i, j]) in _LEFT:
                        grid[i, j] = _f_knit
                        left_count -= 1
                        fixes += 1
                        break

            while right_count > left_count + 1:
                for j in range(cols):
                    if int(grid[i, j]) in _RIGHT:
                        grid[i, j] = _f_knit
                        right_count -= 1
                        fixes += 1
                        break

        return fixes

    def _child_masks_by_parent(self, realization_plan) -> Dict[str, list]:
        masks: Dict[str, list] = {}
        for child in getattr(realization_plan, "regions", []) or []:
            placement = getattr(child, "placement", {}) or {}
            parent_id = placement.get("parent_id")
            if not parent_id or not placement.get("clip_to_parent"):
                continue
            if not get_mask_shape(placement):
                continue
            masks.setdefault(str(parent_id), []).append(placement)
        return masks

    def _is_inside_child_mask(self, r: int, c: int, parent_region, child_masks_by_parent: Dict[str, list], grid_size: int) -> bool:
        parent_id = str(getattr(parent_region, "region_id", "") or "")
        for placement in child_masks_by_parent.get(parent_id, []):
            try:
                if point_in_mask(r, c, placement, grid_size):
                    return True
            except Exception:
                continue
        return False
