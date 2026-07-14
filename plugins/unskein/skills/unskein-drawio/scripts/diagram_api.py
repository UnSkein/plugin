#!/usr/bin/env python3
"""UnSkein 프로젝트 다이어그램(draw.io) API CLI — unskein-drawio 스킬의 헤드리스 헬퍼.

다이어그램은 프로젝트의 문서다(주인=프로젝트, `diagram.project_id`). 플래너가 자기 신분
(planner 토큰)으로 자기 프로젝트 문서를 조회·생성·수정·삭제한다. 이 스크립트는 그 왕복
(인증·`/api` 접미사 보정·XML well-formed 검증·제목 `(id)` 마감)을 한 곳에 모아, 스킬이
매번 curl/python 을 손으로 다시 쓰지 않게 한다(반복 재작성·미묘한 실수 제거).

인증 (env — planner.env; 스킬이 먼저 `. ${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh` 로 로드):
  UNSKEIN_API 또는 UNSKEIN_API_BASE   필수 — 서버 베이스 URL(끝에 /api 없어도 자동 보정)
  UNSKEIN_PLANNER_TOKEN               필수 — X-Planner-Token (kind=planner)
    ※ 다이어그램 라우트 인가는 get_current_user_flex — JWT(Bearer) 또는 planner 토큰만
      받는다. mori/tester 토큰은 401 이라 여기 쓰지 않는다. 토큰 없으면 멈춘다(fallback 금지).

사용:
  # 발견(읽기 전용) — project_id 를 모를 때 이름→id 해석
  diagram_api.py businesses                         비즈니스 id·이름
  diagram_api.py projects --business <id|이름>        프로젝트 id·이름·repo_url

  # 다이어그램 CRUD
  diagram_api.py list   --project <id>              활성 다이어그램 (id·kind·title)
  diagram_api.py get    <diagram_id> [--xml-only]   1건 전체(수정 전 백업용). --xml-only=drawio_xml 만
  diagram_api.py create --project <id> --title T --xml FILE [--kind flow] [--preview FILE]
                                                    POST → 제목 끝에 (id) 자동 마감(2단계)
  diagram_api.py update <diagram_id> [--xml FILE] [--title T] [--kind K] [--preview FILE]
                                                    보낸 필드만 PATCH (preview 미지정 = 옛 썸네일 유지)
  diagram_api.py delete <diagram_id> --yes          소프트 삭제(is_active=false)
  diagram_api.py selftest                           오프라인 자체검증(서버 불요)

규약(서버 계약과 lockstep):
  - kind ∈ erd|flow|api|process|etc — 구조도·토폴로지·흐름은 보통 flow. 위반 시 서버 400.
  - drawio_xml ≤ 5MB(초과 413) + well-formed 아니면 **보내기 전에** 멈춘다(깨진 XML 저장 방지).
  - preview_svg 는 data:image/svg+xml… 데이터 URL 만(위반 400). 헤드리스로 억지 SVG 생성 금지
    — update 에서 --preview 를 빼면 옛 썸네일 유지(사람이 편집기에서 저장하면 갱신). 스킬 §5.
  - 제목 (id) 규약: 생성 응답 id 를 제목 끝 ` (id)` 로 단다. 이미 `(숫자)` 로 끝나면 재부착
    안 함(멱등, 정규식 `\\s*\\(\\d+\\)\\s*$`). 이후엔 목록 제목만 보고 다이어그램을 특정한다.

종료코드: 0=성공, 1=오류(설정 누락·인증 실패·규약 위반·HTTP 에러 — 조용히 넘기지 않는다).
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from xml.dom.minidom import parseString as _parse_xml

TITLE_ID_RE = re.compile(r"\s*\(\d+\)\s*$")  # 제목 끝 " (숫자)" — (id) 마감 멱등 판정
KINDS = ["erd", "flow", "api", "process", "etc"]
MAX_XML_BYTES = 5 * 1024 * 1024


def _die(msg):
    print(f"[diagram_api] 오류: {msg}", file=sys.stderr)
    sys.exit(1)


def _base():
    """서버 베이스 + /api 보정. UNSKEIN_API 가 /api 로 안 끝나면 붙인다(이 프로젝트 관례)."""
    raw = os.environ.get("UNSKEIN_API") or os.environ.get("UNSKEIN_API_BASE")
    if not raw:
        _die("UNSKEIN_API(_BASE) 없음 — planner.env 로드 후 재시도 "
             "(. ${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh)")
    raw = raw.rstrip("/")
    return raw if raw.endswith("/api") else raw + "/api"


def _token():
    tok = os.environ.get("UNSKEIN_PLANNER_TOKEN")
    if not tok:
        _die("UNSKEIN_PLANNER_TOKEN 없음 — 다이어그램은 planner 토큰(또는 사람 JWT)만 인가된다. "
             "planner.env 로드 확인(fallback 금지).")
    return tok


def _req(method, path, body=None):
    """API 왕복. X-Planner-Token 첨부, JSON 파싱. HTTP 에러는 코드+detail 로 드러내고 멈춘다."""
    url = _base() + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-Planner-Token": _token()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        _die(f"HTTP {e.code} — {method} {path}\n  {detail}")
    except urllib.error.URLError as e:
        _die(f"연결 실패 — {method} {path}: {e}")


def _read_xml(path):
    """drawio_xml 파일을 읽어 well-formed·크기 검증 후 문자열로 반환."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        _die(f"XML 파일을 못 읽음: {path} ({e})")
    if len(content.encode("utf-8")) > MAX_XML_BYTES:
        _die("drawio_xml 이 5MB 를 초과한다(서버 413).")
    try:
        _parse_xml(content)
    except Exception as e:
        _die(f"drawio_xml 이 well-formed 가 아니다 — 보내기 전 중단: {e}")
    return content


