---
name: unskein-test
description: 다오가 개발한 화면을 모리(TESTER)가 CDP로 떠 있는 Chrome에 붙어 실제로 검증한다 — 콘솔 에러·네트워크 실패 수집 + 실제 렌더 확인 + 화면 캡처. 수동 진단과, UnSkein 큐에서 test 작업을 스스로 선점→검증→보고하는 자율 TESTER 루프 둘 다 제공한다. 트리거 — UI 테스트, 화면 검증, 브라우저 테스트, 스크린샷, CDP, 9222, 콘솔 에러 수집, 네트워크 실패 확인, 화면 캡처, 셀렉터 확인, 런타임 검증, TESTER, 테스터 루프, test 작업 선점, 큐 화면검증, claim.
---

# UnSkein — 화면 런타임 검증 (모리)

다오가 코드로 만든 화면을, 모리가 실제 Chrome에서 띄워 동작을 확인합니다. Chrome DevTools Protocol(CDP)로 떠 있는 Chrome에 붙어 콘솔 에러·네트워크 실패를 수집하고, 실제 렌더 상태와 셀렉터를 확인하고, 화면을 캡처합니다.

코드 검증(`unskein-verify`: 타입체크·빌드·테스트)과 보완 관계입니다. 글로벌 헌장의 "헤드리스 다오 → 윈도우 모리 UI 검증" 핸드오프에 해당합니다 — 다오는 WSL 헤드리스라 브라우저 화면을 띄울 수 없으므로, 실제 화면 검증은 윈도우의 모리가 맡습니다. UI 테스트는 모리 담당입니다.

스크립트 경로는 모두 플러그인 기준입니다: `${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/...`.

이 스킬은 두 가지로 씁니다: **수동 진단**(§1–§7 — 사람이 화면 하나를 직접 확인)과 **자율 TESTER 루프**(§0 — 큐에서 `test` 작업을 스스로 선점→검증→보고). 큐에 연결해 돌리려면 §0 을 먼저 읽으세요.

## 0. 자율 검증 루프 — TESTER 배선

UnSkein 큐의 `test` 단계를 TESTER 가 스스로 처리합니다. 파이프라인: `plan(구현+자체검증, EXECUTOR)` → **`test`(화면검증, TESTER)** → `inspect(마감, EXECUTOR)` → `done`.

### 0.1 역할·인증

- TESTER 는 **윈도우 Claude Code 세션**입니다(다오=WSL 코드검증, 테스터=윈도우 화면검증 — 프로세스 경계로 "구현≠검증"을 실현). CDP Chrome(기본 9222)은 윈도우 프로세스라 WSL 에서 못 붙습니다. 테스터 세션 여러 개를 병렬로 돌리려면 세션마다 다른 포트로(§3 포트↔프로필 1:1 — 인증 완전 분리).
- **테스터 토큰**(kind=tester): 웹에서 발급(`POST /me/mori-tokens {kind:"tester"}`). EXECUTOR(kind=mori) 토큰과 달리 큐에서 **`test` 작업만** 집습니다(서버 스테이지 게이트). 값은 환경변수로만 둡니다(비밀 무잔존, 화면 출력 금지):
  - `UNSKEIN_API_BASE`(예: `https://unskein.mupai.studio`), `UNSKEIN_MORI_TOKEN`(테스터 토큰).
- **여러 사이트**: 한 TESTER 가 자기 멤버십의 모든 사이트를 담당합니다. 특정 사이트만 보려면 `claim --business=<이름> --project=<이름>` 로 좁힙니다(watch 스코프). `node queue.js scope` 로 담당 가능 사이트를 확인합니다.

### 0.2 한 tick — claim → 검증 → report

`queue.js`(서버 왕복) + `start.ps1`/`remote.js`(CDP)로 한 작업을 처리합니다:

