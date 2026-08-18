<#
  pairing.ps1 — TESTER 번들의 CDP 포트↔프로필 배정을 계산한다 (윈도우 전용).

  왜 있나: 한 윈도우 호스트가 여러 프로젝트의 화면검증을 담당하면 번들마다 다른 CDP 포트를
  써야 한다(인증 경계가 탭이 아니라 프로필이라 — unskein-test §3). 종전에는 사람이 겹치지
  않게 고르고 `cdp\pairing.txt` 에 메모만 남겼고, 그 메모를 읽는 코드가 없어 겹쳐도 막히지
  않았다. 겹치면 start.ps1 이 기동을 거부하는 자리에서야 드러난다. 이 스크립트가 배정을
  사람 기억이 아니라 계산으로 바꾼다.

  누가 쓰나:
    - unskein-setup §T1  — 새 번들을 만들 때 `next` 로 빈 포트를 받아 배정하고 `record` 로 기록
    - unskein-doctor 8번 — `check` 로 번들 사이 포트 중복을 선제 진단

  전제: Windows PowerShell 5.1 (이 저장소는 .ps1 을 항상 powershell.exe 로 부른다).
        5.1 에 없는 문법·인자를 쓰지 않는다(`-Encoding utf8NoBOM` 은 6+ 전용이라 안 쓴다).

  실행:
    powershell.exe -ExecutionPolicy Bypass -File pairing.ps1 -Action list
    powershell.exe -ExecutionPolicy Bypass -File pairing.ps1 -Action check
    powershell.exe -ExecutionPolicy Bypass -File pairing.ps1 -Action next
    powershell.exe -ExecutionPolicy Bypass -File pairing.ps1 -Action record -Bundle EMAX__FRAMEWEB_ERP -Port 9225

  종료코드: 0 정상 / 1 배정 충돌(check) / 2 인자·경로 오류.
    중복을 못 찾은 것과 확인을 못 한 것을 섞지 않는다 — 읽기 실패는 2 로 낸다(조용한 통과 금지).
#>
[CmdletBinding()]
param(
  [ValidateSet('list', 'check', 'next', 'record')]
  [string]$Action = 'list',

  # record 대상 번들 디렉토리 이름(= CDP_PROFILE, 보통 <business>__<project>).
  # 'Profile' 은 PowerShell 자동 변수 $PROFILE 과 겹쳐 쓰지 않는다.
  [string]$Bundle,

  [int]$Port,

  # next 탐색 시작 포트. 9222 는 CDP 관례 기본값이다.
  [int]$From = 9222,

  # 번들 루트. 기본 %USERPROFILE%\.unskein
  [string]$Root
)

$ErrorActionPreference = 'Stop'

if (-not $Root -or $Root -eq '') { $Root = Join-Path $env:USERPROFILE '.unskein' }

function Read-TextLines([string]$Path) {
  # [IO.File]::ReadAllLines 는 BOM 을 감지해 걷어낸다 — 사람이 메모장으로 고쳐 BOM 이
  # 붙어도 읽는다(케이스 파일과 같은 방침: 쓸 때만 BOM 없이, 읽을 때는 관용).
  return [System.IO.File]::ReadAllLines($Path)
}

function Parse-PairingLine([string]$Line) {
  # 한 줄에서 포트와 프로필 이름을 뽑는다. 호스트마다 남아 있는 표기가 달라 세 가지를 모두 견딘다:
  #   CDP_PORT=9223 CDP_PROFILE=NAME   ← 정본(아래 record 가 쓰는 형식)
  #   9223 <-> NAME
  #   9223 NAME
  $t = $Line
  $h = $t.IndexOf('#')
  if ($h -ge 0) { $t = $t.Substring(0, $h) }        # '#' 뒤는 주석
  $t = $t.Trim()
  if ($t -eq '') { return $null }

  $port = $null
  $name = $null

  $m = [regex]::Match($t, 'CDP_PORT\s*=\s*"?(\d{2,5})"?')
  if ($m.Success) { $port = [int]$m.Groups[1].Value }
  else {
    $m2 = [regex]::Match($t, '(?<![\d.])(\d{4,5})(?![\d.])')   # 줄 안의 첫 포트 번호
    if ($m2.Success) { $port = [int]$m2.Groups[1].Value }
  }
  if ($null -eq $port) { return $null }

  $mn = [regex]::Match($t, 'CDP_PROFILE\s*=\s*"?([^\s"#]+)"?')
  if ($mn.Success) { $name = $mn.Groups[1].Value }
  else {
    # 포트 뒤에 남은 토큰 중 화살표·구분자를 뺀 첫 낱말
    $rest = $t.Substring($t.IndexOf([string]$port) + ([string]$port).Length)
    $rest = $rest -replace '<->', ' ' -replace '[-=>|:]', ' '
    $tok = ($rest -split '\s+') | Where-Object { $_ -ne '' } | Select-Object -First 1
    if ($tok) { $name = $tok }
  }

  return [pscustomobject]@{ Port = $port; Name = $name }
}

