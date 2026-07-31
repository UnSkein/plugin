---
name: unskein-doctor
description: 모리 클라이언트가 작업을 못 돌릴 때 무엇이 깨졌는지 진단하고 복구를 안내한다 — 증상→원인 후보→복구 액션→재검증. /unskein:status 스냅샷을 출발점으로 증상에 맞는 갈래를 따라 원인을 좁힌다. 트리거 — 진단, 복구, 안 됨, 실패, doctor, 문제 해결, 토큰 인증 실패, 401, claude 못 찾음, clone 실패, push 실패, 작업 실행 실패, 화면 검증 안 됨, CDP 안 붙음, 9222 연결 실패, 스킬 충돌, CLAUDE.md 충돌, 전역 스킬 겹침, 기존 설치 충돌, gh 인증 실패, gh 없음, PR 생성 안 됨, 작업을 하나도 못 잡음, preflight 차단, 케이스가 안 쌓임, 케이스 동기 실패, 케이스 push 안 됨, UNSKEIN_BUSINESS_ID, 증거 업로드 실패, 첨부 없음, 캡처가 안 올라감, 413, 409.
---

# UnSkein — 진단·복구 (doctor)

모리 클라이언트가 작업을 못 돌릴 때, 무엇이 깨졌는지 짚어내고 복구를 안내합니다. `/unskein:status` 는 작업을 선점·변경하지 않고 현재 상태를 보여주는 스냅샷이고(모리 `preflight()` 를 구동하므로 gh·네트워크 점검에 ~20s 걸릴 수 있습니다), 이 스킬은 그 스냅샷을 출발점으로 증상에 맞는 갈래를 따라가 원인을 좁히고 복구 액션까지 연결합니다. 클라이언트 주인(사용자)과 대화하며 진행합니다.

원칙:

- 비밀(토큰·SSH 키) 값은 화면에 출력하지 않습니다 — `설정됨`/`없음` 같은 존재 여부만 다룹니다.
- 못 고치면 임시 우회를 만들지 않습니다. 사유를 사용자에게 그대로 보고하고 멈춥니다(fallback 금지).
- 복구 후에는 재검증 단계까지 진행합니다.
- 진단·복구 보고는 plugin `docs/보고규칙.md` 를 따릅니다 — 증상(현상)을 먼저, 원인·복구는 뒤에, 평범한 한국어로.

## 0. 역할 판별 (먼저 — 오진 방지)

doctor 의 `preflight()` 는 **EXECUTOR(모리 실행기)** 가 작업을 잡기 위한 준비 점검입니다. 그래서 이 머신의 역할을 먼저 가릅니다 — 잘못 읽으면 executor-전용 항목을 "고장"으로 오진합니다.

- **EXECUTOR(모리 실행기)** — `/unskein:run`·`/unskein:watch` 로 작업을 claim 해 다오를 돌리는 클라이언트. preflight 전 항목이 유효합니다.
- **PLANNER(운영자/등록)** — 코드베이스를 보고 스코프·WBS 를 서버 큐에 등록하는 세션(개발·claim 안 함). **executor-전용 항목은 해당 없음**입니다.
- 한 머신이 **둘 다** 겸할 수 있습니다.

**executor-전용 항목 — PLANNER 전용 머신에선 `없음`/`[실패]` 여도 정상(고장 아님):**
- `UNSKEIN_MORI_TOKEN` — claim 인증용(X-Mori-Token). PLANNER 는 대신 PLANNER 토큰(kind=planner) 또는 admin 로그인을 씁니다.
- `자격증명 폴더(creds)` — 다오가 고객 repo 를 clone/push 할 때만.
- (dao-skills 원본·work 루트도 executor 실행용 — executor 겸할 때만 갖추면 됩니다.)

**두 역할 공통 — 어느 쪽이든 `[실패]` 면 진짜 문제:** `claude`·`git`·`gh` 인증·큐 서버 도달·플러그인 최신.

역할이 모호하면 임의 판단하지 말고 사용자에게 묻습니다. **PLANNER 전용**이면 아래 §1 스냅샷에서 executor-전용 `[실패]` 는 "해당 없음(정상)" 으로 읽고, 공통 항목만 갈래(§2)로 좁힙니다.

