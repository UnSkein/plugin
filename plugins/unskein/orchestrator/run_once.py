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
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

# Windows 등 비 UTF-8 콘솔(cp949 등)에서도 한글·기호 출력이 깨지지 않게 stdout/stderr 를 UTF-8 로 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

API_BASE = os.getenv("UNSKEIN_API", "https://unskein.mupai.studio")
MORI_TOKEN = os.getenv("UNSKEIN_MORI_TOKEN")
if not MORI_TOKEN:
    print(
        "UNSKEIN_MORI_TOKEN 환경변수가 필요합니다. "
        "UnSkein 설정 화면에서 발급한 토큰을 넣으세요."
    )
    sys.exit(1)
# claude -p 가 오래 걸릴 수 있어 넉넉히.
CLAUDE_TIMEOUT = int(os.getenv("UNSKEIN_CLAUDE_TIMEOUT", "600"))

# watch 대상 — 이 클라이언트가 바라볼 프로덕션 작업의 범위를 좁힌다(이름으로 지정).
# 둘 다 비우면 토큰 사용자의 모든 비즈니스/프로젝트가 대상(기존 동작).
# id 는 환경별로 다르므로 이름으로 지정한다(서버가 멤버십 안에서 매칭).
WATCH_BUSINESS = os.getenv("UNSKEIN_WATCH_BUSINESS") or None
WATCH_PROJECT = os.getenv("UNSKEIN_WATCH_PROJECT") or None

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

# 자격증명(SSH 키 / 토큰 / known_hosts)을 모아두는 폴더. 부모 환경 또는 기본 ~/.unskein/creds.
CRED_DIR = os.getenv(
    "UNSKEIN_CRED_DIR", os.path.expanduser(os.path.join("~", ".unskein", "creds"))
)
# 다오가 repo 를 클론·작업하는 작업 폴더. 기본 ~/.unskein/work.
WORK_ROOT = os.getenv(
    "UNSKEIN_WORK_ROOT", os.path.expanduser(os.path.join("~", ".unskein", "work"))
)
# 다오 작업 폴더에 심을 스킬 원본(plugin 동봉). 기본은 run_once.py 기준 ../dao-skills.
# CLAUDE.md(항상 규칙·출력 규약·단계 순서) + .claude/skills/(단계 스킬 6개)가 들어 있다.
DAO_SKILLS_SRC = os.getenv(
    "UNSKEIN_DAO_SKILLS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dao-skills"),
)
# SSH 개인키. 기본 CRED_DIR/id_ed25519, 없으면 id_rsa 차선 탐색.
SSH_KEY = os.getenv("UNSKEIN_SSH_KEY", os.path.join(CRED_DIR, "id_ed25519"))
# SSH known_hosts. 기본 CRED_DIR/known_hosts.
KNOWN_HOSTS = os.getenv(
    "UNSKEIN_SSH_KNOWN_HOSTS", os.path.join(CRED_DIR, "known_hosts")
)


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