function Get-Assignments {
  # 번들마다 두 출처를 읽어 합집합을 만든다.
  #   cdp\pairing.txt — 사람이 남긴 배정 기록
  #   tester.ps1      — $env:CDP_PORT (실제로 동작에 쓰이는 값. remote.js 가 이걸 읽는다)
  # 기록만 보면 사람이 tester.ps1 만 고친 경우를 놓쳐 이미 쓰는 포트를 다시 배정하게 된다.
  $out = @()
  if (-not (Test-Path -LiteralPath $Root)) { return $out }

  $dirs = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue
  foreach ($d in $dirs) {
    $bundle = $d.Name

    $pf = Join-Path $d.FullName 'cdp\pairing.txt'
    if (Test-Path -LiteralPath $pf) {
      foreach ($ln in (Read-TextLines $pf)) {
        $p = Parse-PairingLine $ln
        if ($p) {
          $out += [pscustomobject]@{
            Bundle = $bundle; Port = $p.Port
            Name   = $(if ($p.Name) { $p.Name } else { $bundle })
            Source = 'pairing.txt'
          }
        }
      }
    }

    $tp = Join-Path $d.FullName 'tester.ps1'
    if (Test-Path -LiteralPath $tp) {
      $txt = [System.IO.File]::ReadAllText($tp)
      $mp = [regex]::Match($txt, '(?m)^\s*\$env:CDP_PORT\s*=\s*"?(\d{2,5})"?')
      if ($mp.Success) {
        $nm = $bundle
        $mn = [regex]::Match($txt, '(?m)^\s*\$env:CDP_PROFILE\s*=\s*"([^"]*)"')
        if ($mn.Success -and $mn.Groups[1].Value -ne '') { $nm = $mn.Groups[1].Value }
        $out += [pscustomobject]@{
          Bundle = $bundle; Port = [int]$mp.Groups[1].Value
          Name   = $nm; Source = 'tester.ps1'
        }
      }
    }
  }
  return $out
}

function Get-Conflicts([object[]]$Assignments) {
  # 같은 포트를 서로 다른 번들이 쓰면 충돌이다. 한 번들 안에서 pairing.txt 와 tester.ps1 이
  # 같은 포트를 말하는 건 정상이므로 번들 이름으로 묶어 센다.
  $conf = @()
  $byPort = $Assignments | Group-Object -Property Port
  foreach ($g in $byPort) {
    $bundles = ($g.Group | Select-Object -ExpandProperty Bundle | Sort-Object -Unique)
    if ($bundles.Count -gt 1) {
      $conf += [pscustomobject]@{ Port = [int]$g.Name; Bundles = $bundles }
    }
  }
  return $conf
}

function Get-Drift([object[]]$Assignments) {
  # 한 번들 안에서 pairing.txt 와 tester.ps1 의 포트가 다르면 기록이 낡은 것이다.
  $drift = @()
  foreach ($g in ($Assignments | Group-Object -Property Bundle)) {
    $ports = ($g.Group | Select-Object -ExpandProperty Port | Sort-Object -Unique)
    if ($ports.Count -gt 1) {
      $detail = ($g.Group | ForEach-Object { "$($_.Source)=$($_.Port)" }) -join ', '
      $drift += [pscustomobject]@{ Bundle = $g.Name; Detail = $detail }
    }
  }
  return $drift
}

try {
  $asg = @(Get-Assignments)
}
catch {
  Write-Host "[pairing] 배정 읽기 실패 — $($_.Exception.Message)"
  exit 2
}

