---
name: unskein-wbs
description: WBS(작업 분해 구조) 관리 — 비즈니스/프로젝트의 WBS 노드를 생성·수정·삭제(CUD)하고, 각 카드의 plan_doc을 자기완결(카드 하나로 착수 가능) 규약으로 채우며, 의존성(dependencies)을 선점 게이트 의미론에 맞춰 말단↔말단으로 인코딩·검증하고, 간트 일정(plan_start/plan_end)을 오늘 기준·의존성 계단식으로 배치·조정하며, repo의 wbs.md 문서와 DB(로컬·프로덕션)를 일관되게 유지한다. 병합(merge)·분할(split)은 해당 API가 생기면 추가하며 현재는 공백이다. 트리거 — wbs 추가/수정/삭제, 작업 분해 등록, wbs 관리, wbs 반영, plan_doc 등록, 의존성 등록, unskein-wbs, 프로젝트에 작업 등록, 일정 배치·조정, 일정 재배치, 간트 날짜(plan_start/plan_end) 채우기.
---

# /unskein-wbs — WBS 관리 (biz·prj CUD + plan_doc 자기완결 + 의존성 게이트)

특정 **비즈니스 → 프로젝트**의 WBS(작업 트리)를 생성·수정·삭제하고, 각 카드의 `plan_doc`을 자기완결 규약(§4)으로 채우며, 의존성 게이트(§1.1·§5)를 말단↔말단으로 인코딩하고, repo 문서(`docs/local/wbs.md`)와 DB(로컬·프로덕션)를 일관되게 유지한다. 병합(merge)·분할(split)은 §8에 자리만 두고 API 구현 후 채운다.

핵심 원칙: **WBS의 단일 출처는 두 곳** — 사람이 읽는 분해 문서 `docs/local/wbs.md` 와 라이브 작업 트리(DB, 칸반·간트가 읽음). CUD 시 둘을 함께 갱신한다. ido가 "로컬·프로덕션 둘 다"를 요청하면 양쪽 환경에 같은 변경을 반영한다.

## 1. WBS 모델 (불변 규약)

- WBS 노드 = 프로젝트의 `task` 1행. 식별: `wbs_code`(예 `1`, `4.9`, `7.11.2`).
- **계층은 wbs_code 접두로 결정한다**: `4.9.1`의 부모는 `4.9`, `4.9`의 부모는 `4`, `4`는 루트(부모 없음). `parent_id`는 부모 wbs_code의 task id로 잡는다.
- **상태 매핑** (문서 ↔ DB status): `✅`=`done`, `🟡`=`exec`, `⬜`=`backlog`. 컨테이너(상위) 노드는 보통 `backlog`. 진행률은 status에서 파생(`progress_for`) — 신규는 `backlog`(0).
- **정렬**: `sort_order`는 형제 표시 순서. 위상순서 유지(부모의 sort_order < 자식). 신규 노드는 기존 최대 sort_order 뒤에 붙인다.
- **격리**: task는 project_id, project는 business_id에 속한다. 쓰기는 멤버(owner/admin/member)만 — viewer는 403. 항상 대상 비즈니스·프로젝트를 이름으로 먼저 특정한다.
- **일정 필드**: 간트(WBS) 막대의 가로 위치는 **오직 `plan_start`·`plan_end` 두 필드**로 정해진다. 둘 중 하나라도 비면(null) 프론트가 **오늘→오늘+1** 하루짜리로 폴백하고 흐리게(`unscheduled`) 표시해 모든 막대가 오늘 열에 몰린다. → 신규·수정 노드는 §6 규칙(오늘 기준·의존성 계단식)으로 두 필드를 반드시 채운다. `due_dt`·`created_at`·`actual_*`는 막대 위치에 안 쓴다.
- 추측 금지(fallback 금지): 대상 biz/project가 없거나 모호하면 멈추고 묻는다.

### 1.1 dependencies = 선점(claim) 게이트 (간트 표시용 아님)

