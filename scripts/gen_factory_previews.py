# -*- coding: utf-8 -*-
"""
scripts/gen_factory_previews.py
为送厂 5 张色码图批量生成视觉预览图（织物效果图），供工厂对照改错。

在配有 GPU 与本项目 Python 环境的机器上运行（本仓库 Windows 工作机无 Python 环境）：
    python scripts/gen_factory_previews.py

输出：outputs/factory_delivery/F*_preview.png（640x640，色码每格 <-> 16x16 纹理块严格对齐）
推理配置与论文/既有 sim run 一致：stage4 + midpoint 300 步 + global_correlated 噪声 + seed 42。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFM = os.path.join(ROOT, 'conditional-flow-matching-main')
sys.path.insert(0, CFM)

import torch

from knitting.inference import (
    load_model,
    build_neighbor_inputs,
    generate_single_image,
)
from data.preprocess import load_color_table
from data.stage1_adapter import parse_stage1_color_map

STAGE = 4
CHECKPOINT = os.path.join(CFM, 'checkpoints', 'stage4', 'best.pt')
JSON_PATH = os.path.join(CFM, 'assets', 'instructions.json')
OUT_DIR = os.path.join(ROOT, 'outputs', 'factory_delivery')

# 送厂 5 片：内部色码图 -> 交付包预览图文件名
JOBS = [
    ('patternplan/pp_01/color_map/pp_01_output.bmp', 'F1_pp01_circle_wave_preview.png'),
    ('edit/edt_05/color_map/edt_05_output.bmp', 'F2_edt05_diamond_wave_preview.png'),
    ('patternplan/pp_04/color_map/pp_04_output.bmp', 'F3_pp04_frame_rib_preview.png'),
    ('edit_native/edtp_01/color_map/edtp_01_output.bmp', 'F4_edtp01_circle_honeycomb_preview.png'),
    ('random/rnd_03/color_map/rnd_03_output.bmp', 'F5_rnd03_frame_cross_preview.png'),
]


def main():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('device =', device)
    model = load_model(STAGE, CHECKPOINT, JSON_PATH, device)
    color_table = load_color_table(JSON_PATH)
    os.makedirs(OUT_DIR, exist_ok=True)

    for rel, out_name in JOBS:
        src = os.path.join(ROOT, 'outputs', 'runs', rel)
        dst = os.path.join(OUT_DIR, out_name)
        id_matrix = parse_stage1_color_map(src, color_table)
        print(f'--- {rel}  shape={id_matrix.shape}  ids=[{id_matrix.min()},{id_matrix.max()}]')
        all_neighbor_ids, all_neighbor_mask = build_neighbor_inputs(id_matrix, device)
        result, noise_mode = generate_single_image(
            model=model,
            id_matrix=id_matrix,
            all_neighbor_ids=all_neighbor_ids,
            all_neighbor_mask=all_neighbor_mask,
            stage=STAGE,
            device=device,
            num_steps=300,
            solver='midpoint',
            noise_mode='global_correlated',
            perturb_scale=0.03,
            seed=42,
            batch_size=100,
        )
        result.save(dst)
        print(f'    saved {dst}  size={result.size}  noise={noise_mode}')

    print('ALL DONE')


if __name__ == '__main__':
    main()
