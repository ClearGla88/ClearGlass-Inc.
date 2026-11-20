// Unit tests for sentinel-workspace/core.js. Run: node --test tests/sentinel_workspace/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import "../../sentinel-workspace/core.js";

const C = globalThis.SentinelCore;
const here = path.dirname(fileURLToPath(import.meta.url));
const fixtureDir = path.join(here, "..", "..", "sentinel-workspace", "fixtures");
const V1_TEXT = readFileSync(path.join(fixtureDir, "lookalike-domain-v1.json"), "utf8");
const V2_TEXT = readFileSync(path.join(fixtureDir, "lookalike-domain-v2.json"), "utf8");
const NOW = new Date("2026-11-01T12:00:00Z");

function load(text = V1_TEXT) {
  const r = C.parseDataset(text);
  assert.ok(r.ok, JSON.stringify(r.errors));
  return { ds: r.dataset, idx: C.buildIndex(r.dataset), fp: r.fingerprint };
}
function raw() { return JSON.parse(V1_TEXT); }
function errorsFor(mutate) {
  const doc = raw();
  mutate(doc);
  return C.validateDataset(doc).errors;
}
function hasError(errors, pathPrefix) { return errors.some((e) => e.path.startsWith(pathPrefix)); }

/* ── hashing + canonical form ─────────────────────────────────────────── */

test("sha256 matches node:crypto across block boundaries and unicode", () => {
  const inputs = ["", "abc", "a".repeat(55), "a".repeat(56), "a".repeat(64), "a".repeat(1000), "héllo ✓ 😀 \u0000", JSON.stringify(raw())];
  for (const s of inputs) assert.equal(C.sha256Hex(s), createHash("sha256").update(s, "utf8").digest("hex"));
});

test("canonical JSON ignores key order; fingerprint ignores the export block", () => {
  assert.equal(C.canonicalJSON({ b: 1, a: [2, { d: 3, c: 4 }] }), C.canonicalJSON({ a: [2, { c: 4, d: 3 }], b: 1 }));
  const { ds } = load();
  const withExport = Object.assign({}, ds, { export: { exported_at: "x" } });
  assert.equal(C.fingerprint(withExport), C.fingerprint(ds));
});

/* ── validation ───────────────────────────────────────────────────────── */

test("both committed fixtures validate and are flagged synthetic", () => {
  for (const t of [V1_TEXT, V2_TEXT]) {
    const r = C.parseDataset(t);
    assert.ok(r.ok, JSON.stringify(r.errors));
    assert.equal(r.dataset.dataset.synthetic, true);
    assert.match(r.dataset.dataset.description, /SYNTHETIC/);
  }
});

test("fixture identifiers stay inside reserved namespaces", () => {
  const { ds } = load(V2_TEXT);
  for (const e of ds.entities) {
    if (e.type === "domain") assert.match(e.label, /\.example$/, e.label);
    if (e.type === "ip") assert.match(e.label, /^(192\.0\.2|198\.51\.100|203\.0\.113)\.\d+$/, e.label);
    if (e.type === "organization") assert.match(e.label, /\(fictional\)$/, e.label);
  }
});

test("normalisation drops unknown keys so they cannot reach rendering or export", () => {
  const doc = raw();
  doc.entities[0].onclick = "alert(1)";
  doc.extra_top = 1;
  const r = C.parseDataset(JSON.stringify(doc));
  assert.ok(r.ok);
  assert.equal("onclick" in r.dataset.entities[0], false);
  assert.equal("extra_top" in r.dataset, false);
  assert.ok(r.warnings.some((w) => w.path === "$.extra_top"));
});