`task.dependencies`(선행 task id 배열)는 **간트 표시용이 아니라 다오의 카드 선점(claim)을 실제로 막는 게이트**다 (backend `routes.py`: 선점 게이트 `_deps_satisfied`, 부모 마감 시 자손 롤업 `_rollup_done`, 단위 수집 `_collect_task_subtree`). 아래를 불변 규약으로 지킨다:

- **선점 단위** = plan 상태 후보 카드 + 그 WBS 자손 전체 (ADR-0007 rule 2). 게이트는 이 단위의 간선만 본다.
- **통과 요건**: 단위 구성원(미완·활성)이 가진 선행 중 **단위 밖(external) 선행이 전부 `done`** 이어야 선점된다. `backlog` 선행도 막는다. 삭제·비활성(없어진 id) 선행은 막지 않는다 — **fail-open**.
- **롤업**: 부모 단위로 `done` 보고 시 자손도 `done` 으로 롤업된다(`_rollup_done`) — 말단↔말단 간선이어도 데드락이 없다.
- **적용 범위**: 선점(plan) 단계에만 건다. exec 이후 진행 중 단위는 끊지 않는다.
- **인코딩 규칙 = 말단↔말단만.** 간선의 양끝은 모두 말단이어야 한다. **컨테이너(상위) 노드 간선은 금지** — 개별 말단 선점 시 미검사되어 **우회**되고, 말단만 완료돼도 컨테이너는 `backlog`로 남아 그를 선행으로 가리키는 후행이 **영구 차단(과차단)**된다. (등록·검증은 §5.)

## 2. 대상·환경 정하기 — 먼저 한다

1. **대상**: 비즈니스 이름 + 프로젝트 이름(예: `MUPAI STUDIO` / `UNSKEIN_SAAS`). 이름으로 id를 조회한다(id 하드코딩 금지 — 환경마다 다르다).
2. **환경**: `local`(개발 백엔드/DB) / `production`(`https://unskein.mupai.studio`) / 둘 다. ido 지시에 따른다.
   - 프로덕션: **API(플래너 토큰 — §3)** 가 1차 경로(사람 웹 세션이면 admin 로그인 Bearer 도 같은 유저로 인가 — §3 대안). gcloud로 VM 직접 접근(SSH·DB)도 가능하다(`docs/deploy.md` 접근 정보 — project `epic-framework`, gcloud 설치·인증 완료). API로 안 되는 작업(예: 새 컬럼 의존 PATCH는 backend 재배포 선행)만 VM 경로를 쓴다.
   - 로컬은 백엔드 API 또는 DB 직접(둘 다 가능). 일관성을 위해 가능하면 API를 쓴다.
   - 같은 변경을 양쪽에 반영할 때 **id는 환경마다 다르다** — 항상 이름+wbs_code로 조회한다.

## 3. 인증·엔드포인트 (API 경로)

**인증은 플래너 토큰**(kind=planner, ADR-0013) — 서버 호출 전에 **프로젝트별 격리된 `planner.env`** 를 셸에 올린다(source 우선·cwd 폴백 — ADR-0021). 한 플래너로 여러 프로젝트를 다뤄도 프로젝트마다 토큰·서버가 안 섞인다:
```bash
. "${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh"   # UNSKEIN_API + UNSKEIN_PLANNER_TOKEN 로드 (안 잡히면 멈춤)
```
아래 등록 라우트는 모두 `X-Planner-Token: $UNSKEIN_PLANNER_TOKEN` 로 인가된다(get_current_user_flex 7개 라우트: list_businesses·list_projects·list_tasks·create_task·update_task·attach_plan·delete_task):
```
GET  /api/businesses                      내 비즈니스 목록 → 이름으로 id
GET  /api/businesses/{biz}/projects       프로젝트 목록 → 이름으로 id
GET  /api/projects/{prj}/tasks            현 WBS(노드 전체) — wbs_code·parent_id 포함
POST /api/projects/{prj}/tasks            노드 생성 (아래 필드)
PATCH /api/tasks/{id}                     노드 수정 (부분)
DELETE /api/tasks/{id}                    노드 삭제
```
> **대안(사람/프로덕션)**: 사람이 웹 로그인 세션으로 돌리면 `POST /api/auth/login` → Bearer 로도 같은 유저로 인가된다. 프로덕션에서 API 로 안 되는 작업(새 컬럼 의존 PATCH·DB 직접)만 §2.2 의 gcloud VM 경로를 쓴다. 토큰 kind 를 섞지 말 것(mori↔planner 섞이면 401).

