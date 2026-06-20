#!/usr/bin/env python3
"""상태 점검 — 클라이언트 연결·등록 상태를 읽기 전용으로 본다.

점검 항목:
  - UNSKEIN_API (미설정 시 기본값 표기)
  - UNSKEIN_MORI_TOKEN 설정 여부 (값은 절대 출력하지 않음 — 설정됨/없음만)
  - UNSKEIN_CRED_DIR 존재 + 어떤 자격증명이 있는지 (.env / id_ed25519 — 값·내용 미출력)
  - UNSKEIN_WORK_ROOT 존재 + 클론된 폴더 목록
  - 서버 도달 (GET $UNSKEIN_API/api/health → status)

읽기 전용 — POST /api/mori/claim 등 작업을 선점·변경하는 호출은 절대 하지 않는다.
도달 확인은 GET /api/health 만 사용한다.

stdlib 만 사용 (requests 미설치 환경).
"""

import json
import os
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


def _check_api() -> str:
    if os.getenv("UNSKEIN_API"):
        return f"[OK] UNSKEIN_API: {API_BASE}"
    return f"[기본값] UNSKEIN_API: {API_BASE} (미설정 — 기본값 사용)"


def _check_token() -> str:
    # 값은 절대 출력하지 않는다 — 설정됨/없음만.
    if os.getenv("UNSKEIN_MORI_TOKEN"):
        return "[OK] UNSKEIN_MORI_TOKEN: 설정됨"
    return "[없음] UNSKEIN_MORI_TOKEN: 없음 (unskein-connect 로 설정하세요)"


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
    print(_check_creds())
    print(_check_work_root())
    print(_check_health())
    print("=" * 40)
    print("토큰 유효성은 첫 /unskein:run 에서 확정됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
