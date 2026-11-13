# 9. 14-day execution plan

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

From decision to a live page and a first brief. Day 0 is the day the founders have written legal and tax advice and three confirmed directors. Nothing here has started.

**Dates.** Start and due dates are placeholders. Set Day 0, then fill each date as Day 0 plus the day number. [DECISION REQUIRED] Day 0.

**Owners.** Roles, not people, until the directors are named: Founder; Chair; Treasurer; Secretary; Counsel (the lawyer engaged for stage 0); Author (the named author of the first brief).

**Evidence.** Each completed step is recorded in `data/status.json` with its date and where the evidence is kept. `STATUS.md` then shows the state. The record key for each step is in the last table.

**Escalation.** A step that will miss its due date is reported the same day to the person named in its escalation column, who decides whether to move the dates or stop.

**What only a person can do.** Signing, paying, filing, opening accounts, and contacting anyone. Software may prepare the documents and keep the record; it does not act for the Institute.

---

## Stage 0. Before Day 0

| ID | Task | Owner | Start | Due | Depends on | Deliverable | Evidence of completion | Risk if missed | Escalation |
|---|---|---|---|---|---|---|---|---|---|
| P1 | Engage counsel with Ontario not-for-profit and charity experience | Founder | [START DATE] | [DUE DATE] | None | Engagement confirmed | Engagement letter | Filing on unreviewed drafts; the wrong corporate form | Founder decides whether to proceed without advice. Not recommended |
| P2 | Obtain written advice on the questions in `13_OPEN_QUESTIONS.md`: Path A or B, tax status before registration, name, articles, by-law | Founder, Counsel | [START DATE] | [DUE DATE] | P1 | Written advice | Advice letter, filed under tab 13 of the minute book | Articles that must be amended; an unexpected tax position; a refused name | Founder |
| P3 | Confirm three directors and their offices | Founder | [START DATE] | [DUE DATE] | None | Three names, with roles | Signed consents (step 1) | Cannot file; the plan stalls here | Founder. This is the step most likely to slip |

## Days 0 to 14

| ID | Day | Task | Owner | Start | Due | Depends on | Deliverable | Evidence of completion | Risk if missed | Escalation |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | Each director signs a consent to act and a conflict disclosure | Chair | [START DATE] | [DUE DATE] | P3 | Three consents, three disclosures | Signed originals, tab 3 | No valid directors; filing blocked | Founder |
| 2 | 0 | Decide the name, and obtain ClearGlass Inc.'s written consent if counsel advises it | Founder | [START DATE] | [DUE DATE] | P2 | Name decision; consent letter | Decision note and consent, tab 13 | Name refused; search fee wasted | Counsel |
| 3 | 0 | Confirm the registered office address in Burlington | Founder | [START DATE] | [DUE DATE] | None | Address | Written confirmation, tab 1 | Articles cannot be completed | Founder |
| 4 | 1 | Order the Ontario-biased NUANS report for the chosen name | Secretary | [START DATE] | [DUE DATE] | 2 | Name search report | Report with reference number and date | Filing blocked; the report expires 90 days after its date | Counsel |
| 5 | 1 | Complete and file the articles of incorporation; pay the fee | Chair | [START DATE] | [DUE DATE] | 1, 3, 4, P2 | Filed articles | Registry receipt; copy of the articles as filed, tab 1 | No corporation; every later step waits | Counsel |
| 6 | 2 | Finalize By-law No. 1, the conflict policy, and the banking resolutions with counsel's changes | Secretary | [START DATE] | [DUE DATE] | P2 | Board-ready documents | Final versions circulated to all directors | Meeting held on drafts; default by-laws apply after 60 days | Chair |
| 7 | 3 to 7 | Receive the certificate of incorporation | Chair | [START DATE] | [DUE DATE] | 5 | Certificate; corporation number | Certificate, tab 1 | Schedule slips day for day | Chair. Ask the registry for status after day 7 |
| 8 | 7 | Call and hold the first directors' meeting on at least five days' notice | Chair | [START DATE] | [DUE DATE] | 6, 7 | By-law made; policy adopted; officers appointed; year end fixed; members admitted; banking resolutions passed | Signed minutes, tab 4 | No officers, no banking authority, no by-law | Chair |
| 9 | 7 | Members confirm the by-law, elect the directors, and decide the financial review, by meeting or signed resolution | Chair | [START DATE] | [DUE DATE] | 8 | Members' resolutions | Signed resolution or minutes, tab 5 | By-law lapses at the next meeting; first directors' term ends with no election | Chair |
| 10 | 7 | Open the minute book and the registers of directors, officers and members | Secretary | [START DATE] | [DUE DATE] | 8 | Minute book | Index page with tabs 1 to 14 filled where applicable | Records the Act requires are missing | Chair |
| 11 | 8 | File the initial return | Secretary | [START DATE] | [DUE DATE] | 7, 8 | Initial return | Registry confirmation, tab 9 | Statutory deadline is 60 days after incorporation | Chair |
| 12 | 8 | Confirm or obtain the CRA Business Number | Treasurer | [START DATE] | [DUE DATE] | 7 | Business Number | CRA confirmation, tab 10 | Bank account and tax filings delayed | Chair |
| 13 | 8 | Create the annual compliance calendar from the incorporation date and year end | Secretary | [START DATE] | [DUE DATE] | 7, 8 | Calendar with reminders | Year end recorded in `data/status.json`; dates shown in `STATUS.md` | Missed annual return or meeting | Chair |
| 14 | 9 | Open the bank account in the Institute's legal name with two signing officers | Treasurer | [START DATE] | [DUE DATE] | 8, 12 | Bank account | Account-opening documents, tab 12 | No way to receive or spend money properly | Chair |
| 15 | 9 | Register a domain for the Institute and create its own code host organization | Founder | [START DATE] | [DUE DATE] | 7 | Domain; organization | Registration records in the Institute's name | Public page would sit on a ClearGlass Inc. address, which the checker refuses | Chair |
| 16 | 10 | Publish the public page on the Institute's domain with both disclaimers | Secretary | [START DATE] | [DUE DATE] | 9, 15 | Live page | URL recorded in `data/status.json`; `check` passes | Public statements without the required disclaimers | Chair |
| 17 | 10 to 13 | Write the first brief from the outline; second reader checks every source | Author | [START DATE] | [DUE DATE] | P3 | Brief, version 1.0 | Completed source-verification checklist | Unsourced or wrong public statements | Chair |
| 18 | 14 | Board, or the person it has authorized, approves and publishes the first brief | Chair | [START DATE] | [DUE DATE] | 16, 17 | Published brief | Approval in the minutes; publication date recorded | First program output late | Chair |

