# env 템플릿 (`plugins/unskein/templates/`)

`executor.env.sample`·`planner.env.sample` 은 사용자가 `~/.unskein/env.<target>` 로 복사해 **직접 `source` 하는** 셸 파일이다. 스크립트가 파싱하지 않으므로, **셸 문법 유효성이 곧 수용 기준**이다.

## 규칙

- **주석 예시도 "주석 해제하면 유효한 셸"이어야 한다.** `#KEY=값에 공백` 형태는 주석 상태에선 무해해 보이지만, 사용자가 해제하는 순간 `source` 가 공백 뒤 단어를 명령으로 실행하려 든다 (`STUDIO: command not found`). 공백이 든 예시 값은 반드시 따옴표로 감싼다 — 예: `#UNSKEIN_WATCH_BUSINESS="MUPAI STUDIO"`.

## 검증 방법

예시 항목을 추가·수정할 때는 모든 예시 주석을 일괄 해제해 소싱해 본다:

```bash
sed 's/^#\(UNSKEIN_[A-Z_]*=\)/\1/' plugins/unskein/templates/executor.env.sample > /tmp/env.test
bash -c 'set -eu; source /tmp/env.test'
```

정상 종료하면 "주석 해제 시 깨지는 예시"가 없는 것이다. (2026-07 watch 예시 따옴표 수정에서 도입한 방식.)
