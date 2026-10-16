# Format thesis docx (pandoc export) into Chinese-journal paper style.
# ASCII-only source; Chinese literals via [regex]::Unescape to survive PS 5.1 ANSI parsing.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# ---- Chinese literals ----
$S   = [char]0x5B8B + [char]0x4F53                      # SimSun
$H   = [char]0x9ED1 + [char]0x4F53                      # SimHei
$FIG = [string][char]0x56FE                             # tu (figure)
$TBL = [string][char]0x8868                             # biao (table)
$REFH= [regex]::Unescape('\u53C2\u8003\u6587\u732E')    # references heading
$ABS = [regex]::Unescape('\u6458\u8981')                # abstract heading
$KW  = [regex]::Unescape('\u5173\u952E\u8BCD')          # keywords label
$DOCNAME = [regex]::Unescape('\u8BBA\u6587\u521D\u7A3F') # lunwen chugao
$OUTNAME = $DOCNAME + '_' + [regex]::Unescape('\u6392\u7248') + '.docx'

$root  = 'e:\DeskTop\knitting_pattern_generator'
$src   = Join-Path $root ('docs\' + $DOCNAME + '.docx')
$dst   = Join-Path $root ('docs\' + $OUTNAME)
$work  = Join-Path $env:TEMP 'docx_fmt'

if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Path $work | Out-Null
$zipCopy = Join-Path $work 'src.zip'
Copy-Item $src $zipCopy
[System.IO.Compression.ZipFile]::ExtractToDirectory($zipCopy, (Join-Path $work 'x'))
$x = Join-Path $work 'x'

function ReadXml([string]$p)  { [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8) }
function WriteXml([string]$p, [string]$s) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($p, $s, $enc)
}

# =========================================================
# 1) styles.xml : redefine styles for paper format
# =========================================================
$sp = Join-Path $x 'word\styles.xml'
$st = ReadXml $sp

function RepStyle([string]$xml, [string]$id, [string]$new) {
  $pattern = '(?s)<w:style\b[^>]*w:styleId="' + $id + '".*?</w:style>'
  if (-not [regex]::IsMatch($xml, $pattern)) { Write-Host ("WARN: style not found: " + $id); return $xml }
  return [regex]::Replace($xml, $pattern, { param($m) $new }, 'None')
}

$fontsBody = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="' + $S + '" w:cs="Times New Roman"/>'
$fontsHei  = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="' + $H + '" w:cs="Times New Roman"/>'

# docDefaults: TNR/SimSun 12pt, no after-spacing (line spacing set per style)
$st = [regex]::Replace($st, '(?s)<w:docDefaults>.*?</w:docDefaults>', { param($m) `
  '<w:docDefaults><w:rPrDefault><w:rPr>' + $fontsBody + `
  '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:bidi="ar-SA" w:eastAsia="zh-CN" w:val="en-US"/></w:rPr></w:rPrDefault>' + `
  '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' })

# Normal
$st = RepStyle $st 'Normal' ('<w:style w:default="1" w:styleId="Normal" w:type="paragraph"><w:name w:val="Normal"/><w:qFormat/></w:style>')

# BodyText: xiaosi, 1.5 lines, first-line indent 2 chars, justified
$st = RepStyle $st 'BodyText' ('<w:style w:styleId="BodyText" w:type="paragraph"><w:name w:val="Body Text"/><w:basedOn w:val="Normal"/><w:link w:val="BodyTextChar"/>' + `
  '<w:pPr><w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="480" w:firstLineChars="200"/><w:jc w:val="both"/></w:pPr><w:qFormat/></w:style>')

# FirstParagraph: same as body (Chinese convention indents first paragraph too)
$st = RepStyle $st 'FirstParagraph' ('<w:style w:customStyle="1" w:styleId="FirstParagraph" w:type="paragraph"><w:name w:val="First Paragraph"/><w:basedOn w:val="BodyText"/><w:next w:val="BodyText"/><w:qFormat/></w:style>')

# Compact: table cell text, wuhao, single spacing, centered
$st = RepStyle $st 'Compact' ('<w:style w:customStyle="1" w:styleId="Compact" w:type="paragraph"><w:name w:val="Compact"/><w:basedOn w:val="Normal"/>' + `
  '<w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:rPr><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')

# Heading1 = paper title: SimHei xiaoer(18pt) centered
$st = RepStyle $st 'Heading1' ('<w:style w:styleId="Heading1" w:type="paragraph"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>' + `
  '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="240" w:line="360" w:lineRule="auto"/><w:outlineLvl w:val="0"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:rPr>' + $fontsHei + '<w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>')

# Heading2 = chapter: SimHei sanhao(16pt) centered
$st = RepStyle $st 'Heading2' ('<w:style w:styleId="Heading2" w:type="paragraph"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>' + `
  '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120" w:line="360" w:lineRule="auto"/><w:outlineLvl w:val="1"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:rPr>' + $fontsHei + '<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>')

# Heading3 = section: SimHei sihao(14pt) left
$st = RepStyle $st 'Heading3' ('<w:style w:styleId="Heading3" w:type="paragraph"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>' + `
  '<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="100" w:line="360" w:lineRule="auto"/><w:outlineLvl w:val="2"/><w:ind w:firstLine="0"/></w:pPr>' + `
  '<w:rPr>' + $fontsHei + '<w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>')

# Heading4 = subsection: SimHei xiaosi(12pt) left
$st = RepStyle $st 'Heading4' ('<w:style w:styleId="Heading4" w:type="paragraph"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="BodyText"/><w:qFormat/>' + `
  '<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60" w:line="360" w:lineRule="auto"/><w:outlineLvl w:val="3"/><w:ind w:firstLine="0"/></w:pPr>' + `
  '<w:rPr>' + $fontsHei + '<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>')

# SourceCode: Consolas 9pt, single spacing, light gray shading
$st = RepStyle $st 'SourceCode' ('<w:style w:styleId="SourceCode" w:type="paragraph"><w:name w:val="Source Code"/><w:basedOn w:val="Normal"/>' + `
  '<w:pPr><w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/><w:ind w:left="420" w:firstLine="0"/><w:shd w:val="clear" w:color="auto" w:fill="F5F5F5"/></w:pPr>' + `
  '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="' + $S + '"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

# BlockText = table notes: 9pt, no indent, single spacing
$st = RepStyle $st 'BlockText' ('<w:style w:styleId="BlockText" w:type="paragraph"><w:name w:val="Block Text"/><w:basedOn w:val="Normal"/>' + `
  '<w:pPr><w:spacing w:before="40" w:after="120" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0" w:left="0"/><w:jc w:val="both"/></w:pPr>' + `
  '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

# Caption (figure/table captions): wuhao bold centered
$st = RepStyle $st 'Caption' ('<w:style w:styleId="Caption" w:type="paragraph"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/>' + `
  '<w:pPr><w:spacing w:before="80" w:after="80" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:rPr><w:b/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')

# Bibliography: wuhao, hanging indent
$st = RepStyle $st 'Bibliography' ('<w:style w:styleId="Bibliography" w:type="paragraph"><w:name w:val="Bibliography"/><w:basedOn w:val="Normal"/>' + `
  '<w:pPr><w:spacing w:before="0" w:after="40" w:line="300" w:lineRule="auto"/><w:ind w:left="420" w:hanging="420" w:firstLine="0"/><w:jc w:val="left"/></w:pPr>' + `
  '<w:rPr><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>')

# VerbatimChar (code run char style): Consolas 9pt to match SourceCode paragraph style
$st = RepStyle $st 'VerbatimChar' ('<w:style w:customStyle="1" w:styleId="VerbatimChar" w:type="character"><w:name w:val="Verbatim Char"/>' + `
  '<w:basedOn w:val="DefaultParagraphFont"/><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="' + $S + '"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

# FootnoteText: 9pt single
$st = RepStyle $st 'FootnoteText' ('<w:style w:styleId="FootnoteText" w:type="paragraph"><w:name w:val="footnote text"/><w:basedOn w:val="Normal"/>' + `
  '<w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/></w:pPr>' + `
  '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')

# Table style: three-line table (thick top/bottom, no vertical/inner rules), centered
$threeLine = '<w:tblBorders>' + `
  '<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>' + `
  '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>' + `
  '<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>' + `
  '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>' + `
  '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>' + `
  '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>' + `
  '</w:tblBorders>'
$cellMar = '<w:tblCellMar><w:top w:type="dxa" w:w="30"/><w:left w:type="dxa" w:w="80"/><w:bottom w:type="dxa" w:w="30"/><w:right w:type="dxa" w:w="80"/></w:tblCellMar>'
$st = RepStyle $st 'Table' ('<w:style w:styleId="Table" w:type="table"><w:name w:val="Table"/><w:qFormat/>' + `
  '<w:tblPr>' + $threeLine + $cellMar + '</w:tblPr>' + `
  '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr></w:style>')

# New styles: abstract heading / abstract body
$newStyles = '<w:style w:customStyle="1" w:styleId="AbsHead" w:type="paragraph"><w:name w:val="Abstract Heading"/><w:basedOn w:val="Normal"/><w:qFormat/>' + `
  '<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="120" w:line="360" w:lineRule="auto"/><w:outlineLvl w:val="1"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:rPr>' + $fontsHei + '<w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>' + `
  '<w:style w:customStyle="1" w:styleId="AbsBody" w:type="paragraph"><w:name w:val="Abstract Body"/><w:basedOn w:val="Normal"/><w:qFormat/>' + `
  '<w:pPr><w:spacing w:before="0" w:after="60" w:line="300" w:lineRule="auto"/><w:ind w:firstLine="420" w:firstLineChars="200"/><w:jc w:val="both"/></w:pPr>' + `
  '<w:rPr><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>'
$st = $st.Replace('</w:styles>', $newStyles + '</w:styles>')
WriteXml $sp $st
Write-Host 'styles.xml rewritten'

# =========================================================
# 2) document.xml transformations
# =========================================================
$dp = Join-Path $x 'word\document.xml'
$doc = ReadXml $dp

# 2a) table cell paragraphs: left -> center
$doc = $doc.Replace('<w:pStyle w:val="Compact" /><w:jc w:val="left" />', '<w:pStyle w:val="Compact" /><w:jc w:val="center" />')
# 2b) tables: start -> center
$doc = $doc.Replace('<w:jc w:val="start" /></w:tblPr>', '<w:jc w:val="center" /></w:tblPr>')

# 2c) ordered node walk (tables + paragraphs)
$nodeRx = [regex]'<w:tbl>.*?</w:tbl>|<w:p[ >].*?</w:p>'
$ms = $nodeRx.Matches($doc)
$nodes = New-Object System.Collections.ArrayList
foreach ($m in $ms) {
  $s = $m.Value
  $style = ''
  if ($s -match '<w:pStyle w:val="([^"]+)"') { $style = $Matches[1] }
  $txt = ([regex]::Matches($s, '<w:t[^>]*>([^<]*)</w:t>') | ForEach-Object { $_.Groups[1].Value }) -join ''
  [void]$nodes.Add([pscustomobject]@{
    IsTbl = $s.StartsWith('<w:tbl>')
    Draw  = $s.Contains('<w:drawing>')
    Math  = $s.Contains('<m:oMathPara')
    Style = $style
    Text  = $txt.Trim()
  })
}
$refIdx = -1; $absIdx = -1; $kwIdx = -1
for ($i = 0; $i -lt $nodes.Count; $i++) {
  $n = $nodes[$i]
  if ($n.Style -eq 'Heading2' -and $n.Text -eq $REFH) { $refIdx = $i }
  if ($n.Style -eq 'Heading2' -and $n.Text -eq $ABS -and $absIdx -lt 0) { $absIdx = $i }
}
if ($absIdx -ge 0) {
  for ($i = $absIdx + 1; $i -lt $nodes.Count; $i++) {
    if ($nodes[$i].Text.StartsWith($KW)) { $kwIdx = $i; break }
  }
}
Write-Host ("nodes=" + $nodes.Count + " refIdx=" + $refIdx + " absIdx=" + $absIdx + " kwIdx=" + $kwIdx)

# figure caption texts = markdown alt texts, in document order
$mdTxt = [System.IO.File]::ReadAllText((Join-Path $root ('docs\' + $DOCNAME + '.md')), [System.Text.Encoding]::UTF8)
$alts = [regex]::Matches($mdTxt, '!\[([^\]]*)\]\(') | ForEach-Object { $_.Groups[1].Value }
Write-Host ('md alt captions: ' + $alts.Count)
$tblCapRx = '^' + $TBL + '\s*\d+'
$bibRx = '^\[\d+\]'
$stat = @{ cap = 0; figc = 0; mathc = 0; bib = 0; abs = 0; hdr = 0 }
$ctr = 0
$evaluator = [System.Text.RegularExpressions.MatchEvaluator]{
  param($m)
  $i = $script:ctr; $script:ctr++
  $s = $m.Value
  $n = $script:nodes[$i]
  if ($n.IsTbl) {
    # three-line header rule: bottom border on first row cells
    $trEnd = $s.IndexOf('</w:tr>')
    if ($trEnd -gt 0) {
      $head = $s.Substring(0, $trEnd)
      $rest = $s.Substring($trEnd)
      $head2 = $head.Replace('<w:tcPr />', '<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders></w:tcPr>')
      $head2 = $head2.Replace('<w:tcPr/>', '<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders></w:tcPr>')
      if ($head2 -ne $head) { $script:stat.hdr++ }
      $s = $head2 + $rest
    }
    return $s
  }
  # paragraphs
  if ($n.Style -eq 'BodyText' -or $n.Style -eq 'FirstParagraph') {
    # table caption: bold paragraph starting with biao/table N (md: **表 N ...**)
    if ($n.Text -match $tblCapRx -and $s.Contains('<w:b')) {
      $script:stat.cap++
      return $s.Replace('<w:pStyle w:val="' + $n.Style + '" />', '<w:pStyle w:val="Caption" />')
    }
    # drawing paragraph: center, no indent; append missing figure caption below
    if ($n.Draw) {
      $script:stat.figc++
      $fc = $script:figN; $script:figN++
      $alt = ''
      if ($fc -le $script:alts.Count) { $alt = $script:alts[$fc - 1] }
      $alt = $alt.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;')
      $capP = '<w:p><w:pPr><w:pStyle w:val="Caption" /></w:pPr><w:r><w:t xml:space="preserve">' + $script:FIG + ' ' + $fc + '  ' + $alt + '</w:t></w:r></w:p>'
      return $s.Replace('<w:pPr><w:pStyle w:val="' + $n.Style + '" /></w:pPr>', `
        '<w:pPr><w:pStyle w:val="' + $n.Style + '" /><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/></w:pPr>') + $capP
    }
    # display math paragraph: center, no indent
    if ($n.Math) {
      $script:stat.mathc++
      return $s.Replace('<w:pPr><w:pStyle w:val="' + $n.Style + '" /></w:pPr>', `
        '<w:pPr><w:pStyle w:val="' + $n.Style + '" /><w:ind w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/></w:pPr>')
    }
    # references
    if ($refIdx -ge 0 -and $i -gt $refIdx -and $n.Text -match $bibRx) {
      $script:stat.bib++
      return $s.Replace('<w:pStyle w:val="' + $n.Style + '" />', '<w:pStyle w:val="Bibliography" />')
    }
    # abstract body (incl. keywords paragraph)
    if ($absIdx -ge 0 -and $i -gt $absIdx -and $kwIdx -ge 0 -and $i -le $kwIdx) {
      $script:stat.abs++
      return $s.Replace('<w:pStyle w:val="' + $n.Style + '" />', '<w:pStyle w:val="AbsBody" />')
    }
  }
  if ($n.Style -eq 'Heading2' -and $n.Text -eq $script:ABS -and $i -eq $script:absIdx) {
    $script:stat.abs++
    return $s.Replace('<w:pStyle w:val="Heading2" />', '<w:pStyle w:val="AbsHead" />')
  }
  return $s
}
$script:nodes = $nodes; $script:ctr = 0; $script:stat = $stat; $script:ABS = $ABS; $script:absIdx = $absIdx
$script:alts = $alts; $script:figN = 1; $script:FIG = $FIG; $script:tblCapRx = $tblCapRx
$doc = $nodeRx.Replace($doc, $evaluator)
Write-Host ("captions=" + $stat.cap + " figParas=" + $stat.figc + " mathParas=" + $stat.mathc + " refs=" + $stat.bib + " abs=" + $stat.abs + " tblHdrs=" + $stat.hdr)

# 2d) clamp oversized images to text width (A4, margins 1800tw => 8306tw => 5274310 EMU)
$maxCx = 5274000
$extRx = [regex]'cx="(\d+)" cy="(\d+)"'
$doc = $extRx.Replace($doc, {
  param($m)
  $cx = [long]$m.Groups[1].Value; $cy = [long]$m.Groups[2].Value
  if ($cx -gt $maxCx) {
    $cy2 = [math]::Round($cy * $maxCx / $cx)
    return 'cx="' + $maxCx + '" cy="' + $cy2 + '"'
  }
  return $m.Value
})

# 2e) section properties: A4 + margins + footer page number
$sect = '<w:sectPr>' + `
  '<w:footerReference w:type="default" r:id="rIdFtrPg"/>' + `
  '<w:pgSz w:h="16838" w:w="11906"/>' + `
  '<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="851" w:footer="992" w:gutter="0"/>' + `
  '<w:cols w:space="425"/>' + `
  '</w:sectPr>'
if ($doc.Contains('<w:sectPr />')) { $doc = $doc.Replace('<w:sectPr />', $sect) }
elseif ($doc.Contains('<w:sectPr/>')) { $doc = $doc.Replace('<w:sectPr/>', $sect) }
else { Write-Host 'WARN: sectPr not found' }
WriteXml $dp $doc
Write-Host 'document.xml rewritten'

# =========================================================
# 3) footer part (centered page number) + rels + content types
# =========================================================
$W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
$footer = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + `
  '<w:ftr xmlns:w="' + $W + '">' + `
  '<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>' + `
  '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>' + `
  '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>' + `
  '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>' + `
  '</w:p></w:ftr>'
WriteXml (Join-Path $x 'word\footer1.xml') $footer

$rp = Join-Path $x 'word\_rels\document.xml.rels'
$rels = ReadXml $rp
$relAdd = '<Relationship Id="rIdFtrPg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
$rels = $rels.Replace('</Relationships>', $relAdd + '</Relationships>')
WriteXml $rp $rels

$cp = Join-Path $x '[Content_Types].xml'
$ct = ReadXml $cp
$ctAdd = '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
if (-not $ct.Contains('footer1.xml')) { $ct = $ct.Replace('</Types>', $ctAdd + '</Types>') }
WriteXml $cp $ct
Write-Host 'footer part added'

# =========================================================
# 4) well-formedness check + rezip
# =========================================================
foreach ($f in @('word\document.xml', 'word\styles.xml', 'word\footer1.xml', 'word\_rels\document.xml.rels', '[Content_Types].xml')) {
  $xml = New-Object System.Xml.XmlDocument
  $xml.Load((Join-Path $x $f))
}
Write-Host 'xml well-formed OK'

if (Test-Path $dst) { Remove-Item $dst -Force }
$fs = [System.IO.File]::Open($dst, [System.IO.FileMode]::Create)
$zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
$files = Get-ChildItem $x -Recurse -File
foreach ($f in $files) {
  $rel = $f.FullName.Substring($x.Length + 1).Replace('\', '/')
  $entry = $zip.CreateEntry($rel, [System.IO.Compression.CompressionLevel]::Optimal)
  $es = $entry.Open()
  $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
  $es.Write($bytes, 0, $bytes.Length)
  $es.Close()
}
$zip.Dispose(); $fs.Close()
Write-Host ('written: ' + $dst + '  (' + (Get-Item $dst).Length + ' bytes)')
