param(
  [string]$InPath = "e:\DeskTop\knitting_ai_competition.pptx",
  [string]$OutDir = "e:\DeskTop\knitting_pattern_generator\scripts\render"
)
if (!(Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

# PowerPoint 的 COM 初始化很不稳定：刚创建出来时 Presentations 可能还是 null，
# 也可能残留的实例把调用直接拒掉。所以每一步都轮询重试。
$pp = $null
for ($k = 0; $k -lt 10; $k++) {
  try {
    if ($null -eq $pp) { $pp = New-Object -ComObject PowerPoint.Application }
    try { $pp.DisplayAlerts = 1 } catch { }
    try { $pp.Visible = -1 } catch { }
    if ($null -ne $pp.Presentations) { break }
  } catch { $pp = $null }
  Start-Sleep -Seconds 3
}
if ($null -eq $pp -or $null -eq $pp.Presentations) { Write-Output "APP FAILED"; exit 1 }

$err = ""
$pres = $null
for ($k = 0; $k -lt 8 -and $null -eq $pres; $k++) {
  try { $pres = $pp.Presentations.Open($InPath, $true, $false, $true) }
  catch { $err = $_.Exception.Message; Start-Sleep -Seconds 3 }
}
if ($null -eq $pres) {
  Write-Output "OPEN FAILED: $err"
  try { $pp.Quit() } catch {}
  exit 1
}

Start-Sleep -Seconds 3
$w = 1600; $h = 900
$count = 0
for ($j = 0; $j -lt 12 -and $count -eq 0; $j++) {
  try { $count = $pres.Slides.Count } catch { }
  if ($count -eq 0) {
    try { $count = $pp.ActivePresentation.Slides.Count; $pres = $pp.ActivePresentation } catch { }
  }
  if ($count -eq 0) { Start-Sleep -Seconds 2 }
}
Write-Output "count=$count"
for ($i = 1; $i -le $count; $i++) {
  $num = "{0:D2}" -f $i
  $file = Join-Path $OutDir ("slide_$num.png")
  $ok = $false; $tries = 0
  while (-not $ok -and $tries -lt 5) {
    try { $pres.Slides.Item($i).Export($file, "PNG", $w, $h); $ok = $true }
    catch { $tries++; Start-Sleep -Milliseconds 800 }
  }
  Write-Output "slide $i ok=$ok tries=$tries"
}
Start-Sleep -Seconds 1
try { $pres.Close() } catch {}
Start-Sleep -Seconds 1
try { $pp.Quit() } catch {}
Write-Output "DONE $count"
