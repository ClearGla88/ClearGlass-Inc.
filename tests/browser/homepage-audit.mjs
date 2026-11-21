// Homepage audit: layout, navigation, keyboard and motion checks for index.html
// at 320, 375, 390, 768, 1024 and 1440 px, plus a no-JavaScript pass.
//
//   python3 -m http.server 8765 --bind 127.0.0.1 &      # repository root
//   node tests/browser/homepage-audit.mjs [screenshot-dir]
//
// BASE overrides the server (default http://127.0.0.1:8765/). If AXE points at
// axe-core's axe.min.js, WCAG 2.x A/AA rules also run (axe finds a subset of
// issues; a clean run is not a compliance claim). Exits 1 on any failure.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.BASE || 'http://127.0.0.1:8765/';
const SHOTS = process.argv[2] || '';
const AXE = process.env.AXE && fs.existsSync(process.env.AXE) ? fs.readFileSync(process.env.AXE, 'utf8') : '';
const WIDTHS = [320, 375, 390, 768, 1024, 1440];

const failures = [];
const notes = [];
const fail = (where, msg) => failures.push(`[${where}] ${msg}`);

const browser = await chromium.launch();

async function open(width, opts = {}) {
  const ctx = await browser.newContext({
    viewport: { width, height: width < 768 ? 844 : 900 },
    deviceScaleFactor: 1,
    javaScriptEnabled: opts.js !== false,
    reducedMotion: opts.reducedMotion || 'no-preference',
  });
  await ctx.route(/^https?:\/\/(?!127\.0\.0\.1|localhost)/, r => r.abort());
  const page = await ctx.newPage();
  const problems = [];
  page.on('response', r => { if (r.status() >= 400) problems.push(`${r.status()} ${r.url()}`); });
  page.on('pageerror', e => problems.push(`JS error: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') problems.push(`console: ${m.text()}`); });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  return { ctx, page, problems };
}

// Layout facts gathered in the page.
const layout = () => {
  const vw = document.documentElement.clientWidth;
  const out = { vw, scrollWidth: document.documentElement.scrollWidth, offscreen: [], clipped: [], small: [] };
  const visible = el => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (el.closest('.visually-hidden, [aria-hidden="true"], .backdrop')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) out.offscreen.push(`${el.tagName.toLowerCase()}.${el.className}`.slice(0, 80));
    if (/^(H1|H2|H3|P|A|SPAN|LI|LABEL|BUTTON)$/.test(el.tagName) && el.scrollWidth > el.clientWidth + 1 &&
        ['hidden', 'clip'].includes(getComputedStyle(el).overflowX)) out.clipped.push(el.textContent.trim().slice(0, 60));
  }
  for (const el of document.querySelectorAll('a[href], button, summary, input, textarea')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 24 || r.width < 24) out.small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.name || '').trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  const header = document.querySelector('.site-header').getBoundingClientRect();
  const h1 = document.querySelector('h1').getBoundingClientRect();
  out.headerBottom = header.bottom;
  out.h1Top = h1.top;
  out.h1InFirstViewport = h1.bottom <= innerHeight;
  const ids = new Set([...document.querySelectorAll('[id]')].map(n => n.id));
  out.brokenAnchors = [...document.querySelectorAll('a[href^="#"]')].map(a => a.getAttribute('href')).filter(h => h.length > 1 && !ids.has(h.slice(1)));
  out.h1Count = document.querySelectorAll('h1').length;
  const levels = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => +h.tagName[1]);
  out.headingSkips = levels.filter((l, i) => i > 0 && l > levels[i - 1] + 1).length;
  out.imgsWithoutAlt = [...document.querySelectorAll('img')].filter(i => !i.hasAttribute('alt')).length;
  out.imgsWithoutSize = [...document.querySelectorAll('img')].filter(i => !i.getAttribute('width') || !i.getAttribute('height')).length;
  return out;
};

for (const width of WIDTHS) {
  const where = `${width}px`;
  const { ctx, page, problems } = await open(width);
  problems.forEach(p => fail(where, p));
  const L = await page.evaluate(layout);
  if (L.scrollWidth > L.vw) fail(where, `horizontal overflow: scrollWidth ${L.scrollWidth} > ${L.vw}`);
  L.offscreen.forEach(o => fail(where, `element past viewport edge: ${o}`));
  L.clipped.forEach(c => fail(where, `clipped text: ${c}`));
  L.small.forEach(s => fail(where, `target under 24px: ${s}`));
  if (L.headerBottom > L.h1Top) fail(where, `header (bottom ${L.headerBottom}) overlaps h1 (top ${L.h1Top})`);
  if (!L.h1InFirstViewport) notes.push(`[${where}] h1 ends below the first viewport`);
  L.brokenAnchors.forEach(a => fail(where, `anchor with no target: ${a}`));
  if (L.h1Count !== 1) fail(where, `expected one h1, found ${L.h1Count}`);
  if (L.headingSkips) fail(where, `heading levels skip ${L.headingSkips} time(s)`);
  if (L.imgsWithoutAlt) fail(where, `${L.imgsWithoutAlt} img without alt`);
  if (L.imgsWithoutSize) fail(where, `${L.imgsWithoutSize} img without width/height`);

  // Every nav target lands below the sticky header, not under it. Smooth
  // scrolling is switched off here so positions are final, not mid-animation.
  await page.addStyleTag({ content: 'html{scroll-behavior:auto!important}' });
  for (const id of ['capabilities', 'approach', 'insights', 'about', 'contact']) {
    await page.evaluate(i => { location.hash = '#' + i; }, id);
    await page.waitForTimeout(80);
    const pos = await page.evaluate(i => ({
      header: document.querySelector('.site-header').getBoundingClientRect().bottom,
      heading: document.querySelector(`#${i} h2`).getBoundingClientRect().top,
    }), id);
    if (pos.heading < pos.header - 1) fail(where, `#${id} heading hidden under header (${pos.heading} < ${pos.header})`);
  }
  await page.evaluate(() => { history.replaceState(null, '', location.pathname); scrollTo({ top: 0, behavior: 'instant' }); });
  await page.waitForTimeout(100);

  if (SHOTS) {
    await page.screenshot({ path: path.join(SHOTS, `home-${width}.png`) });
    await page.screenshot({ path: path.join(SHOTS, `home-${width}-full.png`), fullPage: true });
  }

  if (AXE && (width === 390 || width === 1440)) {
    await page.addScriptTag({ content: AXE });
    const res = await page.evaluate(() => window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } }));
    res.violations.forEach(v => fail(`${where} axe`, `${v.id} (${v.impact}): ${v.nodes.length} node(s): ${v.nodes.map(n => n.target.join(' ')).slice(0, 3).join(', ')}`));
    notes.push(`[${where}] axe: ${res.violations.length} violations, ${res.passes.length} rules passed, ${res.incomplete.length} need manual review`);
  }
  await ctx.close();
}

