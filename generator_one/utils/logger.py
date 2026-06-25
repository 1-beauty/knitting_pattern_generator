"""
日志工具模块
"""
import logging
import sys
from pathlib import Path
from config import LOGGING_CONFIG

def setup_logger(name: str = "knitting_pattern", level: str = None) -> logging.Logger:
    """
    创建并配置logger
    
    Args:
        name: logger名称
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
    
    Returns:
        配置好的logger实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 设置日志级别
    log_level = level or LOGGING_CONFIG["level"]
    logger.setLevel(getattr(logging, log_level))
    
    # 创建formatter
    formatter = logging.Formatter(LOGGING_CONFIG["format"])
    
    # 控制台handler
    if LOGGING_CONFIG["console"]:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 文件handler
    log_file = LOGGING_CONFIG["file"]
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# 创建全局logger
logger = setup_logger()