# ClearGlass Interface System

How the site stays one system across 177 routes — what is shared, what is
deliberately not, and how a regression gets caught.

## What was already here

This is not a greenfield design system. The homepage-derived visual language
already existed and was already widely adopted before this pass:

| Layer | File | Role |
| --- | --- | --- |
| Tokens + components | `assets/css/cg-design-system.css` | Homepage-derived tokens (prism palette, glass surfaces, radii, motion) and the shared component layer |
| Token primitives | `tokens.css` | Namespaced `--cg-*` brand primitives |
| Accent remap | `theme.css` | Maps legacy per-page accent variables onto the blue-violet identity |
| Rhythm + cards | `brand-system.css` | Typography rhythm, card/panel treatment, CTA geometry |
| Interaction | `ui.css`, `buttons.css` | Focus rings, hover physics, button geometry |
| Navigation | `nav.js` | Injected glass top bar, product catalog, mobile drawer |
| Command layer | `control-surface.js` | Command cluster + palette on 35 pages |

**The homepage is a light "crystal/prism" theme** — white/off-white surfaces,
`Cormorant Garamond` + `Urbanist` + `IBM Plex Mono`, and a prism gradient
(`#38bdf8 → #a78bfa → #f472b6 → #fbbf24 → #34d399`). Any future token work
should extend that, not a dark palette.

## What this pass added

The visual layer was in good shape. The gaps were in **enforcement**,
**keyboard access**, and **content honesty**.

### 1. A site-wide adoption gate — `tools/design_system.py`

Consistency held only by convention, and convention had already failed: 54
pages were missing the token layer and 11 were missing the navigation entirely.
The generator enforces four contracts and is idempotent:

```bash
python3 tools/design_system.py            # apply fixes in place
python3 tools/design_system.py --check     # exit 1 if any route is stale (CI)
python3 tools/design_system.py --report    # regenerate DESIGN_SYSTEM_AUDIT.md
```

Discovery is **recursive**. An earlier version walked four hard-coded folders,
which is how `streaming-growth-command-center/` shipped outside every gate — no
tab icons, no logo, no link-graph entry. Whole subtrees that are legitimately
outside the public shell are named in `EXEMPT_DIRS` with reasons (`operations/`
regenerates and would lose injected tags; `checkout/` is a payment flow where
extra navigation is a conversion risk; `apps/`, `projects/` ship their own
shells).

| Contract | Enforced on |
| --- | --- |
| `assets/css/cg-design-system.css` is linked | every non-exempt route |
| `nav.js` is loaded | every non-exempt route |
| `cg-a11y.js` is loaded | every non-exempt route |
| Twitter/X card present | every indexable route |

Metadata is **derived, never invented**: cards are built from `og:*` first, then
`<title>`/`<meta name="description">`. A page with nothing to borrow is
reported, not given filler.

Exemptions live in `EXEMPT` / `NAV_EXEMPT` in the tool, each paired with a
reason, and a test asserts every exemption still points at a real page.

### 2. The keyboard contract — `cg-a11y.js`

The site runs **two navigation systems**. `control-surface.js` sets
`window.__cgNavLoaded = true` on purpose to supersede `nav.js` on 35 pages. That
is a legitimate product decision, but it meant the accessibility contract
depended on which nav a page happened to load — and the `control-surface.js`
pages shipped with **no skip link and no `aria-current` at all**.

`cg-a11y.js` is a small, dependency-free module that runs regardless of which
nav is active and guarantees:

- a **bypass link** ("Skip to main content") as the first tab stop (WCAG 2.4.1),
  with a target resolved even on pages authored without `<main>`;
- **`aria-current="page"`** on the active destination, in either nav's
  containers (`#cg-global-nav` / `.cgcs-*`);
- **external-link marking** (`rel="noopener noreferrer"`, `data-cg-external`).

It is idempotent and additive — on a `nav.js` page the skip link already exists
and the module leaves it alone. Because both navs inject asynchronously, active
route marking retries through a `MutationObserver` with a 6-second lifetime.

