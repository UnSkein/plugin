# unskein 플러그인

모리·다오 자동 개발 시스템의 실행 엔진. UnSkein 작업 큐를 폴링해 다오(`claude -p`)를 구동하고 결과를 회수한다.

## 담은 것

| 종류 | 항목 | 설명 |
|------|------|------|
| 오케스트레이터 | `orchestrator/run_once.py` | 작업 1건 선점 → 다오 한 바퀴 → 결과 회수 (폴링 없음) |
| 오케스트레이터 | `orchestrator/run_loop.py` | 작업 큐를 주기 폴링하며 연속 구동 |
| 오케스트레이터 | `orchestrator/status.py` | 연결·등록 상태 읽기 전용 점검 |
| command | `/unskein:run` | run_once 실행 (한 바퀴) |
| command | `/unskein:watch` | run_loop 실행 (감시 루프) |
| command | `/unskein:status` | 연결·등록 상태 점검 |
| skill | `unskein-setup` | 실행기를 한 프로젝트용으로 셋업 (서버 연결·인증 + 런타임·의존성 설치 + repo 클론 + 검증·보완, 자격증명 갱신 포함) |
| skill | `unskein-doctor` | 연결·실행 실패 진단·복구 안내 (status 스냅샷을 출발점으로 증상 → 원인 → 복구 → 재검증) |
| skill | `unskein-test` | 다오가 만든 화면을 CDP로 런타임 UI 검증 (CDP 설치 + start/remote/stop, 콘솔·네트워크 에러 수집·캡처) |
| 자식 규약 문서 | `orchestrator/CONTRACT.md` | 자식이 결과·질문을 오케스트레이터가 파싱할 약속 형식으로 출력하는 규약 |
| 자식 다오 스킬 | `dao-skills/` | 모리가 작업마다 다오 작업 폴더(`WORK_ROOT`)로 복사해 **자식 다오에게** 깔아주는 운영 규약(`CLAUDE.md`) + 단계 스킬 7개. **모리 자신의 스킬이 아니다** — `skills/` 와 달리 plugin 이 로드하지 않고, `WORK_ROOT` 에서 띄운 자식 다오 세션만 읽는다. |
| 다오 스킬 카탈로그 | `DAO-SKILLS.md` | 모리가 보는 **다오wsl 스킬 목록·용도** 참조 정보 — 다오wsl(작업 다오)에 어떤 스킬이 있고 언제 쓰는지. `dao-skills/` 의 각 `SKILL.md` 에서 자동 생성한다(직접 고치지 않는다). |
| bin | `unskein-once`, `unskein-loop` | 셸에서 직접 실행하는 래퍼 |
| bin | `gen-dao-catalog.py` | `dao-skills/` 에서 `DAO-SKILLS.md` 를 생성·점검(`--check`)한다. dao-skills 변경 시 다시 돌려 동기화한다. |
| bin | `planner-env.sh` | 플래너 스킬(scope·wbs·drawio·doctor)이 `source` 하는 인증 로드 — 프로젝트별 격리 `planner.env`(source 우선·cwd 폴백, ADR-0021)에서 `UNSKEIN_API`+`UNSKEIN_PLANNER_TOKEN` 을 올린다. |

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `UNSKEIN_API` | `https://unskein.mupai.studio` | SaaS 작업 큐 주소 |
| `UNSKEIN_MORI_TOKEN` | (필수) UnSkein 설정 화면에서 발급 | 모리 연결 토큰 |
| `UNSKEIN_CLAUDE_TIMEOUT` | `600` | `claude -p` 실행 타임아웃(초) |
| `UNSKEIN_GIT_TOKEN` | (HTTPS repo 시 필수) | git 클론·push 토큰. 호스트별 `UNSKEIN_GIT_TOKEN_<HOST>` 도 지원. 없으면 `creds/.env` 파싱 |
| `UNSKEIN_HOME` | `~/.unskein` | **상태 루트** — EXECUTOR 는 creds·work, PLANNER 는 `planner.env` 가 이 밑으로 파생된다. 한 머신 다중 프로젝트면 프로젝트마다 `<프로젝트>/.unskein` 으로 상태를 통째 격리(ADR-0020 실행기 · ADR-0021 플래너). 빈 값·`~`·상대경로는 정규화 |
| `UNSKEIN_PLANNER_TOKEN` | (PLANNER 필수) UnSkein 설정 화면에서 kind=planner 발급 | 플래너 등록 토큰 — `X-Planner-Token` 으로 등록 API(businesses·projects·tasks·plan) 인가. `planner.env` 에 담아 `bin/planner-env.sh` 가 로드(ADR-0013·0021). 모리 토큰과 다른 kind |
| `UNSKEIN_CRED_DIR` | `$UNSKEIN_HOME/creds` | 자격증명 폴더 (SSH 키 `id_ed25519`/`id_rsa`, `known_hosts`, `.env`, askpass 스크립트). 개별 재정의는 상태 분산 위험 — preflight 가 정합을 점검 |
| `UNSKEIN_WORK_ROOT` | `$UNSKEIN_HOME/work` | 다오가 repo 를 클론·작업하는 폴더. 개별 재정의는 상태 분산 위험 — preflight 가 정합을 점검 |
| `UNSKEIN_LOOP_INTERVAL` | `30` | (watch) 빈 폴링 시 대기 초 |
| `UNSKEIN_LOOP_MAX_EMPTY` | `0` | (watch) 연속 빈 폴링 N회 후 종료, 0=무한 |

