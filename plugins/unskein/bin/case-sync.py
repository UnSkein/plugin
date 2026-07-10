#!/usr/bin/env python3
"""UnSkein TESTER 케이스 동기화 CLI (push/pull) — tester-case-store 6.3(UNS-550).

TESTER 검증 노하우(케이스)를 서버에 축적해 사용자·단말 간 재사용한다.
키 = (사용자 × 비즈니스 × 호스트 × 기능 × 이름). `bin/memory-sync.py` 의 케이스판.

- push: 로컬 케이스(`case.md`)들을 서버에 upsert. 파일(shots/ 등)은 제외,
  content_hash 동일이면 skip. **자기 소유 파일만** — `_public/` 은 읽기 전용이라 제외.
- pull: 내 케이스 전부 + 같은 비즈니스의 (해당 호스트) public 케이스 전부를
  로컬에 풀고 `INDEX.md` 를 재생성한다. 남의 public 은 `_public/<작성자>/` 하위.

── 로컬 레이아웃 (ADR-0020: UNSKEIN_HOME 규약) ────────────────────────
  $UNSKEIN_HOME/cases/                     (UNSKEIN_HOME 미설정 시 ~/.unskein/cases)
    INDEX.md                               ← pull 이 로컬 파일들로부터 재생성(기계 생성)
    <host>/<feature>/<slug>/case.md        ← 내 케이스(본문만 서버로)
    <host>/<feature>/<slug>/shots/…        ← 스크린샷 등 파일(서버 미전송)
    <host>/<feature>/<slug>/diagnostics/…  ← raw 진단 데이터(서버 미전송)
    _public/<작성자>/<host>/<feature>/<slug>/case.md   ← 남의 public(읽기 전용)

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
                         tags,visibility,body,task_id?,tested_url?}]}
                        → {upserted, skipped}   (body=파일 원문 전체, 무손실 왕복)
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
  python3 bin/case-sync.py push --business <이름|id> [--host SLUG] [--dry-run]
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

CASE_FILE = "case.md"
PUBLIC_DIR = "_public"  # 남의 public 케이스 — 읽기 전용, push 제외
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
    """
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

def scan_local_cases(root, host_filter=None):
    """`<root>/<host>/<feature>/<slug>/case.md` 를 (fields, raw, relpath) 로 수집.

    `_public/` 은 제외(읽기 전용). frontmatter 의 host/feature/name 이 디렉토리와
    다르면 오류로 모은다 — 키 불일치는 서버에서 남의 자리·빈손 pull 을 만든다.
    반환: (valid:[dict], errors:[str])
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
                with open(cpath, encoding="utf-8") as fh:
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
                if str(fields.get("task_id") or "").isdigit():
                    item["task_id"] = int(fields["task_id"])
                if fields.get("tested_url"):
                    item["tested_url"] = fields["tested_url"]
                valid.append(item)
    return valid, errors


# ─────────────────────────── push ───────────────────────────

def cmd_push(cfg, root, business_arg, host_filter, dry_run):
    items, errors = scan_local_cases(root, host_filter)
    for e in errors:
        print(f"[push] 규약 위반(제외됨): {e}", file=sys.stderr)
    if not items:
        print(f"[push] 보낼 케이스 없음: {root}" + (f" (host={host_filter})" if host_filter else ""))
        return 1 if errors else 0
    business_id = cfg.resolve_business_id(business_arg)
    if dry_run:
        for it in items:
            print(f"[push:dry-run] {it['host']}/{it['feature']}/{it['name']} "
                  f"({it['visibility']}, {len(it['body'])}자)")
        print(f"[push:dry-run] business_id={business_id} 대상 {len(items)}건, 규약 위반 {len(errors)}건")
        return 1 if errors else 0
    out = cfg.post("/api/cases/push", {"business_id": business_id, "items": items})
    up, sk = out.get("upserted", 0), out.get("skipped", 0)
    print(f"[push] business_id={business_id}: upserted={up} skipped={sk}"
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


def cmd_pull(cfg, root, business_arg, host_filter):
    business_id = cfg.resolve_business_id(business_arg)
    my_user = cfg.whoami_user()
    params = {"business_id": business_id}
    if host_filter:
        params["host"] = host_filter
    out = cfg.get("/api/cases/pull", params=params)

    written = skipped = 0
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
        body = item.get("body") or ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                if content_hash(fh.read()) == content_hash(body):
                    skipped += 1  # 무변경 — no-op(멱등)
                    continue
        with open(path, "w", encoding="utf-8") as fh:  # pull=서버 진실 실체화
            fh.write(body)
        written += 1

    regenerate_index(root)
    print(f"[pull] business_id={business_id}" + (f" host={host_filter}" if host_filter else "") + f" → {root}")
    print(f"[pull] 파일 written={written} skipped={skipped} · INDEX.md 재생성 완료")
    return 0


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
    bad = sample.replace("name: chat-send", "name: wrong-slug")
    put("localhost-5151/forge/bad-case/case.md", bad)
    put("_public/alice/localhost-5151/forge/their-case/case.md",
        sample.replace("name: chat-send", "name: their-case"))
    valid, errors = scan_local_cases(root)
    check(len(valid) == 1 and valid[0]["name"] == "chat-send", "정상 케이스 1건 수집")
    check(len(errors) == 1 and "bad-case" in errors[0], "키 불일치 검출")
    check(all("_public" not in v["host"] for v in valid), "_public push 제외")
    check(valid[0]["task_id"] == 42, "task_id 정수 변환")

    # 4) pull 소유 분리 + 멱등 + 인덱스
    check(_item_is_mine({"mine": True}, "me") is True, "mine 필드 우선")
    check(_item_is_mine({"owner": "me"}, "me") is True, "owner==whoami → 내 것")
    check(_item_is_mine({"owner": "alice"}, "me") is False, "owner≠whoami → 남의 것")
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
        return cmd_push(cfg, root, args.business, args.host, args.dry_run)
    if args.cmd == "pull":
        return cmd_pull(cfg, root, args.business, args.host)
    return 1


if __name__ == "__main__":
    sys.exit(main())
