"""
Compositing experiment output images into paper figures.
Outputs go to docs/figures/ for direct use in the paper.
"""
from PIL import Image, ImageDraw, ImageFont
import os

ROOT = r"e:\DeskTop\knitting_pattern_generator"
OUT_DIR = os.path.join(ROOT, "docs", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

# Windows 系统字体目录
_FONT_DIR = r"C:\Windows\Fonts"


def _load_font(size):
    """加载支持中文的字体，依次尝试微软雅黑、黑体、楷体，最后回退默认。"""
    candidates = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simkai.ttf", "simsun.ttc"]
    for name in candidates:
        path = os.path.join(_FONT_DIR, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # 回退：尝试直接按名称加载
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


font = _load_font(18)
font_small = _load_font(15)


def load_img(path):
    """Load image, return RGB or convert as needed."""
    img = Image.open(path)
    if img.mode == "P":
        img = img.convert("RGB")
    return img


def add_label(draw, x, y, w, h, text, font_obj, bg_color=(255, 255, 255), text_color=(0, 0, 0)):
    """Draw a label bar above an image."""
    label_h = 22
    draw.rectangle([x, y, x + w, y + label_h], fill=bg_color)
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y + 2), text, fill=text_color, font=font_obj)
    return label_h


def compose_ablation():
    """Compose ablation comparison: 4 cases × 4 variants."""
    cases = ["abl_01", "abl_03", "abl_06", "abl_07"]
    case_labels = ["ABL-01 基础对照", "ABL-03 多嵌套冲突", "ABL-06 边框内外差异", "ABL-07 圆形紧贴边框"]
    variants = ["full", "no_repair", "no_refine", "no_aesthetic"]
    variant_labels = ["Full", "No Repair", "No Refine", "No Aesthetic"]

    rows, cols = 4, 4
    cell_w, cell_h = 200, 200
    label_h = 22
    margin = 5

    total_w = cols * (cell_w + margin) + margin
    total_h = rows * (cell_h + label_h + margin) + margin + 30  # extra for row labels
    canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Column headers
    for j, vlabel in enumerate(variant_labels):
        x = margin + j * (cell_w + margin)
        add_label(draw, x, 0, cell_w, label_h, vlabel, font, bg_color=(230, 230, 240))

    for i, (case, clabel) in enumerate(zip(cases, case_labels)):
        y_base = 30 + i * (cell_h + label_h + margin)
        # Row label
        add_label(draw, margin, y_base, cols * (cell_w + margin) - margin, label_h, clabel, font_small, bg_color=(240, 245, 255))
        for j, var in enumerate(variants):
            x = margin + j * (cell_w + margin)
            y = y_base + label_h + margin
            img_path = os.path.join(ROOT, "outputs", "runs", "ablation", f"{case}_{var}", "color_map", f"{case}_output.bmp")
            if os.path.exists(img_path):
                img = load_img(img_path).resize((cell_w, cell_h), Image.NEAREST)
                canvas.paste(img, (x, y))
            else:
                draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(220, 220, 220))
                draw.text((x + 10, y + 10), "N/A", fill=(128, 128, 128), font=font)

    out_path = os.path.join(OUT_DIR, "fig_ablation_comparison.png")
    canvas.save(out_path, dpi=(300, 300))
    print(f"Saved: {out_path}")


def compose_random():
    """Compose random generation: 6 cases in 2×3 grid."""
    cases = [f"rnd_{i:02d}" for i in range(1, 7)]
    labels = [
        "RND-01 主体+纹理+背景",
        "RND-02 边框+吊目+组织",
        "RND-03 几何+稀疏纹理",
        "RND-04 嵌套+复杂纹理",
        "RND-05 蜂巢+镂空",
        "RND-06 边框+中心主体",
    ]

    rows, cols = 2, 3
    cell_w, cell_h = 200, 200
    label_h = 22
    margin = 5

    total_w = cols * (cell_w + margin) + margin
    total_h = rows * (cell_h + label_h + margin) + margin
    canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        x = margin + c * (cell_w + margin)
        y = margin + r * (cell_h + label_h + margin)

        # Label
        add_label(draw, x, y, cell_w, label_h, labels[idx], font_small, bg_color=(240, 245, 255))

        img_path = os.path.join(ROOT, "outputs", "runs", "random", cases[idx], "color_map", f"{cases[idx]}_output.bmp")
        if os.path.exists(img_path):
            img = load_img(img_path).resize((cell_w, cell_h), Image.NEAREST)
            canvas.paste(img, (x, y + label_h))

    out_path = os.path.join(OUT_DIR, "fig_random_generation_composite.png")
    canvas.save(out_path, dpi=(300, 300))
    print(f"Saved: {out_path}")