`POST .../tasks` 가 받는 WBS 필드: `title, description, status, position, sort_order, wbs_code, parent_id, is_milestone, progress, dependencies, plan_start, plan_end, due_dt, assignee_id, payload`. (status는 TASK_STATUSES, progress 0~100, parent_id는 같은 프로젝트만 — 위반 400.)

> 로컬을 DB로 직접 다룰 때는 `business`/`project`/`task` 모델을 쓰되, `parent_id`는 부모 wbs_code로 조회해 잡고, 멱등(같은 wbs_code 있으면 skip)하게 한다. (이름으로 조회 → DB·API 어디서 돌려도 이식 가능.) **함정**: `task.payload`는 NOT NULL — 직접 INSERT 시 `'{}'::jsonb` 를 넣어야 한다.

**스콥/계획 본문은 `plan_doc`에 넣는다 — 이 스킬의 핵심 자리.** 한 노드의 스콥(수용 기준·계획 본문)은 **다음 단계(exec)가 읽는 `plan_doc` 필드**에 데이터로 주입한다. `PATCH /api/tasks/{id}` 의 `plan_doc`(로컬은 DB 직접)으로 set/edit 하며, **status 전이와 분리**한다 — 스콥을 넣어도 상태를 바꾸지 않는다. `/plan` 승인 엔드포인트(backlog→plan 강제 전이)는 쓰지 않는다(status·승인은 별개 단계·사람 몫). **스콥 *작성*은 이 스킬의 롤이 아니다** — 외부(다른 세션·`/unskein-scope` 스킬·사람)가 정의한 스콥을 받아 정확한 위치에 넣을 뿐이다(플랜을 포함한 스콥 생성 과정은 운영자가 관여). 웹 UI의 스콥 등록·편집도 같은 `plan_doc` PATCH 경로를 쓴다. **넣는 위치는 여기, 넣는 내용의 표준은 §4다.**

## 4. plan_doc 자기완결 규약 — 카드 하나로 착수 가능

**동기**: 실행 단위(다오 세션)는 카드 하나만 들고 착수한다. `plan_doc`이 빈약해 정보를 다시 찾으러 나가면(컨텍스트 재탐색) 프로그램이 엉뚱한 방향으로 간다. 그래서 `plan_doc`은 **repo를 새로 클론해도 카드(말단)+부모(루트)만 읽으면 전체 맥락이 복원**되게 자기완결이어야 한다. (스콥 *작성*은 §3대로 이 스킬 롤이 아니다 — 받은 스콥을 이 규약 형태로 넣는 게 이 절이고, 작성 측 산출 형식은 `unskein-scope`가 맞춘다.)

### 4.1 말단(leaf) plan_doc 최소 표준 — 7요소
말단 카드 `plan_doc`은 아래 7요소를 모두 담는다. 해당 없으면 **"해당 없음"으로 명시**(생략 금지).

- **[배경]** 이 작업이 왜 필요한가 — 스콥 목적 속 이 카드의 위치 (1~2문장).
- **[전제]** 선행 카드·환경 조건 (무엇이 끝나 있어야 시작 가능한가). ← §5의 **의존 간선의 선행과 일치**해야 한다.
- **[완료 기준]** 성공/실패를 판단할 수 있는 검증 가능한 기준. **이 완료 기준을 이 카드의 실행 주체가 자기 환경에서 달성할 수 있는지**를 함께 명시한다 — 라이브 자원이 전제면 그 자원(어느 DB·어느 백엔드·어느 브라우저)과 그것에 닿는 실행 주체(VM 실행기·사람 운영자)를 [전제]·[실행 정보]에 적는다. 실행기(다오)가 못 닿는 자원을 요구하는 완료 기준은 실행기 말단에 두지 않는다(작성 측 분해 규칙 = `unskein-scope §2·§3`).
- **[실행 정보]** 대상 파일·경로·명령·API·접속 방법 — 실행자가 탐색 없이 시작할 수준.
- **[검증 방법]** 완료를 스스로 확인하는 커맨드/절차.
- **[함정·실측]** 알려진 함정, 선행 실측 결과 (있으면).
- **[참조]** 루트 카드 plan_doc(스콥 전문) + repo 원본 경로 병기 (§4.3).

