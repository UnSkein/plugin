#!/usr/bin/env python3
"""UnSkein TESTER 케이스 동기화 CLI (push/pull) — tester-case-store 6.3(UNS-550).

TESTER 검증 노하우(케이스)를 서버에 축적해 사용자·단말 간 재사용한다.
키 = (사용자 × 비즈니스 × 호스트 × 기능 × 이름). `bin/memory-sync.py` 의 케이스판.

- push: 로컬 케이스(`case.md` + 폴더 최상위 재사용 스크립트)를 서버에 upsert.
  content_hash 동일이면 skip. **자기 소유 파일만** — `_public/` 은 읽기 전용이라 제외.
- pull: 내 케이스 전부 + 같은 비즈니스의 (해당 호스트) public 케이스 전부를
  로컬에 풀고 `INDEX.md` 를 재생성한다. 남의 public 은 `_public/<작성자>/` 하위.
  받은 스크립트는 케이스 폴더에 **실행 가능한 상태로** 떨군다.

── 로컬 레이아웃 (ADR-0020: UNSKEIN_HOME 규약) ────────────────────────
  $UNSKEIN_HOME/cases/                     (UNSKEIN_HOME 미설정 시 ~/.unskein/cases)
    INDEX.md                               ← pull 이 로컬 파일들로부터 재생성(기계 생성)
    <host>/<feature>/<slug>/case.md        ← 내 케이스 본문
    <host>/<feature>/<slug>/*.js|.mjs|.py|.ps1|.sh   ← 재사용 스크립트(서버 전송)
    <host>/<feature>/<slug>/shots/…        ← 스크린샷 등 파일(케이스 저장소 미전송)
    <host>/<feature>/<slug>/diagnostics/…  ← raw 진단 데이터(케이스 저장소 미전송)
    _public/<작성자>/<host>/<feature>/<slug>/case.md   ← 남의 public(읽기 전용)

**폴더 최상위 스크립트는 전부 올라간다** — public 케이스면 비즈니스 멤버 전체가
본다. 안 올릴 파일은 하위 폴더(`shots/`·`diagnostics/`·임의 폴더)로 옮긴다.
`shots/`·`diagnostics/` 는 케이스가 아니라 **그 회차 작업**에 귀속하는 증거라
이 CLI 가 아니라 `queue.js artifacts` 가 작업에 첨부한다(수명이 다르다 — 스콥
tester-artifact-store §2).

── 케이스 frontmatter 규약 ────────────────────────────────────────────
    ---
    host: localhost-5151          # 호스트 슬러그(디렉토리와 일치 필수)
    feature: forge                # 기능(디렉토리와 일치 필수)
    name: chat-panel-send         # 슬러그 = 디렉토리 이름(일치 필수)
    title: 포지 채팅 패널 전송 검증
    status: success               # success | partial | failed
    tags: [chat, sse]             # 선택
    visibility: public            # public | private (최초 push 기본 public)
    task_id: 1234                 # 선택 — 원 검증 작업
    tested_url: http://localhost:5151/forge   # 선택
    ---
    (본문 5요소: 의뢰서 Why / 실행 시퀀스 How / 결과 What / 함정 Pitfalls / Tips)

호스트 슬러그 규칙(단일 출처 — unskein-test 도 이 명령을 쓴다): URL 의
host[:port] 에서 `:` → `-`. 예: `http://localhost:5151/x` → `localhost-5151`.
파생은 `case-sync.py slug <url>` 로 — 규칙을 손으로 재구현하지 않는다.

── 서버 계약 (6.1 UNS-548 — backend /api/cases/*) ─────────────────────
  POST /api/cases/push  {business_id, items:[{host,feature,name,title,status,
                         tags,visibility,body,scripts?,task_id?,tested_url?}]}
                        → {upserted, skipped, scripts_upserted}
                        (body=파일 원문 전체, 무손실 왕복 · scripts=[{name,body}])
                        스크립트를 실어 보냈는데 응답에 `scripts_upserted` 가 없으면
                        스크립트를 모르는 구서버라 멈춘다(조용히 버려짐 방지).
  GET  /api/cases/pull  ?business_id=&host=     → {items:[…]}
                        item 소유 구분: `mine`(bool) 또는 `owner`(username —
                        /api/whoami 의 user 와 비교). 둘 다 없으면 멈춘다(fallback 금지).
  GET  /api/whoami      X-Unskein-Token — 소유 비교용 username.
  GET  /api/businesses  이름→id 해석(planner 토큰/JWT 전용 — tester/mori 토큰은
                        401 이므로 숫자 id 나 UNSKEIN_BUSINESS_ID 를 쓴다).

── 인증·설정 (env — executor.env / planner.env 공용) ──────────────────
  UNSKEIN_API_BASE 또는 UNSKEIN_API   필수 — 서버 베이스 URL
  UNSKEIN_PLANNER_TOKEN               → X-Planner-Token
  UNSKEIN_MORI_TOKEN                  → X-Mori-Token (EXECUTOR·TESTER 토큰 겸용)
     (둘 중 있는 것을 쓴다 — 어느 kind 토큰이든 같은 사용자로 인가된다.
      없으면 401 로 멈춘다 — fallback 금지.)
  UNSKEIN_BUSINESS_ID                 (선택) business_id 직접 지정 — 이름 해석 생략
  UNSKEIN_BUSINESS / UNSKEIN_WATCH_BUSINESS   (선택) 비즈니스 이름 — --business 생략 시

사용:
  python3 bin/case-sync.py push --business <이름|id> [--host SLUG] [--dry-run] [--chunk N]
  python3 bin/case-sync.py pull --business <이름|id> [--host SLUG]
  python3 bin/case-sync.py slug <url|host[:port]>    # 호스트 슬러그 파생(규칙 단일 출처)
  python3 bin/case-sync.py selftest                  # 오프라인 자체 테스트(서버 불요)

종료코드: 0=성공, 1=오류(설정 누락·인증 실패·규약 위반 — 조용히 넘기지 않는다).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# 윈도우 콘솔(cp949 등)에서 ✓·한글 출력이 UnicodeEncodeError 로 크래시하지 않게
# stdout/stderr 를 UTF-8 로 재구성한다(#563 P2). reconfigure 부재 환경은 그대로 둔다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CASE_FILE = "case.md"
PUBLIC_DIR = "_public"  # 남의 public 케이스 — 읽기 전용, push 제외

# 재사용 스크립트 규약(스콥 tester-artifact-store §3) — 서버 한도와 같은 값을 여기
# 한 자리에 둔다. 두 SKILL.md 는 이 상수를 가리킨다(수치 재기술 금지).
# 이름 규칙에 `$` 대신 `\Z` 를 쓰는 이유: `$` 는 끝의 개행 앞에서도 맞는다.
SCRIPT_EXTS = (".js", ".mjs", ".py", ".ps1", ".sh")
SCRIPT_NAME_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
SCRIPT_MAX_FILES = 10
SCRIPT_MAX_BYTES = 256 * 1024
# POST 당 본문 예산 — 스크립트가 실리면 케이스당 최대 256KB 라 건수만으로 나눈
# 청크가 nginx 본문 한도(413)에 걸린다(#562 P2 가 스크립트 때문에 재발).
PUSH_MAX_BYTES = 1_000_000
INDEX_HEADER = (
    "# 케이스 인덱스\n\n"
    "> `case-sync.py pull` 이 로컬 파일들로부터 재생성하는 기계 생성 파일 — 직접 편집 금지.\n"
)


# ─────────────────────────── 공통 유틸 ───────────────────────────

def _die(msg):
    """오류를 stderr 에 찍고 1 로 종료 — fallback 금지, 조용히 넘기지 않는다."""
    print(f"[case-sync] 오류: {msg}", file=sys.stderr)
    sys.exit(1)


def normalize_body(s):
    """개행 정규화 — 백엔드 _normalize_body 와 동일(무변경 재push 가 no-op 이 되게)."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(s):
    return hashlib.sha256(normalize_body(s).encode("utf-8")).hexdigest()


