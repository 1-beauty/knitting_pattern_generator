from PIL import Image, ImageDraw, ImageFont
import os

base = r'outputs\runs\simulation'
out_dir = r'docs\figures'

def get_font(size):
    try:
        return ImageFont.truetype('arial.ttf', size)
    except:
        return ImageFont.load_default()

# === Part 1: sem_01, sem_03, sem_06 — Stage 1-4 composite ===
cases_stages = {
    'sem01': ['stage1_result.png', 'stage2_result.png', 'stage3_result.png', 'stage4_result.png'],
    'sem03': ['stage1_result.png', 'stage2_result.png', 'stage3_result.png', 'stage4_result.png'],
    'sem06': ['stage1_result.png', 'stage2_result.png', 'stage3_result.png', 'stage4_result.png'],
}

stage_labels = ['Stage 1', 'Stage 2', 'Stage 3', 'Stage 4']
target_size = 320  # resize all to 320x320 for compact layout

for case, stages in cases_stages.items():
    imgs = []
    for s in stages:
        # Find the actual folder
        folder = f'sim_{case}_{s.replace("_result.png", "")}'
        path = os.path.join(base, folder, 'simulation', s)
        im = Image.open(path)
        # Resize to target
        im = im.resize((target_size, target_size), Image.LANCZOS)
        imgs.append(im)

    label_h = 30
    gap = 8
    total_w = 4 * target_size + 3 * gap
    total_h = target_size + label_h + 10

    composite = Image.new('RGB', (total_w, total_h), 'white')
    draw = ImageDraw.Draw(composite)
    font = get_font(16)

    for i, (im, label) in enumerate(zip(imgs, stage_labels)):
        x = i * (target_size + gap)
        composite.paste(im, (x, label_h + 10))
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((x + (target_size - tw) // 2, 6), label, fill='black', font=font)

    out_path = os.path.join(out_dir, f'fig_sim_{case}_stages.png')
    composite.save(out_path)
    print(f'Saved: {out_path} ({total_w}x{total_h})')

# === Part 2: Supplementary cases Stage 4 composite ===
supp_cases = ['sem02', 'sem04', 'sem05', 'sem07', 'sem10']
supp_labels = ['sem_02', 'sem_04', 'sem_05', 'sem_07', 'sem_10']

imgs = []
for case in supp_cases:
    folder = f'sim_{case}_stage4'
    path = os.path.join(base, folder, 'simulation', 'stage4_result.png')
    im = Image.open(path)
    im = im.resize((target_size, target_size), Image.LANCZOS)
    imgs.append(im)

gap = 8
total_w = 5 * target_size + 4 * gap
total_h = target_size + label_h + 10

composite = Image.new('RGB', (total_w, total_h), 'white')
draw = ImageDraw.Draw(composite)
font = get_font(16)

for i, (im, label) in enumerate(zip(imgs, supp_labels)):
    x = i * (target_size + gap)
    composite.paste(im, (x, label_h + 10))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x + (target_size - tw) // 2, 6), label, fill='black', font=font)

out_path = os.path.join(out_dir, 'fig_sim_supplementary.png')
composite.save(out_path)
print(f'Saved: {out_path} ({total_w}x{total_h})')