def _read_preview(path):
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    if not svg.startswith("data:image/svg+xml"):
        _die("preview 는 data:image/svg+xml… 데이터 URL 이어야 한다(서버 400).")
    return svg


def _finalize_title(title, diagram_id):
    """제목 끝 (id) 마감값. 이미 (숫자)로 끝나면 None(변경 불필요 = 멱등)."""
    if TITLE_ID_RE.search(title):
        return None
    return f"{title} ({diagram_id})"


def _resolve_business(ident):
    """비즈니스 식별자(id 숫자 또는 이름) → id."""
    if str(ident).isdigit():
        return int(ident)
    for b in _req("GET", "/businesses") or []:
        if b.get("name") == ident:
            return b["id"]
    _die(f"비즈니스 이름을 못 찾음: {ident} (businesses 로 목록 확인)")


# ── 명령 ────────────────────────────────────────────────────────────────

def cmd_businesses(a):
    for b in _req("GET", "/businesses") or []:
        print(b["id"], b.get("name"))


def cmd_projects(a):
    bid = _resolve_business(a.business)
    for p in _req("GET", f"/businesses/{bid}/projects") or []:
        print(p["id"], p.get("name"), p.get("repo_url") or "")


def cmd_list(a):
    for d in _req("GET", f"/projects/{a.project}/diagrams") or []:
        print(d["id"], d["kind"], repr(d["title"]))


def cmd_get(a):
    d = _req("GET", f"/diagrams/{a.diagram_id}")
    if a.xml_only:
        sys.stdout.write(d.get("drawio_xml") or "")
    else:
        print(json.dumps(d, ensure_ascii=False, indent=1))


def cmd_create(a):
    if a.kind not in KINDS:
        _die(f"kind 는 {'|'.join(KINDS)} 중 하나여야 한다: {a.kind}")
    body = {"title": a.title, "kind": a.kind, "drawio_xml": _read_xml(a.xml)}
    if a.preview:
        body["preview_svg"] = _read_preview(a.preview)
    d = _req("POST", f"/projects/{a.project}/diagrams", body)
    did = d["id"]
    new_title = _finalize_title(d["title"], did)
    if new_title:  # 제목 끝 (id) 2단계 마감 — 멱등이면 건너뜀
        d = _req("PATCH", f"/diagrams/{did}", {"title": new_title})
    print(f"생성됨: id={d['id']} kind={d['kind']} title={d['title']!r} "
          f"xml={len(d.get('drawio_xml') or '')}자")