// Mobile menu: open, focus in, Tab stays inside, Escape closes and returns focus.
{
  const where = 'menu@390';
  const { ctx, page } = await open(390);
  const toggle = page.locator('[data-menu-toggle]');
  await toggle.focus();
  await page.keyboard.press('Enter');
  if (await toggle.getAttribute('aria-expanded') !== 'true') fail(where, 'toggle did not set aria-expanded=true');
  if (!await page.locator('#mobile-nav').isVisible()) fail(where, 'panel not visible when open');
  const first = await page.evaluate(() => document.activeElement.textContent.trim());
  if (first !== 'Capabilities') fail(where, `focus not moved into menu (on "${first}")`);
  for (let i = 0; i < 12; i++) await page.keyboard.press('Tab');
  const inside = await page.evaluate(() => !!document.activeElement.closest('[data-mobile-nav], [data-menu-toggle]'));
  if (!inside) fail(where, 'Tab escaped the open menu');
  await page.keyboard.press('Escape');
  if (await toggle.getAttribute('aria-expanded') !== 'false') fail(where, 'Escape did not close the menu');
  if (!await page.evaluate(() => document.activeElement.matches('[data-menu-toggle]'))) fail(where, 'focus not returned to toggle after Escape');
  await toggle.click();
  await page.locator('#mobile-nav a[href="#approach"]').click();
  await page.waitForTimeout(400);
  if (await toggle.getAttribute('aria-expanded') !== 'false') fail(where, 'menu stayed open after choosing a link');
  if (!(await page.evaluate(() => location.hash)).endsWith('#approach')) fail(where, 'menu link did not navigate');
  await ctx.close();
}