test("validation rejects malformed, dangling, ambiguous and hostile input", () => {
  assert.ok(hasError(errorsFor((d) => { d.schema = "other/1"; }), "$.schema"));
  assert.ok(hasError(errorsFor((d) => { delete d.dataset.synthetic; }), "$.dataset.synthetic"));
  assert.ok(hasError(errorsFor((d) => { d.claims[0].id = d.entities[0].id; }), "$.claims[0].id"), "ids are unique across collections");
  assert.ok(hasError(errorsFor((d) => { d.relationships[0].to = "ent-missing"; }), "$.relationships[0].to"));
  assert.ok(hasError(errorsFor((d) => { d.relationships[0].evidence.supporting.push("obs-missing"); }), "$.relationships[0].evidence"));
  assert.ok(hasError(errorsFor((d) => { delete d.observations[0].observed_at; }), "$.observations[0].observed_at"), "time keys must be present");
  assert.deepEqual(errorsFor((d) => { d.observations[0].observed_at = null; }), [], "null is the explicit unknown");
  assert.ok(hasError(errorsFor((d) => { d.observations[0].observed_at = "yesterday"; }), "$.observations[0].observed_at"));
  assert.ok(hasError(errorsFor((d) => { d.observations[0].observed_at = "2026-09-03T08:14:00"; }), "$.observations[0].observed_at"), "date-times need a zone");
  assert.ok(hasError(errorsFor((d) => { d.sources[0].uri = "javascript:alert(1)"; }), "$.sources[0].uri"));
  assert.ok(hasError(errorsFor((d) => { d.sources[0].uri = "data:text/html,x"; }), "$.sources[0].uri"));
  assert.ok(hasError(errorsFor((d) => { d.observations[0].extraction.confidence = 1.4; }), "$.observations[0].extraction.confidence"));
  assert.ok(hasError(errorsFor((d) => { d.observations[0].extraction.confidence = "high"; }), "$.observations[0].extraction.confidence"));
  assert.ok(hasError(errorsFor((d) => { d.relationships[0].first_observed = "2027-01-01T00:00:00Z"; }), "$.relationships[0].first_observed"));
  assert.ok(hasError(errorsFor((d) => { delete d.relationships[0].directed; }), "$.relationships[0].directed"));
  assert.ok(hasError(errorsFor((d) => { d.merge_candidates[0].entities = ["ent-org-registrar", "ent-org-registrar"]; }), "$.merge_candidates[0].entities"));
  assert.ok(hasError(errorsFor((d) => { d.merge_candidates[0].criteria = []; }), "$.merge_candidates[0].criteria"));
  assert.ok(hasError(errorsFor((d) => { d.entities[0].type = "spy"; }), "$.entities[0].type"));
  assert.ok(hasError(errorsFor((d) => { d.entities[0].attributes.nested = { a: 1 }; }), "$.entities[0].attributes.nested"));
  assert.ok(hasError(errorsFor((d) => { d.sources[0].assessment.reliability = "Z"; }), "$.sources[0].assessment.reliability"));
});

test("prototype-pollution keys and deep nesting are refused", () => {
  const polluted = V1_TEXT.replace('"attributes": {}', '"attributes": {"__proto__": {"admin": true}}');
  assert.notEqual(polluted, V1_TEXT);
  const r = C.parseDataset(polluted);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => /__proto__/.test(e.path)));
  assert.equal({}.admin, undefined);
  let deep = 1;
  for (let i = 0; i < 20; i++) deep = [deep];
  const doc = raw();
  doc.entities[0].aliases = deep;
  assert.equal(C.validateDataset(doc).ok, false);
});

test("oversized and non-JSON files fail closed with a reason", () => {
  const big = " ".repeat(C.LIMITS.maxBytes + 1);
  const r1 = C.parseDataset(big);
  assert.equal(r1.ok, false);
  assert.match(r1.errors[0].message, /limit/);
  const r2 = C.parseDataset("{not json");
  assert.equal(r2.ok, false);
  assert.match(r2.errors[0].message, /Not valid JSON/);
  assert.equal(C.parseDataset(42).ok, false);
});

/* ── index, projection, filters ───────────────────────────────────────── */

test("index counts and explicit unknown times", () => {
  const { ds, idx } = load();
  assert.equal(idx.entity.size, ds.entities.length);
  assert.equal(idx.relationship.size, 22);
  assert.equal(idx.undatedObservations, 2, "aggregate volume + vendor kit note have no observation time");
  assert.equal(C.kindOf(idx, "obs-sbx-kit"), "observation");
  assert.equal(C.kindOf(idx, "nope"), null);
});

