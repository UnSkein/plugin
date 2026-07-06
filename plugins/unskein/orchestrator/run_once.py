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

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# Windows 등 비 UTF-8 콘솔(cp949 등)에서도 한글·기호 출력이 깨지지 않게 stdout/stderr 를 UTF-8 로 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

API_BASE = os.getenv("UNSKEIN_API", "https://unskein.mupai.studio")
# 토큰은 import 시점에 강제하지 않는다 — 진단 도구(status.py/doctor)가 이 모듈을 import 해
# preflight() 를 구동하기 때문이다(토큰 없음 자체가 진단 대상). 실제 강제는 작업을 잡는
# 진입점(main)에서 한다. /api/health 같은 공개 엔드포인트는 토큰 없이도 점검할 수 있다.
MORI_TOKEN = os.getenv("UNSKEIN_MORI_TOKEN")
# claude -p 가 오래 걸릴 수 있어 넉넉히.
CLAUDE_TIMEOUT = int(os.getenv("UNSKEIN_CLAUDE_TIMEOUT", "600"))
# 작업별 heartbeat 주기(초). process_task 가 단일패스·동시 풀 양쪽에서 이 주기로 찍어,
# 한 턴이 서버 lease(CLAIM_STALE) 를 넘겨도 다른 워커가 같은 작업을 이중선점하지 못하게 한다.
HEARTBEAT_INTERVAL = int(os.getenv("UNSKEIN_HEARTBEAT_INTERVAL", "60"))
# 실패 복구(F) — RESULT report 전송 재시도. 5xx·네트워크만 지수 백오프(4xx 는 계약/상태
# 위반 — 인접성 400·펜스 409 등 — 이라 재시도해도 같으니 영구 실패). 소진/4xx 면 호출자가
# status 를 유지한 채 종료해 재선점이 단계를 재실행한다(session 없는 question 전환 금지).
REPORT_RETRIES = int(os.getenv("UNSKEIN_REPORT_RETRIES", "4"))
REPORT_BACKOFF_BASE = float(os.getenv("UNSKEIN_REPORT_BACKOFF", "1.0"))
# 버려진 작업폴더 GC 유예(초) — 갓 선점/전이 중인 폴더를 age 단독으로 지우지 않게.
GC_GRACE_SECONDS = int(os.getenv("UNSKEIN_GC_GRACE", "3600"))

# watch 대상 — 이 클라이언트가 바라볼 프로덕션 작업의 범위를 좁힌다(이름으로 지정).
# 둘 다 비우면 토큰 사용자의 모든 비즈니스/프로젝트가 대상(기존 동작).
# id 는 환경별로 다르므로 이름으로 지정한다(서버가 멤버십 안에서 매칭).
WATCH_BUSINESS = os.getenv("UNSKEIN_WATCH_BUSINESS") or None
WATCH_PROJECT = os.getenv("UNSKEIN_WATCH_PROJECT") or None

# EXECUTOR opt-in(ADR-0016) — 켜면 이 클라이언트가 test 도 집어 코드검증(unskein-verify)을
# pre-merge 로 돌리고 통과 시 inspect 로 잇는다(화면검증 TESTER 는 배포 후 별개). claim 에
# auto_advance_test=True 로 실린다. 기본 off — 진짜 프로덕션은 꺼서 사람 리뷰 게이트를 유지한다.
AUTO_ADVANCE_TEST = (os.getenv("UNSKEIN_AUTO_ADVANCE_TEST") or "").strip().lower() in (
    "1", "true", "yes", "on",
)

# watch 대상 키워드(인자/명령줄에서 인식). 짧은형(bis/prj)·풀네임·플래그·key=value 모두 허용.
_WATCH_BIZ_KEYS = {"business", "bis", "--business", "-b"}
_WATCH_PRJ_KEYS = {"project", "prj", "--project", "-p"}


def parse_watch_args(argv: list[str]) -> tuple[str | None, str | None, list[str]]:
    """argv 에서 watch 대상(비즈니스/프로젝트)을 뽑고 나머지 위치 인자를 돌려준다.

    인식 형식(값에 공백 있으면 따옴표로 묶는다):
      bis "이름" prj "이름"  /  business <이름> project <이름>
      --business <이름> --project <이름>  /  -b <이름> -p <이름>
      bis=이름  business=이름  prj=이름  project=이름
    반환 (business, project, positionals). 못 만나면 해당 값은 None.
    """
    business = project = None
    positionals: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        key = tok.lower()
        if "=" in tok and key.split("=", 1)[0] in (_WATCH_BIZ_KEYS | _WATCH_PRJ_KEYS):
            k, _, v = tok.partition("=")
            if k.lower() in _WATCH_BIZ_KEYS:
                business = v
            else:
                project = v
            i += 1
            continue
        if key in _WATCH_BIZ_KEYS and i + 1 < len(argv):
            business = argv[i + 1]
            i += 2
            continue
        if key in _WATCH_PRJ_KEYS and i + 1 < len(argv):
            project = argv[i + 1]
            i += 2
            continue
        positionals.append(tok)
        i += 1
    return business, project, positionals


def apply_watch_args(business: str | None, project: str | None) -> None:
    """argv 로 받은 watch 대상으로 모듈 전역을 덮어쓴다(인자가 env 보다 우선).

    값이 None(인자 미지정)이면 env 기본값을 그대로 둔다. 빈 문자열은 '대상 없음'.
    """
    global WATCH_BUSINESS, WATCH_PROJECT
    if business is not None:
        WATCH_BUSINESS = business or None
    if project is not None:
        WATCH_PROJECT = project or None

def _env_path(name: str, default: str) -> str:
    """경로 env 를 읽는다 — 빈 값은 미설정 취급(기본값 사용), '~'·상대경로는 절대경로로
    정규화한다. source 실수(빈 export, 따옴표 틸드 "~/…", 상대경로)로 상태 폴더가
    launch cwd 에 조용히 흩어지는 사고를 막는다(askpass 는 git -C 밑에서 실행돼
    상대경로면 인증이 즉사한다)."""
    raw = (os.getenv(name) or "").strip() or default
    return os.path.abspath(os.path.expanduser(raw))


# 실행기 상태 루트 — env·creds·work 를 통째로 격리하는 단일 변수(ADR-0020).
# 한 머신에서 여러 프로젝트를 돌릴 때 프로젝트 디렉토리마다
# UNSKEIN_HOME=<프로젝트>/.unskein 으로 상태를 격리한다(코드=플러그인은 전역 1벌 공유).
# 미설정이면 종전과 동일한 전역 ~/.unskein (하위호환). 개별 변수가 여전히 우선하지만
# 정상 배치에선 UNSKEIN_HOME 하나만 쓴다 — 부분 지정(예: 전역 WORK_ROOT 잔존)은
# 상태가 전역/프로젝트로 갈라지는 사고라 preflight 가 정합성을 점검한다.
UNSKEIN_HOME = _env_path("UNSKEIN_HOME", os.path.join("~", ".unskein"))
# 자격증명(SSH 키 / 토큰 / known_hosts)을 모아두는 폴더. 부모 환경 또는 기본 $UNSKEIN_HOME/creds.
CRED_DIR = _env_path("UNSKEIN_CRED_DIR", os.path.join(UNSKEIN_HOME, "creds"))
# 다오가 repo 를 클론·작업하는 작업 폴더. 기본 $UNSKEIN_HOME/work.
WORK_ROOT = _env_path("UNSKEIN_WORK_ROOT", os.path.join(UNSKEIN_HOME, "work"))
# 다오 작업 폴더에 심을 스킬 원본(plugin 동봉). 기본은 run_once.py 기준 ../dao-skills.
# CLAUDE.md(항상 규칙·출력 규약·단계 순서) + .claude/skills/(단계 스킬 6개)가 들어 있다.
DAO_SKILLS_SRC = _env_path(
    "UNSKEIN_DAO_SKILLS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dao-skills"),
)
# SSH 개인키. 기본 CRED_DIR/id_ed25519, 없으면 id_rsa 차선 탐색.
SSH_KEY = _env_path("UNSKEIN_SSH_KEY", os.path.join(CRED_DIR, "id_ed25519"))
# SSH known_hosts. 기본 CRED_DIR/known_hosts.
KNOWN_HOSTS = _env_path("UNSKEIN_SSH_KNOWN_HOSTS", os.path.join(CRED_DIR, "known_hosts"))


