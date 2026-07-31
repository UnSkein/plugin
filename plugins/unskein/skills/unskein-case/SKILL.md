---
name: unskein-case
description: TESTER 검증 케이스(노하우)를 UnSkein 서버와 동기한다 — push(내 케이스 업로드)/pull(내 것 전부 + 같은 비즈니스의 public 케이스 내려받기). 검증 시퀀스·셀렉터·함정을 축적해 같은 화면 재검증을 수 분 내로 만든다. 트리거 — 케이스 풀, 케이스 푸시, 케이스 동기, 검증 노하우 동기, 검증 케이스 저장, 케이스 내려받기, case pull, case push, case sync, 케이스 저장소.
---

# UnSkein — 검증 케이스 동기 (TESTER 케이스 저장소)

화면검증에서 얻은 노하우(케이스)를 서버에 축적해 사용자·단말 간 재사용합니다. 케이스는 **본문(마크다운) + 재사용 스크립트**가 서버에 저장되고, 스크린샷·raw 진단 같은 증거 파일은 로컬에 남습니다. 키 = 사용자 × 비즈니스 × 호스트 × 기능 × 이름.

`unskein-test`(화면검증)가 tick 안에서 이 스킬의 CLI 를 자동 호출합니다(검증 전 pull → 검증 후 push). 이 문서는 수동 실행과 규약의 단일 출처입니다.

## 1. 명령

CLI: `${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py` (파이썬 stdlib 전용 — WSL `python3`, 윈도우 `python`).

```shell
# 내려받기: 내 케이스 전부 + 같은 비즈니스의 (해당 호스트) public 케이스
# (본문 + 재사용 스크립트 — 스크립트는 실행 가능한 상태로 케이스 폴더에 떨어집니다)
python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py pull --business <이름|id> [--host localhost-5151]

# 올리기: 로컬 케이스(본문 + 폴더 최상위 스크립트)를 서버에 upsert (무변경은 skip — 멱등)
python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py push --business <이름|id> [--host localhost-5151] [--dry-run]

# 호스트 슬러그 파생 (규칙 단일 출처 — 손으로 만들지 말 것)
python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py slug http://localhost:5151/board   # → localhost-5151

# 오프라인 자체 테스트 (서버 불요)
python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py selftest
```

- `--business` 생략 시 `UNSKEIN_BUSINESS_ID` → `UNSKEIN_BUSINESS`(이름) 순으로 읽습니다.
- **이름→id 해석은 planner 토큰 전용**입니다(kind 격리). tester/mori 토큰으로 돌릴 때는 숫자 id(`--business 14`) 또는 `UNSKEIN_BUSINESS_ID` 를 쓰세요 — 이름을 주면 401 로 명확히 멈춥니다(조용한 우회 없음).

## 2. 환경변수 (executor.env / planner.env 공용)

| 변수 | 용도 |
|------|------|
| `UNSKEIN_API_BASE` 또는 `UNSKEIN_API` | 서버 베이스 URL (필수) |
| `UNSKEIN_PLANNER_TOKEN` | planner 토큰 → `X-Planner-Token` |
| `UNSKEIN_MORI_TOKEN` | EXECUTOR/TESTER 토큰 → `X-Mori-Token` (둘 중 있는 것 사용) |
| `UNSKEIN_BUSINESS_ID` | (선택) business id 직접 지정 — 이름 해석 생략 |
| `UNSKEIN_BUSINESS` | (선택) 비즈니스 이름 — planner 토큰일 때만 해석 가능 |
| `UNSKEIN_HOME` | (선택) 상태 루트 — 케이스는 `$UNSKEIN_HOME/cases` (미설정 시 `~/.unskein/cases`) |

어느 kind 토큰이든 **같은 사용자로 인가**됩니다(서버가 소유자를 인증에서 취함 — 바디 위조 불가). 토큰 값은 화면에 출력하지 않습니다.

