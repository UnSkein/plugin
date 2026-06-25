---
name: unskein-deploy
description: 머지된 커밋을 테스트 서버에 반영한다 — backend 통째 + import 스모크 + 재시작 + 실패 시 롤백 + 배포 SHA 기록. 배포 정보(docs/deploy.md)를 단일 출처로 읽는다. git 커밋·머지·PR 은 다루지 않는다(그건 unskein-git). 트리거 — 배포, deploy, 서버 반영, 테스트서버 반영, release.
---

# unskein-deploy — 테스트 서버 배포 (메커닉만)

머지된 변경을 **테스트 서버**에 반영한다. 이 스킬은 **배포 메커닉만** 다룬다 — git 커밋·브랜치·머지·PR 은 `unskein-git` 의 몫이다. 배포 정보는 repo 의 `docs/deploy.md` 를 **단일 출처**로 읽는다.

> 정상 흐름에서는 `master` 머지 시 **GitHub Actions 가 자동으로** 같은 절차를 돈다. 이 스킬은 자동 배포가 막혀 있거나(시크릿 미설정 등) **수동 배포가 필요할 때의 경로**다. 둘 다 `docs/deploy.md` §4 라는 같은 절차를 따른다.

## 1. 배포 정보 확인 — 먼저 한다

`docs/deploy.md` 에서 다음을 읽는다: 배포 대상(현재 = 테스트 서버)·접근 방법·재시작 방법·**배포 단위**·마이그레이션 방식·(해당 시) frontend 빌드.

- 필요한 정보가 다 있으면 → 2번.
- 없거나 비어 있으면 → 임의값·추측으로 배포하지 말고 **회수(QUESTION)**. 무엇이 빠졌는지(대상·접근·재시작·마이그레이션 중) 짚는다. 사람이 답하면 그 답을 `docs/deploy.md` 에 기록한 뒤 이어간다.

## 2. 배포 — docs/deploy.md §4 절차 (통째)

배포할 커밋 `<REF>`(보통 `origin/master`)에 대해, 로컬 작업트리가 아니라 **커밋된 트리**를 배포한다(미커밋 WIP 유출 방지):

0. **드리프트 점검** — `/api/version`(현 배포 SHA) ↔ `<REF>` SHA. 다르면 그 사이 커밋이 함께 올라감을 인지하고 진행(모르고 점프 금지).
1. **백업** — 덮어쓰기 전 서버 backend `.py` 보존.
2. **통째 전송** — `git archive <REF> backend` 로 backend 디렉토리 전체를 한 커밋에서. **변경 파일만 골라 올리지 않는다**(부분 배포 = import 불일치). `venv`·`.env`·`__pycache__` 는 전송하지 않아 서버 비밀·환경 보존.
3. **import 스모크** — `venv/bin/python -c "import main"` 통과해야 재시작한다(누락 모델 등 import 오류를 재시작 전에 잡음).
4. **배포 SHA 기록** — `backend/DEPLOYED_SHA` 에 `<REF>` SHA. `/api/version` 이 노출.
5. **재시작 + health, 실패 시 롤백** — health 실패면 백업 복원 후 재시작(깨진 채로 두지 않는다).

frontend·마이그레이션·DB 전체 교체가 필요하면 `docs/deploy.md` 의 해당 절을 따른다(마이그레이션은 자동 — 재시작만으로 적용).

## 3. 검증

- `/api/health` → `{"status":"ok"}`, `/api/version` → 배포한 `<REF>` SHA, `systemctl is-active` → active.

## 회수 / 보고

- 막히면(배포 정보 누락·접근/인증 실패·import 스모크 실패·health 실패) 우회하지 말고 **회수(QUESTION)**. fallback 금지.
- 결과(배포 SHA·검증)를 보고한다. 단계 마감 보고(`RESULT: status=...`)가 필요한 흐름이면 그 보고는 `unskein-git` 이 담당한다 — 이 스킬은 배포 결과만 낸다.

## 향후 프로덕션

- 현 대상은 **테스트 서버**다. 진짜 프로덕션 배포는 **별도 프로세스**로 잡는다(미정) — 그 절차가 정해지면 `docs/deploy.md` 에 추가하고 이 스킬이 대상으로 분기한다.
