---
name: unskein-skill-creator
description: 사용자 프로세스의 단계 스킬(AI 단계가 수행할 스킬)을 규격에 맞춰 생산·점검하는 단일 진입점 — 정합성 3관문 중 ① 생산. 대상 프로세스 정의(상태·전이·doc_slot·claim_kinds)에서 스킬이 갖춰야 할 정보를 추출하고, 전이 계약 frontmatter(exits·output·version)와 출력 마커(RESULT/QUESTION)를 갖춘 SKILL.md 골격을 생성하며, 스킬 repo 를 린트(dev 예약 이름 거부·구체 status 키 금지·계약 형식 검증)하고 등록용 매니페스트(폐쇄 메타 JSON)를 추출한다. 스킬 repo 에 push 하기 전에 쓰는 생산 도구다 — 실행기는 클론·설치한 스킬을 수리하지 않는다. 트리거 — 단계 스킬 생성, 단계 스킬 만들기, 스킬 골격, 스킬 린트, 스킬 검사, 매니페스트 추출, 전이 계약, 프로세스 스킬, AI 단계 스킬, skill creator, skill lint, 스크.
---

# /unskein-skill-creator — 단계 스킬 생산 도구 (관문 ① 생산)

사용자 정의 프로세스의 **AI 단계(claim_kinds 가 비어 있지 않은 상태)가 수행할 스킬**을 만들고 점검한다. 단계 스킬은 손으로 흩어지게 쓰지 않고 이 도구를 단일 진입점으로 생산한다 — 형식 편차를 없애고(린트 통과 보장), "스킬 없는 상태(빈 칸)" 생산을 도구 수준에서 차단한다.

**이 문서가 단계 스킬 규격(전이 계약 frontmatter·린트 규칙)의 단일 출처다.**

## 0. 왜 — 스킬 1급화

AI가 밟는 모든 단계는 스킬이 있어야만 성립하고, 상태는 그 스킬 호출의 순서표다. 화면(정의 매트릭스)에서 프로세스를 만들 수 있어도, 스킬 없는 상태는 정의할 수는 있어도 실행되지 않는다. 설계 순서는 **스킬(실행 자산) → 배열(프로세스 정의) → 상태(파생)** 다.

스킬 정합성은 한 지점이 아니라 세 관문으로 보장한다(서버는 스킬 repo 를 읽을 수 없다 — 주소만 저장, 인증 비밀 없음):

| 관문 | 시점 | 무엇을 보장 | 수단 |
|---|---|---|---|
| ① 생산 | 스킬을 만들 때 | 스킬 자체 정합성 — 전이 계약 frontmatter·출력 마커·이름 slug | **이 스킬** (골격 생성 §3.2 + 린트 §3.3) |
| ② 등록 | 프로세스 연결·스킬 등록 전 | 순서·전이의 시스템 적합성 — 정의의 AI 단계마다 대응 스킬 존재 + 그 자리 전이 모양↔exits 일치 + doc_slot↔output 일치 | 매니페스트 등록(서버 교차 검증, 불일치 409). 서버 API 준비 전에는 §3.4 매니페스트 추출로 대비 |
| ③ 실행 | claim·설치 시 | 실물 일치 — 설치된 스킬이 등록분과 같은가(이름·버전) | 실행기 스캔 — 설치된 것만 능력 신고, 불일치는 QUESTION 회수(fallback 금지) |

## 1. 투입 시점 = 생산 시점 (push 전)

- 이 도구는 스킬 repo 에 push 되기 **전**에 쓴다. 실행기는 클론·설치한 스킬에 이 도구를 적용해 수리하지 않는다 — **정합성이 보장된 것만 소비한다.** (설치 후 수리는 실행기마다 실물이 달라져 재현성이 무너지고, 조용한 수리는 fallback 금지 위반이다. 실행기의 몫은 신원 대조뿐, 불일치는 질문 회수.)
- **배달 = 운영자 설치**: 완성된 단계 스킬은 스킬 plugin 으로 묶여 실행기 운영자가 직접 설치한다(현행 unskein plugin 설치·업데이트와 같은 사람 게이트). 미설치 실행기는 그 프로세스 카드를 집지 않을 뿐이고 카드는 기다린다(pull 원칙 — 정상). 업데이트 = plugin 업데이트라는 의식적 행위다.

## 2. 전이 계약 — frontmatter 규격

단계 스킬 SKILL.md 의 frontmatter 필수 키 5종:

