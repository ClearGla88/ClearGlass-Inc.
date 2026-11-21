// Performance measurement for Sentinel Workspace.
//
//   node tests/sentinel_workspace/bench.browser.cjs
//
// Part 1 times the core analysis functions in Node. Part 2 times the page in
// headless Chromium (Playwright): import → first rendered graph, selection
// latency, force layout and JS heap. Results depend on the machine; record the
// conditions printed at the top alongside any numbers you quote.
"use strict";
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { generate } = require("./gen_dataset.cjs");
const { serve, ROOT } = require("./serve.cjs");

const SIZES = [20, 250, 1000, 2500, 5000];

function loadCore() {
  const src = fs.readFileSync(path.join(ROOT, "sentinel-workspace/core.js"), "utf8");
  const mod = { exports: {} };
  new Function("module", "exports", src)(mod, mod.exports);
  return mod.exports;
}
function time(fn, reps = 3) {
  let best = Infinity, out;
  for (let i = 0; i < reps; i++) { const t0 = performance.now(); out = fn(); best = Math.min(best, performance.now() - t0); }
  return { ms: best, out };
}
function datasetText(n) {
  if (n === 20) return fs.readFileSync(path.join(ROOT, "sentinel-workspace/fixtures/lookalike-domain-v1.json"), "utf8");
  /* 5,000 entities at 2 relationships each is ~6 MB, over the 5 MB import
     limit; that size is measured at 1.5 relationships per entity instead. */
  return JSON.stringify(generate(n, 42, n >= 5000 ? 1.5 : 2));
}
const f1 = (x) => (x < 10 ? x.toFixed(2) : x.toFixed(0));

(async () => {
  console.log("conditions: " + os.cpus().length + "× " + (os.cpus()[0] || {}).model + ", " + Math.round(os.totalmem() / 2 ** 30) + " GiB, Node " + process.version + ", " + os.platform() + " " + os.release());
  const C = loadCore();
  console.log("\n## Core (Node, best of 3)\n");
  console.log("| entities | relationships | bytes | parse+validate ms | buildGraph ms | metrics ms | path ms | radial ms | force ms (iterations, approx) |");
  console.log("|---|---|---|---|---|---|---|---|---|");
  for (const n of SIZES) {
    const text = datasetText(n);
    const parsed = time(() => C.parseDataset(text));
    const ds = parsed.out.dataset, idx = C.buildIndex(ds);
    const g = time(() => C.buildGraph(ds, idx, { filters: { review: ["unreviewed", "confirmed", "disputed"] } }));
    const m = time(() => C.computeMetrics(g.out.nodes, g.out.edges));
    const edges = C.projectEdges(ds);
    const from = ds.entities[0].id, to = ds.entities[ds.entities.length - 1].id;
    const p = time(() => C.findPaths(edges, { from, to, maxHops: 6, direction: "any" }));
    const r = time(() => C.layoutRadial(g.out.nodes, g.out.edges, {}));
    const f = time(() => C.layoutForce(g.out.nodes, g.out.edges, { seed: 1 }), 1);
    console.log(`| ${ds.entities.length} | ${ds.relationships.length} | ${text.length} | ${f1(parsed.ms)} | ${f1(g.ms)} | ${f1(m.ms)} | ${f1(p.ms)} | ${f1(r.ms)} | ${f1(f.ms)} (${f.out.params.iterations}${f.out.params.approximation ? ", grid" : ""}) |`);
  }

  let chromium;
  try { ({ chromium } = require("playwright")); } catch (e) { console.log("\nPlaywright not available; browser measurements skipped."); return; }
  const { server, url } = await serve();
  const browser = await chromium.launch();
  console.log("\n## Browser (headless Chromium " + browser.version() + ", 1440×900, one run each)\n");
  console.log("| entities | import → graph drawn ms | SVG elements | select latency ms | force layout ms | JS heap MB |");
  console.log("|---|---|---|---|---|---|");
  try {
    for (const n of SIZES) {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await ctx.newPage();
      await page.goto(url + "/sentinel-workspace.html");
      await page.locator("#graph .node").first().waitFor();
      const text = datasetText(n);
      const expected = JSON.parse(text).entities.length;
      const t0 = Date.now();
      await page.locator("#fileDataset").setInputFiles({ name: "scale.json", mimeType: "application/json", buffer: Buffer.from(text) });
      await page.waitForFunction((k) => document.querySelectorAll("#graph .node").length === k, expected, { timeout: 120000 });
      const importMs = Date.now() - t0;
      const svgCount = await page.evaluate(() => document.querySelectorAll("#graph *").length);
      const select = await page.evaluate(() => {
        const nodes = document.querySelectorAll("#graph .node");
        const el = nodes[Math.floor(nodes.length / 2)].querySelector(".shape");
        const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
        const t = performance.now();
        el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 7, clientX: x, clientY: y }));
        el.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 7, clientX: x, clientY: y }));
        return { ms: performance.now() - t, selected: !!document.querySelector("#graph .node.sel") };
      });
      await page.getByRole("button", { name: "Force", exact: true }).click();
      await page.waitForFunction(() => /Force layout finished/.test(document.getElementById("activityLast").textContent), null, { timeout: 180000 });
      const forceMs = await page.evaluate(() => +(/, (\d+) ms/.exec(document.getElementById("activityLast").textContent) || [0, 0])[1]);
      const cdp = await ctx.newCDPSession(page);
      await cdp.send("Performance.enable");
      const metrics = (await cdp.send("Performance.getMetrics")).metrics;
      const heap = metrics.find((m) => m.name === "JSHeapUsedSize").value / 2 ** 20;
      console.log(`| ${expected} | ${importMs} | ${svgCount} | ${select.ms.toFixed(1)}${select.selected ? "" : " (not selected)"} | ${forceMs} | ${heap.toFixed(1)} |`);
      await ctx.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