> PLANNER 준비 확인은 별도입니다 — `UNSKEIN_PLANNER_TOKEN` + `UNSKEIN_API` 가 **프로젝트별 격리된 `planner.env`** 에서 로드돼(`. "${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh"` — source 우선·cwd 폴백, ADR-0021) 등록 API(businesses·projects·tasks·plan)에 닿으면 됩니다. 어느 파일에서 로드됐는지는 `UNSKEIN_PLANNER_ENV_FILE` 로 확인합니다(여러 프로젝트를 다룰 때 **엉뚱한 프로젝트의 planner.env 를 주웠는지** — cwd 폴백이 조상 `.unskein` 을 잡는 함정). 토큰이 안 잡히면 멈추고 알립니다(fallback 금지). 폴백: 사람이 웹 로그인 세션이면 admin 로그인 Bearer 도 인가. `unskein-scope` 가 코드베이스를 자동 clone/pull 하려면 `planner.env` 에 `UNSKEIN_BUSINESS`·`UNSKEIN_PROJECT`(repo_url 조회) + `UNSKEIN_SSH_KEY`(git 키)도 필요합니다(ADR-0022) — clone/pull 실패는 스킬이 그대로 멈추고 보고합니다(fallback 금지). `플래너설치.md` §0·§4 · ADR-0013 · ADR-0021 · ADR-0022.

## 1. 스냅샷 확보

먼저 현재 상태를 읽어 증상을 확인합니다:

```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/status.py"
```

출력은 두 부분입니다 — **설정 항목**과, 모리 `preflight()` 를 그대로 구동한 **준비 점검**(작업을 잡기 전 게이트와 동일한 점검). 같은 단일 출처라 스냅샷과 실제 게이트가 어긋나지 않습니다.

- 설정: `UNSKEIN_API`, `UNSKEIN_MORI_TOKEN`(`설정됨`/`없음`), watch 대상, 가용 scope.
- 준비 점검(preflight): 다오 CLI(`claude`)·`git`·`gh` 인증·dao-skills 원본·creds 폴더·work 루트·큐 서버 도달·플러그인 최신. 각 줄이 `[OK]`/`[실패]`/`[경고]` 로 나옵니다 — **`[실패]` 줄이 곧 모리(EXECUTOR)가 작업을 못 잡는 사유입니다.** 단 §0 을 먼저 적용해, **PLANNER 전용 머신이면 executor-전용 항목(`UNSKEIN_MORI_TOKEN`·`creds`)의 `[실패]`/`없음`은 고장이 아니라 "해당 없음(정상)"** 으로 읽습니다.

`creds` 에 어떤 자격증명 파일이 있는지는 3번에서 `ls` 로, `work` 루트의 소유자·권한은 4번에서 `ls -ld` 로 확인합니다(스냅샷 줄엔 존재·OK 여부만 나옵니다).

사용자에게 실제 증상도 함께 묻습니다(예: "한 바퀴 실행했는데 어디서 멈췄나요?", 화면에 나온 에러 메시지 한 줄). 스냅샷의 `없음`/`실패` 항목과 사용자 증상을 맞춰 아래 갈래로 들어갑니다.

## 2. 증상 → 원인 후보 → 복구 갈래

| # | 증상(어디서 멈추나) | 원인 후보 | 복구 액션 |
|---|------|------|------|
| 1 | `claude` 또는 `git` 을 못 찾음 | WSL에 실행 파일 부재 | `unskein-setup` S1로 설치 안내 |
| 2 | claim 단계에서 멈춤(`HTTP 401`) / 토큰 인증 실패 | `UNSKEIN_API`·`UNSKEIN_MORI_TOKEN` 미설정 또는 무효 | `unskein-setup` 로 연결 정보 재설정 |
| 3 | claim은 되는데 clone·push 에서 실패 | git 자격증명(HTTPS 토큰/SSH 키) 누락·만료 | `unskein-setup` 로 자격증명 재배치·교체 |
| 4 | 작업 루트 생성/쓰기 실패(preflight `작업 루트(work)` `[실패]`) | `UNSKEIN_WORK_ROOT` 쓰기 권한 부족 (부재는 preflight 가 자동 생성) | 권한 보정 |
| 5 | "다오 스킬 원본을 찾을 수 없습니다" 로 회수됨 | dao-skills 원본 누락(plugin 설치·갱신 문제) | `/plugin` 재설치 |
| 6 | `claude -p` 가 timeout / is_error / JSON 파싱 실패로 회수됨 | 실행 시간 초과 / claude 내부 오류 / 출력 비정상 | 아래 6번에서 원인 분기 후 확인 |
| 7 | 서버 도달 실패(`GET /api/health`) | 네트워크·주소 문제 | 주소·네트워크 확인 |
| 8 | 화면 검증(CDP)이 Chrome(기본 9222)에 안 붙음 | WSL Node 로 실행해 `127.0.0.1` 이 WSL 루프백을 가리킴 / 포트 불일치(병렬 세션 — `--port`/`CDP_PORT` 확인) / Chrome 미기동 | 윈도우 Node·PowerShell 로 실행 + 포트 대조 (`unskein-test` 6장) |
| 9 | 모리·다오가 규약과 다르게 동작(출력 형식 어김, 엉뚱한 지침·스킬을 따름) | 기존 전역 스킬·`CLAUDE.md`·플러그인이 unskein 과 충돌 | 아래 9번에서 충돌 점검 |
| 10 | 작업을 하나도 못 잡고 preflight 가 `[실패] gh CLI 인증(PR 생성)` 으로 종료(claim 안 함) | gh 미설치·미인증·토큰 무효 | 아래 10번 — `unskein-setup` S1 로 `gh auth login` + `gh auth setup-git` |
| 11 | 화면검증은 도는데 **케이스가 안 쌓인다**(케이스 목록이 며칠째 그대로) | `UNSKEIN_BUSINESS_ID` 미설정 또는 이름을 넣음 / 케이스 동기 명령 미실행 / 토큰·서버 문제 | 아래 11번 — 비즈니스 **번호**를 넣고 재push |
| 12 | 검증 결과에 **첨부(캡처·raw)가 없다**, 리포트에 "증거 업로드 미실행(사유)" | 업로드 명령 미실행 / 한도·이름 규칙 위반(413·409·422) / 캡처를 케이스 폴더로 안 옮김 | 아래 12번 |

