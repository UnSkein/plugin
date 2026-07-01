---
name: unskein-connect
description: 모리 클라이언트(WSL)를 UnSkein 서버에 연결한다 — claude/git 준비 확인 + 연결 정보(API 주소·모리 토큰) 설정 + 서버 도달 검증. 트리거 — unskein 연결, 서버 연결, connect, UnSkein 셋업, 모리 토큰 등록, 클라이언트 연결.
---

# UnSkein — 서버 연결

이 클라이언트(WSL)가 UnSkein 서버의 작업 큐에 닿을 수 있도록, 실행 환경과 연결 정보를 한 번 갖춰 둡니다. 특정 프로젝트가 아니라 클라이언트↔서버 연결만 다룹니다 — 프로젝트 추가는 `unskein-add-site` 를 쓰세요. 클라이언트 주인(사용자)과 대화하며 아래 순서로 진행합니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

## 1. 실행 환경 확인

모리(오케스트레이터)와 다오(`claude -p`)는 **WSL distro 안에서** 구동합니다. 두 가지를 먼저 못박습니다:

- **상주 환경**: watch 는 오래 도는 루프라 **distro 가 떠 있는 상태로 그 안에서** 돌려야 합니다. 윈도우가 명령마다 distro 를 잠깐 켰다 끄는 방식으로는 루프가 명령 종료와 함께 죽습니다 — distro 에 들어가 상주로 띄우세요.
- **플러그인 설치 위치**: 오케스트레이터는 **설치된 플러그인**(`${CLAUDE_PLUGIN_ROOT}/orchestrator`)에서 돌고, 다오 스킬 원본(`dao-skills/`)도 그 옆에서 찾습니다. 따라서 **오케스트레이터가 도는 그 환경(WSL distro) 안에 플러그인이 설치돼 있어야** 합니다. 윈도우에만 설치돼 있고 distro 엔 없으면 작업 때 스킬을 못 찾아 실패합니다.

- WSL 안에 `claude`(Claude Code)가 있는지 확인합니다. 없으면 설치를 안내하고 멈춥니다.
- WSL 안에 `git` 이 있는지 확인합니다. 없으면 설치를 안내하고 멈춥니다.
- WSL 안에 `gh`(GitHub CLI)가 있고 인증돼 있는지 확인합니다(`gh auth status`). 다오가 마감 단계(`unskein-git`)에서 **PR 을 만들기** 때문입니다.
  - 없으면 설치를 안내합니다. sudo 가 없으면 공식 릴리스 바이너리를 `~/.local/bin` 에 풀어 넣습니다(gcloud 와 같은 무-sudo 방식): `cli/cli` 최신 릴리스의 `gh_*_linux_amd64.tar.gz` 를 받아 `bin/gh` 를 `~/.local/bin/gh` 로.
  - 인증: `gh auth login`(mupaistudio 계정, GitHub.com·HTTPS) → `gh auth setup-git`(이후 push 도 gh 자격증명으로 일원화).
  - `gh` 가 없거나 미인증이면 PR 생성이 안 됩니다. **모리는 작업을 잡기(claim) 전 preflight 에서 gh 인증을 치명 항목으로 점검하므로, 미설치·미인증이면 작업을 잡지 않고 종료하며 이 셋업을 요구합니다**(fallback 금지). 그러니 여기서 반드시 갖춰 두세요. (preflight 통과 후 세션 도중 gh 가 깨진 드문 경우엔, `unskein-git` 이 브랜치 push 까지만 하고 PR 은 사람에게 회수하는 2차 안전망이 있습니다.)

## 2. 연결 정보 설정

**먼저 타겟을 정합니다 — 이 클라이언트가 어느 서버의 큐를 볼지.** `UNSKEIN_API` 와 `UNSKEIN_MORI_TOKEN` 은 **한 서버에 묶인 짝**입니다: 토큰은 발급한 서버 전용이라, 서버를 바꾸면 토큰도 그 서버 것으로 바꿔야 합니다(안 맞으면 큐 접근이 401 로 거절됩니다).

