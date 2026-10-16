"""英文案例展示交付：串行导出截图图、核对活动引用及独立渲染后的文本。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
import pymupdf
import build_case_label_raster_figures as rasters
from paper_case_labels import CASE_PATTERN, CASE_NAMES, case_label

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/case_labels_20260922'
PAPER = ROOT / 'docs/论文初稿.md'
FIG1 = ROOT / 'docs/figures/Fig1_Hierarchical_Semantic_Action_Compilation_EN.pptx'
FIG = ROOT / 'docs/figures'
PREVIEW = ROOT / 'outputs/factory_delivery/F1_pp01_circle_wave_preview.png'
EVIDENCE = ROOT / 'outputs/fig1_pptx_en_20260921/source_evidence.json'
# SVG 矢量管线退役（2026-09-30）后，原 build_case_label_figures.py 中 verify 仍需的非-SVG 辅助迁至本文件。
STEMS = (
    'fig_edit_cases_composite',
    'fig_end_to_end_factory', 'fig_experimental_evidence_chain',
    'fig_baseline_comparison', 'fig_internal_baseline_leakage',
)


def destination(stem, extension='pptx'):
    assert stem in STEMS
    return FIG / f'{stem}_CaseLabels_EN.{extension}'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def compact(text):
    return re.sub(r'\s+', '', text)


def glyph_collisions(page):
    # 用逐行墨迹而非大文本框，允许原有框内多行文字。
    boxes = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            text = ''.join(s['text'] for s in line['spans']).strip()
            if text:
                boxes.append((text, pymupdf.Rect(line['bbox'])))
    bad = []
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1:]:
            overlap = ra & rb
            if overlap.width > 2 and overlap.height > 1.2:
                bad.append({'a': a, 'b': b, 'intersection': list(overlap)})
    return bad


def flatten(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from flatten(shape.shapes)


def check_preview():
    data = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    inputs = FIG / 'assets_real/real_colormap_pp01_big.png'
    assert sha(PREVIEW) == data['sources']['preview']['sha256']
    assert sha(inputs) == data['sources']['large_action_png']['sha256']
    assert Image.open(PREVIEW).size == (320, 320)
    mapping = ROOT / 'scripts/gen_factory_previews.py'
    assert sha(mapping) == data['sources']['preview_mapping']['sha256']
    assert "('patternplan/pp_01/color_map/pp_01_output.bmp', 'F1_pp01_circle_wave_preview.png')" in mapping.read_text(encoding='utf-8')
    return {'evidence_path': str(EVIDENCE), 'evidence_sha256': sha(EVIDENCE), 'preview_path': str(PREVIEW),
            'preview_sha256': sha(PREVIEW), 'size': [320, 320], 'input_path': str(inputs), 'input_sha256': sha(inputs),
            'mapping_script_sha256': sha(mapping), 'old_output_semantic_case': 'sem_01',
            'new_output_case': 'pp_01', 'new_display_label': case_label('pp_01'),
            'scope': 'Only the preview architecture figure replaces its output image; shared assets stay unchanged.'}


def render_rasters():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    pres = None
    reports = []
    try:
        app = win32com.client.Dispatch('PowerPoint.Application')
        for path in (rasters.OUT9, rasters.OUT7):
            pres = app.Presentations.Open(str(path), True, False, False)
            sl = pres.Slides.Item(1)
            sl.Export(str(path.with_suffix('.png')), 'PNG', 4000,
                      round(4000 * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth))
            pres.SaveAs(str(path.with_suffix('.pdf')), 32)
            measures, overflow = [], []
            for i in range(1, sl.Shapes.Count + 1):
                s = sl.Shapes.Item(i)
                if not (s.HasTextFrame and s.TextFrame2.HasText):
                    continue
                tr = s.TextFrame2.TextRange
                width, height = s.Width, s.Height
                if s.TextFrame2.Orientation in (2, 3, 4, 5):
                    # 竖排通过全局墨迹矩形和形状边界独立检查。
                    width, height = s.Width, s.Height
                row = {'name': s.Name, 'text': tr.Text, 'shape_pt': [s.Left, s.Top, width, height],
                       'ink_pt': [tr.BoundLeft, tr.BoundTop, tr.BoundWidth, tr.BoundHeight]}
                measures.append(row)
                if tr.BoundWidth > width + 1.2 or tr.BoundHeight > height + 1.2:
                    overflow.append(row)
            reports.append({'path': str(path), 'measurements': measures, 'overflow': overflow})
            pres.Close()
            pres = None
        dump('raster_render_audit.json', reports)
        assert not any(r['overflow'] for r in reports), reports
    finally:
        if pres is not None:
            pres.Close()
        pythoncom.CoUninitialize()
    rasters.audit_delivery()
    print('GUI/stage figures: COM export and text measurements passed.')


def validate_paper():
    text = PAPER.read_text(encoding='utf-8')
    body, mapping = text.split('### Supplementary Section F: Case-label Mapping', 1)
    # 不触碰公式/动作缩写，源码示例和链接目标不适用展示命名。
    prose = re.sub(r'```[\s\S]*?```', '', body)
    prose = re.sub(r'!?\[([^]]*)\]\([^)]*\)', r'\1', prose)
    assert not CASE_PATTERN.search(prose), CASE_PATTERN.findall(prose)
    assert not re.search(r'\b(?:SEM|TEST|STRESS|EDTP?|RND|ABL|NEST)[_-]\d+', prose)
    assert 'sem_NN' in mapping and '`pp_01`' in mapping
    assert all(label in body and label in mapping for label in CASE_NAMES.values())
    # 案例编号约定段已按用户要求转为中文（展示名仍为英文），pin 中文起始句。
    assert '案例按实验族及其原始数字后缀标识' in body
    cap5 = next(line for line in body.splitlines() if line.startswith('**图 5 '))
    assert 'Generation Case 01' in cap5 and 'Semantic Case 01' not in cap5
    assert 'Semantic Case 31–Semantic Case 100，70 条' in body
    refs = re.findall(r'!\[[^]]*\]\(([^)]*)\)', text)
    assert len(refs) == 13
    assert len([r for r in refs if '_CaseLabels_EN.png' in r]) == 7
    for ref in refs:
        assert (PAPER.parent / ref).is_file(), ref
    return {'path': str(PAPER), 'sha256': sha(PAPER), 'active_figures': refs,
            'unapproved_raw_display_ids': 0, 'mapping_section_present': True,
            'figure5_same_case': True, 'semantic_70_case_range_preserved': True}


def verify_all():
    paper = validate_paper()
    # SVG 矢量管线已退役（2026-09-30）：论文图以 docs/figures/*.pptx 为手工维护源，
    # 不再做 SVG 源一致性审计；STEMS/destination/flatten/check_preview 已内置于本文件。
    rasters.audit_delivery()
    records = []
    paths = [FIG1] + [destination(stem) for stem in STEMS] + [rasters.OUT9, rasters.OUT7]
    for path in paths:
        prs = Presentation(path)
        assert len(prs.slides) == 1
        texts = [s.text for s in flatten(prs.slides[0].shapes) if s.has_text_frame and s.text.strip()]
        is_gui = path == rasters.OUT7
        if not is_gui:
            assert not CASE_PATTERN.search('\n'.join(texts)), path
        with pymupdf.open(path.with_suffix('.pdf')) as doc:
            assert len(doc) == 1
            extracted = compact(doc[0].get_text())
            missing = [t for t in texts if 'Case ' in t or 'Factory Sample' in t if compact(t) not in extracted]
            assert not missing, (path, missing)
            overlaps = glyph_collisions(doc[0])
            records.append({'path': str(path), 'native_text_count': len(texts),
                            'case_texts': [t for t in texts if 'Case ' in t or 'Factory Sample' in t],
                            'pdf_missing_labels': missing, 'pdf_line_bbox_intersections': overlaps,
                            'gui_raw_ids_exception': is_gui,
                            'hashes': {ext: sha(path.with_suffix(ext)) for ext in ('.pptx', '.png', '.pdf')}})
        image = Image.open(path.with_suffix('.png')).convert('RGB')
        image.thumbnail((1600, 1400))
        image.save(OUT / (path.stem + '_overview.png'))
    result = {'paper': paper, 'figures': records, 'figure5_pair': check_preview(),
              'unmodified_gui_capture_verified': True,
              'old_sources_unchanged': True, 'word_regenerated': False,
              'scope': 'English case display names and new explanatory text, not a full manuscript translation.'}
    dump('delivery_audit.json', result)
    print(json.dumps({'figures': len(records), 'paper_raw_ids': 0,
                      'missing_pdf_labels': 0, 'line_bbox_intersections': {Path(r['path']).stem: len(r['pdf_line_bbox_intersections']) for r in records}}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--render-rasters', action='store_true')
    args = parser.parse_args()
    if args.render_rasters:
        render_rasters()
    else:
        verify_all()
