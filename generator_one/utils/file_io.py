"""
文件读写工具
"""
import json
import pickle
from pathlib import Path
from typing import Any, Dict
import numpy as np
from PIL import Image

from utils.logger import logger


def save_json(data: Dict, filepath: Path) -> None:
    """保存JSON文件"""
    filepath = Path(filepath)
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved JSON to {filepath}")
    except PermissionError as e:
        logger.error(f"Permission denied when saving JSON to {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save JSON to {filepath}: {e}")
        raise


def load_json(filepath: Path) -> Dict:
    """加载JSON文件"""
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"JSON file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    logger.debug(f"Loaded JSON from {filepath}")
    return data


def save_pickle(data: Any, filepath: Path) -> None:
    """保存Pickle文件"""
    filepath = Path(filepath)
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'wb') as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.debug(f"Saved pickle to {filepath}")
    except PermissionError as e:
        logger.error(f"Permission denied when saving pickle to {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save pickle to {filepath}: {e}")
        raise


def load_pickle(filepath: Path) -> Any:
    """加载Pickle文件"""
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"Pickle file not found: {filepath}")
    
    with open(filepath, 'rb') as f:
        data = pickle.load(f)
    
    logger.debug(f"Loaded pickle from {filepath}")
    return data


def save_image(image: np.ndarray, filepath: Path, palette: np.ndarray = None) -> None:
    """
    保存图像

    Args:
        image: 图像数组
            - (H, W) 且提供 palette: 保存为8-bit调色板图
            - (H, W, 3): 保存为RGB图
        filepath: 保存路径
        palette: 调色板 (256, 3)，用于8-bit indexed BMP
    """
    filepath = Path(filepath)
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        logger.error(f"Permission denied creating directory {filepath.parent}: {e}")
        raise

    # ---------- 8-bit indexed image ----------
    if image.ndim == 2 and palette is not None:
        if image.dtype != np.uint8:
            image = image.astype(np.uint8)

        pil_image = Image.fromarray(image, mode="P")

        # PIL要求palette长度固定为 256*3
        flat_palette = palette.astype(np.uint8).reshape(-1).tolist()
        if len(flat_palette) < 256 * 3:
            flat_palette += [0] * (256 * 3 - len(flat_palette))
        elif len(flat_palette) > 256 * 3:
            flat_palette = flat_palette[:256 * 3]

        try:
            pil_image.putpalette(flat_palette)
            pil_image.save(filepath)
            logger.debug(f"Saved 8-bit indexed image to {filepath}")
            return
        except PermissionError as e:
            logger.error(f"Permission denied saving image to {filepath}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to save 8-bit image to {filepath}: {e}")
            raise

    # ---------- RGB image ----------
    if image.dtype != np.uint8:
        image = (image * 255).astype(np.uint8) if image.max() <= 1.0 else image.astype(np.uint8)

    try:
        pil_image = Image.fromarray(image)
        pil_image.save(filepath)
        logger.debug(f"Saved image to {filepath}")
    except PermissionError as e:
        logger.error(f"Permission denied saving image to {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save image to {filepath}: {e}")
        raise

def load_image(filepath: Path, as_array: bool = True):
    """
    加载图像

    Args:
        filepath: 图像路径
        as_array: 是否返回numpy数组

    Returns:
        图像（numpy数组或PIL Image）
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Image file not found: {filepath}")

    try:
        pil_image = Image.open(filepath)
    except Exception as e:
        logger.error(f"Failed to open image {filepath}: {e}")
        raise

    if as_array:
        return np.array(pil_image)
    else:
        return pil_image