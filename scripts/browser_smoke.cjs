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
    const approval = base + '/approve/' + draft.id;
    await page.goto(approval);
    assert((await page.locator('pre').textContent()).includes('pending'));
    assert.equal(await page.locator('input[name=csrf]').inputValue(), fixture.csrf);
    await page.locator('input[name=confirmation]').fill('yes');
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Confirm playlist in my account' }).click()]);
    assert((await page.locator('body').textContent()).includes('confirmation_required'), (await page.locator('body').textContent()).slice(0,500));
    await page.goto(approval);
    await page.locator('input[name=confirmation]').fill('CREATE');
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Confirm playlist in my account' }).click()]);
    assert((await page.locator('body').textContent()).includes('complete'));
    const replay = await fetch(approval, { method: 'POST', headers: {
      Cookie: 'yt_session=' + fixture.cookie, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ csrf: fixture.csrf, confirmation: 'CREATE' }) });
    assert.equal(replay.status, 409);
    await page.goto(approval);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator('h1').isVisible());
    assert.deepEqual(errors, []);
    console.log('PASS: Chromium own-session approval, CSRF form, typed confirmation, no write on wrong phrase, complete playlist, replay refusal, mobile page; no JavaScript errors.');
  } finally {
    if (browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    fs.rmSync(temp, { recursive: true, force: true });
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