## What can go wrong with the schedule

| Assumption | If it fails |
|---|---|
| The certificate arrives within a week of filing. [CONFIRM] current processing time [L-07] | Steps 8 to 18 move day for day. The 60-day limits in steps 6 and 11 run from the incorporation date, not from Day 0 |
| The name is accepted | Go back to step 2 with an alternate name and a new search. A number name is not available [L-11] |
| Counsel returns advice before Day 0 | Do not start. Filing first and fixing later means articles of amendment and a members' special resolution [L-42] |
| Three directors are available on Day 0 | Do not file with fewer than three [L-01] |
| Money is needed before the bank account exists (fees in steps 4 and 5) | A founder pays personally and is reimbursed on receipts after step 14, by board resolution. No ClearGlass Inc. funds [DECISION REQUIRED] who pays |

## Record keys

| Step | `data/status.json` key |
|---|---|
| P2 | `milestones.legal_and_tax_advice` |
| 1 | `gates.three_director_consents` |
| 4 | `milestones.name_search_report` |
| 5 | `gates.articles_filed` |
| 7 | `gates.certificate_of_incorporation`, with `entity.corporation_number` and `entity.incorporation_date` |
| 8 | `gates.bylaws_adopted`, `gates.conflict_policy_adopted`, `entity.financial_year_end` |
| 8, 9 | `gates.organizational_minutes_signed` |
| 10 | `milestones.minute_book_opened` |
| 11 | `milestones.initial_return_filed` |
| 12 | `gates.cra_business_number` |
| 13 | `gates.annual_return_calendar` |
| 14 | `gates.institute_bank_account` |
| 15 | `milestones.separate_domain_and_code_host` |
| 16 | `public_site`, then `gates.public_charity_disclaimer` |
| 18 | `milestones.first_public_brief_published` |

Legal basis for the sequence: three directors and consents [L-01] [L-03]; name search [L-08]; first directors' meeting [L-38]; by-law and its confirmation [L-17] [L-18]; election of directors [L-31]; signed resolutions [L-33]; records [L-36]; initial return [L-12]; business number [L-26].
