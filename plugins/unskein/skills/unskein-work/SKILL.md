---
name: unskein-work
description: 익스큐터의 현재 Claude Code 세션이 헤드리스 `claude -p`(자식 다오)를 띄우지 않고 스스로 다오가 되어 UnSkein 큐의 작업 한 건을 직접 처리한다 — claim → (이식된 다오 스킬로) 구현·검증·PR → 회수. 운영자가 지켜보며 조종할 수 있어 화면검증·첫 케이스·헤드리스가 반복 실패하는 작업에 쓴다("셸 말고 함께" 모드). 트리거 — 함께 작업, 세션에서 직접 처리, in-session 다오, 헤드리스 말고, unskein-work, work.py prepare, claim 해서 이 세션이 처리, 운영자가 보며 진행.
---

# UnSkein — 함께 작업 (in-session 다오)

`/unskein:run`·`/unskein:watch` 는 claim 한 작업을 **헤드리스 `claude -p`(자식 다오)** 로 처리한다. 이 스킬은 그 자식을 띄우지 않고, **익스큐터의 이 Claude Code 세션이 스스로 다오가 되어** 같은 작업 폴더에서 이식된 다오 스킬을 따라 구현→보고한다.

- **언제**: 운영자가 **지켜보며 조종**해야 하는 작업 — 화면검증이 얽힌 것, 첫 케이스, 헤드리스가 반복 실패해 원인을 봐야 하는 것. 자율 대량 처리는 `watch` 가 맡는다.
- **어디서**: **익스큐터 distro 안**의 세션에서 쓴다(planner/운영 세션이 아니라). `run`/`watch` 와 같은 executor.env(모리 토큰·git 인증)를 쓴다.
- **불변식**: 헤드리스 실행(`run_dao`)만 세션이 대체하고 나머지 배관(claim·스킬 이식·clone·프롬프트·마커·전이·report·heartbeat)은 `run_once` 를 그대로 재사용한다 → **서버·전이·마커 규약은 run/watch 와 100% 동일**하다.

스크립트: `${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py`.

## 0. 전제 — 연결·인증

`run`/`watch` 와 같다. 먼저 executor.env 를 source 해 모리 토큰·git 인증·`UNSKEIN_API` 를 셸에 올린다(비밀 무잔존 — 화면 출력 금지). 연결·셋업은 `unskein-setup`.

```bash
source "$UNSKEIN_HOME/executor.env"   # 기본 ~/.unskein/executor.env (프로젝트 격리면 그 경로)
```

- 토큰은 **kind=mori(EXECUTOR)** — `plan`/`exec`/`inspect` 단계를 집는다(`test` 화면검증은 `unskein-test`/kind=tester 담당).
- `prepare` 가 시작 전 **preflight** 로 클라이언트 준비(다오 스킬 원본·런타임·서버 도달)를 점검해, 미충족이면 큐를 건드리기 전에 멈춘다.

## 1. 한 건 처리 — prepare → (세션이 다오로 수행) → report

