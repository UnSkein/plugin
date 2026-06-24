---
name: unskein-wbs
description: WBS(작업 분해 구조) 관리 — 비즈니스/프로젝트의 WBS 노드를 생성·수정·삭제(CUD)하고, repo의 wbs.md 문서와 DB(로컬·프로덕션)를 일관되게 유지한다. 병합(merge)·분할(split)은 해당 API가 생기면 추가하며 현재는 공백이다. 트리거 — wbs 추가/수정/삭제, 작업 분해 등록, wbs 관리, wbs 반영, unskein-wbs, 프로젝트에 작업 등록.
---

# /unskein-wbs — WBS 관리 (biz·prj CUD + merge/split 자리)

특정 **비즈니스 → 프로젝트**의 WBS(작업 트리)를 생성·수정·삭제하고, repo 문서(`docs/local/wbs.md`)와 DB(로컬·프로덕션)를 일관되게 유지한다. 병합(merge)·분할(split)은 §6에 자리만 두고 API 구현 후 채운다.

핵심 원칙: **WBS의 단일 출처는 두 곳** — 사람이 읽는 분해 문서 `docs/local/wbs.md` 와 라이브 작업 트리(DB, 칸반·간트가 읽음). CUD 시 둘을 함께 갱신한다. ido가 "로컬·프로덕션 둘 다"를 요청하면 양쪽 환경에 같은 변경을 반영한다.

## 1. WBS 모델 (불변 규약)

- WBS 노드 = 프로젝트의 `task` 1행. 식별: `wbs_code`(예 `1`, `4.9`, `7.11.2`).
- **계층은 wbs_code 접두로 결정한다**: `4.9.1`의 부모는 `4.9`, `4.9`의 부모는 `4`, `4`는 루트(부모 없음). `parent_id`는 부모 wbs_code의 task id로 잡는다.
- **상태 매핑** (문서 ↔ DB status): `✅`=`done`, `🟡`=`exec`, `⬜`=`backlog`. 컨테이너(상위) 노드는 보통 `backlog`. 진행률은 status에서 파생(`progress_for`) — 신규는 `backlog`(0).
- **정렬**: `sort_order`는 형제 표시 순서. 위상순서 유지(부모의 sort_order < 자식). 신규 노드는 기존 최대 sort_order 뒤에 붙인다.
- **격리**: task는 project_id, project는 business_id에 속한다. 쓰기는 멤버(owner/admin/member)만 — viewer는 403. 항상 대상 비즈니스·프로젝트를 이름으로 먼저 특정한다.
- 추측 금지(fallback 금지): 대상 biz/project가 없거나 모호하면 멈추고 묻는다.

## 2. 대상·환경 정하기 — 먼저 한다

1. **대상**: 비즈니스 이름 + 프로젝트 이름(예: `MUPAI STUDIO` / `UNSKEIN_SAAS`). 이름으로 id를 조회한다(id 하드코딩 금지 — 환경마다 다르다).
2. **환경**: `local`(개발 백엔드/DB) / `production`(`https://unskein.mupai.studio`) / 둘 다. ido 지시에 따른다.
   - 프로덕션: **API(admin 로그인)** 가 1차 경로. gcloud로 VM 직접 접근(SSH·DB)도 가능하다(`docs/deploy.md` 접근 정보 — project `epic-framework`, gcloud 설치·인증 완료). API로 안 되는 작업(예: 새 컬럼 의존 PATCH는 backend 재배포 선행)만 VM 경로를 쓴다.
   - 로컬은 백엔드 API 또는 DB 직접(둘 다 가능). 일관성을 위해 가능하면 API를 쓴다.
   - 같은 변경을 양쪽에 반영할 때 **id는 환경마다 다르다** — 항상 이름+wbs_code로 조회한다.

## 3. 인증·엔드포인트 (API 경로)

```
POST /api/auth/login                      {username,password} → access_token (Bearer)
GET  /api/businesses                      내 비즈니스 목록 → 이름으로 id
GET  /api/businesses/{biz}/projects       프로젝트 목록 → 이름으로 id
GET  /api/projects/{prj}/tasks            현 WBS(노드 전체) — wbs_code·parent_id 포함
POST /api/projects/{prj}/tasks            노드 생성 (아래 필드)
PATCH /api/tasks/{id}                     노드 수정 (부분)
DELETE /api/tasks/{id}                    노드 삭제
```

