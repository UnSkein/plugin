#!/usr/bin/env python3
"""모리 조율자 루프 — UnSkein 작업 큐를 폴링하며 다오(claude -p)를 동시 구동한다.

흐름:
  풀에 여유 슬롯이 있는 한 매 tick 마다 POST /api/mori/claim 으로 작업을 선점하고,
  스레드 풀 워커에서 run_once.process_task 로 처리한다(작업별 격리 폴더 +
  주기적 heartbeat). 동시 한도는 UNSKEIN_MAX_CONCURRENCY. 풀이 가득 차면 슬롯이
  빌 때까지 대기하고, 선점할 작업이 없으면 INTERVAL 초 대기한다.

  단일 조율자 + 동시 다오 풀(ADR-0006). claim 은 조율자 스레드 한 곳에서만 하므로
  중복 선점이 없고(서버 SKIP LOCKED 가 이차 방어), 다오 실행만 워커로 흩어진다.

옵션 (env 또는 argv):
  UNSKEIN_LOOP_INTERVAL    빈 tick 시 대기 초 (기본 30).
  UNSKEIN_LOOP_MAX_EMPTY   연속 빈 tick 이 값에 도달 + 진행 중 0 이면 종료 (기본 0 = 무한).
  UNSKEIN_MAX_CONCURRENCY  동시 다오 수 (기본 3).
  UNSKEIN_HEARTBEAT_INTERVAL  작업별 heartbeat 주기 초 (기본 60).
  argv 로도 받음: `run_loop.py [INTERVAL] [MAX_EMPTY]`.

SIGINT(Ctrl-C) 로 깔끔히 종료한다 — 새 선점을 멈추고 진행 중 작업을 마저 기다린다.
stdlib 만 사용.
"""

import os
import signal
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

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
MAX_CONCURRENCY = max(1, int(os.getenv("UNSKEIN_MAX_CONCURRENCY", "3")))

# 위치 인자: run_loop.py [INTERVAL] [MAX_EMPTY] (watch 키워드 제외 후)
if len(_positionals) >= 1:
    INTERVAL = int(_positionals[0])
if len(_positionals) >= 2:
    MAX_EMPTY = int(_positionals[1])

_STOP = False


def _on_sigint(signum, frame):
    global _STOP
    _STOP = True
    print("\n[loop] SIGINT 수신 — 새 선점을 멈추고 진행 중 작업 완료 후 종료합니다.", flush=True)


