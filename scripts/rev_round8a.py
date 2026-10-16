# -*- coding: utf-8 -*-
"""第八轮 a（结构性下放）：正文 16 组段落/图/表 deepcopy 至 Supp，正文留指针句。
去向：A←p033,034,077；G←p063,064；I←p057,067,068；D←p087；C←p137,153-157,160-165(含表6/图9)；
K←p136,142；H←p122；新 Section L←p090-095(图6,7)；新 Section M←p102-105,107-111,113-115,117-118。
重编号：正文 Fig.10→Fig.6；迁出图→Fig.S1-S4；表6→表S21；删 4.1.x 空标题；迁段内交叉引用加"正文"前缀。
全部断言通过才落盘。"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import copy, re
from docx import Document
from docx.oxml.ns import qn

MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
SUPP = r'e:\DeskTop\knitting_pattern_generator\docs\Supplementary_Material.docx'
m, s = Document(MAIN), Document(SUPP)
ps = m.paragraphs
body = m.element.body
sectPr_s = s.element.body.findall(qn('w:sectPr'))[-1]

def rng(a, b):
    """正文段落 a..b 闭区间的全部 body 级元素（含其间表格/空段/图）。"""
    kids = list(body)
    i0, i1 = kids.index(ps[a]._p), kids.index(ps[b]._p)
    return kids[i0:i1 + 1]

def rpl(el, old, new, cnt=1):
    n = 0
    for t in el.findall('.//' + qn('w:t')):
        if t.text and old in t.text:
            n += t.text.count(old); t.text = t.text.replace(old, new)
    assert n == cnt, ('rpl', old, n)

def supp_anchor(prefix):
    sp = s.paragraphs
    i = next(k for k, p in enumerate(sp) if p.style.name == 'Heading 3' and p.text.startswith(prefix))
    for k in range(i + 1, len(sp)):
        if sp[k].style.name in ('Heading 1', 'Heading 2', 'Heading 3'):
            return sp[k]._p
    return sectPr_s  # 末节：追加到文档尾

def move_to(els, anchor):
    for el in els:
        anchor.addprevious(copy.deepcopy(el))
    for el in els:
        el.getparent().remove(el)

# ---------- 1) 迁移（先 deepcopy 插入 Supp，再删正文） ----------
MOVE = [  # (range, anchor-prefix or 'END-L'/'END-M')
    ((33, 34), 'A. '), ((77, 77), 'A. '),
    ((63, 64), 'G. '),
    ((57, 57), 'I. '), ((67, 68), 'I. '),
    ((87, 87), 'D. '),
    ((137, 137), 'C. '), ((153, 157), 'C. '), ((160, 165), 'C. '),
    ((136, 136), 'K. '), ((142, 142), 'K. '),
    ((122, 122), 'H. '),
]
moved_els = {}
for (a, b), pre in MOVE:
    els = rng(a, b)
    moved_els[(a, b)] = [copy.deepcopy(e) for e in els]
    move_to(els, supp_anchor(pre))

# 新 Section L（原型系统）与 M（实验设置细节）追加到 Supp 末尾
h3 = next(p.style for p in s.paragraphs if p.style.name == 'Heading 3')
bt = next(p.style for p in s.paragraphs if p.style.name == 'Body Text')
lh = s.add_paragraph('L. 原型系统：工作台与交互编辑（Prototype System: Workbench and Interactive Editing）', style=h3)
li = s.add_paragraph('本节给出正文第 3 章管线的桌面原型实现与交互编辑界面截图，供复现与试用参考。', style=bt)
mh = s.add_paragraph('M. 实验设置细节（Experimental Setup Details: Dataset, Metrics, Implementation, Baselines）', style=h3)
mi = s.add_paragraph('本节汇总正文第 4 章的数据集构建、评价指标定义、实现参数与基线定义，正文仅保留设置摘要与结果讨论。', style=bt)
elsL = rng(90, 95)
elsM1, elsM2, elsM3, elsM4 = rng(102, 105), rng(107, 111), rng(113, 115), rng(117, 118)
seq = [copy.deepcopy(lh._p), copy.deepcopy(li._p)] + [copy.deepcopy(e) for e in elsL]
seq += [copy.deepcopy(mh._p), copy.deepcopy(mi._p)] + [copy.deepcopy(e) for e in elsM1 + elsM2 + elsM3 + elsM4]
for e in seq:
    sectPr_s.addprevious(e)
# 删除正文原元素与重复的临时标题段
for e in elsL + elsM1 + elsM2 + elsM3 + elsM4:
    e.getparent().remove(e)
lh._p.getparent().remove(lh._p); li._p.getparent().remove(li._p)
mh._p.getparent().remove(mh._p); mi._p.getparent().remove(mi._p)

# ---------- 2) 迁出内容内的交叉引用/编号修正（Supp 侧） ----------
S = s.element.body
for old, new, c in [('Fig. 6.', 'Fig. S1.', 1), ('Fig. 7.', 'Fig. S2.', 1), ('Fig. 8.', 'Fig. S3.', 1),
                    ('Fig. 9.', 'Fig. S4.', 1), ('Table 6', 'Table S21', 1), ('表 6', '表 S21', 2),
                    ('图 9 ', '图 S4 ', 1), ('(?<!正文)式（9）', '正文式（9）', 1),
                    ('三者的工艺依据与对照见补充材料 Section I。', '', 1)]:
    n = 0
    rx = re.compile(old) if old.startswith('(?<') else None
    for t in S.findall('.//' + qn('w:t')):
        if t.text:
            if rx:
                t.text, k = rx.subn(new, t.text); n += k
            elif old in t.text:
                n += t.text.count(old); t.text = t.text.replace(old, new)
    assert n == c, (old, n)
n = 0
for t in S.findall('.//' + qn('w:t')):
    if t.text and re.search(r'(?<!正文 )\d\.\d+(?:\.\d+)? 节', t.text):
        t.text, k = re.subn(r'(?<!正文 )(\d\.\d+(?:\.\d+)?) 节', r'正文 \1 节', t.text); n += k
assert n >= 6, n
rpl(s.paragraphs[next(i for i, p in enumerate(s.paragraphs) if p.text.startswith('正文图 7 的 GUI 截图'))]._p,
    '正文图 7', '图 S2')

# ---------- 3) 正文侧：指针句、空标题删除、图号重排 ----------
def find(pre): return next(p for p in m.paragraphs if p.text.startswith(pre))
def append(p, text):
    nr = copy.deepcopy(p.runs[-1]._r)
    for t in nr.findall(qn('w:t')): nr.remove(t)
    for om in nr.findall('.//' + qn('m:oMath')): om.getparent().remove(om)
    from docx.oxml import OxmlElement
    nt = OxmlElement('w:t'); nt.set(qn('xml:space'), 'preserve'); nt.text = text
    nr.append(nt); p._p.append(nr)

append(find('表 1 给出样本级数据清理后保留的 15 类离散动作标签'), '动作标签来源与两阶段样本级清理过程见补充材料 Section A。')
append(find('以一个“矩形边框包裹波浪吊目圆形主体”的设计为例'), '规则库的组织方式、114 条显式映射项与三类映射的实现边界见补充材料 Section I。')
append(find('基于上述两类关系及式（5）定义的有效作用域'), '确定性单遍贪心编译、作用域裁剪与成组完整性检查机制见补充材料 Section G。')
append(find('动作网格构建阶段将底布、边界和稀疏事件合成为最终的'), 'refinement 与 aesthetic pass 的交界处理见补充材料 Section I。')
append(find('式（7）中，'), '工艺启发式约束的定位（结构上可织但工艺上高风险的灰色地带）见补充材料 Section A。')
append(find('如图 5 所示，模型采用基于 UNet'), 'ODE 推理与采样细节见补充材料 Section D；完整管线另封装为支持交互增量编辑的桌面原型系统，界面与编辑案例见补充材料 Section L。')
append(find('本节评估 PatternPlan 是否能够准确理解自然语言中的设计意图'), '测试集撰写协议与去重统计见补充材料 Section H。')
append(find('在贪心修复之上进一步引入全局约束求解'), '外部基线的对称修复对比与逐方法 TAP 口径分析见补充材料 Section K 与 Section C。')
append(find('repair 主要影响高风险输入下的工艺稳定性'), '修复对纹理语义保留程度的定量对比见补充材料 Section K。')
append(find('可编辑生成实验进一步验证了 PatternPlan 作为结构控制接口的作用'), 'A/B 两组逐变体指标、24 条压力测试与可编辑案例对照见补充材料 Section C（图 S3）。')
append(find('本节评估结构感知视觉预览模块对第一阶段动作结构信息的呈现能力'),
       'Stage 1–4 的全图级与窗口级定量结果见补充材料 Section C；其权衡为：Stage 4 以更小 patch 与边界感知加权牺牲像素级全局一致性、换取边界与局部纹理可读性提升，与其设计阶段外观代理定位一致。')

# 4.1 摘要段（插在 4.1 标题后）
sump = m.add_paragraph('实验设置摘要如下：第一阶段语义解析测试集由 4 名针织背景人员独立撰写、去重后得 100 条；第二阶段训练与评估基于 Neural Inverse Knitting 数据集过滤后的 4028 对配对样本；评价覆盖字段级准确率、样本完全正确率、目标动作纯度、硬约束与工艺启发式约束违例、三项结构级指标及像素级与结构感知预览指标；基线含三类诊断性外部范式与 Plan-Grid、+Repair、+CSP 三个内部控变量。数据集构建、指标定义、实现参数与基线定义见补充材料 Section M。',
                       style=next(p.style for p in m.paragraphs if p.style.name == 'Body Text'))
find('4.1 实验设置（Experimental Setup）')._p.addnext(sump._p)

for pre in ['4.1.1 数据集', '4.1.2 评价指标', '4.1.3 实现细节', '4.1.4 基线方法']:
    p = find(pre)
    p._p.getparent().remove(p._p)

n = 0
for t in m.element.body.findall('.//' + qn('w:t')):
    if t.text and 'Sec. 4.4 Fig. 9.' in t.text:
        n += 1; t.text = t.text.replace('Sec. 4.4 Fig. 9.', 'Supplementary Section C (Fig. S4).')
assert n == 1, n
n = 0
for t in m.element.body.findall('.//' + qn('w:t')):
    if t.text and ('Fig. 10' in t.text or '图 10' in t.text):
        n += t.text.count('Fig. 10') + t.text.count('图 10')
        t.text = t.text.replace('Fig. 10', 'Fig. 6').replace('图 10', '图 6')
assert n >= 5, n

# ---------- 4) 校验 ----------
txt = '\n'.join(p.text for p in m.paragraphs)
CN = len(re.findall(r'[\u4e00-\u9fff]', txt))
assert 16500 <= CN <= 17800, CN
figs = [p.text for p in m.paragraphs if re.match(r'^Fig\. \d+\.', p.text)]
nums = [int(re.match(r'^Fig\. (\d+)\.', f).group(1)) for f in figs]
assert nums == [1, 2, 3, 4, 5, 6], nums
tnums = [int(re.match(r'^Table (\d+) ', p.text).group(1)) for p in m.paragraphs if re.match(r'^Table \d+ ', p.text)]
assert tnums == [1, 2, 3, 4, 5], tnums
for bad in ['Fig. 7', 'Fig. 8', 'Fig. 9', 'Fig. 10', '图 10', 'Table 6', '表 6 ', '式（10）', '式（11）', '式（12）']:
    if bad in txt:
        for p in m.paragraphs:
            if bad in p.text: print('RESIDUAL', bad, '|', p.text[:70])
    assert bad not in txt, bad
cites = sorted(set(int(x) for t in re.findall(r'\[(\d+(?:,\s*\d+)*)\]', txt) for x in re.findall(r'\d+', t)))
assert cites == list(range(1, 49)), cites[:4]
stxt = '\n'.join(p.text for p in s.paragraphs)
for key in ['L. 原型系统', 'M. 实验设置细节', 'Fig. S1.', 'Fig. S2.', 'Fig. S3.', 'Fig. S4.', 'Table S21', '正文式（9）']:
    assert key in stxt, key
m.save(MAIN); s.save(SUPP)
print('OK round8a | main CN=%d | figs=%s tables=%s | supp sections A-M' % (CN, nums, tnums))
