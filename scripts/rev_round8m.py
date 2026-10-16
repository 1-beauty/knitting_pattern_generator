# -*- coding: utf-8 -*-
"""Round 8m: Honest revision of Table 6 + related paragraphs per expanded Protocol-B result.

Key changes:
- Table 6: updated with expanded hard-nested pool (n=44, 45 paired motifs).
- Region IoU reframed (dense trivially maximizes scope coverage).
- Grouping/wave-pair significance reported (p<1e-3, robust).
- Abstract, 3.2.1 forward-ref, 4.3.2 paragraphs, conclusion all updated.
"""
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.table import WD_TABLE_ALIGNMENT
import re, sys

SRC = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(SRC)

# ============================================================
# A. Paragraph w:t targeted substitutions (preserves oMath)
# ============================================================
def wt_sub(p, old, new, expected_count=1):
    """Replace 'old' with 'new' in w:t elements of paragraph p."""
    total = 0
    for t in p._p.findall('.//' + qn('w:t')):
        if t.text and old in t.text:
            c = t.text.count(old)
            t.text = t.text.replace(old, new)
            total += c
    assert total >= expected_count, f"Expected {expected_count} hits for '{old[:60]}', got {total}"
    return total

def rewrite(p, new_text):
    """Full text rewrite (only for paragraphs with NO oMath)."""
    assert not p._p.findall('.//' + qn('m:oMath')), "Cannot rewrite oMath para!"
    runs = p.runs
    if not runs:
        p.add_run(new_text)
    else:
        runs[0].text = new_text
        for r in runs[1:]:
            r._r.getparent().remove(r._r)

paras = doc.paragraphs
edits = 0

# p002 (abstract, EN, 2043 chars) — 2 targeted subs
p = paras[2]
wt_sub(p, "degrades region-structure metrics",
       "degrades wave-pair grouping integrity (p<0.001 over 44 hierarchical inputs)")
wt_sub(p, "an advantage that is directional under the current motif sample",
       "a statistically robust advantage confirmed on an expanded hierarchical nested pool")
edits += 2
print("p002 (abstract) OK")

# p048 — full rewrite (no oMath, long Chinese phrase may span runs)
p = paras[48]
t048 = p.text
assert "0.240" in t048 and "0.953" in t048
t048_new = t048.replace(
    "以区域内密集周期填充替换事件级编译后纹理泄漏率由 0.240 升至 0.311、成组完整率由 1.000 降至 0.953",
    "以区域内密集周期填充替换事件级编译后成组完整率由 1.000 降至 0.923（Wilcoxon p<0.001，扩展 44 条硬嵌套输入）")
assert t048_new != t048, "p048 replace failed"
rewrite(p, t048_new)
edits += 1
print("p048 OK")

# p110 — full rewrite (no oMath)
p = paras[110]
t110 = p.text
t110_new = t110.replace(
    "在消融测试集（Ablation Case 01–08）上补充协议 B 控变量对比",
    "在扩展的层次嵌套输入集（原 8 条 Ablation Case + 36 条程序化构造的硬嵌套案例 NESTEXP-01–36，共 44 条）上补充协议 B 控变量对比")
assert t110_new != t110, "p110 replace failed"
rewrite(p, t110_new)
edits += 1
print("p110 OK")

# p112 — HAS oMath, 3 numeric w:t targeted subs
p = paras[112]
wt_sub(p, "8 条输入）", "44 条输入）")
wt_sub(p, "8 条输入共 9 个承载纹理的 motif", "44 条输入共 45 个承载纹理的 motif")
wt_sub(p, "5 条含波浪吊目纹理", "19 条含波浪吊目纹理")
edits += 3
print("p112 (oMath safe) OK")

