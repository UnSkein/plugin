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

UnSkein 큐의 **검증 단계**를 TESTER 가 스스로 처리합니다. 어느 status 가 검증 단계인지, 검증 뒤 어디로 가는지, 갈래가 있는지는 **그 카드가 속한 프로세스 정의가 정합니다** — 이 스킬에 박혀 있지 않습니다. claim 이 그 카드의 단계 값(`stage.skill`·`stage.label`·`stage.reportable_next`)을 배달하고, 보고는 그 값으로 합니다(§0.2 7단계).

파이프라인은 프로세스마다 다릅니다:

| 프로세스 | 검증 단계 | 다음 | 갈래 |
|---|---|---|---|
| `dev` | `test`(화면검증) | `inspect`(마감) / `plan`(롤백) | PASS/FAIL 2갈래 |
| `frame9_bnd` | `verify`(검수(CDP)) | `inspection` | 없음 — 무조건 전진 |

dev 가 `plan → test → inspect → done` 으로 도는 것은 **dev 정의가 그 모양**이기 때문이지, 이 스킬이 강제해서가 아닙니다.

### 0.1 역할·인증

- TESTER 는 **윈도우 Claude Code 세션**입니다(다오=WSL 코드검증, 테스터=윈도우 화면검증 — 프로세스 경계로 "구현≠검증"을 실현). CDP Chrome(기본 9222)은 윈도우 프로세스라 WSL 에서 못 붙습니다. 테스터 세션 여러 개를 병렬로 돌리려면 세션마다 다른 포트로(§3 포트↔프로필 1:1 — 인증 완전 분리).
- **테스터 토큰**(kind=tester): 웹에서 발급(`POST /me/mori-tokens {kind:"tester"}`). EXECUTOR(kind=mori) 토큰과 달리 큐에서 **검증 단계만** 집습니다(서버 스테이지 게이트) — 어느 단계가 그것인지는 프로세스 정의의 `claim_kinds` 에 `tester` 가 든 자리로 정해집니다(dev 는 `test`, `frame9_bnd` 는 `verify`). 값은 환경변수로만 둡니다(비밀 무잔존, 화면 출력 금지):
  - `UNSKEIN_API_BASE`(예: `https://unskein.mupai.studio`), `UNSKEIN_MORI_TOKEN`(테스터 토큰).
  - `UNSKEIN_BUSINESS_ID`(케이스 동기용 business id) — 비즈니스 **이름→id 해석은 planner 토큰 전용**이라 tester 토큰은 id 를 직접 둡니다. 미설정이면 케이스 pull/push 가 명확히 멈춥니다(조용한 우회 없음).
- **여러 사이트**: 한 TESTER 가 자기 멤버십의 모든 사이트를 담당합니다. 특정 사이트만 보려면 `claim --business=<이름> --project=<이름>` 로 좁힙니다(watch 스코프). `node queue.js scope` 로 담당 가능 사이트를 확인합니다.

### 0.2 한 tick — claim → 검증 → report

`queue.js`(서버 왕복) + `start.ps1`/`remote.js`(CDP)로 한 작업을 처리합니다:

1. **선점**: `node ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/queue.js claim` → `{claimed, task, stage, skills}`. `claimed:false` 면 조용히 종료(대기 작업 없음). task 에는 검증 대상 **`tested_url`**, 수용 기준(`title`/`description`/`plan_doc`), `subtree`(하위 작업)가 실려 옵니다. **`stage`** 에는 그 카드의 단계 값(`status`=출발 단계 · `skill`=이 단계가 호출할 스킬 · `doc_slot` · `label` · `reportable_next`=보고 가능한 다음 단계)이 정의에서 파생돼 실려 옵니다 — 7단계 보고가 이 값을 씁니다.
   - claim 은 **이 단말에 설치된 스킬을 함께 신고**합니다(`~/.claude/plugins` 스캔 → 이름·버전·`exits`·`output` 만. 스킬 본문은 올리지 않습니다). 서버는 (정의의 `skill_key` × 신고 × `kind`) 교차로 후보를 파생하므로, **신고에 없는 스킬이 배정된 단계의 카드는 오지 않고 기다립니다**(pull 원칙). 정의 화면의 "보유 N대"·능력표가 이 신고를 읽습니다.
   - 서버가 신고를 무시하면(구서버) claim 이 **중단**합니다 — 조용히 dev 카드만 도는 축소 운행을 막습니다. 이 오류가 나면 서버를 올려야 합니다.
