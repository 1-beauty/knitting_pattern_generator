# -*- coding: utf-8 -*-
"""第八轮 d（4.6 详细讨论下放 Supp Section N）：
把 p128-p136（六方面局限详述 + 工业部署语境 + 领域可迁移性 + 人力角色边界）整段 deepcopy 到新 Supp Section N，
正文 4.6 保留 p125-p127 + 一段合并概述（保留 [48]、proof-of-concept 口径与六点局限）+ 指针。
迁段内指向正文的节号加'正文'前缀。全部断言通过才落盘。"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import copy, re
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
SUPP = r'e:\DeskTop\knitting_pattern_generator\docs\Supplementary_Material.docx'
m, s = Document(MAIN), Document(SUPP)
sectPr_s = s.element.body.findall(qn('w:sectPr'))[-1]

def find(pre): return next(p for p in m.paragraphs if p.text.startswith(pre))

# ---------- 1) 正文插入合并概述段（在 p127 之后） ----------
bt = next(p.style for p in m.paragraphs if p.style.name == 'Body Text')
summary = ('当前系统仍存在六方面局限，此处概述、详细展开见补充材料 Section N：其一，语义到工艺实现的映射依赖预定义规则集合，'
           '规则库外的复杂组织采用保守降级、可能牺牲纹理丰富度；其二，自修复以局部动作替换为主，对区域级结构冲突'
           '（大面积密集镂空、连续前后床切换、高密度局部纹理）仍需引入区域级重构机制；其三，动作切换强度评分与工艺启发式约束属代理指标，'
           '不能替代真实织造中的纱线张力、断纱风险与织物平整度测量；其四，结构感知视觉预览是基于公开数据集学习的条件生成模型，'
           '定位为设计阶段结构预览而非物理织造仿真，未来需引入更贴近针织结构的纱线级仿真与计算设计方法 [47] 并结合真实样片验证；其五，样本级清理删除了含两类低频动作的配对样本，模型暂不覆盖完整动作空间；'
           '其六，本文生成的动作色码图是机器专有色码无关的抽象动作表示 [48]，颜色仅用于区分内部动作类别，'
           '4.5 节 5 片实物样片的区域几何与纹理均与设计一致，为思路在真实制造条件下提供了可行性证据（proof-of-concept），批量泛化留待后续工作。'
           '工业部署语境中的系统定位、框架的领域可迁移性与人力角色边界亦见补充材料 Section N。')
sp = m.add_paragraph(summary, style=bt)
find('在评估层面，本文已将 H1–H8 硬约束形式化')._p.addnext(sp._p)

# ---------- 2) 新建 Supp Section N，并把 p128-p136 迁入 ----------
h3 = next(p.style for p in s.paragraphs if p.style.name == 'Heading 3')
sbt = next(p.style for p in s.paragraphs if p.style.name == 'Body Text')
nh = s.add_paragraph('N. 补充讨论：详细局限性、部署语境与可迁移性（Extended Discussion: Detailed Limitations, Deployment Context and Transferability）', style=h3)
ni = s.add_paragraph('本节展开正文 4.6 节的六方面局限、工业部署语境中的系统定位、框架的领域可迁移性分析与人力角色边界；正文仅保留概述与指针。', style=sbt)
# add_paragraph 追加到文末（sectPr 之后不存在，实际追加到 body 末尾）；确保位于 sectPr 之前
for e in (nh._p, ni._p):
    e.getparent().remove(e); sectPr_s.addprevious(e)

PREFIX = ['当前系统仍存在六方面局限。首先', '其次，自修复机制主要基于局部动作替换',
          '第三，动作切换强度评分与工艺启发式约束属于代理指标', '第四，视觉预览模块是基于公开数据集学习',
          '第五，样本级清理中删除了含两类低频动作', '第六，需明确本文定位',
          '在工业部署语境中，本系统定位于', '本文框架可拆分为领域无关层',
          '在人力角色上，本系统应理解为打版师的增强工具']
rx = re.compile(r'(?<!正文 )(\d\.\d+(?:\.\d+)?) 节')
moved = 0
for pre in PREFIX:
    p = find(pre)
    el = copy.deepcopy(p._p)
    for t in el.findall('.//' + qn('w:t')):
        if t.text: t.text = rx.sub(r'正文 \1 节', t.text)
    sectPr_s.addprevious(el)
    p._p.getparent().remove(p._p)
    moved += 1
assert moved == 9, moved

# ---------- 校验 ----------
txt = '\n'.join(p.text for p in m.paragraphs)
CN = len(re.findall(r'[\u4e00-\u9fff]', txt))
cites = sorted(set(int(x) for t in re.findall(r'\[(\d+(?:,\s*\d+)*)\]', txt) for x in re.findall(r'\d+', t)))
assert cites == list(range(1, 49)), cites[:4]
figs = [int(re.match(r'^Fig\. (\d+)\.', p.text).group(1)) for p in m.paragraphs if re.match(r'^Fig\. \d+\.', p.text)]
assert figs == [1, 2, 3, 4, 5, 6], figs
assert '当前系统仍存在六方面局限，此处概述' in txt
assert '[47]' in summary and '[48]' in summary, '主文概述未保留 [47]/[48] 引用'
for bad in ['在工业部署语境中，本系统定位于', '本文框架可拆分为领域无关层', '在人力角色上，本系统应理解为']:
    assert bad not in txt, bad
stxt = '\n'.join(p.text for p in s.paragraphs)
assert 'N. 补充讨论' in stxt and '正文 4.5 节' in stxt
m.save(MAIN); s.save(SUPP)
print('OK round8d | main para CN=%d | supp N added' % CN)
