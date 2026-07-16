---
name: unskein-setup
description: 셋업 단일 진입점 — 토큰만 있으면 시작한다(~/.unskein/setup.env 에 토큰 값 한 줄, 호출 위치 무관). 역할을 몰라도 서버가 토큰 종류(kind)로 판별해(R0, /api/whoami · ADR-0027) EXECUTOR/PLANNER/TESTER 절차로 분기하고, 설치할 프로젝트도 멤버십 목록(whoami businesses)을 질문창으로 띄워 고르게 하며, 작업 디렉토리도 이름을 물어 셋업이 만든다. 실행기(WSL distro)를 한 프로젝트용으로 한 번에 세운다 — 서버 연결·인증(executor.env 단일 파일) + 런타임·의존성 설치 + repo 클론 + 프로비저닝 검증·보완. 자격증명(토큰·SSH 키) 갱신도 재실행으로. connect·add-site 를 통합했다. TESTER(kind=tester)도 프로비저닝한다 — 프로젝트별 tester.ps1·CDP 프로필/포트·cases 번들로 한 윈도우 호스트가 여러 프로젝트 TEST 를 격리 담당(§T). PLANNER 는 동봉 가이드로 이어 진행. 사용자 프로세스의 단계 스킬 plugin 설치→능력 신고 확인→정의 등록·연결→첫 카드 실증도 이 스킬이 안내한다(§S5 — frame9 개통 실측의 일반화). 설치 시 서버의 프로젝트 설명을 PROJECT.md 파일로 저장해 신규 유닛이 "무엇을 하는 프로젝트인지"를 안다(R0-4 — 프로젝트 오리엔테이션). 각 단계 idempotent(이미 된 건 스킵). 트리거 — 실행기 셋업, unskein-setup, 처음 시작, 온보딩, 역할 판별, 토큰 받음, whoami, 서버 연결, 클라이언트 연결, UnSkein 셋업, 모리 토큰 등록, 프로젝트 등록, 프로젝트 추가, 사이트 추가, 자격증명 갱신, 토큰 갱신, 토큰 회전, 토큰 교체, SSH 키 교체, 호스트 추가, 프로비저닝, 클론 검증, 런타임 설치, 프로젝트 격리, UNSKEIN_HOME, 다중 프로젝트, 상태 격리, TESTER 셋업, tester 프로비저닝, 화면검증기 셋업, tester.ps1, CDP 프로필, 멀티 프로젝트 TEST, 병렬 검증 격리, 테스터 토큰 발급, 멤버십 추가, 단계 스킬 설치, 스킬 플러그인 설치, 프로세스 스킬 설치, 능력 신고 확인, 능력표, 프로세스 정의 등록, 프로세스 연결, 사용자 프로세스 개통, 실행기 스킬 추가, 프로젝트 설명, 프로젝트 오리엔테이션, PROJECT.md, 무슨 프로젝트인지.
---

# UnSkein — 실행기·검증기 셋업 (프로젝트별)

이 실행기(WSL distro)를 **한 프로젝트**를 처리할 수 있게 한 번에 세운다 — 서버 연결·인증부터 클론·의존성·검증까지. **1 watch 세션 = 1 프로젝트.** 한 distro 에서 여러 프로젝트를 돌리려면 프로젝트 디렉토리마다 상태 루트를 격리해(`UNSKEIN_HOME=<프로젝트>/.unskein` — S0, ADR-0020) 이 셋업을 반복한다: 코드(플러그인)는 전역 1벌 공유, 상태(env·creds·work)만 프로젝트별로 갈라진다. 클라이언트 주인(사용자)과 대화하며 진행한다.

> **이 스킬이 셋업의 단일 진입점이다.** 역할을 모르면 **R0**(토큰 → 서버 판별)부터. 직접 프로비저닝은 두 종류 — **EXECUTOR**(kind=mori · WSL 헤드리스 · 코드개발까지 — 아래 **S0–S4**, 사용자 프로세스의 단계 스킬 설치는 선택 절 **§S5**) 와 **TESTER**(kind=tester · 윈도우 네이티브 · CDP 화면검증 — **§T**). S0–S4 는 EXECUTOR 기준이고, TESTER 는 §T 에서 같은 `UNSKEIN_HOME`-식 상태 격리를 **윈도우/PowerShell·프로젝트별 번들**로 편다(한 윈도우 호스트가 여러 프로젝트 TEST 를 로그인·토큰·포트·산출물 안 섞이게 담당). **PLANNER**(kind=planner)는 동봉 가이드(`${CLAUDE_PLUGIN_ROOT}/docs/플래너설치.md`)를 이 세션이 이어서 진행한다. 역할을 이미 알면 S0/§T/플래너 문서로 직행해도 된다.

- **각 단계는 idempotent** — 이미(수동으로) 된 건 감지해 **건너뛰고**, 안 된 것만 처리한다. 값이 빠지면 임의로 채우지 말고 **물어서 멈춘다**(fallback 금지).
- 비밀(토큰·키)은 화면·셸 기록에 남기지 않는다. 저장소 주소·git 설정에 토큰을 넣지 않는다.
- **전제**: 플러그인이 이 WSL distro 의 `claude` 에 **user 스코프**로 설치돼 있어야 한다(오케스트레이터·다오 스킬 원본이 `${CLAUDE_PLUGIN_ROOT}` 옆에서 돈다). 윈도우에만 있고 distro 엔 없으면 워커가 스킬을 못 찾는다.

> **범위 밖(별도)**: 실행기는 **개발까지**(다오가 코드검증=타입체크·빌드·유닛테스트) 준비한다. 화면·런타임 검증(TESTER)은 **머지 후 배포된 테스트서버**를 대상으로 하는 별도 단계다 — `docs/architecture/실행기-개발-검증-흐름.md` 참조. 그래서 이 셋업은 **앱을 기동하지 않는다.**

## R0. 진입 — 토큰으로 역할 판별 (매뉴얼 없이 시작, ADR-0027)

