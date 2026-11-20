// End-to-end browser journey for sentinel-workspace.html.
//
//   node tests/sentinel_workspace/e2e.browser.cjs [screenshot-dir]
//
// Needs Playwright with Chromium (require("playwright")). It is not part of
// the CI suite, which runs only the dependency-free core tests; see
// sentinel-workspace/README.md. It serves the repository itself, so no
// other server is needed, and fails on any console error, page error or
// request that leaves the local origin.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium, devices } = require("playwright");
const { serve, ROOT } = require("./serve.cjs");

const SHOTS = process.argv[2] || null;
let step = 0;
function ok(msg) { step++; console.log("ok " + step + " - " + msg); }
async function shot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, name + ".png") }); }

function guard(page, origin) {
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  page.on("request", (r) => { if (!r.url().startsWith(origin) && !r.url().startsWith("blob:") && !r.url().startsWith("data:")) problems.push("external request: " + r.url()); });
  return problems;
}
async function download(page, buttonText) {
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: buttonText, exact: true }).click()]);
  const p = await dl.path();
  return { name: dl.suggestedFilename(), text: fs.readFileSync(p, "utf8") };
}
async function prompt(page, text) {
  await page.locator("#dlgPrompt").waitFor({ state: "visible" });
  await page.locator("#promptInput").fill(text);
  await page.locator("#promptOk").click();
  await page.locator("#dlgPrompt").waitFor({ state: "hidden" });
}
async function search(page, q) {
  await page.keyboard.press("/");
  await page.locator("#searchInput").fill(q);
  await page.locator("#searchResults [role=option]").first().waitFor();
  await page.keyboard.press("Enter");
}