2. **케이스 흡수(claim 직후)**: `tested_url` 에서 호스트 슬러그를 파생해 이 호스트의 축적 케이스를 내려받습니다 — 슬러그 규칙(host[:port] 의 `:`→`-`, 예 `localhost:5151`→`localhost-5151`)은 손으로 만들지 말고 **같은 코드로 파생**합니다:
   ```shell
   SLUG=$(python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py slug <tested_url>)
   python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py pull --host=$SLUG   # --business 는 UNSKEIN_BUSINESS_ID 로
   ```
   `$UNSKEIN_HOME/cases/<host>/` 아래 이 호스트/기능의 케이스(내 것 + `_public/` 공유분)를 읽고 **실행 시퀀스·셀렉터·함정을 재사용**합니다 — 같은 화면 재검증은 케이스의 시퀀스부터 돌립니다. 케이스가 없으면 첫 검증입니다(그대로 진행). 상세 규약은 `unskein-case` 스킬.
3. **lease 유지**: 검증이 길면 주기적으로 `node queue.js heartbeat <id>`(서버 stale 기준 180s — 60s 안팎으로 갱신).
4. **화면 기동·검증**: `start.ps1 -Url <tested_url>` → `remote.js navigate/collect/attrs/shot`(§4) 로 수용 기준의 시나리오를 수행. 콘솔 에러·네트워크 실패·렌더·셀렉터를 수집하고 화면을 캡처합니다. **병렬 TESTER 는 자기 포트로**: `start.ps1 -Port <n> -Url ...` + `$env:CDP_PORT=<n>`(또는 명령마다 `--port=<n>`) — 포트 없이 돌리면 두 루프가 같은 9222 크롬(같은 로그인)에 붙어 인증이 섞입니다(§3 페어링).
   - **화면에 진입한 직후 기준 크기를 잡습니다(§0.6 표준 뷰포트) — 빠뜨리면 그 검증 결과는 재현되지 않습니다.**
     ```shell
     node ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/remote.js viewport 1920x1080
     ```
5. **케이스 기록(검증 후)**: 이번 검증을 케이스로 남기고 서버에 올립니다 — 다음 검증(나·같은 비즈니스 동료)이 재사용합니다.
   - `$UNSKEIN_HOME/cases/<host>/<feature>/<slug>/case.md` 작성 — frontmatter(host/feature/name/title/status/tags/visibility) + 5요소 본문(의뢰서 Why / 실행 시퀀스 How / 결과 What / 함정 Pitfalls / 다음 사용자에게 Tips). 템플릿: `unskein-case` 스킬 `references/case-template.md`. **본문에 계정·비밀번호·토큰 금지(비밀 무잔존)** — 최초 push 는 public 기본이라 비즈니스 멤버 전체가 봅니다.
   - **다음 검증자가 그대로 돌릴 스크립트는 케이스 폴더 최상위**(`<slug>/scan-formdef.js` 같은 `.js`·`.mjs`·`.py`·`.ps1`·`.sh`)에 둡니다 — push 가 **본문과 함께 올려** 상대의 pull 에 실행 가능한 상태로 딸려 옵니다(케이스당 10개·총 256KB, 규칙·한도는 `unskein-case` §4.1). 최상위 파일은 전부 올라가니 안 올릴 것은 하위 폴더로 옮기세요. "이 스크립트 하나만 돌리면 된다"는 안내는 그 파일이 함께 와야 성립합니다.
   - 스크린샷은 케이스 폴더 `shots/`, raw 진단 데이터(collect JSON 등)는 `diagnostics/` 에 둡니다 — 이 하위 폴더는 케이스 저장소로 가지 않고 **6단계에서 작업 증거로 업로드**합니다.
   - **`remote.js shot` 은 케이스 폴더가 아니라 `skills/unskein-test/scripts/shots/<name>.jpg` 에 씁니다**(기본 JPEG 품질 80 — §0.7) — 캡처한 파일을 케이스 폴더 `shots/` 로 옮기세요. 안 옮기면 6단계가 올릴 것을 못 찾습니다 — 그때 출력의 `scanned` 에 `{"dir":"shots","missing":true}` 로 남으니, 0건 업로드면 이 값을 보고 "증거가 없어서"인지 "안 옮겨서"인지 가른 뒤 넘어갑니다(증거가 단말에만 남는데 성공 보고가 나가는 침묵 실패를 막습니다).
   - `python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py push --host=$SLUG` 로 올리고, payload 에 케이스 키(`cases: [{host, feature, name}]`)를 기록합니다(§0.3).
