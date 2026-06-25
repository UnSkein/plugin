---
description: 작업 큐를 주기적으로 감시하며 연속 처리 (폴링 루프)
---

# 작업 큐 감시 루프

UnSkein 작업 큐를 주기적으로 확인해, 처리할 작업이 있으면 다오를 구동하고 없으면 기다린다.

연결은 `unskein-connect` 참고.

옵션:
- `UNSKEIN_LOOP_INTERVAL` — 폴링 주기(초), 기본 30
- `UNSKEIN_LOOP_MAX_EMPTY` — 빈 폴링 N회 후 종료(0=무한), 기본 0

watch 대상(바라볼 프로덕션 범위, 이름으로 지정 — 비우면 모든 비즈니스/프로젝트). 인자 또는 환경변수로 줄 수 있고, 인자가 환경변수보다 우선한다:

- 인자: `/unskein:watch bis "비즈니스이름" prj "프로젝트이름"`
  - `bis`(=`business`/`--business`/`-b`) 비즈니스 이름, `prj`(=`project`/`--project`/`-p`) 프로젝트 이름. 공백 있으면 따옴표로 묶는다. `bis=이름` 형식도 가능.
  - 위치 인자 `[INTERVAL] [MAX_EMPTY]` 는 그대로 호환된다(예: `/unskein:watch 10 0 bis "..."`).
- 환경변수: `UNSKEIN_WATCH_BUSINESS`, `UNSKEIN_WATCH_PROJECT`.

지정한 이름이 이 토큰의 멤버십에 없으면 폴링을 시작하지 않고 가능한 이름을 알려 멈춘다(조용히 전체로 넘어가지 않음). 가용 대상은 `/unskein:status` 로 확인한다.

실행(`$ARGUMENTS` 로 위 인자를 그대로 넘긴다):
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_loop.py" $ARGUMENTS
```
중단은 Ctrl+C.
