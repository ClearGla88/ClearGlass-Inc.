# Compliance calendar

> **Status notice.** ClearGlass Institute is a proposed organization. It is not yet incorporated and is not a registered charity. Files in this folder are working drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Recurring obligations once the Institute exists. None apply yet. Every rule below is only as reliable as its entry in `LEGAL_VERIFICATION.md`; several are unverified.

## Get the dates

Dates run from the incorporation date and the financial year end. Before incorporation, model them:

```bash
python3 clearglass-institute/tools/institute_kit.py calendar --incorporated 2027-01-15 --fye 12-31
```

After incorporation, record `entity.incorporation_date` and `entity.financial_year_end` in `data/status.json` and run `render`. `STATUS.md` then lists the real dates, each with its rule and that rule's verification level.

## One-time, after incorporation

| When | What | Owner | Rule |
|---|---|---|---|
| Within 60 days | Initial return to the Ontario Business Registry | Secretary | [L-12] |
| Within 60 days | Own by-laws passed, or the standard ones apply | Board | [L-18] |
| Next members' meeting | Members confirm the by-laws | Members | [L-17] |
| Within 18 months | First annual meeting of members | Board | [L-15] |

## Every year

| When | What | Owner | Rule |
|---|---|---|---|
| Within 6 months after year end | Ontario annual return | Secretary | [L-13] |
| Within 6 months after year end | T2 corporation income tax return, even with no tax owing | Treasurer | [L-25] |
| Within 6 months after year end | T1044, if passive income or assets pass its tests | Treasurer | [L-24] |
| Within 6 months after year end (planning date) | Annual meeting: financial statements, election of directors, audit decision | Board | [L-15] [L-16] |
| At the annual meeting | Appoint an auditor, or pass the waiver the Act allows for the Institute's type and revenue | Members | [L-06] [L-28] |
| Before the annual meeting | Recheck the audit thresholds; they can change by regulation | Treasurer | [L-06] |
| First board meeting after the annual meeting | Review the conflict policy; report related-party transactions to members | Board | policy, section 7 |
| Year end | Add up outside donations and government grants for the year. Over $10,000 means public benefit corporation status next year | Treasurer | [L-04] |

## When something changes

| Trigger | What | Deadline | Rule |
|---|---|---|---|
| A director or officer joins or leaves; the registered office moves | Notice of change | 15 days | [L-14] |
| The Institute becomes a public benefit corporation | Check the employee-director cap, the audit rules, and the dissolution clause | Before the next financial year | [L-05] [L-06] [L-19] |
| A funder requires qualified donee status, or donors need receipts | Board decision on a charity application | Board's call | [L-20] [L-21] |
| Federal non-profit reporting rules change | Recheck T1044 and any new short return | When enacted | [L-24] |

## Every six months

Recheck the source register. `check` warns when a rule was last checked more than 180 days ago. Open each source, confirm the rule still reads the same, update `checked`, and upgrade the level if the provision was read on the official page.
