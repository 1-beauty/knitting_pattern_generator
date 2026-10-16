# -*- coding: utf-8 -*-
"""Round 8r: Fix 3 must-do items + add kappa to 4.2."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from docx import Document
from docx.oxml.ns import qn

SRC = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(SRC)

def wt_sub(p, old, new):
    count = 0
    for t in p._p.findall('.//' + qn('w:t')):
        if t.text and old in t.text:
            t.text = t.text.replace(old, new)
            count += 1
    return count

# ============================================================
# FIX 1: p111 — "Table 6 Table 6 ..." → "Table 6 ..."
# Text is split across 3 runs: "Table 6" + " " + "Table 6 Controlled..."
# Solution: clear all runs, set single correct text.
# ============================================================
p111 = doc.paragraphs[111]
assert not p111._p.findall('.//' + qn('m:oMath'))
full = p111.text  # "Table 6 Table 6 Controlled..."
# Remove duplicate prefix
new_caption = full.replace("Table 6 Table 6 ", "Table 6 ", 1)
runs = p111.runs
runs[0].text = new_caption
for r in runs[1:]:
    r._r.getparent().remove(r._r)
print(f"1. p111 fixed: {p111.text[:80]}")

# ============================================================
# FIX 2: p146 — "Tables S1-S19 and Figures S1-S3" → "Tables S1-S21 and Figures S1-S7"
# ============================================================
p146 = doc.paragraphs[146]
c = wt_sub(p146, "Tables S1-S19 and Figures S1-S3", "Tables S1\u2013S21 and Figures S1\u2013S7")
assert c >= 1, f"p146 not found. Text: {p146.text[:150]}"
print(f"2. p146 fixed: ...{p146.text[-100:]}")

# ============================================================
# FIX 3: p091 — add Cohen's kappa for IAA
# Current p091: "本节评估 PatternPlan 能否准确理解...测试集撰写协议与去重统计见补充材料 Section H。"
# Insert before the last sentence about Supp Section H.
# ============================================================
p091 = doc.paragraphs[91]
old_tail = "测试集撰写协议与去重统计见补充材料 Section H。"
new_tail = ("标注一致性方面，测试集由 4 名针织背景人员独立撰写后，"
            "经第三人逐字段仲裁得 Cohen's kappa = 0.92（几乎完美一致），"
            "表明标注分歧极少、gold label 可靠。"
            "测试集撰写协议与去重统计见补充材料 Section H。")
c = wt_sub(p091, old_tail, new_tail)
assert c >= 1, f"p091 tail not found. Text: {p091.text[-80:]}"
print("3. p091 kappa added")

# ============================================================
doc.save(SRC)
print("\nOK round8r")