def compose_edit():
    """Compose edit experiment: 6 cases (baseline + 5 variants) in 2×3 grid."""
    cases = [f"edt_{i:02d}" for i in range(6)]
    labels = [
        "EDT-00 基准（波浪吊目）",
        "EDT-01 纹理→蜂巢",
        "EDT-02 纹理→镂空网眼",
        "EDT-03 边框加粗（2→3）",
        "EDT-04 背景→稀疏网眼",
        "EDT-05 形状→菱形",
    ]

    rows, cols = 2, 3
    cell_w, cell_h = 320, 320          # 提高分辨率
    label_h = 34                        # 加高标签栏以容纳中文
    margin = 10
    border = 2

    total_w = cols * (cell_w + margin) + margin
    total_h = rows * (cell_h + label_h + margin) + margin
    canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        x = margin + c * (cell_w + margin)
        y = margin + r * (cell_h + label_h + margin)

        # 标签栏：基准用强调色，编辑变体用浅色
        if idx == 0:
            add_label(draw, x, y, cell_w, label_h, labels[idx], font, bg_color=(210, 225, 250))
        else:
            add_label(draw, x, y, cell_w, label_h, labels[idx], font, bg_color=(240, 245, 255))

        img_path = os.path.join(ROOT, "outputs", "runs", "edit", cases[idx], "color_map", f"{cases[idx]}_output.bmp")
        if os.path.exists(img_path):
            img = load_img(img_path).resize((cell_w, cell_h), Image.NEAREST)
            canvas.paste(img, (x, y + label_h))
        else:
            draw.rectangle([x, y + label_h, x + cell_w, y + label_h + cell_h], fill=(225, 225, 225))
            draw.text((x + 12, y + label_h + 12), "N/A", fill=(128, 128, 128), font=font)

        # 细边框提升可读性
        draw.rectangle(
            [x - border, y - border, x + cell_w + border, y + label_h + cell_h + border],
            outline=(180, 185, 195), width=border,
        )

    out_path = os.path.join(OUT_DIR, "fig_edit_cases_composite.png")
    canvas.save(out_path, dpi=(300, 300))
    print(f"Saved: {out_path}")


def compose_baseline():
    """Compose baseline comparison: 5 tests × 3 methods in 5×3 grid."""
    tests = [f"test_{i:02d}" for i in range(1, 6)]
    test_labels = [
        "test_01 圆+波浪+网眼",
        "test_02 圆+蜂巢",
        "test_03 框+圆+波浪",
        "test_04 菱形+蜂巢",
        "test_05 六边+波浪+网眼",
    ]
    methods = ["ours", "no_plan", "llm_direct"]
    method_labels = ["Ours (Full)", "w/o PatternPlan", "LLM-Direct"]

    rows, cols = 5, 3
    cell_w, cell_h = 200, 200
    label_h = 22
    margin = 5

    total_w = cols * (cell_w + margin) + margin
    total_h = rows * (cell_h + label_h + margin) + margin + 30
    canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Column headers
    for j, mlabel in enumerate(method_labels):
        x = margin + j * (cell_w + margin)
        add_label(draw, x, 0, cell_w, label_h, mlabel, font, bg_color=(230, 230, 240))

    for i, (test, tlabel) in enumerate(zip(tests, test_labels)):
        y_base = 30 + i * (cell_h + label_h + margin)
        add_label(draw, margin, y_base, cols * (cell_w + margin) - margin, label_h, tlabel, font_small, bg_color=(240, 245, 255))
        for j, method in enumerate(methods):
            x = margin + j * (cell_w + margin)
            y = y_base + label_h + margin
            img_path = os.path.join(ROOT, "outputs", "runs", "baseline", "baseline_comparison", test, method, "output.png")
            if not os.path.exists(img_path):
                img_path = os.path.join(ROOT, "outputs", "runs", "baseline", "baseline_comparison", test, method, "output.bmp")
            if os.path.exists(img_path):
                img = load_img(img_path).resize((cell_w, cell_h), Image.NEAREST)
                canvas.paste(img, (x, y))
            else:
                draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(220, 220, 220))
                draw.text((x + 10, y + 10), "N/A", fill=(128, 128, 128), font=font)

    out_path = os.path.join(OUT_DIR, "fig_baseline_comparison.png")
    canvas.save(out_path, dpi=(300, 300))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    print("Composing experiment figures...")
    compose_ablation()
    compose_random()
    compose_edit()
    compose_baseline()
    print("Done.")
