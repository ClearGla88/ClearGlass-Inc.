# Burlington Growth Report — YYYY_MM

> Reporting period: `[start, end]`; comparison: `[period]`; timezone: America/Toronto. Generated values must link to aggregate source snapshots and checksums. Unknown is `N/A`, never zero.

## Executive decision record

- **Outcome versus 90-day target:**
- **One evidence-supported win:**
- **One miss/data gap:**
- **Decision required / owner / due date:**
- **Policy, consent, suspension, or reputation incidents:**

## Weekly scorecard

| Metric | Prior | Current | Δ | Target | Source / freshness | Interpretation |
|---|---:|---:|---:|---:|---|---|
| GBP impressions | | | | | | |
| GBP actions (call/site/directions) | | | | | | |
| Burlington/Halton organic sessions | | | | | | |
| Qualified local leads | | | | 10/month | | |
| Instagram follower growth | | | | | | |
| Engagement rate (declared formula) | | | | | | |
| Top-3 grid cells / total | | | | +30% relative | | |
| Consent complaints / opt-outs | | | | 0 incidents | | |

### Top queries, pages, and posts

| Item | Metric | Change | Evidence | Next action |
|---|---:|---:|---|---|
| | | | | |

### Geo-grid detail

| Keyword | Grid/version | Top 3 | 4–10 | 11–20 | >20/not found | Median rank | Scan source/time |
|---|---|---:|---:|---:|---:|---:|---|
| | | | | | | | |

Explain cell movement only as observation unless a controlled experiment supports causality. Attach grid artifact checksum and keep centre/spacing unchanged.

How to fill this section and the site rows. All three commands run without credentials.

```bash
python3 tools/geo_grid.py compare last-month-run.json this-month-run.json --markdown
```

```bash
python3 tools/local_seo_audit.py --live https://www.clearglassinc.com --json burlington-exposure/audits/YYYY-MM-DD-live.json --markdown burlington-exposure/audits/YYYY-MM-DD-live.md
```

```bash
python3 tools/exposure_contracts.py
```

`compare` counts only cells that succeeded in both runs. It reports a null relative change when the baseline rate is zero, and it refuses runs taken on different grids, keywords, thresholds or providers. Copy its table as-is; don't recompute by hand. Report the site's Burlington signals from the audit (pages with Burlington in the title or H1, name variants, canonical findings) next to the grid. They are the levers the plan can actually move.

## Monthly review

### Progress versus targets

| Objective | Baseline | Current | Day-90 target | Confidence | Status |
|---|---:|---:|---:|---|---|
| Green cells for three terms | | | +30% | | |
| Local organic sessions | | | +40% | | |
| Qualified local leads/month | | | 10 | | |
| Legitimate local mentions/month | | | 2 | | |

### Experiment register

| ID | Hypothesis | Control/candidate | Primary metric | Guardrails | Result | Decision/approver |
|---|---|---|---|---|---|---|
| | | | | | | |

### What worked / did not / learned

- **Worked (evidence):**
- **Did not work (evidence):**
- **Confounders and data gaps:**
- **Next experiments (priority, owner, gate):**

## Operations, governance, and recovery

Record drafts awaiting approval; sends/posts/releases performed by humans or approved adapters; source errors; drift; access changes; retention/deletion work; GBP warnings; and rollback events. Every material action includes artifact digest, actor, approver, policy version, result, and recovery owner. Never publish raw contact details, IP addresses, credentials, review identities, or sensitive customer/project data.
