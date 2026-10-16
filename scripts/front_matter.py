# -*- coding: utf-8 -*-
"""P0-2/P0-3：英文标题(候选①)+Abstract+Keywords 替换中文前置件；
在 参考文献 前插入声明件(CRediT/利益冲突/数据可用/致谢/基金)。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(MAIN)
ps = doc.paragraphs

TITLE = ('Hierarchical semantic-constraint compilation and editable generation '
         'of action graphs for flat knitting machines')
ABSTRACT = ('Flat-knitting action graphs are discrete process representations that link design '
    'semantics to stitch-level action structures; their generation must simultaneously satisfy '
    'design-semantics expression and discrete manufacturing constraints such as loop support, '
    'transfer targets and action combinations. To bridge the representation gap between '
    'natural-language design descriptions and low-level action grids, we formulate the task as '
    'semantics-to-action compilation under discrete manufacturing constraints and propose a '
    'hierarchical semantic-constraint compilation and editable generation framework. A '
    'knitting-specific manufacturing intermediate representation, PatternPlan, captures geometry, '
    'texture and parent-child hierarchy; it is compiled into a two-dimensional action graph via '
    'sparse event planning, with hard-constraint checking and conservative self-repair suppressing '
    'structural conflicts, region-level structural editing, and a conditional flow-matching visual '
    'preview as an auxiliary verification interface. On a 15-class action space cleaned from the '
    'Neural Inverse Knitting dataset, PatternPlan achieves 97.2% field-level parsing accuracy over '
    '100 inputs within rule-library coverage. Baseline and controlled experiments show that direct '
    'action-matrix generation and visual-image quantization fail on action validity or design '
    'semantics, respectively, and that replacing event-level compilation with dense filling '
    'systematically degrades region-structure metrics, indicating that region attribution and '
    'grouping completeness stem from explicit hierarchical scoping and sparse event planning; '
    'comparison with a CP-SAT global constraint-projection baseline further shows that action '
    'validity can be closed a posteriori by constraint solving, whereas region attribution and '
    'grouping must be injected explicitly by the compilation process. The action color-code map is '
    'a machine-specific, color-agnostic abstract action representation whose outputs satisfy the '
    'action-level structural constraints defined herein; the system has been validated by a real '
    'factory production test, in which color-code maps of five representative designs were '
    'converted through the factory patterning workflow and knitted into physical samples on real '
    'flat-knitting machines, with region geometry and texture consistent with the designs (Fig. 10), '
    'confirming the accuracy of the semantics-to-action compilation route from digital generation '
    'to physical knitting. These results indicate that flat-knitting action-graph generation is '
    'better modeled as manufacturing-constraint-oriented semantics-to-action compilation than as '
    'plain text-to-image generation.')
KEYWORDS = ('Keywords: Flat knitting; Action graph generation; Hierarchical semantic planning; '
            'Constraint compilation; Editable generation; Visual preview')

def set_text(p, text):
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.add_run(text)

set_text(ps[0], TITLE)
set_text(ps[1], 'Abstract')
set_text(ps[2], ABSTRACT)
set_text(ps[3], KEYWORDS)
print('front matter set')

DECL = [
    ('CRediT authorship contribution statement',
     '[Author A]: Conceptualization, Methodology, Software, Writing - original draft. '
     '[Author B]: Validation, Writing - review & editing. [Author C]: Supervision, Funding acquisition. '
     '(Please replace placeholders with the actual author contributions.)'),
    ('Declaration of competing interest',
     'The authors declare that they have no known competing financial interests or personal '
     'relationships that could have appeared to influence the work reported in this paper.'),
    ('Data availability',
     'The semantic-parsing test inputs (100 cases), per-case outputs and the code will be made '
     'publicly available with the publication of this article.'),
    ('Acknowledgements',
     'The authors thank the partner knitting factory for carrying out the production test. '
     '[Funding agency / grant number to be added.]'),
    ('Funding',
     'This research did not receive any specific grant from funding agencies in the public, '
     'commercial, or not-for-profit sectors. [Replace if funded.]'),
]
# 定位 supplementary-online 句，在其前插声明件
target = None
for p in doc.paragraphs:
    if p.text.strip().startswith('Supplementary data to this article'):
        target = p; break
assert target is not None
for heading, body in reversed(DECL):
    bp = OxmlElement('w:p'); bppr = OxmlElement('w:pPr'); bps = OxmlElement('w:pStyle')
    bps.set(qn('w:val'), 'BodyText'); bppr.append(bps); bp.append(bppr)
    br = OxmlElement('w:r'); bt = OxmlElement('w:t'); bt.text = body
    bt.set(qn('xml:space'), 'preserve'); br.append(bt); bp.append(br)
    hp = OxmlElement('w:p'); hppr = OxmlElement('w:pPr'); hps = OxmlElement('w:pStyle')
    hps.set(qn('w:val'), 'Heading2'); hppr.append(hps); hp.append(hppr)
    hr = OxmlElement('w:r'); ht = OxmlElement('w:t'); ht.text = heading; hr.append(ht); hp.append(hr)
    target._p.addprevious(hp)
    target._p.addprevious(bp)
print('declarations inserted')
doc.save(MAIN)
print('saved')
