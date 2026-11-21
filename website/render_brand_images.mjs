// Render the homepage's raster brand images from local sources:
//   assets/site/img/icon-32.png, icon-180.png, icon-512.png  (from monogram.svg)
//   assets/site/img/og-card.png                              (1200x630 social card)
//
// Optional: the PNGs are committed, so only rerun this after changing the
// monogram, fonts or headline. Needs Playwright with Chromium:
//   node website/render_brand_images.mjs        (run from the repository root)
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

// createRequire so a globally installed Playwright resolves too.
const { chromium } = createRequire(import.meta.url)('playwright');

const root = process.cwd();
const img = path.join(root, 'assets/site/img');
// Inline the fonts: a setContent page cannot load file:// URLs.
const font = (name) => 'data:font/woff2;base64,' +
  fs.readFileSync(path.join(root, 'assets/site/fonts', name)).toString('base64');
const mark = fs.readFileSync(path.join(img, 'monogram.svg'), 'utf8');
const markUri = 'data:image/svg+xml;base64,' + Buffer.from(mark).toString('base64');

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

for (const size of [32, 180, 512]) {
  await page.setViewportSize({ width: size, height: size });
  // Apple touch icons get a solid background; the mark already has one.
  await page.setContent(
    `<html><body style="margin:0;background:#09080c"><img src="${markUri}" width="${size}" height="${size}" style="display:block"></body></html>`
  );
  await page.screenshot({ path: path.join(img, `icon-${size}.png`), omitBackground: size === 32 });
}

await page.setViewportSize({ width: 1200, height: 630 });
await page.setContent(`<!doctype html><html><head><style>
@font-face{font-family:Cormorant;font-weight:500;src:url(${font('cormorant-garamond-latin-500-normal.woff2')})}
@font-face{font-family:Cormorant;font-weight:500;font-style:italic;src:url(${font('cormorant-garamond-latin-500-italic.woff2')})}
@font-face{font-family:Plex;font-weight:500;src:url(${font('ibm-plex-mono-latin-500-normal.woff2')})}
html,body{margin:0;width:1200px;height:630px;overflow:hidden}
body{display:flex;align-items:center;gap:64px;padding:0 88px;box-sizing:border-box;color:#f5f0f2;
background:radial-gradient(90% 80% at 15% 0%,rgba(122,22,48,.75),transparent 60%),radial-gradient(60% 60% at 100% 100%,rgba(170,131,255,.18),transparent 70%),linear-gradient(160deg,#1a0a11,#09080c 70%)}
body::after{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(245,240,242,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(245,240,242,.04) 1px,transparent 1px);background-size:44px 44px}
img{width:260px;height:260px;border-radius:50%;box-shadow:0 0 0 8px rgba(9,8,12,.9),0 0 70px rgba(199,68,91,.45),0 0 120px rgba(170,131,255,.3)}
.k{font:500 18px Plex;letter-spacing:.24em;text-transform:uppercase;color:#ec8b9b}
h1{margin:22px 0 0;font:500 92px/1 Cormorant}
h1 span{display:block;font-style:italic;background:linear-gradient(90deg,#f5f0f2,#cdb9ff 45%,#7ceeff);-webkit-background-clip:text;color:transparent}
.n{margin-top:30px;font:500 18px Plex;letter-spacing:.2em;text-transform:uppercase;color:#a6e8f2}
</style></head><body><img src="${markUri}" alt=""><div><p class="k">ClearGlass Inc.</p>
<h1>Governed AI.<span>Engineered Trust.</span></h1><p class="n">See Through Everything.</p></div></body></html>`);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: path.join(img, 'og-card.png') });

await browser.close();
console.log('rendered icon-32/180/512.png and og-card.png');
