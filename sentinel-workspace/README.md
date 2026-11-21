# Sentinel Workspace

An evidence-driven investigation workspace for ClearGlass Sentinel: [`/sentinel-workspace.html`](../sentinel-workspace.html).

**Status:** a working vertical slice. It is a static page that runs entirely in the browser, with no backend, accounts, AI model or external services. It ships with one **synthetic** training dataset whose entities, records, hashes and times are all fictional. It has not had a security review and it is not production-certified. The existing live geospatial console at `sentinel.html` is unchanged apart from the corrections listed under "Changes to existing Sentinel pages", and it links here.

## The loop it supports

```
LOAD OR IMPORT DATA → INSPECT GRAPH → SELECT ENTITY OR RELATIONSHIP → OPEN EVIDENCE
→ ATTACH TO INVESTIGATION → WEIGH HYPOTHESES → RECORD CONCLUSION → EXPORT BRIEF
```

Every step is covered by `tests/sentinel_workspace/e2e.browser.cjs` (24 checks on desktop and an iPhone 13 profile).

| Mode | What works |
|---|---|
| **Explore** | Graph (radial, force-directed, hierarchical), accessible tables (entities, relationships, claims, sources), search across the full dataset, entity-type, relationship-type, review-state and time-window filters, 1- and 2-hop isolation, pinning, layout undo, selection history (Back), constrained path analysis, graph metrics with "Explain this result", and entity-resolution decisions. |
| **Investigate** | Question and scope, competing hypotheses, a hypothesis–evidence matrix, assumptions, unresolved questions, annotations, and a conclusion that requires a rationale and can be reopened. History is append-only. |
| **Compare** | Snapshot diff by record ID, showing added, not present and modified records. It separates newly collected from newly occurring, and extraction changes from source changes. The inspector shows before and after values for the selected record. |
| **Brief** | A Markdown brief with validated citations, plus a versioned JSON graph, entity and relationship CSV, an evidence manifest, view state and an SVG image of the graph. |

## Implementation map

| File | Role |
|---|---|
| `../sentinel-workspace.html` | Page shell and strict Content-Security-Policy (`default-src 'self'`; no inline script or style). |
| `core.js` | All analytical rules as pure functions: schema validation, normalisation, SHA-256 fingerprint, index, merge resolver, graph projection and filters, path finding, metrics, layouts, evidence assessment, rule-based summaries, citation validation, CSV/JSON/manifest exports, snapshot diff, notebook operations and the brief. No DOM, no network, and no clock unless one is passed in. |
| `app.js` | DOM, interaction and persistence. Data is inserted with `textContent` and never with `innerHTML`. |
| `layout-worker.js` | Runs force layout in a Web Worker. Falls back to time-sliced main-thread work where workers are unavailable. |
| `workspace.css` | Visual system. Colour never carries meaning alone: shapes, type codes, line styles and text labels carry it too. |
| `fixtures/lookalike-domain-v1.json`, `-v2.json` | Synthetic training scenario with two snapshots. Domains use `.example` (RFC 2606); addresses use documentation ranges (RFC 5737). |
| `../tests/sentinel_workspace/core.test.mjs` | Unit tests for `core.js` (Node built-in test runner, no dependencies). Runs in CI. |
| `../tests/sentinel_workspace/e2e.browser.cjs` | Browser journey (Playwright). Run locally. |
| `../tests/sentinel_workspace/bench.browser.cjs`, `gen_dataset.cjs` | Benchmarks and the deterministic scale-dataset generator. |

## Run it

```bash
python3 -m http.server 8000          # from the repository root; any static server works
# open http://localhost:8000/sentinel-workspace.html
```

Opened from `file://`, browsers block reading the bundled dataset; the page says so and offers **Import**. Imports and everything else still work.

```bash
node --test tests/sentinel_workspace/core.test.mjs   # unit tests (CI runs these)
node tests/sentinel_workspace/e2e.browser.cjs [dir]  # browser journey; needs Playwright + Chromium
node tests/sentinel_workspace/bench.browser.cjs      # benchmarks
```

## Data contract — `clearglass.sentinel/1`

