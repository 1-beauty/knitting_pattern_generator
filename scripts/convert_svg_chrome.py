"""Convert SVG files to PNG using Chrome headless."""
import os
import subprocess
import shutil

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
FIG_DIR = os.path.join(PROJECT_ROOT, "docs", "figures")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "runs")

def svg_to_png_chrome(svg_path, png_path, width=1200):
    """Convert SVG to PNG using Chrome headless."""
    svg_url = "file:///" + svg_path.replace("\\", "/")
    cmd = [
        CHROME,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        f"--screenshot={png_path}",
        f"--window-size={width},900",
        "--hide-scrollbars",
        svg_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if os.path.exists(png_path):
            size = os.path.getsize(png_path)
            print(f"  OK: {os.path.basename(svg_path)} -> {os.path.basename(png_path)} ({size} bytes)")
            return True
        else:
            print(f"  FAIL: {os.path.basename(svg_path)} - output not created")
            return False
    except Exception as e:
        print(f"  ERROR: {os.path.basename(svg_path)} - {e}")
        return False

def bmp_to_png(bmp_path, png_path):
    """Convert BMP to PNG using Pillow."""
    from PIL import Image
    img = Image.open(bmp_path)
    img.save(png_path, "PNG")
    print(f"  OK: {os.path.basename(bmp_path)} -> {os.path.basename(png_path)}")

def main():
    print("=== SVG to PNG (Chrome headless) ===\n")
    
    svgs = [
        ("system_overview.svg", 1400),
        ("stage2_simulation.svg", 1200),
        ("fig_ablation_compare.svg", 1000),
        ("fig_ablation_metrics.svg", 800),
        ("fig_ablation_radar.svg", 800),
        ("fig_random_generation.svg", 1200),
        ("fig_edit_cases.svg", 1200),
    ]
    
    for svg_name, width in svgs:
        svg_path = os.path.join(FIG_DIR, svg_name)
        png_name = svg_name.replace(".svg", ".png")
        png_path = os.path.join(FIG_DIR, png_name)
        if os.path.exists(svg_path):
            svg_to_png_chrome(svg_path, png_path, width)
        else:
            print(f"  SKIP: {svg_name} not found")

    # BMP conversions (already done, verify)
    print("\n=== BMP to PNG ===\n")
    bmp_cases = [
        ("exp_case_01", "case_01_output.bmp"),
        ("exp_case_01_all", "case_01_output.bmp"),
    ]
    for run_name, bmp_name in bmp_cases:
        bmp_path = os.path.join(OUTPUTS_DIR, run_name, "color_map", bmp_name)
        png_path = bmp_path.replace(".bmp", ".png")
        if os.path.exists(bmp_path):
            if not os.path.exists(png_path):
                bmp_to_png(bmp_path, png_path)
            else:
                print(f"  OK: {os.path.basename(png_path)} already exists")
        else:
            print(f"  SKIP: {bmp_path} not found")

    print("\n=== Done ===")

if __name__ == "__main__":
    main()
