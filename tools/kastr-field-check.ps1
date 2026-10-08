# KASTR field check (Windows) -- read-only. Run on the box itself (hub or spoke), in a normal PowerShell:
#   powershell -ExecutionPolicy Bypass -File kastr-field-check.ps1
# Collects this KASTR's version, relay + federation + cluster status, relay health, the hub's spoke table and the
# relay / launch log lines about the cluster into one text file on the Desktop. Tokens and access codes are blanked.
param([int]$Port = 0)   # optional: the KASTR web port when it is not the remembered one
$ErrorActionPreference = "SilentlyContinue"
$state = Join-Path $env:LOCALAPPDATA "ASI\KASTR"
$port = $Port
$pf = Join-Path $state "http-port"
if (-not $port -and (Test-Path $pf)) { $port = [int](Get-Content $pf -Raw).Trim() }
if (-not $port) { foreach ($p in 8000, 8001, 8002) { try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$p/api/instance" -TimeoutSec 3 | Out-Null; $port = $p; break } catch {} } }
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) ("kastr-field-" + $env:COMPUTERNAME + "-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
function Redact([string]$t) {
  $t = $t -replace '(?i)(jwt=)[A-Za-z0-9._\-]+', '$1<redacted>'
  $t = $t -replace '(?i)("(token|code|access|secret|roomKey|admin|publisher|viewer|federation)"\s*:\s*)"[^"]*"', '$1"<redacted>"'
  $t = $t -replace '(?i)(Bearer\s+)[A-Za-z0-9._\-]+', '$1<redacted>'
  return $t
}
function Section($title, $body) { Add-Content -Path $out -Value ("`r`n===== " + $title + " =====`r`n" + (Redact $body)) -Encoding utf8 }
Set-Content -Path $out -Value ("KASTR field check  " + (Get-Date -Format "u") + "  host " + $env:COMPUTERNAME + "  web port " + $port) -Encoding utf8
if (-not $port) { Section "error" "no KASTR answered on this machine (is it running?)"; Write-Host "Wrote $out"; exit 1 }
foreach ($ep in "/api/instance", "/api/relay/status", "/api/relay/cluster", "/api/relay/health", "/api/relay/spokes", "/api/lan/advertise") {
  try { $r = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:$port" + $ep) -TimeoutSec 15; Section $ep $r.Content }
  catch { Section $ep ("failed: " + $_.Exception.Message) }
}
$ll = Join-Path $state "launch.log"
if (Test-Path $ll) {
  $lines = Get-Content $ll -Tail 4000 | Where-Object { $_ -match '(?i)cluster|federation|spoke|hub|relay:|rehome|token|session' } | Select-Object -Last 250
  Section "launch.log (cluster / federation lines, last 250)" ($lines -join "`r`n")
} else { Section "launch.log" ("not found at " + $ll) }
Write-Host "Wrote $out -- send this file."