1. **선점**: `node ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/queue.js claim` → `{claimed, task}`. `claimed:false` 면 조용히 종료(대기 작업 없음). task 에는 검증 대상 **`tested_url`**, 수용 기준(`title`/`description`/`plan_doc`), `subtree`(하위 작업)가 실려 옵니다.
2. **lease 유지**: 검증이 길면 주기적으로 `node queue.js heartbeat <id>`(서버 stale 기준 180s — 60s 안팎으로 갱신).
3. **화면 기동·검증**: `start.ps1 -Url <tested_url>` → `remote.js navigate/collect/attrs/shot`(§4) 로 수용 기준의 시나리오를 수행. 콘솔 에러·네트워크 실패·렌더·셀렉터를 수집하고 화면을 캡처합니다. **병렬 TESTER 는 자기 포트로**: `start.ps1 -Port <n> -Url ...` + `$env:CDP_PORT=<n>`(또는 명령마다 `--port=<n>`) — 포트 없이 돌리면 두 루프가 같은 9222 크롬(같은 로그인)에 붙어 인증이 섞입니다(§3 페어링).
4. **산출물 저장(매뉴얼 재사용)**: 이번 검증에 쓴 **시나리오 스크립트**(remote.js 명령 순서)와 스크린샷을 작업별 폴더(`scripts/cases/<task_id>/`)에 남깁니다 — 사용자 매뉴얼 작성 시 그대로 재사용합니다. 경로를 payload 에 싣습니다.
5. **판정·보고**:
   - **PASS** → `node queue.js report <id> --status=inspect --summary="..." --doc=<리포트.md> --payload=<payload.json>`. (다음 단계 inspect=마감은 별도 담당.)
   - **FAIL** → `--status=plan`(화면검증 FAIL 롤백 — 구현자 EXECUTOR 가 다시 집습니다). 실패 근거를 payload.findings 에 담습니다.
6. **판단 필요(사양이냐 버그냐)** → `node queue.js question <id> --text="..."` 로 사람에게 묻고(waiting) tick 을 종료합니다. 운영자가 웹에서 답하면 다음 claim 때 그 답이 실려 재개됩니다.

### 0.3 결과 슬롯 — `payload['test']`

report 의 `--payload` 는 아래 구조(JSON)로, 서버가 `task.payload['test']` 에 저장합니다. 웹 칸반·매뉴얼 작성이 이걸 읽습니다:

```jsonc
{
  "verdict": "PASS | FAIL | BLOCKED",
  "tested_url": "https://.../board",          // 실제로 연 주소
  "build_sha": "97b43af2",                     // /api/version 등에서 확인한 대상 빌드(있으면)
  "scenarios": [{ "id": "S-1", "name": "...", "result": "PASS", "note": "" }],
  "findings":  [{ "severity": "P0|P1|P2|P3", "summary": "...", "evidence": "cases/<id>/shots/01.png" }],
  "console_errors": [], "network_failures": [],
  "screenshots": ["cases/<id>/shots/01.png"],
  "scripts":     ["cases/<id>/scripts/scenario.md"],   // 검증에 쓴 스크립트(매뉴얼 재사용)
  "report_path": "cases/<id>/report.md"
}
```

스크린샷·스크립트는 **경로만** payload/DB 에 두고, 실제 파일은 저장소(프로젝트 repo 의 test-cases 등)에 커밋해 매뉴얼 작성 시 찾게 합니다.

### 0.4 연속 운용 (CronCreate)

한 tick 은 1건만 처리합니다. 연속 감시는 클로드 세션이 폴링하거나 CronCreate 로 주기 재구동합니다(예: `*/5`). 매 tick 은 claim → (있으면) 검증·보고 → 종료. 중복 선점은 서버 SKIP LOCKED·heartbeat 로 막히니 여러 TESTER 를 동시에 돌려도 **큐 측은** 안전합니다 — 단 **CDP 측은 세션별 포트 분리가 전제**(§0.2 3단계·§3 페어링): 포트를 안 나누면 같은 크롬·같은 로그인에 붙습니다.

## 1. 무엇을 / 언제

- 다오가 만든 화면의 런타임 검증: 콘솔 에러, 네트워크 실패(요청 실패·HTTP 4xx/5xx), 실제 렌더 결과 확인.
- 단발 진단: 특정 화면을 한 번 열어 콘솔·네트워크 상태를 수집.
- 캡처: 기대 화면과 비교할 스크린샷 확보.
- 셀렉터 확인: 버튼·입력 같은 요소가 실제로 존재하고 보이는지(`attrs`) 확인.

