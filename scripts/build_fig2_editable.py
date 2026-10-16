"""按图1风格重绘原生可编辑图2（PatternPlan IR 实例），并执行交付审计。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
import sys
import time
from zipfile import ZipFile

sys.dont_write_bytecode = True
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches, Pt
import build_fig1_editable as f1
from ppt_kit import box as native_box
from eval_edit_locality import build_motif_mask

ROOT = f1.ROOT
TEMPLATE = f1.TEMPLATE
OUT = ROOT / 'outputs/fig2_pptx_en_20260921'
STEM = ROOT / 'docs/figures/Fig2_PatternPlan_IR_Instance_EN'
PPTX, PNG, PDF = (STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf'))
INK, MUTED, BLUE = f1.INK, f1.MUTED, f1.BLUE
COLS = [(0.16, 5.30), (5.62, 5.90), (11.68, 5.58)]
PALETTES = [('EAF3FC', '4E86B5'), ('EAF4ED', '487F55'), ('F1EDF8', '8062AA')]
SCOPE_COLORS = {0: 'E8EDF2', 1: '4E86B5', 2: '8062AA'}
CANVAS = (6.52, 2.02, 4.10)
TEXT_RECORDS = []
VISUAL_RECORDS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def instance():
    # 与正文图2及补充材料E同一实例；作用域几何按编译器同款公式逐格生成。
    plan = {'layout_type': 'framed', 'motifs': [
        {'id': 'm0', 'motif_type': 'rectangle', 'role': 'border', 'effect': 'rib',
         'region': {'center': [20, 20], 'size': [32, 32]}, 'params': {'border_thickness': 2},
         'parent_id': None},
        {'id': 'm1', 'motif_type': 'circle', 'role': 'center', 'effect': 'wave_tuck',
         'region': {'center': [20, 20], 'size': [18, 18]}, 'params': {'period_x': 4, 'period_y': 4},
         'parent_id': 'm0'}]}
    assert plan == json.loads(plan_text()), '实例必须与补充材料E的JSON逐字一致'
    # 作用域几何由系统真实栅格化函数生成（eval_edit_locality.build_motif_mask，
    # 与 generator_one/generation/mask_utils.py 同款语义）。补充材料E的 region.size
    # 以 [w, h] 包围盒书写，运行时半宽/半径取 w // 2；边框 motif_type 归一为 frame。
    def runtime_motif(motif):
        region = motif['region']
        size = region['size']
        half = size[0] // 2 if isinstance(size, (list, tuple)) else int(size)
        kind = 'frame' if motif['motif_type'] == 'rectangle' else motif['motif_type']
        return {'motif_type': kind, 'region': {'center': region['center'], 'size': half},
                'params': motif.get('params', {})}
    m0_mask = build_motif_mask(runtime_motif(plan['motifs'][0]))   # 边框环：cheb <= 16 且 cheb > 14
    m1_mask = build_motif_mask(runtime_motif(plan['motifs'][1]))   # 圆盘：dr^2 + dc^2 <= 9^2
    actions = [[0] * 40 for _ in range(40)]
    for r in range(40):
        for c in range(40):
            if m1_mask[r, c]:
                actions[r][c] = 2
            elif m0_mask[r, c]:
                actions[r][c] = 1
    areas = Counter(v for row in actions for v in row)
    assert int(m0_mask.sum()) == 248 and int(m1_mask.sum()) == 253, areas
    assert not bool((m0_mask & m1_mask).any()), 'm0 环与 m1 圆盘必须互斥'
    assert areas == {0: 1600 - 248 - 253, 1: 248, 2: 253}, areas
    image = Image.new('RGB', (40, 40))
    for r in range(40):
        for c in range(40):
            image.putpixel((c, r), tuple(bytes.fromhex(SCOPE_COLORS[actions[r][c]])))
    evidence = {
        'sample': 'Figure 2 instance = Supplementary E JSON', 'canvas': 40,
        'rasterizer': 'scripts/eval_edit_locality.build_motif_mask (mask_utils semantics)',
        'bbox_to_runtime': 'region.size [w,h] -> scalar half-extent/radius = w // 2; rectangle border -> frame',
        'm0_ring': {'motif_type': 'frame', 'formula': 'cheb <= 16 and cheb > 14',
                    'area': int(m0_mask.sum()), 'derived_from': 'size 32x32 -> half 16, border_thickness 2'},
        'm1_disc': {'motif_type': 'circle', 'formula': '(r-20)^2 + (c-20)^2 <= 9^2',
                    'area': int(m1_mask.sum()), 'derived_from': 'size 18 -> radius 9'},
        'subset': 'm1 disc (cheb <= 9) sits inside the m0 frame interior and is disjoint from the ring',
        'scope_areas': dict(areas),
    }
    write_json('sample_evidence.json', evidence)
    return plan, image, actions


def plan_text():
    # 直接读取论文补充材料E中的JSON代码块，避免手工抄录漂移。
    lines = (ROOT / 'docs/论文初稿.md').read_text(encoding='utf-8').splitlines()
    start = lines.index('```json', 1289)
    end = lines.index('```', start + 1)
    return '\n'.join(lines[start + 1:end])


def text(sl, name, x, y, w, h, value, size=20, color=INK, bold=False, align='left'):
    s = f1.text(sl, name, x, y, w, h, value, size, color, bold, align)
    TEXT_RECORDS.append({'name': name, 'text': value, 'font_pt': size, 'box_inches': [x, y, w, h]})
    return s


def scope_runs(sl, image, actions, x, y, size):
    # 与图1同款：同行同色连续格合并为原生矩形，颜色取自作用域色块图。
    elements = []
    for r in range(40):
        c = 0
        while c < 40:
            rgb = image.getpixel((c, r))
            start = c
            while c < 40 and image.getpixel((c, r)) == rgb:
                c += 1
            hexrgb = ''.join(f'{k:02X}' for k in rgb)
            elements.append(f1.shape(sl, f'scope_run_{r}_{start}_{c}', x+start*size/40,
                                     y+r*size/40, (c-start)*size/40, size/40, hexrgb, hexrgb, lw=.18))
    f1.grouped(sl, 'scope_grid_group', elements)
    VISUAL_RECORDS.append({'prefix': 'scope', 'layout': [x, y, size]})


def build_deck():
    OUT.mkdir(parents=True, exist_ok=True)
    plan, image, actions = instance()
    prs = Presentation()
    if TEMPLATE.exists():
        tpl = Presentation(TEMPLATE)
        prs.slide_width, prs.slide_height = tpl.slide_width, tpl.slide_height
    else:
        # 模板随2026-09-29 docs整理删除；幻灯片尺寸改读图1证据清单（与图1同源）。
        ev = ROOT / 'outputs/fig1_pptx_en_20260921/source_evidence.json'
        if ev.exists():
            w, h = json.loads(ev.read_text(encoding='utf-8'))['template_inches']
        else:
            w, h = 17.416666666666668, 9.802083333333334
        prs.slide_width, prs.slide_height = Inches(w), Inches(h)
    # 导师修改标准第二轮：底部横带删除后回收幻灯片高度至9.00in，上下留白 .40/.44 平衡。
    prs.slide_height = Inches(9.00)
    prs.core_properties.title = 'PatternPlan Hierarchical Manufacturing IR Instance'
    prs.core_properties.subject = 'Figure 2: editable native shapes; Supplementary E instance'
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    TEXT_RECORDS.clear()
    VISUAL_RECORDS.clear()
    headers = [('Motif', 'Hierarchy'),
               ('Spatial', 'Scopes'),
               ('Seven-tuple', 'Fields')]
    # 分块编号遵循Elsevier体例：图内圆盘放小写字母，图注以(a)-(c)引用；删冗后字号整体放大。
    # 栏宽5.3–5.9in足够30pt单行标题（图1双行系窄栏惯性，此处合并）。
    # 导师标准：三条副标题删除（PatternPlan tree与根芯片逐字重复、40×40 canvas与口号句由图注/正文承载）。
    for i, ((x, w), (bg, accent), (first, second)) in enumerate(zip(COLS, PALETTES, headers)):
        tag = 'abc'[i]
        f1.shape(sl, f'column_{i+1}', x, .40, w, 8.16, bg, kind='round')
        f1.shape(sl, f'panel_disc_{tag}', x+.12, .58, .44, .44, accent, kind='oval')
        text(sl, f'panel_label_{tag}', x+.12, .58, .44, .44, tag, 26, 'FFFFFF', align='center')
        text(sl, f'heading_{i+1}', x+.10, .60, w-.20, .50, f'{first} {second}', 30, bold=True, align='center')
        f1.shape(sl, f'inner_panel_{i+1}', x+.10, 1.30, w-.20, 7.15, 'FFFFFF', bg, 'round', 1)

    # ① 层级树：根芯片＋两张motif卡，字段以芯片行呈现，不用等宽代码块。
    # m1卡的parent行与紧邻的parent_id边芯片重复，删除；栏1底注与栏2底注/底部横带同义，删除。
    f1.shape(sl, 'plan_root', .36, 1.44, 4.90, .58, 'EEE8F6', 'A294C3', 'round')
    text(sl, 'plan_root_text', .42, 1.50, 4.78, .46, 'PatternPlan · layout_type = framed', 22, bold=True, align='center')
    f1.line(sl, 'tree_trunk_root', 2.81, 2.02, 2.81, 2.26, 'A4AEB8', 1.5)
    cards = [(2.26, 2.86, 'EAF2FB', '709FCC', 'm0 · rectangle',
              [('role', 'border'), ('effect', 'rib'), ('region', 'center (20, 20) · 32 × 32'),
               ('params', 'border_thickness = 2'), ('parent', 'null · top level')]),
             (5.56, 2.44, 'F1EDF8', '8062AA', 'm1 · circle',
              [('role', 'center'), ('effect', 'wave_tuck'), ('region', 'center (20, 20) · Ø18'),
               ('params', 'period_x = 4 · period_y = 4')])]
    for y, card_h, fill, accent, title, rows in cards:
        f1.shape(sl, 'motif_card_'+title.split()[0], .46, y, 4.70, card_h, fill, accent, 'round')
        text(sl, 'motif_title_'+title.split()[0], .64, y+.08, 3.20, .38, title, 27, bold=True)
        for j, (key, value) in enumerate(rows):
            text(sl, f'field_key_{title.split()[0]}_{key}', .62, y+.58+j*.46, .98, .40, key, 22, MUTED)
            text(sl, f'field_value_{title.split()[0]}_{key}', 1.60, y+.58+j*.46, 3.50, .40, value, 22)
    f1.line(sl, 'tree_edge_m0_m1', 2.81, 5.12, 2.81, 5.56, '8062AA', 1.7, True)
    f1.shape(sl, 'parent_edge_chip', 3.00, 5.18, 2.30, .40, 'FFFFFF', '8062AA', 'round')
    text(sl, 'parent_edge_label', 3.04, 5.22, 2.22, .32, 'parent_id = m0', 22, '8062AA', True, 'center')

    # ② 作用域画布：40×40 实心原生色块，无坐标轴；几何由实例参数公式逐格生成。
    scope_runs(sl, image, actions, *CANVAS)
    f1.shape(sl, 'scope_outline', CANVAS[0]-.005, CANVAS[1]-.005, CANVAS[2]+.01, CANVAS[2]+.01, None, '7C98AE', lw=1)
    legend = [('ground · plain field', SCOPE_COLORS[0]), ('m0 · rectangle ring 32 × 32, t = 2', SCOPE_COLORS[1]),
              ('m1 · circle Ø18 · wave_tuck 4 × 4', SCOPE_COLORS[2])]
    for i, (label, rgb) in enumerate(legend):
        y = 6.56+i*.50
        f1.shape(sl, f'scope_legend_swatch_{i}', 6.62, y+.08, .28, .28, rgb, '8C9DAA', lw=.5)
        text(sl, f'scope_legend_{i}', 6.96, y, 4.40, .40, label, 22)
    # 导师标准：subset底注与图注(b)“子区域事件写入在编译期被限制于父级作用域之内”逐字重复，删除。

    # ③ 七元组契约：字段名＋含义；取值见栏1，完整Schema见补充材料E。
    fields = [('id', 'motif identifier'), ('type', 'geometry: rectangle, circle…'),
              ('effect', 'texture pattern in region'), ('role', 'layout role: border / center'),
              ('region', 'spatial scope on canvas'), ('params', 'craft parameters θ'),
              ('parent', 'parent scope reference')]
    for i, (key, meaning) in enumerate(fields):
        y = 1.44+i*.95
        f1.shape(sl, f'tuple_chip_{key}', 11.86, y, 1.24, .58, 'FFFFFF', '8062AA', 'round')
        text(sl, f'tuple_key_{key}', 11.90, y+.11, 1.16, .36, key, 22, '8062AA', True, 'center')
        text(sl, f'tuple_meaning_{key}', 13.18, y+.11, 3.94, .36, meaning, 22)
    # 导师标准：tuple_note三行与图注(c)“形状定写入作用域…补充材料E”逐字重复，删除。

    # 导师标准：底部箭头链横带删除（图注(a)末句与正文3.2末句已承载）；幻灯片高度回收至9.00in。
    notes = (
        'Figure 2 instance is byte-identical to the Supplementary E JSON (m0 rectangle border, m1 circle center).\n'
        'Scope blocks are native rectangles rasterized by the system mask function build_motif_mask: m0 frame ring cheb <= 16 and cheb > 14 (248 cells), m1 disc radius 9 (253 cells).\n'
        'No texture glyph is overlaid on the scopes; the m1 effect (wave_tuck, period 4 x 4) is named in the legend and is not compiled into events for this schema instance.\n'
        'Colors encode region scopes, not knitting actions; the action color table of Figure 1 is not reused here.\n'
        'All text is Times New Roman; the figure carries no axes, ticks or monospace code blocks.\n'
        '2026-09-29 revision: panel discs carry letters a-c per Elsevier style and the caption cites (a)-(c); '
        'the duplicate hierarchy note under column (a) and the parent row inside the m1 card were removed '
        '(the parent_id edge chip remains); fonts enlarged for reviewer readability; '
        'column headings set on a single line (the two-line split was inherited from Fig. 1 narrow columns) '
        'and the reclaimed header space went into larger cards, canvas and tuple rows.\n'
        '2026-09-29 advisor-style pass: the bottom arrow-chain band, the tuple note, the subset note and the '
        'three subheadings were removed (each is verbatim-covered by the caption or Sec. 3.2); body fonts '
        'raised to a uniform 22pt and the slide height trimmed to 9.00in so top/bottom margins balance.')
    tf = sl.notes_slide.notes_text_frame
    tf.text = notes
    for para in tf.paragraphs:
        for run in para.runs:
            run.font.name, run.font.size = 'Times New Roman', Pt(18)
    prs.save(PPTX)
    normalize_package()
    write_json('text_manifest.json', TEXT_RECORDS)
    write_json('native_visual_manifest.json', VISUAL_RECORDS)
    return audit_deck()


def normalize_package():
    # 与图1同一规范化：包内所有typeface统一Times New Roman并补latin/ea/cs。
    from lxml import etree
    from pptx.oxml.ns import qn
    from pptx.oxml.xmlchemy import OxmlElement
    target = BytesIO()
    with ZipFile(PPTX) as src, ZipFile(target, 'w') as dest:
        for item in src.infolist():
            blob = src.read(item.filename)
            if item.filename.endswith('.xml'):
                root = etree.fromstring(blob)
                for node in root.iter():
                    if 'typeface' in node.attrib:
                        node.set('typeface', 'Times New Roman')
                    if node.tag in {qn('a:rPr'), qn('a:defRPr'), qn('a:endParaRPr')}:
                        node.set('lang', 'en-US')
                        if 'sz' in node.attrib:
                            node.set('sz', str(max(1800, int(node.get('sz')))))
                        for tag in ('a:latin', 'a:ea', 'a:cs'):
                            face = node.find(qn(tag))
                            if face is None:
                                face = OxmlElement(tag)
                                node.append(face)
                            face.set('typeface', 'Times New Roman')
                blob = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            dest.writestr(item, blob)
    PPTX.write_bytes(target.getvalue())


def flatten(shapes):
    for s in shapes:
        yield s
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from flatten(s.shapes)


def audit_deck():
    assert PPTX.exists()
    p = Presentation(PPTX)
    assert len(p.slides) == 1
    shapes = list(flatten(p.slides[0].shapes))
    runs = [s for s in shapes if s.name.startswith('scope_run_')]
    _, image, actions = instance()
    covered = set()
    for s in runs:
        r, start, end = (int(v) for v in s.name.rsplit('_', 3)[1:])
        rgb = image.getpixel((start, r))
        assert tuple(s.fill.fore_color.rgb) == rgb, s.name
        assert all(image.getpixel((c, r)) == rgb for c in range(start, end)), s.name
        assert start == 0 or image.getpixel((start-1, r)) != rgb, s.name
        assert end == 40 or image.getpixel((end, r)) != rgb, s.name
        x, y, size = CANVAS
        for actual, want in zip((s.left, s.top, s.width, s.height),
                                (x+start*size/40, y+r*size/40, (end-start)*size/40, size/40)):
            assert abs(actual-Inches(want)) <= 3, s.name
        cells = {(r, c) for c in range(start, end)}
        assert not covered & cells
        covered |= cells
    assert covered == {(r, c) for r in range(40) for c in range(40)}
    pictures = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert not pictures, '图2不使用任何位图贴图'
    fonts, bounds = [], []
    for s in shapes:
        if s.left < -12700 or s.top < -12700 or s.left+s.width > p.slide_width+12700 or s.top+s.height > p.slide_height+12700:
            bounds.append(s.name)
        if s.has_text_frame and s.text.strip():
            for para in s.text_frame.paragraphs:
                for run in para.runs:
                    assert run.font.size is not None, s.name
                    fonts.append(run.font.size.pt)
    assert not bounds, bounds
    assert min(fonts) >= 18, min(fonts)
    ratio = 160 / (p.slide_width / 914400 * 25.4)
    assert min(fonts) * ratio >= 6
    with ZipFile(PPTX) as z:
        forbidden = [n for n in z.namelist() if n.lower().endswith('.svg')]
        assert not forbidden
        assert all(b'image/svg+xml' not in z.read(n) and b'<asvg:' not in z.read(n)
                   for n in z.namelist() if n.endswith(('.xml', '.rels')))
    from lxml import etree
    from pptx.oxml.ns import qn
    faces = set()
    with ZipFile(PPTX) as z:
        for name in z.namelist():
            if name.endswith('.xml'):
                for node in etree.fromstring(z.read(name)).iter():
                    if 'typeface' in node.attrib:
                        faces.add(node.get('typeface'))
                    if node.tag == qn('a:t'):
                        assert not re.search(r'[\u3400-\u9fff]', node.text or ''), name
    assert faces == {'Times New Roman'}, faces
    alltext = '\n'.join(s.text for s in shapes if s.has_text_frame)
    for phrase in ('PatternPlan', 'layout_type = framed', 'parent_id = m0', 'border_thickness = 2',
                   'period_x = 4'):
        assert phrase in alltext, phrase
    result = {
        'passed': True, 'slide_count': 1, 'total_objects_recursive': len(shapes),
        'object_types': dict(Counter(str(s.shape_type) for s in shapes)),
        'scope_runs': len(runs), 'scope_cells_covered': len(covered),
        'scope_pixel_exact': True, 'pictures': len(pictures),
        'text_objects': sum(s.has_text_frame and bool(s.text.strip()) for s in shapes),
        'min_font_pt': min(fonts), 'max_font_pt': max(fonts),
        'figure_width_mm': 160, 'min_reduced_font_pt': min(fonts)*ratio,
        'shape_out_of_slide': bounds, 'svg_files': forbidden,
        'package_typefaces': sorted(faces), 'pptx_sha256': sha(PPTX),
    }
    write_json('object_audit.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def render_deck(export=True):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app, pres = None, None
    try:
        if not export:
            prior = json.loads((OUT / 'export_audit.json').read_text(encoding='utf-8'))
            for path in (PPTX, PNG, PDF):
                assert sha(path) == prior['exports'][path.suffix]['sha256'], f'交付物与原导出记录不符: {path.name}'
        try:
            app = win32com.client.GetActiveObject('PowerPoint.Application')
        except Exception:
            app = win32com.client.Dispatch('PowerPoint.Application')
        for attempt in range(12):
            try:
                pres = app.Presentations.Open(str(PPTX), True, False, False)
                assert pres.Slides.Count == 1
                break
            except Exception:
                if attempt == 11:
                    raise
                time.sleep(1)
        slide = pres.Slides.Item(1)
        if export:
            slide.Export(str(PNG), 'PNG', 4000, round(4000*pres.PageSetup.SlideHeight/pres.PageSetup.SlideWidth))
            pres.SaveAs(str(PDF), 32)
        records, overflow = [], []

        def inspect(shapes):
            for i in range(1, shapes.Count+1):
                s = shapes.Item(i)
                if s.Type == 6:
                    inspect(s.GroupItems)
                if s.HasTextFrame and s.TextFrame2.HasText:
                    tf, tr = s.TextFrame2, s.TextFrame2.TextRange
                    w, h = s.Width-tf.MarginLeft-tf.MarginRight, s.Height-tf.MarginTop-tf.MarginBottom
                    row = {'name': s.Name, 'text': tr.Text, 'available_pt': [w, h],
                           'bound_pt': [tr.BoundWidth, tr.BoundHeight],
                           'glyph_rect_pt': [tr.BoundLeft, tr.BoundTop, tr.BoundWidth, tr.BoundHeight],
                           'com_font': tr.Font.Name, 'com_font_size': tr.Font.Size}
                    assert tr.Font.Name == 'Times New Roman' and tr.Font.Size >= 18, row
                    records.append(row)
                    if tr.BoundWidth > w+1.2 or tr.BoundHeight > h+1.2:
                        overflow.append(row)
        # COM遍历形状时偶发拒绝呼叫(RPC_E_CALL_REJECTED)或对象失效(AttributeError <unknown>)；
        # 打开后先静置再幂等重取slide整体重试；真实字体/尺寸违规(AssertionError)立即上抛，绝不当作瞬态掩盖。
        time.sleep(4)
        for walk in range(10):
            records.clear(); overflow.clear()
            try:
                inspect(pres.Slides.Item(1).Shapes)
                break
            except AssertionError:
                raise
            except Exception:
                if walk == 9:
                    raise
                time.sleep(3)
        overlaps = []
        for i, a in enumerate(records):
            ax, ay, aw, ah = a['glyph_rect_pt']
            for b in records[i+1:]:
                bx, by, bw, bh = b['glyph_rect_pt']
                ix = min(ax+aw, bx+bw)-max(ax, bx)
                iy = min(ay+ah, by+bh)-max(ay, by)
                if ix > 2 and iy > 1.2:
                    overlaps.append({'names': [a['name'], b['name']], 'intersection_pt': [ix, iy]})
        report = {'png': str(PNG), 'png_size': Image.open(PNG).size if PNG.exists() else None,
                  'pdf': str(PDF), 'pptx_sha256': sha(PPTX), 'actual_powerpoint_com': True,
                  'text_objects_checked': len(records), 'text_overflow': overflow,
                  'text_overlap': overlaps, 'overlap_tolerance_pt': [2, 1.2],
                  'text_measurements': records, 'export_performed_this_call': export,
                  'ppt_version': app.Version}
        write_json('render_audit.json', report)
        if overflow or overlaps:
            write_json('render_failure_'+str(time.time_ns())+'.json', report)
        im = Image.open(PNG).convert('RGB')
        im.resize((1600, round(im.height*1600/im.width)), Image.Resampling.LANCZOS).save(OUT/'overview.png')
        im.resize((1890, round(im.height*1890/im.width)), Image.Resampling.LANCZOS).save(OUT/'print_160mm_300dpi.png', dpi=(300, 300))
        k = im.width / (pres.PageSetup.SlideWidth/72)
        for key, (x, w) in {'hierarchy': COLS[0], 'scopes': COLS[1], 'fields': COLS[2]}.items():
            im.crop((round(x*k), round(.40*k), round((x+w)*k), round(8.56*k))).save(OUT/f'detail_{key}.png')
        print(json.dumps({'rendered': True, 'text_overflow_count': len(overflow), 'overflow': overflow,
                          'text_overlap_count': len(overlaps), 'overlaps': overlaps}, ensure_ascii=False, indent=2))
        assert not overflow, 'PowerPoint 实测存在文字溢出'
        assert not overlaps, 'PowerPoint 实测存在文字重叠'
        audit_exports()
    except Exception as exc:
        write_json('render_error_'+str(time.time_ns())+'.json', {'error': repr(exc), 'pptx': str(PPTX)})
        raise
    finally:
        if pres is not None:
            pres.Close()
        pythoncom.CoUninitialize()


def audit_exports():
    import pymupdf as fitz
    with fitz.open(PDF) as doc:
        assert len(doc) == 1
        page = doc[0]
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
                 for line_ in b['lines'] for s in line_['spans'] if s['text'].strip()]
        assert len(spans) >= 40
        assert not page.get_images(full=True), '图2 PDF不应含位图'
        assert min(s['size'] for s in spans) >= 17.99
        assert Image.open(PNG).width == 4000
        pdf_fonts = sorted({s['font'] for s in spans})
        assert all('TimesNewRoman' in f.replace('-', '') for f in pdf_fonts), pdf_fonts
        assert not re.search(r'[\u3400-\u9fff]', page.get_text())
        assert all(f[1] != 'n/a' for f in page.get_fonts(full=True)), 'PDF字体未嵌入'
        image = Image.open(PNG).convert('RGB')
        _, source, _ = instance()
        scale = image.width / (page.rect.width / 72)
        x, y, width = CANVAS
        pitch = width / 40
        bad = [(r, c) for r in range(40) for c in range(40)
               if image.getpixel((round((x+(c+.5)*pitch)*scale), round((y+(r+.5)*pitch)*scale))) != source.getpixel((c, r))]
        result = {'pdf_pages': 1, 'pdf_text_spans': len(spans),
                  'pdf_min_font_pt': min(s['size'] for s in spans), 'pdf_fonts': pdf_fonts,
                  'pdf_image_objects': len(page.get_images(full=True)),
                  'pdf_vector_drawings': len(page.get_drawings()),
                  'scope_cell_centers_checked': 1600, 'scope_rgb_mismatches': len(bad),
                  'png_pixels': Image.open(PNG).size,
                  'exports': {p.suffix: {'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
                              for p in (PPTX, PNG, PDF)}}
        assert not bad, bad[:10]
        write_json('export_audit.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    f1.FONT = 'Times New Roman'
    if args.verify:
        audit_deck()
        render_deck(export=False)
    else:
        build_deck()
        render_deck()


if __name__ == '__main__':
    main()