| 키 | 값 | 뜻 |
|---|---|---|
| `name` | 소문자 slug (`[a-z][a-z0-9-]*`) | 정의의 skill_key 와 **정확 일치** — 단계→스킬 선택은 이 값 하나로만 된다 |
| `description` | 자유 텍스트 | 사람용 설명(트리거 포함 권장). 선택에는 쓰이지 않는다 |
| `version` | `X.Y.Z` | 실행 대장(ledger)의 skill_version 원료. 필수 — 누락 스킬은 신고·실행 불가 |
| `exits` | `forward` \| `verdict` \| `terminal` | 전이 모양(방법). 어느 모양이든 막히면 `QUESTION:` 회수 가능 |
| `output` | `none` \| `doc` \| `payload` | 산출물 형 |

- `exits` — **forward**: 단일 전진(수행 후 다음 status 하나로 보고) / **verdict**: PASS·FAIL 분기(판정에 따라 두 갈래 중 하나로 보고) / **terminal**: 단일 홉(수행 즉시 종결 상태로 보고).
- `output` — **none**: 산출 본문 없음(RESULT 첫 줄만) / **doc**: 문서 산출(`<<<UNSKEIN_DOC` 블록 → 정의의 doc_slot 에 저장. 슬롯 이름은 정의 소유 — 스킬은 "문서를 낸다"만 선언) / **payload**: 보고 payload 에 구조화 값.
- **구체 status 키 금지 (핵심 원칙)**: 전이 "방법"(exits 모양)은 스킬에, 전이 "대상"(구체 status 키)은 정의에 가른다. 스킬 본문·frontmatter 어디에도 특정 status 키를 박지 않는다 — 키를 박으면 그 스킬은 다른 프로세스 자리에 재배열할 수 없다. 보고할 status 값은 **작업 프롬프트(claim)가 배달한 값**만 쓴다.

## 3. 절차

### 3.1 추출 — 정의에서 스킬 요건 도출

대상 프로세스 정의(상태·전이·doc_slot·claim_kinds)와 그 단계가 다룰 작업 맥락에서 뽑는다:

- 스킬이 붙을 자리(상태)의 **전이 모양** → `exits` — 분기 자리면 verdict, 직진 자리면 forward, 접수 즉시 종결이면 terminal. 정의의 그 자리와 모양이 어긋나면 관문 ②에서 409 로 막힌다.
- 그 상태의 **doc_slot 유무** → `output` — 슬롯이 있으면 doc.
- **입력** — 이전 단계 산출물 슬롯. 스킬 본문 "입력" 절에 슬롯 이름이 아니라 **내용의 성격**으로 서술한다(예: "접수된 요청 본문").
- `claim_kinds` — 어느 실행기(kind)가 집는 단계인지(본문 맥락 서술용).

정의를 조회할 수 없으면(권한·환경) 사용자에게 상태·전이·산출물을 물어 채운다. 추측으로 채우지 않는다.

### 3.2 골격 생성

§5 템플릿으로 `<스킬 repo>/…/<name>/SKILL.md` 를 생성한다. 디렉토리명 = `name` = 정의에 지목할 skill_key.

### 3.3 린트 — 기계 검사

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/unskein-skill-creator/scripts/skill_lint.py" <스킬 repo 루트>
```

§4 규칙을 전부 검사한다(위반 1건 이상 = exit 1, 위반 목록 출력). 스크립트가 못 보는 것은 본문을 읽어 직접 확인한다:

- 본문 산문에 특정 프로세스의 status 키가 전이 대상으로 적혀 있지 않은가(예: "다음 status 는 `review` 다" — 재배열 불가로 만드는 반례).
- 출력 마커 예시가 §5 규약과 같은 형태인가.
- 막힘 처리(`QUESTION:` 회수)가 우회·fallback 없이 서술돼 있는가.

### 3.4 매니페스트 추출

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/unskein-skill-creator/scripts/skill_lint.py" <스킬 repo 루트> --manifest skills-manifest.json
```

린트 전부 통과 시에만 폐쇄 메타(`name`·`version`·`exits`·`output`)를 JSON 으로 추출한다. **스킬 본문은 서버에 올리지 않는다**(주입 경계 — 서버는 모양만 보고 적합성을 판정). 등록 API(관문 ②)가 준비되면 이 파일을 등록하고, 준비 전에는 스킬 repo 에 함께 커밋해 둔다.

## 4. 린트 규칙 (관문 ① 기계 검사)

