"""Pass 2: vertical-balance rebalancing for S2 / S5 / S7 / S12.
Keyed by (slide_index, shape_id). Content and styling untouched; only
positions/sizes change so每页内容在版心内均衡分布.
"""
from pptx import Presentation
from pptx.util import Inches

PATH = r"e:\DeskTop\knitting_ai_competition.pptx"
prs = Presentation(PATH)


def shp_map(slide_idx):
    slide = prs.slides[slide_idx - 1]
    return {sh.shape_id: sh for sh in slide.shapes}


def set_pos(sh, l=None, t=None, w=None, h=None):
    if l is not None:
        sh.left = Inches(l)
    if t is not None:
        sh.top = Inches(t)
    if w is not None:
        sh.width = Inches(w)
    if h is not None:
        sh.height = Inches(h)


def delete(sh):
    el = sh._element
    el.getparent().remove(el)


# ============================================================
# SLIDE 2 — TOC: single left column -> two columns (01-04 | 05-07)
# ============================================================
s2 = shp_map(2)
LB, LT = 1.0, 1.55          # left col: box x, title x
RB, RT = 7.0, 7.55          # right col
rows_l = [1.8, 3.1, 4.4, 5.7]
rows_r = [2.45, 3.75, 5.05]
items = [  # (box, num, title, sub, conn_after)
    (6, 7, 8, 9, 10), (11, 12, 13, 14, 15), (16, 17, 18, 19, 20),
    (21, 22, 23, 24, 25), (26, 27, 28, 29, 30), (31, 32, 33, 34, 35),
    (36, 37, 38, 39, None),
]
for i, (box, num, title, sub, conn) in enumerate(items):
    if i < 4:
        bx, tx, t = LB, LT, rows_l[i]
        in_col = i < 3          # connector stays within the column
        cx = LB + 0.205
    else:
        bx, tx, t = RB, RT, rows_r[i - 4]
        in_col = i < 6
        cx = RB + 0.205
    set_pos(s2[box], l=bx, t=t)
    set_pos(s2[num], l=bx, t=t)
    set_pos(s2[title], l=tx, t=t)
    set_pos(s2[sub], l=tx, t=t + 0.22)
    if conn is not None:
        if in_col:
            set_pos(s2[conn], l=cx, t=t + 0.55, h=0.6)
        else:
            delete(s2[conn])    # #25: 04->05 crosses columns, drop it

# ============================================================
# SLIDE 5 — spread the 4-step architecture down the whole page
# ============================================================
s5 = shp_map(5)
# step headers (bg, text) and body cards
for hb, ht in [(6, 7), (12, 13), (18, 19), (24, 25)]:
    set_pos(s5[hb], t=1.4)
    set_pos(s5[ht], t=1.47)
for body, title, text in [(8, 9, 10), (14, 15, 16), (20, 21, 22), (26, 27, 28)]:
    set_pos(s5[body], t=1.9, h=2.1)
    set_pos(s5[title], t=2.02)
    set_pos(s5[text], t=2.35, h=1.55)
for conn in (11, 17, 23):
    set_pos(s5[conn], t=2.95)
# input / output pills
set_pos(s5[29], t=4.2); set_pos(s5[30], t=4.24)
set_pos(s5[31], t=4.2); set_pos(s5[32], t=4.24)
# core-design bar
set_pos(s5[33], t=4.9); set_pos(s5[34], t=4.95)
# metric cards
for bg, lab, val in [(35, 36, 37), (38, 39, 40), (41, 42, 43), (44, 45, 46)]:
    set_pos(s5[bg], t=5.7)
    set_pos(s5[lab], t=5.73)
    set_pos(s5[val], t=5.97)

# ============================================================
# SLIDE 7 — three columns each stretched into the full band
# ============================================================
s7 = shp_map(7)
for hd in (6, 37, 56):                      # section headers align at 1.15
    set_pos(s7[hd], t=1.15)
# left 15-color grid: row pitch 0.52 -> 0.95, start 1.7
grid_rows = [
    (7, 8, 9, 10, 11, 12), (13, 14, 15, 16, 17, 18),
    (19, 20, 21, 22, 23, 24), (25, 26, 27, 28, 29, 30),
    (31, 32, 33, 34, 35, 36),
]
for r, ids in enumerate(grid_rows):
    t = 1.7 + 0.95 * r
    for sid in ids:
        set_pos(s7[sid], t=t)
# middle constraint lists: row pitch 0.34 -> 0.44
set_pos(s7[38], t=1.6)                                  # 硬约束 H1–H8
for r, (a, b) in enumerate([(39, 40), (41, 42), (43, 44), (45, 46)]):
    set_pos(s7[a], t=1.95 + 0.44 * r)
    set_pos(s7[b], t=1.95 + 0.44 * r)
set_pos(s7[47], t=3.85)                                 # 工艺启发式 C1–C6
for r, (a, b) in enumerate([(48, 49), (50, 51), (52, 53)]):
    set_pos(s7[a], t=4.2 + 0.44 * r)
    set_pos(s7[b], t=4.2 + 0.44 * r)
set_pos(s7[54], t=5.65)                                 # green note box
set_pos(s7[55], t=5.69)
# right validation cards: pitch 1.35 -> 1.8
for k, (bg, bar, lab, num, cap) in enumerate(
        [(57, 58, 59, 60, 61), (62, 63, 64, 65, 66), (67, 68, 69, 70, 71)]):
    t = 1.6 + 1.8 * k
    set_pos(s7[bg], t=t)
    set_pos(s7[bar], t=t)
    set_pos(s7[lab], t=t + 0.08)
    set_pos(s7[num], t=t + 0.34)
    set_pos(s7[cap], t=t + 0.82)

# ============================================================
# SLIDE 12 — equalize column bottoms + drop limitation bar lower
# ============================================================
s12 = shp_map(12)
# left 2x2 scenario cards: H1.12 -> 1.8, rows 1.5 / 3.8 (bottom = 5.6)
for k, (bg, ico, title, desc) in enumerate(
        [(7, 8, 9, 10), (11, 12, 13, 14), (15, 16, 17, 18), (19, 20, 21, 22)]):
    t = 1.5 if k < 2 else 3.8
    set_pos(s12[bg], t=t, h=1.8)
    set_pos(s12[ico], t=t + 0.54)
    set_pos(s12[title], t=t + 0.46)
    set_pos(s12[desc], t=t + 0.76)
# right roadmap cards: H1.12 -> 1.2, rows 1.5 / 2.95 / 4.4 (bottom = 5.6)
for k, (bg, tab, tlab, b1, b2) in enumerate(
        [(24, 25, 26, 27, 28), (29, 30, 31, 32, 33), (34, 35, 36, 37, 38)]):
    t = 1.5 + 1.45 * k
    set_pos(s12[bg], t=t, h=1.2)
    set_pos(s12[tab], t=t, h=1.2)
    set_pos(s12[tlab], t=t + 0.42)
    set_pos(s12[b1], t=t + 0.23)
    set_pos(s12[b2], t=t + 0.63)
# limitation bar: sits lower, a bit taller
set_pos(s12[39], t=5.95, h=0.8)
set_pos(s12[40], t=6.03)
set_pos(s12[41], t=6.29)

prs.save(PATH)
print("saved rebalance: S2, S5, S7, S12")
