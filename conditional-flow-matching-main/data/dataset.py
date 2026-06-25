"""
data/dataset.py
v3 (方案B): 加载neighbor_mask
"""

import os
import h5py
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler


class KnittingWindowDataset(Dataset):
    
    def __init__(self, h5_path, split='train', load_to_memory=True, expected_patch_size=None):
        self.h5_path = h5_path
        self.split   = split
        self.expected_patch_size = expected_patch_size
        
        print(f"[Dataset {split}] 读取split信息...")
        with h5py.File(h5_path, 'r') as f:
            all_splits = f['split'][:]
            self.has_mask = bool(f.attrs.get('has_mask', False))
            self.patch_size = int(f.attrs.get('patch_size', f['center_sim'].shape[1]))

        if expected_patch_size is not None and self.patch_size != int(expected_patch_size):
            raise RuntimeError(
                f"HDF5 patch_size={self.patch_size}, but config patch_size={expected_patch_size}. "
                "请删除旧的 dataset_processed/dataset.h5 后重新运行 python data/preprocess.py"
            )
        
        target_split = split.encode('utf-8')
        self.indices = np.where(all_splits == target_split)[0]
        
        print(f"[Dataset {split}] 找到 {len(self.indices)} 个样本")
        
        if len(self.indices) == 0:
            raise RuntimeError(
                f"split='{split}'没有样本\n"
                "请确认HDF5是新版预处理生成的（v3）"
            )
        
        if not self.has_mask:
            raise RuntimeError(
                "HDF5文件没有neighbor_mask字段\n"
                "请用最新版preprocess.py重新生成"
            )
        
        self.load_to_memory = load_to_memory
        
        if load_to_memory:
            print(f"[Dataset {split}] 加载到内存...")
            with h5py.File(h5_path, 'r') as f:
                self._neighbor_ids  = f['neighbor_ids'][self.indices]
                self._neighbor_mask = f['neighbor_mask'][self.indices]
                self._center_sim    = f['center_sim'][self.indices]
                self._center_ids    = f['center_id'][self.indices]
            
            mem_mb = (
                self._neighbor_ids.nbytes + 
                self._neighbor_mask.nbytes +
                self._center_sim.nbytes + 
                self._center_ids.nbytes
            ) / 1024 / 1024
            print(f"[Dataset {split}] 加载完成 ({mem_mb:.1f} MB)")
        else:
            print(f"[Dataset {split}] 使用HDF5流式读取，不预加载到内存")
            self.h5f = None
    
    @property
    def center_ids(self):
        if self.load_to_memory:
            return self._center_ids
        with h5py.File(self.h5_path, 'r') as f:
            return f['center_id'][self.indices]
    
    def __len__(self):
        return len(self.indices)
    
    def __getitem__(self, idx):
        if self.load_to_memory:
            neighbor_ids  = self._neighbor_ids[idx]
            neighbor_mask = self._neighbor_mask[idx]
            center_sim    = self._center_sim[idx]
        else:
            if self.h5f is None:
                self.h5f = h5py.File(self.h5_path, 'r', swmr=True)
            real_idx = int(self.indices[idx])
            neighbor_ids  = self.h5f['neighbor_ids'][real_idx]
            neighbor_mask = self.h5f['neighbor_mask'][real_idx]
            center_sim    = self.h5f['center_sim'][real_idx]
        
        neighbor_ids  = torch.from_numpy(np.array(neighbor_ids)).long()
        neighbor_mask = torch.from_numpy(np.array(neighbor_mask)).bool()
        center_sim    = torch.from_numpy(
            np.array(center_sim)
        ).float().permute(2, 0, 1)
        
        return {
            'neighbor_ids':  neighbor_ids,
            'neighbor_mask': neighbor_mask,
            'center_sim':    center_sim,
            'center_id':     neighbor_ids[1, 1],
        }
    
    def get_sample_weights(self, strategy='three_tier'):
        from collections import Counter
        
        cids = self.center_ids
        class_counts = Counter(cids.tolist())
        
        if strategy == 'three_tier':
            class_weights = {}
            for c, count in class_counts.items():
                if count > 100000:
                    class_weights[c] = 1.0
                elif count > 10000:
                    class_weights[c] = 5.0
                elif count > 1000:
                    class_weights[c] = 20.0
                else:
                    class_weights[c] = 50.0
        elif strategy == 'balanced':
            class_weights = {c: 1.0/cnt for c, cnt in class_counts.items()}
        elif strategy == 'sqrt':
            class_weights = {c: 1.0/np.sqrt(cnt) for c, cnt in class_counts.items()}
        else:
            raise ValueError(f"未知策略：{strategy}")
        
        sample_weights = np.array([
            class_weights[int(cid)] for cid in cids
        ], dtype=np.float32)
        
        print(f"\n=== 采样权重统计（策略：{strategy}）===")
        for c in sorted(class_counts.keys()):
            w = class_weights[c]
            n = class_counts[c]
            expected_pct = (w * n) / sum(
                class_weights[k] * v for k, v in class_counts.items()
            ) * 100
            print(f"  ID {c:2d}: 原占比 {n/len(cids)*100:5.2f}% "
                  f"→ 采样后 {expected_pct:5.2f}% (权重 {w:.4f})")
        
        return sample_weights


def worker_init_fn(worker_id):
    pass


def get_dataloaders(processed_dir, batch_size=64,
                    num_workers=4,
                    use_weighted_sampling=True,
                    sampling_strategy='three_tier'):
    h5_path = os.path.join(processed_dir, 'dataset.h5')
    
    if not os.path.exists(h5_path):
        raise FileNotFoundError(
            f"找不到HDF5文件：{h5_path}\n"
            "请先运行 python data/preprocess.py"
        )
    
    train_dataset = KnittingWindowDataset(h5_path, 'train')
    val_dataset   = KnittingWindowDataset(h5_path, 'val')
    
    if use_weighted_sampling:
        weights = train_dataset.get_sample_weights(sampling_strategy)
        sampler = WeightedRandomSampler(
            weights=torch.tensor(weights, dtype=torch.float),
            num_samples=len(weights),
            replacement=True,
        )
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            sampler=sampler,
            num_workers=num_workers,
            pin_memory=True,
            drop_last=True,
            persistent_workers=(num_workers > 0),
            worker_init_fn=worker_init_fn,
        )
    else:
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=num_workers,
            pin_memory=True,
            drop_last=True,
            persistent_workers=(num_workers > 0),
            worker_init_fn=worker_init_fn,
        )
    
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
        drop_last=False,
        persistent_workers=(num_workers > 0),
        worker_init_fn=worker_init_fn,
    )
    
    return train_loader, val_loader