test("graph scope reports hidden counts; the rejected guess is hidden by the default review filter", () => {
  const { ds, idx } = load();
  const full = C.buildGraph(ds, idx, {});
  assert.equal(full.scope, "full");
  assert.equal(full.edges.length, 22);
  const reviewed = C.buildGraph(ds, idx, { filters: { review: ["unreviewed", "confirmed", "disputed"] } });
  assert.equal(reviewed.scope, "subgraph");
  assert.equal(reviewed.hidden.edges, 1);
  assert.equal(reviewed.excluded.byReview, 1);
  assert.ok(!reviewed.edges.some((e) => e.id === "rel-billing-vendor-guess"));
});

test("neighbourhood isolation and forced visibility of the selection", () => {
  const { ds, idx } = load();
  const one = C.buildGraph(ds, idx, { focus: "ent-ip-shared", hops: 1 });
  const ids = one.nodes.map((n) => n.id).sort();
  assert.deepEqual(ids, ["ent-dom-billing", "ent-dom-paycenter", "ent-ip-shared", "ent-org-hosta"]);
  assert.ok(one.nodes.every((n) => n.distance !== null && n.distance <= 1));
  const two = C.buildGraph(ds, idx, { focus: "ent-ip-shared", hops: 2 });
  assert.ok(two.nodes.length > one.nodes.length);
  const filtered = C.buildGraph(ds, idx, { filters: { entityTypes: ["domain"] }, keep: ["ent-ip-shared"] });
  const kept = filtered.nodes.find((n) => n.id === "ent-ip-shared");
  assert.ok(kept && kept.forced, "selected entity stays visible and is flagged as forced");
});

test("time window keeps overlapping intervals and treats unknown times explicitly", () => {
  const { ds, idx } = load();
  const w = { from: "2026-09-01T00:00:00Z", to: "2026-09-30T23:59:59Z", includeUnknown: false };
  const g = C.buildGraph(ds, idx, { filters: { window: w } });
  const ids = new Set(g.edges.map((e) => e.id));
  assert.ok(ids.has("rel-billing-resolves"));
  assert.ok(!ids.has("rel-paycenter-resolves"), "March activity is outside the window");
  assert.ok(!ids.has("rel-ip-allocated"), "allocation since 2019 with unknown end: overlap is uncertain, not assumed");
  assert.ok(!ids.has("rel-billing-vendor-guess"), "unknown time excluded when includeUnknown is false");
  const g2 = C.buildGraph(ds, idx, { filters: { window: Object.assign({}, w, { includeUnknown: true }) } });
  assert.ok(g2.edges.some((e) => e.id === "rel-billing-vendor-guess"));
  assert.ok(g2.edges.some((e) => e.id === "rel-ip-allocated"));
  const early = { from: "2018-01-01T00:00:00Z", to: "2018-12-31T23:59:59Z", includeUnknown: true };
  assert.equal(C.windowAllows(idx.relationship.get("rel-ip-allocated"), early), false, "starts after the window: a definite miss");
  const spans = { from: "2019-01-01T00:00:00Z", to: "2019-12-31T23:59:59Z", includeUnknown: false };
  assert.equal(C.windowAllows(idx.relationship.get("rel-ip-allocated"), spans), true, "starts inside the window: a definite overlap");
});

/* ── entity resolution ───────────────────────────────────────────────── */

