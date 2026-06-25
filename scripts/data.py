from pathlib import Path
from PIL import Image
import sys
import json

# =========================
# 配置区
# =========================
ROOT_DIR = r"generator_two\data\instruction"

# 输出结果保存路径（设为 None 则只在控制台输出，不保存文件）
OUTPUT_JSON = r"outputs\color_stats.json"

# 17色 -> 针织技法映射表（基于论文推导）
COLOR_MAP = {
    (255,   0,  16): {"hex": "#FF0010", "name": "Front Knit",           "abbr": "f_knit",    "desc": "前床正针（最基础针法）"},
    ( 43, 206,  72): {"hex": "#2BCE48", "name": "Back Knit",            "abbr": "b_knit",    "desc": "后床针/反针"},
    ( 94, 241, 242): {"hex": "#5EF1F2", "name": "Transfer F→B",        "abbr": "xfer_f2b",  "desc": "移针：前床→后床"},
    (255,   0, 190): {"hex": "#FF00BE", "name": "Transfer B→F",        "abbr": "xfer_b2f",  "desc": "移针：后床→前床"},
    (  0, 129,  69): {"hex": "#008145", "name": "Back Tuck",            "abbr": "b_tuck",    "desc": "后床集圈"},
    (179, 179, 179): {"hex": "#B3B3B3", "name": "Miss",                "abbr": "miss",      "desc": "浮针/跳针"},
    (126,   0, 149): {"hex": "#7E0095", "name": "Transfer Offset L1",  "abbr": "xfer_l1",   "desc": "移针并左移1位"},
    (  0, 164, 255): {"hex": "#00A4FF", "name": "Front Tuck",          "abbr": "f_tuck",    "desc": "前床集圈"},
    (255, 230,   6): {"hex": "#FFE606", "name": "Split Front",         "abbr": "f_split",   "desc": "前床劈针"},
    (255, 164,   4): {"hex": "#FFA404", "name": "Split Back",          "abbr": "b_split",   "desc": "后床劈针"},
    (  0, 117, 220): {"hex": "#0075DC", "name": "Front Tuck Var",      "abbr": "f_tuck_v",  "desc": "前床集圈变体"},
    (117,  59,  59): {"hex": "#753B3B", "name": "Yarn Change",         "abbr": "carrier",   "desc": "纱线换色/载体动作"},
    (255, 255, 128): {"hex": "#FFFF80", "name": "Split Variant",       "abbr": "split_v",   "desc": "劈针变体"},
    (  0,  92,  49): {"hex": "#005C31", "name": "Back Tuck Var",       "abbr": "b_tuck_v",  "desc": "后床集圈变体"},
    (194,   0, 136): {"hex": "#C20088", "name": "Transfer Offset R1",  "abbr": "xfer_r1",   "desc": "移针并右移1位"},
    ( 96,   0, 112): {"hex": "#600070", "name": "Transfer Offset L2",  "abbr": "xfer_l2",   "desc": "移针并左移2位"},
    (128, 128, 128): {"hex": "#808080", "name": "Drop",                "abbr": "drop",      "desc": "脱圈/删针"},
}


# =========================
# 工具函数
# =========================
def rgb_to_key(r, g, b):
    return (r, g, b)


def get_color_info(rgb_tuple):
    """查找颜色对应的针法信息"""
    info = COLOR_MAP.get(rgb_tuple)
    if info:
        return info
    return {
        "hex": "#{:02X}{:02X}{:02X}".format(*rgb_tuple),
        "name": "Unknown",
        "abbr": "unknown",
        "desc": "未知色值（不在17色映射表中）"
    }


def scan_image_colors(image_path: Path):
    """
    扫描单张图片，返回每种颜色的像素数
    返回: { (r,g,b): pixel_count, ... }
    """
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"  [警告] 无法打开: {image_path.name} -> {e}")
        return None

    color_count = {}
    pixels = list(img.getdata())
    for pixel in pixels:
        rgb = rgb_to_key(*pixel)
        color_count[rgb] = color_count.get(rgb, 0) + 1

    return color_count


def scan_category(category_dir: Path):
    """
    扫描一个类别文件夹中所有图片的颜色统计
    返回:
        total_colors: { (r,g,b): total_pixel_count }
        image_count: 成功扫描的图片数
        total_pixels: 总像素数
    """
    total_colors = {}
    image_count = 0
    total_pixels = 0
    failed = 0

    files = sorted([f for f in category_dir.iterdir() if f.is_file()])

    for i, f in enumerate(files):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff"):
            continue

        colors = scan_image_colors(f)
        if colors is None:
            failed += 1
            continue

        image_count += 1
        for rgb, count in colors.items():
            total_colors[rgb] = total_colors.get(rgb, 0) + count
            total_pixels += count

        # 进度提示（每500张输出一次）
        if (i + 1) % 500 == 0:
            print(f"    已扫描 {i + 1}/{len(files)} ...")

    return total_colors, image_count, total_pixels, failed


def format_percentage(count, total):
    if total == 0:
        return "0.00%"
    return f"{count / total * 100:.4f}%"


