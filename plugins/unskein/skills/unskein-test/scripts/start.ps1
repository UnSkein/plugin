# UnSkein mori - CDP-mode Chrome starter for browser/UI testing.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Force
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Url http://localhost:5173
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/start.ps1 -Profile work
#
# Policy:
#   - Single CDP Chrome at port 9222 (one profile at a time).
#   - To switch profile: stop.ps1 first, then start.ps1 -Profile <name>.
#   - -Force only kills CDP Chrome (matched by user-data-dir or port). Normal Chrome untouched.
#   - Default profile: %USERPROFILE%\.cdp-chrome  (dedicated, separate from normal Chrome)
#   - Named profile:   %USERPROFILE%\.cdp-chrome-<name>  (-Profile <name>)

param(
    [switch]$Force,
    [string]$Url = 'about:blank',
    [string]$Profile = ''
)

$ErrorActionPreference = 'Stop'

$Port = 9222
if ($Profile -ne '') {
    $UserData = Join-Path $env:USERPROFILE ".cdp-chrome-$Profile"
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

# 1. Check if already up (DevTools endpoint ping)
function Test-CdpReady {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-CdpReady) {
    if ($Force) {
        Write-Host "[CDP] Force mode - killing existing CDP Chrome..."
        Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
            Where-Object { $_.CommandLine -like "*.cdp-chrome*" -or $_.CommandLine -like "*--remote-debugging-port=$Port*" } |
            ForEach-Object {
                Write-Host "  killing PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 2
    } else {
        $info = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version"
        Write-Host "[CDP] Already running. $($info.Browser)"
        Write-Host "[CDP] Profile: (existing - to switch run stop.ps1 first)"
        Write-Host "[CDP] WebSocket: $($info.webSocketDebuggerUrl)"
        exit 0
    }
}

# 2. Prepare user-data-dir
if (-not (Test-Path $UserData)) {
    New-Item -ItemType Directory -Path $UserData -Force | Out-Null
    Write-Host "[CDP] Created profile dir: $UserData"
}

# 3. Start Chrome
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

# 4. Wait for DevTools endpoint (max 60s - first run can be slow due to profile setup)
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-CdpReady) { $ready = $true; break }
}

if (-not $ready) {
    Write-Error "[CDP] DevTools endpoint not ready after 60s"
    exit 1
}

$info = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version"
Write-Host "[CDP] READY. Browser: $($info.Browser)"
Write-Host "[CDP] Endpoint: http://127.0.0.1:$Port"
Write-Host "[CDP] Profile: $UserData"
Write-Host "[CDP] Use: node <skill>/scripts/remote.js <command>"
