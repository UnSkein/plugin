---
description: UnSkein 작업 큐에서 한 건을 받아 한 바퀴 처리 (폴링 없음)
---

# 한 바퀴 실행

UnSkein 작업 큐에서 backlog/answered 작업 1건을 선점(claim)하고, 다오(claude -p)를 구동해 처리한 뒤 결과를 회수한다.

연결이 안 돼 있으면 먼저 `unskein-setup` 으로 서버 연결·셋업하세요.

watch 대상을 주면 그 비즈니스/프로젝트 범위에서만 1건을 선점한다. 비우면 모든 비즈니스/프로젝트가 대상. 인자가 환경변수보다 우선한다:

- 인자: `/unskein:run bis "비즈니스이름" prj "프로젝트이름"` (`bis`=`business`/`-b`, `prj`=`project`/`-p`, `bis=이름` 형식도 가능)
- 환경변수: `UNSKEIN_WATCH_BUSINESS`, `UNSKEIN_WATCH_PROJECT`

지정한 이름이 멤버십에 없으면 선점 전에 멈추고 가능한 이름을 알려 준다.

그다음 실행한다(`$ARGUMENTS` 로 위 인자를 그대로 넘긴다):
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_once.py" $ARGUMENTS
```
