// Deterministic generator for scale-test datasets (synthetic, reserved
// namespaces only: .example domains and RFC 5737 documentation addresses).
// Used by bench.browser.cjs. Output validates against clearglass.sentinel/1.
"use strict";

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const RANGES = ["192.0.2.", "198.51.100.", "203.0.113."];
const REL_TYPES = ["resolves_to", "registered_via", "mentions", "names_domain", "allocated_to", "links_to"];

function generate(n, seed = 42, relPerEntity = 2) {
  const rand = mulberry32(seed);
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];
  const ipCount = Math.min(Math.round(n * 0.12), 762);
  const orgCount = Math.max(2, Math.round(n * 0.08));
  const docCount = Math.max(1, Math.round(n * 0.08));
  const certCount = Math.max(1, Math.round(n * 0.1));
  const domCount = n - ipCount - orgCount - docCount - certCount;
  const entities = [];
  for (let i = 0; i < domCount; i++) entities.push({ id: "ent-d" + i, type: "domain", label: "d" + i + ".example" });
  for (let i = 0; i < ipCount; i++) entities.push({ id: "ent-ip" + i, type: "ip", label: RANGES[i % 3] + Math.floor(i / 3 + 1) });
  for (let i = 0; i < orgCount; i++) entities.push({ id: "ent-o" + i, type: "organization", label: "Organisation " + i + " (fictional)" });
  for (let i = 0; i < docCount; i++) entities.push({ id: "ent-doc" + i, type: "document", label: "Report " + i + " (fictional)" });
  for (let i = 0; i < certCount; i++) entities.push({ id: "ent-c" + i, type: "certificate", label: "Certificate " + i + " (fictional)" });
  const sources = [];
  for (let i = 0; i < 12; i++) sources.push({ id: "src-" + i, title: "Generated source " + i, kind: "generated", independence_group: "grp-" + (i % 8), collected_at: "2026-10-01T00:00:00Z", assessment: { reliability: pick(["A", "B", "C", "unknown"]), basis: "Generated for scale testing." } });
  const observations = [], relationships = [];
  const relCount = Math.round(n * relPerEntity);
  const base = Date.parse("2026-01-01T00:00:00Z");
  for (let r = 0; r < relCount; r++) {
    const a = entities[Math.floor(Math.pow(rand(), 1.6) * entities.length)];
    let b = entities[Math.floor(rand() * entities.length)];
    if (b === a) b = entities[(entities.indexOf(a) + 1) % entities.length];
    const dated = rand() > 0.08;
    const t = new Date(base + Math.floor(rand() * 270) * 86400000).toISOString().replace(".000", "");
    const oid = "obs-" + r;
    observations.push({ id: oid, source_id: pick(sources).id, location: "row " + r, excerpt: a.label + " " + "rel " + r + " " + b.label, about: [a.id, b.id], observed_at: dated ? t : null, collected_at: "2026-10-01T00:00:00Z", ingested_at: "2026-10-02T00:00:00Z", extraction: { method: "parser", version: "gen 1", confidence: null } });
    relationships.push({ id: "rel-" + r, type: pick(REL_TYPES), from: a.id, to: b.id, directed: rand() > 0.1, semantics: "Generated.", review: pick(["unreviewed", "confirmed", "confirmed", "disputed"]), evidence: { supporting: [oid], contradicting: [] }, first_observed: dated ? t : null, last_observed: dated ? t : null });
  }
  const claims = [];
  for (let i = 0; i < Math.max(1, Math.round(n / 20)); i++) claims.push({ id: "clm-" + i, statement: "Generated claim " + i, kind: pick(["observed", "derived", "hypothesized"]), status: "unresolved", review: "unreviewed", about: [entities[i % entities.length].id], evidence: { supporting: ["obs-" + i], contradicting: [] } });
  const merge_candidates = [];
  for (let i = 0; i + 1 < orgCount && merge_candidates.length < Math.max(1, Math.round(n / 100)); i += 2) merge_candidates.push({ id: "mc-" + i, entities: ["ent-o" + i, "ent-o" + (i + 1)], criteria: ["Generated candidate."] });
  return {
    schema: "clearglass.sentinel/1",
    dataset: { id: "ds-scale-" + n, title: "Scale test — " + n + " entities (generated)", version: "1.0.0", synthetic: true, as_of: "2026-10-02T00:00:00Z", description: "SYNTHETIC. Generated for performance measurement only." },
    sources, entities, observations, relationships, claims, merge_candidates
  };
}
module.exports = { generate };