def _load_git_token(repo_url: str | None = None) -> str | None:
    """git 토큰을 조회한다. 우선순위:

    1) 부모 환경 UNSKEIN_GIT_TOKEN
    2) (호스트 지정 시) 환경 UNSKEIN_GIT_TOKEN_<HOST>
    3) CRED_DIR/.env 파일을 직접 파싱 (dotenv 미설치)
       — '#' 주석/빈 줄 무시, KEY=VALUE split, 따옴표 strip.
       파일 안에서도 호스트별 키(UNSKEIN_GIT_TOKEN_<HOST>)를 일반 키보다 우선.

    못 찾으면 None 반환 (fallback 기본값 금지 — 호출자가 raise 로 드러낸다).
    """
    host_key = None
    if repo_url:
        host = _repo_host(repo_url)
        if host:
            host_key = "UNSKEIN_GIT_TOKEN_" + host.upper().replace(".", "_").replace(
                "-", "_"
            )

    # 1)/2) 부모 환경 — 호스트별 키 우선.
    if host_key and os.environ.get(host_key):
        return os.environ[host_key].strip()
    if os.environ.get("UNSKEIN_GIT_TOKEN"):
        return os.environ["UNSKEIN_GIT_TOKEN"].strip()

    # 3) CRED_DIR/.env 직접 파싱.
    env_path = os.path.join(CRED_DIR, ".env")
    if not os.path.isfile(env_path):
        return None
    parsed: dict[str, str] = {}
    with open(env_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                parsed[key] = val
    if host_key and parsed.get(host_key):
        return parsed[host_key]
    if parsed.get("UNSKEIN_GIT_TOKEN"):
        return parsed["UNSKEIN_GIT_TOKEN"]
    return None


def _repo_host(repo_url: str) -> str | None:
    """repo_url 에서 호스트명을 뽑는다. (github.com 등)

    git@github.com:UnSkein/SaaS.git → github.com
    https://github.com/UnSkein/SaaS.git → github.com
    ssh://git@github.com/UnSkein/SaaS.git → github.com
    """
    if not repo_url:
        return None
    url = repo_url.strip()
    if url.startswith("git@"):
        # git@HOST:path
        rest = url[len("git@"):]
        return rest.split(":", 1)[0] or None
    for prefix in ("https://", "ssh://"):
        if url.startswith(prefix):
            rest = url[len(prefix):]
            # ssh://git@HOST/path 형태면 userinfo 제거
            if "@" in rest.split("/", 1)[0]:
                rest = rest.split("@", 1)[1]
            return rest.split("/", 1)[0].split(":", 1)[0] or None
    return None


def _strip_userinfo(repo_url: str) -> str:
    """https repo_url 에 박힌 userinfo(자격증명)를 제거한다.

    예) https://x-access-token:TOKEN@github.com/UnSkein/SaaS.git
        → https://github.com/UnSkein/SaaS.git

    ASKPASS+env 경로로만 토큰을 공급하므로 repo_url 은 항상 자격증명-free 여야 한다.
    operator 오설정이나 변조된 task payload 로 토큰이 박혀 들어와도
    prompt/콘솔/.git config/transcript 에 누출되지 않게 host 앞 userinfo 를 잘라낸다.
    ssh(git@HOST)/scp 형식의 user 는 SSH 로그인 사용자라 보존한다(https 만 처리).
    """
    url = (repo_url or "").strip()
    if url.startswith("https://"):
        prefix = "https://"
        rest = url[len(prefix):]
        head, sep, tail = rest.partition("/")
        if "@" in head:
            head = head.rsplit("@", 1)[1]
        return prefix + head + sep + tail
    return url


def _repo_name(repo_url: str) -> str:
    """repo_url 의 basename 에서 .git 을 떼어낸 폴더 이름.

    https://github.com/UnSkein/SaaS.git → SaaS
    git@github.com:UnSkein/SaaS.git → SaaS
    """
    url = (repo_url or "").strip().rstrip("/")
    # scp 형식(git@host:owner/repo)의 ':' 뒤 path 를 우선 분리.
    if url.startswith("git@") and ":" in url:
        url = url.split(":", 1)[1]
    base = url.rsplit("/", 1)[-1]
    if base.endswith(".git"):
        base = base[: -len(".git")]
    return base


def detect_scheme(repo_url: str) -> str:
    """repo_url 의 전송 방식 판정. 'ssh' | 'https' | 'unknown'."""
    url = (repo_url or "").strip()
    if url.startswith(("git@", "ssh://")):
        return "ssh"
    if url.startswith("https://"):
        return "https"
    return "unknown"


def _resolve_ssh_key() -> str | None:
    """SSH 개인키 경로를 확정한다. SSH_KEY 존재 시 그대로,
    없고 기본 id_ed25519 였다면 id_rsa 차선 탐색. 둘 다 없으면 None."""
    if os.path.isfile(SSH_KEY):
        return SSH_KEY
    # id_ed25519 기본값에서만 차선 탐색(명시 지정 키는 존중).
    alt = os.path.join(CRED_DIR, "id_rsa")
    if os.path.isfile(alt):
        return alt
    return None


def _write_askpass() -> str:
    """GIT_ASKPASS 스크립트를 CRED_DIR 에 없으면 생성하고 실행권한을 준다. 경로 반환.

    git 이 자격증명을 물을 때 호출 인자($1) 로 'Username'/'Password' 를 판별:
      - 'Username' 포함 → x-access-token 출력
      - 'Password' 포함 → 환경변수 UNSKEIN_GIT_TOKEN 출력
    토큰은 env 로만 받는다 — 인자나 평문 파일에 토큰을 박지 않는다.
    """
    os.makedirs(CRED_DIR, exist_ok=True)
    if os.name == "nt":
        path = os.path.join(CRED_DIR, "askpass.cmd")
        if not os.path.isfile(path):
            content = (
                "@echo off\r\n"
                'echo %1 | findstr /I "Username" >nul\r\n'
                "if %errorlevel%==0 (\r\n"
                "  echo x-access-token\r\n"
                ") else (\r\n"
                "  echo %UNSKEIN_GIT_TOKEN%\r\n"
                ")\r\n"
            )
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        return path

    path = os.path.join(CRED_DIR, "askpass.sh")
    if not os.path.isfile(path):
        content = (
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  *Username*) echo x-access-token ;;\n"
            '  *Password*) echo "$UNSKEIN_GIT_TOKEN" ;;\n'
            "esac\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    os.chmod(path, 0o755)
    return path


def prepare_ssh_creds() -> None:
    """SSH 분기 전용 준비. CRED_DIR 권한 700, 개인키 권한 0600,
    known_hosts 가 비었으면 ssh-keyscan 1회. 실패는 경고만(치명 아님)."""
    os.makedirs(CRED_DIR, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(CRED_DIR, 0o700)
        except OSError as exc:
            print(f"[warn] CRED_DIR 권한 설정 실패: {exc}")

    key = _resolve_ssh_key()
    if key:
        if os.name != "nt":
            try:
                os.chmod(key, 0o600)
            except OSError as exc:
                print(f"[warn] SSH 키 권한 설정 실패: {exc}")
        else:
            # 윈도우: icacls 로 상속 제거 + 현재 사용자 읽기 전용. 실패해도 경고만.
            try:
                subprocess.run(
                    [
                        "icacls",
                        key,
                        "/inheritance:r",
                        "/grant:r",
                        f"{os.environ.get('USERNAME', '')}:R",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as exc:  # noqa: BLE001 — 권한 보정은 best-effort
                print(f"[warn] icacls 키 권한 설정 실패: {exc}")

    # known_hosts 가 없거나 비었으면 ssh-keyscan github.com 으로 1회 채운다.
    need_scan = (not os.path.isfile(KNOWN_HOSTS)) or os.path.getsize(KNOWN_HOSTS) == 0
    if need_scan:
        try:
            proc = subprocess.run(
                ["ssh-keyscan", "github.com"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                with open(KNOWN_HOSTS, "a", encoding="utf-8") as f:
                    f.write(proc.stdout)
            else:
                print(f"[warn] ssh-keyscan 실패(무시, accept-new 로 진행): {proc.stderr.strip()[:200]}")
        except Exception as exc:  # noqa: BLE001 — accept-new 가 받쳐줌
            print(f"[warn] ssh-keyscan 실행 실패(무시): {exc}")


def build_git_env(repo_url: str) -> dict:
    """repo 의 전송 방식에 맞춰 git 자격증명을 환경변수로 구성한다.

    부모 환경을 복사해 PATH/HOME/ANTHROPIC 인증을 보존하고, 모리 토큰만 제거한다.
    토큰을 repo_url/clone 인자/.git config 에 절대 넣지 않는다 — ASKPASS+env 경로로만.
    키/토큰 누락은 raise 로 드러낸다 (fallback 기본값 금지).
    """
    env = os.environ.copy()  # PATH/HOME/ANTHROPIC 인증 보존 (빈 dict 금지)
    env.pop("UNSKEIN_MORI_TOKEN", None)  # 표적 비밀 축소: 자식 다오는 모리 API 토큰 불필요
    env.pop("UNSKEIN_SUDO_PASSWORD", None)  # 프로비저닝 전용 — 자식 다오는 sudo 불필요(단일 .env 담아도 안 샘)
    env["GIT_TERMINAL_PROMPT"] = "0"

    scheme = detect_scheme(repo_url)

    if scheme == "ssh":
        key = _resolve_ssh_key()
        if not key:
            raise RuntimeError(
                f"SSH repo 인데 개인키가 없습니다: {SSH_KEY} — "
                "UNSKEIN_CRED_DIR/creds 에 키 파일을 두세요"
            )
        prepare_ssh_creds()
        known_hosts = KNOWN_HOSTS
        if os.name == "nt":
            key = key.replace("\\", "/")
            known_hosts = known_hosts.replace("\\", "/")
        ssh_exe = os.getenv("UNSKEIN_SSH_EXE", "ssh")
        env["GIT_SSH_COMMAND"] = (
            f'{ssh_exe} -i "{key}" -o IdentitiesOnly=yes '
            f"-o StrictHostKeyChecking=accept-new "
            f'-o UserKnownHostsFile="{known_hosts}"'
        )
        return env

    if scheme == "https":
        token = _load_git_token(repo_url)
        if not token:
            raise RuntimeError(
                "HTTPS repo 인데 git 토큰이 없습니다 — "
                "UNSKEIN_GIT_TOKEN 또는 creds/.env 에 토큰을 두세요"
            )
        env["GIT_ASKPASS"] = _write_askpass()
        env["UNSKEIN_GIT_TOKEN"] = token
        # 자식의 모든 git 호출(clone/pull/push)에서 credential.helper 를 빈 값으로 강제한다.
        # GIT_CONFIG_* env 는 config 목록 맨 끝(최우선)에 추가되고, 빈 helper 값은
        # 앞서 누적된 helper 목록(store/manager/osxkeychain 등)을 초기화한다.
        # → 호스트에 영구 helper 가 설정돼 있어도 토큰이 디스크/키체인에 평문 저장되지 않는다.
        # clone 인자의 '-c credential.helper=' 가 pull/push 에는 안 걸리는 비대칭을 env 로 일괄 차단.
        # 부모 env 에 이미 GIT_CONFIG_COUNT 가 있으면 덮어쓰지 않고 다음 index 에 덧붙여
        # (빈 helper 가 맨 끝 = 최후 적용 → 무조건 helper 목록 초기화 우선).
        try:
            base = int(env.get("GIT_CONFIG_COUNT", "0"))
            if base < 0:
                base = 0
        except ValueError:
            base = 0
        env[f"GIT_CONFIG_KEY_{base}"] = "credential.helper"
        env[f"GIT_CONFIG_VALUE_{base}"] = ""
        env["GIT_CONFIG_COUNT"] = str(base + 1)
        return env

    raise RuntimeError(
        f"repo_url 형식을 알 수 없습니다(https:// 또는 git@ 만 지원): {repo_url}"
    )


def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if MORI_TOKEN:  # 토큰 없으면 헤더 생략(None 헤더로 깨지지 않게) — 인증 필요한 호출은 서버가 401 로 막는다.
        headers["X-Mori-Token"] = MORI_TOKEN
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict:
    # 토큰 없으면 헤더 생략 — preflight 의 /api/health(공개) 는 토큰 없이도 점검된다.
    headers = {"X-Mori-Token": MORI_TOKEN} if MORI_TOKEN else {}
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        method="GET",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_report(task_id: int, body: dict) -> bool:
    """RESULT report 전송(F) — 일시 실패(5xx·네트워크)는 지수 백오프로 재시도하고, 4xx(인접성
    400·펜스 409 등 계약/상태 위반)는 재시도 없이 영구 실패로 본다. 성공 True / 영구 실패 False.

    영구 실패를 session 없는 question 으로 바꾸지 않는다(성공턴·전이·doc 폐기 방지 — fallback
    금지). 호출자는 False 면 status 를 유지한 채 return 1 하여, 재선점이 같은 단계를 재실행하게 한다.
    """
    path = f"/api/mori/tasks/{task_id}/report"
    last = ""
    for attempt in range(REPORT_RETRIES + 1):
        try:
            _post(path, body)
            return True
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                detail = exc.read().decode("utf-8", "replace")[:500]
                print(f"[report] 영구 실패 {exc.code} (재시도 안 함): {detail}")
                return False
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            # 연결 단계(URLError)뿐 아니라 응답 수신 단계 실패도 재시도 대상으로 잡는다 —
            # read timeout(TimeoutError)·연결 리셋(ConnectionResetError, 예: 배포 재시작 중
            # in-flight POST)·잘린 본문(http.client.IncompleteRead). 이들은 URLError 가 아니라
            # 그냥 두면 _post_report 를 빠져나가 run_loop 가 session 없는 question 으로 바꾼다
            # (성공턴 폐기 — F 가 막으려는 바로 그 fallback). URLError 는 OSError 하위지만 명시.
            last = f"network {type(exc).__name__}: {exc}"
        if attempt < REPORT_RETRIES:
            delay = REPORT_BACKOFF_BASE * (2 ** attempt)
            print(
                f"[report] 일시 실패({last}) — {delay:.1f}s 후 재시도 "
                f"{attempt + 1}/{REPORT_RETRIES}"
            )
            time.sleep(delay)
    print(f"[report] 재시도 소진({last}) — 영구 실패로 처리(status 유지).")
    return False


def gc_work_root() -> None:
    """버려진 작업 폴더 정리(F) — 서버 live(status != done) 집합에 없고 mtime 이 grace 를 넘긴
    WORK_ROOT/<task_id> 만 지운다. 진행 중·재개 가능(waiting/answered) 트리와 갓 선점된 폴더는
    live 집합 또는 grace 가 보호한다(age 단독 삭제 금지 — ADR-0008 resume·ADR-0009 재진입 보존).
    live 조회 실패·개별 폴더 오류는 무시한다(정리가 작업을 막지 않게)."""
    if not os.path.isdir(WORK_ROOT):
        return
    try:
        live = {str(i) for i in _get("/api/mori/live-task-ids").get("ids", [])}
    except Exception as exc:  # noqa: BLE001 — GC 는 best-effort, 실패해도 작업은 진행.
        print(f"[gc] live 집합 조회 실패 — 정리 건너뜀: {exc}")
        return
    now = time.time()
    for name in os.listdir(WORK_ROOT):
        path = os.path.join(WORK_ROOT, name)
        if not os.path.isdir(path) or name in live:
            continue  # live(진행 중/재개 가능) 트리는 보존
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if age < GC_GRACE_SECONDS:
            continue  # grace 내 — 갓 선점/전이 중일 수 있어 보존
        print(f"[gc] 버려진 작업폴더 정리: {name} (age {age / 3600:.1f}h)")
        shutil.rmtree(path, ignore_errors=True)


def _claim_body() -> dict:
    """claim 에 실어 보낼 watch 대상 필터. 미지정 항목은 넣지 않는다."""
    body: dict = {}
    if WATCH_BUSINESS:
        body["business"] = WATCH_BUSINESS
    if WATCH_PROJECT:
        body["project"] = WATCH_PROJECT
    if AUTO_ADVANCE_TEST:
        body["auto_advance_test"] = True
    return body


def watch_label() -> str:
    """현재 watch 대상을 사람이 읽을 한 줄로."""
    if not WATCH_BUSINESS and not WATCH_PROJECT:
        return "전체 (대상 미지정)"
    biz = WATCH_BUSINESS or "(전체 비즈니스)"
    return f"{biz} / {WATCH_PROJECT}" if WATCH_PROJECT else biz


def resolve_watch_scope() -> tuple[bool, str]:
    """watch 대상(env)이 서버에서 보이는 비즈니스/프로젝트에 매칭되는지 사전 검증.

    반환 (ok, message). 대상 미지정이면 검증 없이 통과한다.
    이름이 멤버십에 없으면 가능한 이름을 곁들여 ok=False 로 드러낸다
    (조용한 fallback 금지 — 잘못된 대상이면 멈춘다).
    """
    if not WATCH_BUSINESS and not WATCH_PROJECT:
        return True, watch_label()
    try:
        scope = _get("/api/mori/scope")
    except Exception as exc:  # noqa: BLE001 — 검증 실패 사유를 그대로 드러낸다
        return False, f"watch 대상 검증 실패(서버 도달/토큰 확인): {exc}"
    businesses = scope.get("businesses", []) or []
    target = businesses
    if WATCH_BUSINESS:
        target = [b for b in businesses if b.get("name") == WATCH_BUSINESS]
        if not target:
            avail = ", ".join(b.get("name", "") for b in businesses) or "(없음)"
            return False, (
                f"watch 대상 비즈니스 '{WATCH_BUSINESS}' 를 찾을 수 없습니다. "
                f"가능한 비즈니스: {avail}"
            )
    if WATCH_PROJECT:
        proj_names = [
            p.get("name") for b in target for p in (b.get("projects") or [])
        ]
        if WATCH_PROJECT not in proj_names:
            avail = ", ".join(n for n in proj_names if n) or "(없음)"
            where = f"비즈니스 '{WATCH_BUSINESS}'" if WATCH_BUSINESS else "내 비즈니스"
            return False, (
                f"watch 대상 프로젝트 '{WATCH_PROJECT}' 를 {where} 에서 찾을 수 없습니다. "
                f"가능한 프로젝트: {avail}"
            )
    return True, watch_label()


def _git_behind(repo_dir: str) -> int | None:
    """repo_dir 의 현재 브랜치가 upstream 보다 몇 커밋 뒤졌는지. 못 구하면 None."""
    try:
        subprocess.run(
            ["git", "-C", repo_dir, "fetch", "--quiet"],
            capture_output=True, timeout=30, check=True,
        )
        out = subprocess.run(
            ["git", "-C", repo_dir, "rev-list", "--count", "HEAD..@{upstream}"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return int(out.stdout.strip() or "0")
    except Exception:  # noqa: BLE001 — 업데이트 점검은 best-effort(실패해도 차단 안 함).
        return None


def _gh_auth_state() -> str:
    """gh CLI 인증 상태를 범주로 돌려준다 — "ok" / "unauthed" / "error".

    다오는 마감(unskein-git)에서 PR 을 `gh pr create` 로만 만든다(REST fallback 없음).
    gh 가 없거나 미인증이면 작업을 다 하고도 PR 단계에서 튕기므로, 잡기 전에 막는다.

    `gh auth status` 는 저장된 토큰을 api.github.com 에 질의해 유효성(폐기·만료 포함)까지
    확인한다 → 종료코드 0 은 "github.com 에 인증된 계정이 있다"는 뜻이다(미로그인·무효 토큰은
    비-0). 단 0 이 곧 "대상 repo 에 PR 가능"은 아니다 — scope 부족 토큰·비-collaborator 계정은
    0 이어도 `gh pr create` 가 막힌다. 대상 repo 는 claim 전엔 미상이라 여기서 점검 불가하며
    (그 잔여는 마감의 unskein-git 이 떠안는다), 여기서는 잡는 지배적 케이스(미설치·미로그인·
    폐기/만료 토큰)만 본다.
      - "ok": 종료코드 0.
      - "unauthed": 종료코드 비-0 — 미로그인·토큰 무효.
      - "error": 실행 자체 실패(미설치·타임아웃·네트워크 등) — 토큰이 아니라 연결 문제일 수 있다.
    fallback 금지 — 어느 실패든 조용히 통과시키지 않는다(호출측이 차단).
    """
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return "ok" if r.returncode == 0 else "unauthed"
    except Exception:  # noqa: BLE001 — 미설치(FileNotFoundError)·타임아웃·네트워크 등은 "error".
        return "error"


def preflight() -> tuple[bool, list[str]]:
    """작업을 잡기(claim) 전에 이 클라이언트가 일할 준비가 됐는지 점검한다.

    준비가 안 됐는데 작업을 잡으면, 잡은 뒤 단계(plant_dao_skills 등)에서 실패해
    프로덕션 task 가 question 으로 튕겨 큐를 오염시킨다(설계 사고). 그래서 잡기 전에
    여기서 막는다(fallback 금지 — 치명 항목 미충족이면 시작하지 않는다).

    점검(치명): 실행 환경(다오·git 바이너리가 잡히면 WSL 등 환경이 떠 있는 것)·
    gh CLI 인증(다오가 마감에서 PR 을 만드는 데 필수)·다오 스킬 원본·자격증명 폴더·
    작업 루트·큐 서버 도달. (경고): 플러그인 업데이트.
    repo pull 여부는 작업마다 prepare_repo 가 clone+fetch+reset 으로 보장하므로
    여기서 점검하지 않는다(작업 전엔 repo 미상).

    반환 (ok, lines). ok=False 면 치명 항목 미충족 → 호출측이 선점 전에 멈춘다.
    """
    lines: list[str] = []
    state = {"ok": True}

    def check(label: str, passed: bool, detail: str = "", critical: bool = True) -> None:
        mark = "OK" if passed else ("실패" if critical else "경고")
        # detail(원인·조치 힌트)은 실패/경고일 때만 — 통과 줄에 붙으면 오해를 준다.
        suffix = "" if passed else (f" — {detail}" if detail else "")
        lines.append(f"  [{mark}] {label}{suffix}")
        if not passed and critical:
            state["ok"] = False

    # 1) 실행 환경 작동 — 다오·git 바이너리(잡히면 실행 환경이 떠 있는 것).
    check("다오 CLI(claude) 존재", shutil.which("claude") is not None,
          "PATH 에 claude 없음 — 다오를 못 띄운다")
    check("git 존재", shutil.which("git") is not None, "PATH 에 git 없음")
    # gh CLI 인증 — 다오가 마감(unskein-git)에서 PR 을 `gh pr create` 로 만든다.
    # 없거나 미인증이면 작업을 다 하고도 PR 단계에서 튕긴다 → 잡기 전에 막고 사람에게 요구한다.
    if shutil.which("gh") is None:
        check("gh CLI 인증(PR 생성)", False,
              "PATH 에 gh 없음 — unskein-setup S1 로 설치 후 "
              "`gh auth login`(mupaistudio) + `gh auth setup-git`")
    else:
        gh_state = _gh_auth_state()
        if gh_state == "unauthed":
            check("gh CLI 인증(PR 생성)", False,
                  "gh 미인증/토큰 무효 — `gh auth login`(mupaistudio) + `gh auth setup-git` 실행")
        elif gh_state == "error":
            # 토큰 문제와 구분 — gh 가 응답을 못 줬다(타임아웃·네트워크·일시 장애일 수 있음).
            check("gh CLI 인증(PR 생성)", False,
                  "gh auth status 응답 없음(네트워크·일시 장애일 수 있음) — "
                  "네트워크 확인 후 재시도, 지속되면 `gh auth login`(mupaistudio)")
        else:  # "ok"
            check("gh CLI 인증(PR 생성)", True)

    # 2) 필요한 것 — 다오 스킬 원본 / 자격증명 폴더 / 작업 루트.
    # 유효 상태 경로 표시 — 다중 프로젝트(UNSKEIN_HOME 격리)에서 이 세션이 어느 홈으로
    # 붙었는지 화면만으로 판별하게 한다(오배선이 무증상이 되는 것을 막는다, ADR-0020).
    home_set = bool((os.getenv("UNSKEIN_HOME") or "").strip())
    lines.append(f"  [경로] 상태 루트(UNSKEIN_HOME): {UNSKEIN_HOME}"
                 + ("" if home_set else " (기본값)"))
    lines.append(f"  [경로] creds: {CRED_DIR}  /  work: {WORK_ROOT}")
    split_state = False
    if home_set:
        # 정합 가드 — 루트를 지정했는데 개별 변수(UNSKEIN_CRED_DIR/UNSKEIN_WORK_ROOT,
        # 보통 전역 env 잔존)로 유효 경로가 그 밖이면 상태가 전역/프로젝트로 갈라진다
        # (부분 재정의 사고 — 공유 WORK_ROOT 는 GC 교차 삭제까지 간다). 조용히 진행하지
        # 않고 선점 전에 막는다(fallback 금지).
        # 비교는 realpath — 같은 폴더를 심링크/실경로로 달리 표기해도 오탐하지 않게.
        # 경로 비교는 POSIX(WSL) 전제(대소문자 혼용 등 윈도우 표기 차이는 미고려).
        home_real = os.path.realpath(UNSKEIN_HOME)

        def _under_home(p: str) -> bool:
            rp = os.path.realpath(p)
            return rp == home_real or rp.startswith(home_real + os.sep)

        split = [f"{n}={p}" for n, p in (("creds", CRED_DIR), ("work", WORK_ROOT))
                 if not _under_home(p)]
        split_state = bool(split)
        check("상태 루트 정합(UNSKEIN_HOME)", not split,
              f"UNSKEIN_HOME={UNSKEIN_HOME} 밖: {'; '.join(split)} — 개별 변수"
              "(UNSKEIN_CRED_DIR/UNSKEIN_WORK_ROOT) 잔존(전역 env 누출?)을 정리하거나, "
              "의도한 분리면 UNSKEIN_HOME 을 빼세요")
        # SSH 자격 경로는 의도적 외부 배치(~/.ssh 등)가 정당할 수 있어 경고만 —
        # 전역 env 잔존으로 다른 신원의 키를 조용히 쓰는 누출을 화면에 드러낸다.
        drift = [f"{n}={p}" for n, p in (("ssh_key", SSH_KEY), ("known_hosts", KNOWN_HOSTS))
                 if not _under_home(p)]
        check("SSH 자격 경로(UNSKEIN_HOME 안)", not drift,
              f"UNSKEIN_HOME 밖: {'; '.join(drift)} — 의도한 외부 키가 아니면 "
              "UNSKEIN_SSH_KEY/UNSKEIN_SSH_KNOWN_HOSTS 잔존(전역 env 누출?) 확인",
              critical=False)
    check("다오 스킬 원본(dao-skills)", os.path.isdir(DAO_SKILLS_SRC),
          f"{DAO_SKILLS_SRC} 없음 — plugin 설치 또는 UNSKEIN_DAO_SKILLS 확인")
    check("자격증명 폴더(creds)", os.path.isdir(CRED_DIR),
          f"{CRED_DIR} 없음 — unskein-setup 로 자격증명 배치")
    if split_state:
        # 정합 실패면 홈 밖 위치에 폴더를 만들지 않는다(정리 대상만 늘림) — 존재 검사만.
        check("작업 루트(work)", os.path.isdir(WORK_ROOT),
              f"{WORK_ROOT} 없음(상태 루트 정합 실패로 생성 보류)")
    else:
        try:
            os.makedirs(WORK_ROOT, exist_ok=True)
            work_ok = os.path.isdir(WORK_ROOT)
        except OSError:
            work_ok = False
        check("작업 루트(work)", work_ok, f"{WORK_ROOT} 생성 불가")

    # 3) 큐 서버 도달 — '필요한 것이 작동'에 서버 포함.
    try:
        h = _get("/api/health")
        server_ok = isinstance(h, dict) and h.get("status") == "ok"
        check(f"큐 서버 도달({API_BASE})", server_ok, "" if server_ok else "health 비정상")
    except Exception as exc:  # noqa: BLE001
        check(f"큐 서버 도달({API_BASE})", False, str(exc))

    # 4) 업데이트 — 플러그인 새 버전(경고만, 차단 안 함). 플러그인이 git 설치일 때만.
    plugin_root = os.getenv("CLAUDE_PLUGIN_ROOT")
    if plugin_root and os.path.isdir(os.path.join(plugin_root, ".git")):
        behind = _git_behind(plugin_root)
        if behind is None:
            check("플러그인 업데이트 확인", True, "원격 조회 실패 — 건너뜀", critical=False)
        elif behind > 0:
            check("플러그인 최신 여부", False,
                  f"원격이 {behind} 커밋 앞섬 — /plugin 갱신 권장", critical=False)
        else:
            check("플러그인 최신 여부", True)

    return state["ok"], lines


def _is_local_api(api: str) -> bool:
    """API 주소가 로컬(개발) 서버인지 — localhost/127.0.0.1 등."""
    return any(h in api for h in ("localhost", "127.0.0.1", "0.0.0.0"))


def autonomous_scope_block() -> str | None:
    """자율 루프(watch)를 막아야 하는 위험 조합이면 사유를 돌려준다(아니면 None).

    범위 미지정(WATCH_BUSINESS·WATCH_PROJECT 둘 다 없음) + 원격(테스트/프로덕션) 서버는
    이 클라이언트가 전체 큐를 무제한 자율 선점(claim)하게 한다. 다오는 항상
    --dangerously-skip-permissions 로 무인 실행되므로, 여러 클라이언트가 같은 큐를
    동시에 물면 같은 task 를 두고 경쟁한다(이번 두 모리 사고). 명시 동의
    (UNSKEIN_ALLOW_UNSCOPED=1) 없이는 막는다 — 범위를 지정해 단독 소유하게 한다.
    """
    unscoped = not WATCH_BUSINESS and not WATCH_PROJECT
    remote = not _is_local_api(API_BASE)
    if unscoped and remote and os.getenv("UNSKEIN_ALLOW_UNSCOPED") != "1":
        return (
            f"범위 미지정(전체 큐) + 원격 서버({API_BASE}) 자율 루프는 막혀 있습니다 — "
            "여러 클라이언트가 같은 큐를 경쟁하는 사고 방지. bis/prj 로 범위를 "
            "지정(권장)하거나, 의도적이면 UNSKEIN_ALLOW_UNSCOPED=1 로 명시 동의하세요."
        )
    return None


def plant_dao_skills(work_root: str) -> None:
    """다오 스킬 원본(dao-skills/)을 work_root 로 복사한다 — 다오 스킬 이식.

    work_root/CLAUDE.md(항상 규칙·출력 규약·단계 순서) + work_root/.claude/skills/
    (단계 스킬)가 깔려, work_root 에서 띄운 다오 세션이 이를 자동으로 읽는다.
    work_root 는 클론될 repo(work_root/<repo>)의 상위라, 여기 깔린 파일은
    고객 repo 의 커밋에 섞이지 않는다.

    매번 덮어써 항상 최신 상태로 둔다(단일 원본 = plugin dao-skills/).
    원본 폴더가 없으면 배포·설치 문제이므로 raise 로 드러낸다(fallback 금지).
    """
    src = DAO_SKILLS_SRC
    if not os.path.isdir(src):
        raise RuntimeError(
            f"다오 스킬 원본을 찾을 수 없습니다: {src} — plugin 설치/배포를 확인하세요"
        )
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(work_root, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


# status → (이번에 수행할 단계 지시, 보고할 next status). claim 한 status 가
# 이번 단계를 정한다 — 다오는 그 단계만 수행하고 next status 로 보고한다(단계 분할).
STAGE_INSTRUCTIONS = {
    # plan = 첫 구현 단계(스콥 게이트 — ADR-0009). 사람이 attach_plan 으로 수용 기준을
    # 확정해 실행대기로 올린 작업이라, 다오는 스콥을 다시 하지 않고 곧장 구현한다.
    "plan": (
        "이번 단계: 구현+자체검증. 먼저 unskein-wiki-search 로 기존 지식을 확인하고, "
        "unskein-exec 로 주입된 구현 사양(수용 기준)을 최소·수술적으로 구현한 뒤, "
        "unskein-verify 로 타입체크·빌드·테스트로 자체검증하라(화면검증은 별도 TESTER 담당). "
        "이 단계에서는 커밋·push 하지 않는다(마감 단계에서만)."
    ),
    # exec 는 은퇴된 레거시 단계 — 이미 exec 로 들어간 작업의 드레인용으로만 남긴다
    # (새 작업은 plan 에서 구현 후 곧장 test 로 보고한다 — dao-skills/CLAUDE.md 단계 표).
    "exec": (
        "이번 단계: 구현. unskein-exec 로 정해진 범위를 최소·수술적으로 구현하라. "
        "이 단계에서는 커밋·push 하지 않는다(마감 단계에서만)."
    ),
    "test": (
        "이번 단계: 검증. unskein-verify 로 타입체크·빌드·테스트를 돌리고 결과를 확인하라. "
        "검증 결과 본문을 RESULT 마커의 <<<UNSKEIN_DOC 블록으로 보고하라."
    ),
    "inspect": (
        "이번 단계: 기록·점검·마감. unskein-wiki-ingest 로 얻은 지식을 기록하고, "
        "unskein-wiki-lint 로 문서 부패를 점검한 뒤, unskein-git 으로 feature 브랜치에 "
        "커밋·push 하고 PR 을 만들어라. master 직접 머지·배포는 하지 않는다(머지되면 자동 배포)."
    ),
}


def build_prompt(task: dict) -> str:
    # repo_url 에 박힌 userinfo(자격증명) 제거 — prompt/콘솔/.git config/transcript 누출 차단.
    repo = _strip_userinfo(task.get("repo_url") or "")
    folder = _repo_name(repo)
    title = task.get("title") or ""
    description = task.get("description") or ""
    project_name = task.get("project_name") or ""
    status = task.get("status") or ""
    header = f"작업: {title}\n"
    if project_name:
        header += f"프로젝트: {project_name}\n"
    if description:
        header += f"{description}\n"

    # 이번 단계 지시 — claim 한 status 가 단계를 정한다(매핑 없으면 unknown 단계로 드러냄).
    stage_line = STAGE_INSTRUCTIONS.get(
        status,
        f"이번 단계 매핑이 없습니다(status={status}). "
        "QUESTION 으로 어떤 단계인지 물어라.",
    )

    # 이전 단계 저장본을 프롬프트에 주입(있을 때만 — 빈값 강제 금지).
    prior = ""
    if status in ("plan", "exec"):
        # plan = 첫 구현 단계(스콥 게이트 — ADR-0009). plan_doc 은 직전 단계 산출물이
        # 아니라 사람이 attach_plan 으로 붙인 구현 사양(수용 기준)이다. exec 는 레거시.
        plan_doc = task.get("plan_doc")
        if plan_doc:
            prior = f"\n구현 사양(수용 기준):\n{plan_doc}\n"
        # 화면검증 FAIL 롤백(test→plan)으로 되돌아온 재작업이면, 이전 화면검증 실패 근거를
        # 실어 무엇을 고쳐야 하는지 알린다(payload['test'].verdict==FAIL). TESTER 결과 슬롯.
        test_res = (task.get("payload") or {}).get("test") or {}
        if test_res.get("verdict") == "FAIL":
            fs = test_res.get("findings") or []
            lines = [f"- [{f.get('severity', '')}] {f.get('summary', '')}" for f in fs]
            detail = "\n".join(lines) if lines else (test_res.get("report_path") or "근거 미기재")
            prior += f"\n이전 화면검증 실패(고쳐야 함):\n{detail}\n"
    elif status == "inspect":
        result_doc = task.get("result_doc")
        if result_doc:
            prior = f"\n검증 결과:\n{result_doc}\n"

    # ADR-0007 rule 2 — 서브트리 주입. 이 작업이 WBS 상위 노드면(자손 있음) 자손
    # 내용을 함께 실어, 다오가 서브트리 전체를 한 단위로 개발하고 한 브랜치/PR 로
    # 마감하게 한다(자손 없으면 빈 블록).
    subtree = task.get("subtree") or []
    subtree_block = ""
    if subtree:
        sb = [
            "\n이 작업은 WBS 상위 노드다 — 아래 자손까지 한 단위로 함께 개발하고 "
            "한 브랜치/PR 로 마감하라(서브트리 실행). 수용 기준·구현·검증이 자손 내용을 "
            "포괄해야 한다:"
        ]
        for n in subtree:
            code = n.get("wbs_code")
            head = f"- [{code}] {n.get('title', '')}" if code else f"- {n.get('title', '')}"
            st = n.get("status")
            if st:
                head += f" (status={st})"
            sb.append(head)
            desc = n.get("description")
            if desc:
                sb.append(f"    설명: {desc}")
            pdoc = n.get("plan_doc")
            if pdoc:
                sb.append("    계획:")
                sb.extend(f"      {pl}" for pl in pdoc.splitlines())
        subtree_block = "\n".join(sb) + "\n"

    return (
        header
        + f"대상 repo: {repo}\n"
        + f"작업 폴더 이름: {folder}\n\n"
        + f"모리가 '{folder}' 를 미리 클론·최신화해 두었다"
        + (
            " (기본 브랜치 최신 상태에서 시작 — 직접 clone/pull/checkout 하지 말 것)."
            if status == "plan"
            else " (이전 단계 작업 트리 유지 — 직접 clone/pull/reset 하지 말 것)."
        )
        + f" '{folder}' 안으로 들어가 작업을 수행하라.\n"
        + stage_line
        + "\n"
        + prior
        + subtree_block
        + "\n현재 단계만 수행하고 다음 status 로 보고하라. "
        + "전체 단계 순서를 한 번에 밟지 않는다 — 다음 단계는 모리가 다음에 다시 선점한다.\n"
        + "완료 보고는 CLAUDE.md 4.1 출력 규약을 따른다 — "
        + "'RESULT: status=<다음 status> stage=<단계명> summary=<요약>' 첫 줄, "
        + "산출물이 있으면 그 아래 '<<<UNSKEIN_DOC' ~ 'UNSKEIN_DOC' 펜스 블록. "
        + "막히면 'QUESTION: <질문>' 한 줄."
    )


def build_resume_prompt(answer: str) -> str:
    """대화턴(CLAUDE.md §4.1) — 사람 답변을 이어받는 다오 세션에 전달할 프롬프트.

    --resume 로 직전 세션을 복원하므로 작업·단계 컨텍스트는 세션에 이미 있다. 여기선
    사람 답변만 전달하고, 막혔던 지점을 이어 현재 단계를 마치고 §4.1 규약대로 보고하게 한다.
    """
    return (
        "사람이 네 질문에 답했다. 아래 답변을 반영해 막혔던 지점부터 이어서 진행하라.\n\n"
        f"사람 답변:\n{answer}\n\n"
        "현재 단계를 마치고 CLAUDE.md 4.1 출력 규약대로 보고하라 — "
        "'RESULT: status=<다음 status> stage=<단계명> summary=<요약>' 첫 줄"
        "(산출물이 있으면 '<<<UNSKEIN_DOC' ~ 'UNSKEIN_DOC' 펜스 블록), "
        "다시 막히면 'QUESTION: <질문>' 한 줄."
    )


def run_dao(
    prompt: str, cwd: str, git_env: dict, resume_session_id: str | None = None
) -> tuple[int, str, str]:
    """claude -p 비대화형 실행. (returncode, stdout, stderr) 반환.

    git_env 는 build_git_env() 가 만든 환경 — git 자격증명(GIT_SSH_COMMAND/
    GIT_ASKPASS+토큰)과 부모 인증(PATH/HOME/ANTHROPIC)을 함께 담는다.
    자식 다오가 이 env 로 클론·push 를 수행한다.

    resume_session_id 가 있으면 `--resume <id>` 로 직전 다오 세션을 이어받는다
    (대화턴 CLAUDE.md §4.1 — prompt 는 사람 답변). 같은 cwd 라야 세션 transcript
    (~/.claude/projects/<cwd-slug>/<id>.jsonl)를 찾는다 — process_task 가 작업별
    task_root 로 고정해 턴 사이 cwd 가 일정하다. 없으면 새 세션으로 prompt 를 구동.
    """
    cmd = ["claude", "-p", prompt]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]
    cmd += ["--output-format", "json", "--dangerously-skip-permissions"]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        env=git_env,
        # 비대화형 — stdin 을 닫는다. 닫지 않으면 claude 가 파이프 입력을 기다리며
        # 수 초 지연(특히 --resume)하거나, 부모 stdin 상황에 따라 멈출 수 있다.
        stdin=subprocess.DEVNULL,
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


def extract_marker(
    result_text: str,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """result 텍스트에서 RESULT:/QUESTION: 마커 추출.

    반환: (kind, status, stage, summary, doc).
    kind 는 'result' | 'question' | 'unknown'.

    RESULT 마커(단계 완료, 다중 줄 + 펜스 블록):
        RESULT: status=<next_status> stage=<stage> summary=<한 줄 요약>
        <<<UNSKEIN_DOC
        <단계 산출물 본문 (markdown, 여러 줄 허용)>
        UNSKEIN_DOC
      - 메타는 공백 구분 key=value(status, stage, summary 순). summary 는 마지막
        키라 'summary=' 이후 그 줄 끝까지 전부가 값(공백 포함 허용).
      - 여는 토큰: 줄 전체가 정확히 '<<<UNSKEIN_DOC'. 닫는 토큰: 줄 전체가 'UNSKEIN_DOC'.
        펜스 본문은 원본 들여쓰기를 보존한다(markdown). 산출물 없는 단계는 펜스 생략 → doc=None.
      - status= 가 없으면 kind='unknown' (자동 done 금지).

    QUESTION 마커(막힘, 한 줄):
        QUESTION: <질문 내용>
      → ('question', None, None, 질문내용, None).

    마커가 전혀 없으면 ('unknown', None, None, 마지막줄, None).
    """
    raw_lines = (result_text or "").splitlines()
    # 줄 단위(원본 유지)로 뒤에서부터 'RESULT:'/'QUESTION:' 탐색.
    for i in range(len(raw_lines) - 1, -1, -1):
        stripped = raw_lines[i].strip()
        if stripped.startswith("QUESTION:"):
            return "question", None, None, stripped[len("QUESTION:"):].strip(), None
        if stripped.startswith("RESULT:"):
            meta = stripped[len("RESULT:"):].strip()
            status, stage, summary = _parse_result_meta(meta)
            doc = None
            # 바로 다음 줄이 여는 토큰이면 닫는 토큰까지 본문 수집(원본 들여쓰기 보존).
            if i + 1 < len(raw_lines) and raw_lines[i + 1].strip() == "<<<UNSKEIN_DOC":
                body: list[str] = []
                j = i + 2
                while j < len(raw_lines) and raw_lines[j].strip() != "UNSKEIN_DOC":
                    body.append(raw_lines[j])
                    j += 1
                doc = "\n".join(body)
            if not status:
                # status 누락 → 자동 done 금지. 요약만 들고 unknown 으로.
                return "unknown", None, stage, summary, doc
            return "result", status, stage, summary, doc
    # 마커가 전혀 없으면 마지막(비어있지 않은) 줄을 요약으로 본다.
    tail_lines = [ln.strip() for ln in raw_lines if ln.strip()]
    tail = tail_lines[-1] if tail_lines else (result_text or "").strip()
    return "unknown", None, None, tail, None


def _parse_result_meta(meta: str) -> tuple[str | None, str | None, str | None]:
    """'status=.. stage=.. summary=..' 메타 한 줄 파싱. (status, stage, summary).

    키 순서는 status, stage, summary. summary 는 마지막 키라 'summary=' 이후
    그 줄 끝까지 전부가 값(공백 포함). 누락 키는 None.
    """
    status = stage = summary = None
    rest = meta
    # summary 는 그 줄 끝까지라 먼저 떼어낸다(공백 포함 값 보존).
    idx = rest.find("summary=")
    if idx != -1:
        summary = rest[idx + len("summary="):].strip() or None
        rest = rest[:idx].strip()
    for tok in rest.split():
        if tok.startswith("status="):
            status = tok[len("status="):].strip() or None
        elif tok.startswith("stage="):
            stage = tok[len("stage="):].strip() or None
    return status, stage, summary


def guess_transcript_path(session_id: str | None, cwd: str) -> str | None:
    """claude transcript 추정 경로. ~/.claude/projects/<slug>/<session_id>.jsonl

    claude 는 프로젝트 디렉터리 슬러그를 만들 때 '/' 뿐 아니라 '.'·'_' 등 영숫자가
    아닌 모든 문자를 '-' 로 치환한다(실측 확인). 기본 work_root 가 $UNSKEIN_HOME/work
    (기본 ~/.unskein/work)라 '.' 를 포함하므로 '/' 만 바꾸면 실제 경로와 어긋난다 —
    같은 규칙으로 정규화한다.
    """
    if not session_id:
        return None
    slug = re.sub(r"[^a-zA-Z0-9]", "-", os.path.expanduser(cwd))
    return os.path.expanduser(f"~/.claude/projects/{slug}/{session_id}.jsonl")


def _default_branch(repo_path: str, git_env: dict) -> str:
    """origin 의 기본 브랜치명(master/main 등). origin/HEAD → 없으면 차선 탐색."""
    p = subprocess.run(
        ["git", "-C", repo_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True, text=True, env=git_env, timeout=60,
    )
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip().split("/", 1)[-1]  # 'origin/master' → 'master'
    for cand in ("main", "master"):
        chk = subprocess.run(
            ["git", "-C", repo_path, "ls-remote", "--exit-code", "--heads", "origin", cand],
            capture_output=True, text=True, env=git_env, timeout=60,
        )
        if chk.returncode == 0:
            return cand
    raise RuntimeError("origin 기본 브랜치를 찾을 수 없습니다 (origin/HEAD·main·master 모두 없음)")


def prepare_repo(
    repo: str, folder: str, status: str, git_env: dict, work_root: str | None = None
) -> str:
    """다오 실행 전, 모리가 repo 를 결정적으로 준비한다. 작업 폴더 경로 반환.

    - 폴더가 없으면 clone (credential.helper 빈 값 = 토큰 캐시 저장 차단).
    - origin fetch 로 최신 반영.
    - 첫 클론(폴더 신규)이면 기본 브랜치로 깨끗하게 리셋한다 — 최신 master/main 에서 출발.
    - 폴더가 이미 있으면(같은 task 의 다음 단계·재선점·answered) 작업 트리를 보존한다
      (리셋 금지). plan 이 첫 구현 단계가 된 뒤로는(ADR-0009) plan 재진입에서 리셋하면
      진행 중 구현이 영구 삭제되므로, 존재하는 폴더는 status 무관 보존한다.

    pull 을 다오 프롬프트 지시에 맡기지 않고 모리가 결정적으로 수행한다 — stale
    base(이전 브랜치 위) 에서 작업하는 것을 막는다. 실패는 raise 로 드러낸다
    (fallback 금지 — 호출자가 QUESTION 으로 회수).
    """
    repo_path = os.path.join(work_root or WORK_ROOT, folder)

    def _git(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        p = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True, text=True, env=git_env, timeout=timeout,
        )
        if p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} 실패: {p.stderr.strip()[:300]}")
        return p

    fresh_clone = not os.path.isdir(os.path.join(repo_path, ".git"))
    if fresh_clone:
        p = subprocess.run(
            ["git", "-c", "credential.helper=", "clone", repo, repo_path],
            capture_output=True, text=True, env=git_env, timeout=CLAUDE_TIMEOUT,
        )
        if p.returncode != 0:
            raise RuntimeError(f"git clone 실패: {p.stderr.strip()[:300]}")

    _git(["fetch", "--prune", "origin"])
    default = _default_branch(repo_path, git_env)
    if fresh_clone:
        # 첫 클론 — 최신 기본 브랜치에서 깨끗하게 출발(잔여 없음 보장).
        _git(["checkout", "-f", default])
        _git(["reset", "--hard", f"origin/{default}"])
        _git(["clean", "-fd"])
        print(f"[repo] '{folder}' {default} 최신으로 클론·리셋 (작업 시작)")
    else:
        # 재진입(같은 task 의 다음 단계·재선점·answered) — 작업 트리 보존. plan 이 첫
        # 구현 단계가 된 뒤로는 plan 재진입에서 리셋하면 진행 중 구현이 영구 삭제되므로,
        # 폴더가 있으면 status 무관 보존한다(ADR-0009 · 데이터 손실 방지).
        print(f"[repo] '{folder}' 작업 트리 보존 (재진입, status={status})")
    return repo_path


def process_task(task: dict) -> int:
    """선점한 작업을 heartbeat 를 찍으며 처리한다 — 단일패스(run_once)·동시 풀(run_loop) 공용.

    claim~report 한 턴이 서버 lease(CLAIM_STALE) 를 넘겨도 다른 워커가 같은 task_root 를
    이중선점하지 못하게, task_id 확보 직후 heartbeat 스레드를 띄운다(시작 직후 1회 + 이후
    HEARTBEAT_INTERVAL 마다). 처리가 끝나면 멈춘다. heartbeat 실패는 무시한다(처리를 막지 않게).
    """
    task_id = task["id"]
    stop = threading.Event()

    def _beat() -> None:
        while True:
            try:
                _post(f"/api/mori/tasks/{task_id}/heartbeat")
            except Exception:  # noqa: BLE001 — heartbeat 실패가 처리를 막지 않게.
                pass
            if stop.wait(HEARTBEAT_INTERVAL):
                return

    beat = threading.Thread(target=_beat, daemon=True)
    beat.start()
    try:
        return _process_task(task)
    finally:
        stop.set()


def _process_task(task: dict) -> int:
    """선점한 작업 1건을 다오로 처리하고 report/question 으로 회수한다.

    반환값은 종료 코드 의미 (0=성공, 1=실패). 호출자가 task 를 이미 claim 한 상태.
    """
    task_id = task["id"]
    repo = task.get("repo_url") or ""

    # repo 주소 게이트 — 빈값/형식미상은 QUESTION 으로 회수.
    if not repo:
        msg = "repo_url 이 비어 있습니다(프로젝트에 repo 주소 미등록)"
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1
    scheme = detect_scheme(repo)
    if scheme == "unknown":
        msg = f"repo_url 형식을 알 수 없습니다(https:// 또는 git@ 만 지원): {repo}"
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1

    # 작업 폴더 보장 — 동시 실행 격리를 위해 작업별 폴더(WORK_ROOT/<task_id>)를 쓴다.
    # 같은 task 의 여러 단계(plan→exec→test→inspect)는 같은 폴더라 작업트리가 이어지고,
    # 서로 다른 task 는(같은 repo 라도) 폴더가 달라 동시 실행이 충돌하지 않는다.
    task_root = os.path.join(WORK_ROOT, str(task_id))
    os.makedirs(task_root, exist_ok=True)

    # 다오 스킬 이식 — task_root 에 CLAUDE.md + .claude/skills/ 를 깐다.
    # 원본 누락은 배포 문제이므로 QUESTION 으로 드러낸다(fallback 금지).
    try:
        plant_dao_skills(task_root)
    except Exception as e:  # noqa: BLE001 — 누락 사유를 사용자에게 그대로 회수
        msg = str(e)
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1

    # git 자격증명 환경 구성 — 키/토큰 누락은 QUESTION 으로 드러낸다(fallback 금지).
    try:
        git_env = build_git_env(repo)
    except Exception as e:  # noqa: BLE001 — 누락 사유를 사용자에게 그대로 회수
        msg = str(e)
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1

    # repo 준비 — 모리가 결정적으로 clone/fetch/(plan 이면)기본 브랜치 리셋한다.
    # 이전 작업의 잔여 브랜치 위에서 작업하거나 stale base 로 시작하는 것을 막는다.
    try:
        prepare_repo(
            repo, _repo_name(repo), task.get("status") or "", git_env, work_root=task_root
        )
    except Exception as e:  # noqa: BLE001 — 준비 실패 사유를 그대로 회수
        msg = f"repo 준비 실패: {e}"
        print(f"[error] {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
        return 1

    # 2) 프롬프트 / 이어받기 결정 — answered 면 직전 다오 세션을 사람 답변으로 이어받는다.
    claim_status = task.get("status") or ""
    resume_session_id = None
    if claim_status == "answered":
        # 대화턴(CLAUDE.md §4.1). 이어받을 세션·답변이 없으면 조용히 새로 시작하지 않고
        # QUESTION 으로 드러낸다(fallback 금지). 사람은 칸반에서 plan 으로 되돌려 새로
        # 실행하거나 누락 사유를 본다.
        resume_session_id = task.get("resume_session_id")
        answer = task.get("answer")
        if not resume_session_id:
            msg = (
                "이어받을 다오 세션이 없어 대화턴을 이을 수 없습니다 — 직전 세션 기록이 "
                "비어 있습니다(질문 회수 전에 세션이 기록되지 않았을 수 있음). 처음부터 "
                "다시 실행하려면 작업 패널에서 '실행대기로 되돌리기'(plan) 를 누르세요 "
                "(이 작업은 보드 밖 상태라 간트에서 열 수 있습니다)."
            )
            print(f"[error] {msg}")
            _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
            return 1
        if not answer:
            msg = "사람 답변(answer)이 비어 있어 이어받을 내용이 없습니다."
            print(f"[error] {msg}")
            _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
            return 1
        prompt = build_resume_prompt(answer)
    else:
        # 스콥 게이트 런타임 백스톱(ADR-0009) — plan(첫 구현 단계)인데 구현 사양(plan_doc)이
        # 비어 있으면 서버 게이트(attach_plan/update_task)를 못 지난 레거시/이상 작업이다.
        # 빈 사양으로 blind 구현하지 않고 QUESTION 으로 회수한다(fallback 금지).
        if claim_status == "plan" and not (task.get("plan_doc") or "").strip():
            msg = (
                "실행대기(plan) 작업에 구현 사양(plan_doc)이 비어 있습니다 — 스콥 없이 "
                "구현할 수 없습니다. 작업 패널에서 계획(수용 기준)을 첨부한 뒤 다시 "
                "실행대기로 올리세요."
            )
            print(f"[error] {msg}")
            _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
            return 1
        prompt = build_prompt(task)
    print(f"[prompt]\n{prompt}\n")

    # 3) 다오 구동
    resume_note = f", --resume {resume_session_id}" if resume_session_id else ""
    print(f"[dao] claude -p 실행 (cwd={task_root}, timeout={CLAUDE_TIMEOUT}s{resume_note}) ...")
    try:
        rc, stdout, stderr = run_dao(prompt, task_root, git_env, resume_session_id)
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
        # 세션이 파싱됐으면 함께 보내 답변 후 --resume 으로 이어받게 한다(F). 없으면 None(이어받을
        # 세션 없음을 명시 — fallback 금지). 직전엔 session_id 를 빠뜨려 resume 를 폐기했다.
        q = {"question": f"다오 실행 실패: {err}"}
        if session_id:
            q["session_id"] = session_id
        _post(f"/api/mori/tasks/{task_id}/question", q)
        return 1
    print(f"[dao] session_id={session_id}")
    print(f"[dao result]\n{result_text}\n")

    kind, status, stage, summary, doc = extract_marker(result_text)
    transcript = guess_transcript_path(session_id, task_root)

    # 5) 회수
    if kind == "question":
        # 대화턴(CLAUDE.md §4.1) — 다오가 막혀 질문을 던졌다. 이 세션을 함께 보고해야
        # 사람이 답한 뒤(answered) 모리가 같은 세션을 --resume 으로 이어받을 수 있다.
        # transcript 경로(클라이언트 로컬)는 서버에 보내지 않는다 — session_id 면 충분(§5).
        print(f"[report] QUESTION → {summary}")
        _post(
            f"/api/mori/tasks/{task_id}/question",
            {"question": summary, "session_id": session_id},
        )
    elif kind == "result":
        # 단계 전이는 오직 마커의 next status 로만 일어난다(하드코딩 done 금지).
        print(f"[report] RESULT → status={status} stage={stage} summary={summary}")
        ok = _post_report(
            task_id,
            {
                "summary": summary,
                "session_id": session_id,
                "transcript_path": transcript,
                "status": status,
                "stage": stage,
                "doc": doc,
            },
        )
        if not ok:
            # 보고 영구 실패(F) — 서버 status 는 안 바뀌었다. session 없는 question 으로 바꾸지
            # 않고(성공턴·전이·doc 폐기 방지), status 유지 채 종료해 재선점이 이 단계를 재실행한다.
            print("[report] 보고 실패 — status 유지, 재선점이 단계를 재실행한다.")
            return 1
    else:
        # 마커/status 누락 → 자동 done 금지. 규약대로 보고하지 않았음을 QUESTION 으로 드러낸다(fallback 금지).
        msg = (
            "다오가 단계 완료 마커를 규약대로 내지 않았습니다 "
            "(RESULT: status=.. 펜스 마커 누락). 마지막 출력: "
            + (summary or "(없음)")
        )
        print(f"[report] UNKNOWN → {msg}")
        # 다오는 실제로 한 턴 돌았으므로 세션을 함께 보고한다 — 사람이 답을 주면(answered)
        # 같은 세션을 --resume 으로 이어받아 규약대로 다시 보고하게 한다.
        _post(
            f"/api/mori/tasks/{task_id}/question",
            {"question": msg, "session_id": session_id},
        )
    # 마감(done)된 작업의 격리 폴더는 정리한다 — 작업은 git 으로 push 되어 로컬 클론은
    # 폐기 가능. done 이 아니면(진행 중 단계) 다음 단계가 작업트리를 이어가야 하므로 보존.
    if kind == "result" and status == "done":
        shutil.rmtree(task_root, ignore_errors=True)
    print("[done] 한 바퀴 완료.")
    return 0


def main() -> int:
    # 토큰 강제 — 작업을 잡으려면 모리 토큰이 필요하다. import 시점이 아니라 여기서 막아
    # 모듈을 import-safe 하게 둔다(진단 도구가 preflight 만 구동). watch scope 조회(_get)도
    # 토큰을 쓰므로 그 전에 막는다.
    if not MORI_TOKEN:
        print(
            "UNSKEIN_MORI_TOKEN 환경변수가 필요합니다. "
            "UnSkein 설정 화면에서 발급한 토큰을 넣으세요."
        )
        return 1
    # 0) watch 대상 — 인자(bis/prj 등)로 받으면 env 보다 우선 적용한 뒤 검증한다.
    _b, _p, _ = parse_watch_args(sys.argv[1:])
    apply_watch_args(_b, _p)
    # 잘못 지정했으면 선점 전에 멈춘다(조용한 전체 폴백 금지).
    ok, label = resolve_watch_scope()
    if not ok:
        print(f"[watch] {label}")
        return 1
    print(f"[watch] 대상: {label}")

    # preflight — 작업을 잡기 전에 클라이언트 준비 점검(미충족이면 선점 안 함).
    ok, lines = preflight()
    print("[preflight] 작업 전 준비 점검:")
    for ln in lines:
        print(ln)
    if not ok:
        print("[preflight] 준비 미충족 — 작업을 선점하지 않고 종료(fallback 금지).")
        return 1

    # 버려진 작업폴더 GC(F) — 죽은 턴/마감 작업의 클론 누적을 막는다. 선점 전에 한 번.
    gc_work_root()

    # 1) claim (watch 대상 필터를 실어 보낸다)
    claim = _post("/api/mori/claim", _claim_body())
    if not claim.get("claimed"):
        print("선점할 작업이 없습니다 (대상 범위 내 plan/answered 0건).")
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
