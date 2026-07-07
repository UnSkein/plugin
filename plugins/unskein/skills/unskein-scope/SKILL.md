---
name: unskein-scope
description: 운영자가 실행 전에 작업(또는 작업 트리)을 검증 가능한 수용 기준으로 내리고, WBS로 정리해 각 카드의 plan_doc까지 갖춰 서버에 등록하는 절차. 트리거 — 작업 이해, 범위 정하기, 수용 기준, 기본 스콥, WBS 등록, scope.
---

# 범위(스콥) — 실행 전, 사람이 한다

스콥은 **사람(운영자)이 실행 전에** 작업을 "무엇을 어디까지 · 어떻게" 만들지 검증 가능하게 내리는 절차다. 다오는 더 이상 스콥을 하지 않는다 — 사람이 확정한 `plan_doc`(수용 기준)을 받아 곧장 구현한다(ADR-0009: 실행대기 ⟹ 스콥 존재 ⟹ 첫 단계는 구현, `exec` 단계 은퇴).

이 절차를 돌리는 주체가 **모리 PLANNER**다 — 개발자가 쓰는 클로드코드/운영 세션으로, 대상 프로젝트의 **코드베이스를 그대로 보유**한다(§0 이 자동 clone/pull 로 보장·최신화). 개발자의 "개발/계획 의뢰"를 받아 코드베이스를 근거로 스코프·플랜을 내리고, 그 결과를 **UNSKEIN(프로젝트 매니지먼트 SaaS)의 해당 프로젝트 작업 큐에 타스크로 등록**한다. 여기서 직접 개발하지는 않는다 — 개발은 실행 측(모리 EXECUTOR → 다오 WSL)이 claim 해서 한다.

**스콥의 방식 = drive-then-ask 루프**: 정확히 내릴 수 있는 데까지 내린다 → 진짜 못 정하는 지점에서 질문한다 → 답 받고 또 내린다 → 또 질문 → 또 내린다 → 마지막에 작업 영역 전체를 점검한다. 열린 질문은 멈춤 신호가 아니라 **질문 지점**이다(회피 금지). 요구사항은 추측하지 않는다.

## 0. 코드베이스 보장 — 인증 로드 + 자동 clone/pull (스콥 시작 전, ADR-0022)

스콥의 **근거는 코드베이스**다. 그래서 스콥을 내리기 전에 이 스킬이 **대상 프로젝트 코드베이스를 스스로 보장**한다 — 없으면 clone, 있으면 `git pull --ff-only`. 사람이 수동으로 clone·pull 하지 않는다(최초 clone 도 여기서 한다). 프로젝트별 격리(ADR-0021·0022): 서버·토큰·git 키·비즈니스/프로젝트가 `planner.env` 에 프로젝트별로 못박혀 있다.

**① 인증 로드 + 필수 변수 확인** — 서버·git 호출 전에 셸에 올린다(source 우선·cwd 폴백, ADR-0021):
```bash
. "${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh"
# 로드값: UNSKEIN_API · UNSKEIN_PLANNER_TOKEN · UNSKEIN_BUSINESS · UNSKEIN_PROJECT ·
#         UNSKEIN_SSH_KEY · UNSKEIN_HOME  (planner.env 를 set -a 로 통째 source)
# 필수 변수 — 하나라도 비면 멈추고 보고(fallback 금지, ADR-0022 §5·§6):
for v in UNSKEIN_API UNSKEIN_PLANNER_TOKEN UNSKEIN_HOME UNSKEIN_BUSINESS UNSKEIN_PROJECT; do
  [ -n "${!v:-}" ] || echo "  [없음] $v"
done
```
- 위에서 `[없음]` 이 하나라도 찍히면 **스콥을 진행하지 않고 멈춰 사람에게 알린다**(fallback 금지 — 다른 토큰·엉뚱한 위치로 넘어가지 않는다). 특히 `UNSKEIN_HOME` 이 없으면 아래 ③ 의 clone 위치가 cwd(`dirname ""`=`.`)로 무너져 **플래너를 띄운 repo 안에 코드베이스가 섞일 수 있으니** 반드시 가드한다. 어느 파일에서 로드됐는지는 `UNSKEIN_PLANNER_ENV_FILE`(진단은 `unskein-doctor`).
- `UNSKEIN_SSH_KEY` 는 **선택**(HTTPS repo 면 비운다 — gh 자격에 맡김)이라 필수 목록에서 뺐다. 있으면 ③ 에서 SSH 로 붙는다.

