---
name: unskein-session
description: unskein 프로젝트 세션의 작업 내용을 구조화된 요약으로 repo 안 docs/local 에 저장해 다음 세션이 컨텍스트를 빠르게 복원하게 한다. epic-link의 unskein 전용 버전 — 두 저장소(SaaS·plugin) 커밋·orchestrator 미러·프로덕션 작업 큐 상태를 함께 스냅샷한다. 트리거 — unskein-session, unskein 대화연결, unskein 세션 저장, 세션 마무리, 작업 기록 저장, 다음 세션에 넘기기. unskein 디렉토리에서 세션을 마치거나 컨텍스트를 다음 세션으로 넘길 때 사용한다. "정리해서 넘겨줘", "세션 저장" 같은 말에도 unskein 작업 중이면 이 스킬을 쓴다.
---

# /unskein-session — unskein 대화연결

unskein 세션의 작업을 구조화된 요약으로 남겨, 다음 세션(또는 다음 사람)이 빠르게 이어받게 한다. epic-link와 같은 골격이되, unskein의 두 저장소·orchestrator 미러·모리/다오 흐름·프로덕션 작업 큐에 맞춰 조정했다.

핵심 의도: 요약은 코드에서 파생되지 않는 것 — **왜 그렇게 했는가, 무엇이 미완이고 다음에 뭘 해야 하는가** — 을 남긴다. 코드 구조나 커밋 내용은 git이 이미 안다. 다음 세션이 자체 의제로 새지 않도록 "목적 한 줄"을 맨 앞에 둔다.

## 경로 (환경 무관하게 잡는다)

ido 특정 절대경로를 박지 않는다 — 다른 개발 환경에서도 작동하도록 매번 동적으로 잡는다. unskein 개발 환경은 SaaS repo와 옆 폴더 plugin repo로 구성된다(CLAUDE.md §2).

```bash
ROOT=$(git rev-parse --show-toplevel)              # SaaS repo 루트
PLUGIN="$(dirname "$ROOT")/unskein-plugin"          # 옆 폴더 plugin repo
SLUG=$(printf %s "$ROOT" | sed 's:/:-:g')           # transcript 폴더 slug
LOCAL="$ROOT/docs/local"                            # 세션 메모 (gitignore)
```

- 세션 메모 저장 위치: `$LOCAL` (= `<repo>/docs/local/`). gitignore 되어 있어 프로젝트 안에 두되 git·SaaS repo 로는 안 올라간다.
- transcript 디렉토리: `~/.claude/projects/$SLUG/`.

## Step 1: 세션 ID

transcript 디렉토리에서 현재 세션 ID를 얻는다. `claude session list`는 이 환경에서 미지원이라 디렉토리 기반으로 본다:

```bash
ls -dt ~/.claude/projects/$SLUG/*/ 2>/dev/null | head -1 | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
```

가장 최근 수정된 디렉토리가 현재 세션이다. 여러 개가 섞이면 이번 세션에서 띄운 워크플로/하위 에이전트 transcript 경로로 교차 확인한다. 못 가리면 "세션 ID 미확인(수동 복원)"으로 표기한다.

## Step 2: 연번

```bash
ls "$LOCAL"/unskein_$(date +%y-%m-%d)_* 2>/dev/null | wc -l
```

결과 + 1 이 연번이다. 파일명: `unskein_[YY-MM-DD]_연번_제목.md` (제목은 핵심 키워드를 하이픈으로, 한글 가능). 기존 파일을 덮어쓰지 않는다.

## Step 3: 작업·배포 상태 스냅샷 (unskein 특화)

다음 세션이 "지금 어디까지 됐나"를 즉시 알도록 세 가지를 스냅샷한다. unskein은 작업이 서버 큐에 있고 코드가 두 저장소로 미러되므로, 이 스냅샷이 epic-link의 TaskList 자리를 대신한다.

