"""生成 PPT 用的规则示意图（中文，配色与 PPT 一致）。

产出：
  docs/figures/ppt/fig_repair_cases.png   三类硬约束违例 → 保守修复的前后对照
  docs/figures/ppt/fig_action_space.png   十五色动作空间总表（含工艺属性等级）
  docs/figures/ppt/cmap_zoom.png          真实色码图局部放大 + 成组配对标注
  docs/figures/ppt/cmap_full.png          真实色码图整幅（最近邻放大，像素清晰）

网格里的颜色取自 generator_one/data/instruction_info.json 的真实动作配色，
色码图取自 outputs/runs 下的真实运行产物。
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib.patches import FancyArrow, Rectangle     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "ppt"
INFO = ROOT / "generator_one" / "data" / "instruction_info.json"
RUN = ROOT / "outputs" / "runs" / "gui" / "20260731_155816"
BMP = RUN / "color_map" / "pattern_output.bmp"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#1E3A8A"
INK = "#1A1A2E"
MUTED = "#64748B"
RED = "#DC2626"
GREEN = "#059669"
GRID = "#94A3B8"


def load_items() -> list[dict]:
    data = json.loads(INFO.read_text(encoding="utf-8"))
    items = data["instructions"] if isinstance(data, dict) and "instructions" in data else data
    if isinstance(items, dict):
        items = list(items.values())
    return list(items)


def load_colors() -> dict[str, str]:
    data = json.loads(INFO.read_text(encoding="utf-8"))
    items = data["instructions"] if isinstance(data, dict) and "instructions" in data else data
    out = {}
    if isinstance(items, dict):
        items = list(items.values())
    for it in items:
        abbr = it.get("abbr") or it.get("name")
        col = it.get("color")
        if abbr and col:
            out[abbr] = col if str(col).startswith("#") else "#" + str(col)
    return out


# ============================================================
# 图一：违例 → 修复 前后对照
# ============================================================

def draw_grid(ax, cells, *, n_rows, n_cols, mark=None, bad=True,
              arrows=(), title="", title_color=INK):
    """cells: {(row, col): 颜色}，行 0 在最上。

    mark 处画一个粗框 + 字符标记：bad=True 为违例（✗），否则为修复后（✓）。
    网格底色可能本身就是红色，所以违例框用深墨色而不用红色。
    """
    ax.set_xlim(-0.15, n_cols + 0.15)
    ax.set_ylim(-0.15, n_rows + 0.15)
    ax.invert_yaxis()
    ax.set_aspect("equal")
    ax.axis("off")
    for r in range(n_rows):
        for c in range(n_cols):
            col = cells.get((r, c), "#FFFFFF")
            ax.add_patch(Rectangle((c, r), 1, 1, facecolor=col,
                                   edgecolor=GRID, linewidth=0.7))
    for (r0, c0, r1, c1) in arrows:
        ax.add_patch(FancyArrow(c0 + 0.5, r0 + 0.5, (c1 - c0), (r1 - r0),
                                width=0.04, head_width=0.22, head_length=0.28,
                                length_includes_head=True, color="#111827",
                                zorder=5))
    if mark:
        r, c = mark
        edge = "#111827" if bad else GREEN
        ax.add_patch(Rectangle((c + 0.05, r + 0.05), 0.90, 0.90,
                               facecolor="none", edgecolor=edge,
                               linewidth=2.8, zorder=6))
        # ✓/✗ 在 Microsoft YaHei 里缺字形，改用 × / √
        ax.text(c + 0.5, r + 0.5, "×" if bad else "√", ha="center",
                va="center", fontsize=13, fontweight="bold", color=edge,
                zorder=7)
    if title:
        ax.set_title(title, fontsize=9.5, color=title_color, pad=6)


def fig_repair_cases(colors: dict[str, str]):
    K = colors["f_knit"]
    B = colors["b_knit"]
    M = colors["miss"]
    T = colors["f_tuck"]
    S = colors["f_split"]
    L = colors["xfer_l1"]
    R = colors["xfer_r1"]

    fig = plt.figure(figsize=(12.2, 2.75), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    # 每个案例占 4 个栅格列：违例网格、箭头、修复网格、说明
    gs = fig.add_gridspec(1, 11, width_ratios=[
        1, 0.42, 1, 0.30,      # 案例一
        1, 0.42, 1, 0.30,      # 案例二
        1, 0.42, 1,            # 案例三
    ], wspace=0.12, left=0.015, right=0.985, top=0.80, bottom=0.10)

    def arrow_axis(idx, label):
        ax = fig.add_subplot(gs[0, idx])
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.annotate("", xy=(0.92, 0.52), xytext=(0.08, 0.52),
                    arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=2.0))
        ax.text(0.5, 0.72, label, ha="center", va="bottom", fontsize=8.5,
                color=GREEN)

    # ---------- 案例一：H2 线圈下方缺少支撑 ----------
    base = {(r, c): K for r in range(4) for c in range(5)}
    bad = dict(base)
    bad[(3, 2)] = M                      # 下方为空针
    ax = fig.add_subplot(gs[0, 0])
    draw_grid(ax, bad, n_rows=4, n_cols=5, mark=(2, 2),
              title="H2  线圈下方为空针", title_color=RED)
    arrow_axis(1, "降级")
    fix = dict(bad)
    fix[(2, 2)] = M                      # 本格降级为 miss，不粗暴覆盖镂空
    ax = fig.add_subplot(gs[0, 2])
    draw_grid(ax, fix, n_rows=4, n_cols=5, mark=(2, 2), bad=False,
              title="本格降级为空针（保留镂空）", title_color=GREEN)

    # ---------- 案例二：H5 同行移针目标冲突 ----------
    bad = {(r, c): K for r in range(4) for c in range(5)}
    bad[(1, 1)] = R
    bad[(1, 3)] = L
    ax = fig.add_subplot(gs[0, 4])
    draw_grid(ax, bad, n_rows=4, n_cols=5, mark=(1, 3),
              arrows=((1, 1, 1, 2), (1, 3, 1, 2)),
              title="H5  两针移向同一目标列", title_color=RED)
    arrow_axis(5, "改写")
    fix = dict(bad)
    fix[(1, 3)] = S
    ax = fig.add_subplot(gs[0, 6])
    draw_grid(ax, fix, n_rows=4, n_cols=5, mark=(1, 3), bad=False,
              arrows=((1, 1, 1, 2),),
              title="冲突方改为劈针", title_color=GREEN)

    # ---------- 案例三：H6 同列连续集圈超上限 ----------
    bad = {(r, c): K for r in range(5) for c in range(5)}
    for r in range(4):
        bad[(r, 2)] = T
    ax = fig.add_subplot(gs[0, 8])
    draw_grid(ax, bad, n_rows=5, n_cols=5, mark=(0, 2),
              title="H6  同列连续集圈 4 行 > 上限 3", title_color=RED)
    arrow_axis(9, "打断")
    fix = dict(bad)
    fix[(0, 2)] = K
    ax = fig.add_subplot(gs[0, 10])
    draw_grid(ax, fix, n_rows=5, n_cols=5, mark=(0, 2), bad=False,
              title="插入成圈打断堆叠", title_color=GREEN)

    path = OUT / "fig_repair_cases.png"
    fig.savefig(path, facecolor="#FFFFFF", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    print("[fig]", path)


# ============================================================
# 图二：十五色动作空间总表
# ============================================================

SEM_CN = {
    "LOOP": "成圈", "TUCK": "集圈", "TRANSFER": "移针", "SPLIT": "劈针",
    "EMPTY": "空针", "DROP": "落布", "MISS": "浮针", "CARRIER": "约纱嘴",
}
BED_CN = {"front": "前床", "back": "后床", None: "—", "": "—"}
# 两列分配：左列放基础与背景类，右列放变形与过渡类，两边行数接近
COLUMNS = [["LOOP", "TUCK", "EMPTY", "DROP"], ["TRANSFER", "SPLIT"]]

# 列内横向坐标（相对列左边，单位英寸）
X_SWATCH, X_IDX, X_ABBR, X_NAME, X_BED = 0.06, 0.50, 0.66, 1.56, 3.12
X_BARS = (3.45, 4.35, 5.25)
BAR_W = 0.60
COL_W = 6.05
ROW_H = 0.26
HEAD_H = 0.30


def _level_bar(ax, x, y, val, vmax, color):
    """画一条归一化的等级条，右侧跟数值。"""
    h = 0.15
    ax.add_patch(Rectangle((x, y - h / 2), BAR_W, h, facecolor="#E2E8F0",
                           edgecolor="none"))
    ax.add_patch(Rectangle((x, y - h / 2), BAR_W * val / vmax, h,
                           facecolor=color, edgecolor="none"))
    ax.text(x + BAR_W + 0.05, y, str(val), ha="left", va="center",
            fontsize=6.8, color=MUTED)


def fig_action_space(items: list[dict]):
    """按语义类别分组列出 15 个动作：色块 / 编号 / 缩写 / 中文名 / 床位 / T・E・S。

    动作编号就是数组下标，与训练数据的色序一致，所以要把编号一并标出。
    坐标系直接用英寸（与 figsize 同尺度），避免拉伸变形。
    """
    groups: dict[str, list[tuple[int, dict]]] = {}
    for idx, it in enumerate(items):
        groups.setdefault(it.get("semantic", "?"), []).append((idx, it))

    # 没列入 COLUMNS 的类别归到行数少的那列，不让任何动作漏掉
    cols = [[s for s in c if s in groups] for c in COLUMNS]
    for sem in groups:
        if not any(sem in c for c in cols):
            cols[min(range(2), key=lambda i: len(cols[i]))].append(sem)

    def col_height(sems):
        return sum(HEAD_H + 0.06 + ROW_H * len(groups[s]) + 0.14
                   for s in sems)

    top_pad = 0.26                       # 给顶部 T/E/S 图例留出一行
    H = top_pad + max(col_height(c) for c in cols) + 0.06
    fig = plt.figure(figsize=(12.4, H), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, H)
    ax.invert_yaxis()
    ax.axis("off")

    col_x = [0.10, 6.25]
    bar_meta = (("张力", 7, "#DC2626"), ("弹性", 5, "#0891B2"),
                ("稳定", 5, GREEN))

    for ci, sems in enumerate(cols):
        x0 = col_x[ci]
        # 表头：三条等级条分别是什么
        for (label, vmax, color), bx in zip(bar_meta, X_BARS):
            ax.text(x0 + bx, top_pad - 0.11, f"{label} 1-{vmax}", ha="left",
                    va="center", fontsize=6.6, color=color)
        y = top_pad

        for sem in sems:
            rows = groups[sem]
            ax.add_patch(Rectangle((x0, y), COL_W, HEAD_H, facecolor=NAVY,
                                   edgecolor="none"))
            ax.text(x0 + 0.10, y + HEAD_H / 2,
                    f"{SEM_CN.get(sem, sem)}  {sem}", ha="left",
                    va="center", fontsize=8.5, color="#FFFFFF",
                    fontweight="bold")
            ax.text(x0 + COL_W - 0.10, y + HEAD_H / 2, f"{len(rows)} 个",
                    ha="right", va="center", fontsize=7.5, color="#BFDBFE")
            y += HEAD_H + 0.06

            for k, (idx, it) in enumerate(rows):
                cy = y + ROW_H / 2
                if k % 2 == 0:
                    ax.add_patch(Rectangle((x0, y), COL_W, ROW_H,
                                           facecolor="#F8FAFC",
                                           edgecolor="none"))
                ax.add_patch(Rectangle((x0 + X_SWATCH, y + 0.035), 0.36,
                                       ROW_H - 0.07, facecolor=it["color"],
                                       edgecolor=GRID, linewidth=0.6))
                ax.text(x0 + X_IDX, cy, str(idx), ha="center", va="center",
                        fontsize=7, color=MUTED)
                ax.text(x0 + X_ABBR, cy, it["abbr"], ha="left", va="center",
                        fontsize=7.8, color=INK, fontfamily="Consolas")
                ax.text(x0 + X_NAME, cy, it["name"], ha="left", va="center",
                        fontsize=7.8, color=INK)
                ax.text(x0 + X_BED, cy, BED_CN.get(it.get("bed"), "—"),
                        ha="center", va="center", fontsize=7, color=MUTED)
                for (_, vmax, color), bx, key in zip(
                        bar_meta, X_BARS,
                        ("tension", "elasticity", "stability")):
                    _level_bar(ax, x0 + bx, cy, it[key], vmax, color)
                y += ROW_H
            y += 0.14

    path = OUT / "fig_action_space.png"
    fig.savefig(path, facecolor="#FFFFFF", bbox_inches="tight",
                pad_inches=0.04)
    plt.close(fig)
    print("[fig]", path)


# ============================================================
# 图三：真实色码图整幅 + 局部放大
# ============================================================

def cmap_figures(colors: dict[str, str]):
    """产出两张图：整幅色码图（最近邻放大）与局部放大。

    局部图用来讲“成组完整性”：波浪吊目每个单元是“劈针在左、集圈在右”
    的相邻两格（对应 split_col_offset=2 / tuck_col_offset=3），只剩单边的
    格子会被波浪配对守卫删除。
    """
    from PIL import Image
    import numpy as np

    if not BMP.exists():
        print("[warn] 缺少真实产物，跳过色码图：", BMP)
        return

    # ---------- 整幅：最近邻放大到 960px，保证 PPT 里像素边界清晰 ----------
    im = Image.open(BMP).convert("RGB")
    im.resize((960, 960), Image.NEAREST).save(OUT / "cmap_full.png")
    print("[fig]", OUT / "cmap_full.png")

    # ---------- 局部：找一块同时含 f_tuck 与 f_split 的区域 ----------
    rgb = np.array(im)
    items = load_items()
    idx_of = {it["abbr"]: i for i, it in enumerate(items)}
    pal = {i: tuple(int(items[i]["color"][1:][k:k + 2], 16)
                    for k in (0, 2, 4)) for i in range(len(items))}

    def mask_of(abbr):
        c = np.array(pal[idx_of[abbr]])
        return np.all(np.abs(rgb.astype(int) - c) <= 8, axis=-1)

    m_tuck, m_split = mask_of("f_tuck"), mask_of("f_split")
    ys, xs = np.where(m_tuck | m_split)
    if len(ys) == 0:
        print("[warn] 该运行未出现 f_tuck/f_split，跳过局部图")
        return
    span = 13
    r0 = int(np.clip(ys.mean() - span // 2, 0, rgb.shape[0] - span))
    c0 = int(np.clip(xs.mean() - span // 2, 0, rgb.shape[1] - span))

    fig, ax = plt.subplots(figsize=(3.6, 3.6), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_xlim(0, span)
    ax.set_ylim(0, span)
    ax.invert_yaxis()
    ax.set_aspect("equal")
    ax.axis("off")
    for r in range(span):
        for c in range(span):
            px = rgb[r0 + r, c0 + c] / 255.0
            ax.add_patch(Rectangle((c, r), 1, 1, facecolor=px,
                                   edgecolor=GRID, linewidth=0.5))
    # 把每一对相邻的劈针(左)+集圈(右)用一个框圈起来
    pairs = 0
    for r in range(span):
        for c in range(span - 1):
            if m_split[r0 + r, c0 + c] and m_tuck[r0 + r, c0 + c + 1]:
                ax.add_patch(Rectangle((c + 0.04, r + 0.04), 1.92, 0.92,
                                       facecolor="none", edgecolor="#111827",
                                       linewidth=1.8, zorder=6))
                pairs += 1
    ax.set_title(f"波浪吊目：劈针与集圈始终成对出现（图中 {pairs} 对）",
                 fontsize=8.5, color=INK, pad=6)
    path = OUT / "cmap_zoom.png"
    fig.savefig(path, facecolor="#FFFFFF", bbox_inches="tight",
                pad_inches=0.05)
    plt.close(fig)
    print("[fig]", path, f"crop=({r0},{c0}) span={span} pairs={pairs}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    colors = load_colors()
    missing = [k for k in ("f_knit", "b_knit", "miss", "f_tuck", "f_split",
                           "xfer_l1", "xfer_r1") if k not in colors]
    if missing:
        raise SystemExit(f"动作配色缺失: {missing}（共读到 {len(colors)} 个）")
    print(f"[info] 读到 {len(colors)} 个动作配色")
    fig_repair_cases(colors)
    fig_action_space(load_items())
    cmap_figures(colors)


if __name__ == "__main__":
    main()
