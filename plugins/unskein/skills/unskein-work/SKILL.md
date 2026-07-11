---
name: unskein-work
description: 익스큐터의 현재 Claude Code 세션이 헤드리스 `claude -p`(자식 다오)를 띄우지 않고 스스로 다오가 되어 UnSkein 큐의 작업 한 건을 직접 처리한다 — **수동 진행 모드**. 진행에 방해되는 상태 값(죽은 점유·동결)을 먼저 정리하고, 구현 내용(plan_doc)에 충실하게 수행하며, test 단계는 CDP 화면검증(unskein-test)으로 옮긴다. 운영자가 지켜보며 조종할 수 있어 화면검증·첫 케이스·헤드리스가 반복 실패하는 작업에 쓴다("셸 말고 함께" 모드). 트리거 — 함께 작업, 수동 진행, 세션에서 직접 처리, in-session 다오, 헤드리스 말고, unskein-work, work.py prepare, claim 해서 이 세션이 처리, 운영자가 보며 진행, 특정 작업 직접 처리.
---

# UnSkein — 함께 작업 (in-session 다오 · 수동 진행)

`/unskein:run`·`/unskein:watch` 는 claim 한 작업을 **헤드리스 `claude -p`(자식 다오)** 로 처리한다. 이 스킬은 그 자식을 띄우지 않고, **익스큐터의 이 Claude Code 세션이 스스로 다오가 되어** 같은 작업 폴더에서 이식된 다오 스킬을 따라 구현→보고한다.

- **언제**: 운영자가 **지켜보며 조종**해야 하는 작업 — 화면검증이 얽힌 것, 첫 케이스, 헤드리스가 반복 실패해 원인을 봐야 하는 것. 자율 대량 처리는 `watch` 가 맡는다.
- **어디서**: **익스큐터 distro 안**의 세션에서 쓴다(planner/운영 세션이 아니라). `run`/`watch` 와 같은 executor.env(모리 토큰·git 인증)를 쓴다.
- **불변식**: 헤드리스 실행(`run_dao`)만 세션이 대체하고 나머지 배관(claim·스킬 이식·clone·프롬프트·마커·전이·report·heartbeat)은 `run_once` 를 그대로 재사용한다 → **서버·전이·마커 규약은 run/watch 와 100% 동일**하다.

스크립트: `${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py`.

## 수동 진행 원칙

이 스킬은 **수동 진행**이다 — 자율 루프(run/watch)의 큐 규칙(선점 경쟁·스테이지 게이트·watch 범위)은 워커 여럿이 안 부딪히기 위한 장치이지, 운영자가 보며 진행하는 수동 작업의 목적이 아니다. 수동에서는:

1. **대상을 정한다** — 처리할 작업이 정해져 있으면 `prepare task <id>` 로 그 작업(서브트리)만 집는다. 큐 순서를 기다리지 않는다.
2. **방해되는 상태 값을 먼저 정리한다** — 선점이 안 되면 아래 §0.5 로 원인 값(죽은 점유·동결·waiting)을 확인해 풀고 다시 집는다. 프로세스가 막았다고 작업을 포기하지 않는다.
3. **구현 내용에 충실한다** — 확인할 것(plan_doc 수용 기준, 이전 단계 산출물 `result_doc`·`payload['test']` FAIL 근거, `subtree`)을 확인하고, 그 내용대로 수행한다. 나머지 배관(전이·마커)은 work.py 가 처리한다.
4. **test 단계는 CDP 검증으로 옮긴다** — 수동 prepare 는 `test` 카드도 집는다(항상). 코드검증이 아니라 **CDP 화면검증(`unskein-test`)을 활성화**해 실제 화면을 확인하고, PASS→`inspect` / FAIL→`plan` 으로 옮긴다(§1.2).

## 0. 전제 — 연결·인증

`run`/`watch` 와 같다. 먼저 executor.env 를 source 해 모리 토큰·git 인증·`UNSKEIN_API` 를 셸에 올린다(비밀 무잔존 — 화면 출력 금지). 연결·셋업은 `unskein-setup`.

```bash
source "$UNSKEIN_HOME/executor.env"   # 기본 ~/.unskein/executor.env (프로젝트 격리면 그 경로)
```

- 토큰은 **kind=mori(EXECUTOR)** — 자율 루프에선 `plan`/`exec`/`inspect` 만 집지만, **수동 prepare 는 `test` 도 집는다**(항상 auto_advance_test). 자율 TESTER 루프(kind=tester·연속 감시)는 여전히 `unskein-test` §0 담당이고, 수동에서 잡힌 test 는 이 세션이 CDP 검증으로 처리한다.
- `prepare` 가 시작 전 **preflight** 로 클라이언트 준비(다오 스킬 원본·런타임·서버 도달)를 점검해, 미충족이면 큐를 건드리기 전에 멈춘다.