### 3. Navigation accessibility — `nav.js`

| Added | Why |
| --- | --- |
| `aria-current="page"` | Active route had no accessible signal |
| `visibility:hidden` on the closed catalog | **The closed mega-menu kept 76 links in the tab order** — a keyboard user had to tab the entire product catalog to reach the page |
| Real disclosure button (`aria-expanded`, `aria-controls`) | The catalog was hover/`:focus-within` only, with no way to close it |
| Escape + focus restore on the catalog | — |
| Focus trap, Escape, and focus restore on the mobile drawer | Drawer could be scroll-closed while focus was inside it |

> **Note for conflict resolution.** These calls were once lost: a merge kept the
> function *definitions* but restored the pre-contract `build()` body, so all of
> them sat as dead code for two releases — the drawer was untrapped and the
> catalog unopenable by keyboard, while the source still looked correct. The
> skip link survived only because `cg-a11y.js` is a separate module. When
> resolving conflicts in `build()`, keep the invocation block with the
> definitions; `tests/browser/nav-contract.mjs` fails if they drift apart.

### 4. One overlay per shortcut

`Cmd/Ctrl+K` had three claimants. `nav.js` shipped a palette; then
`global-nav-search.js` landed with site-wide search on the same chord; and
`aegis-omega.js` had a third. `platform.js` loads the latter two **together**,
so both opened on a single keystroke across the 43 pages that load it.

Resolved by giving the shortcut one owner:

- `global-nav-search.js` owns it — it is the discoverable one (visible control
  in the nav, plus `/`).
- The `nav.js` palette was **removed** rather than left as dead code.
- `aegis-omega.js` yields when `window.__cgGlobalNavSearch` is set. The check
  happens at keydown, not at bind time, so the outcome does not depend on which
  deferred script executes first.

`control-surface.js` and `guardian-command.js` also bind the chord but were left
alone: they never co-mount with the search, because it only attaches where a
primary nav exists and `control-surface.js` suppresses that nav. Verified in a
browser — `pricing.html` opens exactly one overlay.

### 5. Content honesty

Twelve instances across seven pages asserted authority the company does not
have. All were removed:

| Page | Was | Now |
| --- | --- | --- |
| `blog/index.html` | "military-grade command surface" | "defence-in-depth command surface" |
| `clearsight.html` | "Defense-grade computer vision" | "Production-grade computer vision" |
| `government.html` | "government-grade compliance" | "public-sector compliance" |
| `government.html` | "Request a classified briefing" | "Request a technical briefing" |
| `guardian.html` | `CG//SI//NF` (×2), "Classified · Eyes Only", "CLASSIFIED · COMMAND INTERFACE" | `CLEARGLASS`, "Governed · Access Controlled", "GOVERNED · COMMAND INTERFACE" |
| `clearglass-nexus.html` | `CG//SI//NF` + "CLASSIFIED · COMMAND INTERFACE" | `CLEARGLASS` + "GOVERNED · COMMAND INTERFACE" |
| `blog/frontier-…-biosecurity.html` | "CLASSIFIED BRIEFING · LEVEL: EYES ONLY" | "ANALYTICAL BRIEFING · OPEN-SOURCE" |
| `conduit.html` | "Classified-command motion" | "Command-grade motion" |
| `clearglass-ultra.html` | ticker: "GOVERNED ACTIONS ▲ 12,408", "APPROVAL LATENCY 3.2m", "WRAITH-OMEN CLASSIFIED" | "▲ APPROVAL-GATED", "HUMAN-IN-THE-LOOP", "HORIZON WARNING" |

`CG//SI//NF` imitates US intelligence control markings (SI = Special
Intelligence, NF = NOFORN). The `clearglass-ultra.html` ticker presented
invented telemetry as live status.

**Deliberately left alone** — these are accurate, not violations:

- `UNCLASSIFIED / NON-CLASSIFIÉ` banners on `index.html`, `government.html`,
  `procurement-legal-tech.html`, `percival-os.html`. They assert the *absence*
  of classification and are labelled demo instances.