## 사용법

### Claude Code 안에서 (command)

```
/unskein:run
/unskein:watch
/unskein:status
```

실행기를 한 프로젝트용으로 세울 때는 `unskein-setup` 스킬을 사용한다(서버 연결·인증·클론·검증 + 자격증명 갱신). 한 머신에서 여러 프로젝트를 돌리려면 프로젝트 디렉토리마다 `UNSKEIN_HOME=<프로젝트>/.unskein` 으로 상태를 격리해 셋업을 반복한다(1 watch 세션 = 1 프로젝트 + 프로젝트별 mori 토큰 — `unskein-setup` S0, ADR-0020). 작업이 안 돌면 `unskein-doctor` 로 진단·복구하고, 다오가 만든 화면을 실제로 확인할 때는 `unskein-test` 로 CDP 검증한다.

작업 다오(다오wsl)에 어떤 단계 스킬이 있고 언제 쓰는지는 [`DAO-SKILLS.md`](DAO-SKILLS.md) 카탈로그를 참조한다.

### 셸에서 직접 (bin)

```shell
# 한 바퀴
"${CLAUDE_PLUGIN_ROOT}/bin/unskein-once"

# 폴링 루프 (Ctrl+C 로 중단)
"${CLAUDE_PLUGIN_ROOT}/bin/unskein-loop"
```

`run_loop.py` 는 argv 로도 옵션을 받는다: `unskein-loop [INTERVAL] [MAX_EMPTY]`.

## 동작 흐름 (한 바퀴)

1. `POST /api/mori/claim` (`X-Mori-Token`) 으로 backlog/answered 작업 1건 선점.
2. 작업 → 프롬프트 변환 + `repo_url` 전송 방식(SSH/HTTPS)에 맞춰 git 자격증명 환경 구성.
3. `dao-skills/` 를 `UNSKEIN_WORK_ROOT` 로 복사 — 자식 다오가 `WORK_ROOT/CLAUDE.md`(운영 규약·단계 순서)와 `WORK_ROOT/.claude/skills/`(단계 스킬)를 읽도록 이식. 모리 자신이 아니라 **자식 다오에게** 깔린다.
4. `UNSKEIN_WORK_ROOT` 에서 `claude -p "<prompt>" --output-format json --dangerously-skip-permissions` 실행. 다오가 prompt 지시대로 repo 를 클론(없으면)·작업·push.
5. stdout(JSON) 파싱 → `RESULT:` / `QUESTION:` 마커 추출 (자식 규약 문서 `orchestrator/CONTRACT.md`).
6. `RESULT` → report, `QUESTION` → question 으로 UnSkein 에 회수.
