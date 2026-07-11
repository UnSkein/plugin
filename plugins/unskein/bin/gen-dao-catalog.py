#!/usr/bin/env python3
"""다오wsl 스킬 카탈로그 생성기.

단일 출처(dao-skills)에서 카탈로그(DAO-SKILLS.md)를 만든다. 스킬이 추가·변경되면
이 스크립트를 다시 돌려 카탈로그를 동기화한다 — 손으로 카탈로그를 고치지 않는다.

입력:
  dao-skills/CLAUDE.md                         (단계 표 — claim status → 주/보조 스킬)
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


class Stage:
    """CLAUDE.md 단계 표의 한 행 — claim status 하나가 한 단계를 정한다."""

    def __init__(self, status: str, label: str, main: str, aux: list[str], nxt: str):
        self.status = status  # claim status (plan/test/inspect)
        self.label = label  # 수행 단계 이름 (구현/검증/마감)
        self.main = main  # 주 스킬
        self.aux = aux  # 보조 스킬(그 단계 안에서 함께 수행, 자체 status 전이 없음)
        self.nxt = nxt  # 보고 next status


def read_stages() -> list[Stage]:
    """dao-skills/CLAUDE.md 의 단계 표에서 claim status→주/보조 스킬 매핑을 뽑는다.

    표 형식(ADR-0009 이후):
      | claim status | 수행 단계 (주 스킬) | 보조 단계 (…) | 산출 본문 | 보고 next status |
      | `plan` | 구현 (`unskein-exec`) | 앞: `unskein-wiki-search` … | 없음 | `test` |
    주 스킬은 2열의 백틱 스킬명, 보조 스킬은 3열의 모든 백틱 스킬명에서 읽는다.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    stages: list[Stage] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.split("|")[1:-1]]
        if len(cells) < 5:
            continue
        status_m = re.match(r"`([a-z]+)`$", cells[0])
        if not status_m:  # 헤더·구분선 행은 건너뛴다
            continue
        main_m = re.search(r"`(unskein-[a-z-]+)`", cells[1])
        if not main_m:
            raise SystemExit(f"단계 표 2열에서 주 스킬을 못 읽음: {cells[1]!r} ({CLAUDE_MD})")
        label = cells[1].split("(")[0].strip()
        aux = re.findall(r"`(unskein-[a-z-]+)`", cells[2])
        nxt_m = re.search(r"`([a-z]+)`", cells[4])
        stages.append(
            Stage(
                status=status_m.group(1),
                label=label,
                main=main_m.group(1),
                aux=aux,
                nxt=nxt_m.group(1) if nxt_m else "?",
            )
        )
    if not stages:
        raise SystemExit(f"단계 표를 찾지 못함: {CLAUDE_MD}")
    return stages


def build() -> str:
    stages = read_stages()
    found = {p.parent.name: read_frontmatter(p) for p in SKILLS_DIR.glob("*/SKILL.md")}

    # 표가 가리키는 스킬(주+보조)과 실제 SKILL.md 집합이 정확히 일치하는지 양방향 검증.
    referenced: list[str] = []
    for st in stages:
        referenced.append(st.main)
        referenced.extend(st.aux)
    ref_set = set(referenced)
    missing = [n for n in referenced if n not in found]
    if missing:
        raise SystemExit(f"단계 표에 있으나 SKILL.md 없음: {missing}")
    extra = [n for n in found if n not in ref_set]
    if extra:
        raise SystemExit(f"SKILL.md는 있으나 단계 표에 없음: {extra}")

    def cell(name: str) -> str:
        purpose, _ = split_desc(found[name]["description"])
        return purpose

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
        "`dao-skills/CLAUDE.md`(단계 표). 스킬을 추가·변경하면 "
        "`python3 bin/gen-dao-catalog.py`로 이 파일을 다시 만든다."
    )
    lines.append("")
    lines.append("## 단계 순서 (claim status가 단계를 정한다)")
    lines.append("")
    lines.append(
        "다오wsl은 작업 하나를 받으면 모리가 claim한 `status`가 이번 수행 단계를 정한다. "
        "각 단계는 **주 스킬**을 호출하고, **보조 스킬**은 그 단계 안에서 함께 수행한다"
        "(보조는 자체 status 전이가 없다). 한 호출에서 모든 단계를 밟지 않는다."
    )
    lines.append("")
    lines.append("| claim status | 수행 단계 | 주 스킬 | 보조 스킬 | 보고 next status |")
    lines.append("|---|---|---|---|---|")
    for st in stages:
        aux = ", ".join(f"`{a}`" for a in st.aux) if st.aux else "—"
        lines.append(
            f"| `{st.status}` | {st.label} | `{st.main}` | {aux} | `{st.nxt}` |"
        )
    lines.append("")
    lines.append(
        "마지막에 결과를 마커로 회수한다: 완료면 "
        "`RESULT: status=<다음 status> stage=<단계명> summary=<요약>` "
        "(+ 필요 시 `<<<UNSKEIN_DOC … UNSKEIN_DOC` 본문), 사람 판단이 필요하면 "
        "`QUESTION: <질문>` (출력 규약 전문은 `dao-skills/CLAUDE.md` 참조)."
    )
    lines.append("")
    lines.append("## 스킬별 상세")
    lines.append("")
    seen: set[str] = set()
    for st in stages:
        for name, role in [(st.main, "주 스킬")] + [(a, "보조") for a in st.aux]:
            if name in seen:  # 스킬은 처음 등장한 단계에서 한 번만 상세를 낸다
                continue
            seen.add(name)
            purpose, trigger = split_desc(found[name]["description"])
            lines.append(f"### {name} — {st.label} ({st.status} 단계 · {role})")
            lines.append("")
            lines.append(f"- **용도**: {purpose}")
            if role == "주 스킬":
                lines.append(
                    f"- **단계**: claim `{st.status}` → {st.label} 수행 → "
                    f"보고 `{st.nxt}`"
                )
            else:
                lines.append(
                    f"- **단계**: `{st.status}`({st.label}) 단계에 흡수 — "
                    "자체 status 전이 없음"
                )
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
