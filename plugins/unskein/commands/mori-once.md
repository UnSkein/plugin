---
description: UnSkein 작업 큐에서 한 건을 선점해 다오로 한 바퀴 처리 (폴링 없음)
---

# 모리 — 한 바퀴 실행

UnSkein 작업 큐에서 backlog/answered 작업 1건을 선점(claim)하고, 다오(claude -p)를 구동해 처리한 뒤 결과를 회수한다.

먼저 아래 환경변수가 설정됐는지 확인한다:
- `UNSKEIN_API` (예: https://unskein.mupai.studio) — SaaS 작업 큐 주소
- `UNSKEIN_MORI_TOKEN` — (필수) UnSkein 설정 화면에서 발급한 내 모리 연결 토큰
- `UNSKEIN_GIT_TOKEN` 또는 `UNSKEIN_CRED_DIR/creds/.env` — HTTPS repo 클론·push 시 필요한 git 토큰 (SSH repo 면 `UNSKEIN_CRED_DIR` 에 개인키)

그다음 실행한다:
```shell
python3 "${CLAUDE_PLUGIN_ROOT}/orchestrator/run_once.py"
```