def cmd_update(a):
    patch = {}
    if a.xml:
        patch["drawio_xml"] = _read_xml(a.xml)
    if a.title is not None:
        patch["title"] = a.title
    if a.kind is not None:
        if a.kind not in KINDS:
            _die(f"kind 는 {'|'.join(KINDS)} 중 하나여야 한다: {a.kind}")
        patch["kind"] = a.kind
    if a.preview:
        patch["preview_svg"] = _read_preview(a.preview)
    if not patch:
        _die("바꿀 필드가 없다 — --xml/--title/--kind/--preview 중 하나는 줘야 한다.")
    d = _req("PATCH", f"/diagrams/{a.diagram_id}", patch)
    print(f"갱신됨: id={d['id']} kind={d['kind']} title={d['title']!r} "
          f"xml={len(d.get('drawio_xml') or '')}자 (바꾼 필드: {', '.join(patch)})")


def cmd_delete(a):
    if not a.yes:
        _die("소프트 삭제는 되돌리기 가능하나 사람 확인이 필요하다 — 확실하면 --yes.")
    _req("DELETE", f"/diagrams/{a.diagram_id}")
    print(f"삭제됨(is_active=false): id={a.diagram_id}")


def cmd_selftest(a):
    """오프라인 자체검증 — 순수 로직(제목 마감·베이스 보정·XML 검증)만, 서버 불요."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'}  {name}")
        ok = ok and cond

    # 제목 (id) 마감 멱등
    check("finalize: 없으면 붙인다", _finalize_title("구조도", 9) == "구조도 (9)")
    check("finalize: 이미 (id)면 None", _finalize_title("구조도 (9)", 9) is None)
    check("finalize: 뒤 공백도 멱등", _finalize_title("구조도 (12) ", 9) is None)
    check("finalize: 중간 (숫자)는 무시", _finalize_title("v(2) 구조도", 9) == "v(2) 구조도 (9)")

    # 베이스 /api 보정
    saved = os.environ.get("UNSKEIN_API")
    os.environ["UNSKEIN_API"] = "https://x.test"
    check("base: /api 없으면 붙인다", _base() == "https://x.test/api")
    os.environ["UNSKEIN_API"] = "https://x.test/api/"
    check("base: 이미 /api면 유지", _base() == "https://x.test/api")
    if saved is not None:
        os.environ["UNSKEIN_API"] = saved
    else:
        os.environ.pop("UNSKEIN_API", None)

    print("selftest:", "통과" if ok else "실패")
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(description="UnSkein 프로젝트 다이어그램 API CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("businesses").set_defaults(fn=cmd_businesses)

    sp = sub.add_parser("projects"); sp.add_argument("--business", required=True)
    sp.set_defaults(fn=cmd_projects)

    sp = sub.add_parser("list"); sp.add_argument("--project", required=True, type=int)
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("get"); sp.add_argument("diagram_id", type=int)
    sp.add_argument("--xml-only", action="store_true", dest="xml_only")
    sp.set_defaults(fn=cmd_get)

    sp = sub.add_parser("create")
    sp.add_argument("--project", required=True, type=int)
    sp.add_argument("--title", required=True)
    sp.add_argument("--xml", required=True)
    sp.add_argument("--kind", default="flow")
    sp.add_argument("--preview")
    sp.set_defaults(fn=cmd_create)

    sp = sub.add_parser("update"); sp.add_argument("diagram_id", type=int)
    sp.add_argument("--xml"); sp.add_argument("--title")
    sp.add_argument("--kind"); sp.add_argument("--preview")
    sp.set_defaults(fn=cmd_update)

    sp = sub.add_parser("delete"); sp.add_argument("diagram_id", type=int)
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(fn=cmd_delete)

    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