처음 시작하는 사용자에게 필요한 것은 셋뿐이다: **Claude Code + 이 플러그인 + 관리자가 보내준 토큰**. 자기 역할(익스큐터/플래너/테스터)은 몰라도 된다 — 역할은 토큰 발급 시점에 kind 로 이미 선언됐고(ADR-0013), 서버가 알려준다. **사람에게 역할을 되묻지 않는다.**

1. **입수 파일(부트스트랩) 작성 — 위치 고정 `~/.unskein/setup.env`**: 홈 상태 루트에 만들어(없으면 `mkdir -p ~/.unskein`, 파일 권한 600) 관리자에게 받은 **토큰 값 한 줄만** **사용자가 편집기로 직접** 넣는다 — KEY=VALUE 형식이 아니다(이 파일은 비밀 전달용이지 env 파일이 아니다):
   ```
   unsk_…   ← 토큰 값 그대로 한 줄
   ```
   - 🔒 **토큰 값은 대화(프롬프트)에도 붙여넣지 않는다** — 대화는 세션 기록으로 디스크에 남고 모델 컨텍스트로도 나간다. 셸 인자·화면 출력도 같은 이유로 금지. 유일한 경로는 "편집기 → 파일".
   - **서버 주소는 비밀이 아니다** — 파일에 넣지 않고 대화에서 묻는다(관리자 안내에 토큰과 함께 온 값).
   - 위치가 홈으로 고정이라 **스킬은 어느 디렉토리에서 호출해도 된다** — 작업 디렉토리는 4에서 셋업이 만들어 주므로 사용자가 미리 위치를 설계할 필요가 없다. 윈도우(테스터 후보) 세션이면 `%USERPROFILE%\.unskein\setup.env`.
   - 이 파일은 **입수용 임시본**이지 최종 저장소가 아니다 — 7에서 역할 정본으로 옮긴 뒤 지운다.
2. **역할 판별** (역할 중립 헤더 — 어떤 kind 든 이 라우트가 받는다). 세션은 **값을 열람·출력하지 않는다**(`cat` 단독 실행 금지) — 셸이 파일을 읽어 변수로 올리고, 명령은 변수 참조로만 쓴다. 개행·공백은 제거한다(윈도우 편집기 CRLF 대비):
   ```bash
   # WSL/bash — UNSKEIN_API 는 대화로 받은 서버 주소
   UNSKEIN_TOKEN=$(tr -d '[:space:]' < ~/.unskein/setup.env)
   curl -s "$UNSKEIN_API/api/whoami" -H "X-Unskein-Token: $UNSKEIN_TOKEN"
   # → {"ok":true,"kind":"mori","name":"<토큰 라벨>","user":"<소유자>",
   #    "businesses":[{"name":"<비즈니스>","description":"<비즈니스 설명|null>",
   #      "projects":[{"name":"<프로젝트>","repo_url":"<repo>","description":"<프로젝트 설명|null>"}]}]}
   #    (신서버 — 설명 미등록이면 null. 구서버는 description 필드 자체가 없다)
   ```
   ```powershell
   # 윈도우/PowerShell — 값 미출력 로더
   $token = (Get-Content -Raw "$env:USERPROFILE\.unskein\setup.env").Trim()
   curl.exe -s "$env:UNSKEIN_API/api/whoami" -H "X-Unskein-Token: $token"
   ```
3. **설치 대상 선택 (질문창)**: 응답의 `businesses`(이 토큰의 멤버십 = 설치 가능 범위)를 **질문창(AskUserQuestion)** 선택지로 띄워 "어느 프로젝트를 설치할지" 고르게 한다 — 라벨은 `<비즈니스> / <프로젝트>`, 선택지 설명에는 응답의 프로젝트 `description` 요약을 싣고(무엇을 하는 프로젝트인지 보고 고르게 — 없으면 생략), 항목이 하나뿐이면 그걸 권장으로 표시. 사용자에게 이름을 타이핑시키지 않는다(오타·이름 불일치 차단).
   - **목록이 비어 있으면**(`businesses: []`): 이 토큰 사용자가 어느 사이트의 멤버도 아니다 — 관리자에게 **멤버십 추가**를 요청하도록 안내하고 멈춘다(§T0-선결과 동종. 디렉토리를 만들어도 해결되지 않는다).
   - **구서버**(응답에 `businesses` 필드 없음): kind 별 자기 라우트로 조회한다 — mori/tester 는 `GET /api/mori/scope`(X-Mori-Token), planner 는 `GET /api/businesses`+`…/projects`(X-Planner-Token). 그것도 안 되면 사용자에게 비즈니스/프로젝트 이름을 직접 묻는다.
   - 선택된 프로젝트의 `repo_url` 은 이후 단계의 입력이다(익스큐터 S1 repo 주소·S2 실클론, 플래너 코드베이스 clone).
