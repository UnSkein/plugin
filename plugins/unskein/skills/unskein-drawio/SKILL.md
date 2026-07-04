---
name: unskein-drawio
description: 운영자/플래너가 프로젝트의 draw.io 다이어그램(구조도·ERD·플로우)을 서버 API 로 조회·생성·수정·삭제한다. 다이어그램은 SaaS DB 에 프로젝트 단위로 저장되고(트리 미접촉), mxGraph XML 을 직접 편집해 PATCH 로 반영한다. 제목 끝에 ` (id)` 규약을 지켜 다이어그램을 이름으로 쉽게 특정한다. 트리거 — 다이어그램, 구조도, 도식, 그림, ERD, 플로우차트, drawio, draw.io, 다이어그램 수정/추가/생성, 구조도 업데이트, diagram.
---

# /unskein-drawio — 다이어그램(draw.io) 관리 (조회·생성·수정·삭제 + 제목 id 규약)

프로젝트에 딸린 **draw.io 다이어그램**(구조도·ERD·플로우·프로세스)을 서버 API 로 다룬다. 다이어그램 본체는 `mxGraphModel` XML(draw.io 원본)이고 SaaS DB `diagram` 테이블에 **프로젝트 단위**로 저장된다(`diagram.project_id`). 조회·PATCH 는 작업 트리를 건드리지 않으므로 worktree 격리(§8.1) 대상이 아니다 — 스코프 등록처럼 공유 트리에서 바로 한다.

핵심 원칙:
- **제목 끝 `(id)` 규약(§4)** — 생성 직후 제목을 ` (id)` 로 마감해 다음에 이름만으로 다이어그램을 특정한다. 사람이 지은 제목과 충돌하지 않는 유일 식별자.
- **덮어쓰기 전 원본 백업 + XML well-formed 검증(§5)** — mxGraph XML 은 한 글자만 깨져도 draw.io 가 못 연다. PATCH 전에 파싱으로 검증하고, 원본 XML 을 스크래치패드에 백업해 되돌릴 수 있게 한다.
- **fallback 금지** — 대상 프로젝트·다이어그램이 모호하면 멈추고 묻는다. 인증 실패를 조용히 넘기지 않는다.
- **비밀 무잔존** — 로그인 토큰은 셸에 남기지 말고 로그인+조회를 한 호출로 묶거나 세션 스크래치패드에만 둔다.

## 1. 언제 쓰나

- "구조도/다이어그램/ERD/플로우 를 고쳐라 / 추가해라 / 보여줘" — 특정 프로젝트의 그림을 편집.
- 새 도식을 만들어 프로젝트에 붙일 때(생성 → 제목 id 마감 → XML 채움).
- 여러 다이어그램 중 하나를 이름으로 찾을 때(§4 규약이 이걸 쉽게 만든다).

ERD 를 **작업(Task)에 연결**하는 건 이 스킬 밖이다(웹 UI 의 작업 상세 ERD 탭 / `task_diagram` 조인). 이 스킬은 다이어그램 본체 CRUD 만 다룬다.

## 2. 대상·환경 정하기 — 먼저 한다

1. **환경**: `production`(`https://unskein.mupai.studio`) / `local`(`http://localhost:8200`). ido 지시에 따른다. base 는 `<서버>/api`.
2. **프로젝트**: 이름으로 특정(`UNSKEIN_SAAS` 등). **id 하드코딩 금지 — 환경마다 다르다.** `GET /api/projects` 로 이름→id 를 조회한다.
3. **다이어그램**: 프로젝트의 목록에서 제목(가능하면 `(id)` 접미)으로 특정(§4). 없거나 모호하면 멈추고 묻는다.

## 3. 인증·엔드포인트 (API 경로)

다이어그램 라우트는 **일반 유저 인증(admin 로그인 → Bearer)** 전용이다. **PLANNER 토큰(`X-Planner-Token`)·모리 토큰은 안 통한다**(그건 등록 라우트 전용 — 다이어그램은 `get_current_user`). 프로덕션은 API 만(admin/admin1234).