`unskein-verify`가 코드 수준에서 PASS를 낸 뒤, 화면이 실제로 사용자에게 보이는지 확정하려 할 때 사용합니다.

## 2. 설치

CDP 모드는 별도 브라우저 바이너리를 받지 않습니다. 시스템에 이미 설치된 Chrome에 붙기 때문입니다.

- **시스템 Chrome**: `start.ps1`이 표준 경로를 자동으로 찾습니다 (`C:\Program Files\Google\Chrome\Application\chrome.exe`, 없으면 `C:\Program Files (x86)\...`). 둘 다 없으면 오류로 멈춥니다.
- **Node**: 윈도우 Node 가 있어야 합니다 (`remote.js` 구동용).
- **Playwright(npm)**: 스킬 폴더(또는 그 상위)에서 `npm i -D playwright` 한 번. `remote.js`가 `node_modules`를 상위로 거슬러 올라가며 찾습니다.

### `npx playwright install` 미사용

`remote.js`는 `chromium.connectOverCDP('http://127.0.0.1:<포트>')`(기본 9222, `--port`/`CDP_PORT` 로 변경)로 이미 떠 있는 시스템 Chrome에 접속합니다. Playwright가 자기 브라우저를 띄우는 방식이 아니라 외부 Chrome을 원격 조작하는 방식이므로, Playwright 번들 브라우저(수백 MB)가 필요 없습니다. 따라서 `npx playwright install` 은 실행하지 않습니다 — npm 패키지(`playwright`)만 있으면 됩니다.

## 3. 실행 환경

- **OS**: 윈도우. `.ps1`은 PowerShell, `remote.js`는 윈도우 Node 로 구동합니다.
- **전용 프로필**: 기본 `%USERPROFILE%\.cdp-chrome`. 평소 쓰는 Chrome 프로필과 분리되어, 일반 Chrome 을 켜 둔 채로 검증용 Chrome 을 따로 띄울 수 있습니다. 이름 있는 프로필은 `%USERPROFILE%\.cdp-chrome-<name>` (`-Profile <name>`).
- **포트 = 세션**: 포트마다 CDP Chrome 하나 — **포트가 다르면 병렬로 띄웁니다**(기본 9222). 같은 포트에서 프로필을 바꾸려면 그 세션만 `stop.ps1 -Port <n>` 먼저, 그다음 `start.ps1 -Port <n> -Profile <name>`.
- **포트↔프로필 1:1 (인증 격리)**: **인증(쿠키·localStorage·JWT)의 경계는 탭이 아니라 프로필**입니다 — 같은 브라우저의 탭들은 로그인을 공유하고, 프로필이 다른 크롬 인스턴스는 완전히 독립입니다. `start.ps1` 이 포트와 프로필을 1:1 로 묶습니다:

  | 기동 | 프로필 | 용도 |
  |------|--------|------|
  | `start.ps1` (기본 9222) | `.cdp-chrome` | 단일 세션(종전과 동일 — 기존 로그인 보존) |
  | `start.ps1 -Port 9223` | `.cdp-chrome-9223` | 병렬 세션 — 9222 와 로그인 완전 분리 |
  | `start.ps1 -Port <n> -Profile <name>` | `.cdp-chrome-<name>` | 이름 있는 프로필(예: 역할 계정 `admin`/`member`/`viewer` 병렬 검증) |

  페어링 충돌은 조용히 넘어가지 않고 거부합니다: **같은 프로필·다른 포트**(크롬이 기존 인스턴스에 위임해 새 포트가 영영 안 뜨는 함정)도, **같은 포트·다른 프로필**(로그인 섞임)도 명확한 에러로 차단. `-Force` 는 **이 페어링의 강제 확보** — 그 포트·그 프로필을 점유한 크롬만 종료하고 새로 띄웁니다(무관한 세션·일반 Chrome 불가침).

## 4. 사용 절차

