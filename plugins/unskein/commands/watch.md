---
description: 작업 큐를 주기적으로 감시하며 연속 처리 (폴링 루프)
---

# 작업 큐 감시 루프

UnSkein 작업 큐를 주기적으로 확인해, 처리할 작업이 있으면 다오를 구동하고 없으면 기다린다.

연결·인증은 `unskein-setup` 참고.

> **어느 서버를 보는지는 환경의 `UNSKEIN_API`+`UNSKEIN_MORI_TOKEN` 짝이 정한다** — 토큰은 그 서버 전용이라 안 맞으면 401. 로컬을 보려면 로컬 API+토큰, 테스트 서버를 보려면 그 서버의 API+토큰. 설정은 `$UNSKEIN_HOME/executor.env`(기본 `~/.unskein` — export 라 source 하면 자식에 상속) 하나에 담고 watch 전에 `source` 한다. **프로젝트 단위 격리**(한 머신 다중 프로젝트, ADR-0020)면 프로젝트마다 `source <프로젝트>/.unskein/executor.env` — 셋업이 그 파일 맨 위에 `UNSKEIN_HOME` 절대경로를 기록해 두므로 어느 cwd 에서든 그 파일 하나로 creds·work 까지 전부 확정된다(프로젝트별 watch 세션 1개 + 전용 mori 토큰 + disjoint 범위 — `unskein-setup` S0). 여러 서버를 오가면(드묾) `executor.local.env` 등으로 파일만 나눠 그 하나만 source(짝 분리 — `unskein-setup` S1).

옵션:
- `UNSKEIN_LOOP_INTERVAL` — 폴링 주기(초), 기본 30
- `UNSKEIN_LOOP_MAX_EMPTY` — 빈 폴링 N회 후 종료(0=무한), 기본 0

watch 대상(바라볼 범위 — 비우면 토큰 사용자의 모든 비즈니스/프로젝트). 인자 또는 환경변수로 줄 수 있고, 인자가 환경변수보다 우선한다:

- 인자: `/unskein:watch bis "비즈니스이름" prj "프로젝트이름"` — 이름으로 지정
  - `bis`(=`business`/`--business`/`-b`) 비즈니스 이름, `prj`(=`project`/`--project`/`-p`) 프로젝트 이름. 공백 있으면 따옴표로 묶는다. `bis=이름` 형식도 가능.
  - 위치 인자 `[INTERVAL] [MAX_EMPTY]` 는 그대로 호환된다(예: `/unskein:watch 10 0 bis "..."`).
- **task 서브트리 스코프**(ADR-0026): `/unskein:watch task 517`(=`--task`/`-t`/`task=517`/`task_id=517`) — 그 작업의 WBS 서브트리(자기 포함)만 선점한다. **개발자별 익스큐터가 한 프로젝트 안에서 자기 WBS 만 병렬 개발**하는 용도(예: A는 로그인 트리, B는 바인딩셋 트리). id 는 보드 상세패널 "복사" 가 주는 `task_id=<숫자>` 값이며 환경(로컬/프로덕션)별로 다르다. 병렬 운용 전제: 익스큐터별 **토큰 별도 발급** + 루트끼리 **서로소**(비조상) + 같은 머신이면 `UNSKEIN_HOME` 격리(ADR-0020).
- 환경변수: `UNSKEIN_WATCH_BUSINESS`, `UNSKEIN_WATCH_PROJECT`, `UNSKEIN_WATCH_TASK`.

지정한 이름이 이 토큰의 멤버십에 없으면 폴링을 시작하지 않고 가능한 이름을 알려 멈춘다(조용히 전체로 넘어가지 않음). 가용 대상은 `/unskein:status` 로 확인한다. task 루트가 없거나 범위 밖이면 서버가 404 로 알리고 폴링이 멈추며, **구서버**(task 스코프 미지원)에 붙으면 필터가 무시된 채 돌지 않도록 즉시 중단한다(에코 가드 — 서버 업데이트 필요).

> **범위 미지정 + 원격 서버는 시작이 거부된다**(여러 클라이언트가 같은 큐를 경쟁하는 사고 방지) — `bis/prj`(또는 `task`) 로 범위를 지정해 **단독 소유**하라. 의도적으로 전체를 보려면 `UNSKEIN_ALLOW_UNSCOPED=1`(로컬 서버는 가드 없음). 또 시작 직전 **preflight** 가 클라이언트 준비(다오 스킬 원본·런타임·서버 도달 등)를 점검해, 미충족이면 **큐를 건드리기 전에** 멈춘다.

실행(`$ARGUMENTS` 로 위 인자를 그대로 넘긴다):
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_loop.py" $ARGUMENTS
```
> watch 는 오래 도는 루프다 — **distro 가 떠 있는 상태로 그 안에서**, **설치된 플러그인**의 orchestrator 로 돌려야 살아 있다(`unskein-setup` S1 상주 환경·플러그인 설치 위치). 명령마다 distro 를 잠깐 켜는 방식이면 루프가 명령 종료와 함께 죽는다.

중단은 Ctrl+C.