# p113 — full rewrite (findings paragraph)
p = paras[113]
new_p113 = ("相同 PatternPlan 下（44 条硬嵌套输入、45 个配对 motif），事件级编译在全部输入上保持硬约束零违例"
    "（44/44，V\u2095=0 by construction）；密集周期填充（Plan-Grid）在原始 8 例最难 2 例中出现硬违例"
    "（42/44 V\u2095=0），经 +Repair/+CSP 后恢复全零。"
    "结构指标方面，成组完整率最具区分度：事件级编译在 19 条含波浪吊目纹理的输入上均取得 1.000"
    "（pair guard 整组写入或整组取消），Plan-Grid 为 0.923——配对 Wilcoxon 符号秩检验 p=1.3\u00d710\u207b\u2074、"
    "bootstrap 95% CI (+0.052,+0.104)，差异高度显著。"
    "而 Region IoU（度量生成纹理对期望作用域的覆盖完整度）在扩展集上 Plan-Grid 0.502 高于事件级 0.447"
    "（p=2.7\u00d710\u207b\u2075，反向），原因是密集周期填充天然占满整个作用域从而平凡最大化覆盖指标，"
    "并不代表更强的区域归属能力。"
    "泄漏率方向上利于事件级（0.048 vs 0.062, p=0.60）但不显著。"
    "综合来看，事件级编译的核心优势体现在构造性合法保证与成组完整性（p<1e-3），而非区域覆盖率。")
rewrite(p, new_p113)
edits += 1
print("p113 OK")

# p114 — full rewrite (interpretive paragraph)
p = paras[114]
new_p114 = ("加入 Plan-Grid+CSP 后递进对比链进一步闭合：本组扩展输入上 Plan-Grid 最终输出经画布边缘清理"
    "几乎已处于可行空间（仅原始 8 例最难 2 例需后验修复），CSP 全局投影在 44 例中 42 例为恒等映射。"
    "结合协议 A 中全局投影以最小改动最优消除 Baseline Case 07 残余违例的结果（4.3.1 节），"
    "可区分两类性质不同的差距：合法性差距可由约束求解后验闭合且全局投影比贪心修复更可靠；"
    "而成组完整性差距（1.000 vs 0.923, p=1.3e-4）在任何后验约束处理下保持不变——"
    "配对关系是事件规划阶段的语义决策而非约束满足问题。"
    "这直接检验了以 CSP/ILP 等强约束生成替代事件级编译的可能性：约束模型可以证明并修复合法性，"
    "但成组语义必须由编译过程显式注入。"
    "区域结构差异的色码图可视化对比见补充材料图 S3；Plan-Grid 残留硬违例的规则修复溯源见补充材料 Section K。")
rewrite(p, new_p114)
edits += 1
print("p114 OK")

# p132 — full rewrite (conclusion)
p = paras[132]
new_p132 = ("在第二项核心方法上，事件级约束编译通过逐层语义降低将结构计划与纹理事件转换为规则化动作网格。"
    "基线对比表明直接从自然语言或图像生成完整动作矩阵难以同时保证针迹级合法性与设计语义（4.3.1 节）；"
    "同约束体系下的控变量消融在扩展的 44 条硬嵌套输入上证实：成组完整率显著下降（1.000→0.923, p<0.001）"
    "且最难嵌套案例出现硬约束违例；"
    "与 CP-SAT 全局约束投影强基线的对比进一步区分了两类性质不同的差距——动作合法性可由约束求解后验闭合，"
    "而成组配对语义必须由编译过程显式注入。"
    "保守自修复与结构守卫作为兜底安全网提升高风险输入下的工艺稳定性；"
    "在此保障下方法在非模板化开放输入上生成多类动作组合的动作图而未退化为单一平针填充。")
rewrite(p, new_p132)
edits += 1
print("p132 OK")

# ============================================================
# B. Table 6 rebuild (table index 5 in doc)
# ============================================================
body = doc.element.body
from docx.table import Table as DxTable
tbl_elements = [child for child in body.iterchildren() if child.tag == qn('w:tbl')]
assert len(tbl_elements) >= 6, f"Expected >=6 tables, got {len(tbl_elements)}"
old_tbl_el = tbl_elements[5]
old_tbl = DxTable(old_tbl_el, doc)

VH = 'V\u2095'  # subscript h
VC = 'V\u2099'  # subscript c (actually V_c but using unicode)

