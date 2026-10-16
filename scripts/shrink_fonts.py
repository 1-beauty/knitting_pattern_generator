# -*- coding: utf-8 -*-
"""字号收紧：正文 BodyText/FirstParagraph 12->11pt；表格 Compact 10.5->10pt；
表题 TableCaption / 图题 Caption / 表注 BlockText -> 10pt。标题层级不动。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.shared import Pt
SRC = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(SRC)

PLAN = {
    'BodyText': 11, 'FirstParagraph': 11,
    'Compact': 10, 'TableCaption': 10, 'Caption': 10, 'BlockText': 10,
}
for name, pt in PLAN.items():
    try:
        st = doc.styles[name]
    except KeyError:
        print('missing style', name); continue
    st.font.size = Pt(pt)
    print(f'{name} -> {pt}pt')
doc.save(SRC)
print('saved')
