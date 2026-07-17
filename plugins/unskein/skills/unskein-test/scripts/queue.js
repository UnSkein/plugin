#!/usr/bin/env node
/*
 * queue.js — UnSkein TESTER 큐 클라이언트 (화면검증 자율 루프의 HTTP 절반).
 *
 * TESTER(kind=tester 모리 토큰)가 검증 단계 작업을 선점(claim)하고, 검증 중 lease 를
 * 유지(heartbeat)하고, 결과(payload[<출발단계>] + result_doc)를 보고(report)하고, 판단이
 * 필요하면 질문(question)한다. CDP 화면조작은 remote.js 가, 이 스크립트는 서버 왕복만 맡는다.
 *
 * 단계 어휘는 이 스크립트가 갖지 않는다 — 카드가 속한 프로세스 정의가 정하고, claim 이
 * 그 카드의 단계 값(stage_skill·stage_doc_slot·stage_label·reportable_next)을 배달한다.
 * dev 의 test→inspect/plan 은 그 정의가 그런 모양이라 그렇게 도는 것이지 여기 박힌 게 아니다.
 *
 * 인증/연결(비밀 무잔존 — 값은 환경변수로만, 화면 출력 금지):
 *   UNSKEIN_API_BASE   예: https://unskein.mupai.studio   (기본 http://127.0.0.1:8000)
 *   UNSKEIN_MORI_TOKEN 테스터 토큰(kind=tester). 없으면 즉시 오류로 멈춘다(fallback 금지).
 *
 * 서브커맨드:
 *   scope                                     내가 담당(watch)할 수 있는 사이트 목록(GET /api/mori/scope)
 *   claim [--business=<이름>] [--project=<이름>]  검증 단계 작업 1건 선점. 없으면 {"claimed":false}
 *                                              설치 스킬(능력)을 함께 신고한다 — 서버가 (정의의
 *                                              skill_key × 신고 × kind) 교차로 후보를 파생한다.
 *   heartbeat <task_id>                        lease 갱신(긴 검증 중 주기적으로)
 *   report <task_id> --status=<다음 status> [--stage=<출발 단계>] [--summary=<s>] [--doc=<file>] [--payload=<file>]
 *                                              검증 결과 보고. --status 는 claim 이 배달한
 *                                              stage.reportable_next 중 하나(어휘는 정의 소유·서버 검증).
 *                                              --stage 생략 시 서버에서 이 카드의 현재 단계를 읽어 쓴다.
 *   question <task_id> --text=<q> [--session=<id>]  사양/버그 판단 필요 시 사람에게 질문(waiting)
 *
 * 예:
 *   node queue.js claim --project=unskein
 *   node queue.js report 412 --status=inspect --summary="화면검증 통과" \
 *        --doc=cases/412/report.md --payload=cases/412/payload.json
 *
 * 출력: 항상 JSON 한 줄(성공/실패 모두). 스킬(클로드 세션)이 파싱해 다음 단계를 정한다.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const API_BASE = (process.env.UNSKEIN_API_BASE || "http://127.0.0.1:8000").replace(/\/+$/, "");
const TOKEN = process.env.UNSKEIN_MORI_TOKEN || "";

// --- 능력 신고(6단계 — 스킬 1급화). run_once.py:628/674 의 node 판. ---
// 신고 = "이 스킬들이 실물로 설치돼 있다"(설치 실물 스캔이라 과대신고가 구조적으로 없다).
// 서버가 (프로세스 정의의 skill_key × 이 목록 × kind) 교차로 선점 가능 카드를 파생한다 —
// 신고가 없으면 서버는 사용자 프로세스 가지를 아예 만들지 않아 dev 카드만 돈다.

// dev 동봉 6종은 계약 frontmatter 이전 규격이라 이름으로 통과시킨다(원본 run_once.py:658-661).
const DEV_DEFAULT_SKILLS = new Set([
  "unskein-exec", "unskein-verify", "unskein-git",
  "unskein-wiki-search", "unskein-wiki-ingest", "unskein-wiki-lint",
]);

// SKILL.md 선두 '---' 쌍의 key: value 를 파싱해 폐쇄 메타만 뽑는다. 스킬 본문은 절대
// 올리지 않는다(주입 경계 — 스킬 규격 unskein-skill-creator SKILL.md §2).
// 형식이 아니면 null(신고 제외 — 그 스킬은 애초에 단계 스킬 자격이 없다).
function skillFrontmatter(file) {
  let text;
  try { text = fs.readFileSync(file, "utf8"); }
  catch { return null; }
  const lines = text.slice(0, 16384).split(/\r?\n/);
  if (!lines.length || lines[0].trim() !== "---") return null;
  const meta = {};
  let closed = false;
  for (const line of lines.slice(1)) {
    if (line.trim() === "---") { closed = true; break; }
    const i = line.indexOf(":");
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  if (!closed) return null;  // 닫는 '---' 없음
  const name = meta.name;
  if (!name) return null;
  // 단계 스킬만 신고한다 — 전이 계약(exits·output)이 있는 것. 도구 스킬(dataviz 등)은
  // 프로세스 단계가 될 수 없으므로 능력표를 오염시키지 않는다.
  if (!DEV_DEFAULT_SKILLS.has(name) && !(meta.exits && meta.output)) return null;
  const out = { name };
  for (const k of ["version", "exits", "output"]) if (meta[k]) out[k] = meta[k];
  return out;
}

// SKILL.md 재귀 수집. 심볼릭 링크는 따라가지 않는다(Dirent 는 lstat 기준이라 isDirectory()
// 가 false — 순환이 구조적으로 없다). 이름순 정렬 = 중복 시 첫 발견의 순서를 고정한다.
function walkSkillFiles(root, acc, depth) {
  let entries;
  try { entries = fs.readdirSync(root, { withFileTypes: true }); }
  catch { return; }  // 권한 없음·경합 삭제 — 그 가지만 건너뛴다
  entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const e of entries) {
    const p = path.join(root, e.name);
    if (e.isDirectory()) { if (depth > 0) walkSkillFiles(p, acc, depth - 1); }
    else if (e.isFile() && e.name === "SKILL.md") acc.push(p);
  }
}

let _skillScanCache = null;

// 설치 스킬 스캔 — 능력 신고의 원천. 이름 중복은 첫 발견이 이긴다. 한 실행 안에서 두 번
// 스캔하지 않는다(queue.js 는 명령당 단발이라 캐시는 위생 목적).
//
// 탐색 루트: ① 테스터에 설치된 Claude plugin 스킬(~/.claude/plugins 아래 SKILL.md —
// 배달=운영자 설치 모델의 실물) ② UNSKEIN_SKILL_SCAN_DIRS(선택, PATH 규약 구분자).
// 실행기의 dao-skills 루트는 여기 없다 — 그건 실행기가 작업 폴더에 심는 원본이고,
// 테스터는 작업 폴더를 심지 않는다.
//
// 구분자는 node 의 path.delimiter 다(윈도우 ';' · POSIX ':'). 실행기(python)는 ':' 고정인데
// 테스터는 윈도우 호스트라 ':' 를 쓰면 드라이브 문자(C:\...)에서 경로가 쪼개진다.
function scanInstalledSkills() {
  if (_skillScanCache) return _skillScanCache;
  const roots = [path.join(os.homedir(), ".claude", "plugins")];
  for (const p of (process.env.UNSKEIN_SKILL_SCAN_DIRS || "").split(path.delimiter)) {
    if (p.trim()) roots.push(p.trim());
  }
  const skills = [];
  const seen = new Set();
  for (const root of roots) {
    try { if (!fs.statSync(root).isDirectory()) continue; }
    catch { continue; }
    const files = [];
    walkSkillFiles(root, files, 12);
    for (const f of files) {
      const meta = skillFrontmatter(f);
      if (meta && !seen.has(meta.name)) { seen.add(meta.name); skills.push(meta); }
    }
  }
  _skillScanCache = skills;
  return skills;
}

function die(msg, extra) {
  // 비밀은 절대 싣지 않는다 — 메시지에 토큰/URL 자격증명이 섞이지 않게 호출부에서 관리.
  process.stdout.write(JSON.stringify({ ok: false, error: msg, ...(extra || {}) }) + "\n");
  process.exit(1);
}

function out(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

// --flag=value 파싱. 위치인자는 args._ 로.
function parseArgs(argv) {
  const a = { _: [] };
  for (const tok of argv) {
    const m = /^--([^=]+)=(.*)$/.exec(tok);
    if (m) a[m[1]] = m[2];
    else if (/^--/.test(tok)) a[tok.slice(2)] = true;
    else a._.push(tok);
  }
  return a;
}

async function api(method, path, body) {
  if (typeof fetch !== "function") die("node18+ 필요 (전역 fetch 없음)");
  const url = API_BASE + path;
  const headers = { "X-Mori-Token": TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // 5xx/네트워크는 지수 백오프 재시도, 4xx 는 영구(계약 위반이니 그대로 드러낸다).
  let lastErr;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
      if (res.status >= 500) { lastErr = { status: res.status, data }; }
      else return { status: res.status, data };
    } catch (e) {
      lastErr = { status: 0, data: { error: String(e && e.message || e) } };
    }
    await new Promise((r) => setTimeout(r, 500 * Math.pow(2, attempt)));
  }
  return lastErr;
}

function readFileMaybe(p, kind) {
  if (!p) return undefined;
  try { return fs.readFileSync(p, "utf8"); }
  catch (e) { die(`${kind} 파일을 읽지 못했습니다: ${p}`); }
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  if (!TOKEN) die("UNSKEIN_MORI_TOKEN(테스터 토큰)이 없습니다 — 설정 후 다시 실행하세요");
  const args = parseArgs(rest);

  if (cmd === "scope") {
    const r = await api("GET", "/api/mori/scope");
    if (!r || r.status !== 200) return die("scope 조회 실패", { status: r && r.status });
    return out({ ok: true, scope: r.data });
  }

  if (cmd === "claim") {
    const body = {};
    if (args.business) body.business = args.business;
    if (args.project) body.project = args.project;
    // 능력 신고 — 설치 스킬의 폐쇄 메타. 없으면 서버가 사용자 프로세스 가지를 안 만든다.
    const skills = scanInstalledSkills();
    if (skills.length) body.skills = skills;
    const r = await api("POST", "/api/mori/claim", body);
    if (!r || r.status !== 200) return die("claim 실패", { status: r && r.status, detail: r && r.data });
    // 에코 검증(fallback 금지 — run_once.py:751 과 대칭): 신고했는데 응답에 skills 키가 아예
    // 없으면 구서버가 신고를 무시한 것이다. 그대로 돌면 사용자 프로세스 카드는 영영 안 잡히고
    // dev 카드만 도는데 운영자는 처리되는 줄 안다. 침묵 축소 운행 대신 중단해 드러낸다.
    // (현 서버는 신고 없이도 skills: null 을 실어 보내므로 키 존재로만 판별한다.)
    if (body.skills && !("skills" in r.data)) {
      return die(
        "서버가 스킬 능력 신고를 지원하지 않습니다 — 신고가 무시된 채 dev 카드만 받게 되므로 " +
        "중단합니다(서버 업데이트 필요).",
        { reported: skills.map((s) => s.name) }
      );
    }
    // task 에 tested_url(검증 대상 사이트)·plan_doc(수용 기준)·subtree 가 실려 온다.
    // stage 는 그 카드의 단계 구조 값(정의 파생) — 루프가 report 에 그대로 넘긴다.
    const task = r.data.task || null;
    return out({
      ok: true,
      claimed: !!r.data.claimed,
      task,
      skills: r.data.skills || null,   // 서버가 접수·적용한 신고(에코)
      stage: task
        ? {
            status: task.status,                      // 출발 단계 = report --stage 에 넘길 값
            skill: task.stage_skill || null,          // 이 단계가 호출할 스킬(이름 정확 일치)
            doc_slot: task.stage_doc_slot || null,    // 산출물이 앉는 슬롯
            label: task.stage_label || null,          // 사람용 표시명
            reportable_next: task.reportable_next || null,  // report --status 는 이 중 하나
          }
        : null,
    });
  }

  const id = args._[0];
  if (["heartbeat", "report", "question"].includes(cmd) && !id) {
    return die(`${cmd} 에는 task_id 가 필요합니다`);
  }

  if (cmd === "heartbeat") {
    const r = await api("POST", `/api/mori/tasks/${id}/heartbeat`);
    if (!r || r.status !== 200) return die("heartbeat 실패", { status: r && r.status });
    return out({ ok: true });
  }

  if (cmd === "report") {
    // status 어휘는 검사하지 않는다 — 카드가 속한 프로세스 정의가 소유하고 서버가
    // (process, key) 멤버십·인접성으로 판정해 어긋나면 400 을 준다. 여기서 dev 어휘
    // (inspect/plan)로 미리 거르면 사용자 프로세스는 통과할 수 없다. 미지정만 막는다 —
    // 배달된 reportable_next 가 2개일 수 있어(분기 정의) 자동 선택은 추측이 된다.
    const status = typeof args.status === "string" ? args.status : "";
    if (!status) {
      return die("report 에는 --status=<다음 status> 가 필요합니다 — claim 이 배달한 stage.reportable_next 중 하나를 고르세요");
    }
    // 출발 단계 — 실행 대장(Activity)에 남는 값이다. 하드코딩하지 않는다: 넘겨받은 값이
    // 있으면 그것을, 없으면 서버에서 이 카드의 현재 단계를 읽어 쓴다(추측이 아니라 서버 값).
    // 생략해서 서버에 안 보내면 서버가 stage 를 body.status(=다음 단계)로 적어 대장이
    // 조용히 틀린다 — 그래서 못 정하면 아래처럼 명확히 실패한다.
    let stage = typeof args.stage === "string" && args.stage ? args.stage : "";
    if (!stage) {
      const s = await api("GET", `/api/mori/tasks/${id}`);
      if (!s || s.status !== 200) {
        return die("출발 단계를 서버에서 읽지 못했습니다 — --stage=<출발 단계> 를 직접 넘기세요", { status: s && s.status });
      }
      stage = s.data.status || "";
      if (!stage || ["answered", "waiting"].includes(stage)) {
        return die(`카드가 ${stage || "미상"} 상태라 출발 단계를 확정할 수 없습니다 — --stage=<출발 단계> 를 직접 넘기세요`);
      }
    }
    const body = { status, stage };
    if (args.summary) body.summary = args.summary;
    const docText = readFileMaybe(args.doc, "doc");
    if (docText !== undefined) body.doc = docText;
    const payloadText = readFileMaybe(args.payload, "payload");
    if (payloadText !== undefined) {
      try { body.payload = JSON.parse(payloadText); }
      catch { return die(`payload JSON 파싱 실패: ${args.payload}`); }
    }
    const r = await api("POST", `/api/mori/tasks/${id}/report`, body);
    if (!r || r.status !== 200) return die("report 실패", { status: r && r.status, detail: r && r.data });
    return out({ ok: true, status, stage });
  }

  if (cmd === "question") {
    if (!args.text) return die("question 에는 --text 가 필요합니다");
    const body = { question: args.text };
    if (args.session) body.session_id = args.session;
    const r = await api("POST", `/api/mori/tasks/${id}/question`, body);
    if (!r || r.status !== 200) return die("question 실패", { status: r && r.status, detail: r && r.data });
    return out({ ok: true, waiting: true });
  }

  die(`알 수 없는 명령: ${cmd || "(없음)"} — scope|claim|heartbeat|report|question`);
}

main().catch((e) => die("예외: " + String(e && e.message || e)));
