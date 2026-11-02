/* Synthetic Chromium system test; optional dev dependency only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const python = process.env.YTINTEL_PYTHON || 'python';
  const owner = 'o'.repeat(40), apiKey = 'a'.repeat(40);
  const generated = spawnSync(python, ['-c', 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'], {cwd:root,encoding:'utf8'});
  assert.equal(generated.status,0,'Python key generation failed');
  const output=generated.stdout;
  const temp = fs.mkdtempSync(path.join(require('node:os').tmpdir(),'ytintel-browser-'));
  const server = spawn(python, ['-m','uvicorn','tests.browser_server:create_browser_app','--factory','--host','127.0.0.1','--port','8000','--no-access-log','--log-level','warning'], {cwd:root,env:{...process.env,
    PYTHONPATH:[root,path.join(root,'src')].join(path.delimiter),YT_DB_PATH:path.join(temp,'browser.db'),
    YT_OWNER_KEY:owner,YT_API_KEY:apiKey,YT_ENCRYPTION_KEY:output.trim()}});
  server.stderr.on('data',data=>process.stderr.write(data));
  let browser;
  try {
    let ready=false;
    for(let i=0;i<100;i++) {try {const r=await fetch('http://localhost:8000/health'); if(r.ok){ready=true;break;}}catch{}
      await new Promise(r=>setTimeout(r,100));}
    assert(ready,'Server startup timeout');
    browser=await chromium.launch({headless:true,...(process.env.YTINTEL_CHROMIUM_PATH?{executablePath:process.env.YTINTEL_CHROMIUM_PATH,args:['--no-sandbox','--disable-dev-shm-usage']}: {})});
    const page=await browser.newPage({viewport:{width:1365,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://localhost:8000');
    await page.locator('#propose').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('YT_OWNER_KEY'));
    await page.locator('#key').fill('incorrect-key');
    await page.locator('#propose').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Owner key is missing or incorrect'));
    await page.locator('#key').fill(owner);
    // OAuth must not navigate away from the owner tab and erase its memory-only credential.
    await page.route('**/owner/oauth/start?write=false', route=>route.fulfill({
      status:200,contentType:'application/json',body:JSON.stringify({url:'http://localhost:8000/health'})}));
    const [oauthTab]=await Promise.all([
      page.waitForEvent('popup',{timeout:2500}),page.locator('#connect').click()
    ]);
    await oauthTab.waitForURL('**/health');
    assert.equal(await page.locator('#key').inputValue(),owner);
    assert.equal(page.url(),'http://localhost:8000/');
    assert.equal(await oauthTab.evaluate(()=>window.opener),null);
    await oauthTab.close();

    await page.locator('#reference').fill('aaaaaaaaaaa');
    await page.locator('#discover').click();
    await page.waitForFunction(()=>document.querySelector('#discovery').textContent.includes('Python'));
    await page.locator('#propose').click();
    await page.locator('#approve').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#approve').disabled);
    assert((await page.locator('#preview li').count())>0);
    // Cancelled dialog must leave the immutable draft pending.
    page.once('dialog',dialog=>dialog.dismiss());
    await page.locator('#approve').click();
    await page.waitForFunction(()=>!document.querySelector('#approve').disabled);
    assert((await page.locator('#preview').textContent()).includes('pending'));
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('#approve').click();
    await page.waitForFunction(()=>document.querySelector('#preview').textContent.includes('complete'));
    assert(await page.locator('#approve').isDisabled());
    await page.setViewportSize({width:390,height:844});
    assert(await page.locator('h1').isVisible());
    assert.deepEqual(errors,[]);
    console.log('PASS: Chromium OAuth tab/key preservation, missing/incorrect-key guidance, discovery, preview, cancelled confirmation, owner-approved synthetic test creation, replay-disabled UI, mobile viewport; no JS errors.');
  } finally {
    if(browser) await browser.close();
    server.kill();
    await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
    fs.rmSync(temp,{recursive:true,force:true});
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
