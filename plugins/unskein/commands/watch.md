---
description: 작업 큐를 주기적으로 감시하며 연속 처리 (폴링 루프)
---

# 작업 큐 감시 루프

UnSkein 작업 큐를 주기적으로 확인해, 처리할 작업이 있으면 다오를 구동하고 없으면 기다린다.

연결은 `unskein-connect` 참고.

옵션:
- `UNSKEIN_LOOP_INTERVAL` — 폴링 주기(초), 기본 30
- `UNSKEIN_LOOP_MAX_EMPTY` — 빈 폴링 N회 후 종료(0=무한), 기본 0

실행:
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_loop.py"
```
중단은 Ctrl+C.
