# -*- coding: utf-8 -*-
"""论文初稿.docx（Word 往返存盘版）→ 论文初稿_送审版.docx 美观精修。

在既有顶刊规格（A4/2.5cm/黑体标题/五号正文/三线表/小五题注与文献）之上做观感精修：
 1) 删除 pandoc 分隔线灰条（w:pict 横线段）；
 2) 悬空表题（表题与表之间仅隔正文/表注段落）移至表正上方，表注(ab)移至表正下方；
 3) 摘要块（Abstract Body）左右各缩进 2 字符，与正文形成层次区隔；
 4) 图片段 keepNext（图与图注同页）；紧邻表格的表题 keepNext（防表题孤行）；
 5) 论文标题（heading 1）段后 1 行呼吸空间，清除段落直接 spacing；
 6) settings.xml 声明 compatibilityMode=15（现代排版引擎）。
样式 ID 已被 Word 匿名化，全部按 w:name 映射定位。
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
WORK = Path(__file__).resolve().parent / '_polish_work'

stat = {'hr': 0, 'capmove': 0, 'notemove': 0, 'keepnext_fig': 0, 'keepnext_cap': 0}

NODE_RX = re.compile(r'<w:tbl>.*?</w:tbl>|<w:p\b[^>]*>.*?</w:p>', re.S)
CAP_TBL_RX = re.compile(r'^表\s*S?\d')
CAP_ANY_RX = re.compile(r'^[图表]\s*S?\d')


def ptext(s: str) -> str:
    return ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', s))


def pstyle(s: str) -> str:
    m = re.search(r'<w:pStyle w:val="([^"]+)"', s)
    return m.group(1) if m else ''


# ---------------------------------------------------------------- styles.xml
def rewrite_styles(st: str) -> str:
    # 摘要块左右各缩进 2 字符（与正文区隔，期刊摘要惯例）
    st = st.replace(
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="AbstractBody">'
        '<w:name w:val="Abstract Body"/><w:basedOn w:val="a"/><w:qFormat/>'
        '<w:pPr><w:ind w:firstLineChars="200" w:firstLine="420"/><w:jc w:val="both"/></w:pPr>',
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="AbstractBody">'
        '<w:name w:val="Abstract Body"/><w:basedOn w:val="a"/><w:qFormat/>'
        '<w:pPr><w:ind w:left="420" w:leftChars="200" w:right="420" w:rightChars="200" '
        'w:firstLine="420" w:firstLineChars="200"/><w:jc w:val="both"/></w:pPr>')
    # 论文标题（heading 1，全文仅 1 处）：段前 0、段后 1 行，给标题呼吸空间
    st = st.replace(
        '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="a"/><w:next w:val="a0"/><w:link w:val="10"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:beforeLines="50" w:afterLines="50"/>',
        '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="a"/><w:next w:val="a0"/><w:link w:val="10"/><w:qFormat/>'
        '<w:pPr><w:keepNext/><w:spacing w:before="0" w:after="0" w:beforeLines="0" w:afterLines="100"/>')
    return st


# ---------------------------------------------------------------- document.xml
def add_keep_next(s: str) -> str:
    if '<w:keepNext' in s:
        return s
    if '<w:pPr>' in s:
        return s.replace('<w:pPr>', '<w:pPr><w:keepNext/>', 1)
    return s


def transform_document(doc: str) -> str:
    spans = list(NODE_RX.finditer(doc))
    nodes = [{'tbl': m.group(0).startswith('<w:tbl>'), 's': m.group(0),
              'st': m.start(), 'en': m.end()} for m in spans]
    # 节点间应无游离文本（书签等均在段内）；尾部为 sectPr…</w:document>
    gaps = [doc[nodes[k]['en']:nodes[k + 1]['st']] for k in range(len(nodes) - 1)]
    if any(g.strip() for g in gaps):
        sys.exit('unexpected text between body nodes: %r' % next(g for g in gaps if g.strip()))
    head = doc[:nodes[0]['st']]
    tail = doc[nodes[-1]['en']:]

    # ---- 1) 删除分隔线灰条段
    kept = []
    for n in nodes:
        if not n['tbl'] and '<w:pict' in n['s'] and '<w:drawing' not in n['s']:
            stat['hr'] += 1
            continue
        kept.append(n)
    nodes = kept

    # ---- 2) 悬空表题归位：表题与表之间仅隔 a0/ab 段落（不得跨其他题注/图）
    move_cap = {}   # 表题节点 id -> 目标表节点 id
    move_note = {}  # 表注节点 id -> 目标表节点 id（移至表后）
    ids = [id(n) for n in nodes]
    for i, n in enumerate(nodes):
        if n['tbl'] or pstyle(n['s']) != 'ad':
            continue
        t = ptext(n['s']).strip()
        if not CAP_TBL_RX.match(t):
            continue
        j = i + 1
        while j < len(nodes) and not nodes[j]['tbl']:
            j += 1
        if j >= len(nodes) or j == i + 1:
            continue
        mid = nodes[i + 1:j]
        if any(pstyle(x['s']) == 'ad' or '<w:drawing' in x['s'] for x in mid):
            continue  # 中间夹其他题注/图：结构歧义，不动
        if any(pstyle(x['s']) not in ('a0', 'ab', '') for x in mid):
            continue
        move_cap[ids[i]] = ids[j]
        stat['capmove'] += 1
        for x in mid:
            if pstyle(x['s']) == 'ab':
                move_note[id(x)] = ids[j]
                stat['notemove'] += 1

    rebuilt = []
    pending_caps = []   # 待插入到下一表之前的表题
    pending_notes = []  # 待追加到上一表之后的表注
    for n in nodes:
        nid = id(n)
        if nid in move_cap:
            pending_caps.append(n['s'])
            continue
        if nid in move_note:
            pending_notes.append(n['s'])
            continue
        if n['tbl']:
            rebuilt.extend(pending_caps)
            pending_caps = []
            rebuilt.append(n['s'])
            rebuilt.extend(pending_notes)
            pending_notes = []
            continue
        rebuilt.append(n['s'])
    rebuilt.extend(pending_caps)
    rebuilt.extend(pending_notes)

    # ---- 3) keepNext：图片段（图与图注同页）；紧邻表格的表题（防孤行）
    out = []
    for k, s in enumerate(rebuilt):
        is_tbl = s.startswith('<w:tbl>')
        # 关键词行：取消左右缩进（直接格式覆盖样式），避免末字孤行
        if not is_tbl and pstyle(s) == 'AbstractBody' and ptext(s).strip().startswith('关键词'):
            kw_ind = ('<w:ind w:left="0" w:leftChars="0" w:right="0" w:rightChars="0" '
                      'w:firstLine="420" w:firstLineChars="200"/>')
            m_ind = re.search(r'<w:ind\b[^>]*/>', s)
            if m_ind:
                s = s[:m_ind.start()] + kw_ind + s[m_ind.end():]
            else:
                s = s.replace('<w:pStyle w:val="AbstractBody"/>',
                              '<w:pStyle w:val="AbstractBody"/>' + kw_ind, 1)
            stat['kw'] = stat.get('kw', 0) + 1
        if not is_tbl and '<w:drawing' in s and '<w:keepNext' not in s:
            s = add_keep_next(s)
            stat['keepnext_fig'] += 1
        if not is_tbl and pstyle(s) == 'ad' and CAP_TBL_RX.match(ptext(s).strip()):
            nxt = k + 1
            while nxt < len(rebuilt) and rebuilt[nxt].startswith('<w:p'):
                nxt += 1
            if nxt < len(rebuilt) and rebuilt[nxt].startswith('<w:tbl>') \
                    and '<w:keepNext' not in s:
                s = add_keep_next(s)
                stat['keepnext_cap'] += 1
        out.append(s)

    # ---- 4) 标题段直接 spacing 清除（交给样式 afterLines=100）
    doc2 = ''.join(out)
    doc2 = doc2.replace(
        '<w:pStyle w:val="1"/><w:spacing w:before="120" w:after="120"/>',
        '<w:pStyle w:val="1"/>', 1)
    return head + doc2 + tail


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

    dp = WORK / 'word' / 'document.xml'
    src_doc = dp.read_text(encoding='utf-8')
    new_doc = transform_document(src_doc)
    dp.write_text(new_doc, encoding='utf-8')
    print('document rewritten:', stat)

    stp = WORK / 'word' / 'settings.xml'
    settings = stp.read_text(encoding='utf-8')
    if 'w:name="compatibilityMode"' not in settings:
        if '<w:compat>' in settings:
            settings = settings.replace('<w:compat>',
                '<w:compat><w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>', 1)
        else:
            settings = settings.replace('</w:settings>',
                '<w:compat><w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')
        stp.write_text(settings, encoding='utf-8')
    print('settings compat15 ok')

    for f in ['word/document.xml', 'word/styles.xml', 'word/settings.xml']:
        ET.parse(WORK / f)
    print('xml well-formed OK')

    dst = DST
    try:
        with open(dst, 'wb') as fh:
            pass
    except PermissionError:
        dst = DST.with_name(DST.stem + '_v2.docx')
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        ordered = list(names)
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
