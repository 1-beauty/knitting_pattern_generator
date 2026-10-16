# -*- coding: utf-8 -*-
"""eq(6) 单独降字号至 10pt 使其单行容纳：为其 oMath 内每个 m:r 设 w:rPr/w:sz=20(10pt)。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
M = qn('m:oMath'); MR = qn('m:r'); MT = qn('m:t')
WRPR = qn('w:rPr'); WSZ = qn('w:sz'); WSZCS = qn('w:szCs')

doc = Document(MAIN)
om = doc.tables[7].cell(0, 1)._tc.find('.//' + M)  # eq (6)
cnt = 0
for r in om.iter(MR):
    # 找/建 w:rPr，置于第一个 m:t 之前
    rpr = r.find(WRPR)
    if rpr is None:
        rpr = OxmlElement('w:rPr')
        mts = r.findall(MT)
        if mts:
            mts[0].addprevious(rpr)
        else:
            r.append(rpr)
    for tag in (WSZ, WSZCS):
        e = rpr.find(tag)
        if e is None:
            e = OxmlElement(tag.split('}')[-1].join(['w:', '']) ) if False else OxmlElement('w:' + tag.split('}')[-1])
            rpr.append(e)
        e.set(qn('w:val'), '19')
    cnt += 1
print('eq6 runs sized to 10pt:', cnt)
doc.save(MAIN)
print('saved')
