# -*- coding: utf-8 -*-
"""
format_thesis_docx.py — 将 pandoc 导出的 docs/论文初稿.docx 重排为中文权威顶刊（《计算机学报》《自动化学报》类）标准格式，
输出 docs/论文初稿_排版.docx（原文件不动）。

排版规格（中文顶刊单栏规范）：
  页面        A4，页边距上下左右均 2.5cm；首页无页码，正文起底部居中编号（pgNumType start=0）
  论文标题    黑体二号(22pt) 加粗居中
  一级标题    黑体小四(12pt) 加粗左排（章）
  二级标题    黑体五号(10.5pt) 加粗左排（节）
  三级标题    宋体五号 加粗左排（小节）
  正文        宋体/Times New Roman 五号(10.5pt)，1.5 倍行距，首行缩进 2 字符，两端对齐，段间不空行
  摘要/关键词  宋体五号；“摘要：”“关键词：”标签黑体加粗（行内标签，无独立摘要标题）
  表格        三线表，整表居中；表内文字小五(9pt)居中单倍行距
  图          居中，宽度压至版心(5274000 EMU)内等比缩放
  图/表题注   小五居中（表题在上、图题在下；md 已有题注段落，按“首 run 加粗 + 图/表编号开头”识别）
  显示公式    段落居中、无首行缩进（变量斜体由 OMML 自带）
  参考文献    小五，悬挂缩进
  代码        Consolas 9pt，浅灰底纹
  标题段前段后 0.5 行（beforeLines/afterLines=50）
"""
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(r'e:\DeskTop\knitting_pattern_generator')
SRC = REPO / 'docs' / '论文初稿.docx'
DST = REPO / 'docs' / '论文初稿_送审版.docx'
WORK = Path(__file__).resolve().parent / '_docx_fmt_work'

MAX_CX = 5274000  # A4 版心宽（EMU），页边距左右各 1417 twip(2.5cm)

SONG = '宋体'
HEI = '黑体'
FONTS_BODY = ('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
              f'w:eastAsia="{SONG}" w:cs="Times New Roman"/>')
FONTS_HEI = ('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
             f'w:eastAsia="{HEI}" w:cs="Times New Roman"/>')

stat = {'cap': 0, 'fig': 0, 'math': 0, 'bib': 0, 'abs': 0, 'tblhdr': 0, 'imgclamp': 0, 'hr': 0}