### 4.1 기동 — `start.ps1`

```shell
powershell -ExecutionPolicy Bypass -File ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/start.ps1
```

| 옵션 | 동작 |
|------|------|
| (없음) | 그 포트가 이미 떠 있으면 — **같은 프로필일 때만** 재사용하고(`-Url` 무시), **다른 프로필이 점유 중이면 거부**합니다(로그인 섞임 방지). 안 떠 있으면 새로 띄웁니다. |
| `-Port <n>` | 그 포트로 띄웁니다(기본 9222). **포트가 다르면 병렬 세션** — 프로필이 자동으로 `.cdp-chrome-<n>` 로 갈려 인증이 완전 분리됩니다(§3 표). |
| `-Force` | **이 페어링(그 포트·그 프로필)을 강제 확보** — 그 포트를 점유한 크롬과 그 프로필을 점유한 크롬(다른 포트에 떠 있어도)을 종료하고 새로 띄웁니다. 무관한 세션(다른 포트+다른 프로필)·일반 Chrome 은 건드리지 않습니다. |
| `-Profile <name>` | `.cdp-chrome-<name>` 프로필로 띄웁니다. 프로필 분리용(포트 페어링보다 우선). |
| `-Url <url>` | 첫 탭으로 그 주소를 엽니다(기본 `about:blank`). 예: `-Url http://localhost:5173`. |

DevTools 엔드포인트가 준비될 때까지 최대 60초 기다립니다(첫 실행은 프로필 생성으로 느릴 수 있습니다). 준비되면 `READY` 와 엔드포인트(`http://127.0.0.1:<포트>`)를 출력합니다.

### 4.2 조작 — `remote.js`

```shell
node ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/remote.js <command> [...]
```

| 명령 | 용도 |
|------|------|
| `tabs` | 열린 탭 목록(인덱스·URL·제목). 탭 선택 전에 확인. |
| `navigate <url> [--new]` | 화면 진입. `--new` 면 새 탭, 아니면 선택한 탭에서 이동. |
| `click <selector>` | 요소 클릭. |
| `type <selector> <text>` | 입력. React 컨트롤드 입력에서도 동작하도록 native setter + `input`/`change` 이벤트를 씁니다. |
| `eval "<js>"` | 페이지 안에서 JS 식 평가, 결과를 JSON 출력. |
| `wait <selector> [--ms=10000]` | 요소가 나타날 때까지 대기. |
| `attrs <selector>` | 매칭 요소들의 DOM 속성(tag·id·class·text·visible·disabled·href 등) 검사. 셀렉터 존재·표시 확인용. |
| `collect [<ms>]` | 콘솔 에러·경고, 페이지 에러, 네트워크 실패(요청 실패·HTTP 4xx/5xx)를 수집해 JSON 출력. 기본 5000ms. |
| `shot <name> [--full]` | 스크린샷을 `scripts/shots/<name>.png` 에 저장. `--full` 은 전체 페이지. |
| `close [--tab=<sel>]` | 탭 닫기. `--tab` 생략 시 가장 최근 탭을 닫습니다. |

**탭 선택 `--tab=<sel>`** (모든 명령 공통, 생략 시 가장 최근 탭):

- `--tab=<인덱스>` — `tabs` 에서 본 번호.
- `--tab=<URL부분>` — URL 부분 문자열 매칭.

**포트 선택** (모든 명령 공통 — 병렬 세션에서 어느 크롬에 붙을지):

- `--port=<n>` — 이 호출만 그 포트로.
- `CDP_PORT=<n>` 환경변수 — 세션 단위 고정(플래그가 우선). 병렬 검증 세션은 자기 포트를 `CDP_PORT` 로 박아두면 명령마다 `--port` 를 안 붙여도 됩니다.
- 생략 — 9222.

**`collect` 권장 수집 시간**:

- `3000` — 정적 화면 빠른 확인.
- `5000` — 일반 페이지(기본값).
- `10000` — 자동 갱신·비동기 요청이 많은 화면.

### 4.3 종료 — `stop.ps1`

```shell
powershell -ExecutionPolicy Bypass -File ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/stop.ps1
```

