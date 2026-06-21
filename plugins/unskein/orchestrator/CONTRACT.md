# 자식 에이전트 출력 규약

오케스트레이터(모리)가 자식 에이전트(다오)를 `claude -p` 로 구동한다. 자식은 작업을 마치면 오케스트레이터가 파싱할 수 있도록 마지막 줄에 약속된 형식으로 출력한다.

- 작업을 완료하면 마지막 줄에: `RESULT: <한 줄 요약>`
- 막히거나 사람 판단이 필요하면: `QUESTION: <질문 내용>`

## 어디에 정의되어 있나

이 규약과 다오의 단계 순서·절대 규칙은 `dao-skills/CLAUDE.md` 에, 단계별 절차는 `dao-skills/.claude/skills/unskein-*/SKILL.md` 에 있다. 모리(`run_once.py`)의 `plant_dao_skills()` 가 작업마다 이 `dao-skills/` 를 다오 작업 폴더(`WORK_ROOT`)로 복사해, 다오 세션이 `WORK_ROOT/CLAUDE.md` + `WORK_ROOT/.claude/skills/` 로 자동으로 읽는다.

`build_prompt()` 는 작업·repo 정보와 클론/풀 지시만 주고, 나머지(출력 규약·단계 순서·push 여부)는 위 `CLAUDE.md` 를 따르게 한다. 마커 파싱은 `extract_marker()` 가 한다 — 마커 문자열(`RESULT:`/`QUESTION:`)을 바꾸면 `dao-skills/CLAUDE.md`, `extract_marker()`, 이 문서를 함께 고친다.