A dataset is one JSON object. Every record has an `id` matching `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, unique across the whole file. Unknown keys are ignored (with a warning) and never reach rendering or export.

| Collection | Required fields | Notes |
|---|---|---|
| `dataset` | `id`, `title`, `version`, `synthetic` (boolean), `as_of` (time or `null`) | `export_policy.restricted_attribute_keys` lists entity attributes removed from every export. |
| `sources` | `id`, `title`, `kind`, `assessment.reliability` (`A`–`F` or `unknown`), `assessment.basis` | `uri` must be http(s). `independence_group` marks sources that are not independent, such as a mirror of another feed. It defaults to the source's own id. |
| `entities` | `id`, `type`, `label` | Types: person, organization, domain, ip, system, document, account, certificate, topic, other. `attributes` values are scalars. `original_ids` preserve upstream identifiers. |
| `observations` (evidence) | `id`, `source_id`, `excerpt`, `about[]`, `observed_at`, `collected_at`, `ingested_at`, `extraction.method` | The three time keys **must be present**; `null` means unknown. `extraction.confidence` is `null` (not supplied) or a number from 0 to 1. |
| `relationships` | `id`, `type`, `from`, `to`, `directed`, `review`, `evidence.supporting[]`, `evidence.contradicting[]`, `first_observed`, `last_observed` | `review`: unreviewed, confirmed, disputed or rejected. `semantics` and `derivation` explain what the link means and how it was made. |
| `claims` | `id`, `statement`, `kind`, `status`, `review`, `about[]`, `evidence` | `kind`: observed, derived, hypothesized or analyst-assessed. `derivation.inputs` reference other records. |
| `merge_candidates` | `id`, `entities[≥2]`, `criteria[≥1]` | Proposals only. Analyst decisions live in the notebook, never in the dataset. |

Limits: 5 MB per file (checked before the file is read), 5,000 entities, 20,000 relationships, 20,000 observations, 4,000 characters per text field, and 12 levels of nesting. The keys `__proto__`, `constructor` and `prototype` are refused anywhere in the file. Time values are ISO 8601 dates, or date-times with a time zone. At two relationships per entity plus one observation each, the 5 MB limit binds at about 4,000 entities, before the entity limit.

## Analytical rules (all in `core.js`)

- **Fingerprint.** SHA-256 over canonical JSON (sorted keys) of the normalised dataset, excluding any `export` block. Every analysis result, export and brief records it.
- **Scope.** The strip always says whether you see the *full dataset* or a *visible subgraph*, with hidden counts and the reason for each. A selected entity that filters would hide stays visible and is marked.
- **Time window.** A relationship passes if its observed interval definitely overlaps the window. If the answer depends on an unknown end or start, the overlap is *uncertain*, and it passes only when "include unknown or partly known timing" is on. A missing `last_observed` is not read as "ongoing".
- **Entity resolution.** Nothing merges without an analyst decision and a rationale. Name similarity alone is flagged as insufficient. The surviving id is the alphabetically first member, so results don't depend on decision order. Decisions are appended and can be undone. Original ids remain.
- **Paths.** A constrained breadth-first search returns all fewest-hop paths, up to 20, under allowed types, review states, direction (follow the arrow or either way), maximum hops and an optional time window. Each step states why it qualifies. A fewest-hop path is not the strongest, likeliest or causal path.
- **Metrics.** Degree counts relationship records in scope, with self-loops counted separately. Distinct neighbours ignore duplicates and direction. Undirected density is distinct pairs ÷ n(n−1)/2; directed density is distinct ordered pairs ÷ n(n−1), where undirected records count in both directions. Components are weakly connected. Both densities are undefined below two entities. No community detection or centrality beyond degree is run. Results go stale, visibly, when filters change.
- **Layouts.** Radial: type sectors, or rings by hop distance from the focus, labelled "1 hop", "2 hops" and "not connected in view". Force: seeded Fruchterman–Reingold, reproducible from seed and pins; above 600 entities, repulsion uses a neighbourhood grid, which is an approximation and is reported. Hierarchy: refuses to draw when directed cycles exist. There is no geographic view, because the data model has no location field.
- **Evidence facets.** These are separate, never one gauge: extraction confidence (only as supplied), source reliability and its basis, independent corroboration (records vs independence groups), freshness relative to `as_of`, analyst review, and model provenance. Unknown is shown as unknown.
- **Hypothesis matrix.** Each item is marked consistent, inconsistent or neutral. The workspace shows counts and the number of independent source groups behind the inconsistent items. It never computes a probability.
- **Layers.** OBSERVED (sources), DERIVED (computed), HYPOTHESIZED (candidate explanations) and ANALYST-ASSESSED (judgements) are tagged in the interface and in the brief.
- **Brief citations.** Citations take the form `[ref:<id>]`. Each one is checked against the loaded dataset before export, and an invalid one blocks the export. References to records missing from the current version are named but not cited.

## Data handling and security

- **Network:** the page loads only its own files. CSP `connect-src 'self'`; no analytics or telemetry. Source links open only on click, in a new tab, with `rel="noopener noreferrer"`.
- **AI:** none is configured. Summaries are rule-based and cite record ids. `validateCitations` exists so a future model integration can be held to the same check.
- **Storage:** the notebook and view state live in `localStorage` under `cg.sentinel.ws.v1.*`, keyed by dataset id. Imported datasets stay in memory only. **Privacy → Delete all local workspace data** removes every key. Browser storage is editable, so it is not tamper-evident; exports are not signed.
- **Logs:** "Activity" is session-only UI history. It carries ids and counts, never excerpts or attribute values. It is not an application event log or a security audit record.
- **Exports:** restricted attributes are removed and the removal is recorded. CSV cells beginning with `= + - @`, tab or CR are prefixed with `'`. Markdown escapes `<` and `>`.
- **Access control:** none. The page cannot enforce who sees what; it says so in the Privacy dialog.
- **Service worker:** `/sentinel-workspace/` files are network-first, so `core.js`, `app.js` and the fixtures always come from the same deploy. The cached copy serves only as the offline fallback.