- Ordinary prose: "classified as harmful", "hashed, classified and
  deduplicated", "open, unclassified doctrine".
- `blog/clearglass-platform-audit-2026.html` uses `"defense-grade"` in scare
  quotes to argue *against* the term.
- `counter-uas-commercialization-os.html` renamed its `CLASSIFIED` pipeline
  stage to `CATEGORIZED`. The original was the correct ML term
  (`DETECTED → CORRELATED → CLASSIFIED → REVIEWED`), but the page's subject
  matter made it ambiguous and the rename costs no meaning.

## Neon Glass System (v1.0, 2026-11-07)

### Why it exists

Every page above links `/assets/css/cg-design-system.css`, but `assets/` was
never uploaded to this repository. On 2026-11-07 that file, `glass.css`,
`future-buttons.css`, `cinematic-motion.css` and their three scripts were 404s
on 42 to 94 pages each: 530 failed CSS/JS requests in one pass over the site
at 375px. Nothing on the site depended on them, because they had never
loaded, so the system is built to be strictly additive.

### Files

| File | Holds |
| --- | --- |
| `assets/css/cg-design-system.css` | Tokens, layered global defaults, the safety rules, neon/status/scanline/grid/aurora components |
| `assets/css/glass.css` | `.cg-glass`, `.cg-glass-elevated`: states, solid fallback, preference handling |
| `assets/css/future-buttons.css` | `.cg-neon-button` and its variants |
| `assets/css/cinematic-motion.css` | Opt-in entrance reveal plus the `cg-low-power` contract `platform.js` sets |
| `assets/js/cg-design-system.js` | Hidden-tab pause; broken-image containment and a "CG" monogram for logo frames |
| `assets/js/future-buttons.js` | Pointer-tracked highlight on neon buttons (skipped on touch and reduced motion) |
| `assets/js/cinematic-motion.js` | IntersectionObserver reveal, staggered; never hides content without the runtime |
| `assets/css/mission-control.css` | First full page built on the tokens (`mission-control.html` was unstyled) |

### Rules that keep it safe on ~94 existing pages

- **Tokens** are `--cg-*`. Names that already existed keep their values: the
  `--cg-neon-cyan/blue/violet/magenta` triplets equal `ui.css`, and radius,
  spacing, font and motion tokens mirror `tokens.css`. A test fails on drift.
  `--cg-shadow` and `--cg-radius` belong to `brand-system.css` and are not redefined.
- **Global defaults** (focus ring, `pre` scrolling, long-word wrapping) live in
  `@layer cg-defaults`, which loses to every unlayered page rule.
- **Safety rules** are the only unlayered globals: reduced motion, the
  low-power contract, pausing animation in hidden tabs, hiding a broken
  image's spilled alt text (it stays exposed to assistive tech), and a ≤900px
  `overflow-x: clip` guard against sideways panning.
- **Components** are opt-in classes. Nothing restyles a page that doesn't use them.

### Palette and limits

One dominant neon (cyan `34,211,238`), one secondary (violet `167,139,250`),
one accent (magenta `244,114,182`). Green, amber and red (`--cg-success`,
`--cg-warning`, `--cg-danger`) are for status only, and danger is not the
accent. Text tokens on `--cg-bg-0`: `--cg-text` 16.9:1, `--cg-text-muted` 8.9:1,
`--cg-text-dim` 6.0:1. Backdrop blur is capped at 18px (`--cg-blur-sm/md/lg` =
6/12/18). Glow is for titles, primary actions, live status and metrics, never body text.

### Components

