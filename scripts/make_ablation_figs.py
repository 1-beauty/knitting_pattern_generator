from PIL import Image, ImageDraw, ImageFont
import os

cases = ['01', '03', '06', '07']
settings = ['full', 'no_repair', 'no_refine', 'no_aesthetic']
setting_labels = ['Full', 'No Repair', 'No Refine', 'No Aesthetic']
base = r'outputs\runs\ablation'
out_dir = r'docs\figures'

for case in cases:
    imgs = []
    for s in settings:
        folder = f'abl_{case}_{s}'
        path = os.path.join(base, folder, 'color_map', f'abl_{case}_sim_input.png')
        imgs.append(Image.open(path))

    # Upscale each image to target size using NEAREST for crisp pixel art
    target = 200
    scaled = []
    for im in imgs:
        scale = target // max(im.width, im.height)
        if scale < 1:
            scale = 1
        new_w = im.width * scale
        new_h = im.height * scale
        scaled.append(im.resize((new_w, new_h), Image.NEAREST))
    imgs = scaled

    w = max(im.width for im in imgs)
    h = max(im.height for im in imgs)

    label_h = 35
    gap = 15
    total_w = 4 * w + 3 * gap
    total_h = h + label_h + 10

    composite = Image.new('RGB', (total_w, total_h), 'white')
    draw = ImageDraw.Draw(composite)

    try:
        font = ImageFont.truetype('arial.ttf', 16)
    except:
        font = ImageFont.load_default()

    for i, (im, label) in enumerate(zip(imgs, setting_labels)):
        x = i * (w + gap)
        composite.paste(im, (x, label_h + 10))
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((x + (w - tw) // 2, 5), label, fill='black', font=font)

    out_path = os.path.join(out_dir, f'fig_ablation_case{case}.png')
    composite.save(out_path)
    print(f'Saved: {out_path} ({total_w}x{total_h})')