## Accessibility

Skip link; landmark regions; native `<dialog>` with focus return; roving-tabindex keyboard navigation in the graph (arrows, Home and End, Enter, Escape) that keeps focus after selection; `/` opens search and Alt+← goes back; a sortable table alternative with `aria-sort`; a resizable inspector separator with keyboard support; reduced-motion and forced-colours support; status text never relies on colour alone; dock and mode buttons are at least 44×34 px (checked in the e2e test). The workspace has not been tested with a real screen reader.

## Changes to existing Sentinel pages (Gate A — truthful foundation)

| Where | Was | Now |
|---|---|---|
| `sentinel.html` deny message | "audit ref … · logged · escalated to human review" (nothing is logged or escalated) | "ref … · shown in this page's timeline only · not sent or stored anywhere" |
| `sentinel.html` report | "Confidence: HIGH (authoritative public feeds)" | "Basis: public USGS and NWS feeds as retrieved in this session. No confidence score is computed." |
| `sentinel.html` report and PFAS export | random id labelled "Audit" / "Audit ref" | "Ref" / "Reference", stating it is not an audit-log entry (`audit_ref` JSON key kept for compatibility, with a note) |
| `sentinel.html` header pill | blinking "FAIL-CLOSED · ARMED" | static "POLICY GATE · FAIL-CLOSED", with a tooltip saying it is a client-side rule |
| `sentinel.html` agent-mesh overlay | green "live" dots on target-state nodes | hollow markers, with the badge "Target-state blueprint · not provisioned" |
| `sentinel.js` concierge | "Confidence: High" on keyword matches | "Basis: keyword match to a published page" |

## Not implemented (deferred)

- **AI assistance (Gate D):** no model is configured, so none is simulated. A server-side integration with citation validation, scope display and approval for state changes would be needed first.
- **Aggregation for large graphs:** there is no community detection or cluster collapsing. Above about 1,000 entities, the SVG becomes slow to style and paint (see the benchmarks); use filters, isolation or the table.
- **Cohort comparison** (filtered group A vs group B) and a PNG export; the SVG export is provided.
- **Server-side storage, multi-analyst review, signed exports and audit logging:** all require a backend and real authorization.
- **Real data connectors:** import is file-based. The live feeds in `sentinel.html` are not wired into this graph model.