4. **작업 디렉토리 생성 (질문창)** — mori/planner 만(tester 는 §T 번들 규약이 이 역할을 대신한다): 프로젝트가 정해졌으니 이 유닛의 작업 디렉토리를 **셋업이 만든다**. **질문창으로 디렉토리 이름(경로)을 확인**한다 — 기본 제안 `~/<프로젝트이름>`(예: `~/WebApp`), 다른 위치·이름을 원하면 직접 입력. 확정되면 `mkdir -p <디렉토리>/.unskein` — 이 `.unskein` 이 상태 루트다.
   - **mori** → S0 배치 모드가 이 값으로 확정된다: `UNSKEIN_HOME=<디렉토리>/.unskein`(프로젝트 격리). **프로젝트가 하나여도 이 배치가 신규 설치의 표준** — 두 번째 프로젝트가 와도 이행이 없다(전역 단일 `~/.unskein` 배치는 기존 설치 호환으로만 유지).
   - **planner** → 이 디렉토리가 **작업폴더**다: `<디렉토리>/.unskein/planner.env`, 코드베이스는 scope §0 이 `<디렉토리>/<repo 이름>/` 으로 클론.
   - 사용자가 디렉토리를 미리 만들 필요도, 특정 위치에서 스킬을 부를 필요도 없다 — 위치는 여기서 묻고 생성은 셋업이 한다.
   - **프로젝트 오리엔테이션 생성(`PROJECT.md`)**: 디렉토리를 만들면 whoami 응답의 비즈니스·프로젝트 `description` 을 `<디렉토리>/PROJECT.md` 파일로 저장한다(멱등 — 재실행 시 서버 값으로 갱신. 테스터 번들은 §T1 이 같은 형식으로 생성). 신규 유닛(플래너/실행기/테스터)이 "이 프로젝트가 무엇을 하는 프로젝트인지"를 여기서 읽는다 — env·creds 만 있고 프로젝트 맥락이 없는 설치를 만들지 않는다. 세션은 생성 직후 그 설명을 사용자에게 한 줄로 보여준다. 형식(값은 서버 응답 그대로 — 지어내지 않는다):
     ```markdown
     # <프로젝트 이름> — 프로젝트 오리엔테이션
     - 비즈니스: <비즈니스 이름> — <비즈니스 description, 없으면 "설명 없음">
     - 서버: <UNSKEIN_API> / repo: <repo_url, 없으면 "미설정">
     - 갱신: <날짜> · 출처 <조회 API — whoami 또는 projects 목록> — 단일 출처는 서버 설명이다. 이 파일은 셋업이 생성·갱신하니 직접 고치지 말고 화면(프로젝트 설정)에서 수정한다.

     ## 이 프로젝트가 하는 일
     <프로젝트 description 본문>
     ```
     - **설명이 비어 있으면**: 본문 자리에 "서버에 프로젝트 설명이 등록돼 있지 않습니다 — 화면(프로젝트 설정)에서 owner/admin 이 채운 뒤 셋업을 재실행하면 이 파일이 갱신됩니다"를 적고, 세션도 같은 내용을 사용자에게 알린다(지어내지 않음). **구서버**(whoami 응답에 `description` 필드 없음)면 본문 자리에 "설명 미제공(구서버 — 서버 업데이트 필요)"로 적는다.
5. **kind 로 분기** (3의 선택값·4의 디렉토리를 그대로 주입):
   - **`mori`** (EXECUTOR — 개발 실행기) → 아래 **S0–S4** 로 계속. 이 토큰이 S1 의 `UNSKEIN_MORI_TOKEN`, 선택값이 `UNSKEIN_WATCH_BUSINESS`/`UNSKEIN_WATCH_PROJECT` 다.
   - **`tester`** (TESTER — 화면검증, **윈도우**) → **§T** 로. 선택값이 번들 이름 `<business>__<project>` 다. 지금 세션이 WSL 이면 프로비저닝 대상은 윈도우 호스트 쪽임을 안내한다(CDP Chrome 은 윈도우 프로세스).
   - **`planner`** (PLANNER — 스코프·플랜 등록) → 동봉 가이드 `${CLAUDE_PLUGIN_ROOT}/docs/플래너설치.md` 절차를 **이 세션이 이어서 진행**한다(planner.env 작성 — 템플릿 `${CLAUDE_PLUGIN_ROOT}/templates/planner.env.sample` — + 코드베이스 clone 검증). 이 토큰이 `UNSKEIN_PLANNER_TOKEN`, 선택값이 `UNSKEIN_BUSINESS`/`UNSKEIN_PROJECT` 다.
6. **오류 처리** (fallback 금지 — 조용히 넘기지 않는다):
   - **401** = 토큰 무효(오타·폐기·비활성) → 관리자에게 재발급/확인 요청. kind 를 추측해 진행하지 않는다.
   - **404**(라우트 없음) = 구서버(whoami 미배포) → 사용자에게 역할을 **명시적으로 묻고** 답에 따라 분기한다(드러난 질문이지 폴백이 아니다).
   - 연결 실패 = 서버 주소·네트워크부터 확인.
7. **승격·정리** (해당 역할 절차 안에서 수행): 토큰을 역할 **정본**으로 옮겨 적은 뒤 `~/.unskein/setup.env` 는 **삭제**한다 — 같은 비밀을 두 곳에 남기지 않는다(무잔존·역할별 단일 파일).
   - mori → `<디렉토리>/.unskein/executor.env` 의 `UNSKEIN_MORI_TOKEN` (S1).
   - planner → `<디렉토리>/.unskein/planner.env` 의 `UNSKEIN_PLANNER_TOKEN`.
   - tester → 정본은 **윈도우 번들** `%USERPROFILE%\.unskein\<business>__<project>\tester.ps1` 의 `$env:UNSKEIN_MORI_TOKEN`(§T — bash env 파일이 아니다). 옮겨 적고 setup.env(WSL 쪽이었다면 그쪽 파일)를 삭제한다.

**디렉토리 구성은 셋업의 산출물이다** — 역할이 정해져야 산출물(executor.env / planner.env / 테스터 번들)이 정해지고, 폴더도 4에서 셋업이 만든다(설치 가이드 3종·다이어그램 "역할별 디렉토리 구성" 참조). 사용자가 미리 만들 것은 `~/.unskein/setup.env` 하나뿐이고, 스킬 호출 위치는 무관하다.

## S0. 배치 모드 — 상태 루트(`UNSKEIN_HOME`) 확정

이하 모든 상태 경로는 `$UHOME` = `${UNSKEIN_HOME:-$HOME/.unskein}` 기준이다(ADR-0020).

