/* Offline Chromium approval regression; this imports only the synthetic test app. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'ytintel-browser-'));
  const python = process.env.YTINTEL_PYTHON || 'python';
  const server = spawn(python, ['-m', 'uvicorn', 'tests.browser_server:create_browser_app',
    '--factory', '--host', '127.0.0.1', '--port', '8000', '--no-access-log', '--log-level', 'warning'],
    { cwd: root, env: { ...process.env, PYTHONPATH: [root, path.join(root, 'src')].join(path.delimiter),
      YT_DB_PATH: path.join(temp, 'browser.db') } });
  server.stderr.on('data', data => process.stderr.write(data));
  const base = 'http://localhost:8000';
  let browser;
  try {
    let fixture;
    for (let i = 0; i < 100; i++) {
      try { const response = await fetch(base + '/__fixture'); if (response.ok) { fixture = await response.json(); break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(fixture, 'Synthetic server startup timed out');
    const headers = { Authorization: 'Bearer ' + fixture.access_token, 'Content-Type': 'application/json' };
    const created = await fetch(base + '/api/drafts', { method: 'POST', headers,
      body: JSON.stringify({ topic: 'Python', total_seconds: 1800, max_seconds: 900 }) });
    assert.equal(created.status, 200);
    const draft = await created.json();
    browser = await chromium.launch({ headless: true, ...(process.env.YTINTEL_CHROMIUM_PATH ? {
      executablePath: process.env.YTINTEL_CHROMIUM_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] } : {}) });
    const context = await browser.newContext();
    await context.addCookies([{ name: 'yt_session', value: fixture.cookie, url: base,
      httpOnly: true, sameSite: 'Lax' }]);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    if(process.env.YTINTEL_PREVIEW_DIR) {
      fs.mkdirSync(process.env.YTINTEL_PREVIEW_DIR, {recursive:true});
      await page.goto(base + '/');
      await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'home-desktop.png'),fullPage:true});
    }
    const approval = base + '/approve/' + draft.id;
    await page.goto(approval);
    if(process.env.YTINTEL_PREVIEW_DIR) {
      fs.mkdirSync(process.env.YTINTEL_PREVIEW_DIR, {recursive:true});
      await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'approval-desktop.png'),fullPage:true});
    }
    assert((await page.locator('pre').textContent()).includes('pending'));
    if(process.env.YTINTEL_PREVIEW_DIR) {
      await page.setViewportSize({width:390,height:844});
      assert.equal(await page.locator('body').evaluate(body => body.scrollWidth > innerWidth), false);
      await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'approval-mobile.png'),fullPage:true});
      await page.setViewportSize({width:1365,height:1000});
    }
    assert.equal(await page.locator('input[name=csrf]').inputValue(), fixture.csrf);
    await page.locator('input[name=confirmation]').fill('yes');
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Confirm playlist in my account' }).click()]);
    assert((await page.locator('body').textContent()).includes('Type the displayed confirmation phrase'), (await page.locator('body').textContent()).slice(0,500));
    await page.goto(approval);
    await page.locator('input[name=confirmation]').fill('CREATE');
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Confirm playlist in my account' }).click()]);
    assert((await page.locator('body').textContent()).includes('complete'));
    assert(await page.getByRole('link', {name:'Open playlist on YouTube ↗'}).isVisible());
    if(process.env.YTINTEL_PREVIEW_DIR) await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'complete-desktop.png'),fullPage:true});
    const replay = await fetch(approval, { method: 'POST', headers: {
      Cookie: 'yt_session=' + fixture.cookie, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ csrf: fixture.csrf, confirmation: 'CREATE' }) });
    assert.equal(replay.status, 409);
    await page.goto(approval);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator('h1').isVisible());
    // A real form POST must follow its OAuth redirect to a different origin.
    const cancelled = await (await fetch(base + '/__consent_fixture')).json();
    await page.goto(base + cancelled.url);
    assert(await page.locator('#consent-dialog').evaluate(dialog => dialog.matches(':modal')));
    assert.equal(await page.locator('dialog').getAttribute('aria-labelledby'), 'consent-title');
    await page.keyboard.press('Escape');
    await page.waitForURL(url => url.hostname === '127.0.0.1' && url.searchParams.get('error') === 'access_denied');
    assert.equal(new URL(page.url()).searchParams.get('code'), null);
    const consent = await (await fetch(base + '/__consent_fixture')).json();
    const consentPage = await page.goto(base + consent.url);
    assert(consentPage.headers()['content-security-policy'].includes(new URL(consent.redirect_uri).origin));
    assert(consentPage.headers()['content-security-policy'].includes("script-src 'nonce-"));
    assert(await page.locator('#consent-dialog').evaluate(dialog => dialog.matches(':modal')));
    assert.equal(await page.locator('body').evaluate(body => body.scrollWidth > innerWidth), false);
    if(process.env.YTINTEL_PREVIEW_DIR) {
      fs.mkdirSync(process.env.YTINTEL_PREVIEW_DIR, {recursive:true});
      await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'consent-mobile.png')});
      await page.setViewportSize({width:1365,height:1000});
      await page.screenshot({path:path.join(process.env.YTINTEL_PREVIEW_DIR, 'consent-desktop.png')});
    }
    const cspErrors = [];
    page.on('console', msg => { if (msg.type() === 'error' && /Content Security Policy|form-action/i.test(msg.text())) cspErrors.push(msg.text()); });
    await page.getByRole('button', { name: 'Allow this client' }).click();
    try { await page.waitForURL('http://127.0.0.1:8000/__client_callback?**', { timeout: 4000 }); } catch { throw new Error(JSON.stringify({url:page.url().split('?')[0],body:(await page.locator('body').textContent()).slice(0,500),cspErrors})); }
    const code = new URL(page.url()).searchParams.get('code');
    assert(code, 'OAuth callback must contain a code');
    const token = await fetch(base + '/token', { method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({ grant_type: 'authorization_code', client_id: consent.client_id,
        code, code_verifier: consent.verifier, redirect_uri: consent.redirect_uri, resource: base + '/mcp/' }) });
    assert.equal(token.status, 200);
    // Explicit write enablement also follows a form redirect, this time to Google.
    const readOnly = await (await fetch(base + '/__write_fixture')).json();
    await context.addCookies([{ name: 'yt_session', value: readOnly.cookie, url: base,
      httpOnly: true, sameSite: 'Lax' }]);
    const nextDraft = await (await fetch(base + '/api/drafts', { method: 'POST', headers,
      body: JSON.stringify({ topic: 'Python', total_seconds: 1800, max_seconds: 900 }) })).json();
    let googleIntercepted = false;
    const cdp = await context.newCDPSession(page);
    await cdp.send('Fetch.enable', { patterns: [{ urlPattern: 'https://accounts.google.com/*' }] });
    cdp.on('Fetch.requestPaused', async event => {
      googleIntercepted = true;
      await cdp.send('Fetch.fulfillRequest', { requestId: event.requestId, responseCode: 200,
        responseHeaders: [{name:'Content-Type', value:'text/html'}],
        body: Buffer.from('<p>Synthetic Google write consent</p>').toString('base64') });
    });
    await page.goto(base + '/approve/' + nextDraft.id);
    await page.getByRole('button', {name: 'Enable playlist writes with the same Google account'}).click();
    try { await page.waitForURL(url => url.origin === 'https://accounts.google.com', {timeout:4000}); } catch { throw new Error(JSON.stringify({stage:'Google write',url:page.url().split('?')[0],googleIntercepted,cspErrors})); }
    assert((await page.locator('body').textContent()).includes('Synthetic Google write consent'));
    assert.deepEqual(cspErrors, []);
    assert.deepEqual(errors, []);
    console.log('PASS: Chromium own-session approval, CSRF form, typed confirmation, no write on wrong phrase, complete playlist, replay refusal, mobile page, native modal/keyboard cancellation, cross-origin AI consent callback/token exchange and Google write consent; no CSP violations or JavaScript errors.');
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    fs.rmSync(temp, { recursive: true, force: true });
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
