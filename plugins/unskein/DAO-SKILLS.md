# 다오wsl 스킬 카탈로그

> 모리가 띄운 작업 다오(다오wsl)에 어떤 스킬이 있고 언제 쓰는지의 참조 정보. 모리 클라이언트가 작업을 의뢰할 때 정확한 스킬을 가리키기 위한 목록이다.
>
> **자동 생성 — 직접 고치지 않는다.** 단일 출처는 `dao-skills/.claude/skills/*/SKILL.md`(스킬별 앞머리)와 `dao-skills/CLAUDE.md`(단계 표). 스킬을 추가·변경하면 `python3 bin/gen-dao-catalog.py`로 이 파일을 다시 만든다.

## 단계 순서 (claim status가 단계를 정한다)

다오wsl은 작업 하나를 받으면 모리가 claim한 `status`가 이번 수행 단계를 정한다. 각 단계는 **주 스킬**을 호출하고, **보조 스킬**은 그 단계 안에서 함께 수행한다(보조는 자체 status 전이가 없다). 한 호출에서 모든 단계를 밟지 않는다.

| claim status | 수행 단계 | 주 스킬 | 보조 스킬 | 보고 next status |
|---|---|---|---|---|
| `plan` | 구현 | `unskein-exec` | `unskein-wiki-search` | `test` |
| `test` | 검증 | `unskein-verify` | — | `inspect` |
| `inspect` | 마감 | `unskein-git` | `unskein-wiki-ingest`, `unskein-wiki-lint` | `done` |

마지막에 결과를 마커로 회수한다: 완료면 `RESULT: status=<다음 status> stage=<단계명> summary=<요약>` (+ 필요 시 `<<<UNSKEIN_DOC … UNSKEIN_DOC` 본문), 사람 판단이 필요하면 `QUESTION: <질문>` (출력 규약 전문은 `dao-skills/CLAUDE.md` 참조).

## 스킬별 상세

### unskein-exec — 구현 (plan 단계 · 주 스킬)

- **용도**: 정해진 범위를 최소·수술적으로 구현한다.
- **단계**: claim `plan` → 구현 수행 → 보고 `test`
- **트리거 키워드**: 구현, 코드 작성, 수정, 만들기, exec.

### unskein-wiki-search — 구현 (plan 단계 · 보조)

- **용도**: 작업을 시작하기 전에 이 repo에 이미 쌓인 지식(패턴·결정·주의사항)을 먼저 찾아 재분석을 막는다.
- **단계**: `plan`(구현) 단계에 흡수 — 자체 status 전이 없음
- **트리거 키워드**: 작업 시작, 기존 지식 검색, repo 파악, 무엇부터, 작업 전 조사.

### unskein-verify — 검증 (test 단계 · 주 스킬)

- **용도**: 변경을 자체 검증한다. 스택을 감지해 타입체크·빌드·테스트를 돌리고 결과를 확인한다.
- **단계**: claim `test` → 검증 수행 → 보고 `inspect`
- **트리거 키워드**: 검증, 빌드, 테스트, 타입체크, 확인, verify.

### unskein-git — 마감 (inspect 단계 · 주 스킬)

- **용도**: 작업이 완료(close)되면 검증 통과분과 지식 기록을 feature 브랜치에 커밋·push 하고 PR 을 만든 뒤 기본은 자동 머지한다(테스트 서버 자율 개발). 충돌·체크 실패는 다오가 해결해 머지, 권한 등 구조적 불가만 보고. UNSKEIN_AUTO_MERGE=0 이면 PR 까지만(사람 리뷰·머지).
- **단계**: claim `inspect` → 마감 수행 → 보고 `done`
- **트리거 키워드**: 작업 완료, 마감, close, 커밋, 브랜치, PR, push, git.

### unskein-wiki-ingest — 마감 (inspect 단계 · 보조)

- **용도**: 작업에서 얻은 지식(패턴·교훈·결정)을 이 repo에 기록해 다음 작업이 재사용하게 한다.
- **단계**: `inspect`(마감) 단계에 흡수 — 자체 status 전이 없음
- **트리거 키워드**: 지식 기록, 정리, 배운 것 저장, 문서화, wiki ingest, 작업 마무리.

### unskein-wiki-lint — 마감 (inspect 단계 · 보조)

- **용도**: repo에 쌓인 지식 문서의 부패를 점검한다 — 깨진 링크, 오래된(stale) 내용, 중복·충돌.
- **단계**: `inspect`(마감) 단계에 흡수 — 자체 status 전이 없음
- **트리거 키워드**: 위키 점검, 문서 부패, 링크 점검, 중복 정리, wiki lint, 지식 정리.
