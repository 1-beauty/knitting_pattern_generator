"""
第二次 LLM 调用：违反报告 -> RepairPlan
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from core import actions
from utils.logger import logger


@dataclass
class SemanticEdit:
    row: int
    col: int
    new_stitch_type: str
    reason: str = ""


@dataclass
class ActionEdit:
    row: int
    col: int
    new_action: str
    reason: str = ""


@dataclass
class RepairPlan:
    strategy: str = "minimal"
    semantic_edits: List[SemanticEdit] = field(default_factory=list)
    action_edits: List[ActionEdit] = field(default_factory=list)
    config_updates: Dict[str, Any] = field(default_factory=dict)


class RepairAgent:
    """
    违反后修复代理：
    - 接收 violation report
    - 让 LLM 输出最小修复 JSON
    - 解析成 RepairPlan
    """

    def __init__(self, llm_client, prompt_builder):
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder

    def propose(self, user_input, violation_report, summary):
        try:
            messages = self.prompt_builder.build_repair_messages(
                user_input=user_input,
                violation_report=violation_report,
                summary=summary,
            )
            response = self.llm_client.chat(messages)

            # 直接判断 success
            if not response.success:
                logger.warning(f"RepairAgent LLM failed: {response.error}")
                return RepairPlan()

            return self._parse_plan(response.content)

        except Exception as e:
            logger.warning(f"RepairAgent unexpected error: {e}")
            return RepairPlan()

    def apply_action_plan(
        self,
        action_grid,
        plan: RepairPlan,
    ):
        fixed = action_grid.copy()
        for edit in plan.action_edits:
            try:
                r = int(edit.row)
                c = int(edit.col)
                idx_val = actions.idx_safe(edit.new_action, default=None)
                if idx_val is None:
                    continue
                if 0 <= r < fixed.shape[0] and 0 <= c < fixed.shape[1]:
                    fixed[r, c] = idx_val
            except Exception:
                continue
        return fixed

    def _extract_text(self, response) -> str:
        if hasattr(response, "content"):
            return response.content
        if hasattr(response, "text"):
            return response.text
        if isinstance(response, dict):
            if "content" in response:
                return response["content"]
            if "text" in response:
                return response["text"]
        return str(response)

    def _parse_plan(self, text: str) -> RepairPlan:
        json_str = self._extract_json(text)
        if not json_str:
            return RepairPlan()

        try:
            data = json.loads(json_str)
        except Exception:
            try:
                data = json.loads(self._fix_json(json_str))
            except Exception:
                return RepairPlan()

        semantic_edits = []
        for item in data.get("semantic_edits", []):
            if not self._valid_semantic(item.get("new_stitch_type", "")):
                continue
            semantic_edits.append(
                SemanticEdit(
                    row=int(item.get("row", -1)),
                    col=int(item.get("col", -1)),
                    new_stitch_type=item.get("new_stitch_type", ""),
                    reason=item.get("reason", ""),
                )
            )

        action_edits = []
        for item in data.get("action_edits", []):
            if item.get("new_action") not in [actions.abbr(i) for i in actions.ALL_ACTION_INDICES]:
                continue
            action_edits.append(
                ActionEdit(
                    row=int(item.get("row", -1)),
                    col=int(item.get("col", -1)),
                    new_action=item.get("new_action", ""),
                    reason=item.get("reason", ""),
                )
            )

        return RepairPlan(
            strategy=data.get("strategy", "minimal"),
            semantic_edits=semantic_edits,
            action_edits=action_edits,
            config_updates=data.get("config_updates", {}) or {},
        )

    def _extract_json(self, text: str) -> Optional[str]:
        text = text.strip()

        # If starts with {, parse until matching brace while respecting strings/escapes
        if text.startswith("{"):
            depth = 0
            in_string = False
            escape = False
            for i, ch in enumerate(text):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[: i + 1]
            return None

        # try fenced code blocks first
        patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1).strip()

        # fallback: find first { and match with simple stack but guard for quotes
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    def _fix_json(self, s: str) -> str:
        s = re.sub(r",\s*}", "}", s)
        s = re.sub(r",\s*]", "]", s)
        s = s.replace("'", '"')
        s = re.sub(r"(\w+):", r'"\1":', s)
        return s

    def _valid_semantic(self, name: str) -> bool:
        return name.lower() in {
            "background", "void", "active", "double_bed",
            "structure", "degree", "tuck", "cable", "support",
        }