## 3. 로컬 레이아웃

```
$UNSKEIN_HOME/cases/
  INDEX.md                                  ← pull 이 재생성(기계 생성 — 직접 편집 금지)
  <host>/<feature>/<slug>/case.md           ← 내 케이스 본문 (push 대상)
  <host>/<feature>/<slug>/scan-formdef.js   ← 재사용 스크립트 (push 대상 — 최상위만)
  <host>/<feature>/<slug>/shots/…           ← 스크린샷 (케이스 저장소 미전송)
  <host>/<feature>/<slug>/diagnostics/…     ← raw 진단 데이터 (케이스 저장소 미전송)
  _public/<작성자>/<host>/<feature>/<slug>/case.md   ← 남의 public — 읽기 전용
```

- **케이스 폴더 최상위의 스크립트는 전부 올라갑니다.** public 케이스면 비즈니스 멤버 전체가 봅니다 — **안 올릴 파일은 하위 폴더로** 옮기세요(`shots/`·`diagnostics/` 등 하위는 수집 대상이 아닙니다).
- `shots/`·`diagnostics/` 는 **케이스가 아니라 그 회차 작업에 귀속**하는 증거라 다른 경로로 갑니다 — `unskein-test` §0.2 6단계가 `queue.js artifacts` 로 작업에 첨부합니다(케이스를 갱신해도 옛 회차 증거가 딸려 지워지지 않게 수명을 갈라 둡니다).
- **`_public/` 은 push 에서 제외**됩니다(읽기 전용). 남의 케이스를 수정하려면 내 자리(`<host>/<feature>/<새슬러그>/`)로 복제해 내 케이스로 만드세요.
- `INDEX.md` 는 pull 이 **로컬 파일들로부터 재생성**합니다 — 원격 blob 통째 sync 가 아니라 충돌이 없습니다.
- pull 은 서버 진실을 실체화합니다 — 로컬에서 고친 케이스는 **push 먼저, 그다음 pull**(순서가 바뀌면 로컬 수정이 서버본으로 덮입니다).

## 4. 케이스 파일 규약

frontmatter 의 `host`/`feature`/`name` 은 **디렉토리 경로와 일치**해야 합니다(불일치는 push 에서 제외되고 오류로 표시). 템플릿: [references/case-template.md](references/case-template.md).

```markdown
---
host: localhost-5151          # case-sync.py slug <url> 로 파생한 값
feature: forge
name: chat-panel-send         # = 디렉토리 슬러그
title: 포지 채팅 패널 전송 검증
status: success               # success | partial | failed
tags: [chat, sse]
visibility: public            # 최초 push 기본 public — private 전환은 웹 UI에서 선별
task_id: 1234                 # (선택) 원 검증 작업
tested_url: http://localhost:5151/forge   # (선택)
---

## 의뢰서 (Why) …
## 실행 시퀀스 (How) …
## 결과 (What) …
## 함정 (Pitfalls) …
## 다음 사용자에게 (Tips) …
```

**본문에 계정·비밀번호·토큰 금지(비밀 무잔존)** — 서버는 저장만 하고 거르지 않으므로 작성 규약이 1차 방어입니다. 최초 push 는 public 이 기본이라 비즈니스 멤버 전체가 봅니다.

## 4.1 재사용 스크립트 규약

다음 검증자가 그대로 돌릴 수 있는 스크립트를 케이스 폴더 **최상위**에 두면 케이스와 함께 저장·배포됩니다(스콥 `tester-artifact-store` §3). 스크립트는 케이스와 같은 단위로 살고 죽습니다 — 케이스를 지우면 함께 사라지고, pull 때 함께 옵니다.

| 규칙 | 값 |
|------|-----|
| 확장자 | `.js` · `.mjs` · `.py` · `.ps1` · `.sh` (그 외는 수집 대상 아님) |
| 이름 | `^[A-Za-z0-9._-]{1,64}$` — 경로 구분자·상위 참조(`..`)·한글 불가 |
| 개수 | 케이스당 10개 |
| 용량 | 케이스당 총 256KB(개행 정규화 후) |