- **전역 단일**(기본): 이 distro 가 프로젝트 하나만 맡는다 → `UNSKEIN_HOME` 미설정, `$UHOME` = `~/.unskein`(종전과 동일 — 기존 실행기 무변경).
- **프로젝트 격리**: 신규 설치 표준 — **R0-4 에서 셋업이 만든 `<디렉토리>/.unskein` 이 이 값이다**(R0 를 안 거친 수동 셋업이라면 프로젝트 디렉토리에서 이 스킬을 실행할 때 `$PWD/.unskein` 을 기본 제안). 확정 값은 **절대경로**로 executor.env **맨 위에** `export UNSKEIN_HOME=…` 로 기록한다(자기완결 — 이후 어느 cwd 에서든 `source <프로젝트>/.unskein/executor.env` 그 파일 하나로 creds·work 까지 전부 확정. `~` 축약·상대경로로 적지 않는다). source 를 깜빡해도 그 `.unskein` 아래(코드베이스)에서 띄우면 run_once 가 **cwd 폴백**으로 자동 로드한다(source 우선·cwd 폴백 — ADR-0021).
- **운용 전제(프로젝트 격리)**:
  1. 프로젝트(watch 세션)마다 **mori 토큰을 따로 발급**한다 — executor.env 복사 재사용(토큰 공유) 금지. 토큰이 같으면 서버 lease 펜싱(`executed_by`)이 두 워처를 구분하지 못해, 범위가 겹치는 순간 좀비 쓰기가 통과한다. watch 범위(`bis/prj`)는 프로젝트 간 disjoint.
  2. 기존 전역 `~/.unskein` 에서 프로젝트 홈으로 **이행**할 땐 그 프로젝트의 **in-flight 작업 0**(waiting/answered·단계 중간 없음)일 때만 — 대화턴 resume 은 작업 폴더 경로(cwd-slug)에 묶여 있어 홈 전환이 세션 이어받기를 끊는다.
  3. **전역 `~/.unskein` 은 그대로 둬도 된다**(ADR-0021): 격리는 위 명시 source + `UNSKEIN_HOME`(+ bashrc 전역 자동 로드 줄 제거)로 이미 된다 — 명시 source 는 cwd 폴백을 꺼서, 전역이 조상이어도 주워지지 않는다. 전역은 다른 역할(TESTER 등)·기존 설치의 상태 홈일 수 있어 **삭제를 강제하지 않는다.** 그 역할을 이 머신에서 안 쓰는 잔재라고 확인되면, 사용자 확인 후 `mv ~/.unskein ~/.unskein_back`(개명 — 되돌리기 가능)로 정리해도 된다(선택). preflight 는 활성 홈과 다른 전역의 존재를 **정보 줄**로 보여준다(경고·차단 아님).
  4. **프로젝트마다 새 셸** — 이전 프로젝트의 `UNSKEIN_MORI_TOKEN` 이 셸에 남으면 source 우선 원칙상 그게 이겨(cwd 폴백 무시) 엉뚱하게 붙는다. 프로젝트 전환 시 새 터미널에서 시작한다(preflight `[경로]`·watch 로 불일치가 드러난다).

## S1. 연결·인증 — `executor.env` 한 파일

〔검사: `$UHOME/executor.env` 에 API·모리토큰·git 토큰이 있고 `/api/health` 200 · `/api/mori/scope` 200 이며, **그 env 의 watch 범위가 이 셋업의 대상 프로젝트와 일치**하면 이 단계 스킵 — 멀쩡한 **전역** env 가 있다고 **프로젝트** 배치 생성을 건너뛰지 않는다(모드부터 S0 로 확정)〕

1. **파악**: 타겟 서버(`UNSKEIN_API`) · 이 실행기가 맡을 **프로젝트 하나**(비즈니스+프로젝트 이름 = watch scope) · 그 프로젝트 repo 주소·스택(node/python 등)·멤버십.
2. **`$UHOME/executor.env` 작성**(chmod 600) — 폴더가 아직 없으면 먼저 만든다: `mkdir -p "${UNSKEIN_HOME:-$HOME/.unskein}"` (프로젝트 격리 첫 셋업은 항상 이 경우). 템플릿 `${CLAUDE_PLUGIN_ROOT}/templates/executor.env.sample` 복사 후 **편집기로** 채운다(값은 export, 셸 인자로 넣지 말 것):
   - 프로젝트 격리 모드면 맨 위에 `UNSKEIN_HOME`(절대경로 — S0) 부터.
   - 서버: `UNSKEIN_API` + `UNSKEIN_MORI_TOKEN`(**kind=mori** — ⚠️ planner 아님, ADR-0013. 프로젝트 격리면 **이 프로젝트 전용으로 발급** — S0 전제 1).
   - git(HTTPS): `UNSKEIN_GIT_TOKEN`(clone/push) + `GH_TOKEN`(gh pr create, 같은 PAT 재사용 가능). / (SSH): 키 파일은 `$UHOME/creds/id_ed25519`(600), 경로는 `UNSKEIN_SSH_KEY`.
   - 선택: `ANTHROPIC_API_KEY`(다오 claude 로그인 대체) · `UNSKEIN_SUDO_PASSWORD`(프로비저닝 sudo — `build_git_env` 가 다오에서 strip).
   - 범위: `UNSKEIN_WATCH_BUSINESS` + `UNSKEIN_WATCH_PROJECT`(둘 다 지정 = disjoint).
3. **로드 방식** — 모드에 따라 갈린다:
   - **전역 단일**: 자동 로드 한 줄을 `~/.bashrc` 에 심어도 된다(매 셸 자동 로드): `set -a; [ -f ~/.unskein/executor.env ] && . ~/.unskein/executor.env; set +a`
   - **프로젝트 격리**: **bashrc 에 심지 않는다** — watch 세션마다 명시 `source <프로젝트>/.unskein/executor.env`. 기존 전역 자동 로드 줄이 bashrc 에 있으면 **제거를 안내**한다: 매 셸에 전역 env 가 깔리면 프로젝트 env 에 없는 변수(git 토큰·SSH 키 경로 `UNSKEIN_SSH_KEY`·`UNSKEIN_WATCH_*`·머지/test 정책)가 전역 값으로 남아, 잘못된 계정·신원·범위·정책으로 도는 레이어링 누출이 생긴다(SSH 키 경로 누출은 preflight 의 `SSH 자격 경로` `[경고]` 로 드러난다).
