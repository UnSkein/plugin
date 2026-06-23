---
name: unskein-verify
description: 변경을 자체 검증한다. 스택을 감지해 타입체크·빌드·테스트를 돌리고 결과를 확인한다. 트리거 — 검증, 빌드, 테스트, 타입체크, 확인, verify.
---

# 자체 검증

이 단계는 `test` status로 claim된다. 이전 단계(`exec`)가 작업트리에 남긴 변경을 검증한다.

1. repo의 스택을 감지한다 (`package.json` / `pyproject.toml`·`requirements.txt` / `go.mod` / `Cargo.toml` 등).
2. 해당 스택의 점검을 돌린다 (있는 것만): 타입체크 → 빌드 → 테스트.
3. scope에서 정한 수용 기준을 실제로 만족하는지 확인한다.
4. 실패가 있으면 고치고 다시 돌린다. 돌릴 수 없는 점검은 결과에 "미실행"으로 명시한다 (통과한 것처럼 보고하지 않는다).

검증을 통과하지 못하면 완료로 보고하지 않는다 — 막히면 `QUESTION:`.

## 통과 후 — 작업 기록 저장

검증을 통과하면, 이 작업의 기록을 `docs/raw/<작업>.md`로 저장한다. 이 파일이 다음 단계 `unskein-wiki-ingest`의 입력이 된다. 파일명은 작업 id나 제목으로 한다.

담는 내용:

- **받은 작업**: 제목·설명·실행 계획.
- **검증 결과**: 무엇을 어떻게 점검해 통과했는지.
- **얻은 지식**: 이 작업에서 새로 알게 된 재사용 가능한 사실·주의사항(Gotcha)·결정. ← 가장 중요하다. 작업 메타데이터가 아니라, 다음 작업이 다시 분석하지 않도록 남기는 지식이다.

작업 기록은 아직 정제 전 원본이다. 어디에 무엇을 남길지 정제하는 일은 `unskein-wiki-ingest`가 한다.

## 보고 — 검증 결과를 산출 본문으로 낸다

검증 결과 본문을 `RESULT` 마커의 `<<<UNSKEIN_DOC` 블록에 담아 보고한다. 모리가 이 본문을 `result_doc`에 저장하고(칸반 표시 + 다음 단계 전달), 다음 단계(`inspect`/마감) 다오에게 "검증 결과"로 전달한다. 보고 next status는 `inspect`다.

```
RESULT: status=inspect stage=verify summary=<한 줄 요약>
<<<UNSKEIN_DOC
## 검증 결과
- <점검 항목과 결과>
UNSKEIN_DOC
```

`result_doc`은 검증 결과의 단일 출처다. 위 `docs/raw` 기록은 그 검증 결과에 "얻은 지식"을 덧붙인 것이다 (`docs/raw ⊇ result_doc`). 저장소·목적이 다른 의도적 이중화다 — `result_doc`은 칸반/단계 전달용(SaaS DB), `docs/raw`는 지식 정제(`unskein-wiki-ingest`) 입력용(repo). 검증을 통과하지 못하면 `RESULT` 대신 `QUESTION:`으로 회수한다.
