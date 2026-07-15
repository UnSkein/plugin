#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""단계 스킬 린트 — 관문 ①(생산) 기계 검사 + 매니페스트 추출. stdlib 전용.

사용:
    python3 skill_lint.py <스킬 repo 루트 | 스킬 디렉토리> [--manifest <출력.json>]

검사 규칙의 단일 출처는 ../SKILL.md §4 다(번호 일치). 전부 통과 = exit 0,
위반 1건 이상 = exit 1 (위반 목록 출력, 매니페스트 미생성 — 보장분만 등록한다).
"""
import argparse
import json
import re
import sys
from pathlib import Path

# §4-3 dev 예약 이름 — 디폴트 스킬(dev 프로세스)과의 충돌·선택 혼란 차단
RESERVED_NAMES = {
    "unskein-exec",
    "unskein-verify",
    "unskein-git",
    "unskein-wiki-search",
    "unskein-wiki-ingest",
    "unskein-wiki-lint",
}
EXITS = {"forward", "verdict", "terminal"}
OUTPUTS = {"none", "doc", "payload"}
REQUIRED_KEYS = ("name", "description", "version", "exits", "output")
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
RESULT_STATUS_RE = re.compile(r"RESULT:.*?\bstatus=(\S+)")


def parse_frontmatter(text):
    """SKILL.md 선두의 '---' 쌍 사이를 key: value 로 파싱. 실패 시 None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return None  # 닫는 '---' 없음


def lint_skill(skill_md: Path, root: Path, errors, warnings):
    """SKILL.md 한 건 검사. 통과분의 매니페스트 메타를 반환(위반 시 None)."""
    rel = skill_md.relative_to(root)
    before = len(errors)

    try:  # §4-11 UTF-8
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        errors.append(f"{rel}: UTF-8 로 읽을 수 없다 (§4-11)")
        return None

    meta = parse_frontmatter(text)
    if meta is None:
        errors.append(f"{rel}: frontmatter('---' 쌍)가 없다 (§4-1)")
        return None

    missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
    if missing:
        errors.append(f"{rel}: frontmatter 필수 키 누락 — {', '.join(missing)} (§4-1)")

    name = meta.get("name", "")
    if name:
        if not SLUG_RE.match(name):
            errors.append(f"{rel}: name '{name}' 은 소문자 slug 가 아니다 (§4-2)")
        if name != skill_md.parent.name:
            errors.append(
                f"{rel}: name '{name}' 이 디렉토리명 '{skill_md.parent.name}' 과 다르다 (§4-2)"
            )
        if name in RESERVED_NAMES:
            errors.append(f"{rel}: '{name}' 은 dev 예약 이름이다 — 사용 불가 (§4-3)")

    version = meta.get("version", "")
    if version and not VERSION_RE.match(version):
        errors.append(f"{rel}: version '{version}' 은 X.Y.Z 형식이 아니다 (§4-5)")

    exits = meta.get("exits", "")
    if exits and exits not in EXITS:
        errors.append(f"{rel}: exits '{exits}' 은 {sorted(EXITS)} 중 하나가 아니다 (§4-6)")
    output = meta.get("output", "")
    if output and output not in OUTPUTS:
        errors.append(f"{rel}: output '{output}' 은 {sorted(OUTPUTS)} 중 하나가 아니다 (§4-6)")

    if "RESULT:" not in text or "QUESTION:" not in text:
        errors.append(f"{rel}: 출력 마커 규약(RESULT:·QUESTION:)이 본문에 없다 (§4-7)")

    for status in RESULT_STATUS_RE.findall(text):  # §4-8 구체 status 키 하드코딩
        if not status.startswith("<"):
            errors.append(
                f"{rel}: RESULT 예시의 status='{status}' — 구체 status 키를 박지 않는다,"
                f" '<…>' 플레이스홀더만 허용 (§4-8)"
            )

    if output == "doc" and "<<<UNSKEIN_DOC" not in text:
        errors.append(f"{rel}: output=doc 인데 <<<UNSKEIN_DOC 블록 규약이 본문에 없다 (§4-9)")

    if (skill_md.parent / "CLAUDE.md").exists():  # §4-10 예약 파일
        errors.append(f"{rel.parent}: 스킬 디렉토리에 CLAUDE.md 동봉 불가 — 예약 파일 (§4-10)")

    if len(errors) > before:
        return None
    return {"name": name, "version": version, "exits": exits, "output": output,
            "path": str(rel)}


def main():
    parser = argparse.ArgumentParser(description="단계 스킬 린트 (관문 ① 생산)")
    parser.add_argument("root", help="스킬 repo 루트 또는 스킬 디렉토리")
    parser.add_argument("--manifest", help="통과 시 매니페스트 JSON 을 쓸 경로")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"오류: 디렉토리가 아니다 — {root}")
        return 1

    skill_mds = sorted(
        p for p in root.rglob("SKILL.md") if ".git" not in p.parts
    )
    if not skill_mds:
        print(f"오류: {root} 아래에 SKILL.md 가 없다")
        return 1

    errors, warnings, manifest = [], [], []
    for skill_md in skill_mds:
        entry = lint_skill(skill_md, root, errors, warnings)
        if entry:
            manifest.append(entry)

    seen = {}  # §4-4 name 중복(선택 결정성) — 통과분 기준
    for entry in manifest:
        if entry["name"] in seen:
            errors.append(
                f"name '{entry['name']}' 중복 — {seen[entry['name']]} / {entry['path']} (§4-4)"
            )
        seen[entry["name"]] = entry["path"]

    for claude_md in sorted(root.rglob("CLAUDE.md")):  # §4-10 후단 — 그 외 위치는 경고
        if ".git" in claude_md.parts:
            continue
        if not (claude_md.parent / "SKILL.md").exists():
            warnings.append(
                f"{claude_md.relative_to(root)}: CLAUDE.md 발견 — 배포 자산에 섞이지 않는지 확인 (§4-10)"
            )

    for warning in warnings:
        print(f"경고: {warning}")
    if errors:
        for error in errors:
            print(f"위반: {error}")
        print(f"\n결과: 스킬 {len(skill_mds)}건 중 위반 {len(errors)}건 — 실패")
        return 1

    print(f"결과: 스킬 {len(skill_mds)}건 전부 통과")
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.write_text(
            json.dumps(sorted(manifest, key=lambda e: e["name"]),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"매니페스트: {manifest_path} ({len(manifest)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