각 갈래의 진단·복구 절차는 아래와 같습니다.

### 1. claude/git 부재

진단:

```shell
command -v claude; command -v git
```

둘 중 하나라도 비면 그 실행 파일이 없는 것입니다. 다오(`claude -p`)는 WSL 안에서 구동하므로 WSL 안에 있어야 합니다.

복구: `unskein-setup` S1(실행 환경 확인)로 설치를 안내합니다. 설치 후 위 명령으로 다시 확인합니다.

### 2. 연결 정보 미설정/무효 (claim 401)

진단: 스냅샷의 `UNSKEIN_MORI_TOKEN` 이 `없음` 이면 미설정입니다. `설정됨` 인데도 `/unskein:run` 이 `[http error] 401` 로 멈추면 토큰이 무효(잘못된 값/만료/해지)입니다. claim 은 토큰을 헤더로 보내 인증하므로, 무효 토큰은 401 로 표시됩니다.

복구: `unskein-setup` S1로 `UNSKEIN_API`·`UNSKEIN_MORI_TOKEN` 을 다시 설정합니다. 토큰은 UnSkein 설정 화면에서 다시 발급합니다. 토큰 값은 화면에 출력하지 않습니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

### 3. git 자격증명 누락·만료 (clone/push 실패)

진단: claim 은 성공하는데(작업을 선점하는데) 다오의 clone·push 단계에서 실패하면 git 자격증명 문제입니다. 저장소 주소 형식으로 필요한 자격증명이 갈립니다:

- `https://` 저장소 → 토큰. `creds/.env` 의 `UNSKEIN_GIT_TOKEN=`(또는 호스트별 `UNSKEIN_GIT_TOKEN_<HOST>=`). 토큰이 없거나 만료되면 clone/push 가 인증 실패합니다.
- `git@`/`ssh://` 저장소 → SSH 개인키. `creds/id_ed25519`(또는 `id_rsa`), 권한 `600`.

스냅샷 preflight 의 `자격증명 폴더(creds)` 줄로 폴더 존재를 보고, 어떤 파일이 있는지는 `ls "${UNSKEIN_CRED_DIR:-${UNSKEIN_HOME:-$HOME/.unskein}/creds}"` 로 봅니다(`.env`/`id_ed25519`/`id_rsa` — 프로젝트 격리 시 `UNSKEIN_HOME` 밑, ADR-0020). 어떤 자격증명이 필요한지는 그 프로젝트의 저장소 주소로 정합니다.

프로젝트 격리(`UNSKEIN_HOME`) 배치에서 preflight 의 `상태 루트 정합(UNSKEIN_HOME)` 줄이 `[실패]` 면 **상태 분산**입니다 — 전역 셸에 남은 개별 변수(`UNSKEIN_CRED_DIR`/`UNSKEIN_WORK_ROOT`, 보통 bashrc 의 전역 env 자동 로드 잔재)가 creds/work 를 프로젝트 홈 밖으로 끌고 간 것. 복구는 그 변수(또는 bashrc 자동 로드 줄)를 제거하고 프로젝트 env 만 다시 `source` 합니다. 같은 잔재 중 SSH 키 경로(`UNSKEIN_SSH_KEY`/`UNSKEIN_SSH_KNOWN_HOSTS`)는 `SSH 자격 경로` 줄에 `[경고]` 로 뜹니다 — 의도한 외부 키(`~/.ssh` 등)가 아니면 같은 방법으로 정리합니다(방치하면 다른 프로젝트의 SSH 신원으로 조용히 clone/push 하는 누출).

