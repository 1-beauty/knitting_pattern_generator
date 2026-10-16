# -*- coding: utf-8 -*-
"""Fig. 2 v5: reference-style action primitives (compact rounded loops, short
strokes, large type). Logical canvas 1680x1240 rendered at SS=3; the docx embed
displays it at full text width (6.27in) so 30 logical px == ~8 pt in print.
"""
import os, math
from PIL import Image, ImageDraw, ImageFont

ROOT = r"e:\DeskTop\knitting_pattern_generator"
OUT = os.path.join(ROOT, "outputs", "fig_actions_proto")
os.makedirs(OUT, exist_ok=True)
F = r"C:\Windows\Fonts"
SS = 6  # supersample 2x; downscaled on save so thick strokes stay smooth
def s(v): return v * SS
def font(sz, bold=False, ital=False):
    fn = "timesbd.ttf" if bold else ("timesi.ttf" if ital else "times.ttf")
    return ImageFont.truetype(os.path.join(F, fn), s(sz))

PAGE = (233, 242, 250); CARD = (255, 255, 255); BORDER = (214, 228, 242)
NAVY = (23, 45, 66); MUT = (105, 122, 140); GRAY = (150, 158, 168)
TEAL = (52, 168, 166); MAG = (230, 0, 126); WHITE = (255, 255, 255)
DASH = (50, 50, 50)

FAM = [("knit", "Knit", "f_knit / b_knit", "New loop is drawn through the loop below."),
       ("tuck", "Tuck", "f_tuck / b_tuck", "Old loop retained; a new yarn is tucked."),
       ("miss", "Miss", "miss", "Needle not selected; no new loop formed."),
       ("xfer", "Transfer", "xfer_l1 / xfer_f_b", "A loop moves to an adjacent needle or bed."),
       ("split", "Split", "f_split / b_split", "A loop is divided for local support and transition."),
       ("carrier", "Drop-off", "carrier", "Loop support removed at this wale (bind-off).")]

SPEC = {"knit": {"mag": {(0, 2)}, "boxes": [(0, 2, 1, 2)]},
        "tuck": {"mag": {(0, 1), (0, 2)}, "boxes": [(0, 1, 0, 2), (2, 1, 2, 2)]},
        "miss": {"mag": {(1, 2)}, "boxes": [(0, 2, 0, 2), (2, 2, 2, 2)]},
        "xfer": {"mag": {(0, 1), (1, 3)}, "boxes": [(0, 0, 0, 1), (1, 2, 1, 3)], "diag": True},
        "split": {"mag": {(0, 2), (1, 2)}, "boxes": [(0, 1, 1, 2)]},
        "carrier": {"mag": {(2, 2)}, "boxes": [(2, 1, 2, 3)]}}

W, H = s(1680), s(908)
img = Image.new("RGB", (W, H), PAGE)
d = ImageDraw.Draw(img)

def cr(pts, seg=24):
    """cubic Bezier through 4 control pts: stays in hull, no CR overshoot zigzag."""
    p0, p1, p2, p3 = list(pts)[:4]; out = []
    for j in range(seg + 1):
        t = j / seg; mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
        out.append((x, y))
    return out

def curve(pts, color, w):
    d.line([(s(x), s(y)) for x, y in cr(pts)], fill=color, width=max(2, int(s(w))), joint="curve")

def xform(pts, cx, cy, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca) for x, y in pts]

TEAL_D = (26, 105, 105); MAG_D = (150, 0, 85)
GRAYD = (135, 135, 135); GOLD = (226, 176, 46)

def _poly(pts, color, w):
    d.line([(s(x), s(y)) for x, y in pts], fill=color, width=max(2, int(s(w))), joint="curve")

def _arcpts(cx, cy, rx, ry, top):
    out = []
    for j in range(25):
        th = math.pi * (1 - j / 24)
        out.append((cx + rx * math.cos(th), cy - ry * math.sin(th) if top else cy + ry * math.sin(th)))
    return out

def _bez(p0, p1, p2, p3, m=16):
    out = []
    for j in range(m + 1):
        q = j / m; w0 = (1 - q) ** 3; w1 = 3 * q * (1 - q) ** 2; w2 = 3 * q * q * (1 - q); w3 = q ** 3
        out.append((w0 * p0[0] + w1 * p1[0] + w2 * p2[0] + w3 * p3[0],
                    w0 * p0[1] + w1 * p1[1] + w2 * p2[1] + w3 * p3[1]))
    return out

