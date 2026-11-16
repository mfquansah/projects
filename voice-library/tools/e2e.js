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
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
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
