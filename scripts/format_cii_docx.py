# -*- coding: utf-8 -*-
"""
format_cii_docx.py — 将 pandoc 生成的中文稿 docx 改造为 Computers in Industry (Elsevier) 投稿版面格式。

依据 Elsevier 通用投稿排版规范：
  - 页面：A4，四边 1 英寸(2.54cm) 页边距，单栏
  - 正文：Times New Roman + 宋体 12pt，双倍行距，两端对齐，首行缩进
  - 章节标题：黑色、加粗、Times New Roman + 黑体；H1(题名)16pt居中 / H2(章)14pt / H3-H4(节)12pt
  - 表格单元格(Compact)：单倍行距 10.5pt，避免随正文双倍而被撑大
  - 图注(Caption)：黑色 TNR+宋体 10.5pt，去斜体去蓝色
  - 图片所在段落：段落级覆盖为居中、单倍、无缩进
  - 连续行号 + 页脚居中页码（Elsevier 评审惯例）

只改“格式”，不改任何文字内容、图表编号、参考文献编号。
运行前请确保已备份（本脚本会在同名 .bak 不存在时自动备份）。
"""
import sys, io, os, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

SRC = sys.argv[1] if len(sys.argv) > 1 else r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'

BODY_ASCII = 'Times New Roman'
BODY_EAST = '宋体'
HEAD_EAST = '黑体'
MONO = 'Consolas'
VML_RECT = '{urn:schemas-microsoft-com:vml}rect'

# ---------------------------------------------------------------- helpers
def _rpr(style):
    return style.element.get_or_add_rPr()

def _ppr(style):
    return style.element.get_or_add_pPr()

def set_fonts(style, ascii_f=BODY_ASCII, east_f=BODY_EAST, drop_theme=True):
    """设置样式字体：ascii/hAnsi/cs=ascii_f，eastAsia=east_f；清除主题字体覆盖。"""
    rpr = _rpr(style)
    # python-docx CT_RPr 提供 get_or_add_rFonts
    try:
        rf = rpr.get_or_add_rFonts()
    except AttributeError:
        rf = rpr.find(qn('w:rFonts'))
        if rf is None:
            rf = OxmlElement('w:rFonts'); rpr.insert(0, rf)
    if drop_theme:
        for a in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
            if rf.get(qn(a)) is not None:
                del rf.attrib[qn(a)]
    rf.set(qn('w:ascii'), ascii_f)
    rf.set(qn('w:hAnsi'), ascii_f)
    rf.set(qn('w:eastAsia'), east_f)
    rf.set(qn('w:cs'), ascii_f)

def clear_color(style):
    """移除样式中的 w:color（含 themeColor），使其回落为自动黑色。"""
    rpr = _rpr(style)
    for c in rpr.findall(qn('w:color')):
        rpr.remove(c)

def set_black(style):
    rpr = _rpr(style)
    for c in rpr.findall(qn('w:color')):
        rpr.remove(c)
    col = OxmlElement('w:color'); col.set(qn('w:val'), '000000')
    # color 需在 rFonts/b/i 之后、sz 之前；用 append 兜底（Word 容错），随后规范化
    rpr.append(col)

def set_first_indent_chars(style, chars=200, twips=480):
    """首行缩进 N 字符（w:firstLineChars，中文习惯），twips 为兼容回退值。"""
    ppr = style.element.get_or_add_pPr()
    ind = ppr.get_or_add_ind()
    ind.set(qn('w:firstLineChars'), str(chars))
    ind.set(qn('w:firstLine'), str(twips))

def pf(style):
    return style.paragraph_format

def style_by_id(doc, sid):
    for s in doc.styles:
        if s.style_id == sid:
            return s
    return None

# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) < 2 and not os.path.exists(SRC + '.bak'):
        shutil.copy2(SRC, SRC + '.bak')
        print('已自动备份 ->', SRC + '.bak')

    doc = Document(SRC)

    # ---- 1. docDefaults：全局默认字体 TNR+宋体 12pt，单倍行距基线 ----
    styles_el = doc.styles.element
    docDefaults = styles_el.find(qn('w:docDefaults'))
    if docDefaults is not None:
        rprd = docDefaults.find(qn('w:rPrDefault'))
        if rprd is not None:
            rpr = rprd.find(qn('w:rPr'))
            if rpr is None:
                rpr = OxmlElement('w:rPr'); rprd.append(rpr)
            rf = rpr.find(qn('w:rFonts'))
            if rf is None:
                rf = OxmlElement('w:rFonts'); rpr.insert(0, rf)
            for a in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
                if rf.get(qn(a)) is not None:
                    del rf.attrib[qn(a)]
            rf.set(qn('w:ascii'), BODY_ASCII); rf.set(qn('w:hAnsi'), BODY_ASCII)
            rf.set(qn('w:eastAsia'), BODY_EAST); rf.set(qn('w:cs'), BODY_ASCII)
            for tag, val in (('w:sz', '24'), ('w:szCs', '24')):
                e = rpr.find(qn(tag))
                if e is None:
                    e = OxmlElement(tag); rpr.append(e)
                e.set(qn('w:val'), val)
        # 段落默认：after=0（行距交由各样式控制）
        pprd = docDefaults.find(qn('w:pPrDefault'))
        if pprd is not None:
            ppr = pprd.find(qn('w:pPr'))
            if ppr is not None:
                sp = ppr.find(qn('w:spacing'))
                if sp is None:
                    sp = OxmlElement('w:spacing'); ppr.append(sp)
                sp.set(qn('w:after'), '0')

    # ---- 2. 正文样式：Normal / BodyText / FirstParagraph ----
    normal = style_by_id(doc, 'Normal')
    if normal:
        set_fonts(normal, BODY_ASCII, BODY_EAST); clear_color(normal)
        normal.font.size = Pt(12)
        p = pf(normal)
        p.line_spacing = 1.0            # Normal 仅承载图片段，单倍
        p.space_before = Pt(0); p.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT   # 图片段的居中由步骤8段落级覆盖

    body = style_by_id(doc, 'BodyText')
    if body:
        set_fonts(body, BODY_ASCII, BODY_EAST); clear_color(body)
        body.font.size = Pt(12)
        p = pf(body)
        p.line_spacing = 1.0            # 单倍行距
        p.space_before = Pt(0); p.space_after = Pt(6)   # 段后空
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_first_indent_chars(body, 200)   # 首行缩进 2 字符

    first = style_by_id(doc, 'FirstParagraph')
    if first:
        set_fonts(first, BODY_ASCII, BODY_EAST); clear_color(first)
        first.font.size = Pt(12)
        p = pf(first)
        p.line_spacing = 1.0
        p.space_before = Pt(0); p.space_after = Pt(6)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_first_indent_chars(first, 200)  # 中文习惯：段首亦缩进 2 字符

    # ---- 3. 标题样式：黑色 TNR+黑体，加粗，层级字号 ----
    head_spec = {
        'Heading1': (16, WD_ALIGN_PARAGRAPH.CENTER, False, 12, 12),   # 题名
        'Heading2': (14, WD_ALIGN_PARAGRAPH.LEFT,   False, 18, 6),    # 章
        'Heading3': (12, WD_ALIGN_PARAGRAPH.LEFT,   False, 12, 6),    # 节
        'Heading4': (12, WD_ALIGN_PARAGRAPH.LEFT,   True,  12, 6),    # 小节(斜体)
        'Heading5': (12, WD_ALIGN_PARAGRAPH.LEFT,   True,  12, 6),
        'Heading6': (12, WD_ALIGN_PARAGRAPH.LEFT,   False, 12, 6),
        'Heading7': (12, WD_ALIGN_PARAGRAPH.LEFT,   False, 12, 6),
        'Heading8': (12, WD_ALIGN_PARAGRAPH.LEFT,   False, 12, 6),
        'Heading9': (12, WD_ALIGN_PARAGRAPH.LEFT,   False, 12, 6),
    }
    for sid, (sz, align, italic, before, after) in head_spec.items():
        st = style_by_id(doc, sid)
        if not st:
            continue
        set_fonts(st, BODY_ASCII, HEAD_EAST); clear_color(st)
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.italic = italic
        p = pf(st)
        p.line_spacing = 1.0
        p.space_before = Pt(before); p.space_after = Pt(after)
        p.alignment = align
        p.first_line_indent = Cm(0)
        p.keep_with_next = True

    # Title / Subtitle（备用，虽未使用）去蓝改黑
    for sid in ('Title', 'Subtitle', 'AbstractTitle', 'TOCHeading'):
        st = style_by_id(doc, sid)
        if st:
            set_fonts(st, BODY_ASCII, HEAD_EAST); clear_color(st)

    # ---- 4. 表格单元格 Compact：单倍 10.5pt，覆盖 BodyText 双倍继承 ----
    compact = style_by_id(doc, 'Compact')
    if compact:
        set_fonts(compact, BODY_ASCII, BODY_EAST); clear_color(compact)
        compact.font.size = Pt(10.5)
        p = pf(compact)
        p.line_spacing = 1.0
        p.space_before = Pt(1); p.space_after = Pt(1)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.first_line_indent = Cm(0)

    # ---- 5. 图注 / 表注 Caption：黑色 TNR+宋体 10.5pt，去斜体 ----
    for sid in ('Caption', 'ImageCaption', 'TableCaption'):
        st = style_by_id(doc, sid)
        if st:
            set_fonts(st, BODY_ASCII, BODY_EAST); clear_color(st)
            st.font.size = Pt(10.5)
            st.font.italic = False
            p = pf(st)
            p.line_spacing = 1.0
            p.space_before = Pt(4); p.space_after = Pt(4)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ---- 6. 引用块 BlockText / 代码 SourceCode ----
    bt = style_by_id(doc, 'BlockText')
    if bt:
        set_fonts(bt, BODY_ASCII, BODY_EAST); clear_color(bt)
        bt.font.size = Pt(12)
        p = pf(bt)
        p.line_spacing = 1.0
        p.space_before = Pt(6); p.space_after = Pt(6)
    sc = style_by_id(doc, 'SourceCode')
    if sc:
        set_fonts(sc, MONO, BODY_EAST); clear_color(sc)
        sc.font.size = Pt(10)
        p = pf(sc); p.line_spacing = 1.0
    vc = style_by_id(doc, 'VerbatimChar')
    if vc:
        set_fonts(vc, MONO, MONO)
        vc.font.size = Pt(10)

    # ---- 7. 参考文献 Bibliography：悬挂缩进、单倍（便于阅读） ----
    bib = style_by_id(doc, 'Bibliography')
    if bib:
        set_fonts(bib, BODY_ASCII, BODY_EAST); clear_color(bib)
        bib.font.size = Pt(12)
        p = pf(bib)
        p.line_spacing = 1.0
        p.space_before = Pt(0); p.space_after = Pt(6)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # ---- 7.5 删除 pandoc 水平分隔线伪影（空段 + w:pict + v:rect，非真实图件）----
    removed = 0
    for para in list(doc.paragraphs):
        pel = para._p
        if (para.text.strip() == ''
                and pel.findall('.//' + qn('w:pict'))
                and not pel.findall('.//' + qn('w:drawing'))
                and pel.findall('.//' + VML_RECT)):
            pel.getparent().remove(pel)
            removed += 1
    print('已删除 pandoc 水平分隔线:', removed)

    # ---- 8. 段落级：图片所在段落居中、单倍、无缩进 ----
    img_fixed = 0
    for para in doc.paragraphs:
        pel = para._p
        if pel.findall('.//' + qn('w:drawing')) or pel.findall('.//' + qn('w:pict')):
            p = para.paragraph_format
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.line_spacing = 1.0
            p.first_line_indent = Cm(0)
            p.space_before = Pt(6); p.space_after = Pt(6)
            img_fixed += 1
    print('图片段落已居中/单倍处理:', img_fixed)

    # ---- 9. 页面设置：A4 + 1英寸边距 + 连续行号 + 页脚页码 ----
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.54); sec.right_margin = Cm(2.54)
    sec.top_margin = Cm(2.54); sec.bottom_margin = Cm(2.54)
    sec.header_distance = Cm(1.27); sec.footer_distance = Cm(1.27)

    sectPr = sec._sectPr
    # （应用户要求不加行号）

    # 页脚页码（PAGE 域，居中，TNR 10pt）
    footer = sec.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    # 清空既有 run
    for r in list(fp.runs):
        r._r.getparent().remove(r._r)
    run = fp.add_run()
    run.font.name = BODY_ASCII; run.font.size = Pt(10)
    fld1 = OxmlElement('w:fldChar'); fld1.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve'); instr.text = ' PAGE '
    fld2 = OxmlElement('w:fldChar'); fld2.set(qn('w:fldCharType'), 'end')
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)
    print('已注入页脚页码域')

    # ---- 9.5 补 compatibilityMode=15，避免 Word 兼容模式渲染 ----
    settings = doc.settings.element
    if settings.find(qn('w:compat')) is None:
        compat = OxmlElement('w:compat')
        cs = OxmlElement('w:compatSetting')
        cs.set(qn('w:name'), 'compatibilityMode')
        cs.set(qn('w:uri'), 'http://schemas.microsoft.com/office/word')
        cs.set(qn('w:val'), '15')
        compat.append(cs)
        settings.append(compat)
        print('已补 compatibilityMode=15')

    doc.save(SRC)
    print('已保存 ->', SRC)

if __name__ == '__main__':
    main()