test("merges are explicit, order-independent, reversible and keep original IDs", () => {
  const { ds, idx } = load();
  const before = C.buildGraph(ds, idx, {});
  const r1 = C.mergeResolver([["ent-org-registrar-llc", "ent-org-registrar"]]);
  const r2 = C.mergeResolver([["ent-org-registrar", "ent-org-registrar-llc"]]);
  assert.equal(r1.canonicalOf("ent-org-registrar-llc"), "ent-org-registrar");
  assert.equal(r2.canonicalOf("ent-org-registrar-llc"), "ent-org-registrar");
  assert.deepEqual(r1.membersOf("ent-org-registrar-llc"), ["ent-org-registrar", "ent-org-registrar-llc"]);
  const merged = C.buildGraph(ds, idx, { resolver: r1 });
  assert.equal(merged.nodes.length, before.nodes.length - 1);
  const node = merged.nodes.find((n) => n.id === "ent-org-registrar");
  assert.deepEqual(node.members, ["ent-org-registrar", "ent-org-registrar-llc"]);
  assert.equal(C.buildGraph(ds, idx, { resolver: C.mergeResolver([]) }).nodes.length, before.nodes.length);
  // name similarity alone never merges anything: no candidate is applied without a decision
  let nb = C.createNotebook(ds, NOW);
  assert.deepEqual(C.confirmedMergeGroups(nb, idx), []);
  assert.throws(() => C.Notebook.decideMerge(nb, "mc-registrar-r1", "confirmed", "", NOW), /rationale/i);
  nb = C.Notebook.decideMerge(nb, "mc-registrar-r1", "confirmed", "Same registrar ID in both records.", NOW);
  assert.equal(C.mergeState(nb, "mc-registrar-r1"), "confirmed");
  nb = C.Notebook.decideMerge(nb, "mc-registrar-r1", "candidate", "", NOW);
  assert.equal(C.mergeState(nb, "mc-registrar-r1"), "candidate");
  assert.equal(nb.merge_decisions.length, 2, "decisions are appended, not overwritten");
});

/* ── paths ────────────────────────────────────────────────────────────── */

test("constrained fewest-hop paths explain each step", () => {
  const { ds, idx } = load();
  const edges = C.projectEdges(ds);
  const noCo = C.REVIEW_STATES.slice();
  const types = idx.relTypes.filter((t) => t !== "co_resolved");
  const any = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, review: noCo, direction: "any", maxHops: 4 });
  assert.equal(any.reachable, true);
  assert.equal(any.shortestLength, 2);
  const via = any.paths.map((p) => p.steps[0].to).sort();
  assert.deepEqual(via, ["ent-ip-shared", "ent-topic-kit"]);
  for (const p of any.paths) {
    assert.equal(p.steps[0].traversal, "forward");
    assert.equal(p.steps[1].traversal, "reverse");
  }
  const forward = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, direction: "forward", maxHops: 6 });
  assert.equal(forward.reachable, false, "no forward-only route exists");
  const withCo = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", direction: "forward", maxHops: 3 });
  assert.equal(withCo.shortestLength, 1);
  assert.equal(withCo.paths[0].steps[0].traversal, "undirected");
  const hop1 = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, direction: "any", maxHops: 1 });
  assert.equal(hop1.reachable, false);
  const confirmedOnly = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, review: ["confirmed"], direction: "any", maxHops: 4 });
  assert.deepEqual(confirmedOnly.paths.map((p) => p.steps[0].to), ["ent-ip-shared"], "unreviewed kit link excluded");
  const limited = C.findPaths(edges, { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, direction: "any", maxHops: 4, limit: 1 });
  assert.equal(limited.paths.length, 1);
  assert.equal(limited.truncated, true);
  const merged = C.findPaths(C.projectEdges(ds, C.mergeResolver([["ent-org-registrar", "ent-org-registrar-llc"]])), { from: "ent-dom-billing", to: "ent-dom-paycenter", relTypes: types, direction: "any", maxHops: 4 });
  assert.equal(merged.paths.length, 3, "a confirmed merge adds the shared-registrar route");
});

/* ── metrics ──────────────────────────────────────────────────────────── */

function e(id, from, to, directed = true, type = "t") {
  return { id, from, to, rel: { id, type, directed, review: "confirmed", evidence: { supporting: [], contradicting: [] } } };
}
test("metrics: self-loops, duplicates, density and components follow their stated definitions", () => {
  const nodes = ["a", "b", "c", "d"].map((id) => ({ id }));
  const edges = [e("1", "a", "b"), e("2", "a", "b"), e("3", "b", "a"), e("4", "b", "c", false), e("5", "c", "b", false), e("6", "c", "c")];
  const m = C.computeMetrics(nodes, edges);
  assert.equal(m.edgeRecords, 6);
  assert.equal(m.selfLoops, 1);
  assert.equal(m.duplicateRecords, 2, "a→b twice; undirected b—c / c—b is one pair");
  assert.equal(m.distinctPairs, 2);
  assert.equal(m.densityUndirected, +(2 / 6).toFixed(6));
  assert.equal(m.densityDirected, +(4 / 12).toFixed(6), "a→b, b→a, b→c, c→b");
  assert.deepEqual(m.degree.a, { in: 1, out: 2, undirected: 0, total: 3, selfLoops: 0, distinctNeighbors: 1 });
  assert.equal(m.degree.c.selfLoops, 1);
  assert.equal(m.degree.c.total, 2, "self-loop excluded from degree");
  assert.equal(m.componentCount, 2);
  assert.equal(m.isolated, 1);
  assert.deepEqual(m.components[0].ids, ["a", "b", "c"]);
  assert.equal(C.computeMetrics([{ id: "x" }], []).densityDirected, null, "density undefined below two entities");
});

