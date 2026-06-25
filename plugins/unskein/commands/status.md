---
description: 클라이언트 연결·등록 상태를 읽기 전용으로 점검
---

# 상태 점검

이 클라이언트의 연결·등록 상태(연결 정보, watch 대상, 자격증명, 작업 폴더, 서버 도달)를 읽기 전용으로 점검한다. watch 대상으로 지정할 수 있는 가용 비즈니스/프로젝트도 함께 보여주고, 지정한 대상이 유효한지 검증한다. 작업을 선점하지 않는다.

```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/status.py"
```
