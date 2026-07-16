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
  heartbeat <task_id>    (내부) prepare 가 띄우는 heartbeat 루프. SIGTERM(=report/release)
                         이나 **세션 사망**(생존 파일 정체·응답 heartbeat_at None·HTTP 409)
                         까지 찍고, 세션이 죽으면 스스로 멈춰 180s 뒤 self-heal 이 재선점을
                         자동 복구하게 한다(ADR-0015 자기종료 — 좀비 데몬 방지).
  liveness <task_id> <session_pid>
                         (내부) prepare 가 띄우는 세션 생존 토처. 세션 앵커가 살아있는 동안
                         생존 파일을 주기적으로 touch 한다(세션 사망 시 멈춤 → 데몬 자기종료).
  release <task_id>      보고 없이 heartbeat·생존 토처만 정지(중단 정리).

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
LV_PID_NAME = ".unskein-work.lv.pid"
LIVENESS_NAME = ".unskein-work.alive"

# 세션 생존 신호(ADR-0015 자기종료). 생존 토처가 LIVENESS_TOUCH_INTERVAL 마다 liveness
# 파일을 touch 하고, heartbeat 데몬은 그 파일이 LIVENESS_STALE_SECONDS 안쪽으로 신선할 때만
# beat 한다. 세션이 비정상 종료(SIGHUP·크래시·SIGKILL)하면 토처가 세션 앵커 소멸을 보고 멈춰
# 파일이 정체 → 데몬 자기종료 → 서버 lease(CLAIM_STALE 180s) 만료 → self-heal 재선점(사람
# 수동 release 불요). STALE 는 정상 턴 오탐(조기종료=이중선점)을 피하려 touch 주기의 몇 배로,
# 서버 180s 안쪽으로 잡는다.
LIVENESS_TOUCH_INTERVAL = int(os.getenv("UNSKEIN_LIVENESS_INTERVAL", "10"))
LIVENESS_STALE_SECONDS = int(os.getenv("UNSKEIN_LIVENESS_STALE", "45"))


def _task_root(task_id: int) -> str:
    return os.path.join(ro.WORK_ROOT, str(task_id))


def _meta_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), META_NAME)


def _pid_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), PID_NAME)


def _lv_pid_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), LV_PID_NAME)


def _liveness_path(task_id: int) -> str:
    return os.path.join(_task_root(task_id), LIVENESS_NAME)


# ---- 세션 생존 신호 (ADR-0015: 세션 사망 → 데몬 자기종료) ----

def _touch(path: str) -> None:
    """파일 mtime 을 현재로 갱신한다(없으면 생성)."""
    with open(path, "a"):
        pass
    os.utime(path, None)


def _pid_alive(pid: int) -> bool:
    """pid 가 살아있으면 True. signal 0 은 존재만 확인한다(POSIX)."""
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 존재하지만 시그널 권한 없음 = 살아있음
    return True


