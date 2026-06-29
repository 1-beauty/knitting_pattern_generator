"""Convert SVG and BMP images to PNG for the paper."""
import os
import sys
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DOC_DIR = os.path.join(PROJECT_ROOT, "docs")
FIG_DIR = os.path.join(DOC_DIR, "figures")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "runs")

def convert_bmp_to_png(bmp_path, png_path):
    """Convert BMP to PNG using Pillow."""
    try:
        from PIL import Image
        img = Image.open(bmp_path)
        img.save(png_path, "PNG")
        print(f"  BMP->PNG: {bmp_path} -> {png_path}")
        return True
    except ImportError:
        print("  [ERROR] Pillow not installed. Run: pip install Pillow")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def convert_svg_to_png(svg_path, png_path, scale=2.0):
    """Convert SVG to PNG."""
    # Try cairosvg first
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path, scale=scale)
        print(f"  SVG->PNG (cairosvg): {svg_path} -> {png_path}")
        return True
    except ImportError:
        pass
    except Exception as e:
        print(f"  cairosvg error: {e}")

    # Try svglib + reportlab
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(svg_path)
        if drawing:
            renderPM.drawToFile(drawing, png_path, fmt="PNG", dpi=150)
            print(f"  SVG->PNG (svglib): {svg_path} -> {png_path}")
            return True
    except ImportError:
        pass
    except Exception as e:
        print(f"  svglib error: {e}")

    # Try Inkscape CLI
    try:
        import subprocess
        result = subprocess.run(
            ["inkscape", svg_path, "--export-type=png", f"--export-filename={png_path}", "--export-dpi=150"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and os.path.exists(png_path):
            print(f"  SVG->PNG (inkscape): {svg_path} -> {png_path}")
            return True
    except (FileNotFoundError, Exception) as e:
        print(f"  inkscape not found: {e}")

    print(f"  [SKIP] Cannot convert {svg_path} - install cairosvg: pip install cairosvg")
    return False


def main():
    print("=== Converting images for paper ===\n")

    # 1. Convert SVGs to PNGs
    svgs_to_convert = [
        "system_overview.svg",
        "stage2_simulation.svg",
        "fig_ablation_metrics.svg",
        "fig_ablation_radar.svg",
        "fig_random_generation.svg",
        "fig_edit_cases.svg",
        "fig_ablation_compare.svg",
    ]

    print("[1] Converting SVG -> PNG:")
    for svg_name in svgs_to_convert:
        svg_path = os.path.join(FIG_DIR, svg_name)
        png_name = svg_name.replace(".svg", ".png")
        png_path = os.path.join(FIG_DIR, png_name)
        if os.path.exists(svg_path):
            convert_svg_to_png(svg_path, png_path)
        else:
            print(f"  [SKIP] {svg_path} not found")

    # fig_end_to_end_case11_12.png already exists
    print(f"  [OK] fig_end_to_end_case11_12.png already exists")

    # 2. Convert BMP outputs to PNG
    print("\n[2] Converting BMP -> PNG:")
    bmp_cases = [
        ("exp_case_01", "case_01_output.bmp"),
        ("exp_case_01_all", "case_01_output.bmp"),
    ]
    for run_name, bmp_name in bmp_cases:
        bmp_path = os.path.join(OUTPUTS_DIR, run_name, "color_map", bmp_name)
        png_name = bmp_name.replace(".bmp", ".png")
        png_path = os.path.join(OUTPUTS_DIR, run_name, "color_map", png_name)
        if os.path.exists(bmp_path):
            if not os.path.exists(png_path):
                convert_bmp_to_png(bmp_path, png_path)
            else:
                print(f"  [OK] {png_path} already exists")
        else:
            print(f"  [SKIP] {bmp_path} not found")

    print("\n=== Done ===")
    print("\nIf SVG conversion failed, install cairosvg:")
    print("  pip install cairosvg")


if __name__ == "__main__":
    main()