| 옵션 | 동작 |
|------|------|
| (없음) | 모든 CDP Chrome 을 종료합니다(`.cdp-chrome*` 프로필 매칭 — 전 포트). 일반 Chrome 은 보호합니다. |
| `-Port <n>` | **그 세션만** 종료합니다(그 포트 + 짝 프로필). 다른 포트의 병렬 세션은 안 건드립니다. |
| `-Profile <name>` | `.cdp-chrome-<name>` 세션만 종료합니다. |
| `-All` | 시스템의 모든 `chrome.exe` 를 종료합니다. **사용자가 명시적으로 요청했을 때만** 씁니다. |

## 5. 검증 흐름 예

1. `start.ps1 -Url http://localhost:5173` 로 검증 대상 화면을 첫 탭에 띄웁니다.
2. `remote.js navigate <url>` 로 검증할 화면에 진입합니다(또는 1번에서 바로 진입한 탭 사용).
3. `remote.js collect 5000` 으로 콘솔 에러·네트워크 실패를 수집합니다.
4. `remote.js shot <이름>` 으로 화면을 캡처합니다. 필요하면 `attrs` 로 핵심 요소 표시 여부를 확인합니다.
5. 수집 결과(`summary.errors`·`summary.netFails`)와 캡처를 기대값과 비교해 pass / fail 을 판정합니다.
6. `stop.ps1` 로 CDP Chrome 을 정리합니다.

### 5.1 병렬 세션 예 — 역할 계정 동시 검증 (admin·member·viewer)

인증 경계 = 프로필이므로, **역할마다 포트+프로필을 갈라** 로그인 상태가 절대 안 섞이는 병렬 검증이 됩니다:

```shell
# 세션 A (admin)                                  # 세션 B (member)
start.ps1 -Port 9222 -Profile admin               start.ps1 -Port 9223 -Profile member
$env:CDP_PORT="9222"                              $env:CDP_PORT="9223"
#  (PowerShell. cmd 는 set CDP_PORT=9222 / 또는 명령마다 --port=<n>)
remote.js navigate <url> → 로그인(admin)           remote.js navigate <url> → 로그인(member)
remote.js collect / shot ...                      remote.js collect / shot ...
stop.ps1 -Port 9222                               stop.ps1 -Port 9223
```

- 각 세션의 JWT·쿠키는 자기 프로필(`.cdp-chrome-admin` / `.cdp-chrome-member`)에만 존재 — 탭 공유 오염 없음.
- `stop.ps1 -Port <n>` 로 자기 세션만 정리 — 상대 세션의 크롬은 계속 돕니다.
- 같은 프로필을 두 포트로 띄우는 실수는 `start.ps1` 이 거부합니다(크롬 위임 함정).

## 6. 주의 — 실환경 검증 필요

**모리 운영 세션이 WSL 안에서 돌고 있으면, 위 명령을 그대로 WSL 셸에서 실행하면 안 됩니다.** `.ps1` 은 `powershell.exe` 로, `remote.js` 는 윈도우 Node 로 호출해야 `127.0.0.1:<포트>` 가 윈도우 로컬을 가리킵니다. WSL 안의 Node 로 실행하면 `127.0.0.1` 이 WSL 루프백이 되어 윈도우의 CDP Chrome 에 닿지 못합니다.

- `.ps1`: `powershell.exe -ExecutionPolicy Bypass -File <윈도우 경로>` 로 호출합니다.
- `remote.js`: 윈도우 Node(예: `node.exe`)로, 스크립트도 윈도우에서 접근 가능한 경로로 호출합니다.

이 동작은 윈도우 실환경에서 별도 확인이 필요합니다(클라이언트가 윈도우). WSL 자체 확인만으로는 CDP 포트 도달을 보장하지 못합니다.

## 7. 비밀·값 누락 처리

- 토큰·키 값은 화면에 출력하지 않습니다(설정됨 / 없음만 표시).
- 검증에 필요한 값(대상 URL·계정 등)이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다. 다른 값으로 우회하지 않습니다(fallback 금지).