def _ppid_of(pid: int) -> int | None:
    """/proc 로 pid 의 부모 pid 를 읽는다(Linux/WSL). 못 구하면 None."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            data = f.read()
        # 형식 "pid (comm) state ppid ..." — comm 은 괄호·공백을 품을 수 있어 마지막 ')' 뒤부터 자른다.
        fields = data[data.rindex(")") + 1:].split()
        return int(fields[1])  # fields[0]=state, fields[1]=ppid
    except (OSError, ValueError, IndexError):
        return None


def _durable_session_pid() -> int:
    """세션 수명을 함께하는 앵커 pid — prepare 의 '조부모'(지속 셸).

    prepare 의 부모(os.getppid())는 Claude Code 가 명령을 감싸는 **단명 `bash -c`** 라(그래서
    ⓐ getppid 감시가 REFUTED — 단명 셸을 감시해 정상 턴을 조기종료), 그 부모(= 세션과 함께
    사는 지속 셸)를 앵커로 삼는다. 조부모를 못 구하면 부모를 쓴다(fallback 이 아니라 앵커 후보의
    차선 — 어느 쪽이든 세션 사망 시 소멸한다)."""
    parent = os.getppid()
    grand = _ppid_of(parent)
    return grand if (grand and grand > 1) else parent


def _session_alive(task_id: int) -> bool:
    """세션 생존 파일이 신선(LIVENESS_STALE_SECONDS 안쪽)하면 True.

    세션이 죽어 토처가 멈추면 파일 mtime 이 정체돼 False → cmd_heartbeat 가 beat 를 멈춘다.
    파일이 없거나 못 읽으면 생존 신호가 없는 것이라 False(죽음으로 간주 = beat 중단 — 좀비
    방지 우선. prepare 가 데몬 기동 전 파일을 만들고 토처를 함께 띄우므로 정상 기동엔 항상 존재)."""
    try:
        age = time.time() - os.path.getmtime(_liveness_path(task_id))
    except OSError:
        return False
    return age < LIVENESS_STALE_SECONDS


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


def _spawn_liveness(task_id: int, session_pid: int) -> int:
    """세션 생존 토처를 detached 로 띄우고 pid 를 pidfile 에 남긴다.

    detached 라 prepare 종료 후에도 산다(세션 전 구간 touch). 세션 앵커(session_pid) 소멸을
    스스로 감시해 멈추므로, prepare 부모(단명 셸)에 묶이지 않는다(ⓐ getppid 반려의 회피)."""
    self_path = os.path.abspath(__file__)
    p = subprocess.Popen(
        [sys.executable, self_path, "liveness", str(task_id), str(session_pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    with open(_lv_pid_path(task_id), "w") as f:
        f.write(str(p.pid))
    return p.pid


def _kill_pidfile(pid_path: str) -> None:
    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        os.remove(pid_path)
    except OSError:
        pass


def _kill_heartbeat(task_id: int) -> None:
    _kill_pidfile(_pid_path(task_id))


def _kill_liveness(task_id: int) -> None:
    _kill_pidfile(_lv_pid_path(task_id))


def _stop_daemons(task_id: int) -> None:
    """세션 종료·중단 정리 — heartbeat 데몬과 생존 토처를 함께 멈춘다."""
    _kill_heartbeat(task_id)
    _kill_liveness(task_id)


def cmd_heartbeat(task_id: int) -> int:
    """prepare 가 띄우는 데몬. SIGTERM(=report/release) 이나 세션 사망까지 heartbeat 를 찍는다.

    세션이 비정상 종료(SIGHUP·크래시·SIGKILL 로 report/release 미호출)하면 detached 인 이 데몬만
    살아남아 같은 lease 로 heartbeat 를 계속 갱신 → 서버가 '진행 중'으로 알고 재선점을 무기한
    차단(좀비). 이를 막으려 세 신호에서 스스로 종료한다(ADR-0015 자기종료). 종료하면 lease 가
    CLAIM_STALE(180s) 후 만료돼 서버 self-heal 이 재선점을 자동 복구한다 — 사람 수동 release 불요.

    - (가) 세션 생존 파일 정체: 세션이 죽어 토처가 멈추면 파일이 정체 → 종료.
    - (다ⓑ) beat 응답 heartbeat_at is None: report/question 이 턴 종료로 비운 상태라 종료.
    - (다ⓒ) HTTP 409: stale 재선점된 좀비의 늦은 beat 를 lease 펜싱이 거부 → 종료.

    일시 네트워크 오류·그 외 HTTP 오류(4xx/5xx)로는 죽지 않는다(데몬 유지 — 처리를 막지 않게)."""
    while True:
        if not _session_alive(task_id):  # (가) 세션 사망 → beat 중단
            return 0
        try:
            resp = ro._post(f"/api/mori/tasks/{task_id}/heartbeat")
        except ro.urllib.error.HTTPError as exc:
            if exc.code == 409:  # (다ⓒ) stale 재선점 좀비 — lease 펜싱이 거부
                return 0
            resp = None  # 그 외 HTTP 오류는 일시로 보고 계속
        except Exception:  # noqa: BLE001 — 네트워크 오류가 데몬을 죽이지 않게
            resp = None
        if isinstance(resp, dict) and resp.get("heartbeat_at") is None:  # (다ⓑ) 턴 종료
            return 0
        time.sleep(ro.HEARTBEAT_INTERVAL)


def cmd_liveness(task_id: int, session_pid: int) -> int:
    """(내부) prepare 가 띄우는 세션 생존 토처.

    세션 앵커(session_pid)가 살아있는 동안 liveness 파일을 LIVENESS_TOUCH_INTERVAL 마다 touch
    한다. 세션이 죽으면(앵커 소멸) 멈춘다 → 파일 정체 → heartbeat 데몬이 (가) 신호로 자기종료."""
    path = _liveness_path(task_id)
    while _pid_alive(session_pid):
        try:
            _touch(path)
        except OSError:  # noqa: BLE001 — touch 실패가 토처를 죽이지 않게
            pass
        time.sleep(LIVENESS_TOUCH_INTERVAL)
    return 0


# ---- prepare: claim + 셋업 → 프롬프트 산출 ----

def _bail(task_id: int, msg: str) -> int:
    """셋업 실패 — 사유를 QUESTION 으로 회수(run_once 와 동일, fallback 금지)."""
    print(f"[error] {msg}")
    try:
        ro._post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
    except Exception:  # noqa: BLE001
        pass
    _stop_daemons(task_id)
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

    # 범위 미지정 + 원격 서버 선점 가드 — 수동 prepare 도 claim 한 건을 잡으므로
    # run/watch 와 같은 위험이다(SKILL.md 서술대로 거부). task/bis/prj 로 범위를 지정하면
    # unscoped 가 아니라 통과한다. 의도적 전체 큐는 UNSKEIN_ALLOW_UNSCOPED=1.
    block = ro.autonomous_scope_block()
    if block:
        print(f"[prepare] 시작 거부 — {block}")
        return 1

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
    process_key = task.get("process_key") or "dev"
    # 무repo 프로젝트(코드베이스 비보유 — 사이트 API 작업형)의 사용자 프로세스 카드는
    # 클론 없이 작업 폴더만으로 수행한다. dev(코드 개발) 카드는 repo 필수(run_once 동일).
    no_repo = not repo
    if no_repo and process_key == "dev":
        return _bail(
            task_id,
            "repo 주소가 비어 있습니다(프로젝트에 repo 미등록) — 코드 개발(dev) "
            "카드는 repo 가 필요합니다. 코드베이스가 없는 프로젝트면 사용자 프로세스를 "
            "연결한 뒤 새 카드로 진행하세요(연결은 새 루트 카드부터 적용 — 이 카드는 "
            "dev 로 남아 같은 오류를 반복합니다).",
        )
    if not no_repo and ro.detect_scheme(repo) == "unknown":
        return _bail(task_id, f"repo_url 형식을 알 수 없습니다(https:// 또는 git@ 만 지원): {repo}")

    task_root = _task_root(task_id)
    os.makedirs(task_root, exist_ok=True)
    try:
        ro.plant_dao_skills(task_root)
    except Exception as e:  # noqa: BLE001
        return _bail(task_id, str(e))
    try:
        git_env = ro.build_dao_env() if no_repo else ro.build_git_env(repo)
    except Exception as e:  # noqa: BLE001
        return _bail(task_id, str(e))
    if not no_repo:
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

    work_dir = task_root if no_repo else os.path.join(task_root, ro._repo_name(repo))
    meta = {"task_id": task_id, "status": status, "work_dir": work_dir, "task_root": task_root}
    with open(_meta_path(task_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    # 세션 생존 신호(ADR-0015) — 데몬 기동 전 파일을 만들어 첫 검사를 통과시키고, 세션 앵커를
    # 감시하는 토처를 함께 띄운다. heartbeat 데몬은 이 파일이 신선할 때만 beat 하므로, 세션이
    # 비정상 종료하면 토처가 멈춰 파일이 정체 → 데몬 자기종료 → 180s 뒤 self-heal 재선점.
    _touch(_liveness_path(task_id))
    session_pid = _durable_session_pid()
    lv_pid = _spawn_liveness(task_id, session_pid)
    hb_pid = _spawn_heartbeat(task_id)

    # --- 세션에 넘길 출력 (세션이 이 프롬프트를 다오로서 수행한다) ---
    print()
    print(f"TASK_ID={task_id}")
    print(f"STATUS={status}")
    print(f"WORK_DIR={work_dir}")
    print(f"HEARTBEAT_PID={hb_pid}")
    print(f"LIVENESS_PID={lv_pid} SESSION_PID={session_pid}")
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
    # 다오 스킬 위치는 task_root 바로 안이다 — repo 카드는 WORK_DIR 가 그 아래 클론
    # 폴더라 ../, 무repo 카드는 WORK_DIR==task_root 라 ./ 가 맞다.
    rel = "." if no_repo else ".."
    print(
        f"\n다음: WORK_DIR 로 들어가 이식된 다오 스킬({rel}/CLAUDE.md + {rel}/.claude/skills/)을 "
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
    _stop_daemons(task_id)  # 보고 전 heartbeat·생존 토처 정지

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
        for pth in (_meta_path(task_id), _pid_path(task_id),
                    _lv_pid_path(task_id), _liveness_path(task_id)):
            try:
                os.remove(pth)
            except OSError:
                pass
    print("[done] 회수 완료.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("사용: work.py {prepare|report|heartbeat|liveness|release} ...")
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
    if cmd == "liveness":
        if len(rest) < 2:
            print("사용: work.py liveness <task_id> <session_pid>")
            return 1
        return cmd_liveness(int(rest[0]), int(rest[1]))
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
        _stop_daemons(int(rest[0]))
        print("[release] heartbeat·생존 토처 정지.")
        return 0
    print(f"알 수 없는 커맨드: {cmd}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ro.urllib.error.HTTPError as exc:
        print(f"[http error] {exc.code} {exc.read().decode('utf-8', 'replace')}")
        sys.exit(1)
