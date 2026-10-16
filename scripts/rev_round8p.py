# -*- coding: utf-8 -*-
"""Round 8p: Insert KID/CLIPScore results paragraph after Table 7."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

SRC = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(SRC)
body = doc.element.body

# --- Locate insertion point: after Table 7 (body[204]), before bookmarkEnd (body[205])
target_tbl = doc.tables[16]._tbl  # Table 7
tbl_pos = None
for i, el in enumerate(body):
    if el is target_tbl:
        tbl_pos = i
        break
assert tbl_pos is not None, "Table 7 not found in body"
print(f"Table 7 at body index {tbl_pos}")

# --- Create new paragraph with Body Text style
new_p = OxmlElement('w:p')
# Set style via pPr
pPr = OxmlElement('w:pPr')
pStyle = OxmlElement('w:pStyle')
pStyle.set(qn('w:val'), 'BodyText')
pPr.append(pStyle)
new_p.append(pPr)

# Content: results interpretation paragraph (Chinese, matching paper language)
text_content = (
    "表 7 结果表明：在分布层面，KID 在 Stage 2–3 上最低（0.042、0.044），"
    "Stage 4 与 Stage 1 相当（0.107 vs 0.110），"
    "说明 Stage 4 以更小 patch 与边界感知加权牺牲全局像素分布保真换取边界可读性的权衡"
    "同样体现在分布指标上，与像素级指标趋势一致；"
    "CLIPScore 在四个 Stage 间几乎无差异（0.282–0.283），"
    "表明各 Stage 生成的预览图均能被 CLIP 正确识别为对应织物类型，"
    "语义层面的一致性不构成区分度，Stage 间的品质差异主要体现在像素保真与结构感知维度。"
    "此外，FID 在 n=50 时具有显著小样本偏差，"
    "因此正文采用无偏的 KID 作为分布指标；"
    "完整 FID 与逐图指标见补充材料表 S10。"
)

# Add run with text
r = OxmlElement('w:r')
rPr = OxmlElement('w:rPr')
rFonts = OxmlElement('w:rFonts')
rFonts.set(qn('w:ascii'), 'Times New Roman')
rFonts.set(qn('w:hAnsi'), 'Times New Roman')
rFonts.set(qn('w:eastAsia'), '宋体')
sz = OxmlElement('w:sz')
sz.set(qn('w:val'), '21')  # 10.5pt (五号)
szCs = OxmlElement('w:szCs')
szCs.set(qn('w:val'), '21')
rPr.append(rFonts)
rPr.append(sz)
rPr.append(szCs)
r.append(rPr)
t = OxmlElement('w:t')
t.text = text_content
t.set(qn('xml:space'), 'preserve')
r.append(t)
new_p.append(r)

# Insert after Table 7
body.insert(tbl_pos + 1, new_p)
print("Results paragraph inserted after Table 7")

doc.save(SRC)
print("OK round8p")