def wave_pts(x0, ytop, n, p, u, cups=True, yB=None, tips="auto", closed=False, tipx=0.30, tipy=None):
    """one continuous yarn path traced after the reference figure: wide head arches
    with eyelets at the shoulders and a pinched neck; bottom cups (cups), open legs
    ending in tips (fabric upper course), a closed elongated loop, or end flicks."""
    yBv = yB if yB is not None else ytop + u
    yS = ytop + 0.18 * u; yC = yBv - 0.40 * u; hw = yC - yS
    a = 0.40 * p; ye = tipy if tipy is not None else yC + 0.42 * u

    def wdown(xi, sd, y1, tx=None):
        tx = tipx if tx is None else tx
        return _bez((xi + sd * a, yS), (xi + sd * a, yS + 0.25 * hw),
                    (xi + sd * tx * p, yS + 0.95 * hw), (xi + sd * tx * p, y1))

    if closed:
        pts = _arcpts(x0, yS, a, yS - ytop, True)
        pts += wdown(x0, +1, yC, 0.30)[1:]
        pts += _arcpts(x0, yC, 0.30 * p, yBv - yC, False)[::-1][1:]
        pts += wdown(x0, -1, yC, 0.30)[::-1][1:]
        return pts
    if tips in ("both", "left"):
        pts = wdown(x0, -1, ye)[::-1]
    else:
        pts = [(x0 - a - 0.26 * p, ytop + 0.90 * u), (x0 - a - 0.11 * p, ytop + 0.77 * u)]
        pts += _bez((x0 - a - 0.06 * p, ytop + 0.66 * u), (x0 - a, yS + 0.60 * hw),
                    (x0 - a, yS + 0.30 * hw), (x0 - a, yS))[1:]
    for i in range(n):
        xi = x0 + i * p
        pts += _arcpts(xi, yS, a, yS - ytop, True)[1:]
        if i < n - 1:
            if cups:
                pts += _bez((xi + a, yS), (xi + a, yS + 0.50 * hw),
                            (xi + 0.10 * p, yC - 0.50 * hw), (xi + 0.10 * p, yC))[1:]
                pts += _arcpts(xi + p / 2, yC, 0.40 * p, yBv - yC, False)[1:]
                pts += _bez((xi + 0.90 * p, yC), (xi + 0.90 * p, yC - 0.50 * hw),
                            (xi + p - a, yS + 0.50 * hw), (xi + p - a, yS))[1:]
            else:
                pts += wdown(xi, +1, ye)[1:]
                pts += wdown(xi + p, -1, ye)[::-1][1:]
        else:
            if tips in ("both", "right"):
                pts += wdown(xi, +1, ye)[1:]
            else:
                pts += _bez((xi + a, yS), (xi + a, yS + 0.30 * hw),
                            (xi + a + 0.06 * p, ytop + 0.66 * u), (xi + a + 0.11 * p, ytop + 0.77 * u))[1:]
                pts.append((xi + a + 0.26 * p, ytop + 0.90 * u))
    return pts

def wave(cxc, ytop, n, p, u, color, od, cups=True, dots="white", yB=None, tips="auto", closed=False, tipx=0.30, tipy=None):
    x0 = cxc - (n - 1) * p / 2
    pts = wave_pts(x0, ytop, n, p, u, cups=cups, yB=yB, tips=tips, closed=closed, tipx=tipx, tipy=tipy)
    t = u * 0.062
    _poly(pts, od, t * 1.5)
    _poly(pts, color, t)
    yS = ytop + 0.18 * u; r = 0.05 * u
    if dots == "white":
        for i in range(n):
            for ex in (x0 + i * p - 0.40 * p, x0 + i * p + 0.40 * p):
                d.ellipse([s(ex - r), s(yS - r), s(ex + r), s(yS + r)],
                          fill=WHITE, outline=od, width=max(1, int(s(t * 0.35))))
    elif dots == "gray":
        rg = 0.055 * u
        for i in range(n):
            for ex in (x0 + i * p - 0.40 * p, x0 + i * p + 0.40 * p):
                d.ellipse([s(ex - rg), s(yS - rg), s(ex + rg), s(yS + rg)], fill=GRAYD)
    return [(x0 + i * p - 0.40 * p, yS) for i in range(n)] + [(x0 + i * p + 0.40 * p, yS) for i in range(n)]

def arrow(x1, y1, x2, y2, color, w, hs):
    d.line([s(x1), s(y1), s(x2), s(y2)], fill=color, width=max(2, int(s(w))))
    a = math.atan2(y2 - y1, x2 - x1)
    for t in (a + math.radians(150), a - math.radians(150)):
        d.line([s(x2), s(y2), s(x2 + hs * math.cos(t)), s(y2 + hs * math.sin(t))], fill=color, width=max(2, int(s(w))))

