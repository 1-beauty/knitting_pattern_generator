# -*- coding: utf-8 -*-
"""图 11 工厂上机试织三栏对照复合图（一区 navy 规范）。

行（F1–F5，与 outputs/factory_delivery/README_送厂说明.md 一致）：
  F1 = docs/images/1.png + 1真实.png  ↔ F1_pp01_circle_wave_preview.png
  F2 = docs/images/4.png + 4真实.png  ↔ F2_edt05_diamond_wave_preview.png
  F3 = docs/images/2.png + 2真实.png  ↔ F3_pp04_frame_rib_preview.png
  F4 = docs/images/5.png + 5真实.png  ↔ F4_edtp01_circle_honeycomb_preview.png
  F5 = docs/images/3.png + 3真实.png  ↔ F5_rnd03_frame_cross_preview.png

列：动作色码图（40×40，论文色表） | 结构感知视觉预览（Stage 4） | 工厂实织样片
输出：docs/figures/fig_factory_knitting.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = r"e:\DeskTop\knitting_pattern_generator"
IMG_DIR = os.path.join(ROOT, "docs", "images")
PREV_DIR = os.path.join(ROOT, "outputs", "factory_delivery")
OUT = os.path.join(ROOT, "docs", "figures", "fig_factory_knitting.png")

ROWS = [
    ("F1", "圆内波纹吊目点阵", "pp_01",   "1.png", "1真实.png", "F1_pp01_circle_wave_preview.png"),
    ("F2", "菱内波纹吊目点阵", "edt_05",  "4.png", "4真实.png", "F2_edt05_diamond_wave_preview.png"),
    ("F3", "框内罗纹纵条",     "pp_04",   "2.png", "2真实.png", "F3_pp04_frame_rib_preview.png"),
    ("F4", "圆环蜂窝吊目点阵", "edtp_01", "5.png", "5真实.png", "F4_edtp01_circle_honeycomb_preview.png"),
    ("F5", "X 形斜向交叉",     "rnd_03",  "3.png", "3真实.png", "F5_rnd03_frame_cross_preview.png"),
]
COL_HEADERS = ["动作色码图（40×40）", "结构感知视觉预览", "工厂实织样片"]

# 布局（一区规范：160mm 宽 → px2pt = 453.543/1008 ≈ 0.449；正文字号 ≥6pt → ≥14px）
PAD, LABEL_W, CELL, GAP = 28, 196, 236, 18
HEADER_H, ROW_GAP, BOTTOM_PAD = 64, 16, 28
W = PAD + LABEL_W + GAP + 3 * CELL + 2 * GAP + PAD
H = HEADER_H + 5 * CELL + 4 * ROW_GAP + BOTTOM_PAD

NAVY, DESC, LINE = (22, 50, 79), (90, 107, 124), (201, 214, 226)
BG, CELL_LINE = (255, 255, 255), (201, 214, 226)


def load_font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf" if bold else r"C:\Windows\Fonts\simsun.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def center_square(img):
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))


def paste_cell(canvas, img, x, y):
    canvas.paste(img, (x, y))
    ImageDraw.Draw(canvas).rectangle([x, y, x + img.width - 1, y + img.height - 1],
                                     outline=CELL_LINE, width=1)


def main():
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    f_head = load_font(18, bold=True)
    f_title = load_font(17, bold=True)
    f_desc = load_font(14)

    x0 = PAD + LABEL_W + GAP
    for ci, head in enumerate(COL_HEADERS):
        cx = x0 + ci * (CELL + GAP) + CELL // 2
        tw = draw.textlength(head, font=f_head)
        draw.text((cx - tw / 2, HEADER_H - 40), head, font=f_head, fill=NAVY)

    for ri, (fid, desc, run, cmap, photo, preview) in enumerate(ROWS):
        y = HEADER_H + ri * (CELL + ROW_GAP)
        # 行标签：F 编号 + 设计描述 + 来源 run
        draw.text((PAD, y + CELL // 2 - 30), fid, font=f_title, fill=NAVY)
        draw.text((PAD, y + CELL // 2 - 6), desc, font=f_desc, fill=DESC)
        draw.text((PAD, y + CELL // 2 + 14), f"run: {run}", font=f_desc, fill=DESC)

        im_map = Image.open(os.path.join(IMG_DIR, cmap)).convert("RGB")
        im_map = im_map.resize((CELL, CELL), Image.NEAREST)
        im_prev = Image.open(os.path.join(PREV_DIR, preview)).convert("RGB")
        im_prev = im_prev.resize((CELL, CELL), Image.LANCZOS)
        im_photo = Image.open(os.path.join(IMG_DIR, photo)).convert("RGB")
        im_photo = center_square(im_photo).resize((CELL, CELL), Image.LANCZOS)

        for ci, im in enumerate([im_map, im_prev, im_photo]):
            paste_cell(canvas, im, x0 + ci * (CELL + GAP), y)
        if ri == 0:
            print("sizes:", im_map.size, im_prev.size, im_photo.size)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    canvas.save(OUT, optimize=True)
    print("saved:", OUT, os.path.getsize(OUT), "bytes,", canvas.size)


if __name__ == "__main__":
    main()