1. frontmatter 필수 키 5종(`name`·`description`·`version`·`exits`·`output`) 존재
2. `name` = 소문자 slug(`[a-z][a-z0-9-]*`) 이고 디렉토리명과 일치
3. **dev 예약 이름 거부** — `unskein-exec`·`unskein-verify`·`unskein-git`·`unskein-wiki-search`·`unskein-wiki-ingest`·`unskein-wiki-lint`. 디폴트 스킬(dev 프로세스)과의 충돌·선택 혼란 차단(§6)
4. 같은 repo 안 `name` 중복 거부(선택 결정성)
5. `version` = `X.Y.Z` 형식
6. `exits` ∈ {forward, verdict, terminal} / `output` ∈ {none, doc, payload}
7. 본문에 출력 마커 규약(`RESULT:` 와 `QUESTION:`) 존재
8. `RESULT:` 예시 줄의 `status=` 값은 `<…>` 플레이스홀더여야 한다 — 구체 status 키 하드코딩 거부
9. `output: doc` 이면 본문에 `<<<UNSKEIN_DOC` 블록 규약 존재
10. 스킬 디렉토리에 `CLAUDE.md` 동봉 거부 — 예약 파일(다오 상시 규약은 시스템 소유). repo 다른 위치의 CLAUDE.md 는 경고(배포 자산에 섞이지 않는지 확인)
11. UTF-8 로 읽을 수 있어야 한다

## 5. 골격 템플릿

공통 뼈대(플레이스홀더 `<…>` 를 채운다). `exits`·`output` 값과 "보고" 절만 모양에 맞게 고른다.

````markdown
---
name: <skill-slug>
description: <이 단계가 하는 일 한 줄. 트리거 — <단계 이름>, …>
version: 0.1.0
exits: <forward|verdict|terminal>
output: <none|doc|payload>
---

# <단계 이름>

이 스킬은 프로세스 정의가 skill_key 로 지목한 단계에서, 실행기가 배달한 작업 프롬프트로 호출된다. 단계·다음 status·산출물 슬롯은 정의가 정하고 claim 이 배달한다 — 이 문서는 "무엇을 어떻게 하는지"만 담는다.

## 입력

- <이전 단계 산출물의 성격 — 예: 접수된 요청 본문. 슬롯 이름을 적지 않는다>

## 절차

1. <구체 작업>
2. <검증·확인>
3. 막히면(진전 없음, 인증·의존성 누락 등) 우회하지 말고 `QUESTION:` 으로 사유를 드러낸다(fallback 금지).

## 보고

status 값은 **작업 프롬프트가 배달한 다음 status** 를 그대로 쓴다. 이 문서에 status 키를 적지 않는다.

<보고 절 — exits 모양별로 아래에서 선택>
````

**exits: forward — 단일 전진** (output: none 이면 펜스 블록 생략)

````markdown
수행을 마치면 마지막 줄에 보고한다.

```
RESULT: status=<배달된 next status> stage=<skill-slug> summary=<한 줄 요약>
<<<UNSKEIN_DOC
<산출 본문 — output: doc 일 때만>
UNSKEIN_DOC
```
````

**exits: verdict — PASS·FAIL 분기**

````markdown
판정을 내리고, 판정에 대응하는 배달 status 로 보고한다 — PASS 면 <배달된 통과 next>, FAIL 이면 <배달된 실패 next>.

```
RESULT: status=<판정에 대응하는 배달 next> stage=<skill-slug> summary=<판정과 근거 한 줄>
<<<UNSKEIN_DOC
## 판정: PASS|FAIL
- <근거 항목>
UNSKEIN_DOC
```
````

**exits: terminal — 단일 홉 종결**

````markdown
수행 즉시 종결 상태로 보고한다(중간 상태 없음).

```
RESULT: status=<배달된 종결 status> stage=<skill-slug> summary=<한 줄 요약>
<<<UNSKEIN_DOC
<결과 본문 — output: doc 일 때만>
UNSKEIN_DOC
```
````

## 6. 디폴트 스킬 대체 원칙

기존 dao-skills 6개 = **디폴트 스킬이자 디폴트 단계(dev 프로세스)** 다. 사용자 스킬 plugin 이 들어와 이를 대체할 때 충돌·선택 혼란이 없어야 한다:

- **이름 충돌 금지**: dev 예약 이름(§4-3) + `CLAUDE.md`(§4-10)는 사용자 스킬이 쓸 수 없다 — 이 린트(관문 ①)와 매니페스트 등록(관문 ②) 시점에 거부된다.
- **선택 결정성**: 다오 세션 카탈로그에 같은 역할의 스킬이 둘 보여 "골라야 하는" 상황을 만들지 않는다. 단계→스킬 선택은 **claim 이 배달한 skill_key 정확 일치 하나**로만 — 다오가 비슷한 스킬을 추론으로 고르는 여지를 제거한다. description 은 사람용이고 선택에 관여하지 않는다.
- **대체 단위 = 프로세스**: dev 카드는 디폴트 스킬·단계표로, 사용자 프로세스 카드는 사용자 스킬로 — 한 카드 안에서 섞이지 않는다(트리 단일 프로세스 제약이 보장).