4. **환경 점검·생성**: `mkdir -p "${UNSKEIN_HOME:-$HOME/.unskein}/creds" "${UNSKEIN_HOME:-$HOME/.unskein}/work"` 로 상태 폴더를 **생성**한다(preflight 는 creds 부재를 치명으로 보고 선점 자체를 막는다 — 검사만 하지 말고 만든다. `$UHOME` 은 이 문서의 표기 약어일 뿐 셸 변수가 아니니 실행 명령엔 위처럼 풀어 쓴다). 이어 WSL 안 `claude`/`git`/`gh` 존재·인증(gh 는 `GH_TOKEN` env 또는 `gh auth login`) · `/api/health` 도달 + `/api/mori/scope` 200(토큰 유효). 없거나 미설정이면 설치·설정을 안내하고 멈춘다.

## S2. 프로비저닝 — 설치·클론·의존성

〔검사: 런타임·클론·의존성이 이미 있으면 각각 스킵〕

1. **런타임 설치**: 그 프로젝트 스택 런타임(node/python 등)을 WSL 에 설치. sudo 가 필요하면 `UNSKEIN_SUDO_PASSWORD`(S1)로 `sudo -S`, 또는 프로비저닝 명령만 NOPASSWD. 이미 있으면 버전만 확인.
2. **실클론**: 그 repo 를 자격증명으로 작업 루트(`$UHOME/work` — 개별 재정의 `UNSKEIN_WORK_ROOT` 는 가능하나 정상 배치에선 쓰지 않는다, 상태 분산)에 **실제 클론**한다(env/askpass·SSH — 토큰 무잔존). `ls-remote` 로 그치지 않는다 — 토큰·키가 end-to-end 로 도는지 확정. (이후 모리 `prepare_repo` 가 이 클론을 fetch·리셋으로 재사용.)
3. **의존성 설치**: 클론 안에서 프로젝트 의존성(`npm ci`/`pip install` 등)을 설치.
4. ⚠️ **앱을 기동하지 않는다** — 코드검증(빌드·유닛)까지만. 화면·런타임은 TESTER(머지 후 테스트서버).

## S3. 검증·보완 — "즉시 처리 가능" 게이트

1. **다오 스킬 심기 확인**: 다오 스킬 원본(`dao-skills/` 또는 `UNSKEIN_DAO_SKILLS`)이 작업 루트로 복사돼 `WORK_ROOT/CLAUDE.md` + `WORK_ROOT/.claude/skills/` 가 깔리는지(작업 때 모리가 매번 심지만 원본·경로 사전 검증).
2. **preflight 통과 확인**: `/unskein:status` 상당 — 다오 CLI·git·gh 인증·dao-skills·creds·work·서버 도달 전부. 하나라도 안 되면 **보완**(설치·자격증명·폴더 재시도).
3. 그래도 안 되면 사유(인증·네트워크·주소 형식·런타임 부재)를 **그대로 보여주고 멈춘다**(다른 값으로 우회 금지).
4. 통과하면 **"즉시 처리 준비 완료"** 를 알리고 다음을 안내한다:
   ```
   /unskein:status                                  # preflight + scope 검증
   /unskein:run bis "<비즈니스>" prj "<프로젝트>"    # 1건 사람 입회 실측 (진짜 개발 가능 증명)
   /unskein:watch                                   # 통과하면 자율 루프
   ```

## S4. 메모리 pull (사적 컨텍스트 복원 — 단말 이식)

〔검사: 이미 최신이면 `written=0`(멱등) — 재실행 무해. 자격증명·프로젝트 못 정하면 멈춰 드러낸다〕

새 단말에서 이 프로젝트의 **사적 메모리**를 서버에서 내려받아 로컬 `~/.claude/projects/<로컬 slug>/memory/` 에 복원한다(경로 무관 이식 — user-memory-db-sync §1.1.2). 소스 머신 slug 와 무관하게 **이 머신 cwd 로 slug 를 다시 만들어** 푼다(수용기준 8). `MEMORY.md` 는 원격 blob 을 받지 않고 로컬 파일들로부터 재생성한다.

```bash
# 이 프로젝트 env 가 source 돼 있어야 한다(S1 의 executor.env — 또는 플래너면 planner.env).
# 코드베이스 디렉토리(대화형 세션을 띄우는 곳)에서 실행하거나 --codebase 로 지정한다.
python3 "${CLAUDE_PLUGIN_ROOT}/bin/memory-sync.py" pull --codebase "<이 머신 코드베이스 경로>"
```

- **프로젝트 특정**: planner 토큰/JWT 면 `UNSKEIN_BUSINESS`+`UNSKEIN_PROJECT` **이름**으로 자동 해석한다. **mori 토큰만** 있는 실행기 셋업이면 이름 라우트(`/api/businesses`)가 kind 격리로 막히니 `UNSKEIN_PROJECT_ID` 를 executor.env 에 명시한다(project id 는 UI/플래너에서 1회 확인 — 토큰·`/api/mori/scope` 로는 id 가 안 나온다). 못 정하면 스크립트가 사유를 내고 멈춘다(fallback 금지).
- **역할 축**: 인자 없이 부르면 본인 메모리를 executor·operator·planner 전 역할로 받는다(같은 이름이 여러 role 에 있으면 대화형 우선 = planner 최종 승). 특정 role 만 원하면 `--role planner`.
- **자격증명 없으면 401 로 멈춘다** — 조용히 skip 하지 않는다. 프라이버시는 소유자 스코프(서버가 본인 `user_id` 행만 반환 — 타 사용자 메모리는 절대 안 온다).
- frontmatter 3축 규약(`project`/`role`/`scope` + `maturity` 예약)·기본값은 `bin/memory-sync.py` 헤더가 단일 출처다.

## S5. 단계 스킬 플러그인 설치 — 사용자 프로세스를 이 실행기가 집게 하기 (선택·재실행)

dev(기본 프로세스)만 돌리는 실행기는 이 절을 건너뛴다. **사용자 정의 프로세스**(예: frame9 폼 이관)의 AI 단계 카드를 이 실행기가 집으려면, 그 정의가 skill_key 로 지목하는 **단계 스킬이 이 distro 의 claude 에 plugin 으로 설치**돼 있어야 한다. 미설치면 실행기는 그 카드를 집지 않을 뿐이고 카드는 기다린다(pull 원칙 — 고장이 아니다). frame9_form 첫 개통(2026-07-16, EMAX/FRAMEWEB_FORM) 실측 절차의 일반화다.

