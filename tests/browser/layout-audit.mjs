// Site-wide layout audit: same-origin 404s, JS errors, horizontal pan, text
// pushed past the right edge, backdrop-blur load, running infinite animations.
//
//   python3 -m http.server 8765 --bind 127.0.0.1 &      # repository root
//   node tests/browser/layout-audit.mjs out.json 375 [page.html ...]
//
// BASE overrides the server (default http://127.0.0.1:8765/). Third-party
// requests are aborted so results do not depend on CDNs. "clippedText" skips
// screen-reader-only text, fixed overlays and containers that intentionally
// scroll or truncate, so what it reports is content a visitor cannot reach.
import { chromium } from 'playwright';
import fs from 'node:fs';

const [, , out, widthArg, ...only] = process.argv;
const width = Number(widthArg || 375);
const root = process.cwd();
const pages = only.length ? only : fs.readdirSync(root).filter(f => f.endsWith('.html')).sort();
const BASE = process.env.BASE || 'http://127.0.0.1:8765/';

const browser = await chromium.launch();
const results = [];
const CONC = 6;
let idx = 0;

async function worker() {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 1 });
  // Block third-party network: proxy denies it anyway; keeps timing stable.
  await ctx.route(/^https?:\/\/(?!127\.0\.0\.1)/, r => r.abort());
  while (idx < pages.length) {
    const p = pages[idx++];
    const page = await ctx.newPage();
    const missing = new Set(); const consoleErr = []; const pageErr = [];
    page.on('response', r => { if (r.url().startsWith(BASE) && r.status() >= 400) missing.add(r.url().replace(BASE, '/')); });
    page.on('console', m => { if (m.type() === 'error') consoleErr.push(m.text().slice(0, 160)); });
    page.on('pageerror', e => pageErr.push(String(e.message).slice(0, 160)));
    let metrics = null, err = null;
    try {
      await page.goto(BASE + encodeURI(p) + '?skipboot=1', { waitUntil: 'load', timeout: 20000 });
      await page.waitForTimeout(900);
      metrics = await page.evaluate(() => {
        const de = document.documentElement;
        const vw = de.clientWidth;
        const over = [];
        if (de.scrollWidth > vw + 1) {
          for (const el of document.body.querySelectorAll('*')) {
            const r = el.getBoundingClientRect();
            if (r.width && r.right > vw + 1) {
              const cs = getComputedStyle(el);
              if (cs.position === 'fixed' && r.left >= vw) continue;
              let anc = el.parentElement, clipped = false;
              while (anc && anc !== document.body) {
                const o = getComputedStyle(anc).overflowX;
                if (o === 'hidden' || o === 'auto' || o === 'scroll' || o === 'clip') { clipped = true; break; }
                anc = anc.parentElement;
              }
              if (!clipped) over.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : ''} r=${Math.round(r.right)}`);
            }
          }
        }
        // What a visitor experiences: can the page pan sideways, and is any
        // text pushed past the right edge where nobody can read it?
        window.scrollTo(99999, window.scrollY);
        const panX = window.scrollX; window.scrollTo(0, window.scrollY);
        const clippedText = [];
        const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let n;
        while ((n = tw.nextNode())) {
          if (!n.nodeValue.trim()) continue;
          const el = n.parentElement; if (!el) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.position === 'fixed' || +cs.opacity === 0) continue;
          // Skip screen-reader-only text and anything inside a container that
          // deliberately clips or scrolls (ellipsis rows, carousels, tickers).
          let skip = false;
          for (let a = el; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
            const c = getComputedStyle(a);
            if (c.clip !== 'auto' && c.position === 'absolute') { skip = true; break; }
            if (c.clipPath && c.clipPath !== 'none') { skip = true; break; }
            if (['hidden','auto','scroll','clip'].includes(c.overflowX) && a.getBoundingClientRect().right <= vw + 2) { skip = true; break; }
            if (a.getAttribute('aria-hidden') === 'true' || a.hasAttribute('inert')) { skip = true; break; }
            if (c.position === 'fixed') { skip = true; break; }
          }
          if (skip) continue;
          const rg = document.createRange(); rg.selectNodeContents(n);
          for (const r of rg.getClientRects()) {
            if (r.width > 1 && r.right > vw + 2 && r.left < vw + 400 && r.bottom > 0) {
              clippedText.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className==='string' ? '.' + el.className.split(' ')[0] : ''}:"${n.nodeValue.trim().slice(0, 24)}" r=${Math.round(r.right)}`);
              break;
            }
          }
          if (clippedText.length >= 6) break;
        }
        let blur = 0, bigBlur = 0;
        for (const el of document.querySelectorAll('*')) {
          const cs = getComputedStyle(el);
          const bf = cs.backdropFilter || cs.webkitBackdropFilter;
          if (bf && bf !== 'none') {
            blur++;
            const m = /blur\(([\d.]+)px\)/.exec(bf);
            if (m && +m[1] > 24) bigBlur++;
          }
        }
        const anims = document.getAnimations();
        const infinite = anims.filter(a => a.effect && a.effect.getTiming().iterations === Infinity && a.playState === 'running').length;
        return {
          scrollW: de.scrollWidth, vw, overflow: de.scrollWidth > vw + 1, panX, clippedText,
          overflowEls: over.slice(0, 6), blur, bigBlur, infinite,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          htmlBg: getComputedStyle(de).backgroundColor,
          bodyColor: getComputedStyle(document.body).color,
        };
      });
    } catch (e) { err = String(e.message).slice(0, 120); }
    results.push({ page: p, missing: [...missing], consoleErr, pageErr, metrics, err });
    await page.close();
  }
  await ctx.close();
}
await Promise.all(Array.from({ length: CONC }, worker));
await browser.close();
results.sort((a, b) => a.page.localeCompare(b.page));
fs.writeFileSync(out, JSON.stringify(results, null, 1));
const n = results.length;
const s = k => results.filter(k).length;
console.log(JSON.stringify({
  width, pages: n,
  loadErrors: s(r => r.err),
  with404: s(r => r.missing.length),
  withConsoleErr: s(r => r.consoleErr.length),
  withPageErr: s(r => r.pageErr.length),
  overflow: s(r => r.metrics?.overflow),
  canPanSideways: s(r => r.metrics?.panX > 0),
  clippedTextPages: s(r => r.metrics?.clippedText?.length),
  bigBlurPages: s(r => r.metrics?.bigBlur > 0),
  totalBlurEls: results.reduce((a, r) => a + (r.metrics?.blur || 0), 0),
  pagesOver8Infinite: s(r => r.metrics?.infinite > 8),
  totalInfinite: results.reduce((a, r) => a + (r.metrics?.infinite || 0), 0),
}, null, 1));
