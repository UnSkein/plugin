# UnSkein mori - Stop CDP Chrome only. Normal Chrome stays untouched by default.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1
#   powershell -ExecutionPolicy Bypass -File <skill>/scripts/stop.ps1 -All
#
# Policy:
#   - Default: kill only chrome.exe with --user-data-dir matching ".cdp-chrome*" or port 9222.
#   - -All: kill EVERY chrome.exe on the system. Requires explicit user request.

param(
    [switch]$All
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

$Port = 9222

$killed = 0
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*.cdp-chrome*" -or $_.CommandLine -like "*--remote-debugging-port=$Port*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }

Write-Host "[CDP] Killed $killed CDP Chrome process(es). Normal Chrome untouched."
