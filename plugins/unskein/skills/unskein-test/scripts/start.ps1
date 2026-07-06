# UnSkein mori - CDP-mode Chrome starter for browser/UI testing.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Force
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Url http://localhost:5173
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Profile work
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Port 9223   # parallel session
#
# Policy:
#   - One CDP Chrome per port; different ports run in PARALLEL (session isolation).
#   - Port <-> profile is 1:1. Default pairing:
#       9222          -> %USERPROFILE%\.cdp-chrome           (back-compat default)
#       other <port>  -> %USERPROFILE%\.cdp-chrome-<port>
#       -Profile <n>  -> %USERPROFILE%\.cdp-chrome-<n>       (explicit name wins over port pairing)
#     The PROFILE is the auth boundary (cookies/localStorage/JWT) - tabs share auth,
#     profiles never do. Different port+profile => fully isolated logins.
#   - Pairing conflicts are refused loudly (no silent success):
#       * this profile held by a Chrome on ANOTHER port  -> refuse (Chrome would delegate
#         to the existing process and this port would never come up)
#       * this port held by a DIFFERENT profile          -> refuse (logins would mix -
#         auth lives in the profile, not the tab)
#   - -Force = take over this pairing: kills the CDP Chrome(s) holding this exact port
#     AND/OR this exact profile (wherever they run), then starts fresh.
#     Unrelated sessions (other port + other profile) and normal Chrome are untouched.

param(
    [switch]$Force,
    [string]$Url = 'about:blank',
    [string]$Profile = '',
    [int]$Port = 9222
)

$ErrorActionPreference = 'Stop'

# Port <-> profile pairing (1:1). Explicit -Profile wins; default 9222 keeps the
# legacy dir (existing logins survive); any other port gets its own dir.
if ($Profile -ne '') {
    $UserData = Join-Path $env:USERPROFILE ".cdp-chrome-$Profile"
} elseif ($Port -ne 9222) {
    $UserData = Join-Path $env:USERPROFILE ".cdp-chrome-$Port"
} else {
    $UserData = Join-Path $env:USERPROFILE ".cdp-chrome"
}

$ChromeExe = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path $ChromeExe)) {
    $ChromeExe = 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
}
if (-not (Test-Path $ChromeExe)) {
    Write-Error "chrome.exe not found at standard paths"
    exit 1
}

# Session matchers - boundary-safe so ".cdp-chrome" never matches ".cdp-chrome-9223",
# and port 9222 never matches 92223. Covers quoted and unquoted --user-data-dir.
$PortRe = [regex]::Escape("--remote-debugging-port=$Port") + '("|\s|$)'
$UdRe   = [regex]::Escape("--user-data-dir=$UserData") + '("|\s|$)'
$UdReQ  = [regex]::Escape('--user-data-dir="' + $UserData + '"')

function Test-SessionChrome([string]$CommandLine) {
    if (-not $CommandLine) { return $false }
    return ($CommandLine -match $PortRe) -or ($CommandLine -match $UdRe) -or ($CommandLine -match $UdReQ)
}

# 1. Check if already up (DevTools endpoint ping - this port only)
function Test-CdpReady {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

if ($Force) {
    # Take over this pairing regardless of endpoint state - clears this port's session,
    # this profile's session (even on another port), and same-port zombies (process
    # alive but endpoint dead). Unrelated sessions untouched.
    Write-Host "[CDP] Force mode - taking over pairing (port $Port / profile $UserData)..."
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { Test-SessionChrome $_.CommandLine } |
        ForEach-Object {
            Write-Host "  killing PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
} elseif (Test-CdpReady) {
    # Port answers - but only reuse it if it is OUR profile (auth lives in the profile;
    # silently reusing another profile's Chrome would mix logins - the exact accident
    # the port<->profile pairing exists to prevent).
    $owner = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object {
            $cl = $_.CommandLine
            $cl -and ($cl -match $PortRe) -and -not ($cl -match '--type=')
        } | Select-Object -First 1
    if ($owner -and -not (($owner.CommandLine -match $UdRe) -or ($owner.CommandLine -match $UdReQ))) {
        Write-Error ("[CDP] Port $Port is already held by a DIFFERENT profile (PID $($owner.ProcessId)). " +
                     "Reusing it would mix logins (auth lives in the profile). " +
                     "Stop it first (stop.ps1 -Port $Port), pick another port, or -Force to take over.")
        exit 1
    }
    $info = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version"
    Write-Host "[CDP] Already running on port $Port. $($info.Browser)"
    Write-Host "[CDP] Profile: $UserData (existing session reused - -Url ignored)"
    Write-Host "[CDP] WebSocket: $($info.webSocketDebuggerUrl)"
    exit 0
}

# 2. Refuse if this profile is already held by a Chrome on another port -
#    Chrome would delegate to that process and port $Port would never come up
#    (start would wait 60s and fail with a misleading error).
#    Child processes (--type=..., e.g. crashpad-handler) carry --user-data-dir but never
#    the port flag - exclude them, only the browser process can cause delegation.
$held = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object {
        $cl = $_.CommandLine
        $cl -and (($cl -match $UdRe) -or ($cl -match $UdReQ)) -and
            -not ($cl -match $PortRe) -and -not ($cl -match '--type=')
    } | Select-Object -First 1
if ($held) {
    Write-Error ("[CDP] Profile $UserData is already used by another Chrome (PID $($held.ProcessId), different port). " +
                 "Chrome would delegate to it and port $Port would never come up. " +
                 "Use that session's port, stop it first (stop.ps1 -Profile <name> / -Port <n>), or -Force to take over.")
    exit 1
}

# 3. Prepare user-data-dir
if (-not (Test-Path $UserData)) {
    New-Item -ItemType Directory -Path $UserData -Force | Out-Null
    Write-Host "[CDP] Created profile dir: $UserData"
}

# 4. Start Chrome
$chromeArgs = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$UserData",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=ChromeWhatsNewUI",
    "--restore-last-session=false",
    $Url
)

Write-Host "[CDP] Starting Chrome (port $Port, profile $UserData)..."
Start-Process -FilePath $ChromeExe -ArgumentList $chromeArgs | Out-Null

# 5. Wait for DevTools endpoint (max 60s - first run can be slow due to profile setup)
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-CdpReady) { $ready = $true; break }
}

if (-not $ready) {
    Write-Error "[CDP] DevTools endpoint not ready after 60s (port $Port)"
    exit 1
}

$info = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version"
Write-Host "[CDP] READY. Browser: $($info.Browser)"
Write-Host "[CDP] Endpoint: http://127.0.0.1:$Port"
Write-Host "[CDP] Profile: $UserData"
if ($Port -ne 9222) {
    Write-Host "[CDP] Use: node <skill>/scripts/remote.js <command> --port=$Port   (or set CDP_PORT=$Port)"
} else {
    Write-Host "[CDP] Use: node <skill>/scripts/remote.js <command>"
}
