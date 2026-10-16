# -*- coding: utf-8 -*-
"""显示公式编号右对齐：把 oMathPara 拆为 行内oMath + 制表位(居中公式/右对齐编号)。
结构: [tab center] oMath [tab right] (n)"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH

SRC = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(SRC)
M = qn('m:oMath'); MP = qn('m:oMathPara'); MR = qn('m:r'); MT = qn('m:t')
CENTER_TW = 4513; RIGHT_TW = 9026  # A4 21cm - 2*2.54cm 边距 = 9026 twips

def mtext(el):
    return ''.join(t.text or '' for t in el.findall('.//' + MT))

fixed = 0
for p in doc.paragraphs:
    omp_list = p._p.findall(MP)
    if not omp_list:
        continue
    omp = omp_list[0]
    om = omp.find(M)
    if om is None:
        continue
    # 取末尾编号 run
    num = None
    rs = om.findall(MR)
    if rs:
        last = rs[-1]
        t = mtext(last).strip()
        if re.match(r'^\(\s*\d+\s*\)$', t):
            num = t
            om.remove(last)
    # 组装: tab + oMath + tab + (n)
    tab1 = OxmlElement('w:r'); tab1.append(OxmlElement('w:tab'))
    tab2 = OxmlElement('w:r'); tab2.append(OxmlElement('w:tab'))
    new_children = [tab1, om, tab2]
    if num:
        nr = OxmlElement('w:r'); nt = OxmlElement('w:t'); nt.text = num; nr.append(nt)
        new_children.append(nr)
    # 移除 oMathPara，插入新序列
    parent = omp.getparent()
    idx = list(parent).index(omp)
    parent.remove(omp)
    for k, ch in enumerate(new_children):
        parent.insert(idx + k, ch)
    # pPr: 制表位 + 左对齐
    ppr = p._p.get_or_add_pPr()
    for old in ppr.findall(qn('w:tabs')):
        ppr.remove(old)
    tabs = OxmlElement('w:tabs')
    for val, pos in (('center', CENTER_TW), ('right', RIGHT_TW)):
        t = OxmlElement('w:tab'); t.set(qn('w:val'), val); t.set(qn('w:pos'), str(pos))
        tabs.append(t)
    ppr.append(tabs)
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    fixed += 1
    print(f'eq fixed: {num}')

doc.save(SRC)
print('display equations fixed:', fixed)