6. **증거 업로드(보고 직전)**: 캡처·raw 진단을 서버에 올려 **플래너가 웹에서 근거를 열어 보게** 합니다. 안 올리면 리포트에 경로 문자열만 남아 결론은 오고 근거는 검증한 단말에만 남습니다.
   ```shell
   node ${CLAUDE_PLUGIN_ROOT}/skills/unskein-test/scripts/queue.js artifacts <id> \
        --dir=$UNSKEIN_HOME/cases/<host>/<feature>/<slug>
   ```
   - `<케이스폴더>/shots/` → `kind=shot`, `<케이스폴더>/diagnostics/` → `kind=diag`. **각 폴더 최상위만** 올립니다(재귀 없음). 케이스 폴더 밖의 파일 1건은 `--file=<경로> --kind=shot|diag|report` 로.
   - **검증 대상이 UnSkein 서버가 아니면 `--build-sha=<그 사이트의 배포 SHA>` 를 함께 줍니다.** 이 값은 첨부 메타에 남아 "어느 코드 상태의 화면인가"를 답합니다(캡처를 git 에 커밋하지 않는 대신 이 한 필드가 그 역할입니다). 생략하면 서버가 **자기** 배포 SHA 를 새기므로, 남의 사이트를 검증했는데 UnSkein 서버의 SHA 가 근거처럼 남습니다. 대상 사이트의 SHA 를 모르면 그냥 생략하지 말고 리포트에 "배포 SHA 미상"이라고 적습니다.
   - 한도(서버가 거부): 파일당 **5MB** · 작업당 **30개** · 작업당 총 **50MB** · 허용 확장자 `.png` `.jpg` `.webp` `.json` `.txt` `.md` `.log` · 이름 `^[A-Za-z0-9._-]{1,64}$`(공백·한글·경로 구분자 불가). **`.jpeg` 는 허용 목록에 없습니다** — 이름이 `.jpeg` 인 캡처가 있으면 `queue.js` 가 `skipped`(`fatal:true`) + `ok:false` 로 멈춰 세우니 `.jpg` 로 바꾸거나 다시 찍습니다(조용히 빠지지 않게). **실행 가능 형식(`.js`·`.ps1`·`.sh`)은 증거로 받지 않습니다** — 그건 5단계 케이스 스크립트 경로입니다(서버가 실행 코드 배포처가 되지 않게).
   - 출력 JSON 의 **`artifacts`**(서버가 가진 메타 전체 `{name, kind, bytes, sha256}`)를 payload 에 그대로 싣습니다(§0.3). 함께 오는 `uploaded`(이번에 올린 것) · `rejected`(서버가 거부) · `skipped`(단말에서 제외 — 이름·확장자·크기) · `scanned`(훑은 하위 폴더와 항목 수, 없으면 `missing:true`)로 무엇이 왜 안 갔는지 드러납니다.
   - `--dir` 경로 자체가 없으면 **즉시 실패**합니다(오타를 "올릴 것 없음"의 성공으로 넘기지 않습니다).
   - 같은 이름의 다른 파일은 **409 로 거부**됩니다(조용히 덮어쓰지 않음) — `shots/` 와 `diagnostics/` 에 같은 파일명을 두지 마세요. 30개·50MB 는 **작업 누적**이라 재검증 회차가 쌓이면 뒤에서 걸립니다. 걸린 지점이 `rejected` 에 남으니 계속 밀어붙이지 말고 그대로 리포트에 옮깁니다.
   - **실패·미실행은 조용히 넘기지 않습니다** — `ok:false` 이거나 `rejected`·`skipped` 가 비어 있지 않으면 두 자리에 남깁니다: ① 리포트 본문에 **"증거 업로드 미실행(사유)"** 한 줄(사람이 읽는 자리) ② payload 에 `artifacts_error` 문자열(기계가 읽는 자리). 케이스 동기 실패를 "케이스 동기 미실행"으로 남기는 규약과 같은 모양입니다 — 2026-07-29 #783 에서 그 표기가 "왜 근거가 없나"를 즉시 가른 결정적 단서였습니다(표기가 없었으면 검증이 부실했던 것과 도구가 실패한 것을 구분할 수 없었습니다).