```
POST  /api/auth/login                          {username,password} → access_token (Bearer)
GET   /api/projects                            내 프로젝트 목록 → 이름으로 id
GET   /api/projects/{project_id}/diagrams      프로젝트의 활성 다이어그램 목록 (drawio_xml 포함)
POST  /api/projects/{project_id}/diagrams      생성  {title, kind, drawio_xml?, preview_svg?}
GET   /api/diagrams/{id}                        1건 전체 (drawio_xml·preview_svg 포함)
PATCH /api/diagrams/{id}                        부분 수정 {title?, kind?, drawio_xml?, preview_svg?}
DELETE /api/diagrams/{id}                       소프트 삭제 (is_active=false) + task_diagram cascade
```

- 쓰기(POST/PATCH/DELETE)는 프로젝트 멤버(owner/admin/member)만 — viewer 는 403. 격리는 프로젝트 경유.
- **`kind` ∈ `erd | flow | api | process | etc`** (위반 400). 구조도·토폴로지는 보통 `flow`.
- **크기 한도**: `drawio_xml` ≤ **5MB**(초과 413). `preview_svg` 는 `data:image/svg+xml…` 데이터 URL 만(위반 400).
- PATCH 는 `exclude_unset` — **보낸 필드만** 바뀐다(안 보낸 `preview_svg` 는 그대로 유지 → §6 썸네일 지연).

인증은 토큰이 셸에 남지 않게 **로그인+조회를 한 호출로** 묶는다(예):
```bash
API=https://unskein.mupai.studio/api
TOK=$(curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"admin1234"}' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
[ -z "$TOK" ] && { echo "LOGIN FAILED"; exit 1; }   # fallback 금지 — 조용히 넘기지 않는다
curl -s "$API/projects/7/diagrams" -H "Authorization: Bearer $TOK" \
  | python3 -c 'import sys,json
for d in json.load(sys.stdin): print(d["id"], d["kind"], repr(d["title"]))'
```

## 4. 제목 끝 `(id)` 규약 — 다이어그램을 이름으로 특정 (필수)

**다이어그램 제목은 끝에 그 다이어그램의 DB id 를 괄호로 단다** — 예: `내가 생각하는 구조도 (Claude 이해) (4)`. id 는 생성 뒤에야 정해지므로 **2단계**로 마감한다:

1. `POST …/diagrams` 로 생성 → 응답의 `id` 를 받는다.
2. 곧바로 `PATCH /api/diagrams/{id}` 로 `title` 을 `"<원제목> (<id>)"` 로 갱신한다.

- **이미 ` (숫자)` 로 끝나면 다시 붙이지 않는다**(멱등). 정규식 `\s*\(\d+\)\s*$` 로 검사.
- 이후 특정: `GET …/projects/{prj}/diagrams` 목록에서 제목이 ` (id)` 로 끝나므로 **제목만 보고 id 를 안다**. 사람이 제목을 바꿔도 접미 id 로 되찾는다.
- 이 규약은 **표시 제목의 편의 식별자**일 뿐 — 캔버스 안 제목 텍스트 셀(`mxCell id="title"` 의 heading)이나 `<diagram name=…>` 은 건드리지 않는다.

기존 다이어그램을 이 규약으로 일괄 정리하려면 목록을 돌며 접미가 없는 것만 PATCH 한다(멱등).

## 5. 수정(가장 흔한 작업) — 안전 절차

1. **찾기**: `GET …/projects/{prj}/diagrams` → 제목(§4 접미 id)으로 대상 id 확정.
2. **원본 백업**: `GET /api/diagrams/{id}` → `drawio_xml` 을 **스크래치패드에 저장**(되돌리기용). preview_svg 유무도 기록.
3. **XML 편집**: mxGraph XML(§7 문법)을 목적에 맞게 고친다. 새 노드/엣지는 **기존 셀의 style 문법을 그대로 답습**한다(색·엣지 스타일 일관).
4. **검증**: PATCH 전에 반드시 well-formed 파싱.
   ```bash
   python3 -c 'import xml.dom.minidom as m; m.parse("new.xml"); print("XML OK")' || exit 1
   ```