def host_slug(raw):
    """URL 또는 host[:port] → 호스트 슬러그. 규칙: host[:port] 의 `:` → `-`.

    예: http://localhost:5151/board → localhost-5151 · unskein.mupai.studio →
    unskein.mupai.studio. **이 함수가 슬러그 규칙의 단일 출처** — unskein-test
    (6.4)는 `case-sync.py slug <url>` 로 파생한다(수기 재구현 금지).
    """
    raw = (raw or "").strip()
    if not raw:
        _die("slug 대상이 비었습니다.")
    if "://" in raw:
        netloc = urllib.parse.urlsplit(raw).netloc
    else:
        # scheme 없는 입력: host[:port][/path] — 첫 `/` 앞까지가 netloc
        netloc = raw.split("/", 1)[0]
    netloc = netloc.rsplit("@", 1)[-1]  # userinfo 제거(비밀 무잔존)
    if not netloc:
        _die(f"호스트를 추출할 수 없습니다: {raw!r}")
    return netloc.replace(":", "-")


def sanitize_segment(s):
    """디렉토리 조각 안전화(작성자 이름 등) — 영숫자·`.`·`_`·`-` 외는 `-`."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", s) or "-"


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(text):
    """케이스 frontmatter 파서(이 규약 전용 — PyYAML 비의존, stdlib only).

    반환: (fields, body). 단층 `key: value` 만 지원(케이스 규약에 중첩 없음).
    `tags` 는 `[a, b]` 또는 `a, b` 를 리스트로 푼다. frontmatter 없으면 ({}, text).
    UTF-8 BOM 이 붙은 파일도 규약 위반이 아니다(#562 P3) — 파싱 전에 벗긴다.
    """
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    body = "\n".join(lines[end + 1:])
    fields = {}
    for ln in lines[1:end]:
        if not ln.strip() or ln.lstrip() != ln:  # 빈 줄·들여쓴 줄(중첩) 무시
            continue
        k, _, v = ln.partition(":")
        fields[k.strip()] = _unquote(v)
    if "tags" in fields:
        rawtags = fields["tags"].strip().strip("[]")
        fields["tags"] = [t for t in (x.strip().strip("'\"") for x in rawtags.split(",")) if t]
    return fields, body


def apply_server_visibility(text, server_vis):
    """서버 visibility 컬럼값을 케이스 파일 frontmatter 에 반영한다(#563 P1).

    본문 blob 은 push 원문 그대로 저장되므로, 웹 UI 에서 전환(PATCH)해도 blob 속
    `visibility:` 줄은 옛값이다. pull 이 이 줄만 서버값으로 고쳐 로컬이 서버 진실을
    따라가게 한다(전환의 소유 = 서버/웹 선별). 본문(body)은 건드리지 않는다.
    """
    if not server_vis:
        return text
    fields, _ = parse_frontmatter(text)
    if not fields or (fields.get("visibility") or "public") == server_vis:
        return text
    lines = text.lstrip("\ufeff").split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return text
    for i in range(1, end):
        if lines[i].lstrip() == lines[i] and lines[i].partition(":")[0].strip() == "visibility":
            lines[i] = f"visibility: {server_vis}"
            return "\n".join(lines)
    lines.insert(end, f"visibility: {server_vis}")
    return "\n".join(lines)


def cases_root():
    home = os.environ.get("UNSKEIN_HOME") or os.path.expanduser("~/.unskein")
    return os.path.join(home, "cases")


# ─────────────────────────── 설정·인증 해석 ───────────────────────────

class Config:
    def __init__(self):
        self.api = (
            os.environ.get("UNSKEIN_API_BASE") or os.environ.get("UNSKEIN_API") or ""
        ).rstrip("/")
        if not self.api:
            _die("UNSKEIN_API_BASE(또는 UNSKEIN_API) 가 없습니다 — executor.env/planner.env 를 확인하세요.")
        planner = os.environ.get("UNSKEIN_PLANNER_TOKEN")
        mori = os.environ.get("UNSKEIN_MORI_TOKEN")
        if planner:
            self.token = planner
            self.header = ("X-Planner-Token", planner)
        elif mori:
            self.token = mori
            self.header = ("X-Mori-Token", mori)
        else:
            _die("토큰이 없습니다 — UNSKEIN_PLANNER_TOKEN 또는 UNSKEIN_MORI_TOKEN 필요(fallback 금지).")

    def _req(self, method, path, params=None, body=None, headers=None):
        url = self.api + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or [self.header]):
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            _die(f"{method} {path} → HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            _die(f"{method} {path} → 연결 실패: {e.reason}")

    def get(self, path, params=None, headers=None):
        return self._req("GET", path, params=params, headers=headers)

    def post(self, path, body):
        return self._req("POST", path, body=body)

    def whoami_user(self):
        """소유 구분용 username — GET /api/whoami (어느 kind 토큰이든 받는 유일 라우트)."""
        out = self.get("/api/whoami", headers=[("X-Unskein-Token", self.token)])
        user = out.get("user")
        if not user:
            _die("/api/whoami 응답에 user 가 없습니다 — 서버 버전을 확인하세요.")
        return user

    def resolve_business_id(self, business_arg):
        """business_id 확정 — 숫자면 그대로, 이름이면 서버 조회(planner/JWT 전용).

        tester/mori 토큰은 /api/businesses 를 못 읽으므로(kind 격리) 이름 해석이
        401 로 멈춘다 — 그 경우 숫자 id 또는 UNSKEIN_BUSINESS_ID 를 쓴다(안내 포함).
        """
        raw = (
            business_arg
            or os.environ.get("UNSKEIN_BUSINESS_ID")
            or os.environ.get("UNSKEIN_BUSINESS")
            or os.environ.get("UNSKEIN_WATCH_BUSINESS")
        )
        if not raw:
            _die("비즈니스를 특정할 수 없습니다 — --business <이름|id> 또는 "
                 "UNSKEIN_BUSINESS_ID/UNSKEIN_BUSINESS 를 설정하세요.")
        raw = str(raw).strip()
        if raw.isdigit():
            return int(raw)
        bizzes = self.get("/api/businesses")  # planner/JWT 전용 — tester 토큰이면 여기서 401 로 멈춤
        hit = [b for b in bizzes if b.get("name") == raw]
        if not hit:
            _die(f"비즈니스 '{raw}' 를 목록에서 못 찾음. (tester/mori 토큰은 이름 해석이 "
                 "불가하니 숫자 id 나 UNSKEIN_BUSINESS_ID 를 쓰세요.)")
        return hit[0]["id"]


# ─────────────────────────── 로컬 케이스 스캔 ───────────────────────────

def collect_scripts(case_dir):
    """케이스 폴더 **최상위**의 재사용 스크립트를 수집 — (scripts:[{name,body}], probs:[str]).

    최상위만 훑고 재귀하지 않는다 — 이 한 줄이 `shots/`·`diagnostics/` 제외를
    구조적으로 보장한다(하위 폴더를 아예 열거하지 않으므로 새 하위 폴더가 생겨도
    자동 제외, 목록 유지보수 불요).

    서버와 같은 한도를 여기서 먼저 건다 — 청크 중간에 422 가 나면 앞 청크는 이미
    커밋돼 부분 적용이 남는다. 결정적인 위반(이름·개수·용량·인코딩)은 스캔에서
    걸러 그 케이스만 제외하고, 비밀 탐지는 서버에 맡긴다.
    """
    scripts, probs = [], []
    total = 0
    try:
        entries = sorted(os.listdir(case_dir))
    except OSError as e:
        return scripts, [f"케이스 폴더를 읽을 수 없음: {e}"]
    for fn in entries:
        path = os.path.join(case_dir, fn)
        if fn == CASE_FILE or not os.path.isfile(path):
            continue
        if os.path.splitext(fn)[1].lower() not in SCRIPT_EXTS:
            continue  # 스크립트 확장자가 아닌 최상위 파일은 대상 밖(위반 아님)
        if not SCRIPT_NAME_RE.match(fn):
            probs.append(f"스크립트 이름 규칙 위반: {fn!r} (^[A-Za-z0-9._-]{{1,64}}$)")
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:  # BOM 허용(case.md 와 동일)
                body = normalize_body(fh.read())
        except UnicodeDecodeError:
            # 바이너리·cp949 를 조용히 넘기지 않는다 — 서버는 텍스트만 받는다.
            probs.append(f"스크립트가 UTF-8 이 아님: {fn}")
            continue
        total += len(body.encode("utf-8"))
        scripts.append({"name": fn, "body": body})
    if len(scripts) > SCRIPT_MAX_FILES:
        probs.append(f"스크립트 {len(scripts)}개 — 최대 {SCRIPT_MAX_FILES}개")
    if total > SCRIPT_MAX_BYTES:
        probs.append(f"스크립트 총합 {total}바이트 — 최대 {SCRIPT_MAX_BYTES}바이트")
    return scripts, probs


def scan_local_cases(root, host_filter=None, with_scripts=False):
    """`<root>/<host>/<feature>/<slug>/case.md` 를 (fields, raw, relpath) 로 수집.

    `_public/` 은 제외(읽기 전용). frontmatter 의 host/feature/name 이 디렉토리와
    다르면 오류로 모은다 — 키 불일치는 서버에서 남의 자리·빈손 pull 을 만든다.
    반환: (valid:[dict], errors:[str])

    `with_scripts` 는 **push 만** 켠다(기본 False). INDEX 재생성(_index_lines_for)이
    같은 함수를 작성자 수만큼 다시 부르는데, 거기서 스크립트를 읽으면 파일 I/O 를
    통째로 반복하고 한도 위반 케이스가 INDEX 에서 통째로 사라진다.
    """
    valid, errors = [], []
    if not os.path.isdir(root):
        return valid, errors
    for host in sorted(os.listdir(root)):
        hdir = os.path.join(root, host)
        if not os.path.isdir(hdir) or host == PUBLIC_DIR:
            continue
        if host_filter and host != host_filter:
            continue
        for feature in sorted(os.listdir(hdir)):
            fdir = os.path.join(hdir, feature)
            if not os.path.isdir(fdir):
                continue
            for slug in sorted(os.listdir(fdir)):
                cpath = os.path.join(fdir, slug, CASE_FILE)
                rel = os.path.relpath(cpath, root)
                if not os.path.isfile(cpath):
                    continue
                with open(cpath, encoding="utf-8-sig") as fh:  # BOM 허용(#562 P3)
                    raw = fh.read()
                fields, _ = parse_frontmatter(raw)
                probs = []
                if not fields:
                    probs.append("frontmatter 없음")
                for key, expect in (("host", host), ("feature", feature), ("name", slug)):
                    got = fields.get(key)
                    if got != expect:
                        probs.append(f"{key}={got!r} ≠ 디렉토리 {expect!r}")
                vis = fields.get("visibility") or "public"
                if vis not in ("public", "private"):
                    probs.append(f"visibility={vis!r} (public|private 만)")
                scripts = []
                if with_scripts:
                    scripts, sprobs = collect_scripts(os.path.join(fdir, slug))
                    probs += sprobs  # 스크립트 위반도 같은 오류 채널로 흐른다
                if probs:
                    errors.append(f"{rel}: " + " · ".join(probs))
                    continue
                item = {
                    "host": host,
                    "feature": feature,
                    "name": slug,
                    "title": fields.get("title") or slug,
                    "status": fields.get("status"),
                    "tags": fields.get("tags") if isinstance(fields.get("tags"), list) else None,
                    "visibility": vis,
                    "body": raw,  # 파일 원문 전체 — 무손실 왕복
                }
                if scripts:  # 없으면 키 자체를 안 보낸다(구서버 호환 + 해시 축 불변)
                    item["scripts"] = scripts
                if str(fields.get("task_id") or "").isdigit():
                    item["task_id"] = int(fields["task_id"])
                if fields.get("tested_url"):
                    item["tested_url"] = fields["tested_url"]
                valid.append(item)
    return valid, errors


# ─────────────────────────── push ───────────────────────────

def _chunks(items, max_items, max_bytes=PUSH_MAX_BYTES):
    """건수와 누적 바이트 중 **먼저 닿는 쪽**에서 끊는다(#562 P2 의 스크립트판).

    한 건이 홀로 예산을 넘어도 잘라내지 않고 단독 청크로 보낸다 — 한도 판정은
    서버가 하고 사유를 알린다(클라이언트가 조용히 줄이지 않는다).
    """
    part, size = [], 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False).encode("utf-8"))
        if part and (len(part) >= max_items or size + n > max_bytes):
            yield part
            part, size = [], 0
        part.append(it)
        size += n
    if part:
        yield part


def cmd_push(cfg, root, business_arg, host_filter, dry_run, chunk=50):
    # push 만 스크립트를 함께 읽는다(INDEX 재생성 경로는 기본 False 로 둔다).
    items, errors = scan_local_cases(root, host_filter, with_scripts=True)
    for e in errors:
        print(f"[push] 규약 위반(제외됨): {e}", file=sys.stderr)
    if not items:
        print(f"[push] 보낼 케이스 없음: {root}" + (f" (host={host_filter})" if host_filter else ""))
        return 1 if errors else 0
    business_id = cfg.resolve_business_id(business_arg)
    n_scripts = sum(len(it.get("scripts") or []) for it in items)
    if dry_run:
        for it in items:
            sc = it.get("scripts") or []
            extra = (" · 스크립트 " + ", ".join(s["name"] for s in sc)) if sc else ""
            print(f"[push:dry-run] {it['host']}/{it['feature']}/{it['name']} "
                  f"({it['visibility']}, {len(it['body'])}자){extra}")
        print(f"[push:dry-run] business_id={business_id} 대상 {len(items)}건"
              f"(스크립트 {n_scripts}개), 규약 위반 {len(errors)}건")
        return 1 if errors else 0
    # 대량 push 는 청크로 나눈다(#562 P2) — 단일 POST 는 nginx 본문 한도(413)에 걸린다.
    # 청크 단위 POST 는 멱등(hash 동일 skip)이라 중간 실패 후 재실행이 안전하다.
    chunk = max(1, int(chunk or 50))
    up = sk = su = 0
    done = 0
    parts = list(_chunks(items, chunk))
    for part in parts:
        out = cfg.post("/api/cases/push", {"business_id": business_id, "items": part})
        # 구서버는 모르는 입력 필드(scripts)를 조용히 버린다 — 200 을 받아도 저장이
        # 안 됐을 수 있다. 접수 신호 키의 존재로 판별해 멈춘다(claim skills 에코 검증
        # 과 같은 규약). "올렸다고 믿는 무해한 실패"가 이 자리에서 제일 비싸다.
        if any(p.get("scripts") for p in part) and "scripts_upserted" not in out:
            _die("서버가 스크립트 접수 신호(scripts_upserted)를 돌려주지 않았습니다 — "
                 "스크립트를 모르는 구버전 서버입니다(케이스 본문만 저장됨). "
                 "서버를 갱신한 뒤 다시 push 하세요.")
        up += out.get("upserted", 0)
        sk += out.get("skipped", 0)
        su += out.get("scripts_upserted", 0)
        done += len(part)
        if len(parts) > 1:
            print(f"[push] 진행 {done}/{len(items)}…")
    # scripts 는 "저장/수집" — 무변경(skip) 케이스의 스크립트는 이미 서버에 있어 다시
    # 저장되지 않는다. 두 수가 다른 것이 정상이라 라벨로 못박는다(실패로 읽히지 않게).
    print(f"[push] business_id={business_id}: upserted={up} skipped={sk} "
          f"scripts={su} 저장/{n_scripts} 수집"
          + (f" · 규약 위반 제외 {len(errors)}건" if errors else ""))
    return 1 if errors else 0


# ─────────────────────────── pull ───────────────────────────

def _item_is_mine(item, my_user):
    """pull 응답 1건의 소유 판정 — `mine`(bool) 우선, 없으면 `owner`==whoami.user.

    둘 다 없으면 서버 계약 불일치 — 조용히 남의 것을 내 것으로 두지 않고 멈춘다.
    """
    if "mine" in item:
        return bool(item["mine"])
    if item.get("owner"):
        return item["owner"] == my_user
    _die("pull 응답에 소유 구분 필드(mine/owner)가 없습니다 — 서버(6.1) 계약을 확인하세요.")


def _write_scripts(cdir, scripts):
    """받은 스크립트를 케이스 폴더에 **실행 가능한 상태로** 떨군다 — (written, skipped, probs).

    이름을 여기서 다시 검증한다 — pull 은 남의 public 도 받으므로 파일명이 곧 로컬
    쓰기 경로다(서버 검증을 믿지 않는 이중 방어). 위반은 조용히 버리지 않고 probs
    로 올려 호출부가 stderr 와 종료코드에 싣는다.

    **삭제는 하지 않는다** — 서버에서 사라진 스크립트를 로컬에서 지우면 테스터가
    작업 중인 파일을 없앨 수 있다. 이 비대칭(덮어쓰되 지우지 않음)은 case.md 와 같다.
    """
    written = skipped = 0
    probs = []
    for s in scripts or []:
        name = (s or {}).get("name") or ""
        body = (s or {}).get("body") or ""
        if (not SCRIPT_NAME_RE.match(name) or os.path.basename(name) != name
                or name in (".", "..")):
            probs.append(f"스크립트 이름 규칙 위반 — 저장 안 함: {name!r}")
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in SCRIPT_EXTS:
            probs.append(f"스크립트 확장자 허용 밖 — 저장 안 함: {name}")
            continue
        path = os.path.join(cdir, name)
        # 정규식 뒤 이중 방어 — 심링크 등으로 케이스 폴더 밖을 가리키면 쓰지 않는다.
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(cdir):
            probs.append(f"케이스 폴더 밖을 가리킴 — 저장 안 함: {name}")
            continue
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    if content_hash(fh.read()) == content_hash(body):
                        skipped += 1  # 무변경 — no-op(멱등)
                        continue
            except (OSError, UnicodeDecodeError):
                pass  # 로컬본을 못 읽으면 서버본으로 덮는다(pull = 서버 진실 실체화)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        if os.name == "posix" and ext in (".sh", ".py"):
            os.chmod(path, 0o755)  # 받고 나서 바로 실행 가능해야 한다(스펙 §3)
        written += 1
    return written, skipped, probs


def cmd_pull(cfg, root, business_arg, host_filter):
    business_id = cfg.resolve_business_id(business_arg)
    my_user = cfg.whoami_user()
    params = {"business_id": business_id}
    if host_filter:
        params["host"] = host_filter
    out = cfg.get("/api/cases/pull", params=params)

    written = skipped = 0
    sc_written = sc_skipped = bad = 0
    for item in out.get("items", []):
        host, feature, name = item.get("host"), item.get("feature"), item.get("name")
        if not (host and feature and name):
            _die(f"pull 항목에 키(host/feature/name)가 없습니다: {item.keys()}")
        if _item_is_mine(item, my_user):
            cdir = os.path.join(root, host, feature, name)
        else:
            owner = sanitize_segment(item.get("owner") or "unknown")
            cdir = os.path.join(root, PUBLIC_DIR, owner, host, feature, name)
        os.makedirs(cdir, exist_ok=True)
        path = os.path.join(cdir, CASE_FILE)
        # 서버 visibility 컬럼을 frontmatter 에 병합(#563 P1) — 웹 전환은 컬럼만 바꾸고
        # blob 은 push 원문이라, 병합 없이는 본문 hash 동일 = skip 으로 전환이 영영 안 내려온다.
        body = apply_server_visibility(item.get("body") or "", item.get("visibility"))
        unchanged = False
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as fh:
                unchanged = content_hash(fh.read()) == content_hash(body)
        if unchanged:
            skipped += 1  # 무변경 — no-op(멱등)
        else:
            with open(path, "w", encoding="utf-8") as fh:  # pull=서버 진실 실체화
                fh.write(body)
            written += 1
        # 스크립트 낙하는 case.md 변경 여부와 **무관**하게 돈다 — 무변경 케이스에서
        # 건너뛰면 본문이 안 바뀐 케이스는 스크립트를 영영 못 받는다(조용한 실패).
        sw, ss, probs = _write_scripts(cdir, item.get("scripts"))
        sc_written += sw
        sc_skipped += ss
        for p in probs:
            print(f"[pull] {host}/{feature}/{name}: {p}", file=sys.stderr)
            bad += 1

    regenerate_index(root)
    print(f"[pull] business_id={business_id}" + (f" host={host_filter}" if host_filter else "") + f" → {root}")
    print(f"[pull] 파일 written={written} skipped={skipped} · "
          f"스크립트 written={sc_written} skipped={sc_skipped} · INDEX.md 재생성 완료")
    if bad:
        print(f"[pull] 규약 위반으로 저장하지 않은 스크립트 {bad}건 — 위 목록 확인", file=sys.stderr)
    return 1 if bad else 0


# ─────────────────────────── INDEX.md ───────────────────────────

def _index_lines_for(root, base_rel=""):
    """`<root>` 의 host/feature/slug 트리 → 인덱스 불릿. base_rel 은 링크 접두."""
    lines = []
    valid, _ = scan_local_cases(root)
    by_host = {}
    for it in valid:
        by_host.setdefault(it["host"], []).append(it)
    for host in sorted(by_host):
        lines.append(f"\n## {host}\n")
        for it in by_host[host]:
            rel = "/".join(filter(None, [base_rel, it["host"], it["feature"], it["name"], CASE_FILE]))
            status = f" ({it['status']})" if it.get("status") else ""
            lines.append(f"- [{it['feature']}/{it['name']}]({rel}) — {it['title']}{status}")
    return lines


def regenerate_index(root):
    """INDEX.md 를 실제 로컬 파일 집합으로부터 재생성 — 원격 blob 통째 sync 금지.

    (메모리 동기의 MEMORY.md 규약과 동일한 충돌 회피 — 인덱스=파일집합 일치.)
    내 케이스 → 호스트별 절, 남의 public → `_public` 절(작성자 표기).
    """
    lines = [INDEX_HEADER.rstrip("\n")]
    lines += _index_lines_for(root)
    pub_root = os.path.join(root, PUBLIC_DIR)
    if os.path.isdir(pub_root):
        pub_lines = []
        for owner in sorted(os.listdir(pub_root)):
            odir = os.path.join(pub_root, owner)
            if not os.path.isdir(odir):
                continue
            for ln in _index_lines_for(odir, base_rel=f"{PUBLIC_DIR}/{owner}"):
                if ln.startswith("- "):
                    pub_lines.append(ln + f" · by {owner}")
                elif ln.startswith("\n## "):
                    pub_lines.append(ln.replace("## ", f"## {PUBLIC_DIR}: "))
        if pub_lines:
            lines.append("\n---\n\n# 공유 케이스 (읽기 전용 — push 제외)")
            lines += pub_lines
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")


# ─────────────────────────── selftest (오프라인) ───────────────────────────

def cmd_selftest():
    """서버 없이 슬러그·frontmatter·스캔 규약·소유 분리·인덱스 재생성 검증."""
    import shutil
    import tempfile

    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + label)
        ok = ok and cond

    # 1) 호스트 슬러그 규칙(6.4 와 한 글자까지 일치해야 하는 단일 출처)
    check(host_slug("http://localhost:5151/board?x=1") == "localhost-5151", "slug: URL+포트")
    check(host_slug("https://unskein.mupai.studio") == "unskein.mupai.studio", "slug: 포트 없음")
    check(host_slug("localhost:5151") == "localhost-5151", "slug: scheme 없음")
    check(host_slug("localhost-5151") == "localhost-5151", "slug: 이미 슬러그(멱등)")
    check(host_slug("http://user:pw@h.example:9000/") == "h.example-9000", "slug: userinfo 제거")

    # 2) frontmatter 파싱
    sample = (
        "---\nhost: localhost-5151\nfeature: forge\nname: chat-send\n"
        "title: 채팅 전송\nstatus: success\ntags: [chat, sse]\nvisibility: public\n"
        "task_id: 42\n---\n\n## Why\n본문\n"
    )
    fields, body = parse_frontmatter(sample)
    check(fields.get("name") == "chat-send", "frontmatter name")
    check(fields.get("tags") == ["chat", "sse"], "tags 리스트 파싱")
    check(body.strip().startswith("## Why"), "body 분리")
    check(content_hash("a\r\nb") == content_hash("a\nb"), "content_hash 개행 정규화")

    # 3) 스캔: 규약 위반 검출 + _public 제외
    root = tempfile.mkdtemp(prefix="casesync-")
    def put(rel, text):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    put("localhost-5151/forge/chat-send/case.md", sample)
    put("localhost-5151/forge/chat-send/shots/01.png", "png")
    # 스크립트 픽스처 — 최상위만 수집(shots/·diagnostics/ 하위는 구조적으로 제외).
    put("localhost-5151/forge/chat-send/scan-formdef.js", "console.log(1)\n")
    put("localhost-5151/forge/chat-send/helper.ps1", "Write-Host 1\r\nWrite-Host 2\r\n")
    put("localhost-5151/forge/chat-send/notes.md", "스크립트 아님\n")
    put("localhost-5151/forge/chat-send/diagnostics/deep.js", "not collected\n")
    bad = sample.replace("name: chat-send", "name: wrong-slug")
    put("localhost-5151/forge/bad-case/case.md", bad)
    put("_public/alice/localhost-5151/forge/their-case/case.md",
        sample.replace("name: chat-send", "name: their-case"))
    valid, errors = scan_local_cases(root)
    check(len(valid) == 1 and valid[0]["name"] == "chat-send", "정상 케이스 1건 수집")
    check(len(errors) == 1 and "bad-case" in errors[0], "키 불일치 검출")
    check(all("_public" not in v["host"] for v in valid), "_public push 제외")
    check(valid[0]["task_id"] == 42, "task_id 정수 변환")
    check("scripts" not in valid[0], "기본 스캔은 스크립트를 안 읽는다(INDEX 재생성용)")

    # 3-1) 스크립트 수집(push 경로) — 최상위만, 하위 폴더·비대상 확장자 제외
    vs, es = scan_local_cases(root, with_scripts=True)
    names = [s["name"] for s in vs[0]["scripts"]]
    check(names == ["helper.ps1", "scan-formdef.js"], "최상위 스크립트만 수집(정렬)")
    check(all("deep.js" != n and "01.png" != n for n in names), "하위 폴더 제외")
    check("notes.md" not in names, "스크립트 확장자 아닌 최상위 파일 제외")
    ps1 = [s for s in vs[0]["scripts"] if s["name"] == "helper.ps1"][0]
    check("\r" not in ps1["body"], "윈도우 CRLF 정규화(매 push 해시 뒤집힘 방지)")
    check(len(es) == 1, "스크립트 수집이 기존 오류 카운트를 흔들지 않음")

    # 3-2) 스크립트 규약 위반 — 이름·개수·용량(별도 폴더라 위 카운트에 영향 없음)
    sdir = tempfile.mkdtemp(prefix="casescripts-")
    with open(os.path.join(sdir, "a" * 62 + ".js"), "w", encoding="utf-8") as fh:
        fh.write("x")
    _, p1 = collect_scripts(sdir)
    check(any("이름 규칙" in p for p in p1), "이름 64자 초과 거부")
    shutil.rmtree(sdir, ignore_errors=True)
    sdir = tempfile.mkdtemp(prefix="casescripts-")
    for i in range(SCRIPT_MAX_FILES + 1):
        with open(os.path.join(sdir, f"s{i}.js"), "w", encoding="utf-8") as fh:
            fh.write("x")
    _, p2 = collect_scripts(sdir)
    check(any("최대 10개" in p for p in p2), "개수 한도 초과 거부")
    shutil.rmtree(sdir, ignore_errors=True)
    sdir = tempfile.mkdtemp(prefix="casescripts-")
    with open(os.path.join(sdir, "big.js"), "w", encoding="utf-8") as fh:
        fh.write("x" * (SCRIPT_MAX_BYTES + 1))
    _, p3 = collect_scripts(sdir)
    check(any("총합" in p for p in p3), "용량 한도 초과 거부")
    shutil.rmtree(sdir, ignore_errors=True)

    # 3-3) 청크 — 건수·바이트 중 먼저 닿는 쪽에서 끊는다
    small = [{"name": f"c{i}", "body": "x"} for i in range(5)]
    check(len(list(_chunks(small, 2))) == 3, "청크: 건수로 분할")
    heavy = [{"name": f"c{i}", "body": "x" * 400_000} for i in range(4)]
    # 건수(50)로만 나누면 1청크 1.6MB → 413. 바이트 예산이 2청크로 끊는다.
    check(len(list(_chunks(heavy, 50))) == 2, "청크: 바이트 예산으로 분할")
    check(sum(len(p) for p in _chunks(heavy, 50)) == 4, "청크: 항목 유실 없음")
    huge = [{"name": "big", "body": "x" * (PUSH_MAX_BYTES + 10)}]
    check(len(list(_chunks(huge, 50))) == 1, "청크: 예산 초과 1건도 잘라내지 않고 단독 전송")

    # 3-4) pull 낙하(_write_scripts) — 이름 재검증·멱등·삭제 안 함
    wdir = tempfile.mkdtemp(prefix="casewrite-")
    w, s, probs = _write_scripts(wdir, [{"name": "run.js", "body": "a\n"}])
    check((w, s, probs) == (1, 0, []), "스크립트 낙하: 신규 1건")
    w2, s2, _ = _write_scripts(wdir, [{"name": "run.js", "body": "a\n"}])
    check((w2, s2) == (0, 1), "스크립트 낙하: 무변경 skip(멱등)")
    _, _, bad_probs = _write_scripts(wdir, [
        {"name": "../escape.js", "body": "x"},
        {"name": "sub/dir.js", "body": "x"},
        {"name": "run.exe", "body": "x"},
    ])
    check(len(bad_probs) == 3, "스크립트 낙하: 이름·확장자 위반 3건 거부")
    check(not os.path.exists(os.path.join(os.path.dirname(wdir), "escape.js")),
          "스크립트 낙하: 상위 경로에 쓰지 않음")
    _write_scripts(wdir, [{"name": "keep.sh", "body": "echo 1\n"}])
    if os.name == "posix":
        check(os.access(os.path.join(wdir, "keep.sh"), os.X_OK), "스크립트 낙하: 실행 권한")
    _write_scripts(wdir, [{"name": "run.js", "body": "a\n"}])
    check(os.path.isfile(os.path.join(wdir, "keep.sh")),
          "스크립트 낙하: 서버에 없는 로컬 파일을 지우지 않음")
    shutil.rmtree(wdir, ignore_errors=True)

    # 4) pull 소유 분리 + 멱등 + 인덱스
    check(_item_is_mine({"mine": True}, "me") is True, "mine 필드 우선")
    check(_item_is_mine({"owner": "me"}, "me") is True, "owner==whoami → 내 것")
    check(_item_is_mine({"owner": "alice"}, "me") is False, "owner≠whoami → 남의 것")

    # 5) 서버 visibility 병합(#563 P1) — 전환의 소유는 서버/웹 선별
    merged = apply_server_visibility(sample, "private")
    mf, mb = parse_frontmatter(merged)
    check(mf.get("visibility") == "private", "visibility 병합: public→private")
    check(mb == parse_frontmatter(sample)[1], "visibility 병합: 본문 불변")
    check(apply_server_visibility(sample, "public") is sample, "visibility 병합: 동일값 no-op")
    novis = sample.replace("visibility: public\n", "")
    check(parse_frontmatter(apply_server_visibility(novis, "private"))[0].get("visibility") == "private",
          "visibility 병합: 줄 없으면 삽입")

    # 6) BOM 허용(#562 P3)
    bf, _ = parse_frontmatter("\ufeff" + sample)
    check(bf.get("name") == "chat-send", "BOM 붙은 frontmatter 파싱")
    put("localhost-5151/forge/bom-case/case.md",
        "\ufeff" + sample.replace("name: chat-send", "name: bom-case"))
    valid2, errors2 = scan_local_cases(root)
    check(any(v["name"] == "bom-case" for v in valid2), "BOM 붙은 케이스 스캔 통과")
    check(len(errors2) == 1, "BOM 이 규약 위반으로 오인되지 않음")
    regenerate_index(root)
    with open(os.path.join(root, "INDEX.md"), encoding="utf-8") as fh:
        idx = fh.read()
    check("(localhost-5151/forge/chat-send/case.md)" in idx, "인덱스: 내 케이스")
    check("_public/alice/localhost-5151/forge/their-case/case.md" in idx, "인덱스: 공유 케이스")
    check("by alice" in idx, "인덱스: 작성자 표기")
    check("bad-case" not in idx, "인덱스: 규약 위반 제외")

    shutil.rmtree(root, ignore_errors=True)
    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ─────────────────────────── main ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="UnSkein TESTER 케이스 push/pull 동기화")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("push", "pull"):
        sp = sub.add_parser(name)
        sp.add_argument("--business", default=None,
                        help="비즈니스 이름 또는 id (생략 시 UNSKEIN_BUSINESS_ID/UNSKEIN_BUSINESS). "
                             "이름 해석은 planner 토큰 전용 — tester/mori 토큰은 id 를 쓴다.")
        sp.add_argument("--host", default=None, help="호스트 슬러그로 한정(예: localhost-5151)")
        sp.add_argument("--cases-dir", default=None, help="케이스 루트 직접 지정(테스트용)")
    sub.choices["push"].add_argument("--dry-run", action="store_true",
                                     help="POST 없이 보낼 목록만 출력")
    sub.choices["push"].add_argument("--chunk", type=int, default=50,
                                     help="POST 당 케이스 수(기본 50) — 대량 push 413 회피(#562 P2)")
    sp = sub.add_parser("slug", help="URL/host[:port] → 호스트 슬러그(규칙 단일 출처)")
    sp.add_argument("target")
    sub.add_parser("selftest")

    args = ap.parse_args()

    if args.cmd == "selftest":
        return cmd_selftest()
    if args.cmd == "slug":
        print(host_slug(args.target))
        return 0

    root = args.cases_dir or cases_root()
    cfg = Config()
    if args.cmd == "push":
        return cmd_push(cfg, root, args.business, args.host, args.dry_run, args.chunk)
    if args.cmd == "pull":
        return cmd_pull(cfg, root, args.business, args.host)
    return 1


if __name__ == "__main__":
    sys.exit(main())