test("analysis runs record reproducibility metadata", () => {
  const { ds, idx, fp } = load();
  const g = C.buildGraph(ds, idx, {});
  const run = C.runAnalysis({ name: "metrics", algorithm: "degree+wcc", params: { scope: "full" }, fingerprint: fp, scope: "full dataset" }, () => C.computeMetrics(g.nodes, g.edges), NOW);
  assert.equal(run.dataset_fingerprint, fp);
  assert.equal(run.executed_at, NOW.toISOString());
  assert.equal(typeof run.runtime_ms, "number");
  assert.equal(run.core_version, C.CORE_VERSION);
  assert.equal(run.result.nodeCount, ds.entities.length);
});

/* ── layouts ──────────────────────────────────────────────────────────── */

test("force layout is reproducible from its seed and respects pins", () => {
  const { ds, idx } = load();
  const g = C.buildGraph(ds, idx, {});
  const a = C.layoutForce(g.nodes, g.edges, { seed: 7 }).positions;
  const b = C.layoutForce(g.nodes, g.edges, { seed: 7 }).positions;
  const c = C.layoutForce(g.nodes, g.edges, { seed: 8 }).positions;
  assert.deepEqual([...a.entries()], [...b.entries()]);
  assert.notDeepEqual([...a.entries()], [...c.entries()]);
  const pinned = new Map([["ent-ip-shared", { x: 0.5, y: -0.25 }]]);
  const p = C.layoutForce(g.nodes, g.edges, { seed: 7, pinned }).positions;
  assert.deepEqual(p.get("ent-ip-shared"), { x: 0.5, y: -0.25 });
  const stepper = C.createForceLayout(g.nodes, g.edges, { seed: 7, iterations: 10 });
  assert.equal(stepper.step(4), false);
  assert.ok(stepper.progress() > 0 && stepper.progress() < 1);
  assert.equal(stepper.step(100), true);
});

test("radial layout: focus at centre, rings by hop distance with meaningful labels", () => {
  const { ds, idx } = load();
  const g = C.buildGraph(ds, idx, {});
  const r = C.layoutRadial(g.nodes, g.edges, { focus: "ent-ip-shared" });
  assert.deepEqual(r.positions.get("ent-ip-shared"), { x: 0, y: 0 });
  assert.equal(r.rings[0].label, "1 hop");
  const d1 = r.positions.get("ent-org-hosta");
  const d2 = r.positions.get("ent-org-registrar");
  assert.ok(Math.hypot(d1.x, d1.y) < Math.hypot(d2.x, d2.y));
  const overview = C.layoutRadial(g.nodes, g.edges, {});
  assert.equal(overview.mode, "type-sectors");
  assert.equal(overview.positions.size, g.nodes.length);
});

test("hierarchical layout refuses directed cycles instead of inventing an order", () => {
  const { ds, idx } = load();
  const g = C.buildGraph(ds, idx, {});
  assert.equal(C.layoutHierarchical(g.nodes, g.edges).ok, true);
  const cyc = C.layoutHierarchical([{ id: "a", type: "other", label: "a" }, { id: "b", type: "other", label: "b" }], [e("1", "a", "b"), e("2", "b", "a")]);
  assert.equal(cyc.ok, false);
  assert.match(cyc.reason, /cycle/i);
});

/* ── evidence ─────────────────────────────────────────────────────────── */

