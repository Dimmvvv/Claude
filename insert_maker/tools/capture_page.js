#!/usr/bin/env node
// Снимок веб-страницы целиком в высоком разрешении (для листания и наездов).
//   node tools/capture_page.js URL out.png [width=1100] [scale=3]
// На Mac один раз: npm i -g playwright && npx playwright install chromium
const { chromium } = require('playwright');

(async () => {
  const [url, out, width = '1100', scale = '3'] = process.argv.slice(2);
  if (!url || !out) { console.error('usage: node tools/capture_page.js URL out.png [width] [scale]'); process.exit(1); }
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: +width, height: 1000 }, deviceScaleFactor: +scale,
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
  });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(4000);
  // прокрутка, чтобы подгрузились ленивые картинки
  const h = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < h; y += 800) { await page.evaluate(v => window.scrollTo(0, v), y); await page.waitForTimeout(150); }
  await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(800);
  // прячем липкие шапки и баннеры, чтобы они не повторялись на снимке
  await page.evaluate(() => {
    for (const el of document.querySelectorAll('body *')) {
      const s = getComputedStyle(el);
      if ((s.position === 'fixed' || s.position === 'sticky') && el.offsetHeight < innerHeight * 0.9)
        el.style.setProperty('display', 'none', 'important');
    }
  });
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  console.log('->', out);
})().catch(e => { console.error(e.message); process.exit(1); });