5. **반영**: `drawio_xml` 만 PATCH(다른 필드 미포함 → 그대로 유지).
   ```bash
   BODY=$(python3 -c 'import json;print(json.dumps({"drawio_xml":open("new.xml").read()}))')
   curl -s -o resp.json -w '%{http_code}\n' -X PATCH "$API/diagrams/{id}" \
     -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d "$BODY"
   ```
6. **확인**: 재조회로 바뀐 셀(새 노드 id·라벨)이 저장 XML 에 있는지 grep 으로 확인한다. HTTP 200 만으로 끝내지 않는다.

생성/삭제도 같은 정신: 생성은 §4(제목 id 마감), 삭제는 소프트(is_active=false)라 되돌리기 가능하나 사람 확인 후에.

## 6. preview_svg(썸네일) 지연 — 정직하게 알린다

목록 카드의 미리보기는 `preview_svg`(draw.io 가 편집기 저장 시 내보낸 export)다. **API 로 `drawio_xml` 만 PATCH 하면 `preview_svg` 는 옛 그림 그대로** — 카드 썸네일이 잠깐 낡아 보인다. 편집기 내용(열면 보이는 실제 도식)은 최신이다.

- 썸네일은 **사람이 편집기에서 한 번 열고 Save** 하면 자동 갱신된다(에디터가 SVG 재export).
- 헤드리스로 정확한 draw.io SVG 를 만드는 건 무겁다 — 억지 SVG 를 넣지 말 것(형식 위반·오도). `preview_svg` 를 못 만들면 **건드리지 말고**(PATCH 에서 빼면 유지) 이 지연을 사용자에게 고지한다.
- `preview_svg` 를 `null` 로 밀면 썸네일이 빈다 — 의도한 경우만.

## 7. mxGraph(draw.io) XML 문법 — 최소 요점

```xml
<mxfile host="unskein.mupai.studio" agent="claude-code">
  <diagram id="<슬러그>" name="<이름>">
    <mxGraphModel ... pageWidth="1460" pageHeight="800" ...>
      <root>
        <mxCell id="0" /><mxCell id="1" parent="0" />
        <!-- 노드(vertex) -->
        <mxCell id="foo" parent="1" vertex="1"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontStyle=1;"
                value="제목&lt;br&gt;둘째 줄">
          <mxGeometry x="980" y="260" width="330" height="92" as="geometry" />
        </mxCell>
        <!-- 엣지(edge) -->
        <mxCell id="e1" parent="1" edge="1" source="foo" target="bar"
                style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;dashed=1;strokeColor=#d79b00;"
                value="라벨">
          <mxGeometry relative="1" as="geometry">
            <Array as="points"><mxPoint x="1410" y="306"/><mxPoint x="1410" y="620"/></Array>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

- **라벨 줄바꿈은 `&lt;br&gt;`**(HTML), `html=1` 필수. `<`,`>`,`&` 는 XML 이스케이프.
- **노드 id 는 유일**. 엣지의 `source`/`target` 은 노드 id. 색·스타일은 기존 셀에서 복사해 팔레트를 통일한다.
- **엣지 경로가 다른 노드를 관통하면** `exitX/exitY`·`entryX/entryY`(0~1 앵커) + `<Array as="points">` 웨이포인트로 여백(gutter)을 돌린다.
- **점선(`dashed=1`)** = "개념상 연결되나 아직 미구현/미연결" 같은 상태 표기에 쓴다(범례를 노드 텍스트로 남기면 좋다).
- 페이지가 넘치면 `pageHeight`/`pageWidth` 를 키운다.

## 8. 체크리스트

- [ ] 환경·프로젝트를 이름으로 특정(id 하드코딩 금지). 모호하면 질문(fallback 금지).
- [ ] admin 로그인으로 Bearer 확보(planner/모리 토큰 아님). 실패 시 멈춤.
- [ ] 수정 전 원본 `drawio_xml` 백업 + PATCH 전 XML well-formed 검증.
- [ ] 생성 시 제목을 ` (id)` 로 마감(§4, 멱등).
- [ ] `drawio_xml` 만 PATCH(preview_svg 유지) + 재조회로 반영 확인.
- [ ] 썸네일 지연을 사용자에게 고지(편집기 저장 시 갱신).
- [ ] 토큰 무잔존(로그인+작업 한 호출 또는 스크래치패드).
