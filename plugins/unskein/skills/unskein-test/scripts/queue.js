#!/usr/bin/env node
/*
 * queue.js — UnSkein TESTER 큐 클라이언트 (화면검증 자율 루프의 HTTP 절반).
 *
 * TESTER(kind=tester 모리 토큰)가 test 상태 작업을 선점(claim)하고, 검증 중 lease 를
 * 유지(heartbeat)하고, 결과(payload['test'] + result_doc)를 보고(report)하고, 판단이
 * 필요하면 질문(question)한다. CDP 화면조작은 remote.js 가, 이 스크립트는 서버 왕복만 맡는다.
 *
 * 인증/연결(비밀 무잔존 — 값은 환경변수로만, 화면 출력 금지):
 *   UNSKEIN_API_BASE   예: https://unskein.mupai.studio   (기본 http://127.0.0.1:8000)
 *   UNSKEIN_MORI_TOKEN 테스터 토큰(kind=tester). 없으면 즉시 오류로 멈춘다(fallback 금지).
 *
 * 서브커맨드:
 *   scope                                     내가 담당(watch)할 수 있는 사이트 목록(GET /api/mori/scope)
 *   claim [--business=<이름>] [--project=<이름>]  test 작업 1건 선점. 없으면 {"claimed":false}
 *   heartbeat <task_id>                        lease 갱신(긴 검증 중 주기적으로)
 *   report <task_id> --status=inspect|plan [--summary=<s>] [--doc=<file>] [--payload=<file>]
 *                                              화면검증 결과 보고. inspect=PASS, plan=FAIL 롤백.
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

const API_BASE = (process.env.UNSKEIN_API_BASE || "http://127.0.0.1:8000").replace(/\/+$/, "");
const TOKEN = process.env.UNSKEIN_MORI_TOKEN || "";

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
    const r = await api("POST", "/api/mori/claim", body);
    if (!r || r.status !== 200) return die("claim 실패", { status: r && r.status, detail: r && r.data });
    // task 에 tested_url(검증 대상 사이트)·plan_doc(수용 기준)·subtree 가 실려 온다.
    return out({ ok: true, claimed: !!r.data.claimed, task: r.data.task || null });
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
    const status = args.status;
    if (!["inspect", "plan"].includes(status)) {
      return die("report --status 는 inspect(PASS) 또는 plan(FAIL 롤백) 이어야 합니다");
    }
    const body = { status, stage: "test" };
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
    return out({ ok: true, status });
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