프로젝트 격리 배치에서 preflight 의 `[경로] 전역 ~/.unskein 도 존재` 줄은 — 활성 홈과 다른 전역 `~/.unskein` 이 이 머신에 있다는 **상황 안내**입니다(경고 아님, 차단도 아님). 이 전역은 **다른 역할(TESTER 등)·기존 설치의 상태 홈**입니다. 명시 `source`(또는 `UNSKEIN_HOME` 지정)로 붙었으면 cwd 폴백이 꺼져 전역은 이 세션에 관여하지 않습니다. 조치: 이 머신에서 그 역할(예: TESTER)을 운영하지 않으면 전역은 불필요한 잔재이니 **정리해도 됩니다**(`mv ~/.unskein ~/.unskein_back` — 개명이라 되돌리기 가능); 운영 중이면 그대로 둡니다. **격리 자체는 전역 삭제가 아니라 명시 source·`UNSKEIN_HOME` 로 합니다** — 지우지 않아도 명시 source 면 안전합니다. 정작 확인할 것은 **어느 파일에서 상태가 왔는지**입니다 — `[경로] env 파일(cwd 폴백 로드)`(실행기)·`UNSKEIN_PLANNER_ENV_FILE`(플래너) 줄로 봅니다. 그 줄이 떴다면 `source` 를 안 해 cwd 폴백으로 로드된 것이니, 의도한 프로젝트가 맞는지 확인하고 아니면 그 프로젝트 env 를 명시 `source` 합니다. 여러 실행기/플래너 중 하나가 엉뚱하게 붙으면 대개 **셸에 이전 프로젝트 토큰이 남아 있어**(source 우선이 그걸 이김) 그런 것이니 — **새 터미널**에서 다시 시작합니다.

복구: `unskein-setup` 의 자격증명 갱신 단계로 자격증명을 재배치하거나 교체합니다(토큰 재발급, 키 교체). 토큰·키 값은 화면에 출력하지 않고, 저장소 주소나 git 설정에 토큰을 넣지 않습니다. 토큰을 교체한 경우 옛 토큰을 발급처에서 폐기하도록 안내합니다.

### 4. 작업 폴더 없음/권한

진단: 스냅샷 preflight 의 `작업 루트(work)` 줄이 `[실패]` 면 작업 폴더 문제입니다(preflight 가 `exist_ok` 로 생성을 시도하므로, 실패는 보통 권한 문제입니다). 작업 루트의 소유자·권한을 직접 봅니다:

```shell
ls -ld "${UNSKEIN_WORK_ROOT:-${UNSKEIN_HOME:-$HOME/.unskein}/work}"
```

복구: 폴더를 만들고 권한을 보정합니다.

```shell
mkdir -p "${UNSKEIN_WORK_ROOT:-${UNSKEIN_HOME:-$HOME/.unskein}/work}"
```

권한 오류가 남으면 폴더 소유자·권한을 사용자에게 보여주고 어떻게 보정할지 함께 정합니다. 임의로 광범위한 권한을 부여하지 않습니다.

### 5. dao-skills 누락 (plugin 설치·갱신 문제)

진단: 작업이 "다오 스킬 원본을 찾을 수 없습니다: ... — plugin 설치/배포를 확인하세요" 라는 질문으로 회수되면, 모리가 다오 작업 폴더에 심을 스킬 원본(plugin 동봉 `dao-skills/`)을 찾지 못한 것입니다. 이 누락은 fallback 없이 곧바로 표시됩니다.

```shell
ls -d "${CLAUDE_PLUGIN_ROOT}/dao-skills"
```

복구: plugin 설치가 불완전하거나 오래된 것이므로 `/plugin` 으로 UnSkein plugin 을 재설치(갱신)합니다. 재설치 후 위 경로가 있는지 다시 확인합니다.

### 6. claude -p 실패 (timeout / is_error / JSON 파싱 실패)

`/unskein:run` 출력으로 세 갈래를 구분합니다:

- **timeout**: "claude -p timeout (1800s 초과)" 로 회수됨. 작업이 `UNSKEIN_CLAUDE_TIMEOUT`(기본 1800초)을 넘긴 것입니다. 작업 규모에 비해 한도가 짧으면 사용자와 상의해 한도를 올리거나 작업을 더 작게 나눕니다. 환경값을 임의로 키우지 말고 사용자에게 확인합니다.
- **is_error**: "claude is_error: <subtype>" 로 회수됨. claude 가 오류 상태로 끝난 것입니다. 함께 출력된 `[dao stderr]` 와 raw stdout 머리부분으로 사유(인증·권한·실행 환경)를 봅니다.
- **JSON 파싱 실패**: "JSON 파싱 실패: ..." 로 회수됨. claude 출력이 정상 JSON 이 아닙니다. raw stdout 머리부분을 확인해 claude 가 에러 메시지를 평문으로 냈는지(예: 로그인·인증 필요, 권한 거부) 봅니다.

