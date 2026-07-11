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
| `unskein` | 모리·다오 실행 엔진 — 오케스트레이터 4 스크립트(run_once·run_loop·work·status) + command 3개 + 운영자 skill 12개 + 자식 다오 스킬 6개(`dao-skills/`) |

## 설치 절차

이 저장소가 곧 마켓플레이스다. GitHub 저장소를 마켓플레이스로 추가한 뒤 플러그인을 설치한다.

```shell
# 1) 이 저장소를 마켓플레이스로 추가
claude plugin marketplace add UnSkein/plugin

# 2) unskein 플러그인 설치
claude plugin install unskein@unskein-marketplace
```

설치 후 Claude Code 안에서 명령을 쓸 수 있다:

- `/unskein:run` — 작업 큐에서 한 건 선점해 한 바퀴 처리
- `/unskein:watch` — 작업 큐를 폴링하며 연속 처리
- `/unskein:status` — 연결·등록 상태 점검

역할별(실행기·플래너·테스터) 상세 설치는 `plugins/unskein/docs/` 의 안내 문서를 따른다 —
설치 후에는 `${CLAUDE_PLUGIN_ROOT}/docs/` 에서 볼 수 있고, `unskein-setup` 스킬이 토큰 종류로
역할을 판별해 알맞은 절차로 이어 준다.

## 설치 전 검증

설정을 바꾸지 않고 구조만 검사하려면, 저장소를 받은 폴더에서:

```shell
git clone https://github.com/UnSkein/plugin.git
cd plugin
claude plugin validate .
```

## 배포 구조

이 저장소 자체가 마켓플레이스다 — 별도 배포 절차 없이 `main` 브랜치가 곧 배포본이다.
`.claude-plugin/marketplace.json` 이 마켓플레이스(플러그인 목록)를 정의하고, 플러그인
`source` 는 저장소 안의 상대 경로(`./plugins/unskein`)를 가리킨다. GitHub 저장소를
마켓플레이스로 추가하면 이 상대 경로가 저장소 루트 기준으로 풀려 플러그인을 찾는다.

포크로 배포하려면 `marketplace.json` 은 그대로 두고, 사용자가
`claude plugin marketplace add <owner>/<fork>` 로 자기 포크를 가리키게 하면 된다.
