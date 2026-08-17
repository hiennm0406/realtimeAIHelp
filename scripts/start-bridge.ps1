<#
  Starts the bridge, opens a quick tunnel, and publishes the new address.

  A Cloudflare quick tunnel gets a fresh hostname on every start, and the site
  reads that hostname from a build-time constant - so a restart is only finished
  once the constant has been rebuilt and redeployed. Netlify builds from git, so
  "redeploy" here means: rewrite the constant, commit, push.

  Doing that by hand is what leaves the site pointing at a dead tunnel, with no
  field in the UI to correct it. This script closes the loop instead.

      powershell -ExecutionPolicy Bypass -File scripts\start-bridge.ps1

  -NoPush  updates the source but stops short of committing (dry run).
#>

[CmdletBinding()]
param(
  [switch]$NoPush,
  [int]$TunnelTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$bridgeJs = Join-Path $repo 'src\lib\bridge.js'
$logDir = Join-Path $repo 'bridge\logs'
$tunnelLog = Join-Path $logDir 'cloudflared.log'

function Say($msg) { Write-Host "  $msg" }
function Step($msg) { Write-Host "`n> $msg" -ForegroundColor Cyan }

if (-not (Test-Path $bridgeJs)) { throw "Not a checkout of this repo: $bridgeJs is missing." }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# --- python ------------------------------------------------------------------
# `python` on PATH is often the Microsoft Store alias: it resolves, then exits
# with "Python was not found" instead of running anything. Get-Command cannot
# tell the two apart, so each candidate has to prove itself by printing a
# version.
function Resolve-Python {
  $candidates = @()
  $candidates += (Get-Command python -ErrorAction SilentlyContinue | ForEach-Object Source)
  $candidates += (Get-Command python3 -ErrorAction SilentlyContinue | ForEach-Object Source)
  $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object FullName
  $candidates += 'C:\Python313\python.exe', 'C:\Python312\python.exe'

  foreach ($c in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if ($c -like '*\WindowsApps\*') { continue }  # the Store alias
    if (-not (Test-Path $c)) { continue }
    $version = & $c --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $version -match 'Python 3') { return $c }
  }
  # `py` last: it is a launcher, so it works but hides which interpreter ran.
  if (Get-Command py -ErrorAction SilentlyContinue) { return 'py' }
  return $null
}

$python = Resolve-Python
if (-not $python) { throw 'No working Python 3 found (the Microsoft Store alias does not count).' }

$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) {
  $guess = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
  if (Test-Path $guess) { $cloudflared = $guess } else { throw 'cloudflared not found.' }
}

# --- clear the old pair ------------------------------------------------------
# Both are restarted together on purpose: a tunnel left over from a previous run
# points at the port we are about to rebind, and would keep serving a hostname
# this script is not the one publishing.
Step 'Stopping any previous bridge and tunnel'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*bridge/server.py*' -or $_.CommandLine -like '*bridge\server.py*' } |
  ForEach-Object { Say "bridge pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
  Where-Object { $_.CommandLine -like '*127.0.0.1:8787*' } |
  ForEach-Object { Say "tunnel pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
Start-Sleep -Milliseconds 1200

# --- bridge ------------------------------------------------------------------
Step 'Starting the bridge'
$env:PYTHONUNBUFFERED = '1'
$bridgeLog = Join-Path $logDir 'bridge.log'
Start-Process -FilePath $python -ArgumentList 'bridge/server.py' `
  -WorkingDirectory $repo -WindowStyle Hidden `
  -RedirectStandardError $bridgeLog -RedirectStandardOutput "$bridgeLog.out"
Say "logging to $bridgeLog"

# Poll rather than sleep a fixed amount: an unauthenticated 401 already proves
# the listener is up, and is the fastest honest signal we can get without
# reading the token out of config.json.
$up = $false
foreach ($i in 1..30) {
  try {
    Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 3 | Out-Null
    $up = $true; break
  } catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 401) { $up = $true; break }
    Start-Sleep -Milliseconds 500
  }
}
if (-not $up) {
  $why = (Get-Content $bridgeLog -Raw -ErrorAction SilentlyContinue), `
         (Get-Content "$bridgeLog.out" -Raw -ErrorAction SilentlyContinue) -join "`n"
  throw "Bridge did not come up on 127.0.0.1:8787.`n$($why.Trim())"
}
Say 'listening on 127.0.0.1:8787'

