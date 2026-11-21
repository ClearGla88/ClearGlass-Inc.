# ClearGlassInc Artemis — Burlington Local SEO Plan

> **Updated 2026-11-21.** The quoted rules (F1 to F20) are in `BURLINGTON_POLICY_FACTS.md`, the measured state of the live site is in `BURLINGTON_EXPOSURE_BASELINE.md`, and the owner's steps are in `BURLINGTON_OWNER_ACTIONS.md`. Corrections to the July plan: Business Profile Q&A is gone (F9, F10); FAQ rich results are gone (F13); review requests must never be filtered by NPS or sentiment (F8); this repository is not the published site.

## Step 0: three gates before any local work

1. **Publishing source.** Find the repository that publishes www.clearglassinc.com. It isn't this one: the live sitemap and homepage differ from the copies here. Every page, schema or link change below goes into the publishing repository.
2. **Business Profile eligibility.** A profile needs in-person contact with customers during stated hours (F1). If ClearGlass meets clients only remotely, it isn't eligible. In that case the map-pack and geo-grid parts of this plan don't apply, and the work is organic search, the Burlington page, content and community. If it is eligible, set it up as a service-area business with the address hidden (F2), no virtual office (F3), and a service area within about two hours' drive (F4).
3. **One name.** The profile name has to be the real-world name used on the website and stationery (F5). The live site uses "ClearGlass Inc." 82 times and "ClearGlass Inc" 6 times, including on the homepage. Pick one. "ClearGlassInc Artemis" is a product name, not the business name.

Distance is one of Google's three main local factors and can't be changed (F6). Expect the Burlington core to respond first and the secondary markets slowly or not at all. Nobody can pay for local placement (F7).

## Principles and success contract

Win local visibility through accurate business information, useful local content, real community participation, and measurable technical quality. Never keyword-stuff a business name, fabricate a location/review/event, gate reviews by sentiment, mass-produce doorway pages, or buy manipulative links. Targets and baseline rules are defined in `BURLINGTON_EXPOSURE_BASELINE.md`.

## Google Business Profile

**Foundation (owner-approved):** verify the real-world business name, eligible address/service-area model, phone, website, hours, holiday hours, and primary/secondary categories against current Google rules. Keep one source-of-truth record. Add only services actually delivered. Use UTM-tagged website links and test them.

**Cadence:** prepare two useful posts weekly and an optional third event-led post. Rotate: local problem/answer, evidence-backed service explanation, rights-cleared case insight, team/community contribution, and article excerpt. Check image rights, alt-text equivalent/caption, claims, dates, CTA destination, and expiration before approval. A named owner publishes; automation records the exact approved digest.

**Reviews:** a completed engagement triggers an eligibility check → consent/channel preference → one neutral request → one bounded reminder → stop. Ask all eligible customers consistently and never offer incentives. Completion is the only trigger. An NPS score or sentiment check that decides who gets asked is selective solicitation, which Google prohibits (F8). Emailed requests rely on the two-year relationship window after a purchase (F18) and need an unsubscribe that lasts 60 days and takes effect within 10 business days (F20).

**Questions:** Business Profile Q&A can no longer be managed. The API was discontinued on November 3, 2025 (F9), and Maps answers questions about places with an AI feature (F10). Put the answers buyers need on the profile's description and services and on the Burlington page. Suppression, withdrawal, delivery, and response state are auditable. Draft responses acknowledge specifics without disclosing customer or project information. Human approval is mandatory before sending or posting.

## Website localization

The live site already has one Burlington-targeted page, `/seo-authority-hub.html`. Its title names Burlington, but its H1 doesn't, and its URL names an SEO tactic. Rebuild it as the Burlington service page at a URL that says what it is, put Burlington in the H1, and leave an instant meta refresh at the old URL. GitHub Pages can't send server-side redirects, and Google treats an instant meta refresh as permanent (F15). Don't create near-identical Oakville, Hamilton, Milton or Dundas pages: pages targeted at cities that funnel users to one page are doorway abuse (F12). Add a city page only when it has its own clients, evidence and demand. Each valid page needs distinct local problem framing, verified delivery details, real case evidence with rights, travel/service constraints, visible FAQs, useful internal links, and one clear lead CTA. Avoid embedded maps that assert an office that does not exist.

Technical gate: indexable canonical; unique title/H1/meta; mobile-first layout; keyboard and focus QA; reduced motion; image dimensions/compression; passing applicable Core Web Vitals; valid sitemap; no broken links; truthful `Organization`, eligible `LocalBusiness`, `Service`, `BreadcrumbList`, and visible-content-only FAQ/Event schema. Never emit aggregate ratings or an address or hours the source of truth doesn't support. A business's own reviews in its own Organization or LocalBusiness markup aren't eligible for stars anyway (F14). FAQPage markup no longer produces a rich result (F13), so write FAQs for readers. If the publishing repository has `tools/internal_links.py`, regenerate the related-link blocks with it. This repository doesn't have it. Check the live site after every release with `python3 tools/local_seo_audit.py --live https://www.clearglassinc.com`.

## Content clusters

Publish one or two evidence-led articles monthly, then connect them to the relevant service and location page. Initial hypotheses:

1. AI automation readiness for Burlington/Halton SMEs.
2. Cybersecurity governance for Ontario professional services.
3. Practical AI risk controls for local manufacturers.
4. How to evaluate an automation architecture partner.

Every brief includes audience, query evidence, primary page, original contribution, subject-matter reviewer, sources, claims register, CTA, update date, and success metric. Local references must add substance, not decorative keyword density.

## Citations and earned authority

Create a canonical NAP/service-area record and audit Google, Apple Business Connect, Bing Places, Yelp, YellowPages, chamber/BIA and eligible industry profiles. Record URL, owner, credentials custodian, last verified date, inconsistency, correction state, and evidence. Prioritize official and relevant sources; do not create duplicates. Earn mentions through workshops, original local datasets, expert commentary, community service, and co-authored guidance—not payment for PageRank.

## 90-day execution

| Window | Work | Exit gate |
|---|---|---|
| Days 1–14 | complete baseline; verify GBP truth; technical crawl; fix critical index/schema/NAP issues; configure governed review drafts; publish one justified location page and 1–2 reviewed articles | evidence owner, policy review, accessibility/schema/link checks |
| Days 15–45 | two GBP drafts/week; social cadence; 2–3 articles; five tailored partnership drafts; first fixed grid scan | exact artifacts approved; attribution works; no policy incidents |
| Days 46–90 | prioritize red-zone/user-demand gaps; improve winning formats; add pages only when justified; seek 1–2 genuine mentions; monthly grid comparisons | measured outcome, experiment disposition, rollback-ready release |

## Experiments, monitoring, rollback

Pre-register hypothesis, primary metric, guardrails, cohort, minimum duration/sample, and stopping rule. Never serve deceptive crawler variants. Monitor indexation, GBP warnings, incorrect facts, leads, conversion, CWV, grid distribution, unsubscribe/complaint rates, and operator overrides. An incorrect claim, consent failure, GBP warning, accessibility regression, or material performance regression stops the experiment. Restore the last approved page/profile package, preserve the audit trail, and open a root-cause action.
