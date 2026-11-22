# Burlington Exposure Program — Owner Actions

Only the owner can do these. Agents can't create a Business Profile, export account data, or send outreach. Do them in this order. The time column is the owner's own time.

Evidence for every claim below: `burlington-exposure/audits/2026-11-21-live.md`, `baseline_metrics.json` and `BURLINGTON_POLICY_FACTS.md`.

## What the 2026-11-21 check changed

1. **This repository does not publish www.clearglassinc.com.** The live site is served by GitHub Pages, but its sitemap (176 URLs) and homepage differ from the copies here. All 8 URLs listed only in this repository's 84-URL sitemap return 404 live. The decisive test: `main` merged fixes to two canonical tags at 18:54 UTC on 2026-11-21, and about four hours later the live pages still showed the old tags and a Last-Modified date of 2026-10-28. Edits made here don't reach the public site.
2. **The live site is healthy.** All 177 sitemap URLs return 200. There are no structured-data parse errors and no phone or locality conflicts.
3. **Burlington is barely on the site.** One live page has Burlington in its title: `/seo-authority-hub.html`. Its H1 doesn't mention Burlington and its URL names an SEO tactic, not a service. `/burlington.html` returns 404.
4. **The name and email are inconsistent.** The homepage's structured data says "ClearGlass Inc". The other 82 uses say "ClearGlass Inc.". The business email in the live structured data is a personal iCloud address.
5. **No Business Profile is on record.** No profile, analytics or social export exists, so every performance number in the plan is still null. That's correct: nothing has been measured yet.
6. **This repository's rebuilt homepage has no Burlington signal.** Its structured data carries only the name "ClearGlass Inc.": no phone, email, address or service area. Its text never mentions Burlington. The live homepage lists Burlington in its service area and mentions it 6 times. If this rebuild is ever published as it stands, the homepage's local signal goes away. Supply the locality and service area through `website/site_config.py` before that happens.

## Actions

| # | Action | Time | Unblocks |
|---|---|---|---|
| 1 | Name the repository and branch that publish www.clearglassinc.com. Check Settings, then Pages, in each candidate repository. A canonical tag on `/procurement-legal-tech.html` points to `clearglassinc.github.io`, so start there. `[CONFIRM]` | 5 min | All site work |
| 2 | Decide on Business Profile eligibility: do you meet clients in person during stated hours (F1)? **Yes:** create or claim a service-area profile with the address hidden (F2), named exactly as on the website (F5), serving Burlington, Halton and Hamilton (F4), with only the services you actually deliver. **No:** drop the geo-grid objective and compete in organic results. Write the decision and the reason into `MISSION_OBJECTIVES.json`. `[DECISION REQUIRED]` | 10 min to decide; verification is Google's timeline | Geo-grid, reviews, citations |
| 3 | Pick one business name ("ClearGlass Inc." is used 82 of 88 times) and one business email on clearglassinc.com, then fix the live homepage's structured data in the publishing repository. | 10 min | Name and email consistency |
| 4 | Export the baselines into a private folder (not this public repository): GA4 sessions by city and landing page for the last 90 days, and Search Console queries and pages for the last 3 months. An agent turns them into `baseline_metrics.json` values with evidence references. | 20 min | Every relative target |
| 5 | Approve the keyword set and one grid (`geo_grid_baseline.json`, `proposed_grids`), choose a licensed rank tracker, and run the first export. If the profile's location is your home, keep that grid and its runs outside this repository. | 30 min plus vendor setup | Geo-grid baseline |
| 6 | Approve the Burlington page brief: services sold, proof you can show, contact, URL. An agent then builds it in the publishing repository, with an instant meta refresh from `/seo-authority-hub.html` (F15). | 15 min review | The largest on-site lever |
| 7 | Approve and send the two workshop proposals in `BURLINGTON_OUTREACH_SCRIPTS.md` (Halton Region Small Business Centre, Burlington Public Library), after reading each organization's official intake page. | 20 min | Earned local mentions |
| 8 | After the profile is verified: ask every client with a completed engagement for a review, the same way, with no incentive and no score-based filtering (F8). | 5 min per client | Prominence |

## Re-run the checks

Live-site audit (read-only GET requests to the public site):

```bash
python3 tools/local_seo_audit.py --live https://www.clearglassinc.com --json burlington-exposure/audits/live.json --markdown burlington-exposure/audits/live.md
```

Artifact honesty check (also runs in CI through `tests/test_exposure_contracts.py`):

```bash
python3 tools/exposure_contracts.py
```

Import a rank-tracker export onto an approved grid:

```bash
python3 tools/geo_grid.py import --grid burlington-exposure/grids/burlington-core-7x7-2km.json --csv export.csv --provider "Tracker name" --observed-at 2026-12-01T09:00:00-05:00 --run-id burlington-2026-12-01 --out run.json
```

## What agents will not do

- Create, claim, verify or edit a Business Profile, or apply for API access.
- Send any email, direct message or review request, or post anything publicly.
- Publish site changes. Changes go to a pull request in the publishing repository.
- Write a number into the baseline without the export it came from.
- Store an address, a client's contact details or a provider login in this repository.

CLEARGLASS: See Through Everything
