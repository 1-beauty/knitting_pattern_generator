"""Deterministic adapter from Stage I color maps to simulator conditions.

Stage I color maps are instruction grids. Each pixel/cell already has one
knitting instruction, so the adapter must not vote or smooth those IDs away.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

BACKGROUND_ID = 0
ROOT = Path(__file__).resolve().parents[2]
STAGE1_INSTRUCTION_INFO = ROOT / "generator_one" / "data" / "instruction_info.json"


def _load_stage1_color_table():
    with STAGE1_INSTRUCTION_INFO.open("r", encoding="utf-8") as f:
        data = json.load(f)

    colors = []
    for inst in data.get("instructions", []):
        hex_color = str(inst.get("color", "")).lstrip("#")
        if len(hex_color) != 6:
            continue
        colors.append((
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
        ))

    if not colors:
        raise ValueError(f"No colors found in {STAGE1_INSTRUCTION_INFO}")
    return np.array(colors, dtype=np.int32)


def _rgb_to_id_with_diagnostics(rgb_array, color_table, source_label):
    flat = rgb_array.reshape(-1, 3).astype(np.int32)
    diff = flat[:, None, :] - color_table[None, :, :]
    dist = np.sum(diff ** 2, axis=-1)
    ids = np.argmin(dist, axis=-1).astype(np.int32)
    min_dist = dist[np.arange(dist.shape[0]), ids]

    exact = int(np.sum(min_dist == 0))
    total = int(flat.shape[0])
    if exact < total:
        unknown = total - exact
        worst = float(np.sqrt(min_dist.max()))
        print(
            f"Stage1 color parse: {unknown}/{total} pixels were not exact palette "
            f"matches ({source_label}); nearest-color fallback used, max_rgb_distance={worst:.1f}"
        )

    return ids.reshape(rgb_array.shape[:2])


def sample_id_map(full_id_map, output_size, preserve_special=True):
    """Downsample a Stage I instruction grid to the simulator grid.

    Stage I color maps are sparse action grids. A pure center sample can miss
    thin borders, waves, eyelets, and transfer support actions, making Stage II
    see almost all background. The default therefore keeps the most important
    non-background action in each source block when one exists.
    """
    h, w = full_id_map.shape
    if output_size <= 0:
        raise ValueError(f"output_size must be positive, got {output_size}")

    if not preserve_special:
        row_idx = np.floor((np.arange(output_size) + 0.5) * h / output_size).astype(int)
        col_idx = np.floor((np.arange(output_size) + 0.5) * w / output_size).astype(int)
        row_idx = np.clip(row_idx, 0, h - 1)
        col_idx = np.clip(col_idx, 0, w - 1)
        return full_id_map[np.ix_(row_idx, col_idx)].astype(np.int32)

    # Higher priority wins when several sparse actions appear in the same block.
    priority = {
        6: 90,   # miss
        10: 85,  # f_tuck_2
        13: 85,  # b_tuck_2
        7: 80,   # xfer_l1
        14: 80,  # xfer_r1
        2: 75,   # xfer_f_b
        3: 75,   # xfer_b_f
        8: 70,   # f_tuck
        4: 70,   # b_tuck
        9: 65,   # f_split
        11: 65,  # b_split
        12: 65,  # split_v
        1: 40,   # b_knit
        0: 10,   # f_knit
    }

    out = np.zeros((output_size, output_size), dtype=np.int32)
    for r in range(output_size):
        r0 = int(np.floor(r * h / output_size))
        r1 = int(np.floor((r + 1) * h / output_size))
        r1 = max(r0 + 1, min(h, r1))
        for c in range(output_size):
            c0 = int(np.floor(c * w / output_size))
            c1 = int(np.floor((c + 1) * w / output_size))
            c1 = max(c0 + 1, min(w, c1))
            block = full_id_map[r0:r1, c0:c1].reshape(-1)
            values, counts = np.unique(block, return_counts=True)
            best = max(
                zip(values.tolist(), counts.tolist()),
                key=lambda vc: (priority.get(int(vc[0]), 50), vc[1]),
            )[0]
            out[r, c] = int(best)
    return out


def parse_stage1_color_map(image_path, color_table=None, grid_size=None):
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    source_label = "simulator palette"
    try:
        stage1_color_table = _load_stage1_color_table()
        if color_table is None or len(stage1_color_table) == len(color_table):
            color_table = stage1_color_table
            source_label = "generator_one/data/instruction_info.json"
    except Exception as exc:
        if color_table is None:
            raise
        print(f"Stage1 color parse: failed to load generator palette ({exc}); using simulator palette")

    full_id_map = _rgb_to_id_with_diagnostics(arr, color_table, source_label)

    h, w = full_id_map.shape
    if grid_size is None:
        return full_id_map.astype(np.int32)

    if h < grid_size or w < grid_size:
        raise ValueError(f"Stage I color map is too small for {grid_size}x{grid_size}: {(h, w)}")

    if (h, w) == (grid_size, grid_size):
        return full_id_map.astype(np.int32)
    return sample_id_map(full_id_map, grid_size, preserve_special=True)