세 경우 모두, WSL에서 claude 단독 동작을 한 번 확인하면 원인이 좁혀집니다:

```shell
claude -p "ok" --output-format json
```

이게 정상 JSON 을 내면 claude 자체는 동작하는 것이니 작업·자격증명 쪽을, 여기서 막히면 claude 설치·로그인 쪽을 봅니다. 원인이 안 잡히면 추측으로 우회하지 말고 관찰한 출력을 사용자에게 보고하고 멈춥니다.

### 7. 서버 도달 실패 (GET /api/health)

진단: 스냅샷의 서버 도달이 `실패` 면 네트워크 또는 주소 문제입니다.

```shell
curl -s "${UNSKEIN_API:-https://unskein.mupai.studio}/api/health"
```

`{"status":"ok"}` 가 나오면 도달 OK 입니다. `HTTP 4xx/5xx` 면 주소는 맞는데 서버 쪽 응답 문제, 연결 자체가 안 되면(타임아웃·이름 해석 실패) 네트워크 또는 주소 오타입니다.

복구: 주소 오타면 `unskein-setup` S1로 `UNSKEIN_API` 를 바로잡습니다. 네트워크 문제면 사유(타임아웃·DNS 등)를 사용자에게 그대로 보여주고, 네트워크가 회복되면 다시 확인합니다.

### 8. 화면 검증이 CDP Chrome(기본 9222)에 안 붙음

화면 런타임 검증은 `unskein-test` 스킬이 담당합니다. 그 검증이 "CDP 연결 실패" 로 멈추면 세 가지를 봅니다.

첫째, 가장 흔한 원인은 실행 위치입니다. `remote.js` 는 **윈도우 Node** 로, `start.ps1`/`stop.ps1` 은 **PowerShell** 로 호출해야 `127.0.0.1:<포트>` 가 윈도우 로컬을 가리킵니다. WSL 안의 Node 로 `remote.js` 를 실행하면 `127.0.0.1` 이 WSL 루프백이 되어 윈도우에 떠 있는 CDP Chrome 에 닿지 못합니다. 모리 운영 세션이 WSL 안에서 돌고 있다면 이 갈래를 먼저 의심합니다.

둘째, **포트 불일치**(병렬 세션): `start.ps1 -Port <n>` 로 띄웠는데 `remote.js` 가 기본 9222 로 붙고 있으면 연결이 안 됩니다. 에러 메시지의 포트와 띄운 포트를 대조하고, `--port=<n>` 또는 `CDP_PORT=<n>` 로 맞춥니다(포트↔프로필 1:1 — `unskein-test` §3).

셋째, Chrome 자체가 그 포트에 안 떠 있을 수 있습니다. 윈도우에서 기동 상태를 확인합니다(윈도우 PowerShell 에서):

```shell
powershell.exe -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/start.ps1"
```

복구: `unskein-test` 6장(실환경 검증 필요)의 안내대로 윈도우 Node·PowerShell 경로로 다시 실행합니다. 그 포트가 안 떠 있으면 위 `start.ps1`(병렬 세션은 `-Port <n>`)로 띄우고 `READY` 출력과 엔드포인트(`http://127.0.0.1:<포트>`)를 확인합니다. "profile is already used by another Chrome" 거부가 뜨면 같은 프로필을 다른 포트로 두 번 띄운 것 — 그 세션의 포트를 쓰거나 `stop.ps1 -Port/-Profile` 로 먼저 정리합니다. WSL 자체 확인만으로는 포트 도달을 보장하지 못하므로, 이 갈래는 윈도우 실환경에서 확인합니다.

### 9. 기존 환경 충돌 (전역 스킬·CLAUDE.md·플러그인)

unskein plugin 은 모리 클라이언트의 사용자 전역(`~/.claude`)에 설치됩니다. 같은 사용자 환경에 이미 다른 스킬·`CLAUDE.md`·플러그인이 있으면, 모리(또는 모리가 띄운 다오)가 그것까지 상속해 unskein 규약과 충돌할 수 있습니다. 또렷한 에러가 아니라 "규약과 다르게 동작"하는 형태(출력 형식을 안 지킴, 엉뚱한 지침을 따름)면 이 갈래를 의심합니다.

진단 — 겹치거나 끼어드는 것이 있는지 봅니다(값이 아니라 존재·이름만):

