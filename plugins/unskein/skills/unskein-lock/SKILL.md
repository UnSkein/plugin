---
name: unskein-lock
description: >-
  UnSkein 작업의 점유(claim/락)를 사람이 안전하게 걸고 해제한다 — 모리 자율 루프가
  중단돼 작업이 "실행 중"으로 잠겨버린 점유 잔류를 풀거나(release/unclaim), 사람이 수작업
  중인 작업을 모리가 못 잡게 수동 동결(lock)한다. status 는 건드리지 않고 점유·동결 깃발만
  다룬다. 반드시 이 스킬을 써라 — 사용자가 "작업 점유 해제", "락 해제", "claim 풀어줘",
  "unclaim", "release", "#<번호> 풀어줘", "작업이 실행 중인데 멈췄어", "stuck claim",
  "죽은 워커 정리", "작업 잠가/동결", "락 걸어줘", "모리가 못 잡게 막아줘", "lock" 이라고
  하거나, 죽은 워커가 남긴 점유를 정리하려 할 때. 점유(claimed_by)·동결(locked_by)과
  상태(status)는 별개이며, 이 스킬은 점유·동결만 바꾸고 status 는 보존한다.
---

# UnSkein — 작업 점유·락 관리 (release / lock)

먼저 `unskein-setup` 으로 서버 연결(`UNSKEIN_API`·`UNSKEIN_MORI_TOKEN`)이 돼 있어야 합니다.

점유·동결과 상태(status)는 **직교**합니다 — 이 스킬은 점유 깃발(`claimed_by`)과 동결 깃발
(`locked_by`)만 다루고 `status`(plan/exec/test/inspect…)는 절대 바꾸지 않습니다. status 를
바꾸면 다음 클라이언트가 그 단계를 되풀이합니다. 사람과 대화하며 진행하고, 값이 빠지면
추측하지 말고 묻고 멈춥니다.

원칙:

- **status 불변** — 해제/걸기는 점유·동결 깃발만 다룹니다.
- **fallback 금지** — API 부재·권한·범위 밖이면 우회하지 말고 사유를 그대로 보고하고 멈춥니다.
- **비밀 무출력** — 토큰 값(`$UNSKEIN_MORI_TOKEN`)을 화면·로그에 남기지 않습니다. 점유자·
  동결자는 **종류만**(사람 수동 / 모리 클라이언트 / 사람 보드) 다룹니다.
- **scope 밖 거부** — 토큰 멤버십 밖 작업(404)은 손대지 않습니다.

## 모델 한 장 (왜 두 깃발인가)

| 깃발 | 뜻 | 자동 claim 과의 관계 |
|---|---|---|
| `claimed_by` | 모리가 선점(claim)한 점유 표식. 단계 간 보존되는 in-flight 신호(ADR-0007). | claim 은 이걸 **안 본다** — `heartbeat_at` 신선도(180s)로 진행 여부를 본다. |
| `heartbeat_at` | 워커 생존 신호. 신선하면 진행 중, 180s 끊기면(죽은 워커) 재선점 대상. | 신선하면 claim 후보에서 제외. |
| `locked_by` | 사람이 자동 claim 에서 빼려고 꽂는 **별개 직교 축**. 만료 없음. | claim 후보 쿼리가 `locked_by IS NULL` 을 거른다 → 동결되면 자동 선점에서 빠짐. |

- **release(해제)** = 죽은 점유를 즉시 푼다. `claimed_by`·`claimed_at`·`heartbeat_at`·
  `executed_by`·`locked_by` 를 비운다(status 보존). release 가 **unlock 을 겸한다**.
  죽은 자손의 잔존 `claimed_by` 는 **ADR-0015 이후** `_subtree_claimable` 이 heartbeat-aware 라
  `CLAIM_STALE_SECONDS`(180s) 만료 후 부모 단위 claim 을 **자동으로 안 막는다**(후보 쿼리와 같은
  self-heal — 더는 '영구 차단·자동 복구 없음'이 아니다). release 는 그 180s 를 안 기다리는 **즉시
  override** 로 남는다 — 살아있는(heartbeat 신선)·턴 사이(NULL)·동결(`locked_by`) 자손까지 강제로
  풀어야 할 때 쓴다.
- **lock(동결)** = `locked_by` 를 꽂아 모리가 못 잡게 한다(status 보존). 사람이 release 로
  풀 때까지 유지(heartbeat staleness 무관 — 만료 없음).

## 1. 대상·의도 확인

작업 번호와 의도(해제 release / 걸기 lock)를 받습니다. 번호가 없으면 묻고 멈춥니다(추측 금지).
여러 건이면 하나씩 처리합니다.

## 2. 현재 상태 읽기 (읽기 전용 — 변경 없음)

```shell
curl -s -H "X-Mori-Token: $UNSKEIN_MORI_TOKEN" "$UNSKEIN_API/api/mori/tasks/<id>"
```

응답에서 봅니다(값이 아니라 상태):

- `status` — 현재 단계(보존 대상).
- `claimed` / `claimed_by` — **모리 선점(claim) 여부**. `claimed_by` 의 비-None 값은 항상
  `user:{id}` 형태이고 **"모리가 사용자 {id} 명의로 선점한 점유"**를 뜻합니다(사람이 보드에서
  직접 claim 하는 경로는 없습니다). raw 마커(id)는 화면에 그대로 옮기지 말고 "점유됨/비점유"로
  말합니다. 이 스킬의 주 시나리오(죽은 워커의 점유 잔류)가 바로 이 `claimed`=true 입니다.
