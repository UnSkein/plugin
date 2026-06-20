# unskein-marketplace

UnSkein 모리·다오 자동 개발 시스템을 Claude Code 플러그인으로 배포하는 마켓플레이스다.

이 저장소는 마켓플레이스 1개(`unskein-marketplace`)와 플러그인 1개(`unskein`)를 담는다.

```
.
├── .claude-plugin/
│   └── marketplace.json      ← 마켓플레이스 정의 (플러그인 목록)
├── plugins/
│   └── unskein/              ← unskein 플러그인 (상세는 plugins/unskein/README.md)
└── README.md                 ← 이 파일
```

## 담긴 플러그인

| 플러그인 | 설명 |
|----------|------|
| `unskein` | 모리·다오 실행 엔진 — 오케스트레이터 3 스크립트 + command 3개 + skill 2개 |

## 로컬 설치 절차

로컬 디렉토리를 마켓플레이스로 추가한 뒤 플러그인을 설치한다.

```shell
# 1) 이 디렉토리를 마켓플레이스로 추가
claude plugin marketplace add /home/ido/unskein-plugin

# 2) unskein 플러그인 설치
claude plugin install unskein@unskein-marketplace
```

설치 후 Claude Code 안에서 명령을 쓸 수 있다:

- `/unskein:run` — 작업 큐에서 한 건 선점해 한 바퀴 처리
- `/unskein:watch` — 작업 큐를 폴링하며 연속 처리
- `/unskein:status` — 연결·등록 상태 점검

## 설치 전 검증

설정을 바꾸지 않고 구조만 검사하려면:

```shell
cd /home/ido/unskein-plugin
claude plugin validate .
```

## GitHub 배포

이 저장소를 GitHub 에 올려 배포하려면 `.claude-plugin/marketplace.json` 의
플러그인 `source` 를 로컬 상대 경로에서 GitHub 참조로 바꾼다.

```json
"source": { "source": "github", "repo": "<owner>/<repo>" }
```

그러면 사용자는 `claude plugin marketplace add <owner>/<repo>` 로 추가할 수 있다.