def dash_rect(box, color, w, dash=4, gap=4):
    x0, y0, x1, y1 = box
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    for (ax, ay), (bx, by) in edges:
        ln = math.hypot(bx - ax, by - ay); n = max(1, int(ln / (dash + gap)))
        for i in range(n + 1):
            t0 = i * (dash + gap) / ln; t1 = min(ln, t0 + dash) / ln
            if t0 >= 1: break
            d.line([s(ax + (bx - ax) * t0), s(ay + (by - ay) * t0), s(ax + (bx - ax) * t1), s(ay + (by - ay) * t1)],
                   fill=color, width=max(2, int(s(w))))

def lattice(gx, gy, gs, spec, u):
    rows, cols = 3, 5
    xs = [gx + gs * (c + .5) / cols for c in range(cols)]
    ys = [gy + gs * (r + .5) / rows for r in range(rows)]
    lw = u * 0.030; nr = u * 0.060
    for yy in ys:
        d.line([s(xs[0]), s(yy), s(xs[-1]), s(yy)], fill=TEAL, width=max(2, int(s(lw))))
    for xx in xs:
        d.line([s(xx), s(ys[0] - gs * 0.11), s(xx), s(ys[-1] + gs * 0.07)], fill=MAG, width=max(2, int(s(lw))))
        arrow(xx, ys[-1] + gs * 0.02, xx, ys[-1] + gs * 0.10, MAG, lw, u * 0.06)
        arrow(xx, ys[0] - gs * 0.02, xx, ys[0] - gs * 0.10, MAG, lw, u * 0.06)
    for r in range(rows):
        for c in range(cols):
            cx, cy = xs[c], ys[r]
            if (r, c) in spec.get("mag", set()):
                d.ellipse([s(cx - nr), s(cy - nr), s(cx + nr), s(cy + nr)], fill=MAG)
            elif r == 0:
                d.ellipse([s(cx - nr), s(cy - nr), s(cx + nr), s(cy + nr)], fill=WHITE, outline=GRAY, width=max(2, int(s(lw))))
            else:
                d.ellipse([s(cx - nr), s(cy - nr), s(cx + nr), s(cy + nr)], fill=TEAL)
    cw_, chh = gs / cols, gs / rows
    for (r0, c0, r1, c1) in spec.get("boxes", []):
        dash_rect([gx + c0 * cw_ + cw_ * .10, gy + r0 * chh + chh * .10,
                   gx + (c1 + 1) * cw_ - cw_ * .10, gy + (r1 + 1) * chh - chh * .10], DASH, u * 0.026)
    if spec.get("diag"):
        arrow(xs[1], ys[0], xs[3], ys[1], MAG, lw * 1.2, u * 0.07)