전체 흐름과 소유 — 스킬 규격·생산(관문 ①~③)의 단일 출처는 `unskein-skill-creator` SKILL.md:

| 순서 | 무엇을 | 누가·어디서 |
|---|---|---|
| 1 | 단계 스킬 생산(골격·린트·매니페스트) → 스킬 plugin repo 에 push | 개발 세션 — `unskein-skill-creator`(관문 ①) |
| 2 | 스킬 plugin 설치·업데이트 + watch 재시작 | **실행기 운영자, 이 distro — S5.1 (사람 게이트)** |
| 3 | 능력 신고 확인(실행기 자동 신고 — 관문 ②③의 원천) | 자동(claim) + 운영자 확인 — S5.2 |
| 4 | 프로세스 정의 등록 · 프로젝트 연결 | 사람 JWT(owner/admin) — S5.3 (실행기 밖) |
| 5 | 첫 카드 끝-끝 실증 | 운영자 — S5.4 |

### S5.1 설치 (사람 게이트 = 이 행위)

〔검사: `claude plugin list` 에 그 스킬 plugin 이 원하는 버전으로 있으면 스킵〕

1. **unskein plugin ≥ 1.43.0** 확인(`claude plugin list`) — 설치 스킬 스캔·능력 신고·claim 단계 소비가 든 버전. 낮으면 먼저 업데이트한다(익스큐터설치 가이드의 marketplace update 경로).
2. **스킬 plugin 을 user 스코프로 설치·업데이트**한다 — unskein plugin 과 같은 경로(`claude plugin marketplace add <repo>` → `claude plugin install <plugin>@<marketplace>` → `claude plugin list` 로 버전 확인). 설치가 곧 "이 실행기가 그 프로세스를 집는다"는 **사람 게이트**다 — 서버에 별도 스킬 등록 절차는 없다(서버는 스킬 본문을 읽지 않는다 — 주입 경계).
3. **watch 루프 재시작** — 돌던 watch 는 새 설치를 모른다. 그 프로젝트의 watch 세션을 재시작해야 다음 claim 부터 신고·수행에 반영된다.
4. (선택) 표준 밖 위치의 스킬은 executor.env 에 `UNSKEIN_SKILL_SCAN_DIRS=<경로:경로>` 로 추가 스캔 루트를 준다 — 기본 스캔은 plugin 동봉 dev 6종 + `~/.claude/plugins` 아래 전부.

### S5.2 신고 확인 (자동 — 운영자는 확인만 한다)

실행기는 claim 마다 설치 스킬을 스캔해 **전이 계약 frontmatter(exits·output)가 있는 단계 스킬만** 폐쇄 메타(name·version·exits·output)로 자동 신고한다 — 일반 도구 스킬은 걸러져 능력표를 오염시키지 않는다(dev 동봉 6종만 이름 예외 통과). 확인:

- **화면**: 프로세스 관리 화면의 능력표(팔레트)에 그 스킬·버전이 뜨는지.
- **API**: `GET /api/businesses/{id}/capabilities` (사람 JWT).
- claim 응답에 skills 에코가 없는 **구서버**면 실행기는 dev 카드만 처리되는 축소 상태로 조용히 돌지 않고 **중단해 드러낸다**(fallback 금지) — 서버 업데이트가 선결.
- **신고가 안 보일 때 의심 순서**: ① 실행기 plugin 버전(신고 없음 + "마지막 사용"만 갱신되는 패턴이 시그니처) ② watch 재시작 누락(S5.1-3) ③ 스킬 frontmatter 의 exits·output 누락(관문 ① 린트로 확인).

### S5.3 정의 등록·프로젝트 연결 (사람 JWT — 실행기 밖, 순서만 여기 적는다)

실행기 프로비저닝 밖이지만 이게 안 되면 카드가 생성되지 않으므로 순서를 적는다. 둘 다 **사람 JWT 전용**이다(mori 토큰 불가) — 정의 등록·교체는 **owner/admin**, 프로젝트 연결은 **쓰기 권한(owner/admin/member — viewer 불가)**. 자동화 스크립트는 비밀이 대화에 남지 않게 **사용자 로컬 실행(getpass 로그인)** 방식으로 만든다.

1. **정의 등록**: `POST /api/businesses/{id}/processes`(교체는 `PUT /api/processes/{key}`) — 서버가 AI 단계(claim_kinds 비어 있지 않음)마다 skill_key ↔ **신고된 계약**(exits·output)을 대조한다(불일치 422). S5.2 신고가 먼저 완료돼 있어야 첫 등록부터 교차 검증이 동작한다.
2. **프로젝트 연결**: `PATCH /api/projects/{id}` 의 `default_process_key` — skill_key 완비 검증(누락 409). 연결 후 **새 루트 카드부터** 그 프로세스로 태어난다(기존 카드 불변).

### S5.4 첫 카드 끝-끝 실증

카드 1장을 올리고(카드의 **제목·설명은 실행기 프롬프트에 그대로 실린다** — 첫 단계 스킬이 읽을 입력을 설명에 적는다) 첫 AI 단계로 사람 전이(보드 드래그)한다. 실행기가 집는지(보드 선점 표시), 완료 보고로 다음 단계로 자동 전진하고 산출물이 정의된 슬롯에 쌓이는지 본다. 안 집으면 S5.2 의심 순서 → 정의 skill_key ↔ 스킬 name **정확 일치** 확인 → `unskein-doctor`.

## T. TESTER 프로비저닝 (kind=tester) — 화면검증기 (윈도우)

