#!/usr/bin/env node
/**
 * UnSkein mori - CDP/Playwright 즉석 조작 CLI.
 *
 * 전제: scripts/start.ps1 로 Chrome이 9222 포트에 떠 있어야 함.
 *       playwright 패키지가 node_modules 에 있어야 함 (walk-up 발견).
 *
 * 사용:
 *   node remote.js tabs
 *   node remote.js navigate <url> [--tab=<sel>] [--new]
 *   node remote.js shot <name> [--tab=<sel>] [--full]
 *   node remote.js click <selector> [--tab=<sel>]
 *   node remote.js type <selector> <text> [--tab=<sel>]   # React 호환 native setter 사용
 *   node remote.js eval "<js expr>" [--tab=<sel>]
 *   node remote.js wait <selector> [--tab=<sel>] [--ms=10000]
 *   node remote.js attrs <selector> [--tab=<sel>]         # DOM 속성 검사
 *   node remote.js collect [<ms>] [--tab=<sel>]           # 콘솔 에러 + 네트워크 실패 수집 (기본 5000ms)
 *   node remote.js close --tab=<sel>
 *
 * 탭 선택:
 *   --tab=<idx>     인덱스 (tabs 명령으로 확인)
 *   --tab=<url부분>  URL 부분문자열 매칭
 *   기본값          가장 최근 탭 (마지막 탭)
 *
 * collect 권장값:
 *   3000  : 정적 화면 빠른 확인
 *   5000  : 일반 페이지 (기본값)
 *   10000 : 자동 갱신/비동기 요청 많은 화면
 *
 * shot 저장 위치: scripts/shots/<name>.png (디렉토리 자동 생성)
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SHOT_DIR = path.join(__dirname, 'shots');
if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

const argv = process.argv.slice(2);
const cmd = argv[0];

function getOpt(name, def) {
    const m = argv.find(a => a.startsWith(`--${name}=`));
    if (!m) return def;
    return m.slice(name.length + 3);
}
function hasFlag(name) {
    return argv.includes(`--${name}`);
}
function positional() {
    return argv.filter(a => !a.startsWith('--'));
}

async function getBrowser() {
    try {
        return await chromium.connectOverCDP('http://127.0.0.1:9222');
    } catch (e) {
        console.error('[ERR] CDP 연결 실패. start.ps1 먼저 실행하세요.');
        console.error(`     ${e.message}`);
        process.exit(1);
    }
}

function pickPage(context, tabSelector) {
    const pages = context.pages();
    if (pages.length === 0) return null;
    if (tabSelector === undefined || tabSelector === '') return pages[pages.length - 1];

    const idx = parseInt(tabSelector, 10);
    if (!isNaN(idx) && idx >= 0 && idx < pages.length) return pages[idx];

    const matched = pages.find(p => p.url().includes(tabSelector));
    if (matched) return matched;

    console.error(`[ERR] 탭 매칭 실패: ${tabSelector}`);
    pages.forEach((p, i) => console.error(`  [${i}] ${p.url()}`));
    process.exit(2);
}

const COMMANDS = {
    async tabs(context) {
        const pages = context.pages();
        console.log(`[INFO] 컨텍스트 ${context.browser().contexts().length}개, 탭 ${pages.length}개`);
        for (let i = 0; i < pages.length; i++) {
            const url = pages[i].url();
            const title = await pages[i].title().catch(() => '?');
            console.log(`  [${i}] ${url}`);
            console.log(`       ${title}`);
        }
    },

    async navigate(context) {
        const [, url] = positional();
        if (!url) { console.error('Usage: navigate <url>'); process.exit(1); }
        let page;
        if (hasFlag('new')) {
            page = await context.newPage();
            console.log('[OK] 새 탭 생성');
        } else {
            page = pickPage(context, getOpt('tab'));
            if (!page) page = await context.newPage();
        }
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        console.log(`[OK] navigated → ${page.url()}`);
        console.log(`     title: ${await page.title()}`);
    },

    async shot(context) {
        const [, name] = positional();
        if (!name) { console.error('Usage: shot <name> [--full]'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));
        if (!page) { console.error('[ERR] 탭 없음'); process.exit(1); }
        const file = path.join(SHOT_DIR, `${name}.png`);
        await page.screenshot({ path: file, fullPage: hasFlag('full') });
        console.log(`[OK] ${file}`);
    },

    async click(context) {
        const [, selector] = positional();
        if (!selector) { console.error('Usage: click <selector>'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));
        await page.click(selector, { timeout: 10000 });
        console.log(`[OK] clicked ${selector}`);
    },

    async type(context) {
        const [, selector, ...rest] = positional();
        const text = rest.join(' ');
        if (!selector || !text) { console.error('Usage: type <selector> <text>'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));

        // React controlled inputs do not react to fill(). Use native setter + input event.
        await page.evaluate(({ sel, val }) => {
            const el = document.querySelector(sel);
            if (!el) throw new Error(`selector not found: ${sel}`);
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }, { sel: selector, val: text });
        console.log(`[OK] typed into ${selector}`);
    },

    async eval(context) {
        const [, ...exprParts] = positional();
        const expr = exprParts.join(' ');
        if (!expr) { console.error('Usage: eval "<js>"'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));
        const result = await page.evaluate(expr);
        console.log(JSON.stringify(result, null, 2));
    },

    async wait(context) {
        const [, selector] = positional();
        if (!selector) { console.error('Usage: wait <selector>'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));
        const ms = parseInt(getOpt('ms', '10000'), 10);
        await page.waitForSelector(selector, { timeout: ms });
        console.log(`[OK] selector appeared: ${selector}`);
    },

    async attrs(context) {
        const [, selector] = positional();
        if (!selector) { console.error('Usage: attrs <selector>'); process.exit(1); }
        const page = pickPage(context, getOpt('tab'));
        const result = await page.evaluate((sel) => {
            const els = Array.from(document.querySelectorAll(sel));
            return els.map((el, i) => {
                const rect = el.getBoundingClientRect();
                return {
                    i,
                    tag: el.tagName,
                    id: el.id || undefined,
                    className: el.className?.toString?.().slice(0, 100) || undefined,
                    text: (el.innerText || el.value || '').slice(0, 100),
                    visible: rect.width > 0 && rect.height > 0,
                    disabled: el.disabled,
                    href: el.href,
                    name: el.name,
                    type: el.type,
                    placeholder: el.placeholder?.slice(0, 50),
                };
            });
        }, selector);
        console.log(JSON.stringify(result, null, 2));
    },

    async collect(context) {
        const ms = parseInt(positional()[1] || '5000', 10);
        const page = pickPage(context, getOpt('tab'));
        if (!page) { console.error('[ERR] 탭 없음'); process.exit(1); }

        const consoleErrors = [];
        const consoleWarnings = [];
        const pageErrors = [];
        const networkFails = [];

        const consoleHandler = (msg) => {
            const t = msg.type();
            const text = msg.text();
            if (t === 'error') consoleErrors.push(text);
            else if (t === 'warning') consoleWarnings.push(text);
        };
        const pageErrorHandler = (err) => pageErrors.push(err.message);
        const reqFailedHandler = (req) => {
            networkFails.push({
                kind: 'requestfailed',
                url: req.url(),
                method: req.method(),
                failure: req.failure()?.errorText,
            });
        };
        const responseHandler = (resp) => {
            const status = resp.status();
            if (status >= 400) {
                networkFails.push({
                    kind: 'http_error',
                    url: resp.url(),
                    method: resp.request().method(),
                    status,
                });
            }
        };

        page.on('console', consoleHandler);
        page.on('pageerror', pageErrorHandler);
        page.on('requestfailed', reqFailedHandler);
        page.on('response', responseHandler);

        console.error(`[INFO] Collecting for ${ms}ms on tab ${page.url()}`);
        await new Promise((r) => setTimeout(r, ms));

        page.off('console', consoleHandler);
        page.off('pageerror', pageErrorHandler);
        page.off('requestfailed', reqFailedHandler);
        page.off('response', responseHandler);

        console.log(JSON.stringify({
            durationMs: ms,
            url: page.url(),
            consoleErrors,
            consoleWarnings: consoleWarnings.slice(-20),
            pageErrors,
            networkFails,
            summary: {
                errors: consoleErrors.length + pageErrors.length,
                warnings: consoleWarnings.length,
                netFails: networkFails.length,
            },
        }, null, 2));
    },

    async close(context) {
        const page = pickPage(context, getOpt('tab'));
        const url = page.url();
        await page.close();
        console.log(`[OK] closed: ${url}`);
    },
};

(async () => {
    if (!cmd || cmd === '-h' || cmd === '--help' || !COMMANDS[cmd]) {
        console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 30).join('\n'));
        process.exit(cmd ? 1 : 0);
    }

    const browser = await getBrowser();
    const context = browser.contexts()[0];
    if (!context) { console.error('[ERR] 컨텍스트 없음'); process.exit(1); }

    try {
        await COMMANDS[cmd](context);
    } catch (e) {
        console.error(`[ERR] ${cmd} 실패: ${e.message}`);
        process.exit(1);
    } finally {
        await browser.close().catch(() => {});
    }
})();