# =========================
# 主流程
# =========================
def main():
    root = Path(ROOT_DIR)

    if not root.exists() or not root.is_dir():
        print(f"目录不存在: {root}")
        sys.exit(1)

    # 找到所有子文件夹
    subdirs = sorted([d for d in root.iterdir() if d.is_dir()])

    if not subdirs:
        print(f"未找到子文件夹: {root}")
        sys.exit(1)

    print("=" * 70)
    print("针织色码统计工具")
    print("=" * 70)
    print(f"  根目录:       {root}")
    print(f"  子文件夹数:   {len(subdirs)}")
    print(f"  映射表色数:   {len(COLOR_MAP)}")

    all_results = {}       # 所有类别的结果
    global_colors = {}     # 全局颜色统计
    global_pixels = 0
    global_images = 0

    for sub in subdirs:
        category_name = sub.name
        print(f"\n{'=' * 70}")
        print(f"扫描类别: {category_name}")
        print("=" * 70)

        colors, img_count, px_count, fail_count = scan_category(sub)

        global_images += img_count
        global_pixels += px_count

        for rgb, count in colors.items():
            global_colors[rgb] = global_colors.get(rgb, 0) + count

        # 按频率降序排列
        sorted_colors = sorted(colors.items(), key=lambda x: x[1], reverse=True)

        print(f"  图片数:     {img_count}")
        if fail_count:
            print(f"  失败数:     {fail_count}")
        print(f"  总像素数:   {px_count:,}")
        print(f"  色值种类:   {len(sorted_colors)}")
        print()
        print(f"  {'色值HEX':<12} {'针法名称':<25} {'缩写':<12} {'像素数':>12} {'占比':>10}")
        print(f"  {'-' * 75}")

        category_result = []
        for rgb, count in sorted_colors:
            info = get_color_info(rgb)
            pct = format_percentage(count, px_count)
            print(f"  {info['hex']:<12} {info['name']:<25} {info['abbr']:<12} {count:>12,} {pct:>10}")

            category_result.append({
                "hex": info["hex"],
                "rgb": list(rgb),
                "name": info["name"],
                "abbr": info["abbr"],
                "desc": info["desc"],
                "pixel_count": count,
                "percentage": round(count / px_count * 100, 4) if px_count > 0 else 0
            })

        all_results[category_name] = {
            "image_count": img_count,
            "total_pixels": px_count,
            "unique_colors": len(sorted_colors),
            "colors": category_result
        }

    # ---- 全局汇总 ----
    print(f"\n{'=' * 70}")
    print("全局汇总（所有类别合计）")
    print("=" * 70)
    print(f"  总图片数:   {global_images}")
    print(f"  总像素数:   {global_pixels:,}")
    print(f"  总色值种类: {len(global_colors)}")
    print()

    sorted_global = sorted(global_colors.items(), key=lambda x: x[1], reverse=True)
    print(f"  {'色值HEX':<12} {'针法名称':<25} {'缩写':<12} {'像素数':>12} {'占比':>10}")
    print(f"  {'-' * 75}")

    global_result = []
    for rgb, count in sorted_global:
        info = get_color_info(rgb)
        pct = format_percentage(count, global_pixels)
        print(f"  {info['hex']:<12} {info['name']:<25} {info['abbr']:<12} {count:>12,} {pct:>10}")

        global_result.append({
            "hex": info["hex"],
            "rgb": list(rgb),
            "name": info["name"],
            "abbr": info["abbr"],
            "desc": info["desc"],
            "pixel_count": count,
            "percentage": round(count / global_pixels * 100, 4) if global_pixels > 0 else 0
        })

    # ---- 类别 x 色值 交叉表 ----
    print(f"\n{'=' * 70}")
    print("类别 × 色值 交叉表（各类别是否包含该色值）")
    print("=" * 70)

    all_color_keys = [rgb for rgb, _ in sorted_global]
    all_cat_names = sorted(all_results.keys())

    # 表头
    header = f"  {'色值':<12} {'针法':<20}"
    for cat in all_cat_names:
        header += f" {cat:>8}"
    print(header)
    print(f"  {'-' * (34 + 9 * len(all_cat_names))}")

    for rgb in all_color_keys:
        info = get_color_info(rgb)
        row = f"  {info['hex']:<12} {info['abbr']:<20}"
        for cat in all_cat_names:
            cat_colors = {tuple(c["rgb"]): c for c in all_results[cat]["colors"]}
            if rgb in cat_colors:
                pct = cat_colors[rgb]["percentage"]
                row += f" {pct:>7.2f}%"
            else:
                row += f" {'—':>8}"
        print(row)

    # ---- 保存 JSON ----
    if OUTPUT_JSON:
        output_data = {
            "root_dir": str(root),
            "color_map_version": "neural_inverse_knitting_17colors",
            "global_summary": {
                "total_images": global_images,
                "total_pixels": global_pixels,
                "unique_colors": len(global_colors),
                "colors": global_result
            },
            "categories": all_results
        }

        output_path = Path(OUTPUT_JSON)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_path}")

    print(f"\n统计完成。")


if __name__ == "__main__":
    main()