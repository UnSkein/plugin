# UnSkein mori - Stop CDP Chrome only. Normal Chrome stays untouched by default.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1                  # all CDP Chromes (every port)
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1 -Port 9223      # only that session
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1 -Profile work   # only that profile's session
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1 -All
#
# Policy:
#   - Default: kill every chrome.exe whose --user-data-dir matches ".cdp-chrome*" (any port).
#     (A CDP Chrome started OUTSIDE these scripts with a non-.cdp-chrome profile is not
#      matched by default - use -Port for it.)
#   - -Port <n>: kill only that session - that port, its paired default profile, AND the
#     actual profile the port-owning browser runs with (children like crashpad follow).
#   - -Profile <name>: kill only the ".cdp-chrome-<name>" session.
#   - -Profile wins if both -Profile and -Port are given.
#   - -All: kill EVERY chrome.exe on the system. Requires explicit user request.

param(
    [switch]$All,
    [int]$Port = 0,
    [string]$Profile = ''
)

if ($All) {
    Write-Host "[CDP] -All flag set - killing every chrome.exe (explicit request only)..."
    $procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'"
    $count = ($procs | Measure-Object).Count
    $procs | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[CDP] Killed $count chrome.exe process(es)."
    exit 0
}

# Build the session matcher. Boundary-safe: ".cdp-chrome" must not match
# ".cdp-chrome-9223", and port 9222 must not match 92223 (same rules as start.ps1).
$matchers = @()
if ($Profile -ne '') {
    $ud = Join-Path $env:USERPROFILE ".cdp-chrome-$Profile"
    $matchers += ([regex]::Escape("--user-data-dir=$ud") + '("|\s|$)')
    $matchers += [regex]::Escape('--user-data-dir="' + $ud + '"')
    $scope = "profile $ud"
} elseif ($Port -ne 0) {
    $portRe = [regex]::Escape("--remote-debugging-port=$Port") + '("|\s|$)'
    $matchers += $portRe
    # Paired default profile for this port (see start.ps1 pairing).
    if ($Port -eq 9222) {
        $ud = Join-Path $env:USERPROFILE ".cdp-chrome"
    } else {
        $ud = Join-Path $env:USERPROFILE ".cdp-chrome-$Port"
    }
    $matchers += ([regex]::Escape("--user-data-dir=$ud") + '("|\s|$)')
    $matchers += [regex]::Escape('--user-data-dir="' + $ud + '"')
    # The session may have been started with -Profile <name> (profile != paired default).
    # Read the ACTUAL --user-data-dir off the port-owning browser and match it too, so
    # children without the port flag (crashpad etc.) die with the session.
    $owner = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match $portRe) -and -not ($_.CommandLine -match '--type=') } |
        Select-Object -First 1
    if ($owner -and $owner.CommandLine -match '--user-data-dir=(?:"([^"]+)"|([^\s"]+))') {
        $ownerUd = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        $matchers += ([regex]::Escape("--user-data-dir=$ownerUd") + '("|\s|$)')
        $matchers += [regex]::Escape('--user-data-dir="' + $ownerUd + '"')
    }
    $scope = "port $Port"
} else {
    # All CDP sessions: any user-data-dir under %USERPROFILE% named .cdp-chrome or .cdp-chrome-*.
    $base = Join-Path $env:USERPROFILE ".cdp-chrome"
    $matchers += ([regex]::Escape($base) + '[^\\"]*("|\s|$)')
    $scope = "all CDP Chromes"
}

$killed = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object {
        $cl = $_.CommandLine
        if (-not $cl) { return $false }
        foreach ($m in $matchers) { if ($cl -match $m) { return $true } }
        return $false
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }

Write-Host "[CDP] Killed $killed CDP Chrome process(es) ($scope). Normal Chrome untouched."