- **한도·이름 위반은 그 케이스가 push 에서 통째로 제외**되고 사유가 stderr 에 뜹니다(조용히 잘라내지 않습니다). 종료코드 1.
- **비밀은 서버가 1차로 막습니다** — `ghp_`·`sk-`·`Bearer <긴토큰>`·`password = "…"` 형태가 있으면 422 로 되돌아옵니다(어느 파일 몇 번째 줄인지만 알려주고 값은 표시하지 않습니다). 자격은 하드코딩하지 말고 환경변수로 받으세요.
- CRLF 는 자동 정규화됩니다 — 윈도우에서 만든 `.ps1`·`.js` 도 무변경 재push 가 no-op 입니다.

## 5. 서버 API (참고 — 6.1 backend)

`POST /api/cases/push`(upsert, content_hash 동일 skip · 응답 `{upserted, skipped, scripts_upserted}`) · `GET /api/cases/pull?business_id=&host=`(내 것 전부 + public, 본문·스크립트 포함) · `GET /api/cases`(목록 메타 — 스크립트는 `script_count` 개수만) · visibility 전환/삭제는 웹 UI(소유자만). 인가는 어느 kind 토큰이든 같은 사용자(`get_memory_principal` 계열).

스크립트를 실어 보냈는데 응답에 `scripts_upserted` 가 없으면 **스크립트를 모르는 구버전 서버**라 CLI 가 멈춥니다 — 구서버는 모르는 필드를 조용히 버리므로 "올렸다고 믿는 실패"가 생기기 때문입니다.

## 6. 동기 의미론 (수정 라운드 1 — #563)

- **visibility 의 소유는 서버(웹 선별)다.** push 는 기존 케이스의 visibility 를 덮지 않고(서버가 보장), pull 은 서버 컬럼값을 로컬 frontmatter 에 병합한다 — 웹에서 private 전환하면 본문이 안 바뀌었어도 재pull 이 로컬 `visibility:` 줄을 고친다.
- **대량 push 는 자동 청크**(기본 50건/POST, `--chunk N`) — 단일 POST 는 서버 본문 한도(413)에 걸린다. 청크는 멱등이라 중간 실패 후 재실행이 안전하다. 스크립트가 실리면 **건수와 본문 바이트(약 1MB) 중 먼저 닿는 쪽**에서 끊는다(케이스당 최대 256KB × 50건이면 건수 청크만으로는 413 이 재발한다).
- **스크립트는 케이스와 함께 산다.** 케이스를 지우면 스크립트도 사라지고, pull 은 본문 변경 여부와 무관하게 스크립트를 내려놓는다(본문이 그대로인 케이스도 스크립트는 갱신된다).
- **pull 은 덮어쓰되 지우지 않는다.** 서버에서 사라진 스크립트를 로컬에서 지우지는 않는다 — 작업 중인 파일을 없앨 수 있기 때문이다. 대신 오래된 단말의 다음 push 로 되살아날 수 있으니, 폐기한 스크립트는 로컬에서도 직접 지운다.
- **받은 스크립트는 바로 실행 가능**하다(POSIX 에서 `.sh`·`.py` 는 실행 권한까지 붙는다). 이름 규칙에 어긋난 항목은 저장하지 않고 사유를 stderr 에 남기며 종료코드 1 이다 — 파일명이 곧 로컬 쓰기 경로라 서버 검증을 믿지 않고 단말에서 다시 막는다.
- **UTF-8 BOM 붙은 case.md 도 정상 처리**된다(규약 위반 아님). 윈도우 콘솔(cp949)에서도 출력이 깨지지 않는다(스크립트가 stdout 을 UTF-8 로 재구성).