TESTER 는 **윈도우 네이티브**다(CDP Chrome 은 윈도우 프로세스라 WSL 루프백에서 못 닿는다 — 환경 필연 분리). EXECUTOR 와 같은 **상태 격리 사상**을 쓰되, 상태 루트가 `UNSKEIN_HOME` 대신 **프로젝트별 번들 디렉토리**다: 한 윈도우 호스트가 여러 프로젝트의 `test`(화면검증)를 **로그인·토큰·포트·산출물 안 섞이게** 담당한다. 코드(플러그인)는 전역 1벌 공유, 상태(토큰·CDP 프로필·cases)만 프로젝트별로 갈라진다. 근거: 설치가이드(윈도우) §2·§3·§5, `unskein-test` SKILL §0(자율 루프)·§3(포트↔프로필 = 인증 경계), ADR-0014(kind 스테이지 게이트).

### T0. 먼저 경로를 고른다 (둘 중 하나 — 번들이 필요한지 여기서 갈린다)

- **경로 1 — 단일 멀티멤버십 토큰(순차)**: 하나의 tester 토큰이 여러 사이트의 **멤버**이면, `UNSKEIN_WATCH_*` 를 **비운 bare** `node queue.js claim` 이 **멤버십 전체의 `test` 단계**를 라운드로빈으로 집는다. **이미 된다 — 프로젝트별 디렉토리·번들 불필요.** 단일 `tester.ps1` 하나로 "여러 프로젝트 순차 TEST" 가 된다. (⚠️ 경로 2 가 필요한 조건은 정확히 둘 — **같은 도메인에 다른 계정**(멀티테넌트: 쿠키는 도메인 단위 격리라 도메인이 서로 다르면 로그인이 달라도 한 프로필에서 안 섞인다) 또는 **병렬 검증**(한 프로필은 동시 실행 불가 + 선점 주체 분리). 도메인이 다 다른 순차 담당이면 경로 1 로 충분.)
- **경로 2 — 비즈니스별 토큰/사이트별 로그인(병렬·격리)**: 프로젝트마다 {토큰·API·WATCH, CDP 포트+프로필, cases}를 **격리한 번들**로 나눈다. 동시 병렬 검증·사이트별 로그인 분리에 필요. 아래 **T1–T3** 로 프로비저닝하고 CronCreate `*/5` 를 **config 마다** 건다.

### T0-선결. 멤버십·토큰 (스코프 게이트 — 디렉토리로 안 풀린다)

TESTER 가 집는 범위는 **그 토큰 사용자의 멤버십**으로 정해진다(kind 은 스테이지만 `test` 로 게이트할 뿐 범위를 넓히지 않는다 — ADR-0014, `queue.js scope`). **scope 밖 사이트는 번들을 만들어도 claim 되지 않는다** — 먼저 멤버십/토큰부터 붙인다:

1. **담당 가능 사이트 확인**: `node queue.js scope` → 대상 비즈니스/프로젝트가 목록에 있어야 한다. 없으면 아래 2·3 이 선결.
2. **멤버십 추가**(경로 1 을 넓히는 정석): 그 사이트에 **tester 토큰 사용자를 멤버로 추가**한다(운영자/플래너가 사이트 멤버 관리에서). 멤버가 되면 그 사이트의 `test` 가 그 토큰의 scope 에 들어온다.
3. **비즈니스별 tester 토큰 발급**(경로 2 격리용): 사이트마다 **전용 tester 토큰**을 발급해 lease 펜싱을 분리한다 — 사람 JWT 로:
   ```
   POST /api/me/mori-tokens   {"name":"tester-<business>__<project>","kind":"tester"}
   ```
   (⚠️ mori·planner 아님 — kind=`tester`. 웹 토큰 드롭다운에 tester 가 없을 때의 정식 경로.) 같은 사용자가 여러 비즈니스 멤버여도 config 마다 **다른 토큰**을 쓰면 두 tick 의 lease 를 서버가 구분한다(EXECUTOR S0 전제 1 과 동종 — 토큰 공유 금지).

> #519 처럼 **scope 밖**(예: business_id=16)으로 온 `test` 는 위 2/3 가 **선결**이다 — 디렉토리 생성으로 해결되지 않는다.

### T1. 번들 생성 (경로 2 · 프로젝트별) — idempotent

`%USERPROFILE%\.unskein\<business>__<project>\` 아래에 config 번들을 만든다(이미 있으면 스킵, 토큰·포트 갱신은 재실행으로 — EXECUTOR 의 `add-site` 에 대응해 **프로젝트 추가는 이 T1 을 다른 `<business>__<project>` 로 반복**):

```
%USERPROFILE%\.unskein\<business>__<project>\
  tester.ps1     # $env:UNSKEIN_API_BASE / UNSKEIN_MORI_TOKEN(kind=tester) / UNSKEIN_WATCH_BUSINESS / UNSKEIN_WATCH_PROJECT / CDP_PORT / CDP_PROFILE
  PROJECT.md     # 프로젝트 오리엔테이션 — 이 config 프로젝트의 서버 설명(R0-4 규약과 같은 형식·멱등)
  cdp\           # 이 config 의 포트↔프로필 페어링 기록(pairing.txt). 프로필 실체는 start.ps1 표준 위치 %USERPROFILE%\.cdp-chrome-<CDP_PROFILE>
  cases\         # 검증 산출물(리포트·스크린샷·시나리오). report 의 payload 엔 경로만 싣는다
