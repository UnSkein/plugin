#!/usr/bin/env python3
"""모리 역할 — UnSkein 작업 1건을 선점해 다오(claude -p)로 한 바퀴 돌린다.

흐름:
  1) POST /api/mori/claim (X-Mori-Token) 으로 backlog/answered 작업 1건 선점.
  2) 작업 → 프롬프트 변환.
  3) repo_url 경로에서 `claude -p "<prompt>" --output-format json
     --dangerously-skip-permissions` 비대화형 실행.
  4) stdout(json) 파싱: session_id + result 텍스트에서 RESULT:/QUESTION: 추출.
  5) RESULT → report, QUESTION → question 으로 UnSkein 에 회수.

stdlib 만 사용 (requests 미설치 환경). 단순 1패스 — 큐 루프/재시도 없음.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# Windows 등 비 UTF-8 콘솔(cp949 등)에서도 한글·기호 출력이 깨지지 않게 stdout/stderr 를 UTF-8 로 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

API_BASE = os.getenv("UNSKEIN_API", "http://localhost:8200")
MORI_TOKEN = os.getenv("UNSKEIN_MORI_TOKEN", "unskein-dev-mori-token")
# claude -p 가 오래 걸릴 수 있어 넉넉히.
CLAUDE_TIMEOUT = int(os.getenv("UNSKEIN_CLAUDE_TIMEOUT", "600"))


def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Mori-Token": MORI_TOKEN,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_prompt(task: dict) -> str:
    repo = task.get("repo_url") or ""
    return (
        f"작업: {task['title']}\n"
        f"{task.get('description') or ''}\n"
        f"대상 repo: {repo}\n\n"
        "이 repo 디렉토리 안에서 작업을 수행하라. "
        "구현 후 변경을 git add + git commit 하라.\n"
        "완료하면 마지막 줄에 'RESULT: <한줄요약>' 를, "
        "막히면 'QUESTION: <질문>' 를 출력하라."
    )


def run_dao(prompt: str, cwd: str) -> tuple[int, str, str]:
    """claude -p 비대화형 실행. (returncode, stdout, stderr) 반환."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_result(stdout: str) -> tuple[str | None, str | None, str | None]:
    """claude json 파싱. (session_id, result_text, error) 반환."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, None, f"JSON 파싱 실패: {exc}"
    session_id = payload.get("session_id")
    result_text = payload.get("result", "")
    if payload.get("is_error"):
        return session_id, result_text, f"claude is_error: {payload.get('subtype')}"
    return session_id, result_text, None


def extract_marker(result_text: str) -> tuple[str, str]:
    """result 텍스트에서 RESULT:/QUESTION: 마커 추출. (kind, content) 반환.

    kind 는 'result' | 'question' | 'unknown'.
    """
    lines = [ln.strip() for ln in (result_text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("RESULT:"):
            return "result", ln[len("RESULT:"):].strip()
        if ln.startswith("QUESTION:"):
            return "question", ln[len("QUESTION:"):].strip()
    # 마커가 없으면 마지막 줄을 결과로 본다.
    tail = lines[-1] if lines else (result_text or "").strip()
    return "unknown", tail


def guess_transcript_path(session_id: str | None, cwd: str) -> str | None:
    """claude transcript 추정 경로. ~/.claude/projects/<slug>/<session_id>.jsonl"""
    if not session_id:
        return None
    slug = cwd.replace("/", "-")
    return os.path.expanduser(f"~/.claude/projects/{slug}/{session_id}.jsonl")


def process_task(task: dict) -> int:
    """선점한 작업 1건을 다오로 처리하고 report/question 으로 회수한다.

    반환값은 종료 코드 의미 (0=성공, 1=실패). 호출자가 task 를 이미 claim 한 상태.
    """
    task_id = task["id"]
    repo = task.get("repo_url") or ""

    if not repo or not os.path.isdir(repo):
        msg = f"repo 경로가 없거나 디렉토리가 아닙니다: {repo}"
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1

    # 2) 프롬프트
    prompt = build_prompt(task)
    print(f"[prompt]\n{prompt}\n")

    # 3) 다오 구동
    print(f"[dao] claude -p 실행 (cwd={repo}, timeout={CLAUDE_TIMEOUT}s) ...")
    try:
        rc, stdout, stderr = run_dao(prompt, repo)
    except subprocess.TimeoutExpired:
        msg = f"claude -p timeout ({CLAUDE_TIMEOUT}s 초과)"
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1
    print(f"[dao] returncode={rc}")
    if stderr.strip():
        print(f"[dao stderr]\n{stderr[:2000]}")

    # 4) 파싱
    session_id, result_text, err = parse_result(stdout)
    if err:
        print(f"[error] {err}\n[raw stdout head]\n{stdout[:2000]}")
        _post(
            f"/api/mori/tasks/{task_id}/question",
            {"question": f"다오 실행 실패: {err}"},
        )
        return 1
    print(f"[dao] session_id={session_id}")
    print(f"[dao result]\n{result_text}\n")

    kind, content = extract_marker(result_text)
    transcript = guess_transcript_path(session_id, repo)

    # 5) 회수
    if kind == "question":
        print(f"[report] QUESTION → {content}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": content})
    else:
        summary = content if kind == "result" else f"(마커 없음) {content}"
        print(f"[report] RESULT → {summary}")
        _post(
            f"/api/mori/tasks/{task_id}/report",
            {
                "summary": summary,
                "session_id": session_id,
                "transcript_path": transcript,
                "status": "done",
            },
        )
    print("[done] 한 바퀴 완료.")
    return 0


def main() -> int:
    # 1) claim
    claim = _post("/api/mori/claim")
    if not claim.get("claimed"):
        print("선점할 작업이 없습니다 (backlog/answered 0건).")
        return 0
    task = claim["task"]
    print(f"[claim] task#{task['id']} '{task['title']}' repo={task.get('repo_url') or ''}")
    return process_task(task)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        print(f"[http error] {exc.code} {exc.read().decode('utf-8', 'replace')}")
        sys.exit(1)
