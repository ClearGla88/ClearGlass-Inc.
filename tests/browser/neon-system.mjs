// Browser contract for the Neon Glass System (assets/css + assets/js).
//
//   python3 -m http.server 8000 &            # from the repository root
//   npm i --no-save playwright               # or use a pre-installed copy
//   node tests/browser/neon-system.mjs       # BASE=http://127.0.0.1:8000/ by default
//
// Builds its own fixture page that loads the real system files from BASE, so
// it tests the shipped CSS/JS rather than a copy. Exits 1 on any failure.
import { chromium } from 'playwright';

const BASE = (process.env.BASE || 'http://127.0.0.1:8000/').replace(/\/?$/, '/');
const FIXTURE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="${BASE}assets/css/cg-design-system.css">
<link rel="stylesheet" href="${BASE}assets/css/glass.css">
<link rel="stylesheet" href="${BASE}assets/css/future-buttons.css">
<link rel="stylesheet" href="${BASE}assets/css/cinematic-motion.css">
<style>body{margin:0;background:#05070f;color:#e9eeff;font-family:system-ui}section{padding:24px}</style>
</head><body>
<section class="cg-aurora cg-grid-bg">
  <h1 class="cg-neon-title" id="title">Neon</h1>
  <div class="cg-glass cg-glass--pad" id="glass">glass</div>
  <a href="#x" class="cg-glass-elevated cg-glass--pad" id="elevated">elevated</a>
  <div class="cg-scanline cg-scanline--sweep cg-neon-border cg-neon-border--animated" id="scan" style="height:80px;border-radius:18px">scan</div>
  <button class="cg-neon-button" id="btn">Primary</button>
  <span class="cg-status-live" id="live">Live</span>
  <span id="frame" style="display:inline-block;width:54px;height:54px;border-radius:50%"><img id="logo" src="${BASE}assets/images/clearglass-logo.png?missing" alt="ClearGlass logo"></span>
</section>
<div style="height:2400px"></div>
<article class="cg-reveal" id="reveal" style="height:120px">reveal</article>
<script src="${BASE}assets/js/cg-design-system.js"></script>
<script src="${BASE}assets/js/cinematic-motion.js"></script>
</body></html>`;

const failures = [];
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures.push(name);
};

const browser = await chromium.launch();

async function open(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...opts });
  const page = await ctx.newPage();
  // Serve the fixture from BASE's own origin: Chrome's Private Network Access
  // blocks a made-up public origin from loading assets on 127.0.0.1.
  const url = BASE + '__neon_system_fixture.html';
  await page.route(url, r => r.fulfill({ contentType: 'text/html', body: FIXTURE }));
  await page.goto(url, { waitUntil: 'load' });
  await page.waitForTimeout(400);
  return { ctx, page };
}

{
  const { ctx, page } = await open();
  const s = await page.evaluate(() => {
    const cs = (sel, pseudo) => getComputedStyle(document.querySelector(sel), pseudo);
    return {
      glassBlur: cs('#glass').backdropFilter,
      elevatedBlur: cs('#elevated').backdropFilter,
      titleShadow: cs('#title').textShadow,
      btnHeight: document.querySelector('#btn').getBoundingClientRect().height,
      liveAnim: cs('#live', '::after').animationName,
      borderAnim: cs('#scan', '::after').animationName,
      frameMarked: document.querySelector('#frame').hasAttribute('data-cg-mark-fallback'),
      logoOpacity: cs('#logo').opacity,
      revealOpacity: cs('#reveal').opacity,
      ready: document.documentElement.classList.contains('cg-reveal-ready'),
    };
  });
  check('glass blur is 12px', /blur\(12px\)/.test(s.glassBlur), s.glassBlur);
  check('elevated glass blur is capped at 18px', /blur\(18px\)/.test(s.elevatedBlur), s.elevatedBlur);
  check('neon title has a glow', s.titleShadow !== 'none');
  check('neon button is a 44px touch target', s.btnHeight >= 44, String(s.btnHeight));
  check('live status pulses', s.liveAnim === 'cg-ping', s.liveAnim);
  check('animated neon border sweeps', s.borderAnim === 'cg-angle-sweep', s.borderAnim);
  check('missing brand logo gets a monogram frame', s.frameMarked);
  check('missing image alt text is hidden visually', s.logoOpacity === '0', s.logoOpacity);
  check('below-fold reveal starts hidden', s.ready && s.revealOpacity === '0', s.revealOpacity);

  await page.locator('#reveal').scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => getComputedStyle(document.querySelector('#reveal')).opacity);
  check('reveal shows once scrolled into view', after === '1', after);

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press('Tab');
  let focused = await page.evaluate(() => document.activeElement && document.activeElement.id);
  for (let i = 0; i < 4 && focused !== 'btn'; i++) {
    await page.keyboard.press('Tab');
    focused = await page.evaluate(() => document.activeElement && document.activeElement.id);
  }
  const ring = await page.evaluate(() => { const c = getComputedStyle(document.activeElement); return `${c.outlineStyle} ${c.outlineWidth}`; });
  check('keyboard focus on neon button shows a 2px ring', focused === 'btn' && ring === 'solid 2px', `${focused} ${ring}`);

  await page.evaluate(() => document.documentElement.setAttribute('data-cg-hidden', ''));
  const paused = await page.evaluate(() => getComputedStyle(document.querySelector('#live'), '::after').animationPlayState);
  check('hidden tab pauses animation', paused === 'paused', paused);
  await ctx.close();
}

{
  const { ctx, page } = await open({ reducedMotion: 'reduce' });
  const s = await page.evaluate(() => ({
    count: getComputedStyle(document.querySelector('#live'), '::after').animationIterationCount,
    reveal: getComputedStyle(document.querySelector('#reveal')).opacity,
  }));
  check('reduced motion stops the pulse loop', s.count === '1', s.count);
  check('reduced motion never hides reveal content', s.reveal === '1', s.reveal);
  await ctx.close();
}

{
  const { ctx, page } = await open({ viewport: { width: 320, height: 700 } });
  const pan = await page.evaluate(() => { window.scrollTo(9999, 0); return window.scrollX; });
  check('no horizontal pan at 320px', pan === 0, String(pan));
  await ctx.close();
}

await browser.close();
if (failures.length) { console.log(`\n${failures.length} failure(s)`); process.exit(1); }
console.log('\nall neon-system checks passed');