**② repo_url 조회** — 플래너 토큰은 유저(멤버십)까지만 특정하지 프로젝트를 못 짚고, 코드베이스가 없으면 `git remote` 로도 알 수 없다. 그래서 `planner.env` 의 `UNSKEIN_BUSINESS`/`UNSKEIN_PROJECT` **이름**으로 서버에서 `repo_url` 을 조회한다(이름 단건 조회 라우트는 없으니 목록을 받아 `name` 정확 일치로 고른다). 파싱은 이 plugin 집안 규약대로 `python3`(unskein-drawio 와 동일 — jq 비의존, 값은 `os.environ` 으로 넘겨 공백 이름도 안전):
```bash
# 비즈니스 목록 → UNSKEIN_BUSINESS 이름 일치의 id
biz_id=$(curl -fsS -H "X-Planner-Token: $UNSKEIN_PLANNER_TOKEN" "$UNSKEIN_API/api/businesses" \
  | python3 -c 'import sys,json,os; m=[b for b in json.load(sys.stdin) if b.get("name")==os.environ["UNSKEIN_BUSINESS"]]; print(m[0]["id"] if m else "")')
[ -n "$biz_id" ] || echo "비즈니스 '$UNSKEIN_BUSINESS' 를 목록에서 못 찾음 — 멈추고 보고"
# 그 비즈니스의 프로젝트 목록 → UNSKEIN_PROJECT 이름 일치의 id·repo_url (repo_url=null 은 빈 문자열로)
proj=$(curl -fsS -H "X-Planner-Token: $UNSKEIN_PLANNER_TOKEN" "$UNSKEIN_API/api/businesses/$biz_id/projects" \
  | python3 -c 'import sys,json,os; m=[p for p in json.load(sys.stdin) if p.get("name")==os.environ["UNSKEIN_PROJECT"]]; print(json.dumps({"id":m[0]["id"],"repo_url":m[0].get("repo_url") or ""}) if m else "")')
proj_id=$(printf '%s' "$proj" | python3 -c 'import sys,json; d=sys.stdin.read().strip(); print(json.loads(d)["id"] if d else "")')
REPO_URL=$(printf '%s' "$proj" | python3 -c 'import sys,json; d=sys.stdin.read().strip(); print(json.loads(d)["repo_url"] if d else "")')
```
- 둘 다 `get_current_user_flex` 인가라 `X-Planner-Token` 으로 닿는다(ADR-0013). 사람이 웹 로그인 세션이면 그 Bearer 로도 같은 유저로 인가된다. (`jq` 는 이 환경의 전제가 아니라 쓰지 않는다 — `python3` 는 `unskein-setup` 이 보장.)
- **`biz_id`·`proj` 가 비거나(이름 오타·미가입·미등록)** `REPO_URL` 이 비어 있으면(프로젝트에 원격 미설정 = repo_url null) **임의로 고르지 말고 멈추고 사람에게 묻는다**(fallback 금지). `repo_url` 미설정이면 확인 후 채워 다음부터 자동 되게 한다.
- 여기서 얻은 `proj_id` 가 §4 의 등록 대상 `project_id` 다(§4 의 repo→프로젝트 역매핑을 대신한다). `REPO_URL` 은 아래 ③ clone 대상.

