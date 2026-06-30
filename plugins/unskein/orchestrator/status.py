#!/usr/bin/env python3
"""상태 점검 — 클라이언트 연결·등록 상태를 읽기 전용으로 본다.

점검 항목:
  - UNSKEIN_API (미설정 시 기본값 표기)
  - UNSKEIN_MORI_TOKEN 설정 여부 (값은 절대 출력하지 않음 — 설정됨/없음만)
  - UNSKEIN_WATCH_BUSINESS/PROJECT — watch 대상(미설정 시 전체)
  - UNSKEIN_CRED_DIR 존재 + 어떤 자격증명이 있는지 (.env / id_ed25519 — 값·내용 미출력)
  - UNSKEIN_WORK_ROOT 존재 + 클론된 폴더 목록
  - gh CLI 존재 + 인증 (gh auth status — 다오 마감 PR 생성용, 토큰 값 미출력)
  - 서버 도달 (GET $UNSKEIN_API/api/health → status)
  - watch 대상 검증 + 가용 비즈니스/프로젝트 (GET $UNSKEIN_API/api/mori/scope, 토큰 필요)

읽기 전용 — POST /api/mori/claim 등 작업을 선점·변경하는 호출은 절대 하지 않는다.
GET /api/health(도달) 와 GET /api/mori/scope(대상 확인) 만 사용한다.

stdlib 만 사용 (requests 미설치 환경).
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

DEFAULT_API = "https://unskein.mupai.studio"
API_BASE = os.getenv("UNSKEIN_API", DEFAULT_API)
CRED_DIR = os.getenv(
    "UNSKEIN_CRED_DIR", os.path.expanduser(os.path.join("~", ".unskein", "creds"))
)
WORK_ROOT = os.getenv(
    "UNSKEIN_WORK_ROOT", os.path.expanduser(os.path.join("~", ".unskein", "work"))
)
WATCH_BUSINESS = os.getenv("UNSKEIN_WATCH_BUSINESS") or None
WATCH_PROJECT = os.getenv("UNSKEIN_WATCH_PROJECT") or None


def _check_api() -> str:
    if os.getenv("UNSKEIN_API"):
        return f"[OK] UNSKEIN_API: {API_BASE}"
    return f"[기본값] UNSKEIN_API: {API_BASE} (미설정 — 기본값 사용)"


def _check_token() -> str:
    # 값은 절대 출력하지 않는다 — 설정됨/없음만.
    if os.getenv("UNSKEIN_MORI_TOKEN"):
        return "[OK] UNSKEIN_MORI_TOKEN: 설정됨"
    return "[없음] UNSKEIN_MORI_TOKEN: 없음 (unskein-connect 로 설정하세요)"


def _check_watch() -> str:
    if not WATCH_BUSINESS and not WATCH_PROJECT:
        return "[전체] watch 대상: 미지정 (모든 비즈니스/프로젝트)"
    biz = WATCH_BUSINESS or "(전체 비즈니스)"
    label = f"{biz} / {WATCH_PROJECT}" if WATCH_PROJECT else biz
    return f"[OK] watch 대상: {label}"


def _check_scope() -> str:
    # 읽기 전용 — GET /api/mori/scope. 가용 비즈니스/프로젝트 표시 + watch 대상 검증.
    if not os.getenv("UNSKEIN_MORI_TOKEN"):
        return "[건너뜀] watch 대상 검증: 토큰 없음 (unskein-connect 먼저)"
    url = f"{API_BASE}/api/mori/scope"
    req = urllib.request.Request(
        url, method="GET", headers={"X-Mori-Token": os.environ["UNSKEIN_MORI_TOKEN"]}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return f"[실패] watch 대상 조회: {url} → HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — 사유를 그대로 보여준다
        return f"[실패] watch 대상 조회: {url} → {exc}"

    businesses = payload.get("businesses", []) or []
    if not businesses:
        return "[경고] 가용 대상 없음 — 이 토큰이 속한 활성 비즈니스가 없습니다"
    lines = ["[OK] 가용 watch 대상:"]
    for b in businesses:
        bname = b.get("name", "")
        projs = ", ".join(p.get("name", "") for p in (b.get("projects") or [])) or "(프로젝트 없음)"
        lines.append(f"      - {bname}: {projs}")

    # 지정한 대상이 가용 목록에 있는지 검증.
    if WATCH_BUSINESS or WATCH_PROJECT:
        target = businesses
        if WATCH_BUSINESS:
            target = [b for b in businesses if b.get("name") == WATCH_BUSINESS]
            if not target:
                lines.append(f"      [실패] 지정한 비즈니스 '{WATCH_BUSINESS}' 가 위 목록에 없습니다")
                return "\n".join(lines)
        if WATCH_PROJECT:
            names = [p.get("name") for b in target for p in (b.get("projects") or [])]
            if WATCH_PROJECT not in names:
                lines.append(f"      [실패] 지정한 프로젝트 '{WATCH_PROJECT}' 가 위 목록에 없습니다")
                return "\n".join(lines)
        lines.append("      [OK] 지정한 watch 대상이 가용 목록과 일치합니다")
    return "\n".join(lines)


def _check_creds() -> str:
    if not os.path.isdir(CRED_DIR):
        return f"[없음] UNSKEIN_CRED_DIR: {CRED_DIR} (폴더 없음)"
    found = []
    # 값·내용은 출력하지 않고 존재 여부만 본다.
    if os.path.isfile(os.path.join(CRED_DIR, ".env")):
        found.append(".env 있음")
    if os.path.isfile(os.path.join(CRED_DIR, "id_ed25519")):
        found.append("id_ed25519 있음")
    if os.path.isfile(os.path.join(CRED_DIR, "id_rsa")):
        found.append("id_rsa 있음")
    detail = ", ".join(found) if found else "자격증명 없음"
    return f"[OK] UNSKEIN_CRED_DIR: {CRED_DIR} ({detail})"


def _check_work_root() -> str:
    if not os.path.isdir(WORK_ROOT):
        return f"[없음] UNSKEIN_WORK_ROOT: {WORK_ROOT} (폴더 없음)"
    try:
        entries = sorted(
            name
            for name in os.listdir(WORK_ROOT)
            if os.path.isdir(os.path.join(WORK_ROOT, name))
        )
    except OSError as exc:
        return f"[경고] UNSKEIN_WORK_ROOT: {WORK_ROOT} (목록 조회 실패: {exc})"
    if entries:
        return f"[OK] UNSKEIN_WORK_ROOT: {WORK_ROOT} (클론된 폴더: {', '.join(entries)})"
    return f"[OK] UNSKEIN_WORK_ROOT: {WORK_ROOT} (클론된 폴더 없음)"


def _check_gh() -> str:
    # gh CLI 존재 + 인증 — 다오가 마감(unskein-git)에서 PR 을 `gh pr create` 로만 만든다.
    # 모리 preflight 가 잡기 전에 치명 항목으로 점검하는 것과 같은 신호. 토큰 값은 출력하지 않는다.
    if not shutil.which("gh"):
        return "[없음] gh CLI: 미설치 (unskein-connect §1 로 설치 + `gh auth login`)"
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001 — 타임아웃·네트워크 등은 응답 없음(토큰 문제와 구분)
        return f"[실패] gh 인증: 응답 없음 (네트워크·일시 장애일 수 있음: {exc})"
    if r.returncode == 0:
        return "[OK] gh CLI: 인증됨 (PR 생성 가능)"
    return "[없음] gh 인증: 미인증/토큰 무효 (`gh auth login`(mupaistudio) + `gh auth setup-git`)"


def _check_health() -> str:
    # 읽기 전용 도달 확인 — GET /api/health 만. 작업 선점(POST /claim) 금지.
    url = f"{API_BASE}/api/health"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
            status = payload.get("status", "(status 필드 없음)")
        except json.JSONDecodeError:
            status = "(JSON 아님)"
        return f"[OK] 서버 도달: {url} → status={status}"
    except urllib.error.HTTPError as exc:
        return f"[실패] 서버 도달: {url} → HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — 네트워크/주소 사유를 그대로 보여준다
        return f"[실패] 서버 도달: {url} → {exc}"


def main() -> int:
    print("UnSkein 클라이언트 상태 (읽기 전용)")
    print("=" * 40)
    print(_check_api())
    print(_check_token())
    print(_check_watch())
    print(_check_creds())
    print(_check_work_root())
    print(_check_gh())
    print(_check_health())
    print(_check_scope())
    print("=" * 40)
    print("토큰 유효성은 첫 /unskein:run 에서 확정됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