```shell
# (1) 전역 스킬 이름이 unskein 제공 스킬과 겹치는가
ls ~/.claude/skills/ 2>/dev/null
#     비교 대상(이름 겹침만 본다):
#     - 모리용(plugin skills/): setup·doctor·test·case·work·scope·wbs·drawio·session·lock·deploy·logical-thinking
#     - dao-skills(작업 폴더로 이식): exec·git·verify·wiki-search·wiki-ingest·wiki-lint
#       (정확한 현재 목록은 `ls ${CLAUDE_PLUGIN_ROOT}/dao-skills/.claude/skills/` 로 확인)
# (2) 전역 CLAUDE.md 가 있어 모리·다오 세션이 상속하는가
ls -l ~/.claude/CLAUDE.md 2>/dev/null
# (3) 다른 marketplace/플러그인이 /unskein:* 명령·같은 이름 스킬과 겹치는가
ls ~/.claude/plugins/marketplaces/ 2>/dev/null
```

판정:

- **스킬 이름 충돌**: 전역 `~/.claude/skills/` 에 위 unskein 스킬·dao-skills 와 같은 이름이 있으면, 같은 이름이 전역과 plugin 에 동시에 존재해 어느 것이 적용될지 모호합니다. 특히 dao-skills 이름(`unskein-exec`·`unskein-git` 등)이 전역에도 있으면, 다오가 작업 폴더 복사본(`plant_dao_skills`) 대신 전역 스킬을 읽을 위험이 있습니다.
- **전역 CLAUDE.md 상속**: `~/.claude/CLAUDE.md` 가 있으면 모리·다오 세션이 그 지침을 함께 상속합니다. 그 안에 출력 규약·정체성·다른 에이전트 지침이 있으면 unskein 의 출력 규약(`RESULT:`/`QUESTION:`)·역할과 충돌할 수 있습니다. 다오는 작업 폴더의 `CLAUDE.md` 를 읽지만 전역 `CLAUDE.md` 도 함께 상속하므로, 둘이 어긋나면 동작이 흔들립니다.
- **명령 충돌**: 다른 플러그인이 같은 `/unskein:*` 명령이나 같은 이름 스킬을 제공하면 호출이 엇갈립니다.

복구: 충돌은 임의로 지우지 않습니다 — 무엇이 겹치는지 사용자에게 그대로 보여주고, 어느 것을 살릴지 함께 정합니다. 전역 `CLAUDE.md` 의 지침이 모리·다오 동작에 끼어들면 그 항목을 사용자에게 보고하고, unskein 규약(plugin `CLAUDE.md`·dao-skills `CLAUDE.md`)이 우선되도록 정리할지 상의합니다. 겹치는 전역 스킬은 이름을 바꾸거나 한쪽을 비활성화할지 사용자와 정합니다(fallback 으로 한쪽을 임의 삭제하지 않습니다).

### 10. gh 미설치·미인증 (preflight 가 claim 전 차단)

진단: 모리가 작업을 하나도 잡지 못하고 preflight 단계에서 `[실패] gh CLI 인증(PR 생성)` 을 출력하며 종료하면(claim 안 함), gh 가 없거나 인증이 깨진 것입니다. 다오는 마감(`unskein-git`)에서 PR 을 `gh pr create` 로만 만들기 때문에(REST fallback 없음), gh 인증은 작업을 잡기 전에 갖춰야 하는 치명 항목입니다. 스냅샷의 `gh CLI` 항목으로 갈래를 좁힙니다.

```shell
command -v gh && gh auth status
```

- `command -v gh` 가 비면 미설치입니다.
- gh 는 있는데 `gh auth status` 가 비-0(미로그인·토큰 무효)이면 미인증입니다.
- `gh auth status` 가 네트워크·타임아웃으로 응답을 못 주면(스냅샷에 `응답 없음`) gh 가 아니라 연결 문제일 수 있으니 네트워크부터 확인합니다.

복구: `unskein-setup` S1 로 gh 를 설치(무-sudo 환경이면 공식 릴리스 바이너리를 `~/.local/bin`)하고, `gh auth login`(mupaistudio 계정, GitHub.com·HTTPS) → `gh auth setup-git` 으로 인증합니다. 토큰 값은 화면에 출력하지 않습니다.

참고: preflight 는 통과(gh 인증됨)했는데도 마감에서 PR 이 권한(403)으로 막히면, 토큰 scope 가 부족하거나 그 계정이 대상 repo 의 collaborator 가 아닌 경우입니다(preflight 는 대상 repo 를 모르므로 여기까진 못 잡습니다 — `unskein-git` 이 브랜치 push 까지만 하고 PR 은 사람에게 회수합니다). 그 repo 에 push/PR 권한이 있는 계정으로 `gh auth login` 했는지, 토큰 scope(`repo`·`workflow`)를 확인합니다.

### 11. 케이스가 안 쌓임 (검증은 도는데 케이스 저장소가 그대로)

