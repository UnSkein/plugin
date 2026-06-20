# unskein 플러그인

모리·다오 자동 개발 시스템의 실행 엔진. UnSkein 작업 큐를 폴링해 다오(`claude -p`)를 구동하고 결과를 회수한다.

## 담은 것

| 종류 | 항목 | 설명 |
|------|------|------|
| 오케스트레이터 | `orchestrator/run_once.py` | 작업 1건 선점 → 다오 한 바퀴 → 결과 회수 (폴링 없음) |
| 오케스트레이터 | `orchestrator/run_loop.py` | 작업 큐를 주기 폴링하며 연속 구동 |
| command | `/unskein:mori-once` | run_once 실행 |
| command | `/unskein:mori-loop` | run_loop 실행 |
| skill | `dao-output-contract` | 다오가 결과·질문을 모리가 파싱할 약속 형식으로 출력하는 규칙 |
| bin | `unskein-once`, `unskein-loop` | 셸에서 직접 실행하는 래퍼 |

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `UNSKEIN_API` | `http://localhost:8200` | SaaS 작업 큐 주소 |
| `UNSKEIN_MORI_TOKEN` | (필수) UnSkein 설정 화면에서 발급 | 모리 연결 토큰 |
| `UNSKEIN_CLAUDE_TIMEOUT` | `600` | `claude -p` 실행 타임아웃(초) |
| `UNSKEIN_LOOP_INTERVAL` | `30` | (loop) 빈 폴링 시 대기 초 |
| `UNSKEIN_LOOP_MAX_EMPTY` | `0` | (loop) 연속 빈 폴링 N회 후 종료, 0=무한 |

## 사용법

### Claude Code 안에서 (command)

```
/unskein:mori-once
/unskein:mori-loop
```

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
2. 작업 → 프롬프트 변환.
3. 작업 repo 경로에서 `claude -p "<prompt>" --output-format json --dangerously-skip-permissions` 실행.
4. stdout(JSON) 파싱 → `RESULT:` / `QUESTION:` 마커 추출.
5. `RESULT` → report, `QUESTION` → question 으로 UnSkein 에 회수.
