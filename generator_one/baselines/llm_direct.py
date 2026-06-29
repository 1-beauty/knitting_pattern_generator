"""
Baseline: LLM directly outputs 40x40 action grid (no PatternPlan, no rules).

This baseline tests whether an LLM can directly generate a valid 15-color
knitting action color map without any structured intermediate representation
or constraint enforcement.
"""

import json
import re
import time
import numpy as np
from typing import Dict, Any, Optional

from config import GRID_SIZE
from core import actions
from rules import check_physical, check_craft_actions, tension_score
from llm.client import LLMClient
from utils.logger import logger


# ============================================================
# Prompt
# ============================================================

LLM_DIRECT_SYSTEM_PROMPT = """你是一个针织组织色码图生成器。

给定用户的针织图案描述，你需要直接输出一个 40x40 的动作网格。
每个格子的值是一个 0-14 的整数，代表一个针织动作。

## 动作编号表
0: 前床成圈（正针）- 最常用，用于主体支撑
1: 后床成圈（反针）- 用于反面或过渡
2: 移针：前至后
3: 移针：后至前
4: 后床集圈 - 用于纹理凸起
5: 空针背景（不织）- 用于背景
6: 移针并左移1针
7: 前床集圈 - 用于纹理凸起
8: 前床劈针 - 用于过渡
9: 后床劈针 - 用于过渡
10: 前床集圈变体
11: 前后落布
12: 劈针变体
13: 后床集圈变体
14: 移针并右移1针

## 规则
- 大部分区域应该是 0（前床成圈）或 5（空针背景）
- 边框使用 1（后床成圈）
- 集圈（4或7）用于纹理效果，成对出现
- 移针（2,3,6,14）用于针床切换
- 不要输出太多特殊动作，大多数格子应该是 0 或 5

## 输出格式
输出一个 JSON 对象，包含 "grid" 字段，值为长度为 1600 的整数数组（行优先顺序，40行×40列）。
数组中每个值必须是 0-14 的整数。

示例格式：
{"grid": [0,0,0,...,0]}  (共1600个元素)

只输出 JSON，不要输出其他内容。"""


def build_llm_direct_user_prompt(user_input: str) -> str:
    return f"""请根据以下针织图案描述，生成 40x40 的动作网格。

描述：{user_input}

请输出 JSON 格式的 1600 个整数数组（值域 0-14，行优先）。"""


# ============================================================
# Parser
# ============================================================

def parse_llm_direct_grid(llm_output: str) -> Optional[np.ndarray]:
    """Parse LLM output into a 40x40 action grid.

    Supports two formats:
    1. {"grid": [...1600 ints...]}
    2. Raw JSON array [...1600 ints...]
    """
    # Try to extract JSON
    json_match = re.search(r'\{[^{}]*"grid"\s*:\s*\[([^\]]*)\]', llm_output, re.DOTALL)
    if json_match:
        try:
            nums = [int(x.strip()) for x in json_match.group(1).split(',') if x.strip()]
            if len(nums) == GRID_SIZE * GRID_SIZE:
                grid = np.array(nums, dtype=np.uint8).reshape(GRID_SIZE, GRID_SIZE)
                grid = np.clip(grid, 0, 14)
                return grid
        except (ValueError, TypeError):
            pass

    # Try raw array
    array_match = re.search(r'\[([^\]]{100,})\]', llm_output, re.DOTALL)
    if array_match:
        try:
            nums = [int(x.strip()) for x in array_match.group(1).split(',') if x.strip()]
            if len(nums) == GRID_SIZE * GRID_SIZE:
                grid = np.array(nums, dtype=np.uint8).reshape(GRID_SIZE, GRID_SIZE)
                grid = np.clip(grid, 0, 14)
                return grid
        except (ValueError, TypeError):
            pass

    return None


# ============================================================
# Pipeline
# ============================================================

class LLMDirectPipeline:
    """Baseline: LLM directly outputs 40x40 action grid."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate(self, user_input: str) -> Dict[str, Any]:
        """Run the LLM-Direct baseline.

        Returns a dict with:
        - action_grid: np.ndarray (40, 40)
        - success: bool (whether grid was parsed)
        - hard_violations: int
        - craft_violations: int
        - tension: float
        - action_diversity: int
        - execution_time: float
        - distribution: dict
        """
        start = time.time()

        messages = [
            {"role": "system", "content": LLM_DIRECT_SYSTEM_PROMPT},
            {"role": "user", "content": build_llm_direct_user_prompt(user_input)},
        ]

        response = self.llm_client.chat(
            messages,
            temperature=0.1,
            max_tokens=16000,  # Need high token limit for 1600 integers
        )

        if not response.success:
            logger.error(f"LLM-Direct: LLM call failed: {response.error}")
            return self._empty_result(time.time() - start, error=response.error)

        grid = parse_llm_direct_grid(response.content)
        if grid is None:
            logger.error("LLM-Direct: Failed to parse grid from LLM output")
            logger.debug(f"LLM output preview: {response.content[:200]}")
            return self._empty_result(time.time() - start, error="parse_failed")

        # Run constraint checks (same as main pipeline)
        hard = check_physical(grid)
        craft = check_craft_actions(grid)
        tension = tension_score(grid)

        # Distribution
        uniq, counts = np.unique(grid, return_counts=True)
        distribution = {actions.abbr(int(i)): int(c) for i, c in zip(uniq, counts)}

        execution_time = time.time() - start

        result = {
            "action_grid": grid,
            "success": True,
            "hard_violations": len(hard),
            "craft_violations": len(craft),
            "tension_score": tension,
            "action_diversity": len(uniq),
            "execution_time": execution_time,
            "distribution": distribution,
            "hard_details": [self._v2d(v) for v in hard[:20]],
            "craft_details": [self._v2d(v) for v in craft[:20]],
        }

        logger.info(
            f"LLM-Direct: hard={len(hard)} craft={len(craft)} "
            f"tension={tension:.4f} diversity={len(uniq)} time={execution_time:.2f}s"
        )
        return result

    def _empty_result(self, execution_time: float, error: str = "") -> Dict[str, Any]:
        return {
            "action_grid": np.full((GRID_SIZE, GRID_SIZE), 5, dtype=np.uint8),  # all background
            "success": False,
            "hard_violations": -1,
            "craft_violations": -1,
            "tension_score": -1.0,
            "action_diversity": 0,
            "execution_time": execution_time,
            "distribution": {},
            "error": error,
        }

    def _v2d(self, v) -> Dict:
        return {
            "level": getattr(v, "level", ""),
            "rule": getattr(v, "rule", ""),
            "row": int(getattr(v, "row", -1)),
            "col": int(getattr(v, "col", -1)),
            "detail": getattr(v, "detail", ""),
        }