async function desktop(browser, origin) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const problems = guard(page, origin);
  const url = origin + "/sentinel-workspace.html";
  await page.goto(url);
  await page.locator("#graph .node").first().waitFor();
  assert.equal(await page.locator("#dsSynthetic").isVisible(), true);
  assert.match(await page.locator("#strip").innerText(), /21\s+of 22 relationships/);
  assert.match(await page.locator("#strip").innerText(), /1 by review state/);
  ok("loads the bundled synthetic dataset; the rejected link is hidden and counted");
  await shot(page, "d01-explore");

  // Table → relationship → evidence → add to investigation
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await page.getByRole("button", { name: "Relationships", exact: true }).click();
  await page.locator("table.data button", { hasText: "utilityco-billing.example → Phishing kit" }).click();
  await assertTitle(page, /serves kit artifact/);
  await page.locator("#isec-evidence .ev", { hasText: "obs-sbx-kit" }).getByRole("button", { name: "Add to investigation" }).click();
  assert.match(await page.locator("#isec-evidence").innerText(), /Remove from investigation/);
  assert.match(await page.locator("#isec-evidence").innerText(), /INDEPENDENT CORROBORATION/i);
  ok("table view selects a relationship; its evidence opens and is attached");
  await shot(page, "d02-relationship-evidence");
  await page.getByRole("button", { name: "Graph", exact: true }).click();

  // Search → claim → attach its evidence
  await search(page, "same operator");
  await assertTitle(page, /same operator controls/);
  assert.match(await page.locator("#inspHead").innerText(), /HYPOTHESIZED/);
  await page.locator("#isec-actions").getByRole("button", { name: "Add evidence to investigation" }).click();
  ok("search opens a hypothesised claim; its supporting and contradicting records are attached");

  // Annotate a relationship
  await search(page, "rel-paycenter-kit");
  await page.locator("#isec-actions").getByRole("button", { name: "Annotate" }).click();
  await prompt(page, "Model-extracted from an archive; verify the capture before relying on it.");
  assert.match(await page.locator("#isec-summary").innerText(), /ANALYST-ASSESSED/);
  ok("annotation recorded and shown as analyst-assessed");

  // Path analysis
  await page.locator("#railBody select[aria-label='Path start']").selectOption("ent-dom-billing");
  await page.locator("#railBody select[aria-label='Path end']").selectOption("ent-dom-paycenter");
  await page.getByRole("button", { name: "Find paths", exact: true }).click();
  assert.match(await page.locator("#railBody").innerText(), /path.* of 1 hop/);
  await page.locator("#railBody").getByRole("button", { name: "Explain this result" }).first().click();
  assert.match(await page.locator("#inspBody").innerText(), /Qualifies because/);
  assert.match(await page.locator("#inspBody").innerText(), /not the strongest, most likely, safest or causal path/);
  ok("constrained path analysis runs and explains why each step qualifies");

  // Metrics + staleness when filters change
  await page.getByRole("button", { name: "Compute for current scope" }).click();
  assert.match(await page.locator("#railBody").innerText(), /Relationship records\s*21/);
  await page.locator("#railBody label.check", { hasText: "rejected" }).first().locator("input").check();
  assert.equal(await page.locator("#metricsStale").isVisible(), true);
  ok("graph metrics compute on the visible scope and flag themselves stale after a filter change");
  await shot(page, "d03-path-metrics");

  // Force layout runs in a Web Worker (allowed by the page CSP) and is reproducible from its seed
  await page.getByRole("button", { name: "Force", exact: true }).click();
  await page.waitForFunction(() => /Force layout finished.*Web Worker/.test(document.getElementById("activityLast").textContent));
  const posA = await page.locator('#graph .node[data-id="ent-ip-shared"]').getAttribute("transform");
  await page.getByRole("button", { name: "Radial", exact: true }).click();
  await page.getByRole("button", { name: "Force", exact: true }).click();
  await page.waitForFunction(() => /Force layout finished.*Web Worker/.test(document.getElementById("activityLast").textContent));
  assert.equal(await page.locator('#graph .node[data-id="ent-ip-shared"]').getAttribute("transform"), posA, "same seed, same layout");
  await page.getByRole("button", { name: "Undo layout" }).click();
  assert.equal(await page.locator("#layoutSeg button[aria-pressed='true']").innerText(), "Radial", "undo reverts the last switch");
  await page.getByRole("button", { name: "Undo layout" }).click();
  assert.equal(await page.locator("#layoutSeg button[aria-pressed='true']").innerText(), "Force", "and the one before it");
  await page.getByRole("button", { name: "Radial", exact: true }).click();
  ok("force layout runs in a Web Worker, reproduces from its seed, and layout changes undo");

  // Merge candidate: confirm with rationale, then undo
  const before = await page.locator("#graph .node").count();
  await page.locator("#railBody .ev", { hasText: "Registrar R1 (fictional) + Registrar R1 LLC" }).getByRole("button", { name: "Confirm merge…" }).click();
  await prompt(page, "Same registrar ID 9999 in both RDAP records.");
  assert.equal(await page.locator("#graph .node").count(), before - 1);
  await page.locator("#railBody .ev", { hasText: "Registrar R1" }).getByRole("button", { name: "Undo decision" }).first().click();
  assert.equal(await page.locator("#graph .node").count(), before);
  ok("merge applies only after a confirmed decision with rationale, and undoes cleanly");

  // Keyboard: roving focus + Enter selects
  await page.locator("#graph .node[tabindex='0']").focus();
  await page.keyboard.press("ArrowRight");
  const focused = await page.evaluate(() => document.activeElement.getAttribute("data-id"));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(50);
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute("data-id")), focused, "focus preserved after selecting");
  assert.equal(await page.locator(`#graph .node[data-id="${focused}"]`).getAttribute("aria-pressed"), "true");
  ok("keyboard moves between entities and selects without losing focus");

  // Back restores previous context
  await page.getByRole("button", { name: "← Back" }).click();
  ok("back returns to the previous selection");

  // Investigate: question, hypotheses, matrix, conclusion
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  await page.getByLabel("Investigative question").fill("Is utilityco-billing.example run by the same operator as uc-paycenter.example?");
  await page.getByRole("button", { name: "Save question" }).click();
  for (const [label, stmt] of [["H1 Same operator", "One actor controls both domains."], ["H2 Unrelated operators", "Shared hosting and a sold kit explain the overlap."]]) {
    await page.getByLabel("Hypothesis label").fill(label);
    await page.getByLabel("Hypothesis statement").fill(stmt);
    await page.getByRole("button", { name: "Add hypothesis" }).click();
  }
  await page.getByLabel("H1 Same operator vs obs-kitnote-public").selectOption("inconsistent");
  await page.getByLabel("H2 Unrelated operators vs obs-kitnote-public").selectOption("consistent");
  await page.getByLabel("H1 Same operator vs obs-sbx-kit").selectOption("consistent");
  await page.getByLabel("H2 Unrelated operators vs obs-sbx-kit").selectOption("consistent");
  assert.match(await page.locator("table.matrix tfoot").innerText(), /I 1/);
  await page.getByLabel("Selected hypothesis").selectOption({ label: "H2 Unrelated operators" });
  await page.locator("#investigatePane").getByLabel("Conclusion", { exact: true }).fill("The overlap is better explained by shared hosting and a publicly sold kit.");
  await page.getByRole("button", { name: "Record conclusion" }).click();
  assert.match(await page.locator("#toast").innerText(), /Rationale is required/);
  assert.doesNotMatch(await page.locator("#investigatePane").innerText(), /Recorded 20/i);
  await page.locator("#investigatePane").getByLabel("Rationale", { exact: true }).fill("The kit is sold publicly and the address hosts over a thousand domains; the only link is inconsistent with H1.");
  await page.getByRole("button", { name: "Record conclusion" }).click();
  assert.match(await page.locator("#investigatePane").innerText(), /Recorded 20/i);
  ok("notebook records question, competing hypotheses, matrix assessments and a conclusion that requires a rationale");
  await shot(page, "d04-investigate");

  // Brief + exports
  await page.getByRole("button", { name: "Brief", exact: true }).click();
  assert.match(await page.locator("#briefPane").innerText(), /Every citation \(\d+\) resolves/);
  const brief = await download(page, "Brief (.md)");
  for (const h of ["Investigative question", "Scope and dataset", "Key findings", "Supporting and contradicting evidence", "Methods", "Unresolved questions", "Limitations", "Review status"]) assert.match(brief.text, new RegExp("## \\d+\\. " + h));
  assert.match(brief.text, /SYNTHETIC DATASET/);
  assert.match(brief.text, /\[ref:obs-sbx-kit\]/);
  assert.match(brief.text, /Path analysis — Constrained breadth-first search/);
  assert.match(brief.text, /H2 Unrelated operators/);
  ok("brief exports with every required section, validated citations and the methods used");
  const graph = JSON.parse((await download(page, "Graph JSON (versioned)")).text);
  assert.equal(graph.schema, "clearglass.sentinel/1");
  assert.deepEqual(graph.export.restricted_fields_removed, ["ent-doc-pr0142.attributes.internal_case_owner"]);
  const csv = (await download(page, "Relationships CSV")).text;
  assert.match(csv.split("\r\n")[0], /^id,type,from,to/);
  const manifest = JSON.parse((await download(page, "Evidence manifest")).text);
  assert.ok(manifest.items.length >= 5 && manifest.items.every((i) => i.status === "present" ? /^[0-9a-f]{64}$/.test(i.excerpt_sha256) : true));
  const view = JSON.parse((await download(page, "View state")).text);
  assert.equal(view.schema, "clearglass.sentinel.view/1");
  const svg = (await download(page, "Graph image (.svg)")).text;
  assert.match(svg, /^<svg/);
  assert.match(svg, /SYNTHETIC/);
  ok("JSON graph (restricted field removed), CSV, evidence manifest, view state and SVG image export");
  await shot(page, "d05-brief");

  // Compare
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("button", { name: "Load bundled later snapshot (v1.1.0)" }).click();
  await page.locator("#comparePane").getByText("Newly collected, not newly occurring").first().waitFor();
  const cmp = await page.locator("#comparePane").innerText();
  assert.match(cmp, /Newly collected, not newly occurring/);
  assert.match(cmp, /Extraction change only/);
  assert.match(cmp, /Not present in v1\.1\.0/);
  assert.match(cmp, /does not mean the underlying fact was deleted/i);
  ok("snapshot comparison separates added, not-present and modified records with temporal caveats");
  await shot(page, "d06-compare");

  // Reload: notebook persists
  await page.reload();
  await page.locator("#graph .node").first().waitFor();
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  assert.match(await page.locator("#investigatePane").innerText(), /H2 Unrelated operators/);
  ok("notebook survives a reload (browser storage)");

  // Hostile and oversized imports
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  const bad = JSON.parse(fs.readFileSync(path.join(ROOT, "sentinel-workspace/fixtures/lookalike-domain-v1.json"), "utf8"));
  bad.sources[0].uri = "javascript:alert(1)";
  await page.locator("#fileDataset").setInputFiles({ name: "bad.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(bad)) });
  await page.locator("#dlgErrors").waitFor({ state: "visible" });
  assert.match(await page.locator("#errorsBody").innerText(), /\$\.sources\[0\]\.uri — Only http: and https: links are accepted/);
  await page.locator("#dlgErrors [data-close]").click();
  await page.locator("#fileDataset").setInputFiles({ name: "big.json", mimeType: "application/json", buffer: Buffer.alloc(5 * 1024 * 1024 + 1, 32) });
  await page.locator("#dlgErrors").waitFor({ state: "visible" });
  assert.match(await page.locator("#errorsBody").innerText(), /It was not read/);
  await page.locator("#dlgErrors [data-close]").click();
  assert.match(await page.locator("#dsTitle").innerText(), /Lookalike billing domain/);
  ok("hostile and oversized imports are refused and leave the loaded dataset unchanged");

  // Privacy: delete local data
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Privacy" }).click();
  assert.match(await page.locator("#handlingBody").innerText(), /contacts no other service/);
  await page.getByRole("button", { name: "Delete all local workspace data…" }).click();
  await page.locator("#dlgHandling [data-close]").click();
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  assert.doesNotMatch(await page.locator("#investigatePane").innerText(), /H2 Unrelated operators/);
  ok("local data deletion clears the stored notebook");

  assert.deepEqual(problems, [], problems.join("\n"));
  ok("desktop: no console errors, page errors or external requests");
  await ctx.close();
}

async function assertTitle(page, re) {
  await page.waitForFunction((src) => new RegExp(src).test((document.querySelector("#inspHead h2") || {}).textContent || ""), re.source);
}

async function mobile(browser, origin) {
  const ctx = await browser.newContext({ ...devices["iPhone 13"] });
  const page = await ctx.newPage();
  const problems = guard(page, origin);
  await page.goto(origin + "/sentinel-workspace.html");
  await page.locator("#graph .node").first().waitFor();
  const vh = page.viewportSize().height;
  const canvas = await page.locator("#canvas").boundingBox();
  assert.ok(canvas.height / vh > 0.55, "canvas uses " + Math.round(canvas.height / vh * 100) + "% of the viewport");
  ok("mobile canvas keeps " + Math.round(canvas.height / vh * 100) + "% of viewport height");
  await shot(page, "m01-explore");
  await page.locator("#dockFilters").click();
  await page.waitForTimeout(300);
  const railBox = await page.locator("#rail").boundingBox();
  assert.ok(railBox.x >= -1, "filters drawer is on screen");
  await shot(page, "m02-filters");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  assert.ok((await page.locator("#rail").boundingBox()).x < -100, "filters drawer closed");
  ok("filters open in a drawer and close with Escape");
  await page.locator("#dockSearch").click();
  await page.locator("#searchInput").fill("paycenter");
  await page.locator("#searchResults [role=option]").first().waitFor();
  await shot(page, "m03-search");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#app").getAttribute("data-sheet"), "half");
  await page.waitForTimeout(300);
  await shot(page, "m04-sheet-half");
  await page.locator("#sheetHandle").click();
  assert.equal(await page.locator("#app").getAttribute("data-sheet"), "full");
  await page.locator("#sheetHandle").click();
  assert.equal(await page.locator("#app").getAttribute("data-sheet"), "peek");
  await page.waitForTimeout(300);
  await shot(page, "m05-sheet-peek");
  ok("search overlay selects; inspector bottom sheet snaps half → full → peek");
  const small = await page.$$eval("#dock button, .modes button", (els) => els.filter((e) => { const r = e.getBoundingClientRect(); return r.height < 34 || r.width < 44; }).length);
  assert.equal(small, 0, "primary touch targets are at least 44×34 px");
  ok("dock and mode buttons meet the touch-target size check");
  await page.setViewportSize({ width: 844, height: 390 });
  await page.waitForTimeout(300);
  assert.ok((await page.locator("#canvas").boundingBox()).height > 120, "landscape keeps a usable canvas");
  ok("landscape orientation keeps a usable canvas");
  assert.deepEqual(problems, [], problems.join("\n"));
  ok("mobile: no console errors, page errors or external requests");
  await ctx.close();
}

(async () => {
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
  const { server, url } = await serve();
  const browser = await chromium.launch();
  try {
    await desktop(browser, url);
    await mobile(browser, url);
    console.log("# pass " + step);
  } finally {
    await browser.close();
    server.close();
  }
})().catch((e) => { console.error("not ok - " + (e && e.stack || e)); process.exit(1); });
