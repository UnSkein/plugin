#!/usr/bin/env python3
"""UnSkein 사용자 메모리 동기화 CLI (push/pull) — user-memory-db-sync §1.1.2.

로컬 Claude Code 메모리(`~/.claude/projects/<slug>/memory/*.md`)를 서버 DB에
`(사용자 × 프로젝트 × 역할)` 로 올리고(push) 새 단말에서 내려받아(pull) 복원한다.
경로 무관 이식: DB는 원시 slug가 아니라 논리 `(user, project, role)` 로 키잉하고,
pull이 현재 머신의 cwd로 slug를 다시 만들어 파일을 푼다(수용기준 8).

── frontmatter 3축 규약 (수용기준 11) ────────────────────────────────
메모리 파일 frontmatter 의 `metadata` 블록에 세 축을 싣는다:

    ---
    name: <슬러그 = 파일명 stem>
    description: <한 줄 요약>
    metadata:
      type: user | feedback | project | reference   # 기존 축
      project: <프로젝트 이름 또는 id>               # 축1 — 어느 프로젝트
      role:    planner | executor | operator         # 축2 — 어느 역할
      scope:   private | shared                       # 축3 — 사적/공유
      # maturity:  (예약 — 값 없음. 후속 B: raw|refined)
    ---

값 없는 구(舊) 파일 기본값: `project`=현 매핑, `role`=토큰 kind 파생(기본 planner),
`scope`=private. **`scope=private` 만 push 대상** — `scope=shared` 는 skip한다
(승격 후보 — repo/CLAUDE.md/wiki 로 사람이 수동 승격). **`MEMORY.md` 는 인덱스라
sync 대상이 아니다** — pull이 로컬 파일들로부터 재생성한다(원격 blob 통째 sync 금지,
충돌 핫스팟 — 수용기준 7·9). 이 CLI는 로컬 파일을 재작성하지 않는다(축 없는 파일은
기본값으로 취급만 하고 원본 보존).

── 인증·설정 (env — planner.env / executor.env 공용) ──────────────────
  UNSKEIN_API                    필수 — 서버 베이스 URL
  UNSKEIN_PLANNER_TOKEN          → X-Planner-Token (kind=planner → role=planner)
  UNSKEIN_MORI_TOKEN             → X-Mori-Token    (kind=mori   → role=executor)
     (둘 중 있는 것을 쓴다. 없으면 401 로 멈춘다 — fallback 금지.)
  UNSKEIN_BUSINESS / UNSKEIN_WATCH_BUSINESS   비즈니스 이름
  UNSKEIN_PROJECT  / UNSKEIN_WATCH_PROJECT    프로젝트 이름 → project_id 해석
  UNSKEIN_PROJECT_ID             (선택) project_id 직접 지정 — 이름 해석 생략

사용:
  python3 bin/memory-sync.py push [--codebase DIR] [--role ROLE] [--dry-run]
  python3 bin/memory-sync.py pull [--codebase DIR] [--role ROLE]
  python3 bin/memory-sync.py selftest         # 오프라인 왕복 자체 테스트(서버 불요)

종료코드: 0=성공, 1=오류(설정 누락·인증 실패·서버 오류 — 조용히 넘기지 않는다).
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

MEMORY_ROLES = ["executor", "operator", "planner"]  # backend models.MEMORY_ROLES 와 동일


# ─────────────────────────── 공통 유틸 ───────────────────────────

def _die(msg):
    """오류를 stderr 에 찍고 1 로 종료 — fallback 금지, 조용히 넘기지 않는다."""
    print(f"[memory-sync] 오류: {msg}", file=sys.stderr)
    sys.exit(1)


def normalize_body(s):
    """개행 정규화 — 백엔드 _normalize_body 와 동일(무변경 재push 가 no-op 이 되게)."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(s):
    return hashlib.sha256(normalize_body(s).encode("utf-8")).hexdigest()


