# -*- coding: utf-8 -*-
"""从真实 F1 数据重绘原生可编辑图1，并执行交付审计。"""
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
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from ppt_kit import box as native_box, pic_fit
from paper_case_labels import case_label, factory_label, CASE_PATTERN

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'docs/第一图模板.pptx'
STEM = ROOT / 'docs/figures/图1_层次化语义动作约束编译框架'
OUT = ROOT / 'outputs/fig1_pptx_20260921'
PPTX, PNG, PDF = (STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf'))
SOURCES = {
    'template': TEMPLATE,
    'prompt': ROOT / 'data/pp_test_inputs.json',
    'plan': ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_pattern_plan.json',
    'stats': ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_stats.json',
    'action_bmp': ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_output.bmp',
    'delivery_bmp': ROOT / 'outputs/factory_delivery/F1_pp01_circle_wave.bmp',
    'paper_action_png': ROOT / 'docs/images/1.png',
    'large_action_png': ROOT / 'docs/figures/assets_real/real_colormap_pp01_big.png',
    'preview': ROOT / 'outputs/factory_delivery/F1_pp01_circle_wave_preview.png',
    'photo': ROOT / 'docs/images/1真实.png',
    'palette': ROOT / 'conditional-flow-matching-main/assets/instructions.json',
    'preview_mapping': ROOT / 'scripts/gen_factory_previews.py',
    'photo_mapping': ROOT / 'scripts/make_factory_knitting_fig.py',
    'protected_system_framework': ROOT / 'docs/figures/system_framework.png',
}
INK, MUTED, BLUE = '172D42', '52677A', '497DA7'
PALETTES = [('EAF3FC', '4E86B5'), ('FBF4EB', 'D98A43'),
            ('EAF4ED', '487F55'), ('ECF4FD', '346BA2'), ('F1EDF8', '8062AA')]
COLS = [(0.16, 2.20), (2.52, 4.00), (6.67, 4.76), (11.58, 2.75), (14.48, 2.78)]
FONT = 'Microsoft YaHei'
TEXT_RECORDS = []
LANG = 'zh'
ZH_STEM, ZH_OUT = STEM, OUT
ZH_COLS = COLS
ACTION_LAYOUT = (11.82, 2.07, 2.26)
VISUAL_RECORDS = []


def configure_language(lang):
    # 默认中文路径和布局不变；英文另存，绝不复用中文交付文件名。
    global LANG, STEM, OUT, PPTX, PNG, PDF, FONT, COLS, ACTION_LAYOUT
    LANG = lang
    STEM = ZH_STEM if lang == 'zh' else ROOT / 'docs/figures/Fig1_Hierarchical_Semantic_Action_Compilation_EN'
    OUT = ZH_OUT if lang == 'zh' else ROOT / 'outputs/fig1_pptx_en_20260921'
    PPTX, PNG, PDF = (STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf'))
    FONT = 'Microsoft YaHei' if lang == 'zh' else 'Times New Roman'
    COLS = ZH_COLS if lang == 'zh' else [(0.16, 2.30), (2.60, 3.40), (6.14, 5.24), (11.52, 2.90), (14.56, 2.70)]
    ACTION_LAYOUT = (11.82, 2.07, 2.26) if lang == 'zh' else (11.62, 2.10, 2.70)


def protect_originals(create=False):
    # 首次构建前冻结基线；独立复核不得重置已有哈希。
    path = OUT / 'protected_originals.json'
    if path.exists():
        baseline = json.loads(path.read_text(encoding='utf-8'))
        for item in baseline.values():
            assert sha(item['path']) == item['sha256'], f"受保护文件已改变: {item['path']}"
        return baseline
    assert create, '缺少构建前保护基线，不能以当前文件冒充原始哈希'
    files = set(SOURCES.values()) | {ZH_STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf')}
    files |= set((ROOT / 'docs/images').glob('*'))
    files |= set((ROOT / 'docs/figures/assets_real').glob('*'))
    baseline = {str(p.relative_to(ROOT)): {'path': str(p), 'sha256': sha(p)} for p in sorted(files) if p.is_file()}
    assert all(str(ZH_STEM.with_suffix(ext).relative_to(ROOT)) in baseline for ext in ('.pptx', '.png', '.pdf'))
    write_json('protected_originals.json', baseline)
    return baseline


def english_sample():
    # 只读取历史输出；按已核验的 lowering 几何公式生成掩膜，绝不重新运行生成器。
    import numpy as np
    grid = Image.open(SOURCES['action_bmp']).convert('RGB')
    plan = json.loads(SOURCES['plan'].read_text(encoding='utf-8'))
    stats = json.loads(SOURCES['stats'].read_text(encoding='utf-8'))
    motifs = {m['motif_id']: m for m in plan['motifs']}
    assert len(motifs) == 4 and motifs['wave_1']['parent_id'] == 'circle_1'
    assert motifs['circle_1']['region']['center'] == [20, 20]
    assert motifs['circle_1']['region']['size'] == 20
    assert motifs['frame_1']['params']['border_thickness'] == 2
    assert motifs['wave_1']['params'] == {'period_x': 5, 'period_y': 4, 'split_col_offset': 2, 'tuck_col_offset': 3, 'thickness': 2}
    palette = json.loads(SOURCES['palette'].read_text(encoding='utf-8'))['instructions']
    colors = {i: tuple(bytes.fromhex(palette[i]['color'][1:])) for i in (0, 1, 7, 8)}
    assert colors == {0: (255, 0, 16), 1: (43, 206, 72), 7: (0, 164, 255), 8: (255, 230, 6)}
    npy = SOURCES['action_bmp'].parent / 'intermediate/pp_01_action.npy'
    actions = np.load(npy, allow_pickle=False)
    assert actions.shape == (40, 40)
    assert set(np.unique(actions).tolist()) == {0, 1, 7, 8}, '本例不能出现移针'
    assert all(grid.getpixel((c, r)) == colors[int(actions[r, c])] for r in range(40) for c in range(40))
    full = {(r, c) for r in range(40) for c in range(40)}
    masks = {'bg': full,
             'frame_1': {(r, c) for r, c in full if 15 < max(abs(r-20), abs(c-20)) <= 17},
             'circle_1': {(r, c) for r, c in full if (r-20)**2+(c-20)**2 <= 13**2},
             'wave_1': {(r, c) for r, c in full if (r-20)**2+(c-20)**2 <= 12**2}}
    assert {k: len(v) for k, v in masks.items()} == {'bg': 1600, 'frame_1': 264, 'circle_1': 529, 'wave_1': 441}
    assert masks['wave_1'] <= masks['circle_1']
    green = {(r, c) for r, c in full if grid.getpixel((c, r)) == colors[1]}
    assert green == masks['frame_1'] | (masks['circle_1'] - masks['wave_1'])
    pairs = [(r, c) for r in (11, 15, 19, 23, 27) for c in ((17, 22) if r in (11, 27) else (12, 17, 22, 27))]
    assert {(r, c) for r, c in full if actions[r, c] == 8} == set(pairs)
    assert {(r, c) for r, c in full if actions[r, c] == 7} == {(r, c+1) for r, c in pairs}
    assert len(pairs) == 16 and stats['total_events'] == 32
    crop_box = (15, 17, 22, 22)
    crop = actions[17:22, 15:22]
    expected = np.zeros((5, 7), dtype=actions.dtype)
    expected[2, 2:4] = [8, 7]
    assert np.array_equal(crop, expected)
    assert all(actions[20, c] == 0 for c in (17, 18))
    assert all(stats['violations'][k] == 0 for k in ('hard_before', 'craft_before', 'hard_after', 'craft_after'))
    assert stats['llm_repair']['rounds'] == stats['llm_repair']['edits'] == 0
    evidence = {
        'sample': 'F1 / pp_01', 'historical_grid_only': True,
        'npy': {'path': str(npy), 'sha256': sha(npy), 'role': '历史最终动作网格，不是修复前网格', 'bmp_pixels_equal': True},
        'geometry_source': {'path': str(ROOT / 'generator_one/generation/visual_to_realization.py'), 'lines': [526, 705],
                            'sha256': sha(ROOT / 'generator_one/generation/visual_to_realization.py')},
        'mask_formula': {'center_rc': [20, 20], 'frame_half_size': 17, 'frame_thickness': 2, 'circle_radius': 13, 'wave_radius': 12},
        'mask_areas': {k: len(v) for k, v in masks.items()}, 'masks_overlap': True,
        'green_mask_cells': len(green), 'green_mask_bmp_different_cells': 0,
        'event_admission_radius_not_wave_mask': {'radius': 10, 'area': 317, 'used_as_wave_mask': False},
        'event_pairs': [{'split_rc': [r, c], 'tuck_rc': [r, c+1]} for r, c in pairs],
        'event_count': 32, 'group_count': 16, 'transfer_count': 0,
        'crop_pil_ltrb': crop_box, 'crop_indexing': '零基；右/下边界不包含', 'crop_shape_rows_cols': [5, 7],
        'crop_action_ids': crop.tolist(), 'support_row': 20, 'support_actions': ['f_knit', 'f_knit'],
        'violations': stats['violations'], 'repair': stats['llm_repair'],
        'recomputed_grid_used': False, 'llm_or_simulation_run': False,
        'layer_subsets': {'crafts': [0, 1], 'crafts_event_cells_base_craft': [7, 8],
                          'events': [7, 8], 'full': [0, 1, 7, 8]},
        'pairing_boundary': '照片归属依据用户确认和F1映射；几何/纹理对应仅作图像观察，不声称逐针机器等价。工厂自行CAD转换。',
    }
    prior_path = OUT / 'sample_evidence.json'
    if prior_path.exists():
        prior = json.loads(prior_path.read_text(encoding='utf-8'))
        for key in ('npy', 'geometry_source'):
            assert prior[key]['sha256'] == evidence[key]['sha256'], f'证据源发生变化: {key}'
    write_json('sample_evidence.json', evidence)
    return grid, masks, pairs, actions


def audit_english(p, shapes):
    # 针对真实数据独立重算像素、掩膜及点位；不仅核对记录数量。
    from lxml import etree
    grid, masks, pairs, actions = english_sample()
    by_name = {s.name: s for s in shapes}
    manifest = json.loads((OUT / 'native_visual_manifest.json').read_text(encoding='utf-8'))
    for rec in manifest:
        prefix, x, y, width = rec['prefix'], *rec['layout']
        found = [s for s in shapes if s.name.startswith(prefix+'_cell_')]
        if rec['kind'] == 'crop':
            image = grid.crop((15, 17, 22, 22))
            points = {(r, c) for r in range(5) for c in range(7)}
            pitch = width / 7
        else:
            image = grid
            points = {(r, c+d) for r, c in pairs for d in (0, 1)}
            pitch = width / 40
        if rec['kind'] in ('crop', 'events'):
            assert len(found) == len(points), prefix
            for r, c in points:
                s = by_name[f'{prefix}_cell_{r:02}_{c:02}']
                assert tuple(s.fill.fore_color.rgb) == image.getpixel((c, r)), s.name
                for actual, want in zip((s.left, s.top, s.width, s.height), (x+c*pitch, y+r*pitch, pitch, pitch)):
                    assert abs(actual-Inches(want)) <= 3, s.name
        else:
            if rec['kind'] == 'layer':
                # 分层色块：逐run核对颜色、几何、极大性，并核对覆盖集合等于keep子集。
                keep = set(rec['keep'])
                recolor = {int(k): tuple(bytes.fromhex(v)) for k, v in rec.get('recolor', {}).items()}
                drawn = keep | set(recolor)
                def expect(rr, cc):
                    return recolor.get(int(actions[rr, cc]), image.getpixel((cc, rr)))
                want = {(r, c) for r in range(40) for c in range(40) if int(actions[r, c]) in drawn}
                covered = set()
                for s in [s for s in shapes if s.name.startswith(prefix+'_run_')]:
                    r, start, end = (int(v) for v in s.name.rsplit('_', 3)[1:])
                    rgb = expect(r, start)
                    assert tuple(s.fill.fore_color.rgb) == rgb, s.name
                    assert all(int(actions[r, c]) in drawn and expect(r, c) == rgb
                               for c in range(start, end)), s.name
                    assert start == 0 or int(actions[r, start-1]) not in drawn or expect(r, start-1) != rgb, s.name
                    assert end == 40 or int(actions[r, end]) not in drawn or expect(r, end) != rgb, s.name
                    for actual, val in zip((s.left, s.top, s.width, s.height),
                                           (x+start*width/40, y+r*width/40, (end-start)*width/40, width/40)):
                        assert abs(actual-Inches(val)) <= 3, s.name
                    cells = {(r, c) for c in range(start, end)}
                    assert not covered & cells
                    covered |= cells
                assert covered == want, prefix
                continue
            want = masks[rec['mask']]
            covered = set()
            runs = [s for s in shapes if s.name.startswith(prefix+'_run_')]
            for s in runs:
                r, start, end = (int(v) for v in s.name.rsplit('_', 3)[1:])
                assert tuple(s.fill.fore_color.rgb) == tuple(bytes.fromhex(rec['color']))
                for actual, val in zip((s.left, s.top, s.width, s.height), (x+start*width/40, y+r*width/40, (end-start)*width/40, width/40)):
                    assert abs(actual-Inches(val)) <= 3, s.name
                cells = {(r, c) for c in range(start, end)}
                assert not covered & cells
                covered |= cells
            assert covered == want, prefix
    fonts, text_count = set(), 0
    with ZipFile(PPTX) as z:
        for name in z.namelist():
            if not name.endswith('.xml'):
                continue
            root = etree.fromstring(z.read(name))
            for node in root.iter():
                if 'typeface' in node.attrib:
                    fonts.add(node.get('typeface'))
                if node.tag == qn('a:t'):
                    assert not re.search(r'[\u3400-\u9fff]', node.text or ''), (name, node.text)
                    text_count += 1
        assert fonts == {'Times New Roman'}, fonts
    for s in shapes:
        if s.has_text_frame:
            for para in s.text_frame.paragraphs:
                for run in para.runs:
                    assert run.font.name == 'Times New Roman'
                    assert run.font.size.pt >= 18
    assert not re.search(r'[\u3400-\u9fff]', p.slides[0].notes_slide.notes_text_frame.text)
    protect_originals()
    write_json('english_audit.json', {'passed': True, 'all_package_typefaces': sorted(fonts),
               'package_text_nodes_checked': text_count, 'han_characters': 0,
               'native_diagrams_checked': manifest, 'square_crop_cells': True,
               'historical_event_positions_exact': True, 'mask_geometry_exact': True,
               'protected_originals_unchanged': True, 'source_pairing_is_not_stitch_equivalence': True})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def flatten(shapes):
    for s in shapes:
        yield s
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from flatten(s.shapes)


def inspect_sources():
    # 2026-09-29 模板文件已随docs整理移除；幻灯片尺寸与模板元数据改依source_evidence.json冻结证据。
    if TEMPLATE.exists():
        prs = Presentation(TEMPLATE)
        tpl = {'template_inches': [prs.slide_width / 914400, prs.slide_height / 914400],
               'template_slide_count': len(prs.slides),
               'template_shape_types': dict(Counter(str(s.shape_type) for s in flatten(prs.slides[0].shapes)))}
    else:
        cand = OUT / 'source_evidence.json'
        if not cand.exists():
            cand = (ZH_OUT if LANG == 'en' else ROOT / 'outputs/fig1_pptx_en_20260921') / 'source_evidence.json'
        ev = json.loads(cand.read_text(encoding='utf-8'))
        tpl = {k: ev[k] for k in ('template_inches', 'template_slide_count', 'template_shape_types')}
    grid = Image.open(SOURCES['action_bmp']).convert('RGB')
    plan = json.loads(SOURCES['plan'].read_text(encoding='utf-8'))
    motifs = {m['motif_id']: m for m in plan['motifs']}
    assert len(motifs) == 4 and motifs['wave_1']['parent_id'] == 'circle_1'
    assert grid.size == (40, 40)
    compare = {}
    for key in ('delivery_bmp', 'paper_action_png', 'large_action_png'):
        im = Image.open(SOURCES[key]).convert('RGB')
        reduced = im.resize(grid.size, Image.Resampling.NEAREST)
        compare[key] = {
            'size': im.size, 'same_40x40_pixels': reduced.tobytes() == grid.tobytes(),
            'different_cells': sum(a != b for a, b in zip(reduced.get_flattened_data(), grid.get_flattened_data())),
            'colors': [{'rgb': rgb, 'count': n} for rgb, n in Counter(reduced.get_flattened_data()).items()],
        }
        if key != 'paper_action_png':
            assert compare[key]['same_40x40_pixels'], key
    report = {
        'sample': 'F1 / pp_01',
        **tpl,
        'sources': {k: {'path': str(p), 'sha256': sha(p)} for k, p in SOURCES.items() if p.exists()},
        'pixel_equivalence': compare,
        'action_colors': [{'rgb': rgb, 'count': count} for rgb, count in Counter(grid.get_flattened_data()).items()],
        'motif_hierarchy': {m['motif_id']: m['parent_id'] for m in plan['motifs']},
        'source_notes': {
            'preview': 'gen_factory_previews.py 的 JOBS 将 pp_01_output.bmp 配对至 F1 预览；现有文件为 Stage 4、320×320。未重新推理。',
            'photo': 'make_factory_knitting_fig.py 的 F1 行映射至 docs/images/1真实.png；独立嵌入原图，不更改织物内容。',
            'boundary': '预览是辅助视觉结果；工厂通过自身 CAD 打版转换，非系统自动输出机器代码。',
            'excluded_asset': 'docs/images/1.png 与 F1 原始 BMP 存在490格差异，不用于本图；实物归属依据用户确认与现有 F1 行映射，不以该旧色码图证明配对。',
        },
    }
    prior_path = OUT / 'source_evidence.json'
    if prior_path.exists():
        prior = json.loads(prior_path.read_text(encoding='utf-8'))
        for key, record in prior['sources'].items():
            if key not in report['sources']:
                # 2026-09-29 随docs整理移除的源（如模板）不再参与哈希比对；存在性过滤已记入report。
                continue
            assert report['sources'][key]['sha256'] == record['sha256'], f'源文件在交付期间发生变化: {key}'
    write_json('source_evidence.json', report)
    print(json.dumps({'source_check': '通过', 'sample': report['sample'], 'pixel_equivalence': {k: v['different_cells'] for k, v in compare.items()}}, ensure_ascii=False))
    return report


def audit_deck():
    assert PPTX.exists(), '交付 PPTX 尚未构建'
    p = Presentation(PPTX)
    assert len(p.slides) == 1
    shapes = list(flatten(p.slides[0].shapes))
    cells = [s for s in shapes if s.name.startswith('action_cell_')]
    assert len(cells) == 1600, f'动作格应为1600，实际{len(cells)}'
    im = Image.open(SOURCES['action_bmp']).convert('RGB')
    for s in cells:
        _, _, row, col = s.name.split('_')
        assert tuple(s.fill.fore_color.rgb) == im.getpixel((int(col), int(row))), s.name
        assert s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
        gx, gy, gw = ACTION_LAYOUT
        assert abs(s.left-Inches(gx+int(col)*gw/40)) <= 2, s.name
        assert abs(s.top-Inches(gy+int(row)*gw/40)) <= 2, s.name
        assert abs(s.width-Inches(gw/40)) <= 2, s.name
        assert abs(s.height-Inches(gw/40)) <= 2, s.name
    pictures = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    want = ('photo',) if LANG == 'en' else ('preview', 'photo')
    assert len(pictures) == len(want), f'嵌入独立图片应为{want}'
    expected = {sha(SOURCES[k]) for k in want}
    assert {hashlib.sha256(s.image.blob).hexdigest() for s in pictures} == expected
    assert all(s.width * s.height < p.slide_width * p.slide_height * 0.15 for s in pictures)
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
    assert min(fonts) >= 18, min(fonts)
    ratio = 160 / (p.slide_width / 914400 * 25.4)
    assert min(fonts) * ratio >= 6
    with ZipFile(PPTX) as z:
        forbidden = [n for n in z.namelist() if n.lower().endswith('.svg')]
        assert not forbidden
        assert all(b'image/svg+xml' not in z.read(n) and b'<asvg:' not in z.read(n)
                   for n in z.namelist() if n.endswith(('.xml', '.rels')))
        media = [n for n in z.namelist() if n.startswith('ppt/media/')]
    evidence = json.loads((OUT / 'source_evidence.json').read_text(encoding='utf-8'))
    for item in evidence['sources'].values():
        assert sha(item['path']) == item['sha256'], item['path']
    names = {s.name for s in shapes}
    assert {'edit_origin_action_fields', 'edit_return_to_ir', 'tree_edge_circle_1_wave_1'} <= names
    alltext = '\n'.join(s.text for s in shapes if s.has_text_frame)
    if LANG == 'en':
        assert not CASE_PATTERN.search(alltext), '英文图面不得残留原始案例编号'
        # 展示名可能按排版换行（如块1标题），压平空白后比对。
        compact_text = ' '.join(alltext.split())
        assert case_label('pp_01') in compact_text and factory_label(1) in compact_text
    plan = json.loads(SOURCES['plan'].read_text(encoding='utf-8'))
    motifs = {m['motif_id']: m for m in plan['motifs']}
    for mid in motifs:
        assert 'tree_node_'+mid in names
    assert motifs['wave_1']['parent_id'] == 'circle_1'
    assert [m['motif_id'] for m in plan['motifs'] if m['parent_id'] is None] == ['frame_1', 'circle_1', 'bg']
    assert motifs['circle_1']['region']['center'] == [20, 20]
    assert motifs['circle_1']['region']['size'] == 20
    assert motifs['frame_1']['params']['border_thickness'] == 2
    assert motifs['wave_1']['params'] == {'period_x': 5, 'period_y': 4, 'split_col_offset': 2, 'tuck_col_offset': 3, 'thickness': 2}
    stats = json.loads(SOURCES['stats'].read_text(encoding='utf-8'))
    assert stats['violations']['hard_after'] == stats['violations']['craft_after'] == 0
    phrases = ('线圈支撑', '转移关系', '堆叠上限', '区域作用域', '成组完整性', '保守修复',
               '用户编辑', '目标字段更新', '局部重新编译', '工厂 CAD', '辅助视觉预览') if LANG == 'zh' else (
               'Constraint checks &', 'conservative repair',
               'Visual target', 'Sparse event', 'Action grid')
    # 2026-09-29 英文版已删 Factory CAD / 辅助预览图面元素；导师标准第二轮再删横带链词与H1–H8注（图注/正文逐字承载），短语清单同步；中文路径不变。
    for phrase in phrases:
        assert phrase in alltext, phrase
    if LANG == 'en':
        audit_english(p, shapes)
    result = {
        'passed': True, 'slide_count': 1, 'total_objects_recursive': len(shapes),
        'top_level_objects': len(p.slides[0].shapes),
        'object_types': dict(Counter(str(s.shape_type) for s in shapes)),
        'main_action_cells': len(cells), 'main_action_pixels_exact': True,
        'independent_pictures': len(pictures), 'image_media': media,
        'picture_area_fractions': {s.name: s.width * s.height / (p.slide_width * p.slide_height) for s in pictures},
        'text_objects': sum(s.has_text_frame and bool(s.text.strip()) for s in shapes),
        'min_font_pt': min(fonts), 'max_font_pt': max(fonts),
        'figure_width_mm': 160, 'reduction_ratio': ratio, 'min_reduced_font_pt': min(fonts) * ratio,
        'shape_out_of_slide': bounds, 'svg_files': forbidden, 'protected_sources_unchanged': True,
        'pptx_sha256': sha(PPTX),
    }
    write_json('object_audit.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def shape(sl, name, x, y, w, h, fill=None, line=None, kind='rect', lw=1):
    s = native_box(sl, x, y, w, h, fill=fill, line=line, lw=lw, shape=kind, adj=0.08)
    s.name = name
    return s


def text(sl, name, x, y, w, h, value, size=20, color=INK, bold=False, align='left', font=None):
    font = font or FONT
    # 根据微软雅黑实测行高留足空间，不缩小字号；保留原定视觉中心。
    count = value.count('\n') + 1
    min_h = size * (1.30*count + .05*(count-1)) / 72
    if h < min_h:
        y -= (min_h-h)/2
        h = min_h
    s = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    s.name = name
    tf = s.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, line in enumerate(value.split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}[align]
        p.space_before = p.space_after = Pt(0)
        p.line_spacing = 1.08
        r = p.add_run()
        r.text = line
        r.font.name, r.font.size, r.font.bold = font, Pt(size), bold
        from pptx.dml.color import RGBColor
        r.font.color.rgb = RGBColor.from_string(color)
        rp = r._r.get_or_add_rPr()
        ea = OxmlElement('a:ea')
        ea.set('typeface', FONT)
        rp.append(ea)
    TEXT_RECORDS.append({'name': name, 'text': value, 'font_pt': size, 'box_inches': [x, y, w, h]})
    return s


def line(sl, name, x1, y1, x2, y2, color=BLUE, width=1.5, arrow=False):
    s = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    s.name = name
    style = s._element.find(qn('p:style'))
    if style is not None:
        s._element.remove(style)
    from pptx.dml.color import RGBColor
    s.line.color.rgb = RGBColor.from_string(color)
    s.line.width = Pt(width)
    if arrow:
        tip = OxmlElement('a:tailEnd')
        tip.set('type', 'triangle')
        tip.set('w', 'med')
        tip.set('len', 'med')
        s._element.spPr.find(qn('a:ln')).append(tip)
    return s


def grouped(sl, name, elements):
    g = sl.shapes.add_group_shape(elements)
    g.name = name
    return g


def cell_grid(sl, image, x, y, size, prefix, preserve_aspect=False, mesh=True):
    n, m = image.size
    height = size*m/n if preserve_aspect else size
    elements = []
    for r in range(m):
        for c in range(n):
            rgb = ''.join(f'{k:02X}' for k in image.getpixel((c, r)))
            elements.append(shape(sl, f'{prefix}_{r:02}_{c:02}', x+c*size/n, y+r*height/m,
                                  size/n, height/m, rgb))
    # 中文版保留细网格线；英文版按论文图11口径改为实心色块，不叠白色网格。
    if mesh and prefix == 'action_cell':
        for k in range(n+1):
            elements.append(line(sl, f'grid_vertical_{k}', x+k*size/n, y, x+k*size/n, y+size, 'FFFFFF', 0.13))
        for k in range(m+1):
            elements.append(line(sl, f'grid_horizontal_{k}', x, y+k*size/m, x+size, y+k*size/m, 'FFFFFF', 0.13))
    return grouped(sl, prefix.replace('_cell', '_grid')+'_editable_group', elements)


def check_icon(sl, name, x, y, size=0.22, color='487F55'):
    shape(sl, name+'_disc', x, y, size, size, color, kind='oval')
    line(sl, name+'_a', x+size*.23, y+size*.52, x+size*.43, y+size*.70, 'FFFFFF', 1.5)
    line(sl, name+'_b', x+size*.43, y+size*.70, x+size*.78, y+size*.30, 'FFFFFF', 1.5)


def scope_sketch(sl, name, x, y, w, h, color=BLUE):
    shape(sl, name+'_frame', x, y, w, h, None, color, lw=1.8)
    shape(sl, name+'_circle', x+w*.20, y+h*.17, w*.60, h*.66, None, color, 'oval', 1.6)
    for r in range(3):
        for c in range(3):
            shape(sl, f'{name}_dot_{r}_{c}', x+w*(.34+c*.14), y+h*(.30+r*.17), .055, .055, color, kind='oval')


def build_deck():
    source = inspect_sources()
    prs = Presentation()
    prs.slide_width, prs.slide_height = (Inches(v) for v in source['template_inches'])
    prs.core_properties.title = '层次化语义动作约束编译框架'
    prs.core_properties.subject = 'F1 / pp_01；原生可编辑论文图1'
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    TEXT_RECORDS.clear()
    headers = [('设计意图', '自然语言输入', 24), ('层次化制造 IR', 'PatternPlan', 27),
               ('事件级约束编译', '设计语义 → 受约束动作', 28),
               ('可编辑动作图', 'ActionGrid', 23), ('工厂实物验证', 'F1 / pp_01', 23)]
    for i, ((x, w), (bg, accent), (title, sub, fs)) in enumerate(zip(COLS, PALETTES, headers)):
        shape(sl, f'column_{i+1}', x, .40, w, 8.16, bg, kind='round')
        shape(sl, f'number_disc_{i+1}', x+.12, .57, .47, .47, accent, kind='oval')
        text(sl, f'number_{i+1}', x+.12, .57, .47, .47, str(i+1), 30, 'FFFFFF', align='center', font='Georgia')
        text(sl, f'heading_{i+1}', x+.66, .58, w-.71, .46, title, fs, bold=True)
        text(sl, f'subheading_{i+1}', x+.12, 1.12, w-.24, .35, sub, 20, accent, align='center')
        if i > 0:
            shape(sl, f'inner_panel_{i+1}', x+.11, 1.61, w-.22, 6.84, 'FFFFFF', bg, 'round', 1.1)

    # ① 自然语言与原生设计师图标；不复用模板人物图像。
    shape(sl, 'intent_speech', .34, 1.87, 1.83, 2.55, 'FFFFFF', '94B6D1', 'round', 1.4)
    text(sl, 'prompt_verbatim_reflow', .41, 2.08, 1.69, 2.11,
         '矩形边框，\n内部圆形，\n圆形内\n波浪吊目，\n背景平针。', 22, bold=True, align='center')
    shape(sl, 'speech_tail', 1.18, 4.38, .28, .22, 'FFFFFF', '94B6D1', 'down')
    shape(sl, 'designer_head', .65, 4.99, .42, .42, 'FFFFFF', BLUE, 'oval', 2)
    shape(sl, 'designer_body', .46, 5.43, .80, .69, '709ABD', kind='round')
    shape(sl, 'designer_screen', 1.02, 5.22, .98, .73, 'FFFFFF', BLUE, 'round', 2)
    scope_sketch(sl, 'screen_drawing', 1.20, 5.35, .61, .43)
    line(sl, 'screen_stand', 1.51, 5.96, 1.51, 6.16, BLUE, 2)
    line(sl, 'designer_table', .48, 6.16, 2.00, 6.16, BLUE, 2)
    text(sl, 'designer_label', .31, 6.36, 1.89, .38, '用户 / 设计师', 21, BLUE, True, 'center')
    scope_sketch(sl, 'intent_geometry', .64, 6.98, 1.22, .94)
    text(sl, 'intent_components', .27, 8.08, 1.98, .30, '几何 · 纹理 · 层级', 18, MUTED, align='center')

    # ② 四个实际 motif：三个根级区域，wave_1 为 circle_1 的子节点。
    shape(sl, 'plan_root', 2.78, 1.80, 3.48, .54, 'EEE8F6', 'A294C3', 'round')
    text(sl, 'plan_root_text', 2.89, 1.83, 3.26, .47, 'framed  ·  40 × 40', 22, bold=True, align='center')
    line(sl, 'tree_trunk', 2.89, 2.34, 2.89, 4.41, 'A4AEB8', 1.5)
    nodes = [('bg', '背景平针', 'panel · plain', 2.51, 'EDF1F5', '8A9BAA'),
             ('frame_1', '矩形边框', 'frame · plain', 3.31, 'EAF2FB', '709FCC'),
             ('circle_1', '圆形区域', 'circle · plain', 4.11, 'EAF4E9', '76A974')]
    for mid, title, sub, y, fill, accent in nodes:
        line(sl, 'tree_edge_root_'+mid, 2.89, y+.31, 3.10, y+.31, 'A4AEB8', 1.5, True)
        shape(sl, 'tree_node_'+mid, 3.13, y, 3.02, .66, fill, accent, 'round')
        text(sl, 'node_label_'+mid, 3.25, y+.02, 2.78, .30, f'{mid}  {title}', 19, bold=True)
        text(sl, 'node_type_'+mid, 3.25, y+.34, 2.78, .27, sub, 18, MUTED, font='Aptos')
    line(sl, 'tree_child_vertical', 3.32, 4.77, 3.32, 5.27, '76A974', 1.7)
    line(sl, 'tree_edge_circle_1_wave_1', 3.32, 5.27, 3.58, 5.27, '76A974', 1.7, True)
    shape(sl, 'tree_node_wave_1', 3.61, 4.95, 2.54, .66, 'FFF0DE', 'D49D58', 'round')
    text(sl, 'wave_label', 3.72, 4.98, 2.33, .30, 'wave_1  波浪吊目', 19, bold=True)
    text(sl, 'wave_type', 3.72, 5.31, 2.33, .27, 'circle · wave_tuck', 18, MUTED, font='Aptos')
    line(sl, 'attribute_divider', 2.78, 5.88, 6.25, 5.88, 'E6D6C4', 1)
    text(sl, 'attribute_title', 2.79, 6.02, 3.46, .35, '区域属性与纹理参数', 22, '9E652F', True)
    fields = ['region.center = [20, 20]', 'region.size = 20', 'border_thickness = 2',
              'period_x = 5  ·  period_y = 4', 'split_col_offset = 2', 'tuck_col_offset = 3']
    for i, value in enumerate(fields):
        text(sl, f'actual_field_{i}', 2.82, 6.45+i*.322, 3.40, .34, value, 19, INK, font='Aptos')

    # ③ 制造约束三组图解与三步编译机制，全部为原生形状。
    shape(sl, 'constraints_band', 6.90, 1.79, 4.30, .46, 'E8EDEB', kind='round')
    text(sl, 'constraints_title', 7.03, 1.84, 4.04, .34, '制造约束', 24, bold=True, align='center')
    for x in (8.32, 9.80):
        line(sl, 'constraint_separator_'+str(x), x, 2.44, x, 4.12, 'D9E1E0', 1)
    for r in range(2):
        for c in range(3):
            shape(sl, f'loop_{r}_{c}', 7.14+c*.21, 2.54+r*.30, .17, .33, None, INK, 'oval', 1.6)
    line(sl, 'transfer_relation', 7.72, 2.87, 8.02, 2.65, INK, 1.7, True)
    for r in range(4):
        for c in range(4):
            shape(sl, f'scope_constraint_{r}_{c}', 8.62+c*.20, 2.49+r*.20, .20, .20,
                  'CCE0CE' if 0 < r < 3 and 0 < c < 3 else 'FFFFFF', INK, lw=.8)
    for r in range(3):
        shape(sl, f'stack_limit_{r}', 9.52, 2.55+r*.20, .14, .16, '709A75')
    shape(sl, 'group_integrity_frame', 10.04, 2.61, .93, .47, 'F9FBFC', INK, 'round', 1.6)
    shape(sl, 'group_integrity_split', 10.14, 2.72, .26, .25, 'FFE606', INK, lw=.7)
    shape(sl, 'group_integrity_tuck', 10.61, 2.72, .26, .25, '00A4FF', INK, lw=.7)
    line(sl, 'group_integrity_link', 10.40, 2.84, 10.61, 2.84, INK, 2)
    for x, title, sub in [(6.99, '线圈支撑', '转移关系'), (8.46, '堆叠上限', '区域作用域'), (9.94, '成组完整性', '劈针＋集圈')]:
        text(sl, 'constraint_'+title, x-.125, 3.50, 1.42, .35, title, 19 if len(title)>4 else 20, bold=True, align='center')
        text(sl, 'constraint_'+sub, x-.125, 3.88, 1.42, .34, sub, 19, MUTED, align='center')
    shape(sl, 'constraints_down', 8.92, 4.34, .28, .30, '91AD9B', kind='down')
    shape(sl, 'compiler_head', 6.91, 4.72, 4.28, .49, 'E4F1E6', kind='round')
    text(sl, 'compiler_title', 7.01, 4.79, 4.08, .34, '事件级编译机制', 24, bold=True, align='center')
    stage_x = [6.92, 8.40, 9.88]
    fills = ['EEF6FC', 'FFF4E7', 'F1EDFB']
    for i, x in enumerate(stage_x):
        shape(sl, f'compiler_stage_{i+1}', x, 5.34, 1.31, 2.66, fills[i], kind='round')
        text(sl, f'compiler_stage_label_{i+1}', x+.03, 5.48, 1.25, .68,
             ['1 作用域\n构建', '2 稀疏\n事件规划', '3 约束\n合成'][i], 20, bold=True, align='center')
    for off in (.30, .15, 0):
        shape(sl, 'mask_layer_'+str(off), 7.09+off*.20, 6.34+off, .88, .51, 'E6F0F8', '9EBAD0', lw=1)
    shape(sl, 'mask_circle', 7.34, 6.51, .42, .34, '90B6D4', kind='oval')
    shape(sl, 'event_group_box', 8.55, 6.42, 1.00, .63, None, 'B9834D', 'round', 1.4)
    shape(sl, 'event_split', 8.67, 6.58, .29, .29, 'FFE606', INK, lw=.7)
    shape(sl, 'event_tuck', 9.14, 6.58, .29, .29, '00A4FF', INK, lw=.7)
    line(sl, 'event_pair_connection', 8.96, 6.72, 9.14, 6.72, INK, 1.8)
    grid = Image.open(SOURCES['action_bmp']).convert('RGB')
    cell_grid(sl, grid.crop((10, 10, 18, 18)), 10.09, 6.29, .90, 'mechanism_crop_cell')
    for i, x in enumerate(stage_x):
        text(sl, f'compiler_caption_{i+1}', x+.02, 7.34, 1.27, .57,
             ['父子区域\n掩膜裁剪', '成组事件\n整组取舍', '约束检查\n保守修复'][i], 19, align='center')
    for x in (8.23, 9.71):
        shape(sl, 'compiler_arrow_'+str(x), x, 6.65, .18, .19, '88A6BD', kind='arrow')
    text(sl, 'compiler_schematic_note', 7.03, 8.10, 4.01, .30, '机制示意：异常时执行保守修复', 18, MUTED, align='center')

    # ④ 1600个矩形逐格保留原始RGB；预览为同一F1的独立图片。
    text(sl, 'action_title', 11.77, 1.69, 2.37, .34, '40 × 40 动作色码', 20, bold=True, align='center')
    cell_grid(sl, grid, 11.82, 2.07, 2.26, 'action_cell')
    shape(sl, 'action_outline', 11.815, 2.065, 2.27, 2.27, None, '7C98AE', lw=1)
    palette = [('f_knit', 'FF0010'), ('b_knit', '2BCE48'), ('f_split', 'FFE606'), ('f_tuck', '00A4FF')]
    for i, (abbr, rgb) in enumerate(palette):
        x, y = 11.84+(i%2)*1.13, 4.38+(i//2)*.33
        shape(sl, 'legend_swatch_'+abbr, x, y+.05, .17, .17, rgb, '8C9DAA', lw=.5)
        text(sl, 'legend_'+abbr, x+.23, y, .85, .28, abbr, 18, font='Aptos')
    check_icon(sl, 'rules_pass', 11.84, 5.17, .20)
    text(sl, 'rule_count', 12.09, 5.12, .82, .32, '违例 0', 18, '487F55')
    shape(sl, 'edit_origin_action_fields', 12.96, 5.08, 1.17, .40, 'E3EEF9', '8CADCA', 'round')
    text(sl, 'edit_origin_label', 13.00, 5.11, 1.09, .33, '字段编辑', 18, '346BA2', True, 'center')
    line(sl, 'preview_divider', 11.81, 5.59, 14.08, 5.59, 'C4D7EA', 1)
    text(sl, 'preview_title', 11.78, 5.68, 2.33, .35, '辅助视觉预览', 21, bold=True, align='center')
    text(sl, 'preview_id', 11.82, 6.07, 2.26, .32, 'Stage 4 · F1 / pp_01', 18, MUTED, align='center', font='Aptos')
    p = pic_fit(sl, SOURCES['preview'], 11.975, 6.45, 1.95, 1.95, frame=False)
    p.name = 'F1_pp01_stage4_preview'

    # ⑤ 真实照片和工厂转换责任边界；不使用机器或纹理占位素材。
    p = pic_fit(sl, SOURCES['photo'], 14.69, 1.81, 2.36, 3.00, frame=False)
    p.name = 'F1_factory_photo_user_confirmed'
    text(sl, 'photo_caption', 14.67, 4.80, 2.40, .35, 'F1 实织样片', 21, '71559A', True, 'center')
    line(sl, 'factory_divider', 14.73, 5.30, 17.03, 5.30, 'DCD3EB', 1)
    shape(sl, 'factory_workflow_box', 14.70, 5.49, 2.34, 1.26, 'F5F2FA', kind='round')
    text(sl, 'factory_cad_title', 14.77, 5.61, 2.20, .33, '工厂 CAD 打版', 21, '71559A', True, 'center')
    text(sl, 'factory_conversion', 14.77, 6.04, 2.20, .30, '色码 → 机台程序', 18, align='center')
    text(sl, 'factory_responsibility', 14.77, 6.42, 2.20, .27, '由工厂完成转换', 18, MUTED, align='center')
    text(sl, 'correspondence_title', 14.66, 7.00, 2.41, .35, '几何与纹理对应', 21, bold=True, align='center')
    scope_sketch(sl, 'geometry_correspondence', 14.89, 7.58, .62, .47, '8062AA')
    text(sl, 'geometry_correspondence_text', 15.62, 7.41, 1.31, .65, '边框·圆形\n吊目点阵', 18)
    text(sl, 'physical_boundary', 14.72, 8.10, 2.28, .34, '工厂落地验证', 19, '71559A', True, 'center')

    # 横向主链；回路从第四栏动作设计字段返回第二栏，不经过预览或实物。
    for i in range(4):
        x = COLS[i][0]+COLS[i][1]-.09
        shape(sl, f'main_flow_{i+1}_{i+2}', x, 4.63, .36, .29, '88ABC9', kind='arrow')
    line(sl, 'edit_origin_link', 14.13, 5.28, 14.24, 5.28, BLUE, 2.6)
    line(sl, 'edit_right_drop', 14.24, 5.28, 14.24, 9.19, BLUE, 2.6)
    line(sl, 'edit_return_horizontal', 14.24, 9.19, 4.51, 9.19, BLUE, 2.6)
    line(sl, 'edit_return_to_ir', 4.51, 9.19, 4.51, 8.60, BLUE, 2.6, True)
    shape(sl, 'edit_cycle_label_background', 6.14, 8.82, 6.72, .75, 'E8F2FB', kind='round')
    text(sl, 'edit_cycle_label', 6.28, 8.99, 6.43, .38,
         '用户编辑 → 目标字段更新 → 局部重新编译', 22, '345D7D', True, 'center')
    sl.notes_slide.notes_text_frame.text = (
        'F1 / pp_01。wave_1.parent_id = circle_1；bg、frame_1、circle_1 为根级 motif。\n'
        '动作图1600个原生方格与原始BMP逐格同RGB；图例不是纱线颜色。\n'
        'Stage 4预览仅辅助视觉；实物按用户确认与工厂F1编号映射。\n'
        '工厂自行完成CAD打版转换，不宣称系统自动输出机台程序。\n'
        '底部回路仅代表用户字段编辑，不是物理或视觉结果自动回传。\n'
        '旧docs/images/1.png与F1相差490格，已排除。\n'
        '第三栏小型网格取真实动作图(row=10:18,col=10:18)，其余约束图标为机制示意。')
    prs.save(PPTX)
    write_json('text_manifest.json', TEXT_RECORDS)
    return audit_deck()


def native_mask(sl, prefix, mask_key, masks, x, y, size, color):
    # 同一行的连续像素合并成原生矩形，轮廓仍严格遵循离散掩膜。
    elements = []
    mask = masks[mask_key]
    for r in range(40):
        c = 0
        while c < 40:
            if (r, c) not in mask:
                c += 1
                continue
            start = c
            while c < 40 and (r, c) in mask:
                c += 1
            elements.append(shape(sl, f'{prefix}_run_{r}_{start}_{c}', x+start*size/40,
                                  y+r*size/40, (c-start)*size/40, size/40, color, color, lw=.18))
    grouped(sl, prefix+'_mask_group', elements)
    VISUAL_RECORDS.append({'prefix': prefix, 'kind': 'mask', 'mask': mask_key,
                           'layout': [x, y, size], 'color': color})


def native_layer(sl, prefix, grid, actions, keep, x, y, size, recolor=None):
    # 只绘制 keep 内动作格；同行同色连续格合并为原生矩形，颜色取自真实色码图。
    # recolor 用于工艺层：事件格在 L2 写入前呈现其基底工艺色。
    recolor = recolor or {}
    elements = []
    for r in range(40):
        c = 0
        while c < 40:
            aid = int(actions[r, c])
            if aid not in keep and aid not in recolor:
                c += 1
                continue
            rgb = recolor.get(aid, grid.getpixel((c, r)))
            start = c
            while c < 40:
                nid = int(actions[r, c])
                if (nid not in keep and nid not in recolor) or recolor.get(nid, grid.getpixel((c, r))) != rgb:
                    break
                c += 1
            hexrgb = ''.join(f'{k:02X}' for k in rgb)
            elements.append(shape(sl, f'{prefix}_run_{r}_{start}_{c}', x+start*size/40,
                                  y+r*size/40, (c-start)*size/40, size/40, hexrgb, hexrgb, lw=.18))
    grouped(sl, prefix+'_layer_group', elements)
    VISUAL_RECORDS.append({'prefix': prefix, 'kind': 'layer', 'keep': sorted(keep),
                           'recolor': {str(k): ''.join(f'{v:02X}' for v in rgb) for k, rgb in recolor.items()},
                           'layout': [x, y, size]})


def native_events(sl, prefix, grid, pairs, x, y, size):
    elements = []
    for r, c0 in pairs:
        for c in (c0, c0+1):
            rgb = ''.join(f'{k:02X}' for k in grid.getpixel((c, r)))
            elements.append(shape(sl, f'{prefix}_cell_{r:02}_{c:02}', x+c*size/40, y+r*size/40,
                                  size/40, size/40, rgb, '52677A', lw=.35))
    grouped(sl, prefix+'_events_group', elements)
    VISUAL_RECORDS.append({'prefix': prefix, 'kind': 'events', 'layout': [x, y, size]})


def native_crop(sl, prefix, grid, x, y, width):
    cell_grid(sl, grid.crop((15, 17, 22, 22)), x, y, width, prefix+'_cell', preserve_aspect=True)
    # 网格线便于辨认每个方格，不更改动作填色或裁剪的长宽比。
    for c in range(8):
        line(sl, f'{prefix}_v_{c}', x+c*width/7, y, x+c*width/7, y+width*5/7, 'FFFFFF', .45)
    for r in range(6):
        line(sl, f'{prefix}_h_{r}', x, y+r*width/7, x+width, y+r*width/7, 'FFFFFF', .45)
    VISUAL_RECORDS.append({'prefix': prefix, 'kind': 'crop', 'layout': [x, y, width]})


def normalize_english_package():
    # 连母版、备注默认字号和主题字体一起统一，避免隐藏的 Aptos/Georgia 回退。
    from lxml import etree
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


def build_deck_en():
    protect_originals(create=True)
    source = inspect_sources()
    grid, masks, pairs, actions = english_sample()
    prs = Presentation()
    prs.slide_width, prs.slide_height = (Inches(v) for v in source['template_inches'])
    # 导师标准：底部横带删除后回收幻灯片高度至9.35in，上下留白 .40/.40 平衡（中文路径不变）。
    prs.slide_height = Inches(9.35)
    prs.core_properties.title = 'Hierarchical Semantic Action Compilation'
    prs.core_properties.subject = 'Figure 1: editable native shapes; F1 / pp_01'
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    TEXT_RECORDS.clear()
    VISUAL_RECORDS.clear()
    # 两行标题独立排版，第二行使用整栏宽度；编号不占用第二行。
    # 分块编号遵循 Elsevier 体例：图内圆盘放小写字母，图注以 (a)-(e) 引用；块4副题与块1重复故移除。
    # 导师标准：删“Natural language”（引文框自明）与“Design semantics to actions”（复述栏题）两条副标题；
    # 保留PatternPlan（图内唯一出现处）与Factory Sample编号（case数据）。
    headers = [('Design', 'Intent', ''),
               ('Hierarchical', 'Manufacturing IR', 'PatternPlan'),
               ('Event-level', 'Constraint Compiler', ''),
               ('Editable', 'Action Map', ''),
               ('Factory', 'Validation', factory_label(1))]
    for i, ((x, w), (bg, accent), (first, second, sub)) in enumerate(zip(COLS, PALETTES, headers)):
        tag = 'abcde'[i]
        shape(sl, f'column_{i+1}', x, .40, w, 8.16, bg, kind='round')
        shape(sl, f'panel_disc_{tag}', x+.12, .58, .44, .44, accent, kind='oval')
        text(sl, f'panel_label_{tag}', x+.12, .58, .44, .44, tag, 26, 'FFFFFF', align='center')
        text(sl, f'heading_first_{i+1}', x+.65, .57, w-.76, .47, first, 28 if i == 1 else 30, bold=True)
        text(sl, f'heading_second_{i+1}', x+.10, 1.08, w-.20, .49, second, 28 if i == 1 else 30, bold=True, align='center')
        if sub:
            text(sl, f'subheading_{i+1}', x+.10, 1.63, w-.20, .34, sub, 22, accent, align='center')
        if i:
            shape(sl, f'inner_panel_{i+1}', x+.10, 2.00, w-.20, 6.45, 'FFFFFF', bg, 'round', 1)

    # ① 只保留英译引文与样例归属；几何草图与图2重复，不再出现在框架图。
    shape(sl, 'intent_quote_box', .31, 2.05, 2.00, 4.30, 'FFFFFF', '94B6D1', 'round', 1.2)
    text(sl, 'intent_quote', .36, 2.70, 1.90, 3.00,
         '“Rectangular\nframe, inner\ncircle with\nwave tucks,\nplain-knit\nbackground.”', 24, align='center')
    # 导师标准：semantic front-end三行注与3.2节“只输出受限字段集合”逐字重复，删除；图注(a)补半句。
    text(sl, 'intent_sketch_title', .21, 6.55, 2.20, .90,
         case_label('pp_01').replace(' Case ', '\nCase '), 26, BLUE, True, 'center')

    # ② 只保留真实层级树；掩膜叠加由图2承载，腾出空间放宽树间距。
    shape(sl, 'plan_root', 2.82, 2.25, 2.96, .56, 'EEE8F6', 'A294C3', 'round')
    text(sl, 'plan_root_text', 2.90, 2.31, 2.80, .44, '40 × 40 grid', 25, bold=True, align='center')
    line(sl, 'tree_trunk', 2.88, 2.81, 2.88, 5.30, 'A4AEB8', 1.5)
    for mid, label, y, fill, accent in [('bg', 'bg · plain', 3.05, 'EDF1F5', '8A9BAA'),
                                        ('frame_1', 'frame_1 · plain', 4.02, 'EAF2FB', '709FCC'),
                                        ('circle_1', 'circle_1 · plain', 4.99, 'EAF4E9', '76A974')]:
        line(sl, 'tree_edge_root_'+mid, 2.88, y+.31, 3.10, y+.31, 'A4AEB8', 1.5, True)
        shape(sl, 'tree_node_'+mid, 3.12, y, 2.64, .62, fill, accent, 'round')
        text(sl, 'node_label_'+mid, 3.23, y+.09, 2.42, .44, label, 22, bold=True)
    line(sl, 'tree_child_vertical', 3.31, 5.61, 3.31, 6.10, '76A974', 1.6)
    line(sl, 'tree_edge_circle_1_wave_1', 3.31, 6.10, 3.52, 6.10, '76A974', 1.6, True)
    shape(sl, 'tree_node_wave_1', 3.55, 5.80, 2.21, .83, 'FFF0DE', 'D49D58', 'round')
    text(sl, 'wave_label', 3.63, 5.84, 2.05, .34, 'wave_1', 24, bold=True)
    text(sl, 'wave_period', 3.59, 6.26, 2.13, .30, 'wave_tuck · 5 × 4', 20, MUTED)
    text(sl, 'ir_clipping_note', 2.75, 7.00, 3.10, .68,
         'wave_1 events clip to\ncircle_1 at compile time', 22, MUTED, align='center')

    # ③ 三阶段降阶各配一张pp_01真实分层色块：工艺层、事件层、合成动作图，均为色码图像素子集。
    shape(sl, 'constraints_band', 6.32, 2.18, 4.88, 1.00, 'E8EDEB', kind='round')
    text(sl, 'constraints_title', 6.42, 2.28, 4.68, .80,
         'Constraint checks &\nconservative repair', 26, bold=True, align='center')
    # 导师标准：H1–H8灰盒注与图注(c)逐字重复，删除；腾出的行高加给三个阶段盒。
    # 导师标准：三阶段名在1.52in盒內20pt会溢出（“Visual target”≈114.6pt>106.6pt），
    # 盒宽放到1.60in、字号定19pt（折印6.87pt≥导师6.8pt下限），缩略图/说明仍居中。
    stage_boxes = [(6.28, 1.60), (7.96, 1.60), (9.64, 1.60)]
    for i, ((x, w), fill, label) in enumerate(zip(stage_boxes, ['EEF6FC', 'FFF4E7', 'F1EDFB'],
            ['Visual target\ngeneration', 'Sparse event\nplanning', 'Action grid\nconstruction'])):
        shape(sl, f'compiler_stage_{i+1}', x, 3.34, w, 4.80, fill, kind='round')
        text(sl, f'compiler_stage_label_{i+1}', x+.02, 3.42, w-.04, .62, label, 19, bold=True, align='center')
    shape(sl, 'craft_outline', 6.375, 4.445, 1.41, 1.41, None, '9EBAD0', lw=.8)
    native_layer(sl, 'compiler_crafts', grid, actions, {0, 1}, 6.38, 4.45, 1.40,
                 recolor={7: (255, 0, 16), 8: (255, 0, 16)})
    shape(sl, 'sparse_canvas', 8.06, 4.45, 1.40, 1.40, 'FFFFFF', 'D8C6B4', lw=.7)
    native_layer(sl, 'compiler_events', grid, actions, {7, 8}, 8.06, 4.45, 1.40)
    native_layer(sl, 'compiler_full', grid, actions, {0, 1, 7, 8}, 9.74, 4.45, 1.40)
    shape(sl, 'composed_outline', 9.735, 4.445, 1.41, 1.41, None, '8062AA', lw=.8)
    for i, (x, cap) in enumerate(zip((6.32, 8.00, 9.68),
            ['Craft layers\n(L0 + L1)', 'Event layer\n(L2)', 'Action grid\n(L0–L3)'])):
        text(sl, f'compiler_stage_caption_{i+1}', x+.02, 6.02, 1.48, .62, cap, 20, align='center')
    for i, (x, count) in enumerate(zip((6.32, 8.00, 9.68), ('1600 cells', '32 cells', '1600 cells'))):
        text(sl, f'compiler_stage_count_{i+1}', x+.02, 6.82, 1.48, .30, count, 22, MUTED, align='center')
    for i, x in enumerate((7.86, 9.54)):
        shape(sl, f'compiler_arrow_{i}', x, 5.05, .15, .19, '88A6BD', kind='arrow')
    # 单遍降阶注记移入图注；腾出的行高加给三个阶段盒。

    # ④ 主动作图实心色块（与图10/送厂色码图一致）；删除辅助预览后图例改四行单列并整体放大。
    cell_grid(sl, grid, *ACTION_LAYOUT, 'action_cell', mesh=False)
    for i, (abbr, rgb) in enumerate([('f_knit', 'FF0010'), ('b_knit', '2BCE48'), ('f_split', 'FFE606'), ('f_tuck', '00A4FF')]):
        y = 5.00+i*.46
        shape(sl, 'legend_swatch_'+abbr, 11.72, y+.05, .24, .24, rgb, '8C9DAA', lw=.4)
        text(sl, 'legend_'+abbr, 12.06, y, 1.20, .40, abbr, 24)
    text(sl, 'rule_count', 11.66, 6.92, 2.60, .40, '0 violations', 22, '487F55', bold=True)
    shape(sl, 'edit_origin_action_fields', 12.36, 7.42, 1.70, .50, 'E3EEF9', '8CADCA', 'round')
    text(sl, 'edit_origin_label', 12.41, 7.47, 1.60, .40, 'Edit fields', 22, '346BA2', True, 'center')

    # ⑤ 删除CAD文本框后实物照片放大；CAD转换与几何/纹理对应改由图注与4.5节承载。
    p = pic_fit(sl, SOURCES['photo'], 14.66, 2.45, 2.52, 4.30, frame=False)
    p.name = 'F1_factory_photo_user_confirmed'
    text(sl, 'photo_caption', 14.62, 7.00, 2.60, .80, 'Factory-knitted\nsample', 25, '71559A', True, 'center')

    # 用户编辑回到IR；不从预览或实物引出自动反馈。
    for i in range(4):
        x = COLS[i][0]+COLS[i][1]-.075
        shape(sl, f'main_flow_{i+1}_{i+2}', x, 4.96, .29, .24, '88ABC9', kind='arrow')
    line(sl, 'edit_origin_link', 13.96, 7.67, 14.32, 7.67, BLUE, 2.3)
    line(sl, 'edit_right_drop', 14.32, 7.67, 14.32, 8.95, BLUE, 2.3)
    line(sl, 'edit_return_horizontal', 14.32, 8.95, 4.30, 8.95, BLUE, 2.3)
    line(sl, 'edit_return_to_ir', 4.30, 8.95, 4.30, 8.61, BLUE, 2.3, True)
    # 导师标准：底部箭头链横带文字删除（图注末二句逐字承载），回路改为Edit fields芯片直连(b)栏底。
    notes = (
        'Sample: F1 / pp_01. All three root motifs (bg, frame_1, circle_1) are retained; wave_1 belongs to circle_1.\n'
        'The quote is an English translation of the recorded prompt, not a new model output. Design geometry is a source-grounded schematic.\n'
        'Mask layers overlap. Verified lowering: center (20,20), frame half-size 17 and thickness 2 (264 cells), circle radius 13 (529), wave radius 12 (441).\n'
        'The radius-10 admission domain (317 cells) is NOT the wave mask. Frame plus circle-minus-wave equals all 352 green BMP cells.\n'
        'Sixteen pairs, 32 events: rows 11 and 27 at split columns 17,22; rows 15,19,23 at 12,17,22,27. Each tuck is one column to the right.\n'
        'The three compiler thumbnails are pixel subsets of the same pp_01 color map: region crafts L0+L1 (1600 cells, event cells shown at their base f_knit craft before L2 writes), event layer L2 (32) and the composed grid L0-L3 (1600).\n'
        'The BMP and intermediate NPY are historical FINAL grids, not before/after repair examples. No generation or simulation was rerun.\n'
        'The pp_01 statistics report zero hard/craft violations before and after, zero repair rounds and zero edits. This is not a universal guarantee.\n'
        'The constraint band lists H1-H8 hard constraints, craft rules and group integrity; repair only deletes or downgrades. This sample has NO transfer action; rule references physical_rules.py H3-H6.\n'
        'Figure 1 keeps module-level content only; detailed mechanism diagrams belong to Figs. 2-4 of the paper.\n'
        'The 1600 native action cells use the exact original RGB values, drawn as solid paper-table blocks without overlay mesh, matching Fig. 10 and the factory-delivered BMP. Colors encode actions, not yarn.\n'
        '2026-09-29 revision: auxiliary preview image, Factory CAD text boxes and the duplicate case subtitle were removed; panel discs carry letters a-e per Elsevier style and the caption cites (a)-(e). The single-pass lowering note moved to the caption.\n'
        '2026-09-29 advisor-style pass: the bottom arrow-chain band text, the semantic front-end note, the H1-H8 scope note and two self-evident subheadings were removed (verbatim-covered by the caption or Sec. 3.2); the edit loop now runs straight from the Edit fields chip back to column (b); remaining body fonts raised to 19-26pt (stage labels 19pt to fit the three-column width) and the slide height trimmed to 9.35in.\n'
        'The unchanged factory photograph is paired by the user-confirmed F1 mapping. Geometry/texture correspondence is a visual observation, not machine-verified stitch equivalence.\n'
        'Factory CAD conversion to a machine program is performed by the factory, not automatically by this system. The edit loop represents user field edits only.\n'
        'The conflicting legacy action image is excluded; no fabricated pre-repair output or current regenerated grid is used.')
    tf = sl.notes_slide.notes_text_frame
    tf.text = notes
    for para in tf.paragraphs:
        for run in para.runs:
            run.font.name, run.font.size = 'Times New Roman', Pt(18)
    prs.save(PPTX)
    normalize_english_package()
    write_json('text_manifest.json', TEXT_RECORDS)
    write_json('native_visual_manifest.json', VISUAL_RECORDS)
    return audit_deck()


def render_deck(export=True):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app, pres = None, None
    try:
        if LANG == 'en' and not export:
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
                assert pres.Slides.Count == 1, 'PowerPoint尚未完成打开'
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
                    row = {'name': s.Name, 'text': tr.Text, 'box_pt': [s.Left, s.Top, s.Width, s.Height],
                           'available_pt': [w, h], 'bound_pt': [tr.BoundWidth, tr.BoundHeight],
                           'glyph_rect_pt': [tr.BoundLeft, tr.BoundTop, tr.BoundWidth, tr.BoundHeight],
                           'com_font': tr.Font.Name, 'com_font_size': tr.Font.Size}
                    if LANG == 'en':
                        assert tr.Font.Name == 'Times New Roman' and tr.Font.Size >= 18, row
                    records.append(row)
                    if tr.BoundWidth > w+1.2 or tr.BoundHeight > h+1.2:
                        overflow.append(row)
        # COM遍历2000+形状时偶发拒绝呼叫(RPC_E_CALL_REJECTED)或对象失效(AttributeError <unknown>)；
        # 大版面打开后先静置让PowerPoint完成初始化，再幂等重取slide整体重试；真实字体违规(AssertionError)立即上抛，绝不当作瞬态掩盖。
        time.sleep(5)
        for walk in range(12):
            records.clear(); overflow.clear()
            try:
                inspect(pres.Slides.Item(1).Shapes)
                break
            except AssertionError:
                raise
            except Exception:
                if walk == 11:
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
        report = {'png': str(PNG), 'png_size': Image.open(PNG).size,
                  'pdf': str(PDF), 'pptx_sha256': sha(PPTX), 'actual_powerpoint_com': True,
                  'text_objects_checked': len(records), 'text_overflow': overflow,
                  'text_overlap': overlaps, 'overlap_tolerance_pt': [2, 1.2],
                  'text_measurements': records, 'application_quit_called': False,
                  'export_performed_this_call': export, 'ppt_version': app.Version}
        write_json('render_audit.json', report)
        if overflow or overlaps:
            write_json('render_failure_'+str(time.time_ns())+'.json', report)
        im = Image.open(PNG).convert('RGB')
        im.resize((1600, round(im.height*1600/im.width)), Image.Resampling.LANCZOS).save(OUT/'overview.png')
        im.resize((1890, round(im.height*1890/im.width)), Image.Resampling.LANCZOS).save(OUT/'print_160mm_300dpi.png', dpi=(300, 300))
        for key, (x, w) in {'intent': COLS[0], 'ir': COLS[1], 'compiler': COLS[2], 'action_factory': (COLS[3][0], 17.26-COLS[3][0])}.items():
            k = im.width / (pres.PageSetup.SlideWidth/72)
            im.crop((round(x*k), round(.40*k), round((x+w)*k), round(8.56*k))).save(OUT/f'detail_{key}.png')
        print(json.dumps({'rendered': True, 'text_overflow_count': len(overflow), 'overflow': overflow,
                          'text_overlap_count': len(overlaps), 'overlaps': overlaps}, ensure_ascii=False, indent=2))
        assert not overflow, 'PowerPoint 实测存在文字溢出'
        assert not overlaps, 'PowerPoint 实测存在文字重叠'
        audit_exports()
    except Exception as exc:
        write_json('render_error_'+str(time.time_ns())+'.json', {'error': repr(exc), 'pptx': str(PPTX),
                   'note': '实际COM验收失败；不跳过文字测量，不将静态检查冒充渲染通过。'})
        raise
    finally:
        if pres is not None:
            try:
                pres.Close()
            except Exception as exc:
                write_json('render_close_warning.json', {'error': repr(exc), 'application_quit_called': False})
        pythoncom.CoUninitialize()


def audit_exports():
    import pymupdf as fitz
    with fitz.open(PDF) as doc:
        assert len(doc) == 1
        page = doc[0]
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
                 for line_ in b['lines'] for s in line_['spans'] if s['text'].strip()]
        # 2026-09-29 英文删6个文本对象（预览标题/CAD三框/降阶注记/块4副题），span下限50→44；中文路径不变。
        assert len(spans) >= (44 if LANG == 'en' else 66)
        assert len(page.get_images(full=True)) == (1 if LANG == 'en' else 2)
        assert len(page.get_drawings()) > 1600
        assert min(s['size'] for s in spans) >= 17.99
        assert Image.open(PNG).width == 4000
        pdf_fonts = sorted({s['font'] for s in spans})
        if LANG == 'en':
            assert all('TimesNewRoman' in f.replace('-', '') for f in pdf_fonts), pdf_fonts
            assert not re.search(r'[\u3400-\u9fff]', page.get_text())
            assert all(f[1] != 'n/a' for f in page.get_fonts(full=True)), 'PDF字体未嵌入'
        render_pixels = {}
        if LANG == 'en':
            image = Image.open(PNG).convert('RGB')
            source = Image.open(SOURCES['action_bmp']).convert('RGB')
            scale = image.width / (page.rect.width / 72)
            gx, gy, gw = ACTION_LAYOUT
            checks = [('main_action', source, gx, gy, gw, [(r, c) for r in range(40) for c in range(40)])]
            palette = {0: (255, 0, 16), 1: (43, 206, 72), 7: (255, 230, 6), 8: (0, 164, 255)}
            rgb_to_id = {v: k for k, v in palette.items()}
            for rec in json.loads((OUT / 'native_visual_manifest.json').read_text(encoding='utf-8')):
                if rec['kind'] == 'layer':
                    recolor = {int(k): tuple(bytes.fromhex(v)) for k, v in rec.get('recolor', {}).items()}
                    drawn = set(rec['keep']) | set(recolor)
                    points = [(r, c) for r in range(40) for c in range(40)
                              if rgb_to_id[source.getpixel((c, r))] in drawn]
                    if recolor:
                        reference = source.copy()
                        for r, c in points:
                            aid = rgb_to_id[source.getpixel((c, r))]
                            if aid in recolor:
                                reference.putpixel((c, r), recolor[aid])
                    else:
                        reference = source
                    checks.append((rec['prefix'], reference, *rec['layout'], points))
            for name, reference, x, y, width, points in checks:
                pitch = width/reference.width
                bad = [(r, c) for r, c in points if image.getpixel((round((x+(c+.5)*pitch)*scale),
                        round((y+(r+.5)*pitch)*scale))) != reference.getpixel((c, r))]
                assert not bad, (name, bad)
                render_pixels[name] = {'cell_centers_checked': len(points), 'rgb_mismatches': len(bad)}
        result = {'pdf_pages': 1, 'pdf_text_spans': len(spans),
                  'pdf_min_font_pt': min(s['size'] for s in spans), 'pdf_fonts': pdf_fonts,
                  'pdf_font_resources': page.get_fonts(full=True), 'actual_render_pixel_checks': render_pixels,
                  'pdf_image_objects': len(page.get_images(full=True)),
                  'pdf_vector_drawings': len(page.get_drawings()),
                  'png_pixels': Image.open(PNG).size,
                  'pdf_page_pt': [page.rect.width, page.rect.height],
                  'exports': {p.suffix: {'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
                              for p in (PPTX, PNG, PDF)}}
        write_json('export_audit.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', choices=('zh', 'en'), default='zh')
    ap.add_argument('--inspect', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--render', action='store_true')
    args = ap.parse_args()
    configure_language(args.lang)
    if args.inspect:
        if LANG == 'en':
            protect_originals(create=True)
            english_sample()
        inspect_sources()
    elif args.verify:
        audit_deck()
        if LANG == 'en':
            assert PDF.exists() and PNG.exists(), '英文交付必须同时包含PNG与PDF'
            render_deck(export=False)
        elif PDF.exists() and PNG.exists():
            audit_exports()
    elif args.render:
        render_deck()
    else:
        if LANG == 'en':
            build_deck_en()
        else:
            build_deck()
        render_deck()


if __name__ == '__main__':
    main()