### 1.1 선점 + 셋업

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" prepare bis "비즈니스이름" prj "프로젝트이름"
```

- watch 대상(`bis`/`prj`)은 `run`/`watch` 와 같은 규칙(인자 > 환경변수). 미지정 + 원격 서버는 거부되니 범위를 지정해 **단독 소유**한다.
- `prepare` 가 하는 일: 대상·preflight 점검 → **claim 1건** → repo clone·최신화 → **다오 스킬 이식**(작업폴더에 `CLAUDE.md` + `.claude/skills/`) → 이번 단계 **프롬프트 산출** → **백그라운드 heartbeat 데몬 기동**(세션이 오래 작업해도 claim lease 가 안 풀리게).
- 출력: `TASK_ID=..`, `STATUS=..`, `WORK_DIR=..`(작업할 repo 폴더), 그리고 `===== DAO PROMPT =====` 블록.
- `NO_TASK` 면 대기 작업이 없다 — 종료. 셋업 실패(repo 미등록·인증 누락·plan_doc 빈값 등)는 `prepare` 가 **QUESTION 으로 회수**하고 멈춘다(fallback 금지).

### 1.2 이 세션이 다오로서 수행

`WORK_DIR` 로 들어가, 그 상위에 이식된 **다오 스킬을 따라** `DAO PROMPT` 를 수행한다:

- 작업폴더 규약: `WORK_DIR/../CLAUDE.md`(다오 정체성·출력 규약·단계 순서·절대 규칙) + `WORK_DIR/../.claude/skills/`(단계 스킬: `unskein-exec`·`unskein-verify`·`unskein-wiki-*`·`unskein-git`). 프롬프트가 지시한 **현재 단계만** 수행한다(`plan`=구현+자체검증 / `inspect`=기록·마감·PR 등).
- clone/pull/checkout 을 직접 하지 않는다 — `prepare` 가 이미 결정적으로 준비했다. `WORK_DIR` 안에서 작업만 한다.
- **git 인증(주의)**: 다오의 push(inspect 단계)는 **이 세션 자신의 git/gh 인증**(executor.env + `gh auth`)을 쓴다 — 헤드리스처럼 scrubbed env 를 주입하지 않는다. master 직접 머지·배포는 하지 않는다(PR 까지 — 머지되면 자동 배포).
- 마치면 **최종 마커 한 개**를 파일로 저장한다(규약: `CLAUDE.md §4.1`):
  - 완료: `RESULT: status=<다음 status> stage=<단계명> summary=<요약>` 첫 줄 + (산출물 있으면) `<<<UNSKEIN_DOC` ~ `UNSKEIN_DOC` 펜스 블록.
  - 막힘: `QUESTION: <질문>` 한 줄. **운영자가 그 자리에서 답할 수 있으면 답을 반영해 계속 진행**하고(대화가 곧 재개), 정말 사람 결정이 필요하면 마커로 저장해 회수한다.

```bash
# 예: 마커를 파일로 저장
cat > /tmp/marker.txt <<'EOF'
RESULT: status=inspect stage=plan summary=X 기능 구현 + 자체검증 통과
<<<UNSKEIN_DOC
## 구현 요약
...
UNSKEIN_DOC
EOF
```

### 1.3 회수

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" report <TASK_ID> --marker-file /tmp/marker.txt
```

- `report` 가 하는 일: 마커 파싱 → **heartbeat 정지** → 규약대로 회수(RESULT=전이 report / QUESTION·UNKNOWN=질문 회수) → `done` 이면 작업폴더 정리.
- 전이는 오직 마커의 `next status` 로만 일어난다(하드코딩 done 금지) — run/watch 와 동일한 서버 게이트.
- 마커를 stdin 으로 넘겨도 된다: `... | python3 .../work.py report <TASK_ID>`.

## 2. 연속 처리 (선택)

한 번에 한 건이다. 여러 건을 이어서 하려면 §1 을 반복한다(`prepare` → 수행 → `report`). `watch` 와 달리 **매 건을 운영자가 보며** 진행한다 — 자율 대량 처리가 목적이면 `watch` 를 쓴다.

## 3. run/watch 와 다른 점 (요약)

| | `run`/`watch` (헤드리스) | `unskein-work` (함께) |
|---|---|---|
| 다오 | 자식 `claude -p` | **이 세션 자신** |
| 관찰·조종 | 불가(RESULT/QUESTION 만 회수) | **운영자가 보며 조종** |
| heartbeat | process_task 스레드 | **`prepare` 가 백그라운드 데몬** |
| 세션 재개(--resume) | 있음(대화턴) | 없음 — 운영자가 그 자리서 이어감 |
| git 인증 | scrubbed env 주입 | 세션 자신의 gh/git 인증 |
| claim·전이·마커·report | ← 동일(run_once 재사용) → | 동일 |

## 4. 중단

작업 중 그만두려면 `python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" release <TASK_ID>` 로 heartbeat 데몬만 멈춘다(보고 안 함 — lease 가 자연 만료되면 재선점 가능). 작업폴더는 보존된다.
