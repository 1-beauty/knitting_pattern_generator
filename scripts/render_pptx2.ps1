param(
  [string]$InPath,
  [string]$OutDir
)
if (!(Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
try {
  $pp = [Runtime.InteropServices.Marshal]::GetActiveObject("PowerPoint.Application")
} catch {
  $pp = New-Object -ComObject PowerPoint.Application
  Start-Sleep -Seconds 3
}
$pres = $null
for ($j = 0; $j -lt 8 -and $null -eq $pres; $j++) {
  try { $pres = $pp.Presentations.Open($InPath, $true, $false, $false) }
  catch { Start-Sleep -Seconds 2 }
}
if ($null -eq $pres) { Write-Output "OPEN FAILED"; exit 1 }
$count = 0
for ($j = 0; $j -lt 15 -and $count -eq 0; $j++) {
  try { $count = $pres.Slides.Count } catch { }
  if ($count -eq 0) { Start-Sleep -Seconds 1 }
}
for ($i = 1; $i -le $count; $i++) {
  $file = Join-Path $OutDir ("slide_{0:D2}.png" -f $i)
  $ok = $false; $tries = 0
  while (-not $ok -and $tries -lt 6) {
    try { $pres.Slides.Item($i).Export($file, "PNG", 1600, 900); $ok = $true }
    catch { $tries++; Start-Sleep -Milliseconds 800 }
  }
  if (-not $ok) { Write-Output "slide $i FAILED" }
}
try { $pres.Close() } catch { }
Write-Output "DONE $count"