7. **보고**: 리포트는 §0.5 리포트 표준을 따릅니다. **claim 이 배달한 다음 단계로 보고합니다** — `stage.reportable_next` 에 있는 status 중 하나를 고릅니다. 어휘 검증은 서버 몫이라(정의 밖 status·부적법 전이는 400) 이 스킬은 어휘를 갖지 않습니다.
   ```shell
   node queue.js report <id> --status=<stage.reportable_next 중 하나> \
        --summary="..." --doc=<리포트.md> --payload=<payload.json>
   ```
   - **`reportable_next` 가 1개면 갈래가 없습니다** — 검증 결과와 무관하게 그 단계로 전진하고, 결함은 리포트와 `payload.findings` 에 적어 다음 단계가 읽게 합니다. **테스터가 판정하지 않습니다.** `frame9_bnd` 의 `verify`(스킬 `frame9bnd-step06-verify-cdp`, `exits: forward` → `inspection`)가 이 모양입니다.
   - **`reportable_next` 가 2개면 그 정의가 분기를 가진 것**이고, 그때만 PASS/FAIL 로 갈래를 고릅니다. dev 가 이 모양입니다 — PASS → `inspect`(마감, 별도 담당), FAIL → `plan`(롤백 — 구현자 EXECUTOR 가 다시 집습니다). 실패 근거를 `payload.findings` 에 담습니다.
   - `--stage`(출발 단계)는 생략하면 `queue.js` 가 서버에서 이 카드의 현재 단계를 읽어 실행 대장에 정확히 남깁니다. 직접 넘길 때는 claim 이 준 `stage.status` 를 그대로 씁니다.
8. **판단 필요(사양이냐 버그냐)** → `node queue.js question <id> --text="..."` 로 사람에게 묻고(waiting) tick 을 종료합니다. 운영자가 웹에서 답하면 다음 claim 때 그 답이 실려 재개됩니다.

케이스 명령(`case-sync.py`)은 파이썬으로 어디서든 돕니다 — 윈도우 세션이면 `python`(또는 `py -3`), WSL 이면 `python3`. 케이스 동기가 실패해도(서버 미배포·토큰 문제) **화면검증 자체는 진행**하되, 실패를 리포트에 "케이스 동기 미실행"으로 명시합니다(조용히 넘기지 않음).

### 0.3 결과 슬롯 — `payload[<출발 단계>]`

report 의 `--payload` 는 아래 구조(JSON)로, 서버가 **그 카드의 출발 단계 키**에 저장합니다 — dev `test` 단계면 `task.payload['test']`, `frame9_bnd` `verify` 단계면 `task.payload['verify']`. 슬롯 키는 서버가 정하므로(클라이언트가 지정하지 않습니다) 보고만 하면 맞는 자리에 앉습니다. 웹 칸반·매뉴얼 작성이 이걸 읽습니다:

```jsonc
{
  "verdict": "PASS | FAIL | BLOCKED",
  "tested_url": "https://.../board",          // 실제로 연 주소
  "build_sha": "97b43af2",                     // /api/version 등에서 확인한 대상 빌드(있으면)
  "scenarios": [{ "id": "S-1", "name": "...", "result": "PASS", "note": "" }],
  "findings":  [{ "severity": "P0|P1|P2|P3", "summary": "...", "evidence": "cases/<host>/<feature>/<slug>/shots/01.jpg" }],
  "console_errors": [], "network_failures": [],
  "screenshots": ["cases/<host>/<feature>/<slug>/shots/01.jpg"],
  "scripts":     ["cases/<host>/<feature>/<slug>/case.md"],   // 실행 시퀀스가 든 케이스(매뉴얼 재사용)
  "report_path": "cases/<host>/<feature>/<slug>/report.md",
  "cases": [{ "host": "localhost-5151", "feature": "forge", "name": "chat-panel-send" }],  // 이번에 기록·push 한 케이스 키
  // 서버에 올린 증거 파일(§0.2 6단계) — queue.js artifacts 출력의 artifacts 를 그대로.
  // 손으로 적지 않습니다: bytes·sha256 의 진실은 서버이고, 이 목록이 웹 열람의 원천입니다.
  "artifacts": [{ "name": "01.jpg", "kind": "shot", "bytes": 184320, "sha256": "…" }],
  "artifacts_error": "shots/big.jpg 413(5MB 초과) — 2건 미업로드"   // 업로드 실패·미실행 시에만
}
```

**`verdict` 는 갈래가 있는 정의에서만 판정입니다.** 정의가 분기를 가지면(`reportable_next` 2개 — dev) `verdict` 가 PASS/FAIL 갈래를 고른 근거입니다. 갈래가 없으면(`exits: forward` — `frame9_bnd` 의 `verify`) **테스터는 판정하지 않으므로** `verdict` 는 전이를 바꾸지 않는 결과 요약 표시일 뿐입니다. 그 경우에도 결함은 `findings` 에 심각도와 함께 남겨 다음 단계(인스팩션)가 읽게 합니다. "사양이냐 버그냐"처럼 판단이 필요하면 판정하지 말고 §0.2 8단계(질문)로 사람에게 넘깁니다.

기존 필드 구조는 불변이고 `cases`(케이스 키)·`artifacts`(증거 메타)가 추가입니다. 파일이 **어디로 가는지는 셋으로 갈립니다** — 같은 케이스 폴더에 있어도 사는 곳이 다릅니다:

| 파일 | 가는 곳 | 올리는 명령 | payload |
|---|---|---|---|
| `case.md` + 최상위 스크립트(`.js`·`.py`·…) | 케이스 저장소(DB) — 케이스와 함께 살고 죽습니다 | `case-sync.py push` (§0.2 5단계) | `cases`(케이스 키) |
| `shots/`·`diagnostics/` 의 캡처·raw 진단 | 작업 증거(서버 디스크) — 그 회차 기록 | `queue.js artifacts` (§0.2 6단계) | `artifacts`(메타 4키) |
| 그 밖의 로컬 파일 | 단말에만 남습니다 | (없음) | 경로 문자열뿐 |

- `screenshots`·`scripts`·`report_path` 는 종전대로 **경로 문자열**입니다(로컬 위치 표시). 웹에서 실제로 열리는 것은 `artifacts` 뿐이라, 플래너가 봐야 할 캡처는 반드시 6단계로 올립니다.
- **`artifacts` 의 주인은 서버입니다** — 업로드 라우트가 유일한 작성자라, 보고에 실어 보낸 값은 서버가 자기 기록(업로드 때 잰 `bytes`·`sha256`)으로 갈아끼웁니다. 손으로 적거나 고쳐도 반영되지 않으니 6단계 출력의 `artifacts` 를 그대로 복사만 합니다.
- `findings[].evidence` 의 파일명은 올린 증거 이름과 **같게** 씁니다(`…/shots/01.jpg` ↔ `01.jpg`) — 웹 검증 결과 뷰가 이름이 일치하는 결함 옆에 열람 링크를 답니다. 이름이 어긋나면 링크가 안 붙습니다.

케이스 **본문·스크립트**는 `case-sync.py push` 로 서버에 축적되어 다른 단말이 pull 로 받습니다(`unskein-case` 스킬).

### 0.4 연속 운용 (CronCreate)

한 tick 은 1건만 처리합니다. 연속 감시는 클로드 세션이 폴링하거나 CronCreate 로 주기 재구동합니다(예: `*/5`). 매 tick 은 claim → (있으면) 검증·보고 → 종료. 중복 선점은 서버 SKIP LOCKED·heartbeat 로 막히니 여러 TESTER 를 동시에 돌려도 **큐 측은** 안전합니다 — 단 **CDP 측은 세션별 포트 분리가 전제**(§0.2 4단계·§3 페어링): 포트를 안 나누면 같은 크롬·같은 로그인에 붙습니다.

