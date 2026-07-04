#!/usr/bin/env python3
"""상태 점검 — 클라이언트 연결·등록 상태를 읽기 전용으로 본다.

준비 점검(다오 CLI·git·gh 인증·dao-skills·creds·work·서버 도달·플러그인 최신)은 모리
run_once.preflight() 를 그대로 구동해 보여준다 — 작업을 잡기 전 게이트와 같은 단일 출처라
점검이 어긋나지 않는다(예전엔 status.py 가 따로 재구현해 drift 가 났다 — gh 누락 사례).
여기서는 preflight 가 다루지 않는 설정 항목만 더한다:
  - UNSKEIN_API (미설정 시 기본값 표기)
  - UNSKEIN_MORI_TOKEN 설정 여부 (값은 절대 출력하지 않음 — 설정됨/없음만)
  - UNSKEIN_WATCH_BUSINESS/PROJECT — watch 대상(미설정 시 전체)
  - watch 대상 검증 + 가용 비즈니스/프로젝트 (GET $UNSKEIN_API/api/mori/scope, 토큰 필요)

작업을 선점·변경하는 호출(POST /api/mori/claim 등)은 하지 않는다. 다만 preflight 를 구동하므로
순수 read-only 는 아니다 — WORK_ROOT 자동 생성(mkdir exist_ok), 플러그인 git fetch(원격 추적
ref 갱신), gh auth status·/api/health 점검(네트워크·gh 로 ~20s 걸릴 수 있음)이 따른다. 파괴적
변경이나 작업 큐 변경은 없다.

stdlib + 같은 폴더의 run_once(모리) 만 사용한다.
"""

import json
import os
import sys
import urllib.error
import urllib.request

import run_once  # 같은 폴더의 모리 — preflight() 를 그대로 구동(준비 점검 단일 출처).

# Windows 등 비 UTF-8 콘솔(cp949 등)에서도 한글·기호 출력이 깨지지 않게 stdout/stderr 를 UTF-8 로 맞춘다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

DEFAULT_API = "https://unskein.mupai.studio"
API_BASE = os.getenv("UNSKEIN_API", DEFAULT_API)
# creds·work 점검은 preflight() 가 단일 출처로 다룬다(여기서 중복 정의하지 않는다).
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
    return "[없음] UNSKEIN_MORI_TOKEN: 없음 (unskein-setup 로 설정하세요)"


def _check_watch() -> str:
    if not WATCH_BUSINESS and not WATCH_PROJECT:
        return "[전체] watch 대상: 미지정 (모든 비즈니스/프로젝트)"
    biz = WATCH_BUSINESS or "(전체 비즈니스)"
    label = f"{biz} / {WATCH_PROJECT}" if WATCH_PROJECT else biz
    return f"[OK] watch 대상: {label}"


def _check_scope() -> str:
    # 읽기 전용 — GET /api/mori/scope. 가용 비즈니스/프로젝트 표시 + watch 대상 검증.
    if not os.getenv("UNSKEIN_MORI_TOKEN"):
        return "[건너뜀] watch 대상 검증: 토큰 없음 (unskein-setup 먼저)"
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


def main() -> int:
    print("UnSkein 클라이언트 상태 (작업 선점·변경 없음 — preflight 점검에 gh·네트워크로 ~20s 걸릴 수 있음)")
    print("=" * 40)
    print(_check_api())
    print(_check_token())
    print(_check_watch())
    # 준비 점검은 모리 preflight() 를 그대로 구동한다 — 게이트와 같은 단일 출처(claude·git·
    # gh·dao-skills·creds·work·서버 도달·플러그인 최신). 점검이 추가돼도 자동 반영된다.
    try:
        _ok, lines = run_once.preflight()
        print("준비 점검(preflight — 작업 잡기 전 게이트와 동일):")
        for ln in lines:
            print(ln)
    except Exception as exc:  # noqa: BLE001 — 진단 도구라 preflight 구동 실패도 그대로 보여준다
        print(f"[실패] preflight 구동 실패: {exc}")
    print(_check_scope())
    print("=" * 40)
    print("토큰 유효성은 첫 /unskein:run 에서 확정됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
