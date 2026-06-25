"""
16色调色板定义与工具
"""
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional
import json

from utils.logger import logger


class ColorPalette:
    """
    颜色调色板管理类
    
    从color_mapping.json加载，提供：
    - RGB到ID的映射
    - ID到RGB的映射
    - 快速查找LUT
    """
    
    def __init__(self, mapping_path: Path):
        """
        Args:
            mapping_path: color_mapping.json的路径
        """
        self.mapping_path = Path(mapping_path)
        self._load_mapping()
        self._build_lut()
    
    def _load_mapping(self):
        """加载颜色映射文件"""
        if not self.mapping_path.exists():
            raise FileNotFoundError(f"Color mapping not found: {self.mapping_path}")
        
        with open(self.mapping_path, 'r') as f:
            data = json.load(f)
        
        self.num_classes = data["num_classes"]
        
        # 构建rgb_to_id字典：tuple(r,g,b) -> id
        self.rgb_to_id: Dict[Tuple[int, int, int], int] = {}
        for rgb_str, idx in data["rgb_to_id"].items():
            rgb_list = json.loads(rgb_str)  # "[255, 0, 0]" -> [255, 0, 0]
            self.rgb_to_id[tuple(rgb_list)] = idx
        
        # 构建id_to_rgb数组：shape (num_classes, 3)
        self.id_to_rgb = np.zeros((self.num_classes, 3), dtype=np.uint8)
        for idx_str, rgb_list in data["id_to_rgb"].items():
            self.id_to_rgb[int(idx_str)] = rgb_list
        
        # id_to_name
        self.id_to_name = {int(k): v for k, v in data["id_to_name"].items()}
        
        logger.info(f"Loaded color palette with {self.num_classes} colors")
    
    def _build_lut(self):
        """
        构建RGB24快速查找表
        将24位RGB值(r<<16 | g<<8 | b)映射到颜色ID
        只对调色板中的颜色有效，其他颜色映射到-1
        """
        # 初始化为-1（表示未知颜色）
        self.rgb24_lut = np.full(256 * 256 * 256, -1, dtype=np.int16)
        
        for (r, g, b), idx in self.rgb_to_id.items():
            key = (int(r) << 16) | (int(g) << 8) | int(b)
            self.rgb24_lut[key] = idx
        
        logger.debug("Built RGB24 lookup table")
    
    def rgb_to_token(self, image_rgb: np.ndarray) -> np.ndarray:
        """
        将RGB图像转换为token ID图
        
        Args:
            image_rgb: RGB图像, shape (H, W, 3), dtype uint8
        
        Returns:
            token_map: ID图, shape (H, W), dtype int16
                       -1表示未知颜色
        """
        # 使用LUT快速转换
        keys = (
            (image_rgb[..., 0].astype(np.int32) << 16) |
            (image_rgb[..., 1].astype(np.int32) << 8) |
            image_rgb[..., 2].astype(np.int32)
        )
        token_map = self.rgb24_lut[keys]
        
        # 统计未知颜色
        unknown_count = np.sum(token_map == -1)
        if unknown_count > 100:  # 改为只有超过100个像素才警告
            logger.warning(f"Found {unknown_count} pixels with unknown colors")
        elif unknown_count > 0:
            logger.debug(f"Found {unknown_count} pixels with unknown colors (using nearest neighbor)")
        
        return token_map
    
    def rgb_to_token_nearest(self, image_rgb: np.ndarray) -> np.ndarray:
        """
        将RGB图像转换为token ID图（使用最近邻匹配）
        对于不在调色板中的颜色，找最接近的颜色
        
        Args:
            image_rgb: RGB图像, shape (H, W, 3), dtype uint8
        
        Returns:
            token_map: ID图, shape (H, W), dtype int16
        """
        # 先尝试精确匹配
        token_map = self.rgb_to_token(image_rgb)
        
        # 如果有未知颜色，使用最近邻
        unknown_mask = token_map == -1
        if np.any(unknown_mask):
            # 对未知像素计算到所有调色板颜色的距离
            unknown_pixels = image_rgb[unknown_mask].astype(np.int16)  # (N, 3)
            palette = self.id_to_rgb.astype(np.int16)  # (16, 3)
            
            # 计算欧氏距离
            dists = np.linalg.norm(
                unknown_pixels[:, None, :] - palette[None, :, :], 
                axis=-1
            )  # (N, 16)
            
            # 找最近的颜色
            nearest_ids = np.argmin(dists, axis=-1)
            token_map[unknown_mask] = nearest_ids
        
        return token_map
    
    def token_to_rgb(self, token_map: np.ndarray) -> np.ndarray:
        """
        将token ID图转换为RGB图像
        
        Args:
            token_map: ID图, shape (H, W), dtype int
        
        Returns:
            image_rgb: RGB图像, shape (H, W, 3), dtype uint8
        """
        h, w = token_map.shape
        image_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        
        for idx in range(self.num_classes):
            mask = token_map == idx
            image_rgb[mask] = self.id_to_rgb[idx]
        
        return image_rgb
    
    def get_background_id(self) -> int:
        """获取背景色ID（默认为0）"""
        return 0
    
    def get_color_rgb(self, color_id: int) -> Tuple[int, int, int]:
        """获取指定ID的RGB值"""
        if 0 <= color_id < self.num_classes:
            return tuple(self.id_to_rgb[color_id])
        else:
            raise ValueError(f"Invalid color ID: {color_id}")


# 全局调色板实例（延迟初始化）
_palette_instance: Optional[ColorPalette] = None


def get_palette(mapping_path: Path = None) -> ColorPalette:
    """
    获取全局调色板实例
    
    Args:
        mapping_path: color_mapping.json路径，首次调用时必须提供
    
    Returns:
        ColorPalette实例
    """
    global _palette_instance
    
    if _palette_instance is None:
        if mapping_path is None:
            from config import COLOR_MAPPING_PATH
            mapping_path = COLOR_MAPPING_PATH
        _palette_instance = ColorPalette(mapping_path)
    
    return _palette_instance