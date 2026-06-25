"""Preprocess paired color maps and simulations into one-to-one patch samples."""

import os
import sys
import json
import numpy as np
from PIL import Image
import h5py

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 在preprocess.py或dataset.py里加


def load_color_table(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    color_table = []
    for inst in data['instructions']:
        hex_color = inst['color'].lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        color_table.append((r, g, b))
    return np.array(color_table, dtype=np.int32)


def rgb_to_id_vectorized(rgb_array, color_table):
    """
    向量化的颜色匹配，比逐像素循环快100倍
    
    rgb_array: (H, W, 3) uint8
    color_table: (N, 3) int32
    返回: (H, W) int32
    """
    # rgb_array: (H, W, 3) → (H, W, 1, 3)
    # color_table: (N, 3)  → (1, 1, N, 3)
    # 距离: (H, W, N)
    
    diff = rgb_array[:, :, None, :].astype(np.int32) - color_table[None, None, :, :]
    dist = np.sum(diff ** 2, axis=-1)  # (H, W, N)
    return np.argmin(dist, axis=-1).astype(np.int32)


def parse_color_map(png_path, color_table, grid_size=None):
    img = Image.open(png_path).convert('RGB')
    if grid_size is not None and img.size != (grid_size, grid_size):
        img = img.resize((grid_size, grid_size), Image.NEAREST)
    arr = np.array(img)
    return rgb_to_id_vectorized(arr, color_table)


def parse_simulation(img_path, grid_shape):
    img = Image.open(img_path).convert('RGB')
    grid_h, grid_w = grid_shape
    target_size = (grid_w * 8, grid_h * 8)
    if img.size != target_size:
        img = img.resize(target_size, Image.BICUBIC)
    arr = np.array(img, dtype=np.float32)
    arr = arr / 127.5 - 1.0
    patch_h = arr.shape[0] // grid_h
    patch_w = arr.shape[1] // grid_w
    if patch_h != patch_w:
        raise ValueError(f"Non-square simulation patch size: {(patch_h, patch_w)}")
    blocks = arr.reshape(grid_h, patch_h, grid_w, patch_w, 3).transpose(0, 2, 1, 3, 4)
    return blocks


def preprocess_dataset(color_map_dir, simulation_dir,
                        output_dir, json_path,
                        chunk_size=10000):
    """
    chunk_size: 每个HDF5文件存放的样本数
    """
    color_table = load_color_table(json_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # 收集配对
    pairs = []
    for category in sorted(os.listdir(color_map_dir)):
        cat_color_dir = os.path.join(color_map_dir, category)
        cat_sim_dir   = os.path.join(simulation_dir, category)
        
        if not os.path.isdir(cat_color_dir):
            continue
        if not os.path.isdir(cat_sim_dir):
            print(f"[警告] 找不到仿真目录：{cat_sim_dir}")
            continue
        
        for fname in sorted(os.listdir(cat_color_dir)):
            if not fname.endswith('.png'):
                continue
            
            color_path = os.path.join(cat_color_dir, fname)
            stem       = os.path.splitext(fname)[0]
            sim_path   = os.path.join(cat_sim_dir, stem + '.jpg')
            
            if not os.path.exists(sim_path):
                continue
            
            pairs.append((color_path, sim_path, category, stem))
    
    if len(pairs) == 0:
        print("共找到配对数据：0 对")
        return 0

    sample_counts = []
    for color_path, _, _, _ in pairs:
        with Image.open(color_path) as img:
            sample_counts.append(img.size[0] * img.size[1])
    total_samples = int(sum(sample_counts))
    print(f"共找到配对数据：{len(pairs)} 对")
    print(f"预计窗口样本数：{total_samples}")
    
    # 创建HDF5文件
    h5_path = os.path.join(output_dir, 'dataset.h5')
    print(f"创建HDF5文件：{h5_path}")
    sample_chunk = max(1, min(int(chunk_size), total_samples))
    
    with h5py.File(h5_path, 'w') as h5f:
        # 创建数据集（预分配空间）
        ds_neighbor = h5f.create_dataset(
            'neighbor_ids',
            shape=(total_samples, 3, 3),
            maxshape=(None, 3, 3),
            dtype=np.int32,
            chunks=(sample_chunk, 3, 3),
            compression='gzip',
            compression_opts=1,  # 快速压缩
        )
        ds_sim = h5f.create_dataset(
            'center_sim',
            shape=(total_samples, 8, 8, 3),
            maxshape=(None, 8, 8, 3),
            dtype=np.float32,
            chunks=(sample_chunk, 8, 8, 3),
            compression='gzip',
            compression_opts=1,
        )
        ds_mask = h5f.create_dataset(
            'neighbor_mask',
            shape=(total_samples, 3, 3),
            maxshape=(None, 3, 3),
            dtype=np.bool_,
            chunks=(sample_chunk, 3, 3),
            compression='gzip',
            compression_opts=1,
        )
        ds_center_id = h5f.create_dataset(
            'center_id',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=np.int32,
        )
        ds_image_id = h5f.create_dataset(
            'image_id',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=np.int32,
        )
        ds_row = h5f.create_dataset(
            'row',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=np.int32,
        )
        ds_col = h5f.create_dataset(
            'col',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=np.int32,
        )
        ds_split = h5f.create_dataset(
            'split',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=h5py.string_dtype(encoding='utf-8'),
        )
        ds_category = h5f.create_dataset(
            'category',
            shape=(total_samples,),
            maxshape=(None,),
            dtype=h5py.string_dtype(encoding='utf-8'),
        )
        h5f.attrs['has_mask'] = True
        h5f.attrs['grid_policy'] = 'one_color_cell_to_one_sim_patch'
        h5f.attrs['patch_size'] = 8
        
        # 处理每对图像
        sample_idx = 0
        import time
        start_time = time.time()
        
        for pair_idx, (color_path, sim_path, category, stem) in enumerate(pairs):
            try:
                id_matrix  = parse_color_map(color_path, color_table)
                sim_blocks = parse_simulation(sim_path, id_matrix.shape)
            except Exception as e:
                print(f"[错误] {stem}: {e}")
                continue

            grid_h, grid_w = id_matrix.shape
            num_cells = grid_h * grid_w
            batch_neighbors = np.zeros((num_cells, 3, 3), dtype=np.int32)
            batch_masks = np.zeros((num_cells, 3, 3), dtype=np.bool_)
            batch_sims = np.zeros((num_cells, 8, 8, 3), dtype=np.float32)
            batch_center_ids = np.zeros((num_cells,), dtype=np.int32)
            batch_rows = np.zeros((num_cells,), dtype=np.int32)
            batch_cols = np.zeros((num_cells,), dtype=np.int32)
            
            local_idx = 0
            for row in range(grid_h):
                for col in range(grid_w):
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            nr, nc = row + dr, col + dc
                            if 0 <= nr < grid_h and 0 <= nc < grid_w:
                                batch_neighbors[local_idx, dr+1, dc+1] = id_matrix[nr, nc]
                                batch_masks[local_idx, dr+1, dc+1] = True
                    
                    batch_sims[local_idx] = sim_blocks[row, col]
                    batch_center_ids[local_idx] = id_matrix[row, col]
                    batch_rows[local_idx] = row
                    batch_cols[local_idx] = col
                    local_idx += 1

            split_name = 'val' if (pair_idx % 10 == 0) else 'train'
            # 批量写入HDF5
            ds_neighbor[sample_idx:sample_idx+num_cells] = batch_neighbors
            ds_mask[sample_idx:sample_idx+num_cells] = batch_masks
            ds_sim[sample_idx:sample_idx+num_cells] = batch_sims
            ds_center_id[sample_idx:sample_idx+num_cells] = batch_center_ids
            ds_image_id[sample_idx:sample_idx+num_cells] = pair_idx
            ds_row[sample_idx:sample_idx+num_cells] = batch_rows
            ds_col[sample_idx:sample_idx+num_cells] = batch_cols
            ds_split[sample_idx:sample_idx+num_cells] = [split_name] * num_cells
            ds_category[sample_idx:sample_idx+num_cells] = [category] * num_cells
            
            sample_idx += num_cells
            
            if (pair_idx + 1) % 100 == 0:
                elapsed = time.time() - start_time
                speed   = (pair_idx + 1) / elapsed
                remain  = (len(pairs) - pair_idx - 1) / speed
                print(
                    f"已处理 {pair_idx+1}/{len(pairs)} 对图像 "
                    f"({sample_idx} 样本) "
                    f"速度: {speed:.1f} 对/秒 "
                    f"剩余: {remain/60:.1f} 分钟"
                )
        
        # 截断到实际大小
        if sample_idx < total_samples:
            print(f"实际样本数 {sample_idx} 小于预计 {total_samples}，调整数据集大小")
            ds_neighbor.resize((sample_idx, 3, 3))
            ds_mask.resize((sample_idx, 3, 3))
            ds_sim.resize((sample_idx, 8, 8, 3))
            ds_center_id.resize((sample_idx,))
            ds_image_id.resize((sample_idx,))
            ds_row.resize((sample_idx,))
            ds_col.resize((sample_idx,))
            ds_split.resize((sample_idx,))
            ds_category.resize((sample_idx,))
    
    elapsed = time.time() - start_time
    print(f"\n预处理完成：{sample_idx} 个窗口样本")
    print(f"总耗时：{elapsed/60:.1f} 分钟")
    print(f"HDF5文件：{h5_path}")
    
    file_size = os.path.getsize(h5_path) / 1024 / 1024 / 1024
    print(f"文件大小：{file_size:.2f} GB")
    
    return sample_idx


if __name__ == '__main__':
    preprocess_dataset(
        color_map_dir  = 'dataset_raw/color_maps',
        simulation_dir = 'dataset_raw/simulations',
        output_dir     = 'dataset_processed',
        json_path      = 'assets/instructions.json',
    )