**③ 코드베이스 보장 (clone 없으면 / pull --ff-only 있으면)** — clone 위치는 상태 루트의 **부모** 아래 `repo basename`(`UNSKEIN_HOME` 은 ① 에서 이미 가드했다 — 없으면 여기 안 온다):
```bash
CODE_PARENT="$(dirname "$UNSKEIN_HOME")"                 # 예: /home/u/work/frameweb
BASENAME=$(basename "${REPO_URL%.git}")                  # 예: FrameWeb ('.git' 접미 제거 후 마지막 세그먼트 — git@·https 모두)
CODEBASE="$CODE_PARENT/$BASENAME"
# git 키(있으면) — 실행기와 같은 UNSKEIN_SSH_KEY. 없으면 gh 자격(HTTPS)에 맡긴다(선택).
[ -n "${UNSKEIN_SSH_KEY:-}" ] && export GIT_SSH_COMMAND="ssh -i \"$UNSKEIN_SSH_KEY\" -o IdentitiesOnly=yes"

if [ -d "$CODEBASE/.git" ]; then
  git -C "$CODEBASE" pull --ff-only        # 로컬 커밋·충돌이면 실패 → 아래처럼 멈추고 보고
else
  git clone "$REPO_URL" "$CODEBASE"        # 최초 clone (없는 부모 폴더는 git 이 만든다)
fi
```
- **`git pull --ff-only` 가 실패**(로컬 커밋이 앞섬·충돌·detached 등)하면 **강제하지 않는다**(reset·`-f` 금지 — 다른 세션·미푸시 작업 유실 위험). 상태를 그대로 사람에게 보고하고 멈춘다(fallback 금지). clone/인증 실패(권한·키)도 마찬가지로 보고.
- **정합 확인**: 이미 있던 코드베이스면 `git -C "$CODEBASE" remote get-url origin` 이 위 `repo_url` 과 (정규화 후) 일치하는지 확인한다 — 다르면 엉뚱한 repo 이니 멈추고 묻는다.
- 이후 **`cd "$CODEBASE"`** 하고 §1 부터 이 코드베이스를 근거로 스콥한다. (이미 코드베이스 안에서 claude 를 띄웠고 그게 대상 repo 면 pull 만 한다.)

## 1. 기본 스콥 작성 → `docs/specs/`

먼저 `unskein-wiki-search`로 repo에 쌓인 지식을 찾아 재분석을 막는다. 그 위에:

- **무엇을 어디까지** 개발할지, **어떻게** 개발할지를 정한다.
- 성공 기준을 **검증 가능한 형태**로 적는다 — 입력/동작/출력, 또는 화면/상태 변화. (이 기준이 `unskein-verify`의 점검 대상이 된다.)
- 받은 작업에 직접 닿는 것으로 범위를 한정한다. 요청하지 않은 개선은 넣지 않는다.
- 저장 위치: `docs/specs/`(repo 루트 기준). 이 문서가 스콥의 단일 출처다.

## 2. 점검 (사람과 함께)

기본 스콥을 사람과 함께 점검한다. 모호한 지점은 임의로 정하지 말고 질문으로 닫는다(루프).

- **실행 가능성(환경 도달성) 점검** — 각 (예정) 말단의 수용 기준을 **그 카드를 실행할 주체가 현재 실행 환경에서 실제로 달성할 수 있는지** 확인한다. 라이브 DB·백엔드·브라우저·외부 시스템이 있어야만 확인되는 완료 기준은, 그 자원에 닿는 주체(예: VM 실행기·사람 운영자)만 달성할 수 있다. **실행기(다오)가 못 닿는 자원을 완료 기준으로 요구하는 카드를 실행기 카드로 만들지 않는다.** 닿는지 불확실하면 임의로 정하지 말고 질문으로 닫는다. 이 점검은 §3의 "누가" 분해를 대체하지 않고 그 위에 얹는다(누가 → 그 누가가 이 환경에서 되는가). → 분해 시 (a)코드 산출/(b)라이브 검증으로 가르는 규칙은 §3.

## 3. WBS로 정리 — 행위 주체 기준 로지컬씽킹

