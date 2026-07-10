#!/usr/bin/env python3
"""unskein-work — 익스큐터 세션이 '다오'가 되어 작업 한 건을 직접 처리한다.

run_once 는 claim 한 작업을 헤드리스 `claude -p`(자식 다오)로 처리한다. work.py 는
그 자식을 띄우지 않고, **현재 익스큐터 Claude Code 세션이 스스로 다오가 되어** 같은
작업 폴더(WORK_ROOT/<task_id>)에서 이식된 다오 스킬을 따라 구현→보고한다 — "셸
(헤드리스) 말고 함께" 모드. 운영자가 지켜보며 조종할 수 있어 화면검증·첫 케이스·
헤드리스가 반복 실패하는 작업에 쓴다.

run_once 의 배관을 그대로 재사용한다 — claim·스킬 이식·clone·프롬프트·마커 파싱·
보고·heartbeat. 유일하게 헤드리스 실행(run_dao)만 세션이 대체한다. 그래서 서버·전이·
마커 규약은 run/watch 와 100% 동일하다.

서브커맨드:
  prepare [watch args]   작업 1건 claim + 셋업(스킬 이식·clone·프롬프트 산출). 프롬프트와
                         작업 폴더를 출력하고, 세션이 오래 작업해도 claim lease 가 안 풀리게
                         **백그라운드 heartbeat 데몬**을 띄운다. 없으면 'NO_TASK'.
                         수동 모드라 **test 단계도 집는다**(항상 auto_advance_test) — test 는
                         CDP 화면검증(unskein-test)으로 수행해 inspect/plan 으로 옮긴다.
                         특정 작업만 하려면 `prepare task <id>` (ADR-0026 서브트리 스코프).
  report <task_id> [--marker-file F] [--payload-file P]
                         세션이 낸 RESULT/QUESTION 마커(파일 또는 stdin)를 읽어 회수
                         (report/question) + heartbeat 정지 + (done 이면) 작업폴더 정리.
                         --payload-file 은 단계 구조화 산출물(JSON — 예: 수동 test 의
                         CDP 검증 결과)을 task.payload[<출발단계>] 로 싣는다.
  heartbeat <task_id>    (내부) prepare 가 띄우는 heartbeat 루프. SIGTERM 까지 찍는다.
  release <task_id>      보고 없이 heartbeat 만 정지(중단 정리).

주의(헤드리스와 다른 점):
  - **세션 재개(--resume) 없음** — in-session 은 별도 claude 세션이 없다. answered 작업은
    답변을 프롬프트에 실어 이어서 진행하고, 다오가 막히면 운영자가 그 자리에서 답해 계속한다
    (웹 기록용으로 QUESTION 보고는 여전히 가능하나 session_id 는 안 싣는다).
  - **git 자격증명** — clone/fetch 는 prepare 가 git_env 로 결정적으로 수행한다. 이후 다오의
    push(inspect 단계)는 **익스큐터 세션 자신의 git/gh 인증**(executor.env + gh auth)을 쓴다
    — 헤드리스처럼 scrubbed 서브프로세스 env 를 주입하지 않는다.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_once as ro  # noqa: E402 — 배관 재사용(run_loop 와 같은 패턴)

META_NAME = ".unskein-work.json"
PID_NAME = ".unskein-work.hb.pid"


def _task_root(task_id: int) -> str:
    return os.path.join(ro.WORK_ROOT, str(task_id))


def _meta_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), META_NAME)


def _pid_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), PID_NAME)


# ---- heartbeat 데몬 (claim lease 유지) ----

def _spawn_heartbeat(task_id: int) -> int:
    """detached heartbeat 데몬을 띄우고 pid 를 pidfile 에 남긴다."""
    self_path = os.path.abspath(__file__)
    p = subprocess.Popen(
        [sys.executable, self_path, "heartbeat", str(task_id)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 부모(prepare) 종료 후에도 살아남는다
    )
    with open(_pid_path(task_id), "w") as f:
        f.write(str(p.pid))
    return p.pid


def _kill_heartbeat(task_id: int) -> None:
    try:
        with open(_pid_path(task_id)) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        os.remove(_pid_path(task_id))
    except OSError:
        pass


def cmd_heartbeat(task_id: int) -> int:
    """prepare 가 띄우는 데몬. SIGTERM(=report/release) 까지 heartbeat 를 찍는다."""
    while True:
        try:
            ro._post(f"/api/mori/tasks/{task_id}/heartbeat")
        except Exception:  # noqa: BLE001 — heartbeat 실패가 데몬을 죽이지 않게
            pass
        time.sleep(ro.HEARTBEAT_INTERVAL)


# ---- prepare: claim + 셋업 → 프롬프트 산출 ----

def _bail(task_id: int, msg: str) -> int:
    """셋업 실패 — 사유를 QUESTION 으로 회수(run_once 와 동일, fallback 금지)."""
    print(f"[error] {msg}")
    try:
        ro._post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
    except Exception:  # noqa: BLE001
        pass
    _kill_heartbeat(task_id)
    return 1


def cmd_prepare(argv: list[str]) -> int:
    if not ro.MORI_TOKEN:
        print("UNSKEIN_MORI_TOKEN 이 필요합니다 — executor.env 를 source 하세요.")
        return 1
    # 수동(함께 작업)은 전 단계를 이 세션이 처리한다 — test 카드도 집어 CDP 화면검증
    # (unskein-test)으로 옮긴다. 자율 루프의 ADR-0016 opt-in(env)과 달리 수동은 항상 켠다:
    # 운영자가 실제 화면을 보며 검증하므로 코드검증만 하는 헤드리스 opt-in 보다 강하다.
    ro.AUTO_ADVANCE_TEST = True
    # watch 대상 — 인자가 env 보다 우선(run_once.main 과 동일).
    b, p, t, _ = ro.parse_watch_args(argv)
    ro.apply_watch_args(b, p, t)
    ok, label = ro.resolve_watch_scope()
    if not ok:
        print(f"[watch] {label}")
        return 1
    print(f"[watch] 대상: {label}")

    ok, lines = ro.preflight()
    print("[preflight] 작업 전 준비 점검:")
    for ln in lines:
        print(ln)
    if not ok:
        print("[preflight] 준비 미충족 — 선점하지 않고 종료(fallback 금지).")
        return 1

    ro.gc_work_root()

    # watch 대상 오류(대상 없음/범위 밖/구서버)는 claim_once 가 WatchScopeError 로 드러낸다.
    try:
        claim = ro.claim_once()
    except ro.WatchScopeError as exc:
        print(f"[watch] {exc}")
        return 1
    if not claim.get("claimed"):
        print("NO_TASK: 선점할 작업이 없습니다 (대상 범위 내 plan/answered 0건).")
        return 0
    task = claim["task"]
    task_id = task["id"]
    print(f"[claim] task#{task_id} '{task.get('title', '')}' repo={task.get('repo_url') or ''}")

    # --- 셋업 (run_once._process_task 전반부와 동일한 게이트·순서) ---
    repo = task.get("repo_url") or ""
    if not repo:
        return _bail(task_id, "repo_url 이 비어 있습니다(프로젝트에 repo 주소 미등록)")
    if ro.detect_scheme(repo) == "unknown":
        return _bail(task_id, f"repo_url 형식을 알 수 없습니다(https:// 또는 git@ 만 지원): {repo}")

    task_root = _task_root(task_id)
    os.makedirs(task_root, exist_ok=True)
    try:
        ro.plant_dao_skills(task_root)
    except Exception as e:  # noqa: BLE001
        return _bail(task_id, str(e))
    try:
        git_env = ro.build_git_env(repo)
    except Exception as e:  # noqa: BLE001
        return _bail(task_id, str(e))
    try:
        ro.prepare_repo(
            repo, ro._repo_name(repo), task.get("status") or "", git_env, work_root=task_root
        )
    except Exception as e:  # noqa: BLE001
        return _bail(task_id, f"repo 준비 실패: {e}")

    # --- 프롬프트 결정 (answered/plan 게이트는 run_once 와 동일) ---
    status = task.get("status") or ""
    if status == "answered":
        answer = task.get("answer")
        if not answer:
            return _bail(task_id, "사람 답변(answer)이 비어 있어 이어받을 내용이 없습니다.")
        prompt = ro.build_resume_prompt(answer)
    else:
        if status == "plan" and not (task.get("plan_doc") or "").strip():
            return _bail(
                task_id,
                "실행대기(plan) 작업에 구현 사양(plan_doc)이 비어 있습니다 — 스콥 없이 "
                "구현할 수 없습니다. 계획을 첨부한 뒤 다시 실행대기로 올리세요.",
            )
        prompt = ro.build_prompt(task)

    work_dir = os.path.join(task_root, ro._repo_name(repo))
    meta = {"task_id": task_id, "status": status, "work_dir": work_dir, "task_root": task_root}
    with open(_meta_path(task_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    hb_pid = _spawn_heartbeat(task_id)

    # --- 세션에 넘길 출력 (세션이 이 프롬프트를 다오로서 수행한다) ---
    print()
    print(f"TASK_ID={task_id}")
    print(f"STATUS={status}")
    print(f"WORK_DIR={work_dir}")
    print(f"HEARTBEAT_PID={hb_pid}")
    print("\n===== DAO PROMPT (이 세션이 다오로서 수행) =====")
    print(prompt)
    print("===== END PROMPT =====")
    if status == "test":
        # 수동 test = 화면검증 — 코드검증이 아니라 CDP 로 실제 화면을 확인해 옮긴다.
        print(
            "\n[test] 이 단계는 CDP 화면검증으로 수행한다(unskein-test §1–7 — WSL 세션이면 "
            "powershell.exe/윈도우 Node 로 호출). PASS → RESULT: status=inspect, "
            "FAIL → RESULT: status=plan. 검증 결과 구조는 report --payload-file 로 싣는다."
        )
    print(
        f"\n다음: WORK_DIR 로 들어가 이식된 다오 스킬(../CLAUDE.md + ../.claude/skills/)을 "
        f"따라 위 프롬프트를 수행한 뒤, 최종 RESULT:/QUESTION: 마커를 파일로 저장하고 "
        f"`work.py report {task_id} --marker-file <파일>` 로 회수하라."
    )
    return 0


# ---- report: 마커 → 회수 ----

def cmd_report(task_id: int, marker_file: str | None, payload_file: str | None = None) -> int:
    if marker_file:
        with open(marker_file, encoding="utf-8") as f:
            result_text = f.read()
    else:
        result_text = sys.stdin.read()

    # 단계 구조화 산출물(선택) — 서버가 task.payload[<출발단계>] 에 저장한다.
    # 수동 test(CDP 화면검증) 결과를 unskein-test §0.3 구조로 실을 때 쓴다.
    payload = None
    if payload_file:
        with open(payload_file, encoding="utf-8") as f:
            payload = json.load(f)

    meta = {}
    try:
        with open(_meta_path(task_id), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass
    task_root = meta.get("task_root") or _task_root(task_id)

    kind, status, stage, summary, doc = ro.extract_marker(result_text)
    _kill_heartbeat(task_id)  # 보고 전 heartbeat 정지

    if kind == "question":
        # in-session: 이어받을 claude 세션이 없어 session_id 는 싣지 않는다(웹 기록용).
        print(f"[report] QUESTION → {summary}")
        ro._post(f"/api/mori/tasks/{task_id}/question", {"question": summary})
    elif kind == "result":
        print(f"[report] RESULT → status={status} stage={stage} summary={summary}")
        body = {
            "summary": summary,
            "session_id": None,
            "transcript_path": None,
            "status": status,
            "stage": stage,
            "doc": doc,
        }
        if payload is not None:
            body["payload"] = payload
        ok = ro._post_report(task_id, body)
        if not ok:
            print("[report] 보고 실패 — status 유지, 재처리가 이 단계를 재실행한다.")
            return 1
    else:
        msg = (
            "다오가 단계 완료 마커를 규약대로 내지 않았습니다 "
            "(RESULT: status=.. 펜스 마커 누락). 마지막 출력: " + (summary or "(없음)")
        )
        print(f"[report] UNKNOWN → {msg}")
        ro._post(f"/api/mori/tasks/{task_id}/question", {"question": msg})

    if kind == "result" and status == "done":
        shutil.rmtree(task_root, ignore_errors=True)
    else:
        for pth in (_meta_path(task_id), _pid_path(task_id)):
            try:
                os.remove(pth)
            except OSError:
                pass
    print("[done] 회수 완료.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("사용: work.py {prepare|report|heartbeat|release} ...")
        return 1
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    if cmd == "prepare":
        return cmd_prepare(rest)
    if cmd == "heartbeat":
        if not rest:
            print("사용: work.py heartbeat <task_id>")
            return 1
        return cmd_heartbeat(int(rest[0]))
    if cmd == "report":
        ap = argparse.ArgumentParser(prog="work.py report")
        ap.add_argument("task_id", type=int)
        ap.add_argument("--marker-file", default=None)
        ap.add_argument("--payload-file", default=None,
                        help="단계 구조화 산출물 JSON (예: 수동 test 의 CDP 검증 결과 — unskein-test §0.3)")
        a = ap.parse_args(rest)
        return cmd_report(a.task_id, a.marker_file, a.payload_file)
    if cmd == "release":
        if not rest:
            print("사용: work.py release <task_id>")
            return 1
        _kill_heartbeat(int(rest[0]))
        print("[release] heartbeat 정지.")
        return 0
    print(f"알 수 없는 커맨드: {cmd}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ro.urllib.error.HTTPError as exc:
        print(f"[http error] {exc.code} {exc.read().decode('utf-8', 'replace')}")
        sys.exit(1)
