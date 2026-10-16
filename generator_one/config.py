"""
全局配置 v7.0-semantic-17colors

只保留真正全局需要的配置：
  - 路径
  - 网格尺寸
  - LLM 连接参数
  - 日志

其余配置（规则参数 / 映射参数 / pipeline 参数）
已内聚到各自模块的 dataclass 里，不再集中在这里。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 路径
# ============================================================

PROJECT_ROOT = Path(__file__).parent

DATA_DIR     = PROJECT_ROOT / "data"
OUTPUT_DIR   = PROJECT_ROOT / "outputs"

INSTRUCTION_INFO_PATH = DATA_DIR / "instruction_info.json"

# 自动创建必要目录
for _dir in [
    OUTPUT_DIR,
    OUTPUT_DIR / "images",
    OUTPUT_DIR / "intermediate",
    OUTPUT_DIR / "logs",
    DATA_DIR,
]:
    _dir.mkdir(parents=True, exist_ok=True)

# ============================================================
# 网格
# ============================================================

GRID_SIZE: int = 40          # 逻辑层唯一尺寸，不随显示放大

# ============================================================
# LLM
# ============================================================

LLM_CONFIG = {
    "provider":      "deepseek",
    "api_key":       os.getenv("DEEPSEEK_API_KEY"),
    "base_url":      "https://api.deepseek.com",
    "default_model": "deepseek-chat",
    "models": {
        "chat":  "deepseek-chat",
        "coder": "deepseek-coder",
    },
    "timeout": 300,
    "retry": {
        "max_attempts":  3,
        "backoff_factor": 2,
    },
}

# ============================================================
# 日志
# ============================================================

LOGGING_CONFIG = {
    "level":   "INFO",
    "format":  "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file":    OUTPUT_DIR / "logs" / "app.log",
    "console": True,
}