### 4.2 루트(feature) plan_doc = 스콥 전문 수록
- 루트 카드 `plan_doc` = **스콥 문서 전문**(등록 시점 사본) + 원본 repo 경로 명기.
- **repo 파일 경로 단독 참조 금지** — 미커밋·새 클론·브랜치 상태에 따라 깨진다. 전문을 DB에 실어 자기완결시킨다.

### 4.3 참조는 DB 내부 우선
- 말단의 상세 참조는 **"루트 카드 N plan_doc" 형식(DB 내부)을 1차**로, repo 경로는 **병기**로 둔다.
- DB만으로 자기완결: 실행자가 말단 + 부모(루트)만 읽어 전체 맥락을 복원할 수 있어야 한다.

### 4.4 비밀 정보는 값 대신 위치 지칭
- 자격증명·키는 `plan_doc`에 **값을 넣지 않고 보관 위치**를 지칭한다(예: "sa 비밀번호는 운영 메모/시스템 DB Fernet 복호화"). 자기완결 원칙의 유일한 예외.

### 4.5 등록 시 스펙 커밋 필수 — 브랜치+PR (실행기 재사용)
등록하는 WBS의 **출처 스펙**(`docs/specs/*.md`)은 **등록 시점에 항상 feature 브랜치+PR로 커밋한다** — master/main 직커밋 금지(PR 경유). 실행기(다오)는 repo 클론 + `plan_doc`만 보므로, 스펙이 repo에 있어야 클론으로 받아 작업 맥락을 이해한다. **후속 처리로 미루지 않는다.**
1. **원격 점검(멱등)**: `git log origin/<main> -- <spec>` 로 이미 원격에 있으면(머지됨) 커밋 단계는 skip.
2. **격리 커밋**: 없으면 동시 세션 안전을 위해 `git worktree add -b wbs/<slug>-spec <경로> origin/<main>` 격리본에서 **그 스펙 파일만** add·commit·push 한다 (CLAUDE.md §8.1 — 공유 트리 브랜치/파일 직접 조작 금지, 다른 untracked 변경 섞지 않음). **로컬 트리가 origin보다 뒤처졌을 수 있으니 worktree 기준은 항상 `origin/<main>`**.
3. **PR**: `gh pr create` → 저장소 기본 정책대로 자동 머지(테스트 repo) 또는 사람 머지(리뷰 게이트). 끝나면 `git worktree remove`.
4. **이중 안전**: 커밋해도 루트 plan_doc엔 §4.2 전문을 함께 싣는다 — 클론·브랜치·머지 지연과 무관하게 자기완결 유지.
- 대상 repo·브랜치(main/master)는 프로젝트에 맞춘다.

## 5. Create (노드 추가)

0. **스펙 커밋 (§4.5) — 먼저 한다.** 이 WBS의 출처 스펙(`docs/specs/*.md`)을 origin 기준 worktree에서 feature 브랜치+PR로 커밋한다 — 실행기가 클론으로 받아 작업을 이해하도록. 미커밋 스펙으로 노드 생성 진행 금지.
1. 대상 프로젝트의 현재 노드를 조회해 `wbs_code → id` 맵과 최대 `sort_order`를 만든다.
2. 추가할 노드를 **위상순서(부모 먼저)** 로 정렬한다.
3. 각 노드: 이미 같은 `wbs_code`가 있으면 skip(멱등). 없으면 `parent_id` = 부모 wbs_code의 id, `sort_order` = 증가값으로 생성. **말단이면 §4 자기완결 표준(7요소)으로 `plan_doc`을 채우고, 루트면 스콥 전문을 싣는다. `plan_start`/`plan_end`는 §6(오늘 기준·의존성 계단식)으로 계산해 함께 넣는다** — 날짜를 비우면 간트에서 오늘 열에 몰리므로 빈 날짜 금지.
4. **의존 간선 등록** — 스콥(`unskein-scope`)이 준 **말단 wbs_code 기준 간선 목록**을 받아:
   1) 각 wbs_code를 **환경별로** `task id`로 조회해 변환한다 (id 하드코딩 금지 — 환경마다 다르다).
   2) 후행 카드의 `dependencies`(선행 id 배열)에 기록한다.
   3) **검증**: 간선 양끝이 모두 **말단**인가(컨테이너 간선 거부 — §1.1) · 같은 프로젝트인가 · 순환이 없는가(위상 정렬 시도) · 승인 선행이 필요한 스콥이면 **진입 말단**에 승인 카드가 걸렸는가.
   4) 각 말단 plan_doc의 **[전제]와 간선이 일치**하는지 대조한다(간선의 선행은 전제에, 전제의 선행 카드는 간선에).