test("corroboration counts independent source groups, not records", () => {
  const { idx } = load();
  const a = C.assessEvidence(idx, idx.relationship.get("rel-billing-resolves").evidence);
  assert.equal(a.corroboration.records, 3);
  assert.equal(a.corroboration.independentGroups, 2, "the mirror republishes Provider A");
  assert.equal(a.corroboration.dependentRecords, 1);
  assert.equal(a.extraction.supplied.length, 0, "no confidence was supplied, so none is reported");
  const k = C.assessEvidence(idx, { supporting: ["obs-archive-kit", "obs-gone"], contradicting: [] });
  assert.deepEqual(k.missing, ["obs-gone"]);
  assert.equal(k.extraction.supplied[0].confidence, 0.72);
});

test("rule-based summaries cite only records that exist", () => {
  const { idx } = load();
  const known = C.knownIds(idx);
  for (const [kind, id] of [["relationship", "rel-billing-resolves"], ["claim", "clm-same-operator"], ["entity", "ent-dom-billing"]]) {
    const s = C.summarize(idx, kind, id);
    assert.ok(s.length >= 2, kind);
    s.forEach((x) => x.cites.forEach((c) => assert.ok(known.has(c), c)));
  }
});

/* ── exports ──────────────────────────────────────────────────────────── */

test("CSV cells neutralise spreadsheet formulas and escape delimiters", () => {
  assert.equal(C.csvCell("=1+1"), "'=1+1");
  assert.equal(C.csvCell("+SUM(A1)"), "'+SUM(A1)");
  assert.equal(C.csvCell("-2+3"), "'-2+3");
  assert.equal(C.csvCell("@cmd"), "'@cmd");
  assert.equal(C.csvCell("\tx"), "'\tx");
  assert.equal(C.csvCell('a,"b"'), '"a,""b"""');
  assert.equal(C.csvCell(-5), "-5", "real numbers are not text formulas");
  assert.equal(C.csvCell(null), "");
  const { ds } = load();
  const csv = C.relationshipsCSV(ds);
  assert.match(csv.split("\r\n")[0], /^id,type,from,to,directed,review/);
  assert.equal(csv.trim().split("\r\n").length, ds.relationships.length + 1);
  assert.match(csv, /rel-billing-vendor-guess,operated_by,.*,unknown,unknown/);
  assert.doesNotMatch(C.entitiesCSV(ds), /internal_case_owner/, "restricted attribute excluded");
});

test("JSON export removes restricted fields, records why, and re-imports", () => {
  const { ds, fp } = load();
  const out = C.exportDataset(ds, { now: NOW });
  assert.equal(out.export.source_fingerprint, fp);
  assert.deepEqual(out.export.restricted_fields_removed, ["ent-doc-pr0142.attributes.internal_case_owner"]);
  assert.notEqual(out.export.content_fingerprint, fp);
  const back = C.parseDataset(JSON.stringify(out));
  assert.ok(back.ok, JSON.stringify(back.errors));
  assert.equal(back.fingerprint, out.export.content_fingerprint);
  assert.equal(back.dataset.entities.find((x) => x.id === "ent-doc-pr0142").attributes.internal_case_owner, undefined);
});

test("evidence manifest hashes excerpts and reports missing records", () => {
  const { ds, idx } = load();
  const m = C.evidenceManifest(ds, idx, ["obs-sbx-kit", "obs-nope"], { now: NOW });
  assert.equal(m.items[0].excerpt_sha256, createHash("sha256").update(idx.observation.get("obs-sbx-kit").excerpt).digest("hex"));
  assert.equal(m.items[1].status, "missing from current dataset");
});

/* ── citations + brief ────────────────────────────────────────────────── */

test("citation validation rejects identifiers that do not exist", () => {
  const { idx } = load();
  const r = C.validateCitations("See [ref:obs-sbx-kit] and [ref:obs-invented] and [x].", C.knownIds(idx));
  assert.deepEqual(r.cited, ["obs-sbx-kit", "obs-invented"]);
  assert.deepEqual(r.invalid, ["obs-invented"]);
  assert.equal(r.ok, false);
});