1. **두 저장소 git 상태** — 미커밋·미push가 남았는지:
   ```bash
   git -C "$ROOT" status -sb; git -C "$ROOT" log --oneline -3
   git -C "$PLUGIN" status -sb; git -C "$PLUGIN" log --oneline -3
   ```
2. **orchestrator 미러** — `run_once.py`/`run_loop.py`가 두 저장소에서 같은지(byte-identical 의무):
   ```bash
   diff -q "$ROOT/orchestrator/run_once.py" "$PLUGIN/plugins/unskein/orchestrator/run_once.py"
   ```
3. **프로덕션 작업 큐** — 접근 가능하면 작업 status 분포(backlog/plan/exec/waiting/done). 인증이 필요하므로 **비밀을 스킬에 넣지 않는다** — 이 세션에서 이미 확보한 토큰이 있으면 그걸로 조회하고, 없으면 "미조회"로 둔다. (TaskList 도구를 쓴 세션이면 그 결과도 함께 기록.)

## Step 4: 요약 작성

아래 템플릿으로 현재 대화 전체를 요약한다.

## Step 5: 파일 생성

- 요약: `$LOCAL/{파일명}.md`.
- 인제스트 대상은 **현재 상태가 완료일 때만** 만든다: `$ROOT/docs/architecture/unskein-session--{날짜}--{제목}.md` 에 성공·결정·교훈 섹션만 추출(이쪽은 git 추적 — 확정 지식만 굳힌다). 미완료가 남았으면 만들지 않고 다음 세션에서 완료 후 생성한다.

## Step 6: 메모리 push (사적 컨텍스트 → 서버, 단말 이식)

세션 마감 시 이 프로젝트의 **사적 메모리**(`~/.claude/projects/$SLUG/memory/`)를 서버 DB에 올려 다른 단말/다음 세션이 pull 로 컨텍스트를 복원하게 한다(user-memory-db-sync §1.1.2). `scope=private` 만 오르고 `scope=shared`·`MEMORY.md` 는 제외된다 — 공유 지식은 repo(CLAUDE.md/wiki)로 사람이 수동 승격하고, 인덱스는 pull 이 로컬 파일들로부터 재생성한다(충돌 핫스팟이라 sync 대상 아님).

```bash
# planner.env(UNSKEIN_API·PLANNER_TOKEN·BUSINESS·PROJECT) 로드 — source 우선·cwd 폴백(ADR-0021)
. "${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh"
python3 "${CLAUDE_PLUGIN_ROOT}/bin/memory-sync.py" push --codebase "$ROOT"
```

- **자격증명/프로젝트 없으면 멈춰 드러낸다**(fallback 금지) — 토큰 없음(401)·프로젝트 미특정(`UNSKEIN_BUSINESS`+`UNSKEIN_PROJECT` 또는 `UNSKEIN_PROJECT_ID` 필요)이면 스크립트가 비영점 종료하며 사유를 낸다. 조용히 skip 하지 않는다.
- **idempotent** — 이미 올라간 것과 내용이 같으면 `skipped`(content_hash no-op). 매 세션 반복 호출 안전.
- role 은 토큰 kind 파생(planner 세션 = planner). 파일 frontmatter 에 `role`/`scope` 가 있으면 그 값이 우선(frontmatter 3축 규약 — `bin/memory-sync.py` 헤더 참조).
- 이 단계는 **repo 코드를 건드리지 않는다**(로컬 메모리만 up-sync) — 아래 "금지"의 코드 수정 금지와 무관.

## Step 7: 보고

보고 서술은 plugin `docs/보고규칙.md` 를 따릅니다 — 사실을 먼저, 평범한 한국어로, 미실행은 "미실행"으로 명시.

```
대화연결 완료
세션 요약: <repo>/docs/local/{파일명}.md
인제스트 대상: docs/architecture/... (또는 "미완료 — 다음 세션에서 생성")
메모리 push: upserted/skipped (또는 "미실행 — 자격증명 없음")
복원: claude --resume '세션ID'
```

---

## 요약 템플릿

