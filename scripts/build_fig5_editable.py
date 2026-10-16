"""按图1风格重绘原生可编辑图5（结构感知视觉预览模块），全英文 TNR，并执行交付审计。"""
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

ROOT = f1.ROOT
TEMPLATE = f1.TEMPLATE
OUT = ROOT / 'outputs/fig5_pptx_en_20260922'
STEM = ROOT / 'docs/figures/Fig5_Structure_Aware_Visual_Preview_EN'
PPTX, PNG, PDF = (STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf'))
INK, MUTED, BLUE = f1.INK, f1.MUTED, f1.BLUE
PLAN = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_pattern_plan.json'
STATS = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_stats.json'
ACTION_BMP = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_output.bmp'
ACTION_NPY = ACTION_BMP.parent / 'intermediate/pp_01_action.npy'
PALETTE = ROOT / 'conditional-flow-matching-main/assets/instructions.json'
PREVIEW = ROOT / 'outputs/factory_delivery/F1_pp01_circle_wave_preview.png'
FIG1_EVIDENCE = ROOT / 'outputs/fig1_pptx_en_20260921/source_evidence.json'
COL_W, GAP, X0 = 4.05, .30, .16
COLS = [X0 + i * (COL_W + GAP) for i in range(4)]
PALETTES = [('EAF3FC', '4E86B5'), ('EAF4ED', '487F55'), ('FDF3E7', 'B07A3C'), ('F1EDF8', '8062AA')]
CANVAS = 2.60  # 导师标准：删冗回收的垂直空间用于放大动作网格（2.20→2.60），填满(a)栏。
TEXT_RECORDS = []
VISUAL_RECORDS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def instance():
    # 只读 Generation Case 01（pp_01）历史产物：动作色码图 A 与 Stage 4 视觉预览图。
    import numpy as np
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    stats = json.loads(STATS.read_text(encoding='utf-8'))
    motifs = {m['motif_id']: m for m in plan['motifs']}
    assert motifs['wave_1']['parent_id'] == 'circle_1'
    actions = np.load(ACTION_NPY, allow_pickle=False)
    assert actions.shape == (40, 40) and set(np.unique(actions).tolist()) == {0, 1, 7, 8}
    grid = Image.open(ACTION_BMP).convert('RGB')
    palette = json.loads(PALETTE.read_text(encoding='utf-8'))['instructions']
    assert len(palette) == 15, '动作标签空间必须是15类'
    colors = {i: tuple(bytes.fromhex(palette[i]['color'][1:])) for i in range(15)}
    used = {0: 'f_knit', 1: 'b_knit', 7: 'f_tuck', 8: 'f_split'}
    assert all(grid.getpixel((c, r)) == colors[int(actions[r, c])] for r in range(40) for c in range(40))
    assert colors[0] == (255, 0, 16) and colors[1] == (43, 206, 72)
    assert colors[7] == (0, 164, 255) and colors[8] == (255, 230, 6)
    assert all(stats['violations'][k] == 0 for k in ('hard_before', 'craft_before', 'hard_after', 'craft_after'))
    # 视觉预览：Stage 4 真实运行输出，与图1引用同一受核验素材（未重新推理）。
    assert Image.open(PREVIEW).convert('RGB').size == (320, 320)
    fig1 = json.loads(FIG1_EVIDENCE.read_text(encoding='utf-8'))
    assert sha(PREVIEW) == fig1['sources']['preview']['sha256'], '预览图与图1受核验素材不一致'
    craft = {i: {'name': used[i], 'color': palette[i]['color'], 'semantic': palette[i]['semantic'],
                 'tension': palette[i].get('tension'), 'elasticity': palette[i].get('elasticity'),
                 'stability': palette[i].get('stability')} for i in sorted(used)}
    evidence = {
        'sample': 'Generation Case 01 (pp_01), historical run outputs only',
        'plan_sha256': sha(PLAN), 'stats_sha256': sha(STATS),
        'action_npy_sha256': sha(ACTION_NPY), 'action_bmp_sha256': sha(ACTION_BMP),
        'action_space_classes': 15, 'classes_used_by_pp01': sorted(used),
        'class_attributes': craft,
        'preview': {'path': str(PREVIEW), 'sha256': sha(PREVIEW), 'size_px': [320, 320],
                    'stage': 4, 'provenance': fig1['source_notes']['preview'],
                    'same_asset_as_figure1': True, 'reinferred': False},
        'module_config': {
            'backbone': 'Stage4AdaptiveSIUNet (UNet velocity field)',
            'conditioner': 'NeighborAwareConditioner: center + 8 neighbors, embed_dim 256, 8 heads',
            'physics_prior': 'PhysicsFeatureEncoder: tension, elasticity, stability + semantic/bed one-hot',
            'framework': 'Conditional Flow Matching; learn v(x_t, t, c) to target field u',
            'inference': 'torchdiffeq odeint, solver midpoint, 300 steps, global_correlated noise, '
                         'perturb_scale 0.03, seed 42, patch 16; grid downsampled to 20x20 patches -> 320x320',
        },
        'boundary': '预览为外观呈现，非纱线级物理仿真，不构成可织性证明；模块只读动作图 A。',
    }
    write_json('sample_evidence.json', evidence)
    return grid, evidence


def text(sl, name, x, y, w, h, value, size=20, color=INK, bold=False, align='left'):
    s = f1.text(sl, name, x, y, w, h, value, size, color, bold, align)
    TEXT_RECORDS.append({'name': name, 'text': value, 'font_pt': size, 'box_inches': [x, y, w, h]})
    return s


def cand_runs(sl, image, x, y, size):
    # 与图1/图3/图4同款：同行同色连续格合并为原生矩形，颜色取自真实色码图。
    elements = []
    for r in range(40):
        c = 0
        while c < 40:
            rgb = image.getpixel((c, r))
            start = c
            while c < 40 and image.getpixel((c, r)) == rgb:
                c += 1
            hexrgb = ''.join(f'{k:02X}' for k in rgb)
            elements.append(f1.shape(sl, f'cand_run_{r}_{start}_{c}', x + start * size / 40,
                                     y + r * size / 40, (c - start) * size / 40, size / 40,
                                     hexrgb, hexrgb, lw=.18))
    f1.grouped(sl, 'cand_group', elements)
    VISUAL_RECORDS.append({'prefix': 'cand', 'layout': [x, y, size]})


def chip(sl, name, x, y, w, h, fill, accent, line1, line2=None, s1=24, s2=22, m=.06):
    f1.shape(sl, name, x, y, w, h, fill, accent, 'round')
    if line2 is None:
        text(sl, name + '_text', x + m, y + (h - .40) / 2, w - 2 * m, .40, line1, s1, accent, True, 'center')
    else:
        text(sl, name + '_title', x + m, y + .10, w - 2 * m, .40, line1, s1, bold=True, align='center')
        text(sl, name + '_sub', x + m, y + .52, w - 2 * m, .38, line2, s2, MUTED, align='center')


def neighbor_window(sl, x, y, cell, accent, fill):
    # N8 条件窗口示意：3×3 原生方块，中心为待预测动作，八邻域为上下文（机制示意）。
    names = []
    for r in range(3):
        for c in range(3):
            is_center = (r == 1 and c == 1)
            color = accent if is_center else fill
            names.append(f1.shape(sl, f'n8_cell_{r}_{c}', x + c * (cell + .03), y + r * (cell + .03),
                                  cell, cell, color, '7C98AE', lw=.8))
    f1.grouped(sl, 'n8_group', names)


def build_deck():
    OUT.mkdir(parents=True, exist_ok=True)
    grid, evidence = instance()
    prs = Presentation()
    if TEMPLATE.exists():
        tpl = Presentation(TEMPLATE)
        prs.slide_width, prs.slide_height = tpl.slide_width, tpl.slide_height
    else:
        # 模板随2026-09-29 docs整理删除；幻灯片尺寸改读图1证据清单（与图2/3/4同款回退）。
        if FIG1_EVIDENCE.exists():
            w, h = json.loads(FIG1_EVIDENCE.read_text(encoding='utf-8'))['template_inches']
        else:
            w, h = 17.416666666666668, 9.802083333333334
        prs.slide_width, prs.slide_height = Inches(w), Inches(h)
    # 导师标准：底部横带删除后回收幻灯片高度至8.30in，各栏内容贴紧面板、不留大片空白。
    prs.slide_height = Inches(8.30)
    prs.core_properties.title = 'Structure-Aware Visual Preview Module'
    prs.core_properties.subject = 'Figure 5: editable native shapes; Generation Case 01 input and Stage 4 preview'
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    TEXT_RECORDS.clear()
    VISUAL_RECORDS.clear()
    # 导师标准：数字盘1-4改 a-d（Elsevier 体例，图注同步引 (a)-(d)）；栏题双行居中升32pt，副题24pt。
    headers = [('Conditional', 'Input', 'action map A · N8 window'),
               ('Conditional', 'Encoder', 'three cues fused to c'),
               ('Generation', 'Core', 'flow matching + ODE'),
               ('Appearance', 'Preview', 'real Stage 4 output')]
    for i, (x, (bg, accent), (first, second, sub)) in enumerate(zip(COLS, PALETTES, headers)):
        tag = 'abcd'[i]
        f1.shape(sl, f'column_{i+1}', x, .40, COL_W, 7.24, bg, kind='round')
        f1.shape(sl, f'panel_disc_{tag}', x + .12, .58, .44, .44, accent, kind='oval')
        text(sl, f'panel_label_{tag}', x + .12, .58, .44, .44, tag, 26, 'FFFFFF', align='center')
        text(sl, f'heading_first_{i+1}', x + .10, 1.06, COL_W - .20, .50, first, 32, bold=True, align='center')
        text(sl, f'heading_second_{i+1}', x + .10, 1.62, COL_W - .20, .50, second, 32, bold=True, align='center')
        text(sl, f'subheading_{i+1}', x + .10, 2.18, COL_W - .20, .40, sub, 24, accent, align='center')
        f1.shape(sl, f'inner_panel_{i+1}', x + .10, 2.64, COL_W - .20, 4.82, 'FFFFFF', bg, 'round', 1)
    for i in range(3):
        f1.line(sl, f'stage_arrow_{i+1}', COLS[i] + COL_W + .04, 5.10, COLS[i + 1] - .04, 5.10, INK, 2.25, True)

    # (a) 条件输入：真实动作色码图 A + N8 窗口示意。工艺属性先验移至(b)编码栏（跨栏重复删除）；
    # “15-class”“reads A only”两行注复述图注，删除；网格放大至2.60in填满回收空间。
    cx = COLS[0] + (COL_W - CANVAS) / 2
    cy = 2.86
    cand_runs(sl, grid, cx, cy, CANVAS)
    f1.shape(sl, 'cand_outline', cx - .005, cy - .005, CANVAS + .01, CANVAS + .01, None, '7C98AE', lw=1)
    text(sl, 'cand_title', COLS[0] + .20, 5.62, COL_W - .40, .36, 'Action map A', 24, bold=True, align='center')
    text(sl, 'cand_sub', COLS[0] + .20, 6.02, COL_W - .40, .36, 'Generation Case 01 · 40×40', 22, MUTED, align='center')
    neighbor_window(sl, COLS[0] + .55, 6.50, .24, '4E86B5', 'CFE0EF')
    text(sl, 'n8_title', COLS[0] + 1.62, 6.66, COL_W - 1.82, .40, 'N8 window', 24, bold=True)

    # (b) 条件编码器 E：邻居/工艺两路编码融合为 c 注入 UNet；三行复述注删除；芯片升24/22pt，
    # 副行改承载真实配置数据（embed/heads、三属性等级）。
    x2 = COLS[1] + .14
    cw = COL_W - .28
    chip(sl, 'enc_chip_neighbor', x2, 2.86, cw, .98, 'EAF4ED', '487F55', 'Neighbor encoder', 'center + 8 neighbors', m=.02)
    chip(sl, 'enc_chip_physics', x2, 4.00, cw, .98, 'EAF4ED', '487F55', 'Physics encoder', 'tension·elastic·stability', m=.02)
    chip(sl, 'enc_chip_fusion', x2, 5.14, cw, .98, 'EAF4ED', '487F55', 'Fusion to vector c', 'single condition vector', m=.02)
    chip(sl, 'enc_chip_inject', x2, 6.28, cw, .98, 'EAF4ED', '487F55', 'Inject into UNet', 'c conditions each step', m=.02)

    # (c) 生成核心：CFM 学速度场、UNet 预测、ODE 中点积分、300 步 Stage 4；三行复述注删除。
    x3 = COLS[2] + .14
    chip(sl, 'core_chip_cfm', x3, 2.86, cw, .98, 'FDF3E7', 'B07A3C', 'Flow matching', 'learn velocity field v', m=.02)
    chip(sl, 'core_chip_unet', x3, 4.00, cw, .98, 'FDF3E7', 'B07A3C', 'UNet prediction', 'v(x, t, c) per patch', m=.02)
    chip(sl, 'core_chip_ode', x3, 5.14, cw, .98, 'FDF3E7', 'B07A3C', 'ODE midpoint', 'noise x0 to preview x1', m=.02)
    chip(sl, 'core_chip_steps', x3, 6.28, cw, .98, 'FDF3E7', 'B07A3C', '300 steps · Stage 4', 'global correlated noise', m=.02)

    # (d) 外观预览：Stage 4 真实输出放大至3.00in；“boundary/texture”两芯片与三行边界注复述图注，删除。
    px = COLS[3] + (COL_W - 3.00) / 2
    py = 2.86
    pic = f1.pic_fit(sl, PREVIEW, px, py, 3.00, 3.00, frame=False)
    pic.name = 'preview_stage4'
    f1.shape(sl, 'preview_outline', px - .005, py - .005, 3.01, 3.01, None, '7C98AE', lw=1)
    text(sl, 'preview_title', COLS[3] + .20, 6.02, COL_W - .40, .36, 'Appearance preview', 24, bold=True, align='center')
    text(sl, 'preview_sub', COLS[3] + .20, 6.42, COL_W - .40, .36, 'Generation Case 01', 22, MUTED, align='center')
    text(sl, 'preview_size', COLS[3] + .20, 6.82, COL_W - .40, .36, 'Stage 4 · 320 × 320 output', 22, MUTED, align='center')
    notes = (
        'Figure 5 is rebuilt as native editable PowerPoint objects in the Figure 1 visual language; all figure text is English Times New Roman.\n'
        'Panel (a) draws the real Generation Case 01 (pp_01) action color map A as merged native rectangles (40 x 40, 15-class action space; '
        'this case uses f_knit, b_knit, f_tuck, f_split). The N8 window is a mechanism schematic of the center-plus-8-neighbor conditioning window.\n'
        'Panel (b) is the conditional encoder E: a neighbor-aware conditioner (center + 8 neighbors, embed 256, 8 heads) plus a physics attribute '
        'prior (tension, elasticity, stability per action class), fused into one condition vector c injected into the UNet.\n'
        'Panel (c) is the generation core: conditional flow matching learns the velocity field v(x, t, c); inference integrates the ODE with a '
        'midpoint solver (300 steps, global correlated noise, seed 42, patch 16) from noise x0 to preview x1 on a 20 x 20 patch grid.\n'
        'Panel (d) embeds the genuine Stage 4 preview of Generation Case 01 (320 x 320), the same verified asset used in Figure 1; it was not '
        're-inferred here. The preview is appearance feedback, not a yarn-level physical simulation and not a proof of knitability.\n'
        'The module reads only the action map A; no yarn material or machine state is simulated. The single embedded raster is the real model output.\n'
        'Advisor pass: redundant restatement notes, the cross-panel physics-prior chip, the two appearance-boundary chips and the bottom band were removed; '
        'panel discs relabeled 1-4 to a-d; headings raised to 32 pt, subheadings 24 pt, chip text 24/22 pt (the column-width ceiling at this chip width); '
        'recovered space reinvested by enlarging the action grid to 2.60 in and the Stage 4 preview to 3.00 in, with panel/slide heights compacted to 8.30 in so no large blank areas remain.')
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
    # 与图1/图3/图4同一规范化：包内所有typeface统一Times New Roman并补latin/ea/cs。
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
                            node.set('sz', str(max(2200, int(node.get('sz')))))
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


def reference_images():
    grid, _ = instance()
    return {'cand': grid}


def layout_of(prefix):
    return [COLS[0] + (COL_W - CANVAS) / 2, 2.86, CANVAS]


def audit_deck():
    assert PPTX.exists()
    p = Presentation(PPTX)
    assert len(p.slides) == 1
    shapes = list(flatten(p.slides[0].shapes))
    _, evidence = instance()
    refs = reference_images()
    covered = {}
    for prefix, image in refs.items():
        runs = [s for s in shapes if s.name.startswith(prefix + '_run_')]
        seen = set()
        for s in runs:
            r, start, end = (int(v) for v in s.name.rsplit('_', 3)[1:])
            rgb = image.getpixel((start, r))
            assert tuple(s.fill.fore_color.rgb) == rgb, s.name
            assert all(image.getpixel((c, r)) == rgb for c in range(start, end)), s.name
            assert start == 0 or image.getpixel((start - 1, r)) != rgb, s.name
            assert end == 40 or image.getpixel((end, r)) != rgb, s.name
            x, y, size = layout_of(prefix)
            for actual, want in zip((s.left, s.top, s.width, s.height),
                                    (x + start * size / 40, y + r * size / 40, (end - start) * size / 40, size / 40)):
                assert abs(actual - Inches(want)) <= 3, s.name
            cells = {(r, c) for c in range(start, end)}
            assert not seen & cells
            seen |= cells
        assert seen == {(r, c) for r in range(40) for c in range(40)}, prefix
        covered[prefix] = len(seen)
    # 唯一位图素材：Stage 4 真实预览输出（与图1同一受核验资产）。
    pictures = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(pictures) == 1, '图5只嵌入一张真实 Stage 4 预览位图'
    assert hashlib.sha256(pictures[0].image.blob).hexdigest() == evidence['preview']['sha256']
    assert pictures[0].width * pictures[0].height < p.slide_width * p.slide_height * 0.15
    fonts, bounds = [], []
    for s in shapes:
        if s.left < -12700 or s.top < -12700 or s.left + s.width > p.slide_width + 12700 or s.top + s.height > p.slide_height + 12700:
            bounds.append(s.name)
        if s.has_text_frame and s.text.strip():
            for para in s.text_frame.paragraphs:
                for run in para.runs:
                    assert run.font.size is not None, s.name
                    fonts.append(run.font.size.pt)
    assert not bounds, bounds
    assert min(fonts) >= 22, min(fonts)
    ratio = 160 / (p.slide_width / 914400 * 25.4)
    assert min(fonts) * ratio >= 6.8
    with ZipFile(PPTX) as z:
        forbidden = [n for n in z.namelist() if n.lower().endswith('.svg')]
        assert not forbidden
        assert all(b'image/svg+xml' not in z.read(n) and b'<asvg:' not in z.read(n)
                   for n in z.namelist() if n.endswith(('.xml', '.rels')))
        media = [n for n in z.namelist() if n.startswith('ppt/media/')]
        assert len(media) == 1 and media[0].lower().endswith('.png'), media
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
    for phrase in ('Action map A', 'N8 window', 'Neighbor encoder', 'Physics encoder',
                   'Fusion to vector c', 'Flow matching', 'ODE midpoint',
                   'Appearance preview', 'Generation Case 01'):
        assert phrase in alltext, phrase
    result = {
        'passed': True, 'slide_count': 1, 'total_objects_recursive': len(shapes),
        'object_types': dict(Counter(str(s.shape_type) for s in shapes)),
        'scope_runs': sum(len([s for s in shapes if s.name.startswith(pfx + '_run_')]) for pfx in refs),
        'scope_cells_covered': covered, 'scope_pixel_exact': True,
        'pictures': len(pictures), 'embedded_media': media,
        'text_objects': sum(s.has_text_frame and bool(s.text.strip()) for s in shapes),
        'min_font_pt': min(fonts), 'max_font_pt': max(fonts),
        'figure_width_mm': 160, 'min_reduced_font_pt': min(fonts) * ratio,
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
        slide_w_pt, slide_h_pt = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
        records, overflow = [], []

        def inspect(shapes):
            for i in range(1, shapes.Count + 1):
                s = shapes.Item(i)
                if s.Type == 6:
                    inspect(s.GroupItems)
                if s.HasTextFrame and s.TextFrame2.HasText:
                    tf, tr = s.TextFrame2, s.TextFrame2.TextRange
                    w, h = s.Width - tf.MarginLeft - tf.MarginRight, s.Height - tf.MarginTop - tf.MarginBottom
                    row = {'name': s.Name, 'text': tr.Text, 'available_pt': [w, h],
                           'bound_pt': [tr.BoundWidth, tr.BoundHeight],
                           'glyph_rect_pt': [tr.BoundLeft, tr.BoundTop, tr.BoundWidth, tr.BoundHeight],
                           'com_font': tr.Font.Name, 'com_font_size': tr.Font.Size}
                    assert tr.Font.Name == 'Times New Roman' and tr.Font.Size >= 22, row
                    records.append(row)
                    if tr.BoundWidth > w + 1.2 or tr.BoundHeight > h + 1.2:
                        overflow.append(row)
        # 与图4同款：先在 COM 新鲜时测量文字（溢出/重叠），再导出——PowerPoint 导出后常进入长忙态
        # 拒绝后续呼叫（僵尸 COM）；测量前置避开该窗口，真实字体违规立即上抛不掩盖。
        time.sleep(4)
        for walk in range(20):
            records.clear()
            overflow.clear()
            try:
                inspect(pres.Slides.Item(1).Shapes)
                break
            except AssertionError:
                raise
            except Exception:
                if walk == 19:
                    raise
                time.sleep(6)
        if export:
            slide.Export(str(PNG), 'PNG', 4000, round(4000 * slide_h_pt / slide_w_pt))
            pres.SaveAs(str(PDF), 32)
        overlaps = []
        for i, a in enumerate(records):
            ax, ay, aw, ah = a['glyph_rect_pt']
            for b in records[i + 1:]:
                bx, by, bw, bh = b['glyph_rect_pt']
                ix = min(ax + aw, bx + bw) - max(ax, bx)
                iy = min(ay + ah, by + bh) - max(ay, by)
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
            write_json('render_failure_' + str(time.time_ns()) + '.json', report)
        im = Image.open(PNG).convert('RGB')
        im.resize((1600, round(im.height * 1600 / im.width)), Image.Resampling.LANCZOS).save(OUT / 'overview.png')
        im.resize((1890, round(im.height * 1890 / im.width)), Image.Resampling.LANCZOS).save(OUT / 'print_160mm_300dpi.png', dpi=(300, 300))
        k = im.width / (pres.PageSetup.SlideWidth / 72)
        for i, key in enumerate(('input', 'encoder', 'core', 'preview')):
            im.crop((round(COLS[i] * k), round(.40 * k), round((COLS[i] + COL_W) * k), round(8.10 * k))).save(OUT / f'detail_{key}.png')
        print(json.dumps({'rendered': True, 'text_overflow_count': len(overflow), 'overflow': overflow,
                          'text_overlap_count': len(overlaps), 'overlaps': overlaps}, ensure_ascii=False, indent=2))
        assert not overflow, 'PowerPoint 实测存在文字溢出'
        assert not overlaps, 'PowerPoint 实测存在文字重叠'
        audit_exports()
    except Exception as exc:
        write_json('render_error_' + str(time.time_ns()) + '.json', {'error': repr(exc), 'pptx': str(PPTX)})
        raise
    finally:
        # 僵尸COM下Close也会拒绝呼叫，不能让它掩盖真实结果。
        try:
            if pres is not None:
                pres.Close()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def audit_exports():
    import pymupdf as fitz
    with fitz.open(PDF) as doc:
        assert len(doc) == 1
        page = doc[0]
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
                 for line_ in b['lines'] for s in line_['spans'] if s['text'].strip()]
        # 删冗+升档后文本对象38个，PDF spans下限钉38防静默丢字。
        assert len(spans) >= 38, len(spans)
        assert len(page.get_images(full=True)) == 1, '图5 PDF应含且仅含一张 Stage 4 预览位图'
        # PDF导出字号有-0.04pt舍入，阈值取标称22-0.05（与图4同款）。
        assert min(s['size'] for s in spans) >= 21.95
        assert Image.open(PNG).width == 4000
        pdf_fonts = sorted({s['font'] for s in spans})
        assert all('TimesNewRoman' in f.replace('-', '') for f in pdf_fonts), pdf_fonts
        assert not re.search(r'[\u3400-\u9fff]', page.get_text())
        assert all(f[1] != 'n/a' for f in page.get_fonts(full=True)), 'PDF字体未嵌入'
        image = Image.open(PNG).convert('RGB')
        refs = reference_images()
        scale = image.width / (page.rect.width / 72)
        checks, bad_total = {}, 0
        for prefix, source in refs.items():
            x, y, width = layout_of(prefix)
            pitch = width / 40
            bad = [(r, c) for r in range(40) for c in range(40)
                   if image.getpixel((round((x + (c + .5) * pitch) * scale), round((y + (r + .5) * pitch) * scale))) != source.getpixel((c, r))]
            checks[prefix] = {'cell_centers_checked': 1600, 'rgb_mismatches': len(bad)}
            bad_total += len(bad)
        result = {'pdf_pages': 1, 'pdf_text_spans': len(spans),
                  'pdf_min_font_pt': min(s['size'] for s in spans), 'pdf_fonts': pdf_fonts,
                  'pdf_image_objects': len(page.get_images(full=True)),
                  'pdf_vector_drawings': len(page.get_drawings()),
                  'scope_pixel_checks': checks, 'scope_rgb_mismatches': bad_total,
                  'png_pixels': Image.open(PNG).size,
                  'exports': {p.suffix: {'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
                              for p in (PPTX, PNG, PDF)}}
        assert not bad_total, result
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