`POST .../tasks` 가 받는 WBS 필드: `title, description, status, position, sort_order, wbs_code, parent_id, is_milestone, progress, dependencies, plan_start, plan_end, due_dt, assignee_id, payload`. (status는 TASK_STATUSES, progress 0~100, parent_id는 같은 프로젝트만 — 위반 400.)

> 로컬을 DB로 직접 다룰 때는 `business`/`project`/`task` 모델을 쓰되, `parent_id`는 부모 wbs_code로 조회해 잡고, 멱등(같은 wbs_code 있으면 skip)하게 한다. (이름으로 조회 → DB·API 어디서 돌려도 이식 가능.)

**스콥/계획 본문은 `plan_doc`에 넣는다 — 이 스킬의 핵심 자리.** 한 노드의 스콥(수용 기준·계획 본문)은 **다음 단계(exec)가 읽는 `plan_doc` 필드**에 데이터로 주입한다. `PATCH /api/tasks/{id}` 의 `plan_doc`(로컬은 DB 직접)으로 set/edit 하며, **status 전이와 분리**한다 — 스콥을 넣어도 상태를 바꾸지 않는다. `/plan` 승인 엔드포인트(backlog→plan 강제 전이)는 쓰지 않는다(status·승인은 별개 단계·사람 몫). **스콥 *작성*은 이 스킬의 롤이 아니다** — 외부(다른 세션·`/unskein-scope` 스킬·사람)가 정의한 스콥을 받아 정확한 위치에 넣을 뿐이다(플랜을 포함한 스콥 생성 과정은 운영자가 관여). 웹 UI의 스콥 등록·편집도 같은 `plan_doc` PATCH 경로를 쓴다.

## 4. Create (노드 추가)

1. 대상 프로젝트의 현재 노드를 조회해 `wbs_code → id` 맵과 최대 `sort_order`를 만든다.
2. 추가할 노드를 **위상순서(부모 먼저)** 로 정렬한다.
3. 각 노드: 이미 같은 `wbs_code`가 있으면 skip(멱등). 없으면 `parent_id` = 부모 wbs_code의 id, `sort_order` = 증가값으로 생성.
4. 양쪽 환경 요청이면 각 환경에서 1~3을 독립 수행(환경마다 id가 다르므로 맵도 환경별로).
5. `docs/local/wbs.md`에 같은 노드를 해당 섹션 위치에 추가한다(상태 마커·들여쓰기 규약 유지).

## 5. Update / Delete

- **Update**: `PATCH /api/tasks/{id}` 로 `title/description/plan_doc(스콥·계획 본문)/status/wbs_code/sort_order/parent_id/progress/is_milestone` 등 변경. 트리 위치를 바꾸면(부모/코드 변경) 자식들의 wbs_code도 일관되게 갱신한다. 문서도 동일 반영.
- **Delete**: `DELETE /api/tasks/{id}`. 하위가 있으면 자손까지(말단부터) 지운다 — 고아 노드를 남기지 않는다. 문서에서도 해당 블록을 제거.
- 파괴적 변경(삭제·대량 수정)·프로덕션 대상은 실행 전 범위를 확인한다.

## 6. 병합(merge) · 분할(split) — 자리 (API 구현 후 채움)

<!-- 미구현: 작업 분리(split)/통합(merge) API가 아직 없다.
     스펙은 docs/specs/wbs-split-merge.md (WBS §7.11). 백엔드 split/merge 엔드포인트가
     생성되면 이 절에 호출 절차(트랜잭션·순환 재검증·롤백·점유/상태 가드·문서 반영)를 채운다.
     그때까지 이 절은 공백으로 둔다. -->

_아직 비어 있음 — split/merge 엔드포인트 구현 후 추가._

## 7. 검증

- 생성/수정 후 `GET .../tasks`로 노드 수·`wbs_code`·`parent_id` 트리가 의도대로인지 확인한다. (루트 수, 고아 parent 참조 0, 상태 분포)
- 양쪽 환경 반영이면 두 환경의 노드 수가 같은지 대조한다.
- `docs/local/wbs.md` 와 DB 트리가 어긋나지 않는지(노드 누락·중복) 본다.
