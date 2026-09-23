# Close a running KASTR before a build (standing workflow rule: builds never
# collide with a live instance). Durable in the repo so it survives tooling
# sessions. Safe to run when nothing is up.
#
#   powershell -NoProfile -File .\close-kastr.ps1            # the app on port 8000
#   powershell -NoProfile -File .\close-kastr.ps1 -Port 8971 # the dev harness
#
# 0.9.8: ask first. POST /api/quit ends KASTR the way closing its window does --
# publishers, monitors, relay and window all torn down -- where a hard kill left
# the ffmpeg | moq publisher pairs running (they kept the operator's cameras on
# the relay as tiles nobody could stop). The hard kill is the fallback, followed
# by a sweep of the bundled helpers by executable path: the frozen build runs
# them from %TEMP%\_MEIxxxx\bin, the source tree from .\bin.

param([int]$Port = 8000)

$ErrorActionPreference = "SilentlyContinue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$pid0 = $null
try {
  $inst = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/instance" -TimeoutSec 2
  if ($inst.app -eq "KASTR" -and $inst.pid) { $pid0 = [int]$inst.pid }
} catch {}

$clean = $false
if ($pid0) {
  try {
    $r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/quit" -TimeoutSec 3
    if ($r.status -eq "quitting" -or $r.status -eq "dev") {
      $p = Get-Process -Id $pid0 -ErrorAction SilentlyContinue
      if ($p) { $clean = $p.WaitForExit(10000) } else { $clean = $true }
    }
  } catch {}
  if (-not $clean) {
    $p = Get-Process -Id $pid0 -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $pid0 -Force -Confirm:$false }
  }
}

# A clean quit tears the children down within about a second of the process
# ending (the Job Object closes with it); give that a moment before sweeping,
# so the sweep reports what was actually left behind.
Start-Sleep -Milliseconds $(if ($clean) { 1500 } else { 500 })

# The launcher (bootloader + child), whatever answered above.
Get-Process -Name "KASTR" | ForEach-Object { Stop-Process -Id $_.Id -Force -Confirm:$false }

# Bundled helpers left behind: matched by where they run from, never by name alone.
$swept = 0
Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe' OR Name='moq.exe' OR Name='moq-relay.exe'" | Where-Object {
  $x = $_.ExecutablePath
  $x -and (($x -like "*\_MEI*\bin\*") -or ($x -like ($here + "\bin\*")) -or ($x -like "*\KASTR\bin\*") -or ($x -like "*\KASTR\dist\*"))
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -Confirm:$false
  $swept++
}

if ($clean) { Write-Output ("KASTR quit cleanly (pid " + $pid0 + ")" + $(if ($swept) { "; swept $swept helper process(es)" } else { "" }) + ".") }
elseif ($pid0) { Write-Output ("KASTR pid " + $pid0 + " did not answer /api/quit -- killed; swept $swept helper process(es).") }
else { Write-Output ("KASTR closed (or nothing was running); swept $swept helper process(es).") }