### 0.5 막힘 정리 — 진행에 방해되는 상태 값

`prepare` 가 `NO_TASK` 인데 대상 작업이 분명 있으면, 큐 프로세스의 상태 값이 막고 있는 것이다. **mori 토큰으로 확인·정리**하고 다시 집는다(절차 상세는 `unskein-lock` 스킬):

```bash
# 1) 무엇이 막는지 확인 (토큰 값 출력 금지)
curl -s -H "X-Mori-Token: $UNSKEIN_MORI_TOKEN" "$UNSKEIN_API/api/mori/tasks/<id>"
```

| 막는 값 | 의미 | 정리 |
|---------|------|------|
| `claimed_by` + `heartbeat_fresh=true` | **진행 중일 수 있음** — 다른 워커가 살아 있다 | 정말 죽었는지 확인 후에만 release(이중 작업 방지) |
| `claimed_by` + heartbeat 끊김 | 죽은 점유(중단된 워커 잔재) | `POST /api/mori/tasks/<id>/release` — 즉시 해제(180s 안 기다림) |
| `locked_by` | 수동 동결(사람이 걸어둠) | 건 사람 확인 후 release(동결 해제 겸함) |
| `status=waiting` | 다오 질문에 답변 대기 — **시스템 전용 상태** | 웹/보드에서 답변 → `answered` 가 되면 prepare 가 집는다(직접 PATCH 금지) |
| `status=backlog` | 실행대기 승격 전 | 보드/플래너에서 `plan` 으로 올린다(plan_doc 필수) |

release 는 점유·동결 깃발만 비우고 **status 는 보존**한다 — 작업 내용·단계는 안 건드린다.

## 1. 한 건 처리 — prepare → (세션이 다오로 수행) → report

### 1.1 선점 + 셋업

```bash
# 특정 작업을 정해 진행(수동 기본 — 큐 순서 무관)
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" prepare task <id>

# 또는 범위에서 다음 1건
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" prepare bis "비즈니스이름" prj "프로젝트이름"
```

- **`task <id>`** 로 처리할 작업(과 그 서브트리)만 집는다 — 보드 상세패널 "복사"가 주는 `task_id=<숫자>` 값. 수동 진행의 기본형이다.
- watch 대상(`bis`/`prj`)은 `run`/`watch` 와 같은 규칙(인자 > 환경변수). 미지정 + 원격 서버는 거부되니 범위를 지정해 **단독 소유**한다.
- `prepare` 가 하는 일: 대상·preflight 점검 → **claim 1건**(수동이라 `test` 포함 전 단계) → repo clone·최신화 → **다오 스킬 이식**(작업폴더에 `CLAUDE.md` + `.claude/skills/`) → 이번 단계 **프롬프트 산출** → **백그라운드 heartbeat 데몬 기동**(세션이 오래 작업해도 claim lease 가 안 풀리게).
- 출력: `TASK_ID=..`, `STATUS=..`, `WORK_DIR=..`(작업할 repo 폴더), 그리고 `===== DAO PROMPT =====` 블록.
- `NO_TASK` 인데 대상 작업이 분명 있으면 → **§0.5 막힘 정리**(죽은 점유·동결·waiting)를 하고 다시 집는다. 셋업 실패(repo 미등록·인증 누락·plan_doc 빈값 등)는 `prepare` 가 **QUESTION 으로 회수**하고 멈춘다(fallback 금지).

### 1.2 이 세션이 다오로서 수행

`WORK_DIR` 로 들어가, 그 상위에 이식된 **다오 스킬을 따라** `DAO PROMPT` 를 수행한다:

- 작업폴더 규약: `WORK_DIR/../CLAUDE.md`(다오 정체성·출력 규약·단계 순서·절대 규칙) + `WORK_DIR/../.claude/skills/`(단계 스킬: `unskein-exec`·`unskein-verify`·`unskein-wiki-*`·`unskein-git`). 프롬프트가 지시한 **현재 단계만** 수행한다(`plan`=구현+자체검증 / `inspect`=기록·마감·PR 등).
- **`test` 단계 = CDP 화면검증**: 프롬프트 대신 **`unskein-test`(§1–7 수동 진단 절차)로 실제 화면을 검증**한다 — `start.ps1` 로 CDP Chrome 기동, `remote.js navigate/collect/attrs/shot` 로 수용 기준의 시나리오 수행(WSL 세션이면 `powershell.exe`·윈도우 Node 로 호출, `unskein-test` §6). 케이스 흡수·기록(`unskein-case`)과 리포트 표준(`unskein-test` §0.5)도 그대로 적용한다. 판정을 마커로 옮긴다:
  - PASS → `RESULT: status=inspect stage=test summary=...` (+ 검증 리포트를 DOC 펜스에)
  - FAIL → `RESULT: status=plan stage=test summary=...` (실패 근거 포함 — 구현자가 다시 집는다)
  - 검증 결과 구조(verdict·scenarios·findings — `unskein-test` §0.3)는 JSON 파일로 저장해 §1.3 의 `--payload-file` 로 싣는다.
  - **예외 — CDP 검증 의뢰 카드(`payload.cdp_request`)**: 이 카드의 종단 remap(PASS/FAIL 모두 done 마감, ADR-0019)은 **tester 토큰 보고에서만** 발동한다. mori 토큰의 수동 보고는 inspect 로 가서 마감 파이프라인(커밋·PR)을 잘못 탄다 — 이 카드는 자율 TESTER 루프(`unskein-test` §0)에 맡긴다.