def main() -> int:
    signal.signal(signal.SIGINT, _on_sigint)

    # 토큰 강제 — 폴링·선점에 모리 토큰이 필요하다(run_once 가 import-safe 하므로 여기서 막는다).
    if not run_once.MORI_TOKEN:
        print(
            "UNSKEIN_MORI_TOKEN 환경변수가 필요합니다. "
            "UnSkein 설정 화면에서 발급한 토큰을 넣으세요.",
            flush=True,
        )
        return 1

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

    # 자율 루프 안전 가드 — 범위 미지정 + 원격 서버는 막는다(두 모리 경쟁 사고 방지).
    block = run_once.autonomous_scope_block()
    if block:
        print(f"[loop] 시작 거부 — {block}", flush=True)
        return 1

    # watch 대상 검증 — 잘못 지정했으면 폴링 시작 전에 멈춘다(조용한 전체 폴백 금지).
    ok, label = resolve_watch_scope()
    if not ok:
        print(f"[loop] watch 대상 오류 — {label}", flush=True)
        return 1

    print(
        f"[loop] 시작 — interval={INTERVAL}s max_empty={MAX_EMPTY or '무한'} "
        f"concurrency={MAX_CONCURRENCY} api={run_once.API_BASE} watch={label}",
        flush=True,
    )

    # 버려진 작업폴더 GC(F) — 폴링 시작 전에 한 번(run_once 의 gc_work_root 미러 사용).
    run_once.gc_work_root()

    tick = 0
    empty_streak = 0
    processed = 0
    inflight: dict = {}  # future -> task_id

    def _drain_done() -> None:
        """완료된 future 를 회수해 결과를 찍는다."""
        nonlocal processed
        for fut in [f for f in inflight if f.done()]:
            tid = inflight.pop(fut)
            try:
                rc = fut.result()
                outcome = "성공" if rc == 0 else "실패(question 회수)"
            except Exception as exc:  # noqa: BLE001 — 한 작업 실패가 루프를 죽이지 않게.
                outcome = f"예외: {exc}"
                try:
                    _post(
                        f"/api/mori/tasks/{tid}/question",
                        {"question": f"루프 처리 중 예외: {exc}"},
                    )
                except Exception:  # noqa: BLE001
                    pass
            processed += 1
            print(
                f"[loop] task#{tid} 처리 완료 — {outcome} (진행 중 {len(inflight)})",
                flush=True,
            )

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        while not _STOP:
            _drain_done()

            if len(inflight) >= MAX_CONCURRENCY:
                # 풀이 가득 — 하나 끝날 때까지 잠깐 대기(회수는 다음 루프 _drain_done).
                wait(list(inflight), timeout=1, return_when=FIRST_COMPLETED)
                continue

            # 여유 슬롯 — 새 작업 선점 시도.
            tick += 1
            try:
                claim = _post("/api/mori/claim", _claim_body())
            except Exception as exc:  # noqa: BLE001 — backend 일시 장애로 루프 중단 안 함.
                print(f"[tick {tick}] claim 실패: {exc} — {INTERVAL}s 후 재시도", flush=True)
                empty_streak = 0  # 장애는 빈 tick 으로 세지 않는다.
                _sleep(INTERVAL)
                continue

            if claim.get("claimed"):
                empty_streak = 0
                task = claim["task"]
                task_id = task["id"]
                # 단일 작업 single-flight — 이미 진행 중인 task_id 는 재submit 하지 않는다.
                # 서버가 lease 만료/경합으로 같은 작업을 또 내줘도 같은 task_root 에서 두
                # 다오가 동시에 돌지 않게 막는 2차 방어(1차는 서버 lease). claim 이 이미
                # heartbeat 를 찍었으니 다음 claim 부터 서버가 이 작업을 자동 배제한다.
                if task_id in inflight.values():
                    print(
                        f"[tick {tick}] task#{task_id} 이미 진행 중 — 재submit 건너뜀",
                        flush=True,
                    )
                    continue
                print(
                    f"[tick {tick}] claim task#{task_id} '{task.get('title', '')}' "
                    f"repo={task.get('repo_url') or ''} "
                    f"(진행 중 {len(inflight) + 1}/{MAX_CONCURRENCY})",
                    flush=True,
                )
                inflight[pool.submit(process_task, task)] = task_id
                continue  # 여유 있으면 대기 없이 바로 다음 선점.

            # 빈 tick — 선점할 작업 없음.
            empty_streak += 1
            print(
                f"[tick {tick}] 빈 tick (연속 {empty_streak}) — 선점할 작업 없음 "
                f"(진행 중 {len(inflight)})",
                flush=True,
            )
            if MAX_EMPTY and empty_streak >= MAX_EMPTY and not inflight:
                print(
                    f"[loop] 연속 빈 tick {empty_streak} >= max_empty {MAX_EMPTY} "
                    "+ 진행 중 0 — 종료.",
                    flush=True,
                )
                break
            _sleep(INTERVAL)

        # 종료 — 진행 중 작업을 마저 기다린다(취소하지 않음).
        if inflight:
            print(f"[loop] 종료 신호 — 진행 중 {len(inflight)}건 완료 대기...", flush=True)
            wait(list(inflight))
            _drain_done()

    print(
        f"[loop] 종료 — 총 tick {tick}, 처리 {processed}건, 연속 빈 tick {empty_streak}",
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