| Class | Use |
| --- | --- |
| `.cg-glass`, `.cg-glass-elevated`, `.cg-glass--pad` | Panels. Interactive glass lifts 2px; `.is-active`/`aria-current`/`aria-selected` and `.is-disabled`/`aria-disabled` states |
| `.cg-neon-border` (`--animated`, `--live`) | 1px masked gradient ring that sweeps or breathes |
| `.cg-neon-title` (`--gradient`), `.cg-neon-metric` | Headlines and key numbers |
| `.cg-neon-button` (`--secondary`, `--ghost`, `--danger`, `--sm`, `--lg`, `--block`) | Primary actions, 44px minimum |
| `.cg-status-live` (`.is-warning`, `.is-danger`, `.is-info`, `.is-idle`) | Live indicator with a transform/opacity pulse |
| `.cg-scanline` (`--sweep`), `.cg-grid-bg`, `.cg-aurora` | Ambient layers; `--sweep` clips its host, so keep it off popover owners |
| `.cg-reveal` / `[data-cg-reveal="fade"\|"scale"]` | Entrance motion on pages that load `platform.js` |

All of them respect `prefers-reduced-motion`, `prefers-contrast: more`,
`forced-colors` and print; glass also respects `prefers-reduced-transparency`.

### Repairs in the same pass

| Defect | Fix |
| --- | --- |
| Corner logo coin printed "ClearG…" alt text outside the circle (every non-home page); nav and homepage orbs showed broken-image icons or alt text | `logo-badge.js` and `nav.js` swap a failed logo for a "CG" monogram; `cg-design-system.js` does the same for brand marks in content |
| On phones the control-surface cluster ("Command Ctrl K") covered each page's own header | Icon-only below 720px (the button already had an `aria-label`); no keyboard hint on touch-only devices |
| Sticky nav re-blurred 34px behind a ~90%-opaque bar on every scroll frame | 18px, `saturate(1.6)` |
| Text pushed past the right edge on 26 pages at 320px and 17 at 375px | Root causes fixed: grid tracks of plain `1fr` (automatic minimum) blown out by nowrap content, header rows that could not wrap, `aspect-ratio` + `min-height` forcing a minimum width, a `content-box` card 36–64px wider than intended. Per-page fixes sit in one marked `<style data-cg-mobile-fit>` block; shared causes were fixed at source (`web-growth-system.css`, `editorial-visuals.js`) |
| `mission-control.html` rendered as raw browser-default HTML | `assets/css/mission-control.css`, built on the tokens |

`sw.js` `VERSION` was bumped to `cg-v67` so returning visitors drop cached copies.

### Checks

```bash
python3 -m pytest tests/test_neon_glass_system.py -q   # 29 contract tests (run in Baseline CI)
python3 -m http.server 8765 --bind 127.0.0.1 &
BASE=http://127.0.0.1:8765/ node tests/browser/neon-system.mjs   # 15 component checks
node tests/browser/layout-audit.mjs out.json 375                 # site-wide layout audit
```

Measured with `layout-audit.mjs` against the previous commit and this one, on
the 94 pages that load the system. Pages with text a visitor cannot reach:
26 → 0 at 320px, 17 → 0 at 375px, 7 → 1 at 768px, 3 → 0 at 1024px, 1 → 0 at
1440px, 0 → 0 at 1920px. No page got worse at any width. The 768px holdout is
`artemis-self-evolving-platform.html`, where `adaptive-action-bar.js` does not
move overflowing actions into its "More" menu. Across all 158 root pages,
same-origin 404 responses went from 769 to 251, and CSS/JS 404s from 530 to 12.

### Still open (needs the owner)

- **Brand images are not in the repo.** `assets/images/clearglass-logo.png`
  (87 pages), `clearglass-logo-256.webp` (54), `clearglass-holographic-seal.png`
  (favicon on ~100 pages, homepage hero), `assets/video/hero.mp4`. The monogram
  is a fallback, not a replacement. `icon.svg` states that it is separate from
  the company logo, so it was not substituted.
- **Pages whose own code is missing**: `products.html` (catalog CSS/JS and
  data fabric), `intelligence-interface.html` (page CSS/JS),
  `mission-control.html` (mission data and behaviour; the theme toggle does
  nothing yet), and `data/control-surface/runs.json` (37 pages). Rebuilding
  them would mean inventing product or mission data.