# ---------------------------------------------------------------- styles.xml
def rewrite_styles(st: str) -> str:
    def rep_style(xml: str, sid: str, new: str) -> str:
        pat = re.compile(r'<w:style\b[^>]*w:styleId="%s".*?</w:style>' % sid, re.S)
        if not pat.search(xml):
            print('WARN: style not found:', sid)
            return xml
        return pat.sub(lambda m: new, xml, count=1)

    st = re.sub(
        r'<w:docDefaults>.*?</w:docDefaults>',
        lambda m: ('<w:docDefaults><w:rPrDefault><w:rPr>' + FONTS_BODY +
                   '<w:sz w:val="21"/><w:szCs w:val="21"/>'
                   '<w:lang w:bidi="ar-SA" w:eastAsia="zh-CN" w:val="en-US"/>'
                   '</w:rPr></w:rPrDefault>'
                   '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
                   '</w:docDefaults>'),
        st, count=1, flags=re.S)

    st = rep_style(st, 'Normal',
        '<w:style w:default="1" w:styleId="Normal" w:type="paragraph">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style>')

    st = rep_style(st, 'BodyText',
        '<w:style w:styleId="BodyText" w:type="paragraph"><w:name w:val="Body Text"/>'
        '<w:basedOn w:val="Normal"/><w:link w:val="BodyTextChar"/>'
        '<w:pPr><w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/>'
        '<w:ind w:firstLine="480" w:firstLineChars="200"/><w:jc w:val="both"/></w:pPr>'
        '<w:qFormat/></w:style>')

    st = rep_style(st, 'FirstParagraph',
        '<w:style w:customStyle="1" w:styleId="FirstParagraph" w:type="paragraph">'
        '<w:name w:val="First Paragraph"/><w:basedOn w:val="BodyText"/>'
        '<w:next w:val="BodyText"/><w:qFormat/></w:style>')

    st = rep_style(st, 'Compact',
        '<w:style w:customStyle="1" w:styleId="Compact" w:type="paragraph">'
        '<w:name w:val="Compact"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/>'
        '<w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>'
        '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    st = rep_style(st, 'Heading1',
        '<w:style w:styleId="Heading1" w:type="paragraph"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:before="0" w:after="0" w:beforeLines="0" w:afterLines="100" w:line="360" w:lineRule="auto"/>'
        '<w:outlineLvl w:val="0"/><w:jc w:val="center"/></w:pPr>'
        '<w:rPr>' + FONTS_HEI + '<w:b/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>')

    st = rep_style(st, 'Heading2',
        '<w:style w:styleId="Heading2" w:type="paragraph"><w:name w:val="heading 2"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:beforeLines="50" w:afterLines="50" w:line="360" w:lineRule="auto"/>'
        '<w:outlineLvl w:val="1"/><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
        '<w:rPr>' + FONTS_HEI + '<w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>')

    st = rep_style(st, 'Heading3',
        '<w:style w:styleId="Heading3" w:type="paragraph"><w:name w:val="heading 3"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:beforeLines="50" w:afterLines="50" w:line="360" w:lineRule="auto"/>'
        '<w:outlineLvl w:val="2"/><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
        '<w:rPr>' + FONTS_HEI + '<w:b/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')

    st = rep_style(st, 'Heading4',
        '<w:style w:styleId="Heading4" w:type="paragraph"><w:name w:val="heading 4"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:beforeLines="50" w:afterLines="50" w:line="360" w:lineRule="auto"/>'
        '<w:outlineLvl w:val="3"/><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
        '<w:rPr>' + FONTS_BODY + '<w:b/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')

    st = rep_style(st, 'SourceCode',
        '<w:style w:styleId="SourceCode" w:type="paragraph"><w:name w:val="Source Code"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/>'
        '<w:ind w:left="420" w:firstLine="0"/><w:shd w:val="clear" w:color="auto" w:fill="F5F5F5"/></w:pPr>'
        '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="' + SONG + '"/>'
        '<w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    st = rep_style(st, 'BlockText',
        '<w:style w:styleId="BlockText" w:type="paragraph"><w:name w:val="Block Text"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:before="40" w:after="120" w:line="240" w:lineRule="auto"/>'
        '<w:ind w:firstLine="0" w:left="0"/><w:jc w:val="both"/></w:pPr>'
        '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    # 题注：小五居中（不加粗样式级 b，保留 run 级已有加粗）
    st = rep_style(st, 'Caption',
        '<w:style w:styleId="Caption" w:type="paragraph"><w:name w:val="caption"/>'
        '<w:basedOn w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:spacing w:before="80" w:after="80" w:line="240" w:lineRule="auto"/>'
        '<w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>'
        '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    st = rep_style(st, 'Bibliography',
        '<w:style w:styleId="Bibliography" w:type="paragraph"><w:name w:val="Bibliography"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:before="0" w:after="40" w:line="300" w:lineRule="auto"/>'
        '<w:ind w:left="360" w:hanging="360" w:firstLine="0"/><w:jc w:val="left"/></w:pPr>'
        '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    st = rep_style(st, 'VerbatimChar',
        '<w:style w:customStyle="1" w:styleId="VerbatimChar" w:type="character">'
        '<w:name w:val="Verbatim Char"/><w:basedOn w:val="DefaultParagraphFont"/>'
        '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="' + SONG + '"/>'
        '<w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    st = rep_style(st, 'FootnoteText',
        '<w:style w:styleId="FootnoteText" w:type="paragraph"><w:name w:val="footnote text"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
        '<w:ind w:firstLine="0"/></w:pPr>'
        '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

    # 三线表样式
    three_line = ('<w:tblBorders>'
                  '<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                  '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                  '<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                  '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                  '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                  '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                  '</w:tblBorders>')
    cell_mar = ('<w:tblCellMar><w:top w:type="dxa" w:w="30"/><w:left w:type="dxa" w:w="80"/>'
                '<w:bottom w:type="dxa" w:w="30"/><w:right w:type="dxa" w:w="80"/></w:tblCellMar>')
    st = rep_style(st, 'Table',
        '<w:style w:styleId="Table" w:type="table"><w:name w:val="Table"/><w:qFormat/>'
        '<w:tblPr>' + three_line + cell_mar + '</w:tblPr>'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr></w:style>')

    # 摘要正文（行内“摘要：”黑体标签由 document 转换插入，无独立摘要标题；左右各缩进 2 字符以区隔正文）
    new_styles = (
        '<w:style w:customStyle="1" w:styleId="AbsBody" w:type="paragraph">'
        '<w:name w:val="Abstract Body"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/>'
        '<w:ind w:left="420" w:leftChars="200" w:right="420" w:rightChars="200" '
        'w:firstLine="420" w:firstLineChars="200"/><w:jc w:val="both"/></w:pPr>'
        '<w:rPr><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')
    if 'w:styleId="AbsBody"' not in st:
        st = st.replace('</w:styles>', new_styles + '</w:styles>')
    return st


# ------------------------------------------------------------- document.xml
NODE_RX = re.compile(r'<w:tbl>.*?</w:tbl>|<w:p>.*?</w:p>|<w:p [^>]*>.*?</w:p>', re.S)
PSTYLE_RX = re.compile(r'<w:pStyle w:val="([^"]+)"\s*/>')
TEXT_RX = re.compile(r'<w:t[^>]*>([^<]*)</w:t>')
CAP_RX = re.compile(r'^[图表]\s*S?\d')
BIB_RX = re.compile(r'^\[\d+\]')


def ptext(s: str) -> str:
    return ''.join(TEXT_RX.findall(s)).strip()


def first_run_bold(s: str) -> bool:
    m = re.search(r'<w:r>.*?</w:r>', s, re.S)
    return bool(m and ('<w:b/>' in m.group(0) or '<w:b />' in m.group(0)))


def center_no_indent(s: str, style: str, keep_next: bool = False) -> str:
    """pPr 内追加居中 + 取消首行缩进（用于图片段 / 显示公式段）；keep_next 使图与图注同页。"""
    extra = '<w:keepNext/>' if keep_next else ''
    old = '<w:pStyle w:val="%s" />' % style
    new = (old + extra + '<w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/>')
    if old + '</w:pPr>' in s:
        return s.replace(old + '</w:pPr>', new + '</w:pPr>', 1)
    # pPr 内已有其他属性的兜底：在 </w:pPr> 前插入
    return re.sub(r'</w:pPr>', extra + '<w:ind w:firstLine="0" w:firstLineChars="0"/>'
                  r'<w:jc w:val="center"/></w:pPr>', s, count=1)


def switch_style(s: str, old: str, new: str) -> str:
    return s.replace('<w:pStyle w:val="%s" />' % old, '<w:pStyle w:val="%s" />' % new, 1)


HEI_BOLD_RPR = ('<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
                'w:eastAsia="' + HEI + '" w:cs="Times New Roman"/><w:b/><w:bCs/></w:rPr>')
ABS_LABEL_RUN = '<w:r>' + HEI_BOLD_RPR + '<w:t>摘要：</w:t></w:r>'


def hei_bold_label(s: str) -> str:
    """关键词段首 run 的加粗 rPr 换为黑体加粗（标签黑体化）。"""
    m = re.search(r'<w:r><w:rPr>(?:(?!</w:rPr>).)*?<w:b\s*/>(?:(?!</w:rPr>).)*?</w:rPr>', s, re.S)
    if m:
        return s[:m.start()] + '<w:r>' + HEI_BOLD_RPR + s[m.end():]
    return s


def three_line_header(tbl: str) -> str:
    """表格首行单元格加下边线（三线表头线）。"""
    tr_end = tbl.find('</w:tr>')
    if tr_end < 0:
        return tbl
    head, rest = tbl[:tr_end], tbl[tr_end:]
    border = ('<w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>')
    head2 = head.replace('<w:tcPr />', '<w:tcPr>' + border + '</w:tcPr>')
    head2 = head2.replace('<w:tcPr/>', '<w:tcPr>' + border + '</w:tcPr>')
    if head2 == head and border not in head:
        head2 = head.replace('<w:tcPr>', '<w:tcPr>' + border)
    if head2 != head:
        stat['tblhdr'] += 1
    return head2 + rest


def transform_document(doc: str) -> str:
    # 表格单元格段落：显式 left -> center
    doc = doc.replace('<w:pStyle w:val="Compact" /><w:jc w:val="left" />',
                      '<w:pStyle w:val="Compact" /><w:jc w:val="center" />')
    # 表格整体居中
    doc = doc.replace('<w:jc w:val="start" /></w:tblPr>', '<w:jc w:val="center" /></w:tblPr>')

    matches = list(NODE_RX.finditer(doc))
    nodes = []
    for m in matches:
        s = m.group(0)
        st_m = PSTYLE_RX.search(s)
        nodes.append({
            'is_tbl': s.startswith('<w:tbl>'),
            'draw': '<w:drawing>' in s,
            'math': '<m:oMathPara' in s,
            'style': st_m.group(1) if st_m else '',
            'text': ptext(s),
            'bold': first_run_bold(s),
        })

    ref_idx = abs_idx = kw_idx = -1
    for i, n in enumerate(nodes):
        if n['style'] == 'Heading2' and n['text'] == '参考文献':
            ref_idx = i
        if n['style'] == 'Heading2' and n['text'] == '摘要' and abs_idx < 0:
            abs_idx = i
    if abs_idx >= 0:
        for i in range(abs_idx + 1, len(nodes)):
            if nodes[i]['text'].startswith('关键词'):
                kw_idx = i
                break
    print('nodes=%d refIdx=%d absIdx=%d kwIdx=%d' % (len(nodes), ref_idx, abs_idx, kw_idx))

    out, pos, ctr = [], 0, 0
    for m in matches:
        s = m.group(0)
        n = nodes[ctr]
        ctr += 1
        out.append(doc[pos:m.start()])
        pos = m.end()

        if n['is_tbl']:
            out.append(three_line_header(s))
            continue

        if n['style'] in ('BodyText', 'FirstParagraph'):
            if '<w:pict>' in s and not n['draw']:
                # pandoc 分隔线（灰色横条）：删除以提升观感
                stat['hr'] += 1
                out.append('')
                continue
            if n['draw']:
                stat['fig'] += 1
                out.append(center_no_indent(s, n['style'], keep_next=True))
                continue
            if n['math']:
                stat['math'] += 1
                out.append(center_no_indent(s, n['style']))
                continue
            if n['bold'] and CAP_RX.match(n['text']):
                stat['cap'] += 1
                s2 = switch_style(s, n['style'], 'Caption')
                # 表题在上：题注后紧跟表格时 keepNext 防止表题孤行
                if ctr < len(nodes) and nodes[ctr]['is_tbl']:
                    s2 = s2.replace('</w:pPr>', '<w:keepNext/></w:pPr>', 1)
                out.append(s2)
                continue
            if ref_idx >= 0 and ctr - 1 > ref_idx and BIB_RX.match(n['text']):
                stat['bib'] += 1
                out.append(switch_style(s, n['style'], 'Bibliography'))
                continue
            if abs_idx >= 0 and kw_idx >= 0 and abs_idx < ctr - 1 <= kw_idx:
                stat['abs'] += 1
                s2 = switch_style(s, n['style'], 'AbsBody')
                if ctr - 1 == abs_idx + 1:
                    # 首段插入行内“摘要：”黑体标签
                    s2 = s2.replace('</w:pPr>', '</w:pPr>' + ABS_LABEL_RUN, 1)
                if ctr - 1 == kw_idx:
                    s2 = hei_bold_label(s2)
                out.append(s2)
                continue
        if n['style'] == 'Heading2' and abs_idx >= 0 and ctr - 1 == abs_idx:
            stat['abs'] += 1
            out.append('')  # 删除独立摘要标题，改为行内标签
            continue
        out.append(s)

    out.append(doc[pos:])
    doc = ''.join(out)

    # 图片超宽等比压缩至版心
    def clamp(m):
        cx, cy = int(m.group(1)), int(m.group(2))
        if cx > MAX_CX:
            stat['imgclamp'] += 1
            return 'cx="%d" cy="%d"' % (MAX_CX, round(cy * MAX_CX / cx))
        return m.group(0)

    doc = re.sub(r'cx="(\d+)" cy="(\d+)"', clamp, doc)

    # 页面设置：A4 + 页边距 2.5cm + 首页无页码 + 页脚页码
    sect = ('<w:sectPr>'
            '<w:footerReference w:type="first" r:id="rIdFtrFirst"/>'
            '<w:footerReference w:type="default" r:id="rIdFtrPg"/>'
            '<w:pgSz w:h="16838" w:w="11906"/>'
            '<w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417" '
            'w:header="851" w:footer="992" w:gutter="0"/>'
            '<w:pgNumType w:start="0"/>'
            '<w:cols w:space="425"/>'
            '<w:titlePg/>'
            '</w:sectPr>')
    # pandoc 3.9 输出带子元素的 <w:sectPr>…</w:sectPr>；旧版为自闭合 <w:sectPr />
    doc, n_sub = re.subn(r'<w:sectPr(?:(?!</w:sectPr>).)*</w:sectPr>', sect, doc, count=1, flags=re.S)
    if n_sub == 0:
        doc = re.sub(r'<w:sectPr\s*/>', sect, doc, count=1)
    return doc


FOOTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
          '<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>'
          '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
          '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
          '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
          '</w:p></w:ftr>')

FOOTER_FIRST = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:p></w:ftr>')


def main():
    if not SRC.exists():
        sys.exit('missing source: %s' % SRC)
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    with zipfile.ZipFile(SRC) as z:
        names = z.namelist()
        z.extractall(WORK)

    sp = WORK / 'word' / 'styles.xml'
    sp.write_text(rewrite_styles(sp.read_text(encoding='utf-8')), encoding='utf-8')
    print('styles.xml rewritten')

    dp = WORK / 'word' / 'document.xml'
    dp.write_text(transform_document(dp.read_text(encoding='utf-8')), encoding='utf-8')
    print('document.xml rewritten:', stat)

    (WORK / 'word' / 'footer1.xml').write_text(FOOTER, encoding='utf-8')
    (WORK / 'word' / 'footer2.xml').write_text(FOOTER_FIRST, encoding='utf-8')

    rp = WORK / 'word' / '_rels' / 'document.xml.rels'
    rels = rp.read_text(encoding='utf-8')
    if 'rIdFtrPg' not in rels:
        rels = rels.replace(
            '</Relationships>',
            '<Relationship Id="rIdFtrPg" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/footer" Target="footer1.xml"/>'
            '<Relationship Id="rIdFtrFirst" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/footer" Target="footer2.xml"/></Relationships>')
        rp.write_text(rels, encoding='utf-8')

    cp = WORK / '[Content_Types].xml'
    ct = cp.read_text(encoding='utf-8')
    if 'footer1.xml' not in ct:
        ct = ct.replace(
            '</Types>',
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/word/footer2.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.footer+xml"/></Types>')
        cp.write_text(ct, encoding='utf-8')
    print('footer parts added')

    # settings.xml：声明 compatibilityMode=15（现代排版引擎，避免 Word 以兼容性模式渲染）
    stp = WORK / 'word' / 'settings.xml'
    settings = stp.read_text(encoding='utf-8')
    m_compat = re.search(r'<w:compatSetting w:name="compatibilityMode"[^>]*/>', settings)
    if m_compat:
        if 'w:val="15"' not in m_compat.group(0):
            settings = settings.replace(m_compat.group(0),
                '<w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>')
    elif '<w:compat>' in settings:
        settings = settings.replace('<w:compat>',
            '<w:compat><w:compatSetting w:name="compatibilityMode" '
            'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>', 1)
    else:
        settings = settings.replace('</w:settings>',
            '<w:compat><w:compatSetting w:name="compatibilityMode" '
            'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')
    stp.write_text(settings, encoding='utf-8')
    print('settings.xml compatibilityMode=15')

    # 良构校验
    for f in ['word/document.xml', 'word/styles.xml', 'word/footer1.xml', 'word/footer2.xml',
              'word/settings.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml']:
        ET.parse(WORK / f)
    print('xml well-formed OK')

    # 重新打包（保持原 zip 的条目顺序，[Content_Types].xml 在最前）
    dst = DST
    try:
        f_out = open(dst, 'wb')
        f_out.close()
    except PermissionError:
        dst = DST.with_name(DST.stem + '_新版.docx')
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        ordered = [n for n in names]
        for f in sorted(WORK.rglob('*')):
            if f.is_file():
                rel = f.relative_to(WORK).as_posix()
                if rel not in ordered:
                    ordered.append(rel)
        for rel in ordered:
            zout.write(WORK / rel, rel)
    print('written:', dst, dst.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