작업 진행 단계를 만들기 위해 **행위 주체(누가 하는가)를 1차 기준**으로 하위 태스크를 재배치·조정한다. 이 분해·검증은 **`logical-thinking` 스킬에 위임**한다 — MECE 방법론의 단일 출처라 여기서 다시 정의하지 않는다.

- **재배치**: `logical-thinking` 작업 A(MECE 분해) — 행위 주체를 1차 기준으로, 동일 기준 형제 브랜치·번호체계로 분해.
- **점검**: `logical-thinking` 작업 B(MECE 검증) — 중복(ME)·누락(CE)·분해 기준 일관성을 점검.
- **중복은 "경우(공통)"으로 묶어** 한 곳에 두고 나머지는 그것을 참조한다(단일 출처·효율성 보장).
- WBS는 스콥 문서 하단 또는 별도 문서에 둔다.
- **실행 가능성 분리 (코드 산출 ↔ 라이브 검증)** — 행위 주체로 나눈 뒤(§2 점검), 한 말단의 수용 기준이 (a) **실행기가 코드베이스만으로 달성 가능한 부분**(코드 작성·SQL 방언 확정·검증용 스크립트와 기대결과 산출)과 (b) **라이브 환경에서만 달성 가능한 부분**(실제 200 응답·화면 렌더·회귀 실측)을 함께 요구하면 **두 말단으로 분리**한다.
  - **(a) 실행기 카드** — 완료 기준 = repo 커밋(라이브 불요). 실행기 큐가 지금 처리.
  - **(b) 라이브 검증 카드** — 완료 기준 = 라이브 실행 증거. **그 환경에 닿는 주체(VM 실행기·사람 운영자)** 에 배정하고, 실행기가 헛claim 하지 않도록 사람·운영자 카드로 표시하거나 승인 게이트(§3.1)로 건다.
  - 간선은 **(a) → (b)** — 코드가 먼저 나오고 라이브 검증이 이어지게 한다(§3.1 간선 목록에 말단↔말단으로 기록).

### 3.1 WBS 산출물 표준 — 등록(unskein-wbs)이 그대로 주입할 수 있게

분해 시점에만 존재하는 지식(각 말단의 착수 정보·작업 순서)이 요약 문장으로 증발하지 않도록, 아래 두 산출물을 **말단(leaf) 단위**로 필수 산출한다. unskein-wbs는 "스콥 작성은 롤이 아니다" — 등록이 주입하려면 **작성 측(여기)이 표준을 채워야** 한다.

- **각 말단 plan_doc 초안 (7요소)** — `unskein-wbs §4` 자기완결 표준에 맞춰 채운다: **[배경]·[전제]·[완료 기준]·[실행 정보]·[검증 방법]·[함정·실측]·[참조]**. 실행자가 repo 클론 + 해당 카드 + 루트 카드만으로 탐색 없이 착수 가능한 수준으로 적는다. 해당 없는 요소는 "해당 없음"으로 명시(생략 금지).
- **의존 간선 목록 (말단 기준)** — 작업 순서 지식을 **말단 wbs_code 간선**으로 명시한다.
  - 형식: `후행 ← 선행` 을 한 줄 1간선 또는 표로 (예: `2.1.2.1 ← 2.1.1.1`).
  - 컨테이너 수준 서술(`1.1 → 1.2`)은 **사람용 요약으로만** 허용하고 **간선 목록의 원천으로 쓰지 않는다** — 게이트는 말단↔말단만 본다(컨테이너 간선은 우회·과차단, `unskein-wbs §1.1`).
  - 각 말단 plan_doc의 **[전제]와 간선이 일치**해야 한다(간선의 선행은 전제에, 전제의 선행 카드는 간선에).
  - **사람 승인 게이트**가 필요한 스콥은 "**진입 말단들 ← 승인 카드**" 간선으로 표현한다 — 승인 카드를 done 처리해야 다오가 진입 카드를 잡는 구조.

## 4. 대상 프로젝트 확정 (등록 project_id)

