---
name: unskein-drawio
description: 플래너가 자기 프로젝트의 draw.io 다이어그램(구조도·ERD·플로우)을 다룬다. 다이어그램은 프로젝트의 문서(주인=프로젝트)이고, 플래너는 자기 신분(플래너 토큰)으로 자기 프로젝트 문서를 조회·생성·수정·삭제한다. 새 로그인·프로젝트 이름찾기 없음 — 이미 가진 걸 쓴다. 제목 끝 ` (id)` 규약으로 다이어그램을 특정한다. 트리거 — 다이어그램, 구조도, 도식, 그림, ERD, 플로우차트, drawio, draw.io, 구조도 수정/추가, diagram.
---

# /unskein-drawio — 프로젝트 다이어그램(draw.io) 관리

**소유권이 이 스킬의 뼈대다: 다이어그램은 프로젝트의 문서다**(`diagram.project_id`). 주인은 **프로젝트**지 사람(admin)이 아니다. 플래너는 자기 프로젝트(= 지금 붙어 있는 repo)의 문서를 **자기 신분(플래너 토큰)** 으로 다룬다. 서버는 "이 플래너가 그 프로젝트 소속이냐"(`_require_project`)로 접근을 판단한다 — 소속이면 프로젝트 문서를 읽고 쓴다.

그래서 **새로 로그인하지 않고, 프로젝트를 이름으로 찾지 않는다.** 신분도 프로젝트도 플래너가 이미 쥐고 있다 — 그걸 그대로 쓴다.

## 1. 전제 — 플래너가 이미 가진 것 (새로 만들지 않는다)

- **신분(토큰)**: `~/.unskein/planner.env` 의 `UNSKEIN_PLANNER_TOKEN`(kind=planner) + `UNSKEIN_API`. 쓰기 전 `source ~/.unskein/planner.env`.
- **프로젝트**: **지금 repo 가 곧 대상 프로젝트**다. `project_id` 는 `unskein-scope §4`(repo→프로젝트 매핑: `git remote get-url origin` → 프로젝트 `repo_url` 일치)로 얻는다. 스코프 세션에서 이미 정했으면 **그 값을 재사용**한다. (이 조회 자체도 플래너 토큰으로 된다 — `GET /api/businesses…/projects`.)
- **인가**: 서버가 프로젝트 소속으로 판단(`_require_project`/`_require_project_write`). 소속이 아니면 403 — 우회하지 말고 멈춘다.

**fallback 금지**: repo 가 어느 프로젝트에도 매핑 안 되거나 둘 이상이면 임의로 고르지 말고 묻는다(unskein-scope §4). 토큰이 없으면 조용히 넘기지 말고 드러낸다.

## 2. 인증·엔드포인트