이 구조를 그대로 채운다. 빈 섹션은 "해당 없음"으로 둔다 — 다음 세션이 섹션 부재와 "확인했고 없음"을 구분할 수 있게.

```markdown
# 세션 요약: [핵심 주제 한 줄]

## 세션 정보
- **날짜**: YYYY-MM-DD
- **프로젝트**: unskein
- **세션 복원**: `claude --resume '[세션ID]'`

## 목적 (Why)
사용자/제품 차원에서 무엇을 가능하게 하려는가. 코드 변경 자체가 아니라 그 너머의 목표. 다음 세션이 본질에서 벗어난 자체 의제로 빠지지 않도록 하는 한 줄.

## 목표 (Outcome)
세션 종료 시 달성될 검증 가능한 결과(URL/UI 동작/데이터 상태/커밋 해시).

## 단기 목표 (Next Action)
다음 세션 진입 즉시 착수할 1~3개 실행 단위. 분석이 아니라 실행 가능한 행동.
- [ ] ...

## 작업 요약
수행한 핵심 3~7개.

## 주요 변경사항
저장소별로 구분: **SaaS(UnSkein/SaaS, master)** / **plugin(UnSkein/plugin, main)** / 메모리 / docs/local. 커밋 해시를 함께.

## 성공 내용
실제 해결·검증된 것. 코드에서 파생 불가능한 "왜 이렇게 했는가". dogfood 바퀴라면 **push 도달을 git으로 firsthand 확인했는지** 명시(서버의 done 하드코딩은 성공을 보장하지 않으므로).

## 결정 사항
기술·아키텍처 결정 + 대안이 있었다면 왜 이 방향인지.

## 교훈
삽질·실수·재발 방지. 코드 수정으로 해결되지 않는 프로세스/판단 차원.

## 제약조건
환경·도구·외부 시스템 제약(프로덕션 재배포 수단, 윈도우 CDP, 모리 연결 여부, 두 watch 등).

## 발견한버그
미해결 버그. 재현 경로 + 증상 + 추정 원인 + 처리(별도 작업/위임/미착수).

## 현재 상태
완료 / 진행중 / 보류.

## 작업·배포 상태 (Step 3 스냅샷)
- 두 저장소 git: 미push·미커밋 여부.
- orchestrator 미러: 일치/불일치.
- 프로덕션 작업 큐: status 분포(조회했으면) — 아니면 "미조회".
- plugin 버전·재설치 필요 여부.

## 다음 세션에서 할 일 (백로그)
단기 목표(상단)와 별개의 백로그/언젠가 할 일.

## 핵심 컨텍스트
다음 세션이 반드시 알아야 할 결정·제약·주의. 모리/다오 흐름, 두 저장소 미러, 프로젝트 메모리 위치(`~/.claude/projects/<repo-slug>/memory/`) 등.

## 세션 복원
```
claude --resume '[세션ID]'
```
```

---

## epic-link와의 차이 (왜 별도 스킬인가)

- 저장 위치가 SHARE 가 아니라 **repo 안 `docs/local/`(gitignore)** 다 — 프로젝트와 함께 다니되 git·SaaS repo 로는 안 올라간다.
- 파일명 접두사가 `unskein_`이고 프로젝트는 항상 unskein이다.
- **TASKS 백로그(TaskList)를 프로덕션 작업 큐 + 두 저장소 git + orchestrator 미러 스냅샷으로 대체·보강**한다.
- epic 전용 platform-admin 운영 메뉴얼 섹션은 없다(unskein 무관). 대신 배포·미러 상태를 본다.
- 세션 ID를 `claude session list` 대신 transcript 디렉토리 기반으로 얻는다(이 환경에서 전자 미지원).

## 금지

- 코드 수정·실행 금지(요약만 수행).
- 비밀(토큰·SSH 키·비밀번호) 포함 금지. 프로덕션 작업 큐 조회를 위해 비밀번호를 스킬·요약에 박지 않는다.
- 기존 파일 덮어쓰기 금지 — 항상 새 파일.