5. 양쪽 환경 요청이면 각 환경에서 1~4를 독립 수행(환경마다 id가 다르므로 맵·간선 변환도 환경별로).
6. `docs/local/wbs.md`에 같은 노드를 해당 섹션 위치에 추가하고, **의존 간선 목록도 함께 기록**한다(DB·문서 이중 출처 유지).

## 6. 일정 배치·조정 (plan_start/plan_end) — 오늘 기준 + 의존성 계단식

간트 막대의 가로 위치는 오직 `plan_start`·`plan_end`로 정해지고, 비면 오늘 열에 몰린다(§1). 그래서 **노드를 만들거나 "일정 조정/재배치"를 요청받으면 이 절의 forward pass로 두 필드를 계산해 채운다.** 이 계산은 이 스킬의 기능이다 — 스콥 본문은 안 쓰지만 일정 날짜는 이 스킬이 정한다.

### 규칙

- **앵커 날짜**: 기본은 **실행일(오늘)**. ido가 시작일을 지정하면 그 날짜. 단위는 일(day), 값은 `YYYY-MM-DD`(nullable `DateTime` 컬럼 — 날짜만 넣으면 자정으로 저장).
- **기간(duration)**: 리프(말단) 작업 기본 **1일** → `plan_end = plan_start + 1일`. ido가 기간(예 3일·1주)을 주면 그 값을 리프 기본으로 쓴다. **컨테이너(자식 있는 상위)** 는 자식 범위를 스팬한다 — `plan_start = min(자식 plan_start)`, `plan_end = max(자식 plan_end)`.
- **의존성 계단식(하나씩 오른쪽)**: 선행이 있으면 후행은 **선행이 끝난 지점에서 시작**한다.
  - 선행 없음 → `plan_start = 앵커`.
  - 선행 있음 → `plan_start = max(모든 선행의 plan_end)`, `plan_end = plan_start + 기간`.
  - **선행 판정 순서**: ① 명시적 `dependencies`(선행 task) 우선. ② `dependencies`가 비면 **같은 부모 아래 직전 형제**(sort_order/wbs_code 바로 앞)를 선행으로 본다 → 의존성을 안 걸어도 형제가 계단식으로 하나씩 밀린다.
- **캘린더 일**(주말 포함)이 기본. 근무일만(주말 스킵) 원하면 ido 지시 시 적용한다.

### 절차 (forward pass 1회)

1. `GET .../tasks`로 현재 노드와 각 노드의 `dependencies` **실제 형식**을 읽는다(형식은 응답 그대로 따른다 — 추측해 새 형식을 만들지 않는다).
2. 노드를 **위상순서**(선행 먼저)로 정렬한다. 순환이 발견되면 멈추고 해당 노드를 보고한다(임의 배치 금지).
3. 순서대로 각 리프의 `plan_start`/`plan_end`를 위 규칙으로 계산하고, 컨테이너는 자식 확정 뒤 스팬으로 채운다.
4. 값을 쓴다 — 생성 시 `POST .../tasks`의 `plan_start`/`plan_end`(와 `dependencies`), 기존 노드 조정 시 `PATCH /api/tasks/{id}`.
5. **status·plan_doc은 건드리지 않는다** — 일정 배치는 상태·스콥과 분리(§3 원칙 유지).