등록 대상 `project_id` 는 **§0 ②에서 이미 확정**됐다 — `planner.env` 의 `UNSKEIN_BUSINESS`/`UNSKEIN_PROJECT` 이름으로 서버에서 프로젝트를 특정하고 `repo_url` 까지 얻었다. 여기선 그 `project_id` 를 등록 대상으로 삼는다. 사람이 비즈니스/프로젝트 이름을 매번 외워 넣지 않게, 그리고 코드베이스가 없어도 프로젝트를 짚게 하는 게 `planner.env` 명시 변수의 취지다(ADR-0022).

- **정합 확인(코드베이스가 이미 있던 경우)**: 현재 repo 원격 `git -C "$CODEBASE" remote get-url origin` 이 §0 의 `repo_url` 과 **정규화 후 일치**하는지 본다(`.git` 접미 제거, `https://`↔`git@`(ssh) 호스트/경로 동치, 대소문자). 다르면 엉뚱한 repo·엉뚱한 프로젝트이니 멈추고 묻는다(fallback 금지).
- **§0 ②가 프로젝트를 못 짚었으면**(이름 오타·미가입·미등록, 또는 `UNSKEIN_BUSINESS`/`UNSKEIN_PROJECT` 미설정) 임의로 고르지 않고 **사람에게 묻는다** — 어느 비즈니스/프로젝트인지, 또는 프로젝트를 먼저 만들지. `repo_url` 미설정 프로젝트는 이름으로 특정하고, 확인 후 `repo_url` 을 채워 다음부터 자동 clone/pull 되게 한다.
- (하위호환 폴백) 이름 변수 없이 코드베이스만 이미 있으면, 그 원격 `repo_url` 을 `GET /api/businesses`→`GET /api/businesses/{biz}/projects`(둘 다 `X-Planner-Token`) 목록과 대조해 역매핑할 수 있다 — 정확히 하나 일치일 때만. 새 설치는 §0 명시 변수를 쓴다.
- 셀프 케이스(이 repo = unskein): `MUPAI STUDIO / UNSKEIN_SAAS`.

## 5. 서버 등록 — 정리된 plan_doc을 갖춰 올린다

정리된 WBS를 §4 에서 식별한 프로젝트의 작업 큐에 등록한다. 스콥이 이미 끝났으므로 **이 등록 단계의 산출은 "각 카드가 정리된 `plan_doc`(수용 기준)을 갖춘 상태"**다 — 빈 뼈대만 올리고 나중에 채우는 게 아니다.

- 등록 도구: 운영자 스킬 `unskein-wbs`(프로덕션 동기) 또는 admin API. **§3.1 산출물(말단 7요소 plan_doc 초안 + 말단 간선 목록)을 그대로 넘긴다** — unskein-wbs가 plan_doc을 자기완결(§4)로 주입하고, 간선을 말단 wbs_code→task id(환경별)로 변환·검증(§5)한다.
- 각 카드 = `title` · `wbs_code` · `parent_id` · `description` + **`plan_doc`(§3.1 7요소 자기완결)**. 루트 카드에는 스콥 전문을 싣는다(말단은 "루트 카드 plan_doc" DB 내부 참조 + repo 경로 병기).
- **메커니즘(주의)**: 생성 API(`POST /projects/{id}/tasks`, `TaskCreate`)는 `plan_doc`을 받지 않는다. 그래서 등록은 **(a) 카드 생성 → (b) `plan_doc` 부여** 두 동작이다:
  - backlog로 두고 기록만: `PATCH /tasks/{id}` 에 `plan_doc`.
  - 실행대기로 올리며 부여: `POST /tasks/{id}/plan`(`attach_plan`) — `plan_doc` 저장 + `backlog→plan`. 빈 `plan_doc`은 422/409로 거부(ADR-0009 게이트).
- `plan_doc`이 있으므로 카드는 실행대기(`plan`)로 올라갈 수 있고, 다오가 claim하면 이 `plan_doc`을 구현 사양으로 받아 곧장 구현한다.
