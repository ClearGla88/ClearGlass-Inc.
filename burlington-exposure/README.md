# burlington-exposure/

Evidence and planning inputs for the Burlington local-visibility program. The program documents are the `BURLINGTON_*.md` files and the six JSON contracts at the repository root. Start with `BURLINGTON_OWNER_ACTIONS.md`.

| Path | What it is | Made by |
|---|---|---|
| `audits/2026-11-21-live.{json,md}` | Read-only audit of https://www.clearglassinc.com: 4 sitemaps, 177 URLs (all HTTP 200), structured data, name/phone/email consistency, Burlington signals | `tools/local_seo_audit.py --live` |
| `audits/2026-11-21-checkout.{json,md}` | The same audit run on this repository's files. This checkout is not the deployed site, so its gaps are warnings, not live defects | `tools/local_seo_audit.py --root .` |
| `grids/burlington-core-7x7-2km.json` | Proposed planning grid: 49 points, 2 km apart, centred on the service-area midpoint the live homepage declares. Not approved | `tools/geo_grid.py plan` |
| `grids/halton-hamilton-7x7-5km.json` | Proposed regional grid: 49 points, 5 km apart. Not approved | `tools/geo_grid.py plan` |

## Tools

All three are standard-library Python. They read local files or make read-only GET requests, and they never write to an external system.

- `tools/local_seo_audit.py` audits either a checkout (`--root`) or the live site (`--live`). The live mode stays on one host, refuses redirects to other hosts or to plain http, and fetches one URL at a time. `--check` exits 1 when an error-severity finding exists.
- `tools/geo_grid.py` has four subcommands. `plan` builds a grid, `import` turns a rank-tracker CSV export into a run file, `summarize` recomputes green-cell counts, and `compare` compares two runs. It fails closed on blank or ambiguous rank values, rows that don't land on a grid point, duplicate rows, and comparisons across different grids, keyword sets, thresholds or providers. It never queries Google (policy fact F16).
- `tools/exposure_contracts.py` checks the six root JSON contracts. No metric may hold a value without a collected source and an evidence reference. Lever scores must equal the formula. Grid summaries must equal the cells. A "verified" opportunity needs first-party evidence. No contact details may be stored.

Tests: `tests/test_local_seo_audit.py`, `tests/test_geo_grid.py` and `tests/test_exposure_contracts.py` run in Baseline CI (`python -m pytest`).

## Rules for this directory

- Commit audits of the public site and grids centred on public points only. A grid centred on a Business Profile's home address reveals that address, so keep it and its runs outside this public repository.
- Raw provider exports stay outside the repository. Commit summaries, or run files that contain no personal data.
- Name each new audit by date and leave older audits in place. They are the before-and-after record.
