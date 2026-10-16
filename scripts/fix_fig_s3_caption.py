# -*- coding: utf-8 -*-
"""Fix missing Fig S3 caption in Supplementary + final cleanup."""
import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree

SUPP = r'e:\DeskTop\knitting_pattern_generator\docs\Supplementary_Material.docx'
doc = Document(SUPP)
body = doc.element.body

# Find para-51 (the image that should have Fig S3 caption)
pi = -1
target_el = None
target_idx = None
for ki, el in enumerate(body.iterchildren()):
    if el.tag == qn('w:p'):
        pi += 1
        if pi == 51:
            target_el = el
            target_idx = ki
            break

assert target_el is not None, "para-51 not found"

# Verify it has a drawing
drawings = target_el.findall('.//' + qn('w:drawing'))
print(f"para-51 has {len(drawings)} drawing(s)")

# Check next paragraph text
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
next_el = body[target_idx + 1]
next_texts = next_el.findall('.//w:t', ns)
next_text = ''.join(t.text or '' for t in next_texts)
print(f"Next para text: {next_text[:80]}")

# Check if it already has a caption (might have been partially there)
if 'Fig. S3' in next_text or '图 S3' in next_text:
    print("Fig S3 caption already exists, skipping")
else:
    # Insert a caption paragraph AFTER the image paragraph
    # Create: "Fig. S3. Internal controlled comparison: region boundary leakage maps."
    caption_p = OxmlElement('w:p')
    
    # Paragraph properties: use same style as Fig S4 caption (find it)
    # Look at para-100's style
    pi2 = -1
    fig_s4_style = None
    for el2 in body.iterchildren():
        if el2.tag == qn('w:p'):
            pi2 += 1
            if pi2 == 99:  # para-99 is the Fig S4 caption
                pPr = el2.find('.//' + qn('w:pPr'))
                if pPr is not None:
                    fig_s4_style = pPr
                break
    
    # Create pPr with BodyText style (consistent with other captions)
    pPr = OxmlElement('w:pPr')
    pStyle = OxmlElement('w:pStyle')
    pStyle.set(qn('w:val'), 'BodyText')
    pPr.append(pStyle)
    # Justified alignment
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'center')
    pPr.append(jc)
    caption_p.append(pPr)
    
    # Create run with text
    run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    # Bold for "Fig. S3."
    b = OxmlElement('w:b')
    rPr.append(b)
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), '18')  # 9pt
    rPr.append(sz)
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Times New Roman')
    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rPr.append(rFonts)
    run.append(rPr)
    t = OxmlElement('w:t')
    t.text = 'Fig. S3. Internal controlled comparison: region structure boundary leakage maps for representative nested inputs. Left: Ours (event-level compilation). Right: Plan-Grid (dense filling). Color encodes action type per the 15-color palette (Table 1).'
    run.append(t)
    caption_p.append(run)
    
    # Insert after target
    body.insert(target_idx + 1, caption_p)
    print("SUCCESS: Inserted Fig S3 caption after para-51")

doc.save(SUPP)
print("Supplementary saved.")