switch ($Action) {

  'list' {
    Write-Host "[pairing] 루트: $Root"
    if ($asg.Count -eq 0) { Write-Host "[pairing] 배정 없음(번들 0개 또는 CDP_PORT 미기재)"; exit 0 }
    foreach ($g in ($asg | Group-Object -Property Bundle | Sort-Object Name)) {
      $ports = ($g.Group | Select-Object -ExpandProperty Port | Sort-Object -Unique) -join '/'
      $src = (($g.Group | Select-Object -ExpandProperty Source | Sort-Object -Unique) -join '+')
      Write-Host ("  {0,-34} 포트 {1,-12} ({2})" -f $g.Name, $ports, $src)
    }
    exit 0
  }

  'check' {
    Write-Host "[pairing] 루트: $Root — 번들 $((@($asg | Group-Object Bundle)).Count) 개"
    $conf = @(Get-Conflicts $asg)
    $drift = @(Get-Drift $asg)

    foreach ($d in $drift) {
      Write-Host "[pairing][경고] $($d.Bundle): 기록과 실제가 다름 — $($d.Detail). 동작에 쓰이는 값은 tester.ps1 쪽이다(remote.js 가 읽는다). record 로 기록을 맞춘다."
    }
    if ($conf.Count -eq 0) {
      Write-Host "[pairing][OK] 포트 중복 없음"
      exit 0
    }
    foreach ($c in $conf) {
      Write-Host "[pairing][실패] 포트 $($c.Port) 를 여러 번들이 쓴다 — $($c.Bundles -join ', ')"
    }
    Write-Host '[pairing] 한 프로필은 동시에 못 뜨고 포트를 공유하면 로그인이 섞인다 — 한쪽을 -Action next 로 옮긴다.'
    exit 1
  }

  'next' {
    $used = @($asg | Select-Object -ExpandProperty Port)
    $p = $From
    while ($used -contains $p) { $p++ }
    # Write-Output — 숫자 하나만 낸다. 호출 쪽이 `$port = powershell.exe … -Action next` 로 받는다.
    Write-Output $p
    exit 0
  }

  'record' {
    if (-not $Bundle -or $Bundle -eq '') { Write-Host "[pairing] -Bundle 이 필요합니다 (<business>__<project>)"; exit 2 }
    if (-not $Port -or $Port -le 0) { Write-Host "[pairing] -Port 가 필요합니다"; exit 2 }

    # 다른 번들이 이미 쓰는 포트면 기록하지 않는다 — 겹침을 막는 게 이 스크립트의 목적이다.
    $taken = @($asg | Where-Object { $_.Port -eq $Port -and $_.Bundle -ne $Bundle })
    if ($taken.Count -gt 0) {
      $who = ($taken | Select-Object -ExpandProperty Bundle | Sort-Object -Unique) -join ', '
      Write-Host "[pairing][실패] 포트 $Port 는 이미 $who 가 쓴다 — -Action next 로 빈 포트를 받으세요"
      exit 1
    }

    $dir = Join-Path (Join-Path $Root $Bundle) 'cdp'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $file = Join-Path $dir 'pairing.txt'

    $line = "CDP_PORT=$Port CDP_PROFILE=$Bundle  # 이 번들 전용 1:1 배정 — 다른 config 와 공유 금지"
    # BOM 없는 UTF-8 로 쓴다. Windows PowerShell 5.1 의 `Out-File -Encoding utf8` 은 BOM 을
    # 붙이고 `-Encoding utf8NoBOM` 은 6+ 전용이라, 5.1 을 포함해 안전한 건 이 방법뿐이다.
    # [IO.File] 은 PowerShell 의 현재 위치가 아니라 .NET 작업 디렉토리를 쓰므로 절대경로를 넘긴다.
    $abs = [System.IO.Path]::GetFullPath($file)
    [System.IO.File]::WriteAllText($abs, $line + "`r`n", (New-Object System.Text.UTF8Encoding($false)))

    Write-Host "[pairing][OK] $abs"
    Write-Host "  $line"
    Write-Host "  tester.ps1 의 `$env:CDP_PORT 도 $Port 로 맞추세요(동작에 쓰이는 값은 그쪽입니다)."
    exit 0
  }
}