function workedNotebook(ds) {
  let nb = C.createNotebook(ds, NOW);
  nb = C.Notebook.setQuestion(nb, "Is utilityco-billing.example run by the same operator as uc-paycenter.example?", "Fixture records only.", NOW);
  nb = C.Notebook.addHypothesis(nb, { label: "H1 Same operator", statement: "One actor controls both domains." }, NOW);
  nb = C.Notebook.addHypothesis(nb, { label: "H2 Unrelated operators", statement: "Shared hosting and a sold kit explain the overlap." }, NOW);
  for (const id of ["obs-sbx-kit", "obs-archive-kit", "obs-kitnote-public", "obs-pdnsa-ip-volume", "obs-gone-later"]) nb = C.Notebook.attachEvidence(nb, id, "", NOW);
  nb = C.Notebook.setAssessment(nb, "hyp-1", "obs-sbx-kit", "consistent", NOW);
  nb = C.Notebook.setAssessment(nb, "hyp-1", "obs-kitnote-public", "inconsistent", NOW);
  nb = C.Notebook.setAssessment(nb, "hyp-1", "obs-pdnsa-ip-volume", "inconsistent", NOW);
  nb = C.Notebook.setAssessment(nb, "hyp-2", "obs-kitnote-public", "consistent", NOW);
  nb = C.Notebook.addAnnotation(nb, "rel-paycenter-kit", "Model-extracted; verify the archive capture before relying on it.", NOW);
  nb = C.Notebook.addItem(nb, "open_questions", "Who registered utilityco-billing.example?", NOW);
  nb = C.Notebook.addItem(nb, "assumptions", "Sandbox hash is computed over identical bytes.", NOW);
  return nb;
}

test("notebook enforces rationale, reopening and append-only history", () => {
  const { ds } = load();
  let nb = workedNotebook(ds);
  assert.throws(() => C.Notebook.recordConclusion(nb, { hypothesis_id: "hyp-2", text: "Unrelated.", rationale: "  " }, NOW), /Rationale/);
  assert.throws(() => C.Notebook.reopenConclusion(nb, "why", NOW), /no recorded conclusion/);
  assert.throws(() => C.Notebook.setAssessment(nb, "hyp-1", "obs-ct-c1", "consistent", NOW), /Attach/);
  assert.throws(() => C.Notebook.setAssessment(nb, "hyp-1", "obs-sbx-kit", "probably", NOW));
  nb = C.Notebook.recordConclusion(nb, { hypothesis_id: "hyp-2", text: "Overlap is explained by shared hosting and a sold kit.", rationale: "Kit is publicly sold; address hosts 1,140 domains." }, NOW);
  assert.equal(nb.conclusion.state, "recorded");
  assert.throws(() => C.Notebook.removeHypothesis(nb, "hyp-2", NOW), /Reopen/);
  nb = C.Notebook.reopenConclusion(nb, "Archive record withdrawn in v1.1.0.", NOW);
  assert.equal(nb.conclusion.state, "reopened");
  assert.equal(nb.conclusion_history.length, 1);
  assert.equal(nb.conclusion_history[0].action, "reopened");
  nb = C.Notebook.recordConclusion(nb, { hypothesis_id: null, text: "Insufficient evidence to choose.", rationale: "Kit link now rests on one source." }, NOW);
  assert.equal(nb.conclusion_history.length, 2);
  nb = C.Notebook.detachEvidence(nb, "obs-kitnote-public", NOW);
  assert.equal(nb.matrix["hyp-1"]["obs-kitnote-public"], undefined);
  assert.equal(C.validateNotebook(nb).ok, true);
  assert.equal(C.validateNotebook({ schema: "x" }).ok, false);
});

test("matrix summary counts inconsistent evidence by independent group, not probability", () => {
  const { ds, idx } = load();
  const s = C.matrixSummary(workedNotebook(ds), idx);
  assert.deepEqual(s[0].counts, { consistent: 1, inconsistent: 2, neutral: 0, unassessed: 2 });
  assert.equal(s[0].inconsistentGroups, 2);
  assert.equal(Object.keys(s[0]).includes("probability"), false);
});