// Sentinel Core: native disclosure, keyboard operable.
{
  const where = 'sentinel';
  const { ctx, page } = await open(390);
  const summary = page.locator('.sentinel__bar');
  await summary.focus();
  await page.keyboard.press('Enter');
  if (!await page.locator('details.sentinel').evaluate(d => d.open)) fail(where, 'Enter did not expand');
  if (!await page.locator('.sentinel__panel').isVisible()) fail(where, 'panel not visible when expanded');
  await page.keyboard.press('Space');
  if (await page.locator('details.sentinel').evaluate(d => d.open)) fail(where, 'Space did not collapse');
  const text = (await page.locator('.sentinel').innerText()).toLowerCase();
  for (const word of ['online', 'secure', 'protected']) if (text.includes(word)) fail(where, `claims "${word}"`);
  await ctx.close();
}

// Reduced motion: decorative animation and smooth scrolling stop.
{
  const where = 'reduced-motion';
  const { ctx, page } = await open(1440, { reducedMotion: 'reduce' });
  const m = await page.evaluate(() => ({
    sweep: getComputedStyle(document.querySelector('.radar__sweep')).animationName,
    dot: getComputedStyle(document.querySelector('.sentinel__dot')).animationName,
    scroll: getComputedStyle(document.documentElement).scrollBehavior,
  }));
  if (m.sweep !== 'none' || m.dot !== 'none') fail(where, `animations still set: ${JSON.stringify(m)}`);
  if (m.scroll !== 'auto') fail(where, `scroll-behavior is ${m.scroll}`);
  const { ctx: c2, page: p2 } = await open(1440);
  const running = await p2.evaluate(() => getComputedStyle(document.querySelector('.radar__sweep')).animationName);
  if (running === 'none') fail(where, 'radar animation missing when motion is allowed (check is not measuring anything)');
  await ctx.close(); await c2.close();
}

// Contact form: no endpoint means switched off and explained, never "sent".
{
  const where = 'contact';
  const { ctx, page } = await open(390);
  const endpoint = await page.locator('[data-contact-form]').getAttribute('data-endpoint');
  if (!endpoint) {
    if (!await page.locator('.contact-form__fields').evaluate(f => f.disabled)) fail(where, 'form usable with no endpoint');
    if (!(await page.locator('#contact-notice').innerText()).includes('not set up')) fail(where, 'missing "not set up" notice');
  }
  const body = (await page.locator('#contact').innerText()).toLowerCase();
  if (/message (was )?sent|thank you/.test(body)) fail(where, 'shows a sent/thank-you state on load');
  await ctx.close();
}

// No JavaScript: content and navigation still work.
{
  const where = 'no-js@390';
  const { ctx, page, problems } = await open(390, { js: false });
  problems.forEach(p => fail(where, p));
  if (await page.locator('[data-menu-toggle]').isVisible()) fail(where, 'menu button shown but cannot work without JS');
  if (!await page.locator('.mobile-nav__list a[href="#contact"]').isVisible()) fail(where, 'navigation links not reachable');
  const L = await page.evaluate(layout);
  if (L.scrollWidth > L.vw) fail(where, `horizontal overflow ${L.scrollWidth} > ${L.vw}`);
  await ctx.close();
}

await browser.close();
console.log(JSON.stringify({ failures, notes }, null, 2));
process.exit(failures.length ? 1 : 0);
