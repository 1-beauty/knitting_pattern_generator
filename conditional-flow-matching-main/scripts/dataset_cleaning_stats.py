"""数据清理统计：扫描 color map PNG 的颜色构成，核算 FR2/FL2 样本级过滤统计。

- 对 dataset_raw（论文使用的 4028 对）验证所有像素均落在 15 色调色板内；
- 对 dataset_raw_pruned_backup（清理前备份）统计含 15 色之外颜色（FR2/FL2 等
  被删动作色）的样本数及其类别分布；
- 输出按类别的过滤前/后分布，供补充材料"数据清理统计"表使用。

用法：
    python conditional-flow-matching-main/scripts/dataset_cleaning_stats.py
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_palette() -> tuple[np.ndarray, list[str]]:
    with (ROOT / "assets/instructions.json").open(encoding="utf-8") as f:
        data = json.load(f)
    colors, abbrs = [], []
    for inst in data["instructions"]:
        h = inst["color"].lstrip("#")
        colors.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        abbrs.append(inst["abbr"])
    return np.array(colors, dtype=np.int32), abbrs


def scan_dir(color_dir: Path, palette: np.ndarray) -> dict:
    """逐类别统计：样本总数、含非调色板颜色的样本数、非调色板颜色集合。"""
    stats: dict = {}
    for cat_dir in sorted(p for p in color_dir.iterdir() if p.is_dir()):
        total, offpal, off_colors = 0, 0, collections.Counter()
        for png in sorted(cat_dir.glob("*.png")):
            arr = np.array(Image.open(png).convert("RGB"))
            uniq = np.unique(arr.reshape(-1, 3), axis=0)
            # 与调色板精确匹配（原始 color map 为无损 PNG，颜色应精确一致）
            match = (uniq[:, None, :] == palette[None, :, :]).all(-1).any(-1)
            total += 1
            if not match.all():
                offpal += 1
                for rgb in uniq[~match]:
                    off_colors[tuple(int(v) for v in rgb)] += 1
        stats[cat_dir.name] = {
            "total": total, "off_palette_samples": offpal,
            "off_palette_colors": dict(off_colors),
        }
    return stats


def report(name: str, stats: dict) -> None:
    print(f"\n=== {name} ===")
    print("| 类别 | 样本数 | 含 15 色之外颜色的样本数 |")
    print("| --- | ---: | ---: |")
    t_all = t_off = 0
    color_pool: collections.Counter = collections.Counter()
    for cat, s in stats.items():
        print(f"| {cat} | {s['total']} | {s['off_palette_samples']} |")
        t_all += s["total"]
        t_off += s["off_palette_samples"]
        color_pool.update(s["off_palette_colors"])
    print(f"| 合计 | {t_all} | {t_off} |")
    if color_pool:
        print("非调色板颜色（RGB: 出现样本次数）：")
        for rgb, n in color_pool.most_common():
            print(f"  {rgb}: {n}")


def main() -> None:
    palette, abbrs = load_palette()
    print(f"15 色调色板（{len(abbrs)} 类）：{abbrs}")
    for name, sub in [("dataset_raw（论文使用，过滤后）", "dataset_raw/color_maps"),
                      ("dataset_raw_pruned_backup（清理前备份）", "dataset_raw_pruned_backup/color_maps")]:
        d = ROOT / sub
        if d.exists():
            report(name, scan_dir(d, palette))
        else:
            print(f"[skip] 目录不存在: {d}")


if __name__ == "__main__":
    main()