# --- tunnel ------------------------------------------------------------------
Step 'Opening the quick tunnel'
Remove-Item $tunnelLog -ErrorAction SilentlyContinue
Start-Process -FilePath $cloudflared `
  -ArgumentList 'tunnel', '--url', 'http://127.0.0.1:8787', '--no-autoupdate' `
  -WorkingDirectory $repo -WindowStyle Hidden `
  -RedirectStandardError $tunnelLog -RedirectStandardOutput "$tunnelLog.out"

$hostname = $null
$deadline = $TunnelTimeoutSeconds * 2
foreach ($i in 1..$deadline) {
  Start-Sleep -Milliseconds 500
  if (-not (Test-Path $tunnelLog)) { continue }
  $text = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
  $m = [regex]::Match($text, 'https://[a-z0-9\-]+\.trycloudflare\.com')
  if ($m.Success) { $hostname = $m.Value; break }
}
if (-not $hostname) { throw "No tunnel hostname within ${TunnelTimeoutSeconds}s. See $tunnelLog" }
Say $hostname

# Confirm the hostname actually serves this bridge before publishing it, so the
# script cannot commit an address that never answers.
#
# 401 counts as success: no token is sent, so a rejection still proves the
# bridge is on the other end of the tunnel.
#
# The local resolver is not the authority here. A fresh quick-tunnel hostname
# can stay unresolvable on this machine for minutes (negative caching, or an
# ISP resolver that will not serve brand-new names) while the rest of the world
# reaches it fine - which is exactly the case where refusing to publish would be
# wrong. So a local failure falls back to asking a public resolver and talking
# to the edge directly.
function Test-Tunnel {
  param([string]$Url)

  foreach ($i in 1..10) {
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "$Url/api/health" -TimeoutSec 8 | Out-Null
      return 'local'
    } catch {
      if ($_.Exception.Response.StatusCode.value__ -eq 401) { return 'local' }
      Start-Sleep -Seconds 2
    }
  }

  $name = ([uri]$Url).Host
  foreach ($server in @('1.1.1.1', '8.8.8.8')) {
    try {
      $ip = (Resolve-DnsName -Name $name -Type A -Server $server -ErrorAction Stop |
             Where-Object IPAddress | Select-Object -First 1).IPAddress
    } catch { continue }
    if (-not $ip) { continue }
    $code = curl.exe -s -o NUL -w '%{http_code}' --max-time 15 `
      --resolve "${name}:443:$ip" "$Url/api/health" 2>$null
    if ($code -in @('200', '401')) { return "public via $server ($ip)" }
  }
  return $null
}

$reach = Test-Tunnel -Url $hostname
if (-not $reach) { throw "Tunnel $hostname never answered, locally or from a public resolver." }
if ($reach -eq 'local') {
  Say 'tunnel is answering'
} else {
  Say "tunnel is answering $reach"
  Say 'this machine cannot resolve it yet; other devices can. Publishing anyway.'
}

# --- publish -----------------------------------------------------------------
Step 'Updating the site'
$source = Get-Content $bridgeJs -Raw
# No `$` anchor: the file is checked out with CRLF, and a trailing \r sits
# between the closing quote and the line end.
$pattern = "(?m)^const FALLBACK_BRIDGE_URL = '[^']*'"
if (-not [regex]::IsMatch($source, $pattern)) {
  throw "FALLBACK_BRIDGE_URL not found in $bridgeJs - has the constant been renamed?"
}
$current = [regex]::Match($source, $pattern).Value
if ($current -like "*$hostname*") {
  Say 'constant already current, nothing to commit'
} else {
  $updated = [regex]::Replace($source, $pattern, "const FALLBACK_BRIDGE_URL = '$hostname'")
  # -NoNewline: the file already ends in one; Set-Content would add a second.
  Set-Content -Path $bridgeJs -Value $updated -Encoding utf8 -NoNewline
  Say "bridge.js -> $hostname"

  if ($NoPush) {
    Say 'skipping commit (-NoPush)'
  } else {
    Push-Location $repo
    try {
      git add src/lib/bridge.js
      git commit -m "Point the site at the current bridge tunnel

Quick tunnels get a new hostname on every restart, and the site reads
the address from a build-time constant, so the constant has to follow.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" | Out-Null
      git push | Out-Null
      Say 'pushed to origin/main - Netlify will rebuild'
    } finally { Pop-Location }
  }
}

# --- allowed_origins ---------------------------------------------------------
# The site's own origin is a separate axis: it only changes when the site moves,
# not when the tunnel restarts, so this is a reminder rather than an edit.
$config = Join-Path $repo 'bridge\config.json'
if (Test-Path $config) {
  $origins = (Get-Content $config -Raw | ConvertFrom-Json).allowed_origins
  Step 'Origins the bridge will accept'
  $origins | ForEach-Object { Say $_ }
  Say 'Opening the site from anywhere else fails with "Failed to fetch".'
}

Write-Host "`nBridge is live at $hostname" -ForegroundColor Green
