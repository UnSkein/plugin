---
name: unskein-git
description: 작업이 완료(close)되면 검증 통과분과 지식 기록을 feature 브랜치에 커밋·push 하고 PR 을 만든다. master/main 에 직접 머지하지 않는다(사람 리뷰·머지 게이트). 여러 개발자·배포 드리프트 방지의 핵심. 트리거 — 작업 완료, 마감, close, 커밋, 브랜치, PR, push, git.
---

# unskein-git — 작업 마감: 브랜치 + 커밋 + PR

작업이 검증(`unskein-verify`)을 통과해 끝나면, 변경을 **feature 브랜치**에 올리고 **PR** 을 만든다. 이 단계는 `inspect` status 로 claim 된다.

> **핵심 규칙: master/main 에 직접 머지하지 않는다.** 사람이 PR 을 리뷰·머지하는 게이트를 둔다(여러 개발자, 구현 ≠ 검증). 머지가 일어나면 그때 **테스트 서버 자동 배포**가 따른다(`unskein-deploy` / GitHub Actions). 즉 이 스킬은 "배포 가능한 상태의 PR" 까지만 만든다.

## 0. 먼저: 지식 기록·점검 (마감 보조)

- **unskein-wiki-ingest** — `docs/raw/` 의 작업 기록을 정제해 repo 지식(`docs/architecture/`·`docs/decisions/`)으로 옮기고, 처리한 원본을 `docs/raw/done/` 으로 이동한다.
- **unskein-wiki-lint** — 기록한 지식 문서의 부패(깨진 링크·중복·stale)를 점검한다.
- 이 산출물은 아래 커밋에 **함께 담는다**(코드 + 지식을 한 PR 로).

## 1. 변경 범위 확정 (WIP 분리)

- 받은 작업에 **직접 닿는 변경만** 커밋한다.
- 무관한 작업트리 변경(다른 기능 WIP·빌드 산출물 등)이 섞여 있으면 pathspec 으로 빼거나 별도로 다룬다. 한 파일에 무관 변경이 섞여 있으면 **hunk 단위로 갈라** 내 변경만 스테이징한다.

## 2. 브랜치

- **feature 브랜치**에서 작업한다(작업을 설명하는 이름; 예: `feat/<요약>`, `fix/<요약>`). 이미 작업 브랜치면 그대로 쓴다.
- `master`/`main` 에서 바로 커밋하지 않는다. 기본 브랜치에 있으면 먼저 브랜치를 판다.

## 3. 커밋

- 검증 통과분 + 지식 기록을 커밋한다. 메시지는 **무엇을·왜**를 한국어로.
- **비밀(토큰·키)** 이 변경·커밋·로그·원격 주소에 남지 않는지 확인한다. 남았으면 멈추고 회수한다.

## 4. 미러·유출 점검

- `orchestrator/run_once.py`·`run_loop.py` 를 고쳤다면 두 저장소(SaaS·plugin) **byte-identical** 인지 점검·동기화한다.
- `.gitignore` 로 막아야 할 유출(dao 스킬 dogfooding 심링크 등)이 커밋에 섞이지 않았는지 점검한다. 새는 것이 있으면 뺀다.

## 5. push + PR

- feature 브랜치를 원격에 push 한다(인증은 클라이언트 git 자격증명 — 토큰을 원격 주소에 넣지 않는다).
- **PR 을 만든다**(`gh pr create`). 제목·본문에 무엇을·왜·검증 결과·영향 범위를 담는다.
- 두 저장소에 걸친 변경(예: orchestrator 미러)이면 **양쪽 PR** 을 만들고 서로 링크한다.
- **머지는 하지 않는다.** 사람이 리뷰 후 머지한다.
- PR 생성이 환경상 불가하면(`gh` 미설치·미인증) **브랜치 push 까지만 하고 PR 은 사람에게 회수**한다 — `master` 직접 머지는 어떤 경우에도 하지 않는다. (`gh` 설치·인증은 `unskein-setup` 이 갖춘다.)
- push/PR 인증이 막히면 우회하지 말고 회수한다(fallback 금지).

## 보고 — 종결 본문을 산출 본문으로 낸다

PR 까지 만들면 변경 요약·**PR 링크**·검증 결과를 `RESULT` 마커의 `<<<UNSKEIN_DOC` 블록에 담아 보고한다. 모리가 이 본문을 `close_doc` 에 저장한다. 보고 next status 는 `done`이다(배포는 이후 머지 시 자동으로 일어난다 — 이 보고에 배포 결과는 포함하지 않는다).

```
RESULT: status=done stage=close summary=<한 줄 요약 + PR 링크>
<<<UNSKEIN_DOC
## 변경 요약
- <커밋·브랜치·PR 결과>
## PR
- <PR 링크 (또는 push 된 브랜치명 + PR 생성 요청)>
## 검증 결과
- <unskein-verify 결과 요지>
UNSKEIN_DOC
```

브랜치 push·PR 생성이 막히면 `RESULT` 대신 `QUESTION:` 으로 회수한다.
