// End-to-end browser test of every screen against tools/demo_server.py. Run: node tools/e2e.js
const { chromium } = require('playwright');
const fs = require('fs'), os = require('os'), path = require('path');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vl-e2e-'));
fs.writeFileSync(path.join(tmp, 'bath.m4a'), 'baby giggling in the bath tub\n');
fs.writeFileSync(path.join(tmp, 'taxes.m4a'), 'a quick reminder about taxes and receipts\n');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: false });
  const page = await ctx.newPage();
  const errors = [];
  let allow400 = false;  // only around a step that deliberately triggers a 400
  page.on('console', m => { if (m.type() === 'error' && !(allow400 && /400/.test(m.text()))) errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  const log = (k, v) => console.log(k.padEnd(34), v);
  const sane = async (where) => {
    const bad = await page.evaluate(() => (document.body.innerText.match(/\b(null|undefined|NaN)\b|\[object/g) || []));
    if (bad.length) { console.log('STRAY TEXT on ' + where + ': ' + JSON.stringify(bad)); errors.push('stray text on ' + where); }
  };

  await page.goto('http://127.0.0.1:8798/');
  await page.waitForSelector('.row');
  log('library rows', await page.$$eval('.row', e => e.length));
  log('placeholder', await page.getAttribute('#q', 'placeholder'));
  log('searchbox height', await page.$eval('.searchbox', e => Math.round(e.getBoundingClientRect().height)));
  log('try links', await page.$$eval('.tryline a', e => e.length));
  log('hero headline', await page.textContent('.hero h1'));
  log('collection cards (top 4)', await page.$$eval('.cards a .t', e => e.map(x => x.textContent).join(', ')));
  log('sidebar collections (all)', await page.$$eval('.cols a .name', e => e.length));
  log('numbered rows', await page.$$eval('.row .num', e => e.slice(0, 3).map(x => x.textContent).join(',')));
  await page.screenshot({ path: path.join(tmp, '1-library.png') });
  await sane('library');

  // instant results while typing, then Enter -> full answer
  await page.fill('#q', 'grocery');
  await page.waitForFunction(() => [...document.querySelectorAll('h2.eyebrow')].some(e => e.textContent.includes('Instant')));
  log('instant heading', await page.textContent('h2.eyebrow.ul'));
  await page.press('#q', 'Enter');
  await page.waitForSelector('.verdict');
  await page.waitForSelector('.result');
  log('verdict', await page.textContent('.verdict h1'));
  log('first label', await page.textContent('.result .label'));
  log('snippet marked words', await page.$$eval('.result mark', e => e.map(x => x.textContent).join(',')));
  log('snippet time chip', await page.textContent('.result .snip .chip'));
  await page.screenshot({ path: path.join(tmp, '2-search.png'), fullPage: true });
  await sane('search');

  // filters
  await page.selectOption('select[aria-label="Collection"]', 'Work & projects');
  log('results after collection filter', await page.$$eval('.result', e => e.length));
  await page.selectOption('select[aria-label="Collection"]', '');

  // open the first result at its timestamp
  await page.click('.result .snip .chip');
  await page.waitForSelector('.ntitle');
  log('note title', await page.textContent('.ntitle'));
  await page.waitForFunction(() => document.querySelectorAll('.bars i').length === 96);
  await page.waitForTimeout(600);
  const hs = await page.$$eval('.bars i', e => e.map(x => parseInt(x.style.height)));
  log('waveform bar heights vary', `${Math.min(...hs)}..${Math.max(...hs)}px`);
  log('sound dots', await page.$$eval('.mark-dot', e => e.map(x => x.title).join('; ')));
  log('transcript rows', await page.$$eval('.seg', e => e.length));
  await page.screenshot({ path: path.join(tmp, '3-note.png'), fullPage: true });
  await sane('note');
  // transcript click seeks; play button toggles
  await page.click('.seg:nth-child(4) button.t');
  await page.waitForTimeout(500);
  log('time after clicking 0:09 row', await page.textContent('.time'));
  log('active segment', (await page.textContent('.seg.active span')).slice(0, 30));
  await page.click('.big');
  await page.waitForTimeout(200);
  log('play button label', await page.getAttribute('.big', 'aria-label'));
  // transcript find
  await page.fill('.transhead input', 'oats');
  log('rows after find "oats"', await page.$$eval('.seg:not(:empty)', e => e.length));
  await page.fill('.transhead input', '');

  // edit title + add a tag
  await page.click('text=Edit');
  await page.fill('input.edit.title', 'A grocery list that learns');
  await page.click('button:has-text("Save")');
  await page.waitForSelector('.ntitle:has-text("A grocery list that learns")');
  log('edited note line', await page.textContent('.small'));
  await page.click('.tagadd');
  await page.fill('.tagin', 'shopping');
  await page.press('.tagin', 'Enter');
  await page.waitForSelector('.tag:has-text("shopping")');
  log('tags', await page.$$eval('.tag', e => e.map(x => x.textContent.trim()).join(', ')));
  log('details rows', await page.$$eval('dl.det dt', e => e.map(x => x.textContent).join(',')));
  log('related', await page.$$eval('.related a b', e => e.length));

  // collection via sidebar
  await page.click('.cols a:has-text("Family memories")');
  await page.waitForSelector('.row');
  log('collection rows', await page.$$eval('.row', e => e.length));

  // attention: accept suggestion, archive from review, restore
  await page.click('.attn');
  await page.waitForSelector('h1:has-text("Needs attention")');
  await page.screenshot({ path: path.join(tmp, '4-attention.png'), fullPage: true });
  await sane('attention');
  log('attention sections', await page.$$eval('section h2', e => e.map(x => x.textContent).join(' | ')));
  await page.click('button:has-text("Accept")');
  await page.waitForTimeout(500);
  log('collections after accept', await page.$$eval('.cols a span:first-child', e => e.map(x => x.textContent).join(', ')));
  await page.click('button:has-text("Archive")');
  await page.waitForTimeout(500);
  log('archived section present', (await page.$$('h2:has-text("Archived")')).length);
  await page.click('button:has-text("Restore")');
  await page.waitForTimeout(400);

  // import via file chooser
  await page.click('.nav a:has-text("Import")');
  await page.waitForSelector('.drop');
  await page.screenshot({ path: path.join(tmp, '5-import.png') });
  await sane('import');
  await page.setInputFiles('input[type=file]:not([webkitdirectory])', [path.join(tmp, 'bath.m4a'), path.join(tmp, 'taxes.m4a')]);
  await page.waitForSelector('.frow');
  await page.waitForSelector('.banner', { timeout: 20000 });
  log('import rows', await page.$$eval('.frow .fstate', e => e.map(x => x.textContent.trim().slice(0, 50)).join(' || ')));
  log('banner', (await page.textContent('.banner p')).slice(0, 60));
  await page.screenshot({ path: path.join(tmp, '6-import-done.png'), fullPage: true });
  await sane('import-done');
  log('library count after import', await page.$eval('.cols', e => e.textContent));

  // dragging out of Voice Memos delivers nothing to a browser: the page must say so, not silently reset
  await page.evaluate(() => { const el = document.querySelector('.drop'); const dt = new DataTransfer(); el.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); });
  await page.waitForSelector('.sysnote:has-text("Nothing came through")');
  log('empty drop message', 'shown');
  log('voice memos row', (await page.textContent('section[aria-label="Import from this computer"]')).includes('30 recordings found on this computer'));
  // import a folder by path: files are read in place and the originals must survive
  const folder = path.join(tmp, 'vm'); fs.mkdirSync(folder);
  fs.writeFileSync(path.join(folder, 'one.m4a'), 'baby babbling at the park');
  fs.writeFileSync(path.join(folder, 'two.m4a'), 'groceries milk eggs bread');
  await page.fill('input[aria-label="Folder path on this computer"]', folder);
  await page.click('button:has-text("Import this folder")');
  await page.waitForSelector('.frow:has-text("one.m4a") .fstate:has-text("Saved as")', { timeout: 20000 });
  await page.waitForSelector('.frow:has-text("two.m4a") .fstate:has-text("Saved as")', { timeout: 20000 });
  log('folder import', (await page.$$eval('.frow .fstate', e => e.map(x => x.textContent.trim().slice(0, 28)).join(' || '))));
  log('originals kept', fs.existsSync(path.join(folder, 'one.m4a')) && fs.existsSync(path.join(folder, 'two.m4a')));
  allow400 = true;
  await page.fill('input[aria-label="Folder path on this computer"]', path.join(tmp, 'nowhere'));
  await page.click('button:has-text("Import this folder")');
  await page.waitForSelector('.sysnote:has-text("isn\'t a folder")');
  log('bad path message', 'shown');
  allow400 = false;
  await sane('import-folder');

  // test batch: the 25 newest, timed, with an estimate for the rest; then import the remaining 5
  const total = async () => (await (await fetch('http://127.0.0.1:8798/api/home')).json()).total_notes;
  const until = async (fn, ms = 90000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await new Promise(r => setTimeout(r, 300)); } return false; };
  const base = await total();
  await page.click('button:has-text("Try a test batch (25 newest)")');
  await page.waitForSelector('section[aria-label="Test batch results"]', { timeout: 90000 });
  const reportText = await page.textContent('section[aria-label="Test batch results"]');
  log('batch imported newest 25 only', (await total()) - base === 25);
  log('report says 25 processed', /25 recordings processed/.test(reportText));
  log('report has time, Claude usage, estimate', /Time:/.test(reportText) && /Claude:/.test(reportText) && /The other 5 recordings/.test(reportText));
  log('report text', reportText.replace(/\s+/g, ' ').slice(0, 330));
  await page.screenshot({ path: path.join(tmp, '8-batch-report.png'), fullPage: true });
  await sane('batch-report');
  if ((await total()) - base !== 25) errors.push('test batch did not import exactly 25');
  await page.click('button:has-text("Import the remaining 5")');
  const rest = await until(async () => (await total()) - base === 30);
  log('remaining 5 imported', rest);
  if (!rest) errors.push('remaining recordings were not imported');
  await page.waitForFunction(() => !document.querySelector('section[aria-label="Test batch results"]') || true);

  // automatic sync (its switch is shelved, so it is driven through the API): the sidebar shows status; nothing is imported twice
  const post = (url, body) => page.evaluate(async ([u, b]) => (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).status, [url, body]);
  const before = await total();
  log('no sync switch on the Import screen', (await page.$$('text=Keep in sync with Voice Memos')).length === 0 && (await page.$$('.sync')).length === 0);
  log('turn sync on (API)', await post('/api/sync/settings', { enabled: true }));
  await page.reload();
  await page.waitForFunction(() => /Synced/.test(document.querySelector('.sync')?.textContent || ''), null, { timeout: 60000 });
  log('sidebar sync status', (await page.textContent('.sync')).trim());
  log('already-imported files not duplicated', (await total()) === before);
  const VM = path.join(__dirname, '.demo', 'voicememos');
  fs.writeFileSync(path.join(VM, '20261116 100000-NEW.m4a'), 'a quick note about the dentist appointment');
  await page.click('.sync button:has-text("Sync now")');
  const second = await until(async () => (await total()) >= before + 1);
  log('new recording picked up', second && (await total()) - before === 1);
  if (!second) errors.push('sync did not pick up the new recording');
  await new Promise(r => setTimeout(r, 4000));   // another check cycle runs: nothing may be imported twice
  log('no duplicates after more checks', (await total()) - before === 1);
  log('originals untouched', fs.readdirSync(VM).length === 31);
  await post('/api/sync/settings', { enabled: false });
  await page.reload();
  await page.waitForSelector('.cols');
  log('sync line gone when off', (await page.$$('.sync')).length === 0);
  await sane('sync');

  // phone width
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto('http://127.0.0.1:8798/#/');
  await page.waitForSelector('.row');
  log('horizontal scroll at 390px', await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth));
  await page.screenshot({ path: path.join(tmp, '7-phone.png'), fullPage: true });
  log('ERRORS', JSON.stringify(errors));
  console.log('screenshots saved in', tmp);
  if (errors.length) process.exitCode = 1;
  await browser.close();
})().catch(e => { console.error('FAILED:', e.message.split('\n').slice(0, 6).join('\n')); process.exit(1); });