TESTER 갈래입니다. 화면검증은 정상으로 돌아 카드가 전진하는데, 케이스 저장소(웹 케이스 목록·`case-sync.py pull`)에 새 케이스가 안 늘어납니다. **에러가 화면에 안 뜨기 때문에 오래 묻힙니다** — 2026-07-29 실측에서 `UNSKEIN_BUSINESS_ID` 가 비어 있어 **12일 동안 케이스가 한 건도 안 올라갔는데 아무도 몰랐습니다.** 사유는 카드에 정확히 적혀 있었지만(검증 결과의 케이스 동기 표기) 보는 자리가 없어 묻혔습니다. 그래서 이 갈래는 **카드부터** 봅니다.

진단 — 세 자리를 순서대로 봅니다:

1. **카드(가장 먼저)**: 그 검증 카드의 검증 결과(`task.payload['test']`)와 리포트 본문에 **"케이스 동기 미실행"** 표기가 있는지 봅니다. `unskein-test` §0.2 는 케이스 동기가 실패해도 검증 자체는 진행하되 사유를 남기게 합니다(#783 은 `payload['test'].cases_sync` 에 사유가 남았습니다). 표기가 있으면 **그 사유가 곧 원인**이라 아래 2·3 은 확인용입니다.
2. **서버 로그**: `POST /api/cases/push` 호출이 아예 없으면 단말에서 명령이 시작 전에 멈춘 것(env 미설정)입니다. 호출은 있는데 4xx 로 끝나면 인증(401)·비즈니스 지정 문제입니다.
3. **단말 env**: 그 TESTER 번들의 `UNSKEIN_BUSINESS_ID`. 값은 출력하지 않고 설정 여부만 봅니다.

```powershell
# TESTER 번들을 dot-source 한 창에서 (값은 출력하지 않는다)
if ($env:UNSKEIN_BUSINESS_ID) { "UNSKEIN_BUSINESS_ID 설정됨" } else { "UNSKEIN_BUSINESS_ID 없음" }
# 서버에 쓰지 않고 무엇이 올라갈지만 본다
python "$env:CLAUDE_PLUGIN_ROOT\bin\case-sync.py" push --host=<슬러그> --dry-run
```

복구: `tester.ps1` 의 `$env:UNSKEIN_BUSINESS_ID` 에 비즈니스 **번호(숫자 id)** 를 넣습니다. **이름은 안 됩니다** — 이름→id 해석은 planner 토큰 전용이라 tester 토큰이 이름을 주면 401 로 멈춥니다(`unskein-case` · `unskein-setup` §T3). 번호는 웹에서 그 비즈니스를 연 주소나 플래너에게 확인합니다. 값을 모르면 임의로 채우지 말고 사용자에게 묻고 멈춥니다.

재검증: **새 창**에서 `. tester.ps1` 을 다시 dot-source 하고(이전 창에는 옛 빈 값이 남아 있습니다) `case-sync.py push --host=<슬러그>` 가 `upserted` 1건 이상으로 끝나는지, `pull` 과 웹 케이스 목록에 실제로 보이는지 확인합니다. 이어서 검증 한 바퀴를 돌려 카드에서 "케이스 동기 미실행" 표기가 사라지는지 봅니다.

### 12. 증거(캡처·raw 진단)가 안 올라감

TESTER 갈래입니다. 검증 결과 상세에 "첨부 없음" 만 뜨거나, 리포트에 **"증거 업로드 미실행(사유)"** 이 적혀 있습니다. 결론(리포트 본문)은 왔는데 그 근거 화면을 플래너가 웹에서 못 엽니다 — 증거가 검증한 단말에만 남은 상태입니다. 11번과 같은 모양의 침묵 실패라 같은 순서로 봅니다.

진단: 업로드 명령(`unskein-test` §0.2 6단계 `queue.js artifacts`) 출력의 네 묶음과 payload 의 `artifacts_error` 를 읽습니다.

- `uploaded` 가 0 인데 `scanned` 에 `{"dir":"shots","missing":true}` → 케이스 폴더에 `shots/` 자체가 없습니다. `remote.js shot` 은 케이스 폴더가 아니라 `skills/unskein-test/scripts/shots/` 에 쓰므로, 캡처를 케이스 폴더로 **안 옮긴** 경우입니다(증거가 없어서가 아닙니다).
- `skipped` → 단말에서 걸러진 것(이름·확장자·크기). `rejected` → 서버가 거부한 것으로, `status` 코드가 사유입니다:

| 코드 | 뜻 | 조치 |
|---|---|---|
| 413 | 한도 초과 — 파일당 / 작업당 개수 / 작업당 총합(한도 값은 `unskein-test` §0.2 6단계가 단일 출처) | 개수·총합은 **작업 누적**이라 재검증 회차가 쌓이면 걸립니다. 그 작업의 옛 첨부를 지우고 다시 올립니다. 매 회차 걸리면 한도를 올리기 전에 **무엇을 남길지 줄입니다** |
| 409 | 같은 이름의 **다른** 내용이 이미 있음(덮어쓰지 않습니다) | 다른 이름으로 올리거나 기존 첨부를 지웁니다. `shots/` 와 `diagnostics/` 에 같은 파일명을 두지 않습니다. 같은 내용이면 애초에 거부가 아니라 skip 입니다 |
| 422 | 이름·확장자 규칙 위반, `kind` 오값 | 이름은 `^[A-Za-z0-9._-]{1,64}$`(공백·한글·경로 구분자 불가). **실행 가능 형식(`.js`·`.ps1`·`.sh`)은 증거로 못 올립니다** — 그건 케이스 스크립트 경로(`case-sync.py push`)가 담당합니다 |
| 401 | 토큰 없음·무효 | 그 번들의 `UNSKEIN_MORI_TOKEN`(tester 토큰)을 재발급·재설정합니다 — 2번 갈래와 같은 처방 |
| 403 | 그 작업이 속한 프로젝트의 멤버가 아니거나 읽기 전용(viewer) | 멤버십·권한을 플래너·운영자와 정합니다(경로를 안다고 열리지 않습니다 — `unskein-setup` §T0-선결) |
| 404 | 그 번호의 작업이 없음 | 작업 번호를 카드에서 다시 확인합니다(선점한 카드의 id) |
| 500 | 서버가 증거 저장 디렉토리를 못 만듦 | 서버 쪽 문제입니다 — 사유 문구를 그대로 보고하고 멈춥니다(단말에서 우회하지 않습니다) |

복구: 위 사유를 해소한 뒤 **같은 명령을 다시 돌립니다** — 같은 내용의 재업로드는 서버가 no-op(skip)으로 받으므로 반복해도 중복이 안 생깁니다. 폴더 경로 오타면 명령이 즉시 실패하니(`증거 폴더가 없습니다`) 경로부터 맞춥니다. 사유가 안 잡히면 우회로 첨부를 포기하지 말고 관찰한 `rejected` 를 그대로 보고합니다.

재검증: `node queue.js artifacts <id> --dir=<케이스폴더>` 가 `ok:true` 로 끝나고 출력의 `artifacts` 목록에 파일이 보이는지, 이어서 웹 검증 결과 상세에서 캡처가 실제로 열리는지 확인합니다. 결함 옆 링크가 안 붙으면 `findings[].evidence` 의 파일명이 올린 이름과 어긋난 것입니다(`unskein-test` §0.3).

## 3. 재검증

복구 후 같은 단계에서 다시 확인해 증상이 사라졌는지 봅니다:

- 1·4·5·7·10번: `/unskein:status` 를 다시 돌려 해당 항목이 `OK` 로 바뀌었는지 확인합니다.
- 2·3·6번: `/unskein:run` 한 바퀴를 실제로 돌려 claim·clone·push·회수까지 진행되는지 확인합니다.
- 8번: 윈도우에서 `start.ps1` 의 `READY` 출력과 `remote.js tabs` 응답으로 CDP Chrome 연결이 되는지 확인합니다(병렬 세션은 그 포트로 — `start.ps1 -Port <n>` + `remote.js tabs --port=<n>`).
- 9번: 충돌을 정리한 뒤 `/unskein:run` 한 바퀴가 규약(`RESULT:`/`QUESTION:`)대로 회수되는지 확인합니다.
- 11·12번: 각 갈래 끝의 재검증 절차대로 — 케이스는 `push` 가 `upserted` 를 내고 웹 목록에 보이는지, 증거는 업로드가 `ok:true` 로 끝나고 웹 검증 결과 상세에서 실제로 열리는지. 둘 다 **다음 검증 한 바퀴에서 카드의 미실행 표기가 사라지는 것**까지 봐야 닫힙니다(단발 성공은 env 가 새 창에 안 실린 경우를 못 가릅니다).

증상이 사라지면 복구 완료를 알리고, 연속 처리는 `/unskein:watch` 로 안내합니다.

## 4. 못 고칠 때

원인이 안 잡히거나 복구가 안 되면, 임시 우회(다른 값으로 돌리기, 인증·권한 건너뛰기, fallback 기본값)를 만들지 않습니다. 다음을 정리해 사용자에게 보고하고 멈춥니다:

- 어느 단계에서 멈추는지.
- 스냅샷에서 `없음`/`실패` 로 나온 항목.
- 시도한 복구와 그 결과.
- 관찰한 에러 메시지(비밀 값 제외).
