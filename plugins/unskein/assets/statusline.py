#!/usr/bin/env python3
"""Claude Code 상태바 — 작업디렉토리 · 컨텍스트 사용률 · 모델명.

UnSkein 플러그인 동봉. unskein-setup 이 선택 설치 시 ~/.claude/statusline.py 로 복사한다.
플러그인은 statusLine 을 직접 실을 수 없어(설정상 미지원) 이 스크립트를 opt-in 으로 깐다.
"""
import sys, json, os, subprocess
from collections import deque


def read_input():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def working_dir(data):
    ws = data.get("workspace") or {}
    path = ws.get("current_dir") or data.get("cwd") or os.getcwd()
    base = os.path.basename(path.rstrip("/")) or path
    # git 연결(linked) 워크트리면 "워크트리"로 표시, 메인이면 폴더명
    try:
        def g(arg):
            r = subprocess.run(["git", "-C", path, "rev-parse", arg],
                               capture_output=True, text=True, timeout=1)
            return r.stdout.strip() if r.returncode == 0 else None
        gd, gcd = g("--git-dir"), g("--git-common-dir")
        if gd and gcd and os.path.abspath(os.path.join(path, gd)) != os.path.abspath(os.path.join(path, gcd)):
            return "워크트리"
    except Exception:
        pass
    return base


def context_window(model):
    mid = (model.get("id") or "").lower()
    disp = (model.get("display_name") or "").lower()
    # 1M-context 모델 (Anthropic 공식 모델 문서 2026-07-02 실측):
    # Fable 5 / Mythos / Opus 4.6~4.8 / Sonnet 5 / Sonnet 4.6. 그 외(Haiku·구 Sonnet/Opus)는 200K.
    norm = (mid + disp).replace("-", "").replace(".", "").replace(" ", "").replace("_", "")
    one_m = ("fable", "mythos", "opus48", "opus47", "opus46", "sonnet5", "sonnet46")
    if "[1m]" in mid or "1m context" in disp or any(k in norm for k in one_m):
        return 1_000_000
    return 200_000


def context_pct(data, model):
    tpath = data.get("transcript_path")
    if not tpath or not os.path.exists(tpath):
        return None
    used = None
    try:
        with open(tpath, "r", encoding="utf-8") as f:
            for line in deque(f, maxlen=600):  # 끝쪽 라인만 스캔
                line = line.strip()
                if not line or '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                msg = obj.get("message") or {}
                u = msg.get("usage") or obj.get("usage")
                if not isinstance(u, dict):
                    continue
                total = (
                    (u.get("input_tokens") or 0)
                    + (u.get("cache_creation_input_tokens") or 0)
                    + (u.get("cache_read_input_tokens") or 0)
                )
                if total > 0:
                    used = total  # 마지막(가장 최근) 값으로 갱신
    except Exception:
        return None
    if used is None:
        return None
    return round(used / context_window(model) * 100)


def model_name(model):
    disp = model.get("display_name") or "Claude"
    mid = (model.get("id") or "").lower()
    if ("[1m]" in mid or "1m" in mid) and "1m" not in disp.lower():
        disp += " (1M context)"
    return disp


def main():
    data = read_input()
    model = data.get("model") or {}
    wd = working_dir(data)
    pct = context_pct(data, model)
    ctx = f"{pct}%" if pct is not None else "—"
    print(f"DIR:{wd} CTX:{ctx} {model_name(model)}")


if __name__ == "__main__":
    main()
