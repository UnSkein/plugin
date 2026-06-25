---
name: unskein-connect
description: 모리 클라이언트(WSL)를 UnSkein 서버에 연결한다 — claude/git 준비 확인 + 연결 정보(API 주소·모리 토큰) 설정 + 서버 도달 검증. 트리거 — unskein 연결, 서버 연결, connect, UnSkein 셋업, 모리 토큰 등록, 클라이언트 연결.
---

# UnSkein — 서버 연결

이 클라이언트(WSL)가 UnSkein 서버의 작업 큐에 닿을 수 있도록, 실행 환경과 연결 정보를 한 번 갖춰 둡니다. 특정 프로젝트가 아니라 클라이언트↔서버 연결만 다룹니다 — 프로젝트 추가는 `unskein-add-site` 를 쓰세요. 클라이언트 주인(사용자)과 대화하며 아래 순서로 진행합니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

## 1. 실행 환경 확인

다오(`claude -p`)는 WSL 안에서 구동합니다.

- WSL 안에 `claude`(Claude Code)가 있는지 확인합니다. 없으면 설치를 안내하고 멈춥니다.
- WSL 안에 `git` 이 있는지 확인합니다. 없으면 설치를 안내하고 멈춥니다.
- WSL 안에 `gh`(GitHub CLI)가 있고 인증돼 있는지 확인합니다(`gh auth status`). 다오가 마감 단계(`unskein-git`)에서 **PR 을 만들기** 때문입니다.
  - 없으면 설치를 안내합니다. sudo 가 없으면 공식 릴리스 바이너리를 `~/.local/bin` 에 풀어 넣습니다(gcloud 와 같은 무-sudo 방식): `cli/cli` 최신 릴리스의 `gh_*_linux_amd64.tar.gz` 를 받아 `bin/gh` 를 `~/.local/bin/gh` 로.
  - 인증: `gh auth login`(mupaistudio 계정, GitHub.com·HTTPS) → `gh auth setup-git`(이후 push 도 gh 자격증명으로 일원화).
  - `gh` 가 없거나 미인증이면 PR 생성이 안 됩니다. 그래도 멈추지는 않습니다 — 다오는 브랜치 push 까지 하고 PR 은 사람에게 회수합니다(`unskein-git`). 자동 PR 을 원하면 여기서 갖춰 둡니다.

## 2. 연결 정보 설정

서버 도달에 필요한 두 값을 WSL 환경에 영속 설정합니다(예: 셸 프로필 등).

- `UNSKEIN_API` — 작업 큐 주소 (예: `https://unskein.mupai.studio`).
- `UNSKEIN_MORI_TOKEN` — 연결 토큰. UnSkein 설정 화면에서 발급해 받습니다.

토큰·주소는 화면에 다시 출력하지 않습니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

watch 대상을 좁히려면(이 클라이언트가 특정 비즈니스/프로젝트만 바라보게), 아래 값을 함께 영속 설정합니다(선택 — 비우면 토큰 사용자의 모든 비즈니스/프로젝트가 대상):

- `UNSKEIN_WATCH_BUSINESS` — 바라볼 비즈니스 이름.
- `UNSKEIN_WATCH_PROJECT` — 바라볼 프로젝트 이름(비즈니스 안에서).

이름은 id 대신 사용자가 지정하기 쉬운 식별자입니다(id 는 환경별 상이). 지정한 이름이 멤버십에 없으면 `/unskein:run`·`/unskein:watch` 가 선점 전에 멈추고 가능한 이름을 알려 줍니다(조용히 전체로 넘어가지 않음). 가용 대상은 `/unskein:status` 로 확인합니다.

## 3. 작업 폴더 확인

- `UNSKEIN_CRED_DIR`(기본 `~/.unskein/creds`) 폴더를 확인하고 없으면 만듭니다.
- `UNSKEIN_WORK_ROOT`(기본 `~/.unskein/work`) 폴더를 확인하고 없으면 만듭니다.

## 4. 서버 도달 확인

연결 정보로 서버에 닿는지 1회 확인합니다:

```shell
curl -s "$UNSKEIN_API/api/health"
```

응답이 `{"status":"ok"}` 면 도달 OK 입니다. 이 단계는 서버에 닿는지만 봅니다(작업을 선점하지 않습니다). 토큰의 실제 유효성은 첫 작업 실행(`/unskein:run`) 때 확정된다고 안내합니다.

## 5. 값 누락 처리

토큰·주소 같은 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다. 다른 값으로 우회하지 않습니다.
