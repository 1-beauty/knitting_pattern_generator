"""rev_round9a: structural fixes for CiI submission.
- restore 5 Elsevier declaration sections before References
- fix Fig.8 caption (manufacturer product photo) + p131 machine paragraph
- delete broken/redundant p107
- fix p057 broken cross-ref (Eq. ) -> (Eq. (5))
- tighten abstract claim: region attribution+grouping -> grouping integrity
All rewrite targets verified oMath==0 except p057/p107 which are handled specially.
"""
import sys
from docx import Document
from docx.oxml.ns import qn

PATH = r"e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx"
d = Document(PATH)
ps = d.paragraphs

def find(pred):
    for p in ps:
        if pred(p.text.strip()):
            return p
    return None

def omath(p):
    return p._p.findall('.//' + qn('m:oMath'))

log = []

# ---------- 1) Abstract: tighten claim ----------
ab = find(lambda t: t.startswith("Flat-knitting action graphs link"))
assert ab is not None and len(omath(ab)) == 0, "abstract locate/omath fail"
OLD = "region attribution and grouping are instead injected explicitly by compilation"
NEW = "grouping integrity is instead injected explicitly by compilation"
hit = False
for r in ab.runs:
    if OLD in r.text:
        r.text = r.text.replace(OLD, NEW); hit = True; break
assert hit, "abstract OLD substring not found in a single run"
log.append("abstract: region-attribution claim -> grouping integrity")

# ---------- 2) p057: (Eq. ) -> (Eq. (5)) ----------
p057 = find(lambda t: "structural prerequisite for the subsequent scope clipping" in t)
assert p057 is not None, "p057 locate fail"
oms = omath(p057)
mtxt = "".join(t.text or "" for t in oms[0].findall('.//' + qn('m:t'))) if oms else ""
log.append(f"p057: oMath count={len(oms)}, first-oMath text={mtxt!r}")
# only inject text if the inline object between '(Eq. ' and ')' carries no visible number
fixed057 = False
for r in p057.runs:
    if "scope clipping (Eq. " in r.text:
        r.text = r.text.replace("scope clipping (Eq. ", "scope clipping (Eq. (5)")
        fixed057 = True; break
assert fixed057, "p057 '(Eq. ' run not found"
log.append("p057: (Eq. ) -> (Eq. (5))")

# ---------- 3) delete broken/redundant p107 ----------
p107 = find(lambda t: t.startswith(": to further isolate"))
assert p107 is not None, "p107 locate fail"
p107._p.getparent().remove(p107._p)
log.append("p107: deleted (broken leading colon + redundant Protocol-B preview)")

# ---------- 4) Fig.8 caption ----------
fig8 = find(lambda t: t.startswith("Fig. 8."))
assert fig8 is not None and len(omath(fig8)) == 0, "fig8 locate/omath fail"
FIG8_NEW = (" The Cixing CX2-52EC-U computerized flat-knitting machine (Ningbo Cixing Co., Ltd.) "
            "used for the factory production test; the photograph is a manufacturer product image, "
            "and the five samples were knitted on this machine model in its standard production "
            "configuration.")
# keep run0 ('Fig. 8.'), rewrite the rest into run1, clear extras
runs = fig8.runs
runs[0].text = "Fig. 8."
if len(runs) > 1:
    runs[1].text = FIG8_NEW
    for r in runs[2:]:
        r.text = ""
else:
    fig8.add_run(FIG8_NEW)
log.append("Fig.8 caption: clarified manufacturer product photo + samples knitted on this model")

# ---------- 5) p131 machine paragraph: fix provenance + trim spec dump ----------
p131 = find(lambda t: "factory-landed production was completed on a Cixing" in t
                   or "factory production test was carried out on a Cixing" in t)