### 0.5 리포트 표준 — 수정하는 쪽이 결과를 믿고 바로 착수하게

검증 리포트(`--doc`)는 아래 표준을 따릅니다. 리포트의 목적은 "검증했다"가 아니라 **수정하는 쪽(EXECUTOR/다오)이 재분석 없이 바로 고치기 시작하는 것**입니다. (use-browser-kit 운용 100건+에서 실증된 형식의 이식.) 서술 어조·구성은 plugin `docs/보고규칙.md`(사실 먼저·평범한 한국어·현상→원인→해결)를 함께 따릅니다.

**코어 4패턴 — 항상 적용:**

1. **재현 검증**: 같은 화면의 이전 검증(케이스·이전 회 리포트)이 있으면, 이전에 발견된 이슈가 이번에도 재현되는지 **일치 여부 비교표**로 먼저 답합니다 (이슈 | 이전 회 | 이번 회 | 일치/변화). 이전 회가 없으면 "첫 검증"이라고 명시합니다.
2. **재현 vs 신규 분리**: 발견 이슈를 "이전에도 있던 것(재현)"과 "이번에 새로 발견(신규)" **두 섹션으로 분리**합니다 — 섞으면 수정하는 쪽이 무엇이 자기 변경의 회귀인지 못 가립니다.
3. **raw 진단 데이터는 본문 밖**: 콘솔 로그 전문·네트워크 덤프·collect JSON 은 케이스 폴더 `diagnostics/` 에 파일로 두고, 본문에는 **결론과 요지만** 씁니다(파일 경로 병기). 리포트가 로그 덤프에 파묻히면 아무도 안 읽습니다. **본문 밖은 보관 금지가 아닙니다** — 그 파일들은 §0.2 6단계로 작업에 첨부해 올립니다. 인라인하지 않으면서 근거는 남습니다.
4. **P0~P3 우선순위 + 한 줄 권장 액션**: 모든 발견 이슈에 심각도(P0 즉시 / P1 이번에 / P2 다음에 / P3 기록만)와 **한 줄 권장 액션**("~를 ~로 고치면 될 것")을 답니다.

**조건부 — 환경이 닿을 때만:**

- 재현 SQL/curl 인라인: 이슈를 그대로 재현하는 한 줄 명령을 본문에 넣습니다(수정자가 복붙 재현).
- DB 컬럼값 통째 인용: 데이터 기인 이슈면 해당 행·컬럼 값을 그대로 인용합니다(추정 대신 실측).

**메타 노하우:**

- **콘솔 에러 문구가 이전 회와 한 글자도 안 바뀌었으면 "수정본 미배포"를 1순위로 의심**합니다 — 같은 status code + 같은 문구 + 같은 요청 수면 거의 확정입니다. 코드를 다시 파기 전에 배포 SHA(`/api/version` ↔ 기대 커밋)부터 대조하고, 그 판정을 리포트 맨 앞에 씁니다.

### 0.6 표준 뷰포트 — 판정의 기준선

화면 크기는 **결론을 바꿉니다.** 잘려서 안 보이는 것과 원래 없는 것이 같은 모습이라, 크기가 흔들리면 "버튼이 없다"가 결함인지 환경인지 영영 못 가립니다. 그래서 **크기를 검증마다 고정**합니다.

| 구분 | 크기 | 언제 |
|---|---|---|
| **기본** | **1920×1080** | **모든 검증**. 결함/정상 판정은 이 크기에서만 내린다 |
| 보조 | 1366×768 | 레이아웃·잘림이 쟁점인 검증에만 **추가로** 한 번 더 |

