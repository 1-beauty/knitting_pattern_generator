"""论文展示层的英文案例命名；不改写实验 ID、路径或运行元数据。"""
from __future__ import annotations
import re

CASE_NAMES = {
    'sem': 'Semantic Case',
    'pp': 'Generation Case',
    'test': 'Baseline Case',
    'edt': 'Description-Edit Case',
    'edtp': 'Field-Edit Case',
    'stress': 'Stress Case',
    'rnd': 'Random-Generation Case',
    'abl': 'Ablation Case',
    'nest': 'Nested Case',
}
# 只在已确定为展示文字的片段中调用，不用于任意源文件或路径。
CASE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_])(?P<family>edtp|stress|test|nest|sem|edt|rnd|abl|pp)'
    r'(?:\\?_|-)(?P<number>\d{2,3})(?![A-Za-z0-9_])', re.IGNORECASE)


def case_label(raw: str) -> str:
    match = CASE_PATTERN.fullmatch(raw)
    if not match:
        raise ValueError(f'未定义的案例编号: {raw}')
    return f"{CASE_NAMES[match['family'].lower()]} {match['number']}"


def replace_case_labels(text: str) -> str:
    return CASE_PATTERN.sub(lambda m: case_label(m.group()), text)


def factory_label(number: int) -> str:
    if number not in range(1, 6):
        raise ValueError(number)
    return f'Factory Sample {number}'


FACTORY_CASES = {
    'F1': 'pp_01', 'F2': 'edt_05', 'F3': 'pp_04',
    'F4': 'edtp_01', 'F5': 'rnd_03',
}

ENGLISH_EXPLANATION = (
    'Cases are identified by experiment family and their original numerical suffix '
    '(e.g., Semantic Case 01 and Baseline Case 01). Numbering is independent across '
    'families; identical suffixes do not imply identical inputs or runs. The same case '
    'label is used consistently in the text, tables, and figures. Original run IDs '
    'and file paths remain unchanged for reproducibility; the display-name mapping '
    'is provided in Supplementary Section F. Unmodified GUI screenshots retain '
    'their original run IDs, with English display-name keys supplied alongside.'
)