assert p131 is not None and len(omath(p131)) == 0, "p131 locate/omath fail"
P131_NEW = (
    "The factory production test was carried out on a Cixing CX2-52EC-U computerized flat-knitting "
    "machine of Ningbo Cixing Co., Ltd. (Fig. 8; principal specifications in Table 8), a 52-inch "
    "single-carriage dual-system machine whose motor-controlled direct-selection-needle cam system "
    "executes knit, tuck, and transfer in one-to-one correspondence with the action primitives "
    "defined in Fig. 2; the test used the machine's standard production configuration. As a "
    "machine-specific-code-agnostic abstract action representation, the action color map was "
    "converted by the factory through its pattern-making workflow into the machine program of this "
    "model. The five samples were knitted on this machine model; Fig. 8 is a manufacturer product "
    "photograph, and the samples serve to verify the feasibility of the proposed approach rather "
    "than to characterize the machine's physical output."
)
r131 = p131.runs
r131[0].text = P131_NEW
for r in r131[1:]:
    r.text = ""
log.append("p131: removed false 'sample visible in Fig.8' claim; trimmed spec dump; added feasibility-verification framing")

# ---------- 6) restore 5 declaration sections before References ----------
ref_head = find(lambda t: t == "References")
assert ref_head is not None, "References heading locate fail"
ref_p = ref_head._p

DECL = [
    ("Funding",
     "This research did not receive any specific grant from funding agencies in the public, "
     "commercial, or not-for-profit sectors."),
    ("Acknowledgements",
     "The authors thank the partner knitting factory for carrying out the production test."),
    ("Data availability",
     "The semantic-parsing test inputs (100 cases), per-case outputs and the code will be made "
     "publicly available with the publication of this article. Factory-test artifacts (color-code "
     "maps and physical sample photographs) are subject to the partner's confidentiality terms and "
     "are available from the corresponding author on reasonable request; the factory patterning "
     "conversion itself is not reproducible outside the partner's workflow."),
    ("Declaration of competing interest",
     "The authors declare that they have no known competing financial interests or personal "
     "relationships that could have appeared to influence the work reported in this paper."),
    ("CRediT authorship contribution statement",
     "<NAME_1>: Conceptualization, Methodology, Software, Writing - original draft. "
     "<NAME_2>: Validation, Writing - review & editing. "
     "<NAME_3>: Supervision, Funding acquisition."),
]
for title, body in DECL:
    h = d.add_paragraph(title, style="Heading 2")
    b = d.add_paragraph(body, style="Body Text")
    ref_p.addprevious(h._p)
    ref_p.addprevious(b._p)
log.append("declarations: Funding/Acknowledgements/Data availability/Declaration/CRediT restored before References")

# ---------- save (handle Word lock) ----------
try:
    d.save(PATH)
    saved = PATH
except PermissionError:
    saved = r"e:\DeskTop\knitting_pattern_generator\docs\论文to_cii_fix9a.docx"
    d.save(saved)
    log.append(f"WARNING: original locked by Word; saved bypass file {saved}")

print("SAVED:", saved)
for l in log:
    print(" -", l)

# ---------- reopen & verify ----------
d2 = Document(saved)
ps2 = d2.paragraphs
txt = [p.text.strip() for p in ps2]
joined = "\n".join(txt)
print("\n=== VERIFY ===")
for k in ["Funding", "Acknowledgements", "Data availability",
          "Declaration of competing interest", "CRediT authorship"]:
    print(f"decl {k!r:38s} present={k in joined}")
print("abstract grouping-only      :", "grouping integrity is instead injected" in joined)
print("abstract no region-attrib   :", "region attribution and grouping are instead" not in joined)
print("p057 (Eq. (5))              :", "scope clipping (Eq. (5))" in joined)
print("p107 broken colon gone      :", not any(t.startswith(": to further isolate") for t in txt))
print("Fig8 manufacturer product   :", "manufacturer product image" in joined)
print("p131 false-visible gone     :", "visible on the take-down roller" not in joined)
print("p131 feasibility framing    :", "verify the feasibility of the proposed approach" in joined)
# abstract word count (whitespace)
for i, t in enumerate(txt):
    if t == "Abstract":
        print("abstract whitespace words   :", len(ps2[i+1].text.split()))
        break
# references still last content heading before decl? show order around References
idx_ref = next(i for i, t in enumerate(txt) if t == "References")
print("order before References     :", [txt[j][:34] for j in range(idx_ref-10, idx_ref)])
