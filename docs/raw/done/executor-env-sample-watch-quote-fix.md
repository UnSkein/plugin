# executor.env.sample watch 예시 따옴표 수정 (source 깨짐)

## 받은 작업

- **제목**: executor.env.sample watch 예시 따옴표 수정 (source 깨짐)
- **설명**: env 템플릿의 공백 값 예시(`UNSKEIN_WATCH_BUSINESS=MUPAI STUDIO` 등)가 따옴표 없이 있어, 사용자가 주석을 해제하면 `source ~/.unskein/env.<target>` 가 깨진다. 예시를 따옴표로 교정.
- **변경**: `plugins/unskein/templates/executor.env.sample` 의 watch 예시 두 줄을 `"MUPAI STUDIO"` / `"UNSKEIN_SAAS"` 로 따옴표 처리하고, "공백이 든 값은 따옴표 필수 (없으면 source 가 깨진다)" 주석 한 줄을 추가.

## 검증 결과

- **source 깨짐 재현 (수정 전)**: HEAD 버전을 주석 해제 후 `source` → `line 20: STUDIO: command not found` 로 실패 확인. (셸이 공백 뒤 `STUDIO` 를 명령으로 해석)
- **수정 후 통과**: 주석 해제 후 `bash -c 'set -eu; source …'` → 정상. `UNSKEIN_WATCH_BUSINESS=[MUPAI STUDIO]`, `UNSKEIN_WATCH_PROJECT=[UNSKEIN_SAAS]` 값이 의도대로 파싱됨.
- **잔존 위험 스캔**: `templates/` 전체(executor·planner)에서 따옴표 없는 공백 값 예시가 더 없음을 grep 으로 확인.
- **인코딩**: 수정 파일 UTF-8 확인 (`file -bi` → charset=utf-8).
- **타입체크·빌드·테스트**: 미실행 — 이 repo 는 셸 스크립트·마크다운 플러그인 repo 로 package.json/pyproject 등 빌드 스택이 없고, 변경도 템플릿 파일 한 개뿐이라 해당 점검이 존재하지 않는다.

## 얻은 지식

- **env 템플릿의 주석 예시도 "주석 해제하면 유효한 셸"이어야 한다.** `KEY=값에 공백` 형태는 주석 상태에선 무해해 보이지만, 사용자가 해제하는 순간 `source` 가 공백 뒤 단어를 명령으로 실행하려 든다. 템플릿에 공백 포함 예시를 둘 때는 반드시 따옴표로 감싼다.
- **템플릿 검증 방법**: `sed 's/^#\(UNSKEIN_[A-Z_]*=\)/\1/'` 로 모든 예시 주석을 일괄 해제한 뒤 `bash -c 'set -eu; source …'` 로 소싱하면 "주석 해제 시 깨지는 예시"를 기계적으로 잡을 수 있다. 새 예시 항목을 추가할 때 같은 방식으로 점검하면 재발을 막는다.
- **소비처**: 이 템플릿은 스크립트가 파싱하지 않고 사용자가 `~/.unskein/env.<target>` 로 복사해 직접 `source` 한다 (unskein-connect 스킬 문서 참조). 따라서 셸 문법 유효성이 곧 수용 기준이다.