- clone/pull/checkout 을 직접 하지 않는다 — `prepare` 가 이미 결정적으로 준비했다. `WORK_DIR` 안에서 작업만 한다.
- **git 인증(주의)**: 다오의 push(inspect 단계)는 **이 세션 자신의 git/gh 인증**(executor.env + `gh auth`)을 쓴다 — 헤드리스처럼 scrubbed env 를 주입하지 않는다. master 직접 머지·배포는 하지 않는다(PR 까지 — 머지되면 자동 배포).
- 마치면 **최종 마커 한 개**를 파일로 저장한다(규약: `CLAUDE.md §4.1`):
  - 완료: `RESULT: status=<다음 status> stage=<단계명> summary=<요약>` 첫 줄 + (산출물 있으면) `<<<UNSKEIN_DOC` ~ `UNSKEIN_DOC` 펜스 블록.
  - 막힘: `QUESTION: <질문>` 한 줄. **운영자가 그 자리에서 답할 수 있으면 답을 반영해 계속 진행**하고(대화가 곧 재개), 정말 사람 결정이 필요하면 마커로 저장해 회수한다.
  - `summary`·`QUESTION`·산출 본문 서술은 plugin `docs/보고규칙.md` 를 따른다 — 사실을 먼저, 평범한 한국어로, 현상 → 원인 → 해결 순서.

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
# test 단계였다면 검증 결과 구조를 함께 싣는다 (task.payload['test'] 로 저장 — 보드가 읽음)
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" report <TASK_ID> --marker-file /tmp/marker.txt --payload-file /tmp/test-payload.json
```

- `report` 가 하는 일: 마커 파싱 → **heartbeat 정지** → 규약대로 회수(RESULT=전이 report / QUESTION·UNKNOWN=질문 회수) → `done` 이면 작업폴더 정리.
- 전이는 오직 마커의 `next status` 로만 일어난다(하드코딩 done 금지) — run/watch 와 동일한 서버 게이트.
- 마커를 stdin 으로 넘겨도 된다: `... | python3 .../work.py report <TASK_ID>`.

## 2. 연속 처리 (선택)

한 번에 한 건이다. 여러 건을 이어서 하려면 §1 을 반복한다(`prepare` → 수행 → `report`). `watch` 와 달리 **매 건을 운영자가 보며** 진행한다 — 자율 대량 처리가 목적이면 `watch` 를 쓴다.

## 3. run/watch 와 다른 점 (요약)

| | `run`/`watch` (헤드리스) | `unskein-work` (함께·수동) |
|---|---|---|
| 다오 | 자식 `claude -p` | **이 세션 자신** |
| 관찰·조종 | 불가(RESULT/QUESTION 만 회수) | **운영자가 보며 조종** |
| 집는 단계 | plan/exec/inspect (test 는 opt-in ADR-0016) | **전 단계 — test 포함(항상)** |
| test 처리 | (opt-in 시) 코드검증만 | **CDP 화면검증(`unskein-test`) → inspect/plan** |
| 막힘(점유·동결) | lease 만료 대기(180s) | **§0.5 로 즉시 정리 후 재선점** |
| heartbeat | process_task 스레드 | **`prepare` 가 백그라운드 데몬** |
| 세션 재개(--resume) | 있음(대화턴) | 없음 — 운영자가 그 자리서 이어감 |
| git 인증 | scrubbed env 주입 | 세션 자신의 gh/git 인증 |
| claim·전이·마커·report | ← 동일(run_once 재사용) → | 동일 |

## 4. 중단

작업 중 그만두려면 `python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/work.py" release <TASK_ID>` 로 heartbeat 데몬만 멈춘다(보고 안 함 — lease 가 자연 만료되면 재선점 가능). 작업폴더는 보존된다.