- **창 최대화는 기준이 아닙니다.** 모니터·작업표시줄·주소창에 먹혀 단말마다 1920×945·2560×1300 으로 제각각이 됩니다(2026-07-29 실측: 최대화했는데 945 였고, 캔버스 아래쪽이 잘려 "스크롤이 안 된다"와 "버튼이 없다"를 구분해 적어야 했다). `remote.js viewport` 는 **창이 아니라 페이지 뷰포트**를 잡아 물리 모니터보다 큰 값도 확보합니다 — 노트북 단말에서도 기준 크기가 그대로 나옵니다.
- **적용 시점은 화면 진입 직후**(§0.2 4단계). 수집·캡처·클릭 좌표가 전부 이 크기 위에서 나와야 합니다.
- **결과에 실제 값을 적습니다** — `payload.viewport`(예 `1920x1080`)와 케이스 본문 양쪽. 지정값이 아니라 `remote.js viewport` 가 되읽어준 값을 적습니다(적용 실패를 숨기지 않습니다).
- **보조 크기로도 봤으면 두 결과를 나눠 적습니다** — "1920 에서는 보이고 1366 에서는 잘림"처럼. 섞어 적으면 다음 사람이 어느 쪽 이야기인지 모릅니다.
- 카드가 다른 크기를 명시하면 그것을 따르고, 그 사실을 리포트에 적습니다(등록 측 규약은 `unskein-wbs` §4.6).

### 0.7 캡처 형식 — 기본 JPEG 품질 80

증거는 서버 디스크에 회차마다 쌓이고 **용량이 곧 비용**이라, 오래된 회차를 지우는 회차 롤링과 같은 목적으로 **한 장의 무게를 줄입니다.**

| 구분 | 형식 | 언제 |
|---|---|---|
| **기본** | **JPEG 품질 80**(`.jpg`) | **모든 캡처.** `remote.js shot <name>` 이 그대로 찍습니다 |
| 예외 | PNG(`.png`) | **텍스트 판독이 쟁점**일 때만 — `--png` 또는 이름을 `.png` 로 |

- **해상도는 줄이지 않습니다.** 판정 기준선이 1920 뷰포트(§0.6)라 축소하면 "잘려서 안 보인다"와 "원래 없다"를 다시 못 가릅니다. 줄이는 것은 압축률이지 크기가 아닙니다.
- PNG 는 압축 잡티가 글자를 흐리지 않아야 하는 캡처(에러 문구·좁은 컬럼의 값·폰트 렌더 결함)에만 씁니다. 레이아웃·존재 확인은 JPEG 로 충분합니다.
- WebP 는 쓰지 않습니다 — Playwright 가 못 찍고 서버 변환은 새 의존성을 부릅니다.
- **`.jpeg` 로는 찍지 않습니다** — 서버 증거 허용 확장자가 `.jpg` 뿐이라 `remote.js shot` 이 `.jpeg` 이름을 거부합니다(찍어두면 업로드에서 빠져 증거가 단말에만 남습니다).
- **이전 케이스에서 이어받은 `.png` 이름은 의도한 예외가 아닙니다.** 2026-07-31 이전에 쌓인 케이스는 실행 시퀀스가 `shot NFL100.png` 처럼 적혀 있고, 이름에 `.png` 가 있으면 지금도 PNG 로 찍힙니다(예외 규칙이 그대로 걸립니다). 케이스를 재사용할 때 그 이름이 **텍스트 판독 때문에 PNG 인 것이 아니면 `.jpg` 로 바꾸고 케이스 본문도 함께 고칩니다** — 안 고치면 옛 케이스만 계속 PNG 로 돌아 이 정책이 비켜 갑니다. 케이스 본문이 가리키는 `shots/…png` 경로도 새로 찍은 파일 이름(`.jpg`)과 맞춰 둡니다(경로가 어긋나면 다음 검증자가 없는 파일을 찾습니다).
- `shot` 출력에 **실제 파일 크기**가 함께 나옵니다 — 한도(파일당 5MB·작업당 50MB, §0.2 6단계)에 언제 닿는지 보면서 진행합니다.

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
| `shot <name> [--full] [--png]` | 스크린샷을 `scripts/shots/<name>.jpg` 에 저장(기본 JPEG 품질 80 — §0.7). `--full` 은 전체 페이지. `--png`(또는 이름을 `.png` 로) 면 무손실 PNG. 저장 후 실제 파일 크기를 함께 출력합니다. |
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
