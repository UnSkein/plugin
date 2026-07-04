---
name: unskein-git
description: 작업이 완료(close)되면 검증 통과분과 지식 기록을 feature 브랜치에 커밋·push 하고 PR 을 만든 뒤 기본은 자동 머지한다(테스트 서버 자율 개발). 충돌·체크 실패는 다오가 해결해 머지, 권한 등 구조적 불가만 보고. UNSKEIN_AUTO_MERGE=0 이면 PR 까지만(사람 리뷰·머지). 트리거 — 작업 완료, 마감, close, 커밋, 브랜치, PR, push, git.
---

# unskein-git — 작업 마감: 브랜치 + 커밋 + PR

작업이 검증(`unskein-verify`)을 통과해 끝나면, 변경을 **feature 브랜치**에 올리고 **PR** 을 만든 뒤, 기본값이면 **자동 머지**한다(§6). 이 단계는 `inspect` status 로 claim 된다.

> **머지 정책 (기본 = 자동 머지 · 테스트 서버 자율 개발).** PR 을 만든 뒤 **`UNSKEIN_AUTO_MERGE` 가 명시적으로 off(`0`/`false`/`no`)가 아니면 자동으로 머지**한다(§6). 머지되면 **테스트 서버 자동 배포**가 따르고, 화면·런타임 검증은 그 뒤 **TESTER** 몫이다(`docs/architecture/실행기-개발-검증-흐름.md`). **옵트아웃**(`UNSKEIN_AUTO_MERGE=0` = "내가 머지할께")이면 PR 까지만 만들고 **사람이 리뷰·머지**한다. 현 서버가 **테스트 서버**라 자율 머지를 기본으로 두며, 진짜 프로덕션이 생기면 거긴 리뷰 게이트를 유지한다. 어느 경우든 master 로 직접 커밋하지 않고 **PR 을 통해서만** 머지한다.

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
- 머지는 **§6** 에서 정책(`UNSKEIN_AUTO_MERGE`)에 따라 처리한다.
- PR 생성이 환경상 불가하면(`gh` 미설치·미인증) **브랜치 push 까지만 하고 PR 은 사람에게 회수**한다 — feature 브랜치→PR 경로를 **우회해 master 로 직접 커밋·push 하지 않는다**(머지는 §6 처럼 PR 을 통해서만). (`gh` 설치·인증은 `unskein-setup` 이 갖춘다.)
- push/PR 인증이 막히면 우회하지 말고 회수한다(fallback 금지).

## 6. 머지 (기본 = 자동)

`UNSKEIN_AUTO_MERGE` 를 확인한다(`echo $UNSKEIN_AUTO_MERGE`). **`0`/`false`/`no`/`off` 가 아니면(미설정 포함) 자동 머지한다:**
- `gh pr merge <PR> --squash --delete-branch`. **필수 상태체크가 있으면** `--auto` 로 통과 시 머지되게 큐잉한다(즉시 머지 거부 시 `--auto` 재시도).
- **머지가 막히면 다오가 직접 해결한다**(사람에게 안 넘긴다 — 자율 개발):
  - **충돌** → master 를 브랜치에 rebase/merge 해 충돌을 해결하고, 재검증(`unskein-verify`) 후 re-push → 다시 머지.
  - **필수체크 실패** → 원인을 보고 **고쳐서**(개발자니까) 다시 검증·push·머지.
  - **권한·리포 정책(사람 승인 필수 등)** 처럼 코드가 아닌 **설정 문제로 구조적으로 못 하는 것만** 예외 — 토큰 머지 권한·branch protection 조정이 필요하니 **사유만 보고**한다.
  - 조용히 스킵(fallback) 금지 — **해결하거나, 못 하면 사유를 보고**(무한 반복은 안 함).
- 머지 성공 시 next status 는 여전히 `done`(배포는 머지로 자동 트리거, 그 뒤 TESTER).

**`UNSKEIN_AUTO_MERGE=0`(사람 머지 모드)** 이면 머지하지 않고 PR 까지만 — 사람이 리뷰·머지한다.

## 보고 — 종결 본문을 산출 본문으로 낸다

PR 까지 만들면 변경 요약·**PR 링크**·검증 결과를 `RESULT` 마커의 `<<<UNSKEIN_DOC` 블록에 담아 보고한다. 모리가 이 본문을 `close_doc` 에 저장한다. 보고 next status 는 `done`이다(자동 머지면 배포·TESTER 가 곧 뒤따르나 이 보고엔 그 결과를 포함하지 않는다).

```
RESULT: status=done stage=close summary=<한 줄 요약 + PR 링크>
<<<UNSKEIN_DOC
## 변경 요약
- <커밋·브랜치·PR 결과>
## PR
- <PR 링크 (또는 push 된 브랜치명 + PR 생성 요청)>
## 머지
- <자동 머지됨 / 충돌 해결 후 머지됨 / 머지 불가(설정: 권한·정책) 사유 / 사람 머지 모드(UNSKEIN_AUTO_MERGE=0)>
## 검증 결과
- <unskein-verify 결과 요지>
UNSKEIN_DOC
```

브랜치 push·PR 생성이 막히면 `RESULT` 대신 `QUESTION:` 으로 회수한다.