### 일정 조정(reflow) 모드

"일정 조정/재배치/날짜 다시 잡아줘" 요청이면 노드를 새로 만들지 않고, 위 절차로 **기존 노드의 `plan_start`/`plan_end`만** 앵커(오늘 또는 지정일)부터 다시 흘려 `PATCH`한다. 대량 PATCH·프로덕션이면 실행 전 대상 범위(노드 수·앵커·기간)를 한 줄로 확인한다.

### 예 (앵커 = 오늘 07-05, 리프 1일)

```
1  설계        선행없음        07-05 → 07-06
2  구현   dependencies=[1]    07-06 → 07-07
3  테스트 dependencies=[2]    07-07 → 07-08
4  문서        선행없음        07-05 → 07-06   (독립 — 1과 같은 날 병렬 시작)
```
→ 의존 사슬 1→2→3은 하루씩 오른쪽 계단, 독립 노드 4는 오늘 시작. (전에는 넷 다 07-05→07-06으로 몰렸다.)

## 7. Update / Delete

- **Update**: `PATCH /api/tasks/{id}` 로 `title/description/plan_doc(자기완결 §4)/status/wbs_code/sort_order/parent_id/dependencies/progress/is_milestone` 등 변경. 트리 위치를 바꾸면(부모/코드 변경) 자식들의 wbs_code도 일관되게 갱신한다. 문서도 동일 반영.
- **Delete**: `DELETE /api/tasks/{id}`. 하위가 있으면 자손까지(말단부터) 지운다 — 고아 노드를 남기지 않는다. 문서에서도 해당 블록을 제거.
- **간선 재배선(삭제·이동·split/merge)**: 노드를 지우거나 옮기면 **그 노드를 가리키는 `dependencies` 간선을 재배선하거나 제거**한다. 끊긴 id는 **fail-open**이라(§1.1) 조용히 게이트가 사라져 **무순서 선점이 재발**한다 — 반드시 후행 카드의 `dependencies` 배열을 갱신하고 문서 간선도 맞춘다.
- 파괴적 변경(삭제·대량 수정)·프로덕션 대상은 실행 전 범위를 확인한다.

## 8. 병합(merge) · 분할(split) — 자리 (API 구현 후 채움)

<!-- 미구현: 작업 분리(split)/통합(merge) API가 아직 없다.
     스펙은 docs/specs/wbs-split-merge.md (WBS §7.11). 백엔드 split/merge 엔드포인트가
     생성되면 이 절에 호출 절차(트랜잭션·순환 재검증·롤백·점유/상태 가드·간선 재배선·문서 반영)를 채운다.
     그때까지 이 절은 공백으로 둔다. -->

_아직 비어 있음 — split/merge 엔드포인트 구현 후 추가._

## 9. 검증

- 생성/수정 후 `GET .../tasks`로 노드 수·`wbs_code`·`parent_id` 트리가 의도대로인지 확인한다. (루트 수, 고아 parent 참조 0, 상태 분포)
- **의존 간선**: 모든 `dependencies` 원소가 존재하는 task id인지(끊긴 참조 = 조용한 fail-open) · 양끝이 모두 **말단**인지 · 순환이 없는지 확인한다.
- **plan_doc 자기완결**: 말단 카드가 §4 7요소를 갖췄는지, 루트가 스콥 전문을 실었는지, repo 단독 참조(옛 포인터)가 남지 않았는지 점검한다.
- 양쪽 환경 반영이면 두 환경의 노드 수가 같은지 대조한다.
- `docs/local/wbs.md` 와 DB 트리가 어긋나지 않는지(노드 누락·중복·간선 누락) 본다.
- **일정**: `plan_start`/`plan_end`가 빈 노드 0(모두 채워짐), 각 노드 `plan_start < plan_end`, 선행 관계에서 `선행.plan_end ≤ 후행.plan_start`(계단 유지). 간트에서 막대가 오늘 열에 몰리지 않고 펼쳐지는지 본다.
