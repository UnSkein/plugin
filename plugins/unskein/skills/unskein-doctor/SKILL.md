---
name: unskein-doctor
description: 모리 클라이언트가 작업을 못 돌릴 때 무엇이 깨졌는지 진단하고 복구를 안내한다 — 증상→원인 후보→복구 액션→재검증. /unskein:status 스냅샷을 출발점으로 증상에 맞는 갈래를 따라 원인을 좁힌다. 트리거 — 진단, 복구, 안 됨, 실패, doctor, 문제 해결, 토큰 인증 실패, 401, claude 못 찾음, clone 실패, push 실패, 작업 실행 실패, 화면 검증 안 됨, CDP 안 붙음, 9222 연결 실패, 스킬 충돌, CLAUDE.md 충돌, 전역 스킬 겹침, 기존 설치 충돌.
---

# UnSkein — 진단·복구 (doctor)

모리 클라이언트가 작업을 못 돌릴 때, 무엇이 깨졌는지 짚어내고 복구를 안내합니다. `/unskein:status` 는 현재 상태를 읽기 전용으로 보여주는 스냅샷이고, 이 스킬은 그 스냅샷을 출발점으로 증상에 맞는 갈래를 따라가 원인을 좁히고 복구 액션까지 연결합니다. 클라이언트 주인(사용자)과 대화하며 진행합니다.

원칙:

- 비밀(토큰·SSH 키) 값은 화면에 출력하지 않습니다 — `설정됨`/`없음` 같은 존재 여부만 다룹니다.
- 못 고치면 임시 우회를 만들지 않습니다. 사유를 사용자에게 그대로 보고하고 멈춥니다(fallback 금지).
- 복구 후에는 재검증 단계까지 진행합니다.

## 1. 스냅샷 확보

먼저 현재 상태를 읽어 증상을 확인합니다:

```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/status.py"
```

출력에서 다음을 읽습니다:

- `UNSKEIN_API` — 설정값 또는 기본값 표기.
- `UNSKEIN_MORI_TOKEN` — `설정됨` / `없음`.
- `UNSKEIN_CRED_DIR` — 폴더 존재 + 어떤 자격증명이 있는지(`.env`/`id_ed25519`/`id_rsa`).
- `UNSKEIN_WORK_ROOT` — 폴더 존재 + 클론된 폴더 목록.
- 서버 도달 — `status=ok` 또는 실패 사유.

사용자에게 실제 증상도 함께 묻습니다(예: "한 바퀴 실행했는데 어디서 멈췄나요?", 화면에 나온 에러 메시지 한 줄). 스냅샷의 `없음`/`실패` 항목과 사용자 증상을 맞춰 아래 갈래로 들어갑니다.

## 2. 증상 → 원인 후보 → 복구 갈래

| # | 증상(어디서 멈추나) | 원인 후보 | 복구 액션 |
|---|------|------|------|
| 1 | `claude` 또는 `git` 을 못 찾음 | WSL에 실행 파일 부재 | `unskein-connect` 1단계로 설치 안내 |
| 2 | claim 단계에서 멈춤(`HTTP 401`) / 토큰 인증 실패 | `UNSKEIN_API`·`UNSKEIN_MORI_TOKEN` 미설정 또는 무효 | `unskein-connect` 로 연결 정보 재설정 |
| 3 | claim은 되는데 clone·push 에서 실패 | git 자격증명(HTTPS 토큰/SSH 키) 누락·만료 | `unskein-add-site` 로 자격증명 재배치·교체 |
| 4 | 작업 폴더 없음/권한 오류 | `UNSKEIN_WORK_ROOT` 부재·권한 부족 | 폴더 생성·권한 보정 |
| 5 | "다오 스킬 원본을 찾을 수 없습니다" 로 회수됨 | dao-skills 원본 누락(plugin 설치·갱신 문제) | `/plugin` 재설치 |
| 6 | `claude -p` 가 timeout / is_error / JSON 파싱 실패로 회수됨 | 실행 시간 초과 / claude 내부 오류 / 출력 비정상 | 아래 6번에서 원인 분기 후 확인 |
| 7 | 서버 도달 실패(`GET /api/health`) | 네트워크·주소 문제 | 주소·네트워크 확인 |
| 8 | 화면 검증(CDP)이 Chrome(9222)에 안 붙음 | WSL Node 로 실행해 `127.0.0.1` 이 WSL 루프백을 가리킴 / Chrome 미기동 | 윈도우 Node·PowerShell 로 실행 (`unskein-test` 6장) |
| 9 | 모리·다오가 규약과 다르게 동작(출력 형식 어김, 엉뚱한 지침·스킬을 따름) | 기존 전역 스킬·`CLAUDE.md`·플러그인이 unskein 과 충돌 | 아래 9번에서 충돌 점검 |

각 갈래의 진단·복구 절차는 아래와 같습니다.

### 1. claude/git 부재

진단:

```shell
command -v claude; command -v git
```

