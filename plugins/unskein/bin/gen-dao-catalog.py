#!/usr/bin/env python3
"""다오wsl 스킬 카탈로그 생성기.

단일 출처(dao-skills)에서 카탈로그(DAO-SKILLS.md)를 만든다. 스킬이 추가·변경되면
이 스크립트를 다시 돌려 카탈로그를 동기화한다 — 손으로 카탈로그를 고치지 않는다.

입력:
  dao-skills/CLAUDE.md                         (단계 순서)
  dao-skills/.claude/skills/*/SKILL.md         (각 스킬의 name·description·트리거)

출력:
  DAO-SKILLS.md  (plugin 루트)

사용:
  python3 bin/gen-dao-catalog.py            # 생성/갱신
  python3 bin/gen-dao-catalog.py --check    # 어긋나면 비0 종료 (CI/점검용)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DAO_SKILLS = PLUGIN_ROOT / "dao-skills"
SKILLS_DIR = DAO_SKILLS / ".claude" / "skills"
CLAUDE_MD = DAO_SKILLS / "CLAUDE.md"
OUT = PLUGIN_ROOT / "DAO-SKILLS.md"


def read_frontmatter(path: Path) -> dict[str, str]:
    """SKILL.md 앞머리(--- ... ---)에서 name·description을 읽는다."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        raise SystemExit(f"앞머리(frontmatter)를 찾지 못함: {path}")
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    for required in ("name", "description"):
        if required not in fields:
            raise SystemExit(f"{required} 누락: {path}")
    return fields


def split_desc(description: str) -> tuple[str, str]:
    """description을 용도와 트리거로 가른다.

    규약: 'description. 트리거 — a, b, c.' 형식.
    """
    parts = re.split(r"\s*트리거\s*[—-]\s*", description, maxsplit=1)
    purpose = parts[0].strip()
    trigger = parts[1].strip() if len(parts) > 1 else ""
    return purpose, trigger


def read_step_order() -> list[str]:
    """dao-skills/CLAUDE.md '단계 순서'에서 스킬명을 순서대로 뽑는다."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # "1. **unskein-xxx** — ..." 형태 줄에서 스킬명 추출
    names = re.findall(r"^\s*\d+\.\s+\*\*(unskein-[a-z-]+)\*\*", text, re.M)
    if not names:
        raise SystemExit(f"단계 순서를 찾지 못함: {CLAUDE_MD}")
    return names


def build() -> str:
    order = read_step_order()
    found = {p.parent.name: read_frontmatter(p) for p in SKILLS_DIR.glob("*/SKILL.md")}

    # 단계 순서에 있는데 실제 스킬이 없으면 드러낸다 (fallback 금지).
    missing = [n for n in order if n not in found]
    if missing:
        raise SystemExit(f"단계 순서에 있으나 SKILL.md 없음: {missing}")
    # 스킬은 있는데 순서에 없는 것도 드러낸다.
    extra = [n for n in found if n not in order]
    if extra:
        raise SystemExit(f"SKILL.md는 있으나 단계 순서에 없음: {extra}")

    lines: list[str] = []
    lines.append("# 다오wsl 스킬 카탈로그")
    lines.append("")
    lines.append(
        "> 모리가 띄운 작업 다오(다오wsl)에 어떤 스킬이 있고 언제 쓰는지의 참조 정보. "
        "모리 클라이언트가 작업을 의뢰할 때 정확한 스킬을 가리키기 위한 목록이다."
    )
    lines.append(">")
    lines.append(
        "> **자동 생성 — 직접 고치지 않는다.** 단일 출처는 "
        "`dao-skills/.claude/skills/*/SKILL.md`(스킬별 앞머리)와 "
        "`dao-skills/CLAUDE.md`(단계 순서). 스킬을 추가·변경하면 "
        "`python3 bin/gen-dao-catalog.py`로 이 파일을 다시 만든다."
    )
    lines.append("")
    lines.append("## 단계 순서 (1 -> %d)" % len(order))
    lines.append("")
    lines.append(
        "다오wsl은 작업 하나를 받으면 사람 개입 없이 아래 순서를 스스로 끝까지 밟는다. "
        "각 단계는 같은 이름의 스킬을 호출한다."
    )
    lines.append("")
    for i, name in enumerate(order, 1):
        purpose, _ = split_desc(found[name]["description"])
        lines.append(f"{i}. **{name}** — {purpose}")
    lines.append("")
    lines.append(
        "마지막에 결과를 한 줄로 회수한다: 완료면 `RESULT: <요약>`, "
        "사람 판단이 필요하면 `QUESTION: <질문>` (출력 규약은 `dao-skills/CLAUDE.md` 참조)."
    )
    lines.append("")
    lines.append("## 스킬별 상세")
    lines.append("")
    for i, name in enumerate(order, 1):
        purpose, trigger = split_desc(found[name]["description"])
        lines.append(f"### {i}. {name}")
        lines.append("")
        lines.append(f"- **용도**: {purpose}")
        lines.append(f"- **단계 위치**: {i} / {len(order)}")
        lines.append(f"- **트리거 키워드**: {trigger if trigger else '(없음)'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    content = build()
    check = "--check" in sys.argv[1:]
    if check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print(
                "DAO-SKILLS.md 가 dao-skills 와 어긋남. "
                "`python3 bin/gen-dao-catalog.py` 로 갱신하세요.",
                file=sys.stderr,
            )
            return 1
        print("DAO-SKILLS.md 최신 상태.")
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(f"생성: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