new_data = [
    ['Method', 'Mean '+VH+'\u2193', 'Mean '+VH+'=0 cases', 'Region coverage (IoU)', 'Leakage', 'Grouping completeness\u2191', 'p (grouping)'],
    ['Ours (full system)', '0', '44 / 44', '0.447', '0.048', '1.000', 'ref.'],
    ['Plan-Grid (dense)', '0.05', '42 / 44', '0.502', '0.062', '0.923', '1.3\u00d710\u207b\u2074'],
    ['Plan-Grid+Repair', '0.02', '43 / 44', '0.502', '0.062', '0.923', '\u2014'],
    ['Plan-Grid+CSP', '0', '44 / 44', '0.502', '0.062', '0.923', '\u2014'],
]

nrows, ncols = len(new_data), len(new_data[0])
new_tbl = doc.add_table(rows=nrows, cols=ncols)
# style
try: new_tbl.style = doc.styles['Table']
except: pass
# fill
for ri, rowdata in enumerate(new_data):
    for ci, val in enumerate(rowdata):
        cell = new_tbl.cell(ri, ci)
        for para in cell.paragraphs:
            para.alignment = 1  # center
            for run in para.runs:
                run._r.getparent().remove(run._r)
            run = para.add_run(val)
            if ri == 0:
                run.bold = True
# three-line border
from docx.oxml.ns import qn as _qn
def three_line(tbl):
    tblPr = tbl._tbl.tblPr
    for b in tblPr.findall(_qn('w:tblBorders')):
        tblPr.remove(b)
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'bottom'):
        e = OxmlElement('w:' + edge)
        e.set(_qn('w:val'), 'single'); e.set(_qn('w:sz'), '12')
        e.set(_qn('w:space'), '0'); e.set(_qn('w:color'), '000000')
        borders.append(e)
    for edge in ('left', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + edge)
        e.set(_qn('w:val'), 'none'); e.set(_qn('w:sz'), '0')
        e.set(_qn('w:space'), '0'); e.set(_qn('w:color'), 'auto')
        borders.append(e)
    tblPr.append(borders)
    for cell in tbl.rows[0].cells:
        tcPr = cell._tc.get_or_add_tcPr()
        for old in tcPr.findall(_qn('w:tcBorders')):
            tcPr.remove(old)
        tcb = OxmlElement('w:tcBorders')
        b = OxmlElement('w:bottom')
        b.set(_qn('w:val'), 'single'); b.set(_qn('w:sz'), '8')
        b.set(_qn('w:space'), '0'); b.set(_qn('w:color'), '000000')
        tcb.append(b)
        tcPr.append(tcb)

three_line(new_tbl)

# Move new table to old position, delete old
old_tbl_el.addnext(new_tbl._tbl)
old_tbl_el.getparent().remove(old_tbl_el)

# Update caption (should be the paragraph just before the table position)
# Find the caption paragraph by scanning
seq = []
for child in body.iterchildren():
    tag = child.tag.split('}')[-1]
    if tag == 'p':
        seq.append(('p', child))
    elif tag == 'tbl':
        seq.append(('t', child))
tbl_positions = [i for i, (k, _) in enumerate(seq) if k == 't']
target_idx = tbl_positions[5]  # index 5 = 6th table
# Scan backwards for "Table 6" or "表 6" caption
for j in range(target_idx - 1, max(-1, target_idx - 4), -1):
    if seq[j][0] != 'p': continue
    pj = seq[j][1]
    text = ''.join(t.text or '' for t in pj.findall('.//' + qn('w:t')))
    if re.search(r'^Table\s*6\b', text):
        # rewrite caption
        for t in pj.findall('.//' + qn('w:t')):
            if t.text and 'Table 6' in t.text:
                t.text = 'Table 6 Controlled comparison on 44 expanded hierarchical inputs (Wilcoxon paired test).'
                break
        print("Table 6 caption updated")
        break
else:
    print("WARNING: Table 6 caption para not found (may be 表 6 not Table 6)")

# Also update the note below table: "注：表 6..." — the paragraph AFTER the table?
# The current p112 was BEFORE the table, actually let me check. From the grep, p112 is a note starting "注：本表..."
# In the paragraph list, p112 is "Block Text" style. Let me verify it's still at index 112.

print("Table 6 rebuilt")

# ============================================================
# Save
# ============================================================
doc.save(SRC)
print(f"\nOK round8m | {edits} paragraph edits + Table 6 rebuilt")
