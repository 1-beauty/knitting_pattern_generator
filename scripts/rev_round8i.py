# -*- coding: utf-8 -*-
"""第八轮 i（工厂叙事口径统一，响应评审 P1-6 内部不一致）：
8c/8d/8f 曾重新引入用户已明令移除的找补措辞（proof-of-concept / 初步验证 / 受控 5 例 / 批量泛化留待后续）。
按既定口径（事实从简、不找补、不弱化；统一表述"技术思路已送合作工厂完成落地测试，证实了思路的准确性"）
重写 p002(摘要EN)/p018/p120/p125/p131，去除上述措辞；保留 [47][48]；摘要保持 ≤250 词。
不动 p111 的统计功效说明（属诚实统计局限，非工厂找补）。"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import re
from docx import Document
from docx.oxml.ns import qn
MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
m = Document(MAIN)
ps = m.paragraphs


def rewrite(pre, new):
    p = next(p for p in ps if p.text.startswith(pre))
    assert not p._p.findall('.//' + qn('m:oMath')), ('oMath', pre)
    old_cites = set(re.findall(r'\[\d+[^\]]*\]', p.text))
    miss = [c for c in old_cites if c not in new]
    assert not miss, (pre[:20], miss)
    rr = p.runs; rr[0].text = new
    for r in rr[1:]: r._element.getparent().remove(r._element)
    return p


# p002 摘要（英）：去 proof-of-concept
rewrite('Flat-knitting action graphs link design semantics',
        'Flat-knitting action graphs link design semantics to stitch-level action structures, whose generation must satisfy discrete manufacturing constraints such as loop support, transfer targets and action combinations. We formulate this task as semantics-to-action compilation and propose a hierarchical semantic-constraint compilation and editable generation framework. A knitting-specific manufacturing intermediate representation, PatternPlan, captures geometry, texture and parent-child hierarchy; it is compiled into a two-dimensional action graph via sparse event planning, with hard-constraint checking and conservative self-repair suppressing structural conflicts, region-level structural editing, and a conditional flow-matching visual preview for verification. On a 15-class action space cleaned from the Neural Inverse Knitting dataset, PatternPlan achieves 97.2% field-level parsing accuracy over 100 inputs within rule-library coverage. Baseline and controlled experiments show that direct action-matrix generation and visual-image quantization fail on action validity or design semantics, and that replacing event-level compilation with dense filling degrades region-structure metrics; comparison with a CP-SAT global constraint-projection baseline further shows that action validity can be closed a posteriori by constraint solving, whereas region attribution and grouping must be injected explicitly by compilation, an advantage that is directional under the current motif sample. The action color-code map is a machine-specific, color-agnostic abstract action representation; five representative designs were converted through the partner factory’s standard patterning workflow and knitted on its routine industrial flat-knitting machines into physical samples consistent with the designs (Fig. 6), confirming the accuracy of the proposed approach. Within rule-library coverage, flat-knitting action-graph generation is therefore better served by manufacturing-constraint-oriented semantics-to-action compilation than by plain text-to-image generation.')

# p018 引言末：去 受控5例/初步验证
rewrite('最后，本文系统已与宁波慈星股份有限公司合作完成工厂验证',
        '最后，本文系统已与宁波慈星股份有限公司合作完成工厂验证（4.5 节）：动作色码图与结构感知视觉预览图交付工厂后，经工厂打版流程转换在真实横机上织出成品样片，实物的区域几何与纹理结构均与设计一致，成品实物已在图 6 中展示，证实了本文技术思路在真实制造条件下的准确性。')

# p120 4.5 图6 讨论：去 受控5例/proof-of-concept/批量泛化留待后续
rewrite('图 6 将上述证据整合为单张对照表',
        '图 6 将上述证据整合为单张对照表，各行依次给出 PatternPlan 摘要、40×40 动作色码图、结构感知视觉预览图与工厂实织样片。五个样片均成功织出，区域轮廓、纹理类型与周期走向均与设计对应（如 Sample 3 的连续罗纹纵条、Sample 1/2 圆形与菱形区域内与设计点阵对应的吊目纹理、Sample 4 的蜂窝状点阵、Sample 5 的 X 形斜向纹理），边框与主体区域边界均与设计网格对应。上述结果表明，本文生成的动作色码图经工厂打版流程转换后可在真实横机上织出区域结构与纹理同设计一致的织物，语义到动作编译思路通过了真实制造链路的落地验证，证实了技术思路的准确性。')

# p125 局限六尾：去 proof-of-concept/批量泛化留待后续（保 [47][48]）
rewrite('当前系统仍存在六方面局限（详细展开见补充材料 Section N）',
        '当前系统仍存在六方面局限（详细展开见补充材料 Section N）：其一，语义到工艺实现的映射依赖预定义规则集合，规则库外复杂组织采用保守降级、可能牺牲纹理丰富度；其二，自修复以局部动作替换为主，区域级结构冲突（大面积密集镂空、连续前后床切换、高密度局部纹理）仍需区域级重构机制；其三，动作切换强度评分与工艺启发式约束属代理指标，不能替代真实织造中的纱线张力、断纱风险与织物平整度测量；其四，结构感知视觉预览定位为设计阶段结构预览而非物理织造仿真，未来需引入更贴近针织结构的纱线级仿真与计算设计方法 [47] 并结合真实样片验证；其五，样本级清理删除了含两类低频动作的配对样本，暂不覆盖完整动作空间；其六，本文动作色码图是机器专有色码无关的抽象动作表示 [48]，颜色仅用于区分内部动作类别，4.5 节 5 片实物样片的区域几何与纹理均与设计一致，证实了技术思路在真实制造条件下的准确性。工业部署语境中的系统定位、领域可迁移性与人力角色边界亦见补充材料 Section N。')

# p131 结论：去 受控5例/初步验证
rewrite('总体而言，本文的核心价值在于以层次化制造中间表示连接设计语义',
        '总体而言，本文的核心价值在于以层次化制造中间表示连接设计语义与制造动作，以事件级约束编译在受测输入上实现动作表示的硬约束零违例（例外见 4.3.3 节）、区域结构与可编辑性；约束结果应理解为预定义离散规则下的验证。在此基础上，本文系统已通过合作工厂的真实落地检测，5 片代表性样片均成功织出且区域结构与纹理均与设计一致，从数字生成到物理织造的链路经真实落地检测证实了技术思路的准确性（4.5 节，成品实物见图 6）。未来工作将围绕针织组织规则扩展、区域级结构重构、结构感知视觉评价、受控用户研究以及面向更丰富组织与完整花型的工厂落地测试展开。')

m.save(MAIN)

# 校验
txt = '\n'.join(p.text for p in m.paragraphs)
for bad in ['proof-of-concept', '初步验证', '受控 5 例', '批量泛化留待']:
    assert bad not in txt, ('still hedging:', bad)
assert '[47]' in txt and '[48]' in txt
abs_words = len(re.findall(r"[A-Za-z]+", ps[2].text))
print('OK round8i | 工厂口径统一 | 摘要词数=%d (<=250: %s)' % (abs_words, abs_words <= 250))
assert abs_words <= 250
