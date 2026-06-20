---
description: UnSkein 작업 큐에서 한 건을 받아 한 바퀴 처리 (폴링 없음)
---

# 한 바퀴 실행

UnSkein 작업 큐에서 backlog/answered 작업 1건을 선점(claim)하고, 다오(claude -p)를 구동해 처리한 뒤 결과를 회수한다.

연결이 안 돼 있으면 먼저 `unskein-connect` 로 서버에 연결하세요.

그다음 실행한다:
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_once.py"
```
