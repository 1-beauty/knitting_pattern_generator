# -*- coding: utf-8 -*-
"""KID + CLIPScore evaluation recipe for the structure-aware visual preview (Stage 1-4).

Run this on a GPU server. Packages needed:
    pip install torch torchvision open-clip-torch torchmetrics pillow
    (torchmetrics >= 1.3 for KIDMetric / clean-fid fallback)

Architecture:
    --gen_dir   Folder containing generated preview images (one subfolder per stage).
    --ref_dir   Folder containing GT reference images (dataset simulations).
    --prompts   Optional JSON mapping sample_id -> text prompt (for CLIPScore).

Expected folder structure:
    gen_dir/stage_1/*.png
    gen_dir/stage_2/*.png
    gen_dir/stage_3/*.png
    gen_dir/stage_4/*.png
    ref_dir/*.png (GT simulation images matching sample IDs)

Usage:
    python eval_kid_clipscore.py \
        --gen_dir /path/to/outputs/preview_eval \
        --ref_dir /path/to/dataset_raw/simulations \
        --prompts /path/to/instructions.json \
        --device cuda

Notes:
    - KID at n=50 has higher variance; for CiI reviewers, recommend reporting
      ± std over multiple subsets (subsample 10 random subsets of 50 and average).
      Or increase to ≥200 samples by combining validation + test.
    - CLIPScore measures text-image alignment (how well the preview matches the
      design intent expressed in the prompt). It uses ViT-B/32 by default.
    - If the server uses an older model, you can switch to ViT-L/14:
        --clip_model ViT-L-14 --clip_pretrained openai
"""
from __future__ import annotations
import argparse, json, os, glob
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

# ============================================================
# KID (Kernel Inception Distance)
# ============================================================
try:
    from torchmetrics.image import KernelInceptionDistance
    USE_TORCHMETRICS = True
except ImportError:
    USE_TORCHMETRICS = False
    try:
        from cleanfid import fid  # fallback: pip install clean-fid
    except ImportError:
        pass


class ImageDir(Dataset):
    def __init__(self, paths, size=299):
        self.paths = paths
        self.tf = transforms.Compose([
            transforms.Resize((size, size)),
            transforms.ToTensor(),  # [0,1]
        ])
    def __len__(self): return len(self.paths)
    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")
        return self.tf(img)


def compute_kid(gen_paths, ref_paths, device="cuda", subset=50, n_subsets=10):
    """KID with multi-subset bootstrap (reduces small-sample bias)."""
    if USE_TORCHMETRICS:
        kid = KernelInceptionDistance(subset_size=subset, degree=3, variance=False).to(device)
        # add real images
        dset_ref = DataLoader(ImageDir(ref_paths, 299), batch_size=32, num_workers=4)
        for batch in dset_ref:
            kid.update((batch * 255).byte().to(device), real=True)
        # add generated images (multiple subset passes)
        dset_gen = DataLoader(ImageDir(gen_paths, 299), batch_size=32, num_workers=4)
        scores = []
        for s in range(n_subsets):
            kid_gen = KernelInceptionDistance(subset_size=subset, degree=3, variance=False).to(device)
            for batch in dset_gen:
                kid_gen.update((batch * 255).byte().to(device), real=False)
            kid_gen.real_features = kid.real_features  # reuse real features
            m, std = kid_gen.compute()
            scores.append(m.item())
        return np.mean(scores), np.std(scores)
    else:
        # clean-fid fallback (FID, not KID; but less biased variant)
        score = fid.compute_fid(os.path.dirname(gen_paths[0]), os.path.dirname(ref_paths[0]))
        return score, 0.0


# ============================================================
# CLIPScore
# ============================================================
def compute_clipscore(gen_paths, prompts_json, device="cuda", clip_model="ViT-B-32", pretrained="openai"):
    """CLIPScore: cosine similarity between CLIP image embedding of generated preview
    and CLIP text embedding of the design prompt."""
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(clip_model, pretrained=pretrained, device=device)
    tokenizer = open_clip.get_tokenizer(clip_model)
    model.eval()

    # Load prompts
    with open(prompts_json, encoding="utf-8") as f:
        instructions = json.load(f)
    # Map: sample stem -> prompt text (adjust key to match your filenames)
    prompt_map = {}
    for item in instructions:
        sid = item.get("id", item.get("sample_id", ""))
        prompt_map[sid] = item.get("prompt", item.get("input", item.get("text", "")))

    scores = []
    with torch.no_grad():
        for gp in gen_paths:
            stem = Path(gp).stem.split("_")[0]  # adjust to match prompt_map keys
            text = prompt_map.get(stem, "")
            if not text:
                continue
            img = preprocess(Image.open(gp).convert("RGB")).unsqueeze(0).to(device)
            txt = tokenizer([text]).to(device)
            img_emb = model.encode_image(img)
            txt_emb = model.encode_text(txt)
            img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
            txt_emb = txt_emb / txt_emb.norm(dim=-1, keepdim=True)
            sim = (img_emb * txt_emb).sum().item()
            scores.append(sim)
    return np.mean(scores) if scores else float("nan")


# ============================================================
# Main
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen_dir", required=True, help="Root with stage_X/ subfolders")
    ap.add_argument("--ref_dir", required=True, help="GT simulation images folder")
    ap.add_argument("--prompts", default=None, help="JSON prompts for CLIPScore")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--clip_model", default="ViT-B-32")
    ap.add_argument("--clip_pretrained", default="openai")
    args = ap.parse_args()

    ref_paths = sorted(glob.glob(os.path.join(args.ref_dir, "*.png")))
    print(f"GT reference images: {len(ref_paths)}")

    for stage in ["stage_1", "stage_2", "stage_3", "stage_4"]:
        stage_dir = os.path.join(args.gen_dir, stage)
        if not os.path.isdir(stage_dir):
            continue
        gen_paths = sorted(glob.glob(os.path.join(stage_dir, "*.png")))
        print(f"\n--- {stage}: {len(gen_paths)} generated images ---")
        if len(gen_paths) < 20:
            print("  [skip] too few images for reliable KID")
            continue
        kid_mean, kid_std = compute_kid(gen_paths, ref_paths, args.device)
        print(f"  KID = {kid_mean:.4f} ± {kid_std:.4f}")
        if args.prompts:
            cs = compute_clipscore(gen_paths, args.prompts, args.device, args.clip_model, args.clip_pretrained)
            print(f"  CLIPScore = {cs:.4f}")


if __name__ == "__main__":
    main()