- `heartbeat_fresh` — `true` 면 워커가 살아 진행 중(섣불리 풀면 진행을 끊음), `false` 면
  끊긴(죽은) 점유 → 해제 안전.
- `is_waiting` — 사람 답 대기(waiting) 여부.
- `locked` / `locked_by` — **수동 동결 여부**. `locked_by` 는 항상 `human:token:{id}`(사람 수동
  동결)이라 종류는 "사람 수동(lock)" 하나뿐입니다. 동결됨/비동결만 말합니다.
- `subtree_claimed` / `subtree_locked` — 자손(서브트리) 중 점유/동결 수 → **cascade 판단**.

스코프 밖이면 404 — 손대지 않고 사유를 보고합니다.

## 3. 판정·영향 고지

무엇을 할지와 영향을 명시합니다 — 예: **"status=exec 는 그대로 두고 점유만 해제합니다"**.
판단 가이드:

- `heartbeat_fresh=true` 인데 release 하려 하면, **진행 중일 수 있다**고 알리고 정말 풀지
  확인합니다(사람 override 는 허용하되 Activity 에 남습니다).
- `subtree_claimed`/`subtree_locked > 0` 이고 서브트리째 처리하려면 `cascade=true`,
  단일 작업만이면 `cascade=false`(기본, 보수적). 어느 쪽인지 정합니다.

## 4. 확인 후 실행

서버 상태를 바꾸므로 실행 전 확인을 받습니다(특히 다른 클라이언트 점유 override, cascade).

**해제(release/unclaim)** — 멱등(이미 비점유·비동결이면 `affected:0` noop):

```shell
curl -s -X POST -H "X-Mori-Token: $UNSKEIN_MORI_TOKEN" -H "Content-Type: application/json" \
  -d '{"cascade": false}' "$UNSKEIN_API/api/mori/tasks/<id>/release"
```

**걸기(lock/동결)** — CAS(이미 동결돼 있으면 409 + 동결 종류 안내):

```shell
curl -s -X POST -H "X-Mori-Token: $UNSKEIN_MORI_TOKEN" -H "Content-Type: application/json" \
  -d '{"cascade": false}' "$UNSKEIN_API/api/mori/tasks/<id>/lock"
```

응답 처리:

- 성공 — `{"ok": true, "affected": <바뀐 수>, "task": {…변경 후 상태…}}`. `affected` 로 실제
  바뀐 작업 수를 보고합니다(release 가 `0` 이면 "이미 풀려 있었습니다").
- `409`(lock) — 이미 동결됨. 응답 `detail` 의 **동결 종류**를 그대로 안내하고 멈춥니다(덮어쓰지
  않음). 풀려면 먼저 release.
- `404` — 스코프 밖/없는 작업. 손대지 않고 사유 보고.

## 5. 재검증

`affected>0` 였다면(또는 확실히 하려면) 2장의 GET 을 다시 호출해 보고합니다:

- release: `claimed=false`, `locked=false`, `heartbeat_at` 비었는지 + **`status` 가 그대로**인지.
- lock: `locked=true`(종류=사람 수동), **`status` 가 그대로**인지.

status 가 바뀌었다면 무언가 잘못된 것이므로 그대로 보고합니다(이 스킬은 status 를 안 바꿉니다).

## 6. 엣지케이스

- **멱등/경합** — release 는 멱등(`affected:0`=이미 해제됨). lock 은 CAS 409 로 경합을 드러냅니다.
- **release 가 unlock 을 겸함** — 동결을 풀 때도 release 를 씁니다(별도 unlock 없음).
- **진행 중 release** — `heartbeat_fresh=true` 작업을 풀면, 살아있는 워커가 한 번 더 보고해
  단계를 옮길 수 있습니다(release 자체는 워커를 막지 못함 — 다음 claim 이 새 보유자로 펜스를
  세움). 또 그 늦은 heartbeat 가 release 직후 재선점을 최대 180s 지연시킬 수 있습니다(드문
  경합 — 필요하면 release 를 한 번 더). 죽은 워커 정리가 본래 용도입니다.
- **자손 동결 보호(ADR-0010)** — 자손 하나만 lock 해도, 그 자손을 품은 **조상의 단위 claim 이
  막힙니다**(`_subtree_claimable`). 즉 동결된 자손은 조상 단위 개발에 끌려가 done 으로 덮이지
  않습니다. 동결 자손이 있는 부모를 모리가 개발하게 하려면 먼저 그 자손을 release 합니다.
- **서브트리(ADR-0007)** — `cascade=true` 면 부모+자손을 한 번에 동결/해제. lock cascade 는 이미
  동결된 자손을 건너뜁니다(부분 멱등). 기본은 단일 작업(보수적).
- **scope 밖** — 토큰 멤버십 밖 작업은 404, 손대지 않습니다.

## 7. 못 할 때

API 가 404(엔드포인트 부재)거나 권한이 없으면, 임시 우회(DB 직접 수정, status 바꿔치기)를
만들지 않습니다. 어느 단계에서 막혔는지·관찰한 응답(비밀 제외)을 사용자에게 보고하고 멈춥니다.