def _get(path: str) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        method="GET",
        headers={"X-Mori-Token": MORI_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _claim_body() -> dict:
    """claim 에 실어 보낼 watch 대상 필터. 미지정 항목은 넣지 않는다."""
    body: dict = {}
    if WATCH_BUSINESS:
        body["business"] = WATCH_BUSINESS
    if WATCH_PROJECT:
        body["project"] = WATCH_PROJECT
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
    "plan": (
        "이번 단계: 범위. 먼저 unskein-wiki-search 로 기존 지식을 찾고, "
        "unskein-scope 로 작업을 검증 가능한 수용 기준으로 정리하라."
    ),
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
        "unskein-wiki-lint 로 문서 부패를 점검한 뒤, unskein-deploy 로 커밋·머지·push 하라."
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
    if status == "exec":
        plan_doc = task.get("plan_doc")
        if plan_doc:
            prior = f"\n이전 단계 계획:\n{plan_doc}\n"
    elif status == "inspect":
        result_doc = task.get("result_doc")
        if result_doc:
            prior = f"\n검증 결과:\n{result_doc}\n"

    return (
        header
        + f"대상 repo: {repo}\n"
        + f"작업 폴더 이름: {folder}\n\n"
        + f"현재 디렉토리에 '{folder}' 가 없으면 "
        + f"'git -c credential.helper= clone {repo} {folder}' 로 클론하라"
        + "(credential.helper 빈 값 = 토큰 캐시 저장 차단). "
        + f"이미 있으면 그 안에서 git pull 하라.\n"
        + f"'{folder}' 안으로 들어가 작업을 수행하라.\n"
        + stage_line
        + "\n"
        + prior
        + "\n현재 단계만 수행하고 다음 status 로 보고하라. "
        + "전체 단계 순서를 한 번에 밟지 않는다 — 다음 단계는 모리가 다음에 다시 선점한다.\n"
        + "완료 보고는 CLAUDE.md 4.1 출력 규약을 따른다 — "
        + "'RESULT: status=<다음 status> stage=<단계명> summary=<요약>' 첫 줄, "
        + "산출물이 있으면 그 아래 '<<<UNSKEIN_DOC' ~ 'UNSKEIN_DOC' 펜스 블록. "
        + "막히면 'QUESTION: <질문>' 한 줄."
    )


def run_dao(prompt: str, cwd: str, git_env: dict) -> tuple[int, str, str]:
    """claude -p 비대화형 실행. (returncode, stdout, stderr) 반환.

    git_env 는 build_git_env() 가 만든 환경 — git 자격증명(GIT_SSH_COMMAND/
    GIT_ASKPASS+토큰)과 부모 인증(PATH/HOME/ANTHROPIC)을 함께 담는다.
    자식 다오가 이 env 로 클론·push 를 수행한다.
    """
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
        env=git_env,
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

    # 작업 폴더 보장 — 클론은 다오가 prompt 지시로 수행하므로 cwd 는 존재하는 WORK_ROOT.
    os.makedirs(WORK_ROOT, exist_ok=True)

    # 다오 스킬 이식 — WORK_ROOT 에 CLAUDE.md + .claude/skills/ 를 깐다.
    # 원본 누락은 배포 문제이므로 QUESTION 으로 드러낸다(fallback 금지).
    try:
        plant_dao_skills(WORK_ROOT)
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

    # 2) 프롬프트
    prompt = build_prompt(task)
    print(f"[prompt]\n{prompt}\n")

    # 3) 다오 구동
    print(f"[dao] claude -p 실행 (cwd={WORK_ROOT}, timeout={CLAUDE_TIMEOUT}s) ...")
    try:
        rc, stdout, stderr = run_dao(prompt, WORK_ROOT, git_env)
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

    kind, status, stage, summary, doc = extract_marker(result_text)
    transcript = guess_transcript_path(session_id, WORK_ROOT)

    # 5) 회수
    if kind == "question":
        print(f"[report] QUESTION → {summary}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": summary})
    elif kind == "result":
        # 단계 전이는 오직 마커의 next status 로만 일어난다(하드코딩 done 금지).
        print(f"[report] RESULT → status={status} stage={stage} summary={summary}")
        _post(
            f"/api/mori/tasks/{task_id}/report",
            {
                "summary": summary,
                "session_id": session_id,
                "transcript_path": transcript,
                "status": status,
                "stage": stage,
                "doc": doc,
            },
        )
    else:
        # 마커/status 누락 → 자동 done 금지. 규약대로 보고하지 않았음을 QUESTION 으로 드러낸다(fallback 금지).
        msg = (
            "다오가 단계 완료 마커를 규약대로 내지 않았습니다 "
            "(RESULT: status=.. 펜스 마커 누락). 마지막 출력: "
            + (summary or "(없음)")
        )
        print(f"[report] UNKNOWN → {msg}")
        _post(f"/api/mori/tasks/{task_id}/question", {"question": msg})
    print("[done] 한 바퀴 완료.")
    return 0


def main() -> int:
    # 0) watch 대상 — 인자(bis/prj 등)로 받으면 env 보다 우선 적용한 뒤 검증한다.
    _b, _p, _ = parse_watch_args(sys.argv[1:])
    apply_watch_args(_b, _p)
    # 잘못 지정했으면 선점 전에 멈춘다(조용한 전체 폴백 금지).
    ok, label = resolve_watch_scope()
    if not ok:
        print(f"[watch] {label}")
        return 1
    print(f"[watch] 대상: {label}")

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
