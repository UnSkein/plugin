---
name: unskein-setup
description: 실행기(WSL distro)를 한 프로젝트용으로 한 번에 세운다 — 서버 연결·인증(executor.env 단일 파일) + 런타임·의존성 설치 + repo 클론 + 프로비저닝 검증·보완. 자격증명(토큰·SSH 키) 갱신도 재실행으로. connect·add-site 를 통합했다. 각 단계 idempotent(이미 된 건 스킵). 트리거 — 실행기 셋업, unskein-setup, 서버 연결, 클라이언트 연결, UnSkein 셋업, 모리 토큰 등록, 프로젝트 등록, 프로젝트 추가, 사이트 추가, 자격증명 갱신, 토큰 갱신, 토큰 회전, 토큰 교체, SSH 키 교체, 호스트 추가, 프로비저닝, 클론 검증, 런타임 설치, 프로젝트 격리, UNSKEIN_HOME, 다중 프로젝트, 상태 격리.
---

# UnSkein — 실행기 셋업 (한 프로젝트)

이 실행기(WSL distro)를 **한 프로젝트**를 처리할 수 있게 한 번에 세운다 — 서버 연결·인증부터 클론·의존성·검증까지. **1 watch 세션 = 1 프로젝트.** 한 distro 에서 여러 프로젝트를 돌리려면 프로젝트 디렉토리마다 상태 루트를 격리해(`UNSKEIN_HOME=<프로젝트>/.unskein` — S0, ADR-0020) 이 셋업을 반복한다: 코드(플러그인)는 전역 1벌 공유, 상태(env·creds·work)만 프로젝트별로 갈라진다. 클라이언트 주인(사용자)과 대화하며 진행한다.

- **각 단계는 idempotent** — 이미(수동으로) 된 건 감지해 **건너뛰고**, 안 된 것만 처리한다. 값이 빠지면 임의로 채우지 말고 **물어서 멈춘다**(fallback 금지).
- 비밀(토큰·키)은 화면·셸 기록에 남기지 않는다. 저장소 주소·git 설정에 토큰을 넣지 않는다.
- **전제**: 플러그인이 이 WSL distro 의 `claude` 에 **user 스코프**로 설치돼 있어야 한다(오케스트레이터·다오 스킬 원본이 `${CLAUDE_PLUGIN_ROOT}` 옆에서 돈다). 윈도우에만 있고 distro 엔 없으면 워커가 스킬을 못 찾는다.

> **범위 밖(별도)**: 실행기는 **개발까지**(다오가 코드검증=타입체크·빌드·유닛테스트) 준비한다. 화면·런타임 검증(TESTER)은 **머지 후 배포된 테스트서버**를 대상으로 하는 별도 단계다 — `docs/architecture/실행기-개발-검증-흐름.md` 참조. 그래서 이 셋업은 **앱을 기동하지 않는다.**

## S0. 배치 모드 — 상태 루트(`UNSKEIN_HOME`) 확정

이하 모든 상태 경로는 `$UHOME` = `${UNSKEIN_HOME:-$HOME/.unskein}` 기준이다(ADR-0020).

- **전역 단일**(기본): 이 distro 가 프로젝트 하나만 맡는다 → `UNSKEIN_HOME` 미설정, `$UHOME` = `~/.unskein`(종전과 동일 — 기존 실행기 무변경).
- **프로젝트 격리**: 한 distro 에서 여러 프로젝트 → **프로젝트 디렉토리에서 이 스킬을 실행**하면 `$PWD/.unskein` 을 `UNSKEIN_HOME` 으로 기본 제안한다. 확정 값은 **절대경로**로 executor.env **맨 위에** `export UNSKEIN_HOME=…` 로 기록한다(자기완결 — 이후 어느 cwd 에서든 `source <프로젝트>/.unskein/executor.env` 그 파일 하나로 creds·work 까지 전부 확정. `~` 축약·상대경로로 적지 않는다). source 를 깜빡해도 그 `.unskein` 아래(코드베이스)에서 띄우면 run_once 가 **cwd 폴백**으로 자동 로드한다(source 우선·cwd 폴백 — ADR-0021).
- **운용 전제(프로젝트 격리)**:
  1. 프로젝트(watch 세션)마다 **mori 토큰을 따로 발급**한다 — executor.env 복사 재사용(토큰 공유) 금지. 토큰이 같으면 서버 lease 펜싱(`executed_by`)이 두 워처를 구분하지 못해, 범위가 겹치는 순간 좀비 쓰기가 통과한다. watch 범위(`bis/prj`)는 프로젝트 간 disjoint.
  2. 기존 전역 `~/.unskein` 에서 프로젝트 홈으로 **이행**할 땐 그 프로젝트의 **in-flight 작업 0**(waiting/answered·단계 중간 없음)일 때만 — 대화턴 resume 은 작업 폴더 경로(cwd-slug)에 묶여 있어 홈 전환이 세션 이어받기를 끊는다.
  3. **전역 `~/.unskein` 무력화**(ADR-0021): 멀티프로젝트로 이행하면 전역을 `mv ~/.unskein ~/.unskein_back` 로 개명(또는 삭제)한다 — cwd 폴백이 대부분 경로의 조상인 전역 `~/.unskein` 을 주워 엉뚱한 프로젝트로 붙는 것을 막는다. preflight 가 프로젝트 모드에서 전역 잔존을 강력 경고하니, 뜨면 개명한다. (셋업이 이행이면 이 개명을 사용자 확인 후 수행한다.)
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

## (선택) 운영자 상태줄

운영자의 watch 세션 상단에 **작업디렉토리 · 컨텍스트 사용률 · 모델명**을 표시하고 싶으면(머신 1회, 사용자 전역 `~/.claude/`). 사용자에게 물어 **동의할 때만** 설치한다. (헤드리스 다오 `claude -p` 엔 안 보이고 인터랙티브 세션에만 뜬다. 플러그인은 statusLine 을 직접 실을 수 없어 — 설정상 미지원 — 이 단계로 opt-in 설치한다.)

1. 스크립트 복사: `mkdir -p ~/.claude && cp "${CLAUDE_PLUGIN_ROOT}/assets/statusline.py" ~/.claude/statusline.py`.
2. `~/.claude/settings.json` 을 **비파괴적으로** 패치 — 파일을 JSON 으로 읽어 **`statusLine` 키가 이미 있으면 건드리지 않고**(사용자 것 존중), 없을 때만 추가한다(다른 키·기존 값 전부 보존, 파일 없으면 새로 만든다):
   ```json
   "statusLine": { "type": "command", "command": "python3 ~/.claude/statusline.py" }
   ```
   ⚠️ 통짜 덮어쓰기 금지 — 반드시 로드→키 존재 확인→병합→저장.

## 자격증명 갱신 (재실행)

토큰 회전·SSH 키 교체·호스트 추가는 **이 스킬을 다시 돌려** S1 의 `executor.env` 값(또는 `creds/` SSH 키)을 갱신하고 S3 로 재검증한다. 교체 후 옛 토큰·공개키는 발급처(GitHub 등)에서 폐기하도록 안내한다. 값은 화면에 출력하지 않고 "설정됨/없음"만 알린다.
