#!/usr/bin/env python3
"""모리 폴링 루프 — UnSkein 작업 큐를 무한 폴링하며 다오(claude -p)로 처리한다.

흐름:
  매 tick 마다 POST /api/mori/claim 으로 작업 1건 선점 시도.
  - 작업 있으면 run_once.process_task 로 한 바퀴 처리 (프롬프트 → claude -p →
    parse → report/question 회수). 처리 직후 곧바로 다음 tick (대기 없이 연속 처리).
  - 작업 없으면 INTERVAL 초 대기 후 재시도. 빈 tick 카운트 증가.

옵션 (env 또는 argv):
  UNSKEIN_LOOP_INTERVAL   빈 tick 시 대기 초 (기본 30).
  UNSKEIN_LOOP_MAX_EMPTY  연속 빈 tick 이 값에 도달하면 종료 (기본 0 = 무한).
  argv 로도 받음: `run_loop.py [INTERVAL] [MAX_EMPTY]`.

claim 응답에는 이미 heartbeat_at 이 기록되지만, claim 직후 한 번 더
heartbeat 를 찍어 처리 시작 시각을 명확히 남긴다.

SIGINT(Ctrl-C) 로 깔끔히 종료한다. stdlib 만 사용.
"""

import os
import signal
import sys
import time

import run_once
from run_once import (
    _claim_body,
    _post,
    apply_watch_args,
    parse_watch_args,
    process_task,
    resolve_watch_scope,
)

# Windows 등 비 UTF-8 콘솔(cp949 등)에서도 한글·기호 출력이 깨지지 않게 stdout/stderr 를 UTF-8 로 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# watch 대상 키워드(bis/prj 등)를 먼저 뽑아 env 보다 우선 적용하고,
# 남은 위치 인자만 INTERVAL/MAX_EMPTY 로 쓴다(기존 위치 인자 호환).
_wb, _wp, _positionals = parse_watch_args(sys.argv[1:])
apply_watch_args(_wb, _wp)

INTERVAL = int(os.getenv("UNSKEIN_LOOP_INTERVAL", "30"))
MAX_EMPTY = int(os.getenv("UNSKEIN_LOOP_MAX_EMPTY", "0"))

# 위치 인자: run_loop.py [INTERVAL] [MAX_EMPTY] (watch 키워드 제외 후)
if len(_positionals) >= 1:
    INTERVAL = int(_positionals[0])
if len(_positionals) >= 2:
    MAX_EMPTY = int(_positionals[1])

_STOP = False


def _on_sigint(signum, frame):
    global _STOP
    _STOP = True
    print("\n[loop] SIGINT 수신 — 현재 tick 후 종료합니다.", flush=True)


def heartbeat(task_id: int) -> None:
    """처리 시작 직후 heartbeat 1회. 실패해도 루프는 계속."""
    try:
        _post(f"/api/mori/tasks/{task_id}/heartbeat")
    except Exception as exc:  # noqa: BLE001 — heartbeat 실패가 처리 흐름을 막지 않게.
        print(f"[loop] heartbeat 실패 (무시): {exc}", flush=True)


def main() -> int:
    signal.signal(signal.SIGINT, _on_sigint)

    # preflight — 작업을 잡기 전에 클라이언트 준비 점검(미충족이면 폴링 시작 안 함).
    ok, lines = run_once.preflight()
    print("[preflight] 작업 전 준비 점검:", flush=True)
    for ln in lines:
        print(ln, flush=True)
    if not ok:
        print(
            "[preflight] 준비 미충족 — 폴링을 시작하지 않고 종료합니다(fallback 금지).",
            flush=True,
        )
        return 1

    # watch 대상 검증 — 잘못 지정했으면 폴링 시작 전에 멈춘다(조용한 전체 폴백 금지).
    ok, label = resolve_watch_scope()
    if not ok:
        print(f"[loop] watch 대상 오류 — {label}", flush=True)
        return 1

    print(
        f"[loop] 시작 — interval={INTERVAL}s max_empty="
        f"{MAX_EMPTY or '무한'} api={run_once.API_BASE} watch={label}",
        flush=True,
    )

    tick = 0
    empty_streak = 0
    processed = 0

    while not _STOP:
        tick += 1
        try:
            claim = _post("/api/mori/claim", _claim_body())
        except Exception as exc:  # noqa: BLE001 — backend 일시 장애로 루프 중단 안 함.
            print(f"[tick {tick}] claim 실패: {exc} — {INTERVAL}s 후 재시도", flush=True)
            empty_streak = 0  # 장애는 빈 tick 으로 세지 않는다.
            _sleep(INTERVAL)
            continue

        if not claim.get("claimed"):
            empty_streak += 1
            print(
                f"[tick {tick}] 빈 tick (연속 {empty_streak}) — "
                f"선점할 작업 없음",
                flush=True,
            )
            if MAX_EMPTY and empty_streak >= MAX_EMPTY:
                print(
                    f"[loop] 연속 빈 tick {empty_streak} >= max_empty "
                    f"{MAX_EMPTY} — 종료.",
                    flush=True,
                )
                break
            _sleep(INTERVAL)
            continue

        # 작업 선점됨 — 연속 처리 (대기 없이 다음 tick 으로).
        empty_streak = 0
        task = claim["task"]
        task_id = task["id"]
        title = task.get("title", "")
        print(
            f"[tick {tick}] claim task#{task_id} '{title}' "
            f"repo={task.get('repo_url') or ''}",
            flush=True,
        )
        heartbeat(task_id)

        try:
            rc = process_task(task)
        except Exception as exc:  # noqa: BLE001 — 한 작업 실패가 루프 전체를 죽이지 않게.
            print(f"[tick {tick}] task#{task_id} 처리 중 예외: {exc}", flush=True)
            try:
                _post(
                    f"/api/mori/tasks/{task_id}/question",
                    {"question": f"루프 처리 중 예외: {exc}"},
                )
            except Exception:  # noqa: BLE001
                pass
            rc = 1

        processed += 1
        outcome = "성공" if rc == 0 else "실패(question 회수)"
        print(f"[tick {tick}] task#{task_id} 처리 완료 — {outcome}", flush=True)
        # 처리 직후 곧바로 다음 tick (연속 처리). 대기하지 않는다.

    print(
        f"[loop] 종료 — 총 tick {tick}, 처리 {processed}건, "
        f"연속 빈 tick {empty_streak}",
        flush=True,
    )
    return 0


def _sleep(seconds: int) -> None:
    """SIGINT 에 반응하도록 1초 단위로 끊어서 대기."""
    for _ in range(seconds):
        if _STOP:
            return
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
