# -*- coding: utf-8 -*-
"""第八轮 g（编号闭合校验修复）：
1) Supp 残留标题 '3.6 原型系统实现' → 归入 Section L，改为 'L.1 ...' 且 Heading 4。
2) 补充图编号顺移：图/Fig. 上下文中 S4<->S6、S5<->S7 交换（不触碰 表/Table Sx），
   使 Supp 图题注按文档顺序为 S1..S7，main 引用保持单调且全部可解析。
单遍映射替换，断言总替换数==8；断言交换后题注顺序 S1..S7；不落盘除非全部通过。"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import re
from docx import Document
from docx.oxml.ns import qn

MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
SUPP = r'e:\DeskTop\knitting_pattern_generator\docs\Supplementary_Material.docx'
m, s = Document(MAIN), Document(SUPP)

# ---------- 1) 残留标题归位 ----------
stray = next(p for p in s.paragraphs if p.style.name == 'Heading 3' and p.text.strip().startswith('3.6 原型系统实现'))
h4 = next(p.style for p in s.paragraphs if p.style.name == 'Heading 4')
for t in stray._p.findall('.//' + qn('w:t')):
    if t.text and '3.6 原型系统实现' in t.text:
        t.text = t.text.replace('3.6 原型系统实现', 'L.1 原型系统实现')
stray.style = h4

# ---------- 2) 图号交换 ----------
SWAP = {'4': '6', '5': '7', '6': '4', '7': '5'}
fig_rx = re.compile(r'(图\s*S|Fig\.\s*S)([4567])')
count = {'n': 0}


def sub_wt(doc):
    for t in doc.element.body.findall('.//' + qn('w:t')):
        if not t.text:
            continue
        def rep(mo):
            count['n'] += 1
            return mo.group(1) + SWAP[mo.group(2)]
        new = fig_rx.sub(rep, t.text)
        if new != t.text:
            t.text = new


sub_wt(m); sub_wt(s)
assert count['n'] == 8, ('swap count', count['n'])

# ---------- 校验：题注文档顺序 S1..S7 ----------
cap = []
for p in s.paragraphs:
    t = p.text.strip()
    mm = re.match(r'^(?:图|Fig\.)\s*S(\d+)', t)
    if mm and (t.startswith('图 S') or t.startswith('Fig. S')):
        # 排除以 '图 S5 的 GUI' 这类正文引用（其后紧跟非题注描述）——题注特征：S数字后接空格+标题词
        cap.append(int(mm.group(1)))
# 题注应为 7 个且严格 S1..S7（含 GUI 引用行会多计，需过滤）
print('caption-order raw:', cap)

# 重新精确取题注：段落以 图 Sx / Fig. Sx 开头且该段是图注（长度较短或以句点/。分隔标题）
def is_caption(p):
    t = p.text.strip()
    if not (t.startswith('图 S') or t.startswith('Fig. S')):
        return False
    if 'GUI 截图均为未经修改' in t:  # s135 正文引用（非题注），交换后仍含此特征串
        return False
    return True
caps = [int(re.match(r'^(?:图|Fig\.)\s*S(\d+)', p.text.strip()).group(1)) for p in s.paragraphs if is_caption(p)]
print('caption-order filtered:', caps)
assert caps == [1, 2, 3, 4, 5, 6, 7], caps

# main 引用单调且可解析
mrefs = []
for p in m.paragraphs:
    for mm in re.finditer(r'(?:图|Fig\.)\s*S(\d+)', p.text):
        mrefs.append(int(mm.group(1)))
print('main supp-fig refs order:', mrefs)
assert all(1 <= x <= 7 for x in mrefs)

# 表 Sx 未被误改：抽查 表 S4/S5/S6/S7 仍存在
stxt = '\n'.join(p.text for p in s.paragraphs)
for tk in ['表 S4', '表 S5', '表 S6', '表 S7']:
    assert tk in stxt, ('table token lost', tk)

m.save(MAIN); s.save(SUPP)
print('OK round8g | stray->L.1 H4 | fig swap=8 | caption order S1..S7 | main refs', mrefs)
