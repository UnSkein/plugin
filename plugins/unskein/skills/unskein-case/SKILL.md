---
name: unskein-case
description: TESTER 검증 케이스(노하우)를 UnSkein 서버와 동기한다 — push(내 케이스 업로드)/pull(내 것 전부 + 같은 비즈니스의 public 케이스 내려받기). 검증 시퀀스·셀렉터·함정을 축적해 같은 화면 재검증을 수 분 내로 만든다. 트리거 — 케이스 풀, 케이스 푸시, 케이스 동기, 검증 노하우 동기, 검증 케이스 저장, 케이스 내려받기, case pull, case push, case sync, 케이스 저장소.
---

# UnSkein — 검증 케이스 동기 (TESTER 케이스 저장소)

화면검증에서 얻은 노하우(케이스)를 서버에 축적해 사용자·단말 간 재사용합니다. 케이스는 **본문(마크다운)만 서버**에 저장되고, 스크린샷 등 파일은 로컬에 남습니다. 키 = 사용자 × 비즈니스 × 호스트 × 기능 × 이름.

`unskein-test`(화면검증)가 tick 안에서 이 스킬의 CLI 를 자동 호출합니다(검증 전 pull → 검증 후 push). 이 문서는 수동 실행과 규약의 단일 출처입니다.

## 1. 명령

CLI: `${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py` (파이썬 stdlib 전용 — WSL `python3`, 윈도우 `python`).

```shell
# 내려받기: 내 케이스 전부 + 같은 비즈니스의 (해당 호스트) public 케이스
python3 ${CLAUDE_PLUGIN_ROOT}/bin/case-sync.py pull --business <이름|id> [--host localhost-5151]

# 올리기: 로컬 케이스들을 서버에 upsert (무변경은 skip — 멱등)
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
  <host>/<feature>/<slug>/case.md           ← 내 케이스 (push 대상 = 이 파일만)
  <host>/<feature>/<slug>/shots/…           ← 스크린샷 (서버 미전송)
  <host>/<feature>/<slug>/diagnostics/…     ← raw 진단 데이터 (서버 미전송)
  _public/<작성자>/<host>/<feature>/<slug>/case.md   ← 남의 public — 읽기 전용
```

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

## 5. 서버 API (참고 — 6.1 backend)

`POST /api/cases/push`(upsert, content_hash 동일 skip) · `GET /api/cases/pull?business_id=&host=`(내 것 전부 + public, 본문 포함) · visibility 전환/삭제는 웹 UI(소유자만). 인가는 어느 kind 토큰이든 같은 사용자(`get_memory_principal` 계열).

## 6. 동기 의미론 (수정 라운드 1 — #563)

- **visibility 의 소유는 서버(웹 선별)다.** push 는 기존 케이스의 visibility 를 덮지 않고(서버가 보장), pull 은 서버 컬럼값을 로컬 frontmatter 에 병합한다 — 웹에서 private 전환하면 본문이 안 바뀌었어도 재pull 이 로컬 `visibility:` 줄을 고친다.
- **대량 push 는 자동 청크**(기본 50건/POST, `--chunk N`) — 단일 POST 는 서버 본문 한도(413)에 걸린다. 청크는 멱등이라 중간 실패 후 재실행이 안전하다.
- **UTF-8 BOM 붙은 case.md 도 정상 처리**된다(규약 위반 아님). 윈도우 콘솔(cp949)에서도 출력이 깨지지 않는다(스크립트가 stdout 을 UTF-8 로 재구성).