- **헤더는 `X-Planner-Token: $UNSKEIN_PLANNER_TOKEN`.** (사람이 웹/직접 돌리는 세션이면 로그인 Bearer 도 같은 유저로 인가된다.) **admin/admin1234 로그인은 쓰지 않는다** — 문서 주인은 프로젝트지 admin 이 아니다.
- ⚠️ **전제 배포**: 다이어그램 라우트가 플래너 토큰을 받는 건 `get_current_user_flex` 승격(SaaS PR #54) 이후다. 그 전 서버는 다이어그램 라우트에서 토큰을 거부(401)한다 — 배포 확인 후 쓴다.

```
GET    /api/projects/{project_id}/diagrams      프로젝트의 활성 다이어그램 목록 (drawio_xml 포함)
POST   /api/projects/{project_id}/diagrams      생성  {title, kind, drawio_xml?, preview_svg?}
GET    /api/diagrams/{id}                        1건 전체 (drawio_xml·preview_svg 포함)
PATCH  /api/diagrams/{id}                        부분 수정 {title?, kind?, drawio_xml?, preview_svg?}
DELETE /api/diagrams/{id}                        소프트 삭제 (is_active=false)
```

- `kind` ∈ `erd | flow | api | process | etc`(위반 400). 구조도·토폴로지는 보통 `flow`.
- `drawio_xml` ≤ **5MB**(초과 413). `preview_svg` 는 `data:image/svg+xml…` 데이터 URL 만(위반 400).
- **PATCH 는 `exclude_unset`** — 보낸 필드만 바뀐다(안 보낸 `preview_svg` 는 유지 → §5 썸네일 지연).

목록 조회(플래너 토큰):
```bash
source ~/.unskein/planner.env
curl -s "$UNSKEIN_API/api/projects/$PID/diagrams" \
  -H "X-Planner-Token: $UNSKEIN_PLANNER_TOKEN" \
  | python3 -c 'import sys,json
for d in json.load(sys.stdin): print(d["id"], d["kind"], repr(d["title"]))'
```

## 3. 제목 끝 `(id)` 규약 — 다이어그램을 이름으로 특정 (필수)

제목 끝에 그 다이어그램의 DB id 를 괄호로 단다 — 예: `내가 생각하는 구조도 (Claude 이해) (4)`. id 는 생성 뒤에야 정해지므로 **2단계**로 마감:

1. `POST …/diagrams` → 응답의 `id`.
2. 곧바로 `PATCH /api/diagrams/{id}` 로 `title` 을 `"<원제목> (<id>)"` 로 갱신.

- **이미 ` (숫자)` 로 끝나면 다시 붙이지 않는다**(멱등). 정규식 `\s*\(\d+\)\s*$` 로 검사.
- 이후엔 목록 제목만 보고 id 를 안다(사람이 제목을 바꿔도 접미 id 로 되찾음).
- 이 규약은 표시 제목의 편의 식별자일 뿐 — 캔버스 안 heading(`mxCell id="title"`)이나 `<diagram name=…>` 은 건드리지 않는다.

## 4. 수정(가장 흔한 작업) — 안전 절차

1. **찾기**: `GET …/projects/{PID}/diagrams` → 제목(§3 접미 id)으로 대상 id 확정.
2. **원본 백업**: `GET /api/diagrams/{id}` → `drawio_xml` 을 스크래치패드에 저장(되돌리기용). preview_svg 유무 기록.
3. **편집**: mxGraph XML(§6)을 고친다. 새 노드/엣지는 **기존 셀의 style 을 그대로 답습**(색·엣지 일관).
4. **검증**: PATCH 전 반드시 well-formed 파싱 — `python3 -c 'import xml.dom.minidom as m; m.parse("new.xml"); print("OK")' || exit 1`.
5. **반영**: `drawio_xml` 만 PATCH(다른 필드 미포함 → 유지). HTTP 코드 확인.
6. **확인**: 재조회로 바뀐 셀(새 노드 id·라벨)이 저장 XML 에 있는지 grep. 200 만으로 끝내지 않는다.

생성은 §3(제목 id 마감), 삭제는 소프트(is_active=false)라 되돌리기 가능하나 사람 확인 후에.

## 5. preview_svg(썸네일) 지연 — 정직하게 알린다

목록 카드 미리보기는 `preview_svg`(draw.io 편집기 저장 시 내보낸 export)다. **API 로 `drawio_xml` 만 PATCH 하면 `preview_svg` 는 옛 그림 그대로** — 카드 썸네일이 잠깐 낡아 보인다(편집기로 열면 보이는 실제 도식은 최신).

- 썸네일은 **사람이 편집기에서 한 번 열고 Save** 하면 자동 갱신(에디터가 SVG 재export).
- 헤드리스로 정확한 draw.io SVG 를 만드는 건 무겁다 — **억지 SVG 를 넣지 말 것**(형식 위반·오도). 못 만들면 PATCH 에서 빼서(유지) 이 지연을 사용자에게 고지.

## 6. mxGraph(draw.io) XML 문법 — 최소 요점

```xml
<mxfile host="unskein.mupai.studio" agent="claude-code">
  <diagram id="<슬러그>" name="<이름>">
    <mxGraphModel ... pageWidth="1460" pageHeight="800" ...>
      <root>
        <mxCell id="0" /><mxCell id="1" parent="0" />
        <mxCell id="foo" parent="1" vertex="1"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
                value="제목&lt;br&gt;둘째 줄">
          <mxGeometry x="980" y="260" width="330" height="92" as="geometry" />
        </mxCell>
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
- **노드 id 유일**. 엣지 `source`/`target` 은 노드 id. 색·스타일은 기존 셀에서 복사해 팔레트 통일.
- 엣지가 다른 노드를 관통하면 `exitX/exitY`·`entryX/entryY`(0~1) + `<Array as="points">` 웨이포인트로 여백(gutter)을 돈다.
- **점선(`dashed=1`)** = "개념상 연결되나 미구현/미연결" 같은 상태 표기.
- 페이지가 넘치면 `pageHeight`/`pageWidth` 를 키운다.

## 7. 체크리스트

- [ ] 대상 프로젝트 = 지금 repo(unskein-scope §4 매핑, 이미 정했으면 재사용). 모호하면 질문(fallback 금지).
- [ ] 인증 = `X-Planner-Token`(플래너 자기 토큰). admin 로그인 안 씀. 토큰 없으면 멈춤.
- [ ] 수정 전 원본 `drawio_xml` 백업 + PATCH 전 XML well-formed 검증.
- [ ] 생성 시 제목 ` (id)` 마감(§3, 멱등).
- [ ] `drawio_xml` 만 PATCH(preview_svg 유지) + 재조회로 반영 확인.
- [ ] 썸네일 지연을 사용자에게 고지(편집기 저장 시 갱신).