```

- 템플릿 `${CLAUDE_PLUGIN_ROOT}/templates/tester.ps1.sample` 을 복사해 편집기로 채운다(값은 `$env:` — PowerShell 은 bash `export` 를 로드하지 않는다. 비밀은 화면·셸 인자로 넣지 말 것):
  ```powershell
  New-Item -ItemType Directory -Force "$env:USERPROFILE\.unskein\<business>__<project>\cdp","$env:USERPROFILE\.unskein\<business>__<project>\cases" | Out-Null
  Copy-Item "$env:CLAUDE_PLUGIN_ROOT\templates\tester.ps1.sample" "$env:USERPROFILE\.unskein\<business>__<project>\tester.ps1"
  ```
- **PROJECT.md 생성**: whoami 응답(R0-2)의 이 프로젝트 `description` 을 번들 루트 `…\<business>__<project>\PROJECT.md` 에 R0-4 형식으로 저장한다(멱등 — 재실행 시 서버 값으로 갱신, 설명이 비어 있으면 R0-4 의 "설명 없음" 규칙 그대로).
- **포트↔프로필 1:1 배정(충돌 금지)**: config 마다 **서로 다른 `CDP_PORT`**(9222, 9223, …)와 **서로 다른 프로필**(`CDP_PROFILE=<business>__<project>`)을 배정한다 — 인증(쿠키·JWT) 경계는 탭이 아니라 **프로필**이라, 안 나누면 로그인이 섞인다(`unskein-test` §3). `tester.ps1` 에 `$env:CDP_PORT` 를 박아두면 `remote.js` 명령마다 `--port` 를 안 붙여도 된다. 배정을 `cdp\pairing.txt` 에 한 줄로 남겨 다음 config 와 겹치지 않게 한다.

> 경로 1 이면 T1 을 건너뛴다 — 번들 없이 단일 `tester.ps1`(WATCH 빈 값) 하나면 된다.

### T2. 사전 준비·검증 (윈도우)

1. **윈도우 도구**: 시스템 Chrome · **윈도우 node18+**(`queue.js` 전역 fetch) · **Playwright(npm)**(`npm i -D playwright`, `npx playwright install` 불필요) · 윈도우 Claude Code — 설치가이드(윈도우) §2.
2. **플러그인 ≥1.25.0**(user 스코프) — tester 프로비저닝·자율 루프가 든 버전. `claude plugin list` 로 확인.
3. **토큰·스코프 검증**: config 를 dot-source 한 뒤 `node queue.js scope` **200 + 대상 사이트 노출**을 확인한다. `401`=kind 오배정/토큰 짝 어긋남, 대상 미노출=T0-선결(멤버십) 필요. 안 되면 사유를 **그대로 보여주고 멈춘다**(다른 값으로 우회 금지 — fallback 금지).

### T3. 실행 표준 (두 경로 — CronCreate 는 config 단위)

- **경로 1(단일 토큰·순차)**: **새 창**에서 단일 `tester.ps1` dot-source(`. tester.ps1`) → `UNSKEIN_WATCH_*` 를 비운 채 `node queue.js claim` 라운드로빈 → 검증 → report. 연속 운용은 CronCreate `*/5` **하나**. (사이트별 로그인이 같거나 무인증일 때 적합.)
- **경로 2(격리·병렬)**: config 마다 **새 창**에서 `. tester.ps1` →
  ```powershell
  & "$env:CLAUDE_PLUGIN_ROOT\skills\unskein-test\scripts\start.ps1" -Port $env:CDP_PORT -Profile $env:CDP_PROFILE
  # 한 tick: claim(--business/--project) → remote.js collect/attrs/shot → report --status=inspect|plan --doc=<cases\...> --payload=<cases\...>
  ```
  산출물은 그 config 의 `cases\` 에 남기고 payload 엔 경로만. 연속 운용은 CronCreate `*/5` 를 **config 마다** 건다. 한 tick 상세는 설치가이드(윈도우) §6.1 = `unskein-test` §0.2.

**격리 누출 방지(경로 2)**: ① config 마다 **다른 tester 토큰**(같은 토큰·겹치는 범위면 lease 펜싱이 두 tick 을 못 가른다 — T0-선결 3). ② config 마다 **새 창**(이전 config 의 `$env:UNSKEIN_MORI_TOKEN`·`CDP_PORT` 가 셸에 남으면 엉뚱하게 붙는다). ③ 포트·프로필 **1:1 고정**(공유 시 로그인 혼입).

### T-갱신. 재검증·회전 (재실행)

토큰 회전·포트 재배정·사이트 추가는 이 §T 를 다시 돌려 해당 config 의 `tester.ps1`(또는 새 `<business>__<project>` 번들)을 갱신하고 `node queue.js scope` 로 재확인한다. 교체 후 옛 토큰은 발급처에서 폐기하도록 안내한다. 값은 화면에 출력하지 않고 "설정됨/없음" 만 알린다.

## (선택) 운영자 상태줄

운영자의 watch 세션 상단에 **작업디렉토리 · 컨텍스트 사용률 · 모델명**을 표시하고 싶으면(머신 1회, 사용자 전역 `~/.claude/`). 사용자에게 물어 **동의할 때만** 설치한다. (헤드리스 다오 `claude -p` 엔 안 보이고 인터랙티브 세션에만 뜬다. 플러그인은 statusLine 을 직접 실을 수 없어 — 설정상 미지원 — 이 단계로 opt-in 설치한다.)

1. 스크립트 복사: `mkdir -p ~/.claude && cp "${CLAUDE_PLUGIN_ROOT}/assets/statusline.py" ~/.claude/statusline.py`.
2. `~/.claude/settings.json` 을 **비파괴적으로** 패치 — 파일을 JSON 으로 읽어 **`statusLine` 키가 이미 있으면 건드리지 않고**(사용자 것 존중), 없을 때만 추가한다(다른 키·기존 값 전부 보존, 파일 없으면 새로 만든다):
   ```json
   "statusLine": { "type": "command", "command": "python3 ~/.claude/statusline.py" }
   ```
   ⚠️ 통짜 덮어쓰기 금지 — 반드시 로드→키 존재 확인→병합→저장.

## 자격증명 갱신 (재실행)

토큰 회전·SSH 키 교체·호스트 추가는 **이 스킬을 다시 돌려** S1 의 `executor.env` 값(또는 `creds/` SSH 키)을 갱신하고 S3 로 재검증한다(EXECUTOR). TESTER 번들(`tester.ps1`)의 토큰 회전·포트 재배정·사이트 추가는 **§T-갱신** 으로 한다. 교체 후 옛 토큰·공개키는 발급처(GitHub 등)에서 폐기하도록 안내한다. 값은 화면에 출력하지 않고 "설정됨/없음"만 알린다.