## Known limitations and risks

- With a single dataset, all evidence about the bundled scenario is synthetic. Do not read conclusions from it about any real organisation.
- Reliability ratings and claim statuses come from the dataset author; the workspace displays them but does not re-assess them.
- Label placement uses estimated text widths, so long labels can overlap in dense regions. Labels thin out as you zoom out.
- The CI job runs the core unit tests and syntax checks only. The browser journey and benchmarks need Playwright and are run by hand.
- Benchmark numbers come from one headless Chromium run on one machine (below). They are measurements, not guarantees.
- Above about 1,000 entities, the first draw takes several seconds, because the browser styles and paints a large SVG.

## Benchmarks

Measured on 2026-11-19 with `node tests/sentinel_workspace/bench.browser.cjs`. Conditions: 4× Intel Xeon @ 2.10 GHz, 16 GiB, Linux, Node 22.23.4, headless Chromium 153 at 1440×900. Datasets of 250 or more entities are generated (`gen_dataset.cjs`, seed 42, two relationships and two observations per entity). The 5,000-entity set uses 1.5 relationships per entity, because two per entity exceeds the 5 MB import limit. Each figure is a single run on one machine; treat it as an indication, not a guarantee. No performance targets were set in advance.

**Core analysis in Node (best of 3, ms)**

| Entities | Relationships | File | Parse + validate | Build graph | Metrics | Path search | Radial layout | Force layout |
|---|---|---|---|---|---|---|---|---|
| 20 (fixture) | 22 | 38 KB | 2.2 | 0.06 | 0.08 | 0.07 | 0.03 | 10 (300 iterations) |
| 250 | 500 | 0.3 MB | 28 | 1.0 | 1.8 | 0.7 | 0.3 | 75 (200) |
| 1,000 | 2,000 | 1.2 MB | 81 | 2.7 | 8.6 | 2.2 | 1.0 | 356 (200, grid approx.) |
| 2,500 | 5,000 | 3.0 MB | 169 | 3.2 | 12 | 6.7 | 0.7 | 855 (120, grid approx.) |
| 5,000 | 7,500 | 4.6 MB | 350 | 7.2 | 26 | 6.2 | 1.6 | 1,760 (120, grid approx.) |

**In the page (headless Chromium, one run each)**

| Entities | Import → graph drawn | SVG elements | Selection handler | Force layout, wall time | JS heap |
|---|---|---|---|---|---|
| 20 | 59 ms | 294 | 9.9 ms | 35 ms | 4.1 MB |
| 250 | 333 ms | 5,027 | 22 ms | 187 ms | 11.9 MB |
| 1,000 | 2.3 s | 10,039 | 43 ms | 2.6 s | 10.0 MB |
| 2,500 | 8.0 s | 25,063 | 82 ms | 12.1 s | 14.7 MB |
| 5,000 | 19.4 s | 45,102 | 161 ms | 34.5 s | 29.7 MB |

How to read these:

- **Selection handler** is the synchronous time from a synthetic pointer event to the updated classes and inspector. It does not include the browser's next paint.
- **Force layout, wall time** includes redrawing the SVG with the new positions. The layout itself runs in a Web Worker, and its compute time is roughly the Node column.
- **JS heap** is measured after load. It excludes DOM and rendering memory and varies with garbage-collection timing.
- **Where the time goes:** a CPU profile of the 1,000-entity import attributes about 1.4 s of 2.2 s to the browser's own style, layout and paint of the SVG, not to workspace JavaScript.

Two changes came out of these measurements:

1. **Force layout moved off the main thread.** Time-slicing the layout across animation frames made 2,500 entities take 44.8 s, because every frame also repainted the SVG. In a Web Worker it takes 12.1 s, most of it the final redraw.
2. **Edges are lighter above 600 relationships.** Each edge is drawn as one path, with labels and evidence badges added only for selected or incident edges. This halved the element count.

**Practical range:** up to about 1,000 entities the workspace stays interactive. Beyond that the first draw takes several seconds, and canvas or WebGL rendering, or aggregation, would be needed (deferred). Use filters, isolation or the table for large datasets.