def panel_b(cxc, by, bh, kind, u):
    """(b) close-up: two-course interlocked fabric after the reference figure, with the
    active stitch of each family highlighted in magenta on top of it."""
    p = 0.59 * u; mw = u * 0.070; w = u * .60
    yL = by + 0.62 * u                      # lower course head tops

    def carc(x0, y0, x1, y1, color, ww):
        d.line([s(x0), s(y0), s(x1), s(y1)], fill=WHITE, width=max(2, int(s(ww * 2.2))))
        d.line([s(x0), s(y0), s(x1), s(y1)], fill=color, width=max(2, int(s(ww))))

    def lower(n=3, cx=cxc):
        wave(cx, yL, n, p, u, TEAL, TEAL_D, dots="gray")

    def upper(n=3, cx=cxc, color=TEAL, od=TEAL_D):
        return wave(cx, by, n, p, u, color, od)   # full course; its cups interlock with the lower heads

    if kind == "knit":
        lower()
        upper(3)
        wave(cxc, by, 1, p, u, MAG, MAG_D, tips="both", tipx=0.10, tipy=by + 0.60 * u)
    elif kind == "tuck":
        lower()
        wave(cxc, by + 0.12 * u, 1, p, u, MAG, MAG_D, dots="none",
             tips="both", tipx=0.15, tipy=by + 0.90 * u)   # tucked yarn held behind
        sh = upper(3)
        t = u * 0.062; r = 0.05 * u
        for ex, ey in (sh[1], sh[4]):                  # both loops held on the needle
            d.rectangle([s(ex - r * 1.8), s(ey - r * 1.8), s(ex + r * 1.8), s(ey + r * 1.8)],
                        outline=GOLD, width=max(1, int(s(t * 0.45))))
    elif kind == "miss":
        lower(1, cxc - p); lower(1, cxc + p)
        d.line([s(cxc - p * 0.72), s(by + 1.04 * u), s(cxc + p * 0.72), s(by + 1.04 * u)],
               fill=MAG, width=max(2, int(s(mw))))     # floating yarn behind
        upper(1, cxc - p); upper(1, cxc + p)
        wave(cxc, by, 1, p, u, TEAL, TEAL_D, yB=by + 1.62 * u, closed=True)  # held, stretched
    elif kind == "xfer":
        lower()
        upper(1, cxc - p)                              # source loop before the move
        upper(1, cxc + p)
        pts = wave_pts(cxc - 0.55 * p, by - 0.06 * u, 1, p, u, closed=True,
                       yB=by - 0.06 * u + 1.00 * u)
        piv = (cxc - 0.55 * p - 0.40 * p, by - 0.06 * u + 0.18 * u)
        pts = xform(pts, piv[0], piv[1], math.radians(-35))
        t = u * 0.062
        _poly(pts, MAG_D, t * 1.5); _poly(pts, MAG, t)
        for sd in (-0.40, 0.40):                        # eyelets of the moving loop
            ex, ey = xform([(cxc - 0.55 * p + sd * p, by - 0.06 * u + 0.18 * u)], piv[0], piv[1], math.radians(-35))[0]
            d.ellipse([s(ex - t * 0.8), s(ey - t * 0.8), s(ex + t * 0.8), s(ey + t * 0.8)],
                      fill=WHITE, outline=MAG_D, width=max(1, int(s(t * 0.35))))
    elif kind == "split":
        lower(); upper(3)
        carc(cxc, by + 0.10 * u, cxc + w * .45, by + 1.10 * u, MAG, mw)
        carc(cxc, by + 0.10 * u, cxc - w * .45, by + 1.10 * u, MAG, mw)
    elif kind == "carrier":
        lower(1, cxc - p); lower(1, cxc + p)
        upper(1, cxc - p); upper(1, cxc + p)
        carc(cxc - w * .30, by + 0.06 * u, cxc - w * .06, by + 0.98 * u, MAG, mw)
        carc(cxc + w * .30, by + 0.06 * u, cxc + w * .06, by + 0.98 * u, MAG, mw)
        arrow(cxc, by + 1.08 * u, cxc, by + 1.48 * u, MAG, mw * .8, u * 0.09)

m = 24; gap = 20; top0 = 24
cw = (1680 - 2 * m - 2 * gap) / 3; ch = 420
for idx, (key, title, abbr, cap) in enumerate(FAM):
    r, c = divmod(idx, 3); x = m + c * (cw + gap); y = top0 + r * (ch + gap)
    d.rounded_rectangle([s(x), s(y), s(x + cw), s(y + ch)], radius=s(14), fill=CARD, outline=BORDER, width=s(2))
    d.text((s(x + 22), s(y + 12)), title, font=font(46, True), fill=NAVY)
    tw_ = d.textlength(title, font=font(46, True)) / SS
    d.text((s(x + 22 + tw_ + 14), s(y + 36)), abbr, font=font(30, ital=True), fill=MUT)
    by = y + 96; bh = 180
    pad = 10; aw = cw * .28; bw = cw * .42; cwid = cw * .26
    axc = x + pad + aw / 2; bxc = x + pad + aw + bw / 2; cxc = x + pad + aw + bw + cwid / 2
    wave(axc, by + 61, 4, 34, 58, TEAL, TEAL_D)
    d.text((s(axc - 14), s(by + bh + 8)), "(a)", font=font(32), fill=NAVY)
    panel_b(bxc, by, bh, key, 96)
    d.text((s(bxc - 14), s(by + bh + 8)), "(b)", font=font(32), fill=NAVY)
    lb = min(cwid * .96, bh * .74)
    lattice(cxc - lb / 2, by + bh / 2 - lb / 2, lb, SPEC[key], 110)
    d.text((s(cxc - 14), s(by + bh + 8)), "(c)", font=font(32), fill=NAVY)
    # caption: centered, wrap to at most 2 lines at 32 logical px (~8.6 pt in print)
    fc = font(32); maxw = cw - 36
    words = cap.split(); lines = []; line = ""
    for wd in words:
        t = (line + " " + wd).strip()
        if d.textlength(t, font=fc) / SS <= maxw: line = t
        else: lines.append(line); line = wd
    lines.append(line)
    ty = y + ch - 14 - len(lines) * 40
    for ln in lines:
        wl = d.textlength(ln, font=fc) / SS
        d.text((s(x + cw / 2 - wl / 2), s(ty)), ln, font=fc, fill=NAVY)
        ty += 40

img = img.resize((W // 2, H // 2), Image.LANCZOS)
p = os.path.join(OUT, "actions_embed.png")
img.save(p)
print("written", p, img.size)