둘 중 하나라도 비면 그 실행 파일이 없는 것입니다. 다오(`claude -p`)는 WSL 안에서 구동하므로 WSL 안에 있어야 합니다.

복구: `unskein-connect` 1단계(실행 환경 확인)로 설치를 안내합니다. 설치 후 위 명령으로 다시 확인합니다.

### 2. 연결 정보 미설정/무효 (claim 401)

진단: 스냅샷의 `UNSKEIN_MORI_TOKEN` 이 `없음` 이면 미설정입니다. `설정됨` 인데도 `/unskein:run` 이 `[http error] 401` 로 멈추면 토큰이 무효(잘못된 값/만료/해지)입니다. claim 은 토큰을 헤더로 보내 인증하므로, 무효 토큰은 401 로 표시됩니다.

복구: `unskein-connect` 2단계로 `UNSKEIN_API`·`UNSKEIN_MORI_TOKEN` 을 다시 설정합니다. 토큰은 UnSkein 설정 화면에서 다시 발급합니다. 토큰 값은 화면에 출력하지 않습니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

### 3. git 자격증명 누락·만료 (clone/push 실패)

진단: claim 은 성공하는데(작업을 선점하는데) 다오의 clone·push 단계에서 실패하면 git 자격증명 문제입니다. 저장소 주소 형식으로 필요한 자격증명이 갈립니다:

- `https://` 저장소 → 토큰. `creds/.env` 의 `UNSKEIN_GIT_TOKEN=`(또는 호스트별 `UNSKEIN_GIT_TOKEN_<HOST>=`). 토큰이 없거나 만료되면 clone/push 가 인증 실패합니다.
- `git@`/`ssh://` 저장소 → SSH 개인키. `creds/id_ed25519`(또는 `id_rsa`), 권한 `600`.

스냅샷의 `UNSKEIN_CRED_DIR` 항목으로 `.env`/`id_ed25519` 존재 여부를 봅니다. 어떤 자격증명이 필요한지는 그 프로젝트의 저장소 주소로 정합니다.

복구: `unskein-add-site` 의 자격증명 갱신 단계로 자격증명을 재배치하거나 교체합니다(토큰 재발급, 키 교체). 토큰·키 값은 화면에 출력하지 않고, 저장소 주소나 git 설정에 토큰을 넣지 않습니다. 토큰을 교체한 경우 옛 토큰을 발급처에서 폐기하도록 안내합니다.

### 4. 작업 폴더 없음/권한

진단: 스냅샷의 `UNSKEIN_WORK_ROOT` 가 `폴더 없음` 이거나 `목록 조회 실패` 면 작업 폴더 문제입니다.

```shell
ls -ld "${UNSKEIN_WORK_ROOT:-$HOME/.unskein/work}"
```

복구: 폴더를 만들고 권한을 보정합니다.

```shell
mkdir -p "${UNSKEIN_WORK_ROOT:-$HOME/.unskein/work}"
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

- **timeout**: "claude -p timeout (600s 초과)" 로 회수됨. 작업이 `UNSKEIN_CLAUDE_TIMEOUT`(기본 600초)을 넘긴 것입니다. 작업 규모에 비해 한도가 짧으면 사용자와 상의해 한도를 올리거나 작업을 더 작게 나눕니다. 환경값을 임의로 키우지 말고 사용자에게 확인합니다.
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

복구: 주소 오타면 `unskein-connect` 2단계로 `UNSKEIN_API` 를 바로잡습니다. 네트워크 문제면 사유(타임아웃·DNS 등)를 사용자에게 그대로 보여주고, 네트워크가 회복되면 다시 확인합니다.

### 8. 화면 검증이 Chrome(9222)에 안 붙음

화면 런타임 검증은 `unskein-test` 스킬이 담당합니다. 그 검증이 "CDP 연결 실패" 로 멈추면 두 가지를 봅니다.

첫째, 가장 흔한 원인은 실행 위치입니다. `remote.js` 는 **윈도우 Node** 로, `start.ps1`/`stop.ps1` 은 **PowerShell** 로 호출해야 `127.0.0.1:9222` 가 윈도우 로컬을 가리킵니다. WSL 안의 Node 로 `remote.js` 를 실행하면 `127.0.0.1` 이 WSL 루프백이 되어 윈도우에 떠 있는 Chrome(9222)에 닿지 못합니다. 모리 운영 세션이 WSL 안에서 돌고 있다면 이 갈래를 먼저 의심합니다.

둘째, Chrome 자체가 9222 에 안 떠 있을 수 있습니다. 윈도우에서 기동 상태를 확인합니다(윈도우 PowerShell 에서):

```shell
powershell.exe -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/start.ps1"
```

복구: `unskein-test` 6장(실환경 검증 필요)의 안내대로 윈도우 Node·PowerShell 경로로 다시 실행합니다. 9222 가 안 떠 있으면 위 `start.ps1` 로 띄우고 `READY` 출력과 엔드포인트(`http://127.0.0.1:9222`)를 확인합니다. WSL 자체 확인만으로는 9222 도달을 보장하지 못하므로, 이 갈래는 윈도우 실환경에서 확인합니다.