def slug_for(path):
    """cwd(또는 코드베이스) 절대경로의 `/` 를 `-` 로 치환한 transcript slug.

    예: /home/mupai/unskein → -home-mupai-unskein. **소스 머신 slug 와 무관하게
    현재 머신 경로에서 만든다**(경로 이식성 — 수용기준 8).
    """
    ap = os.path.abspath(path).rstrip("/")
    return ap.replace("/", "-")


def memory_dir_for(codebase):
    slug = slug_for(codebase)
    return os.path.join(os.path.expanduser("~/.claude/projects"), slug, "memory")


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(text):
    """메모리 파일 frontmatter 파서(이 규약 전용 — PyYAML 비의존, stdlib only).

    반환: (fields, body). fields 는 최상위 키(name/description/…) + `metadata` 는
    중첩 dict. 첫 `---`~다음 `---` 사이만 frontmatter. frontmatter 없으면 ({}, text).
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
    metadata = {}
    in_meta = False
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        if ln[0] in (" ", "\t"):  # 들여쓴 줄 → metadata 자식
            if in_meta:
                k, _, v = ln.strip().partition(":")
                metadata[k.strip()] = _unquote(v)
            continue
        in_meta = False
        k, _, v = ln.partition(":")
        k = k.strip()
        if k == "metadata":
            in_meta = True
            fields["metadata"] = metadata
            continue
        fields[k] = _unquote(v)
    fields.setdefault("metadata", metadata)
    return fields, body


# ─────────────────────────── 설정·인증 해석 ───────────────────────────

class Config:
    def __init__(self):
        self.api = (os.environ.get("UNSKEIN_API") or "").rstrip("/")
        if not self.api:
            _die("UNSKEIN_API 가 없습니다 (planner.env/executor.env 를 source 했는지 확인).")
        planner = os.environ.get("UNSKEIN_PLANNER_TOKEN")
        mori = os.environ.get("UNSKEIN_MORI_TOKEN")
        if planner:
            self.header = ("X-Planner-Token", planner)
        elif mori:
            self.header = ("X-Mori-Token", mori)
        else:
            _die("토큰이 없습니다 — UNSKEIN_PLANNER_TOKEN 또는 UNSKEIN_MORI_TOKEN 필요(fallback 금지).")
        self.business = os.environ.get("UNSKEIN_BUSINESS") or os.environ.get("UNSKEIN_WATCH_BUSINESS")
        self.project = os.environ.get("UNSKEIN_PROJECT") or os.environ.get("UNSKEIN_WATCH_PROJECT")
        self.project_id_env = os.environ.get("UNSKEIN_PROJECT_ID")

    def _req(self, method, path, params=None, body=None):
        url = self.api + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header(self.header[0], self.header[1])
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            _die(f"{method} {path} → HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            _die(f"{method} {path} → 연결 실패: {e.reason}")

    def get(self, path, params=None):
        return self._req("GET", path, params=params)

    def post(self, path, body):
        return self._req("POST", path, body=body)

    def resolve_project_id(self):
        """project_id 확정 — 명시값 우선, 없으면 비즈니스/프로젝트 **이름**으로 서버 조회.

        토큰은 사용자만 식별하지 프로젝트를 모르므로(ADR-0013) 클라이언트가 이름으로
        보충한다(unskein-scope §0/ADR-0022 와 동일 메커니즘). 못 짚으면 멈춘다(fallback 금지).
        """
        if self.project_id_env:
            try:
                return int(self.project_id_env)
            except ValueError:
                _die(f"UNSKEIN_PROJECT_ID 가 정수가 아닙니다: {self.project_id_env!r}")
        if not (self.business and self.project):
            _die("프로젝트를 특정할 수 없습니다 — UNSKEIN_BUSINESS+UNSKEIN_PROJECT(또는 "
                 "UNSKEIN_WATCH_*) 이름이나 UNSKEIN_PROJECT_ID 를 설정하세요.")
        bizzes = self.get("/api/businesses")
        biz = [b for b in bizzes if b.get("name") == self.business]
        if not biz:
            _die(f"비즈니스 '{self.business}' 를 목록에서 못 찾음.")
        biz_id = biz[0]["id"]
        projs = self.get(f"/api/businesses/{biz_id}/projects")
        pr = [p for p in projs if p.get("name") == self.project]
        if not pr:
            _die(f"프로젝트 '{self.project}' 를 비즈니스 '{self.business}' 에서 못 찾음.")
        return pr[0]["id"]


# ─────────────────────────── push ───────────────────────────

def _list_memory_files(memory_dir):
    if not os.path.isdir(memory_dir):
        return []
    return sorted(
        f for f in os.listdir(memory_dir)
        if f.endswith(".md") and f != "MEMORY.md"
    )


def cmd_push(cfg, memory_dir, role_override, dry_run):
    files = _list_memory_files(memory_dir)
    if not files:
        print(f"[push] 메모리 파일 없음: {memory_dir} — 보낼 것 없음.")
        return 0
    project_id = cfg.resolve_project_id()

    # 파일별 → 효과적 role 로 그룹핑(축 보존). role 없으면 None(서버가 토큰 kind 로 파생).
    groups = {}  # role(str|None) → [MemoryItem]
    n_shared = 0
    for fn in files:
        with open(os.path.join(memory_dir, fn), encoding="utf-8") as fh:
            raw = fh.read()
        fields, _ = parse_frontmatter(raw)
        meta = fields.get("metadata", {})
        scope = (meta.get("scope") or "private").strip()
        if scope != "private":
            n_shared += 1  # 공유는 DB 미저장(승격 후보)
            continue
        name = fn[:-3]  # 파일 identity = stem (라운드트립 안정)
        item = {
            "name": name,
            "description": fields.get("description"),
            "type": meta.get("type"),
            "body": raw,          # 전체 원문(frontmatter 포함) — 무손실 왕복
            "scope": "private",
        }
        role = role_override or (meta.get("role") or "").strip() or None
        groups.setdefault(role, []).append(item)

    total_up = total_skip = 0
    for role, items in groups.items():
        body = {"project_id": project_id, "items": items}
        if role:
            body["role"] = role
        label = role or "(토큰 kind 파생)"
        if dry_run:
            print(f"[push:dry-run] role={label} project_id={project_id} items={len(items)}: "
                  + ", ".join(i["name"] for i in items))
            continue
        out = cfg.post("/api/memory/push", body)
        up, sk = out.get("upserted", 0), out.get("skipped", 0)
        total_up += up
        total_skip += sk
        print(f"[push] role={label}: upserted={up} skipped={sk}")

    if dry_run:
        print(f"[push:dry-run] 대상 {sum(len(v) for v in groups.values())}건, shared skip={n_shared}")
    else:
        print(f"[push] 완료 — upserted={total_up} skipped={total_skip} (shared 제외={n_shared})")
    return 0


# ─────────────────────────── pull ───────────────────────────

def cmd_pull(cfg, memory_dir, role_override):
    project_id = cfg.resolve_project_id()
    roles = [role_override] if role_override else MEMORY_ROLES

    os.makedirs(memory_dir, exist_ok=True)
    written = skipped = 0
    for role in roles:
        params = {"project_id": project_id, "role": role}
        out = cfg.get("/api/memory/pull", params=params)
        for item in out.get("items", []):
            name = item["name"]
            path = os.path.join(memory_dir, f"{name}.md")
            body = item.get("body") or ""
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    cur = fh.read()
                if content_hash(cur) == content_hash(body):
                    skipped += 1  # 무변경 — no-op(멱등)
                    continue
            with open(path, "w", encoding="utf-8") as fh:  # pull=서버 진실 실체화
                fh.write(body)
            written += 1

    regenerate_index(memory_dir)
    print(f"[pull] project_id={project_id} → {memory_dir}")
    print(f"[pull] 파일 written={written} skipped={skipped} · MEMORY.md 재생성 완료")
    return 0


def _split_index(index_path):
    """기존 MEMORY.md 를 (header, {filename: line}) 로 분해.

    header = 첫 `- [` 불릿 앞의 원문(제목·설명 보존). 라인맵은 파일명→그 불릿 원문
    (사람이 큐레이션한 Title·hook 을 그대로 보존 — frontmatter 로 기계 복원 불가).
    """
    if not os.path.exists(index_path):
        return "# 메모리 인덱스\n", {}
    with open(index_path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    header_lines = []
    line_map = {}
    first_bullet = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("- [") and "](" in ln and first_bullet is None:
            first_bullet = i
        if first_bullet is None:
            header_lines.append(ln)
        if ln.lstrip().startswith("- ") and "](" in ln:
            # 파일명 추출: ](<...>.md)
            l, _, rest = ln.partition("](")
            fn = rest.split(")", 1)[0].strip()
            fn = os.path.basename(fn)
            if fn.endswith(".md"):
                line_map[fn] = ln
    header = "\n".join(header_lines).rstrip("\n") + "\n"
    return header, line_map


def regenerate_index(memory_dir):
    """MEMORY.md 를 실제 파일 집합으로부터 재생성 — 인덱스=파일집합 일치(수용기준 7).

    기존 큐레이션 라인은 보존(그 파일이 아직 있으면), 사라진 파일 라인은 제거,
    새 파일은 frontmatter(name/description)로 기계 생성해 추가. 블롭 통째 sync 아님.
    """
    index_path = os.path.join(memory_dir, "MEMORY.md")
    header, line_map = _split_index(index_path)
    files = _list_memory_files(memory_dir)
    files_set = set(files)

    out = [header.rstrip("\n"), ""]
    seen = set()
    # 1) 기존 순서·큐레이션 보존(아직 존재하는 파일만)
    for fn, line in line_map.items():
        if fn in files_set and fn not in seen:
            out.append(line)
            seen.add(fn)
    # 2) 인덱스에 없던 새 파일 → 기계 생성 라인 추가
    for fn in files:
        if fn in seen:
            continue
        with open(os.path.join(memory_dir, fn), encoding="utf-8") as fh:
            fields, _ = parse_frontmatter(fh.read())
        title = fields.get("name") or fn[:-3]
        hook = (fields.get("description") or "").strip()
        line = f"- [{title}]({fn})" + (f" — {hook}" if hook else "")
        out.append(line)
        seen.add(fn)

    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")


# ─────────────────────────── selftest (오프라인) ───────────────────────────

def cmd_selftest():
    """서버 없이 frontmatter 파싱·scope 필터·slug 재실체화·인덱스 재생성 왕복 검증."""
    import tempfile

    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + label)
        ok = ok and cond

    # 1) frontmatter 파싱 + 3축
    sample = (
        "---\nname: sample-fact\ndescription: 한 줄 요약\n"
        "metadata:\n  node_type: memory\n  type: project\n"
        "  project: UNSKEIN_SAAS\n  role: planner\n  scope: private\n---\n\n본문 내용\n"
    )
    fields, body = parse_frontmatter(sample)
    check(fields.get("name") == "sample-fact", "frontmatter name 파싱")
    check(fields["metadata"].get("scope") == "private", "metadata.scope 파싱")
    check(fields["metadata"].get("role") == "planner", "metadata.role 파싱")
    check(body.strip() == "본문 내용", "body 분리")

    # 2) slug 재실체화(경로 이식성)
    check(slug_for("/home/alice/unskein") == "-home-alice-unskein", "slug 재실체화")
    check(slug_for("/home/mupai/unskein/") == "-home-mupai-unskein", "slug 말미 슬래시 정규화")

    # 3) content_hash 개행 정규화(무변경 no-op)
    check(content_hash("a\r\nb") == content_hash("a\nb"), "content_hash 개행 정규화")

    # 4) scope 필터 + pull 실체화 + 인덱스 재생성 (다른 slug 디렉토리로 왕복)
    src = tempfile.mkdtemp(prefix="memsync-src-")
    dst = tempfile.mkdtemp(prefix="memsync-dst-")  # 다른 slug 흉내
    priv = sample
    shared = sample.replace("scope: private", "scope: shared").replace("sample-fact", "shared-fact")
    with open(os.path.join(src, "sample-fact.md"), "w", encoding="utf-8") as fh:
        fh.write(priv)
    with open(os.path.join(src, "shared-fact.md"), "w", encoding="utf-8") as fh:
        fh.write(shared)
    # 기존 큐레이션 인덱스(보존돼야 함)
    with open(os.path.join(dst, "MEMORY.md"), "w", encoding="utf-8") as fh:
        fh.write("# 인덱스\n\n- [기존 큐레이션](existing.md) — 사람이 쓴 hook\n")
    with open(os.path.join(dst, "existing.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: existing\ndescription: x\nmetadata:\n  scope: private\n---\n기존\n")

    # push 시 scope 필터 흉내: private 만 서버로
    server = []
    for fn in _list_memory_files(src):
        with open(os.path.join(src, fn), encoding="utf-8") as fh:
            raw = fh.read()
        f2, _ = parse_frontmatter(raw)
        if (f2["metadata"].get("scope") or "private") == "private":
            server.append({"name": fn[:-3], "body": raw})
    check(len(server) == 1 and server[0]["name"] == "sample-fact", "scope=shared push 제외")

    # pull 실체화 → dst
    for it in server:
        with open(os.path.join(dst, it["name"] + ".md"), "w", encoding="utf-8") as fh:
            fh.write(it["body"])
    regenerate_index(dst)

    with open(os.path.join(dst, "MEMORY.md"), encoding="utf-8") as fh:
        idx = fh.read()
    dst_files = set(_list_memory_files(dst))
    check(os.path.exists(os.path.join(dst, "sample-fact.md")), "pull 파일 실체화")
    check("- [기존 큐레이션](existing.md) — 사람이 쓴 hook" in idx, "기존 큐레이션 라인 보존")
    check("(sample-fact.md)" in idx, "새 파일 인덱스 추가")
    check("shared-fact.md" not in idx, "shared 는 인덱스에도 없음")
    # 인덱스=파일집합 일치: 불릿 파일 집합 == 실제 파일 집합
    _, lm = _split_index(os.path.join(dst, "MEMORY.md"))
    check(set(lm.keys()) == dst_files, "인덱스 = 파일집합 일치(수용기준 7)")

    import shutil
    shutil.rmtree(src, ignore_errors=True)
    shutil.rmtree(dst, ignore_errors=True)

    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ─────────────────────────── main ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="UnSkein 사용자 메모리 push/pull 동기화")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("push", "pull"):
        sp = sub.add_parser(name)
        sp.add_argument("--codebase", default=None,
                        help="slug 계산 기준 디렉토리(기본: 현재 cwd). 메모리 경로 = "
                             "~/.claude/projects/<slug>/memory")
        sp.add_argument("--memory-dir", default=None, help="메모리 디렉토리 직접 지정(테스트용)")
        sp.add_argument("--role", default=None, choices=MEMORY_ROLES,
                        help="역할 축 고정(기본: frontmatter/토큰 kind)")
    sub.choices["push"].add_argument("--dry-run", action="store_true",
                                     help="POST 없이 보낼 목록만 출력")
    sub.add_parser("selftest")

    args = ap.parse_args()

    if args.cmd == "selftest":
        return cmd_selftest()

    memory_dir = args.memory_dir or memory_dir_for(args.codebase or os.getcwd())
    cfg = Config()
    if args.cmd == "push":
        return cmd_push(cfg, memory_dir, args.role, args.dry_run)
    if args.cmd == "pull":
        return cmd_pull(cfg, memory_dir, args.role)
    return 1


if __name__ == "__main__":
    sys.exit(main())