test("brief has every required section, valid citations and stated limitations", () => {
  const { ds, idx, fp } = load();
  let nb = workedNotebook(ds);
  nb = C.Notebook.recordConclusion(nb, { hypothesis_id: "hyp-2", text: "Unrelated operators.", rationale: "See matrix." }, NOW);
  const run = C.runAnalysis({ name: "Path analysis", algorithm: "constrained BFS", params: { maxHops: 4 }, fingerprint: fp, scope: "full dataset" }, () => 1, NOW);
  const b = C.buildBrief({ dataset: ds, index: idx, notebook: nb, runs: [Object.assign(run, { summary: "2 paths" })], now: NOW, viewSummary: "radial, all types" });
  assert.equal(b.ok, true, JSON.stringify(b.citations.invalid));
  for (const h of ["Investigative question", "Scope and dataset", "Key findings", "Supporting and contradicting evidence", "Methods", "Unresolved questions", "Limitations", "Review status"]) {
    assert.match(b.markdown, new RegExp("## \\d+\\. " + h), h);
  }
  assert.match(b.markdown, /SYNTHETIC DATASET/);
  assert.match(b.markdown, new RegExp(fp));
  assert.match(b.markdown, /\[ANALYST-ASSESSED\]/);
  assert.match(b.markdown, /\[OBSERVED\]/);
  assert.match(b.markdown, /\[HYPOTHESIZED\]/);
  assert.match(b.markdown, /\[DERIVED\]/);
  assert.match(b.markdown, /not probabilities/);
  assert.match(b.markdown, /Generated 2026-11-01T12:00:00.000Z/);
  assert.deepEqual(b.missingRefs, ["obs-gone-later"]);
  assert.doesNotMatch(b.markdown, /\[ref:obs-gone-later\]/, "missing records are named, never cited");
  assert.ok(b.citations.cited.includes("obs-sbx-kit"));
});

test("brief neutralises markup in analyst text", () => {
  const { ds, idx } = load();
  let nb = C.createNotebook(ds, NOW);
  nb = C.Notebook.setQuestion(nb, "<img src=x onerror=alert(1)>", "", NOW);
  const b = C.buildBrief({ dataset: ds, index: idx, notebook: nb, now: NOW });
  assert.doesNotMatch(b.markdown, /<img/);
  assert.match(b.markdown, /&lt;img/);
});

/* ── comparison ───────────────────────────────────────────────────────── */

test("snapshot diff separates added, not-present and modified records", () => {
  const a = load(V1_TEXT).ds, b = load(V2_TEXT).ds;
  const d = C.diffDatasets(a, b);
  assert.equal(d.sameDataset, true);
  assert.deepEqual(d.collections.entities.added, ["ent-ip-new"]);
  assert.deepEqual(d.collections.observations.added, ["obs-pdnsa-billing-02", "obs-pdnsb-paycenter-late"]);
  assert.deepEqual(d.collections.observations.notPresent, ["obs-archive-kit"]);
  const sbx = d.collections.observations.modified.find((m) => m.id === "obs-sbx-kit");
  assert.deepEqual(sbx.fields, ["extraction"], "extraction-only change");
  const imit = d.collections.relationships.modified.find((m) => m.id === "rel-billing-imitates");
  assert.deepEqual(imit.fields, ["review"]);
  const late = load(V2_TEXT).idx.observation.get("obs-pdnsb-paycenter-late");
  assert.ok(Date.parse(late.observed_at) < Date.parse(a.dataset.as_of), "newly collected, not newly occurring");
  assert.ok(d.caveats.some((c) => /does not mean/.test(c)));
});

/* ── view state ───────────────────────────────────────────────────────── */

test("view state validation", () => {
  const { idx } = load();
  assert.equal(C.validateView({ schema: C.VIEW_SCHEMA, layout: "radial", hops: 1, relTypes: null }, idx).ok, true);
  assert.equal(C.validateView({ schema: C.VIEW_SCHEMA, layout: "globe" }, idx).ok, false);
  assert.equal(C.validateView({ schema: C.VIEW_SCHEMA, hops: 5 }, idx).ok, false);
  assert.ok(C.validateView({ schema: C.VIEW_SCHEMA, focus: "ent-x" }, idx).warnings.length);
});
