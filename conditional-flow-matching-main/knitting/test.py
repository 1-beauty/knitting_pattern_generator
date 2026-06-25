# 写个脚本看预处理后的16×16块到底有多清晰


import h5py
import numpy as np
from PIL import Image

with h5py.File('dataset_processed/dataset.h5', 'r') as f:
    # 取5个不同的block
    indices = [0, 100, 1000, 10000, 100000]
    for i, idx in enumerate(indices):
        block = f['center_sim'][idx]  # (16,16,3)
        block = (block + 1) * 127.5
        block = np.clip(block, 0, 255).astype(np.uint8)
        
        # 放大10倍看清晰度
        img = Image.fromarray(block).resize((160, 160), Image.NEAREST)
        img.save(f'outputs/real_block_{i}.png')
        print(f'真实block_{i}: shape={block.shape}, min={block.min()}, max={block.max()}')
