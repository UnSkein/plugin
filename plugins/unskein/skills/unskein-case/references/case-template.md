# 케이스 템플릿

`$UNSKEIN_HOME/cases/<host>/<feature>/<slug>/case.md` 로 저장한다. frontmatter 의
`host`/`feature`/`name` 은 디렉토리 경로와 한 글자까지 일치해야 한다(`name` = `<slug>`).
`host` 는 `case-sync.py slug <tested_url>` 로 파생한다 — 손으로 만들지 않는다.

> **비밀 무잔존**: 본문에 계정·비밀번호·토큰을 적지 않는다. 로그인 절차는
> "관리자 계정으로 로그인(자격은 운영 문서 참조)" 처럼 참조로만 쓴다.
> 최초 push 는 public 기본 — 비즈니스 멤버 전체가 본다.

```markdown
---
host: <호스트 슬러그>
feature: <기능 슬러그>
name: <케이스 슬러그 = 디렉토리 이름>
title: <사람이 읽는 한 줄 제목>
status: success            # success | partial | failed
tags: []                   # 선택
visibility: public         # public | private
task_id:                   # 선택 — 원 검증 작업 id
tested_url:                # 선택 — 실제로 연 주소
---

## 의뢰서 (Why)
<무엇을 왜 검증했나 — 수용 기준 요약. 작업 카드의 요구를 한 문단으로.>

## 실행 시퀀스 (How)
<재현 가능한 명령 순서 — remote.js navigate/click/type/wait/collect/shot 를
그대로 다시 돌릴 수 있게. 셀렉터·대기 조건 포함.>

1. `navigate <url>`
2. `wait <selector>`
3. …

## 결과 (What)
<판정과 근거 — 시나리오별 PASS/FAIL, 콘솔 에러·네트워크 실패 요약(문구는
diagnostics/ 에, 본문엔 결론만), 스크린샷 파일명(shots/…).>

## 함정 (Pitfalls)
<이 화면에서 걸리는 것들 — 늦게 뜨는 요소, 가짜 성공, 포트/프로필 주의,
데이터 전제(선행 시드) 등. 다음 검증자가 같은 곳에서 안 미끄러지게.>

## 다음 사용자에게 (Tips)
<재검증을 빠르게 하는 지름길 — 어느 시퀀스부터 돌리면 되는지, 어떤 단계는
생략 가능한지, 관련 케이스 링크.>
```

- 스크린샷은 같은 폴더 `shots/`, raw 진단 데이터(collect JSON·네트워크 덤프)는
  `diagnostics/` 에 둔다 — 이 하위 폴더는 케이스 저장소로 가지 않고, 그 회차 작업의
  증거로 따로 올라간다(`unskein-test` §0.2 6단계 `queue.js artifacts`).
- 다음 검증자가 그대로 돌릴 **재사용 스크립트**(`.js`·`.mjs`·`.py`·`.ps1`·`.sh`)는
  케이스 폴더 **최상위**에 둔다 — `case.md` 본문과 함께 서버로 가고 pull 이 실행
  가능한 상태로 떨군다(규칙·한도는 SKILL.md §4.1). 최상위 스크립트는 전부 올라가니
  안 올릴 파일은 하위 폴더로 옮긴다.
- 검증을 다시 돌린 경우(재검증) 결과 절에 이전 회와의 일치 여부를 남긴다
  (리포트 표준 — unskein-test SKILL.md §0.5).
