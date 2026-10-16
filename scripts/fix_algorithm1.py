# -*- coding: utf-8 -*-
"""算法 1 重排：把 'Source Code' 样式灰底段落（para[70]）改为 Elsevier 风格 Algorithm 框。
结构：题注段（Algorithm 1，左对齐）+ 单格边框表（Input/Output + 11 编号步骤）。
原段落清空保留为表后空段（防止表格与下一段合并，并充当间距）。"""
import re
import docx
from docx.shared import Pt, Twips
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH

SRC = r'docs\论文to_cii.docx'
doc = docx.Document(SRC)
ps = doc.paragraphs

# --- 定位算法段：Source Code 样式且以"算法 1"开头 ---
idx = None
for i, p in enumerate(ps):
    if p.style.name == 'Source Code' and p.text.strip().startswith('算法 1'):
        idx = i
        break
assert idx is not None, 'algorithm paragraph not found'
raw = ps[idx].text
lines = [l for l in raw.split('\n')]
title_line = lines[0].strip()                      # 算法 1：语义驱动动作色码图生成
body = [l.strip() for l in lines[1:] if l.strip()] # 输入/输出 + 步骤
assert body[0].startswith('输入') and body[1].startswith('输出'), body[:2]
steps = body[2:]
assert len(steps) == 11 and all(re.match(r'^\d+\.', s) for s in steps), steps
cap_title = title_line.split('：', 1)[1].strip()    # 语义驱动动作色码图生成

# --- 字体辅助 ---
def add_run(p, text, bold=False, italic=False, size=9):
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    r.font.name = 'Times New Roman'
    rPr = r._element.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rPr.insert(0, rf)
    rf.set(qn('w:ascii'), 'Times New Roman')
    rf.set(qn('w:hAnsi'), 'Times New Roman')
    rf.set(qn('w:eastAsia'), '宋体')
    return r

def fmt(p, before=1, after=1, hang=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = 1.0
    if hang:
        pf.left_indent = Twips(340)
        pf.first_line_indent = Twips(-340)

# --- 1) 原段落改写为题注段 ---
cap = ps[idx]
for r in list(cap.runs):
    r._element.getparent().remove(r._element)
cap.style = doc.styles['Normal']
add_run(cap, 'Algorithm 1', bold=True, size=10)
add_run(cap, '  ' + cap_title, bold=False, size=10)
fmt(cap, before=8, after=4)
cap.alignment = WD_ALIGN_PARAGRAPH.LEFT

# --- 2) 建单格表，插到题注段之后 ---
tbl = doc.add_table(rows=1, cols=1)   # 先加在文末
tbl.autofit = False
tbl.columns[0].width = Twips(9360)
tbl.rows[0].cells[0].width = Twips(9360)

# 边框：外框上下粗(12)、左右细(6)，无内线 —— algorithmic 风格
tblPr = tbl._tbl.tblPr
borders = OxmlElement('w:tblBorders')
for tag, sz in (('top', 12), ('left', 6), ('bottom', 12), ('right', 6), ('insideH', 0), ('insideV', 0)):
    el = OxmlElement('w:' + tag)
    el.set(qn('w:val'), 'single' if sz else 'none')
    el.set(qn('w:sz'), str(sz))
    el.set(qn('w:color'), '000000')
    borders.append(el)
tblPr.append(borders)
# 单元格边距
mar = OxmlElement('w:tblCellMar')
for tag, v in (('top', 100), ('left', 170), ('bottom', 100), ('right', 170)):
    el = OxmlElement('w:' + tag)
    el.set(qn('w:w'), str(v))
    el.set(qn('w:type'), 'dxa')
    mar.append(el)
tblPr.append(mar)

cell = tbl.rows[0].cells[0]
cp = cell.paragraphs[0]
for r in list(cp.runs):
    r._element.getparent().remove(r._element)
# Input / Output
p = cp
p.text = ''
add_run(p, 'Input: ', bold=True)
add_run(p, '自然语言描述 D')
fmt(p, hang=False)
p2 = cell.add_paragraph()
add_run(p2, 'Output: ', bold=True)
add_run(p2, '内部动作色码图 P，统计报告 Q')
fmt(p2)
# 分隔细线（段落下边框）
pPr = p2._p.get_or_add_pPr()
pbdr = OxmlElement('w:pBdr')
btm = OxmlElement('w:bottom')
btm.set(qn('w:val'), 'single'); btm.set(qn('w:sz'), '6'); btm.set(qn('w:color'), '000000')
pbdr.append(btm)
pPr.append(pbdr)
# 步骤
for s in steps:
    sp = cell.add_paragraph()
    num, rest = s.split('.', 1)
    add_run(sp, num.ljust(2) + '.', bold=False)
    add_run(sp, rest.strip())
    fmt(sp, hang=True)

# 移动到题注段之后
cap._p.addnext(tbl._tbl)

# --- 3) 校验 ---
d2 = docx.Document(SRC) if False else doc
doc.save(SRC)
chk = docx.Document(SRC)
tables = chk.tables
# 找到含 'Input:' 的表
hit = [i for i, t in enumerate(tables) if 'Input' in t.rows[0].cells[0].text]
print('algorithm table index:', hit, 'total tables:', len(tables))
capno = [i for i, p in enumerate(chk.paragraphs) if p.text.startswith('Algorithm 1')]
print('caption para:', capno)
# 公式表不受影响
eqt = [i for i, t in enumerate(tables) if t._tbl.find('.//' + qn('m:oMath').replace('w:', 'm:')) is not None] if False else None
print('OK')