- **Two palettes.** `theme.css` forces every accent alias to crimson
  `#ff1b3d` with `!important`, including `--cyan`, `--yellow` and `--gold`,
  on 40 pages, while `tokens.css`, the favicon and this system are
  cyan/violet. A warning styled with `--yellow` renders as brand crimson,
  right next to `--danger`. Which palette is canonical is a brand decision.
- **Animation load.** 41–43 of the 94 in-system pages run more than 8 infinite
  animations at once (about 1,400–1,500 in total). They now pause in
  background tabs and stop under reduced motion or low power, but each page
  still needs its own pass.
- `adaptive-action-bar.js` overflow measurement (above); the control-surface
  cluster still overlaps the right edge of some page headers on phones.

## Verification

```bash
python3 -m pytest tests/test_design_system.py -q   # 18 contract tests
python3 -m pytest tests/ -q                         # full suite (1190 passed)
python3 tools/design_system.py --check              # adoption gate
python3 tools/internal_links.py --check             # link graph freshness
python3 -m ruff check .

# Browser-level behaviour (Playwright + the pre-installed Chromium)
npm i --no-save playwright
node tests/browser/nav-contract.mjs products.html   # 21 assertions
node tests/browser/a11y-contract.mjs pricing.html aegis.html sentinel.html
```

Browser tests must append `?skipboot=1` — the site's documented bypass for the
first-visit boot loader. Without it the harness measures `/loader.html` instead
of the page under test.

CI enforcement rides on the existing `CI / Python Tests` job: because
`tests/test_design_system.py` lives in `tests/`, `pytest tests/` fails the build
if any route drifts out of the system.

## Known gaps (not fixed here)

| Issue | Severity | Scope | Mitigation |
| --- | --- | --- | --- |
| 39 root pages have no `<main>` landmark | Medium | `pricing.html`, `aegis.html`, `sentinel.html`, `government.html`, … | The bypass link resolves a target regardless, so WCAG 2.4.1 is met. `cg-a11y.js` deliberately does **not** fake `role="main"` — the block holding the `<h1>` is often just the hero, and mislabelling a partial region is worse than the missing role. Needs markup edits per page. |
| Two navigation systems coexist | Medium | 35 `control-surface.js` pages vs 108 `nav.js` pages | The keyboard contract is now unified via `cg-a11y.js`; the *visual* chrome still differs. Consolidating is a larger product decision. |
| `index.html` has two `role="banner"` elements | Low | homepage | The classification-style strip and the header both claim the banner landmark. |
| Large inline `<style>` blocks | Low | `clearglass-nexus.html` (79 KB), `guardian.html` (74 KB), `index.html` (71 KB) | Not regressed by this work; extracting them is a separate performance pass. |
| `unpkg.com` third-party scripts | Low | 2 pages (maplibre-gl) | Pre-existing external dependency. |

## Rollback

Every change is additive and reversible.

```bash
# Full rollback of this branch
git revert <merge-commit>            # or: git checkout main -- .

# Roll back only the injected asset links / metadata, keeping the tooling
git checkout main -- '*.html' 'blog/*.html' 'offers/*.html' 'products/**/*.html'

# Roll back only the navigation accessibility work
git checkout main -- nav.js
rm cg-a11y.js
```

Removing `cg-a11y.js` from disk degrades gracefully: pages still load, the
`<script>` tag 404s, and the site returns to its previous behaviour. Removing
the `<script>` tags themselves is what `git checkout main -- '*.html'` does.

## Adding a page

1. Author the page with a `<main>` element and a single `<h1>`.
2. Add it to `PAGES` and a cluster in `tools/internal_links.py`, then run it.
3. Run `python3 tools/design_system.py` — it links the design system, the nav,
   the keyboard contract, and derives the social card.
4. Add the URL to `sitemap.xml`.
5. If the page must opt out, add it to `EXEMPT`/`NAV_EXEMPT` **with a reason** —
   a test enforces that.