### 9. 기존 환경 충돌 (전역 스킬·CLAUDE.md·플러그인)

unskein plugin 은 모리 클라이언트의 사용자 전역(`~/.claude`)에 설치됩니다. 같은 사용자 환경에 이미 다른 스킬·`CLAUDE.md`·플러그인이 있으면, 모리(또는 모리가 띄운 다오)가 그것까지 상속해 unskein 규약과 충돌할 수 있습니다. 또렷한 에러가 아니라 "규약과 다르게 동작"하는 형태(출력 형식을 안 지킴, 엉뚱한 지침을 따름)면 이 갈래를 의심합니다.

진단 — 겹치거나 끼어드는 것이 있는지 봅니다(값이 아니라 존재·이름만):

```shell
# (1) 전역 스킬 이름이 unskein 제공 스킬과 겹치는가
ls ~/.claude/skills/ 2>/dev/null
#     비교 대상: unskein-connect/add-site/doctor/test (모리용),
#     unskein-scope/exec/verify/wiki-search/wiki-record/wiki-lint (dao-skills)
# (2) 전역 CLAUDE.md 가 있어 모리·다오 세션이 상속하는가
ls -l ~/.claude/CLAUDE.md 2>/dev/null
# (3) 다른 marketplace/플러그인이 /unskein:* 명령·같은 이름 스킬과 겹치는가
ls ~/.claude/plugins/marketplaces/ 2>/dev/null
```

판정:

- **스킬 이름 충돌**: 전역 `~/.claude/skills/` 에 위 unskein 스킬·dao-skills 와 같은 이름이 있으면, 같은 이름이 전역과 plugin 에 동시에 존재해 어느 것이 적용될지 모호합니다. 특히 dao-skills 이름(`unskein-scope` 등)이 전역에도 있으면, 다오가 작업 폴더 복사본(`plant_dao_skills`) 대신 전역 스킬을 읽을 위험이 있습니다.
- **전역 CLAUDE.md 상속**: `~/.claude/CLAUDE.md` 가 있으면 모리·다오 세션이 그 지침을 함께 상속합니다. 그 안에 출력 규약·정체성·다른 에이전트 지침이 있으면 unskein 의 출력 규약(`RESULT:`/`QUESTION:`)·역할과 충돌할 수 있습니다. 다오는 작업 폴더의 `CLAUDE.md` 를 읽지만 전역 `CLAUDE.md` 도 함께 상속하므로, 둘이 어긋나면 동작이 흔들립니다.
- **명령 충돌**: 다른 플러그인이 같은 `/unskein:*` 명령이나 같은 이름 스킬을 제공하면 호출이 엇갈립니다.

복구: 충돌은 임의로 지우지 않습니다 — 무엇이 겹치는지 사용자에게 그대로 보여주고, 어느 것을 살릴지 함께 정합니다. 전역 `CLAUDE.md` 의 지침이 모리·다오 동작에 끼어들면 그 항목을 사용자에게 보고하고, unskein 규약(plugin `CLAUDE.md`·dao-skills `CLAUDE.md`)이 우선되도록 정리할지 상의합니다. 겹치는 전역 스킬은 이름을 바꾸거나 한쪽을 비활성화할지 사용자와 정합니다(fallback 으로 한쪽을 임의 삭제하지 않습니다).

## 3. 재검증

복구 후 같은 단계에서 다시 확인해 증상이 사라졌는지 봅니다:

- 1·4·5·7번: `/unskein:status` 를 다시 돌려 해당 항목이 `OK` 로 바뀌었는지 확인합니다.
- 2·3·6번: `/unskein:run` 한 바퀴를 실제로 돌려 claim·clone·push·회수까지 진행되는지 확인합니다.
- 8번: 윈도우에서 `start.ps1` 의 `READY` 출력과 `remote.js tabs` 응답으로 Chrome(9222) 연결이 되는지 확인합니다.
- 9번: 충돌을 정리한 뒤 `/unskein:run` 한 바퀴가 규약(`RESULT:`/`QUESTION:`)대로 회수되는지 확인합니다.

증상이 사라지면 복구 완료를 알리고, 연속 처리는 `/unskein:watch` 로 안내합니다.

## 4. 못 고칠 때

원인이 안 잡히거나 복구가 안 되면, 임시 우회(다른 값으로 돌리기, 인증·권한 건너뛰기, fallback 기본값)를 만들지 않습니다. 다음을 정리해 사용자에게 보고하고 멈춥니다:

- 어느 단계에서 멈추는지.
- 스냅샷에서 `없음`/`실패` 로 나온 항목.
- 시도한 복구와 그 결과.
- 관찰한 에러 메시지(비밀 값 제외).