| 타겟 | `UNSKEIN_API` | 토큰 | 언제 |
|------|---------------|------|------|
| 로컬(도그푸드/개발) | `http://localhost:8200` | 로컬 서버 토큰 | 이 머신에서 UnSkein 자체를 개발·도그푸드할 때(로컬 SaaS 가 dev 로 떠 있음) |
| 테스트 서버 | `https://unskein.mupai.studio` | 테스트 서버 토큰 | 실제 작업 큐를 처리하는 클라이언트일 때 |

> `unskein.mupai.studio` 는 헌장상 **테스트 서버**입니다(진짜 프로덕션은 별도·미정) — "프로덕션" 으로 부르면 타겟 오인으로 이어집니다.

정한 타겟의 두 값을 WSL 환경에 영속 설정합니다.

- `UNSKEIN_API` — 위 표에서 고른 작업 큐 주소.
- `UNSKEIN_MORI_TOKEN` — 그 서버에서 **kind=mori** 로 발급한 연결 토큰(UnSkein 설정 화면). EXECUTOR(claim)용이라 kind=mori 다 — 운영자 등록용 kind=planner 토큰(`~/.unskein/planner.env`, `플래너-설치.md` §4)과 다른 토큰이니 섞지 마세요(ADR-0013).

한 머신이 두 타겟을 오가면, 짝(API+토큰)을 **통째로** 담은 env 파일을 타겟별로 둡니다 — `~/.unskein/env.local`(로컬) / `~/.unskein/env.test`(테스트 서버). watch·run 전에 그 파일을 `source` 해서 해당 타겟의 API+토큰을 한꺼번에 잡습니다. 셸 프로필에는 **상시 쓰는 한 타겟만** 두고 나머지는 env 파일로 분리해, 스테일한 기본값이 조용히 따라붙지 않게 합니다.

> **템플릿에서 생성** — 플러그인에 커밋된 `templates/executor.env.sample`(비밀 없음)을 타겟 파일로 복사해 값만 채웁니다(권한 600, ADR-0013):
> ```shell
> cp "${CLAUDE_PLUGIN_ROOT}/templates/executor.env.sample" ~/.unskein/env.test
> chmod 600 ~/.unskein/env.test    # 편집기로 UNSKEIN_MORI_TOKEN 채우기 (셸 인자로 넣지 말 것)
> ```
> 값은 화면·셸 기록에 남기지 않도록 **편집기로 직접** 입력합니다. 두 타겟을 다 쓰면 `env.local` 로도 같은 복사를 반복합니다.

토큰·주소는 화면에 다시 출력하지 않습니다. 값이 빠지면 임의로 채우지 말고 사용자에게 물어 멈춥니다.

watch 대상을 좁히려면(이 클라이언트가 특정 비즈니스/프로젝트만 바라보게), 아래 값을 함께 영속 설정합니다(선택 — 비우면 토큰 사용자의 모든 비즈니스/프로젝트가 대상):

- `UNSKEIN_WATCH_BUSINESS` — 바라볼 비즈니스 이름.
- `UNSKEIN_WATCH_PROJECT` — 바라볼 프로젝트 이름(비즈니스 안에서).

이름은 id 대신 사용자가 지정하기 쉬운 식별자입니다(id 는 환경별 상이). 지정한 이름이 멤버십에 없으면 `/unskein:run`·`/unskein:watch` 가 선점 전에 멈추고 가능한 이름을 알려 줍니다(조용히 전체로 넘어가지 않음). 가용 대상은 `/unskein:status` 로 확인합니다.

> **단독 소유 — 원격 서버는 범위 필수.** 원격(테스트) 서버를 **범위 미지정(전체 큐)** 으로 watch 자율 루프하면, 여러 클라이언트가 같은 큐를 두고 경쟁합니다(한쪽이 끝낸 작업을 다른 쪽이 뒤집는 사고). 그래서 **범위 미지정 + 원격 서버 조합은 막혀 있습니다**(watch 가 선점 전 거부) — `bis/prj` 로 범위를 지정해 그 범위를 **이 클라이언트가 단독 소유**하게 하세요. 의도적으로 전체를 보려면 `UNSKEIN_ALLOW_UNSCOPED=1` 로 명시 동의합니다(로컬 서버는 가드 없음).

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
