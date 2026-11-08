# ClearGlass Sales Kickoff Kit: AI and Cyber Risk Advisory

Version 1, 2026-11-08. Status: READY FOR REVIEW. Nothing has been sent.

Uses SPIN for discovery and MEDDIC for qualification. This kit contains no customer results, credentials or guarantees. Wherever one of those would go, there is a `[bracket]` for you to fill in, or to delete if you can't fill it.

---

## 0. Inputs used

| Field | Value used in this kit |
|---|---|
| Offer | ClearGlass Inc. provides technology strategy, secure systems architecture, AI automation, cybersecurity risk reduction and technical operational leadership, so organizations can modernize without adding operational risk |
| Beachhead buyer (narrowed) | Owner, CEO or COO of an Ontario company with 20 to 200 staff, starting in Halton, Hamilton and GTA West. No in-house security lead; IT is a generalist or an outside provider |
| Business problem | Staff are adopting AI tools and the company is collecting security obligations faster than leadership can see or control them |
| Outcomes | Leadership can see which AI tools touch which data; baseline security gaps are ranked by business impact; client, insurer and audit questions get answered faster; there is a 90-day plan the team can execute |
| Buying triggers | Cyber insurance renewal questionnaire; a large client's security or AI questionnaire; a phishing or payment-fraud scare; a company-wide AI rollout (Copilot, ChatGPT Team, Gemini); a new IT provider; growth into regulated clients |
| Entry offer | AI and Cyber Risk Snapshot. Fixed scope, fixed fee, 10 business days |
| Entry price | CAD 3,500 fixed. This is a proposal inside the CAD 1,500 to 5,000 entry range already documented in `CLEARGLASS_AI_AUTOMATION_CONSULTING.md`, not a market-validated price |
| Stage | New prospects; pipeline starts at zero |

Why the buyer was narrowed: the original definition covered North American mid-market founders, CEOs, COOs, CTOs, CISOs and technology leaders. A CISO at a mid-market firm usually expects references, insurance and a team behind the vendor. An owner-led company with no security lead buys on clarity, local presence and fixed risk. Start there, earn references, then move up-market.

### What the Snapshot includes
1. An inventory of the AI tools in use and the company data each one touches, from interviews plus a guided look at admin consoles.
2. A check of 10 baseline controls:
   - multi-factor sign-in on email and admin accounts
   - backups that have been restored in a test
   - a backup copy attackers can't alter
   - patching
   - admin rights
   - email authentication (SPF, DKIM, DMARC)
   - a way for staff to report phishing
   - vendor and remote access
   - incident contacts
   - answers to the insurance questionnaire
3. A risk register ranked by business impact, in plain language.
4. A 90-day action plan with an owner for each item.
5. A 60-minute readout with the decision makers.

What it is not: a penetration test, legal advice, an audit opinion or a certification. It needs no admin passwords, because you work through interviews and screen shares. Say this up front; it removes the security objection.

---

## 1. Positioning statement

Full version:
ClearGlass helps owners and operators of growing Ontario companies who are adopting AI faster than they can govern it. In 10 business days we show leadership which AI tools touch company and client data, where the basic security gaps are, and what each gap would cost if it failed. Then we hand over a 90-day plan the team can actually execute. Most security reviews are written for IT; ours is written for the person who signs the cheques. It is fixed-scope and fixed-fee, and AI use and security are reviewed together. Doing nothing is not neutral: the next client questionnaire, insurance renewal or phished mailbox becomes a scramble paid for in lost days and lost trust.

One-line version:
ClearGlass shows owner-led Ontario companies, in 10 business days and for a fixed fee, what their AI tools and security gaps put at risk, and what to fix first.

Breakdown:
- **Who:** owners, CEOs and COOs of Ontario companies with 20 to 200 staff and no security lead.
- **Problem:** AI use and security obligations are growing without leadership visibility.
- **Measurable outcome:** a ranked risk register with a cost for each risk, and a 90-day plan. Measure progress by the number of top-10 gaps closed by day 90 and by the time it takes to answer the next questionnaire.
- **Difference:** a deliverable written for owners, fixed scope and fee, AI and security reviewed together. Only add "vendor-neutral, no product resale" if that is true for you.
- **Cost of doing nothing:** unknown data exposure through AI tools, questionnaires that can't be answered, and recovery measured in days.

Verifiable context you can quote, with the source:
- Statistics Canada: the share of Canadian businesses using AI to produce goods or deliver services rose from 6.1% to 12.2% in the year to Q2 2025. Source: Analysis in Brief 11-621-M2025011, https://www150.statcan.gc.ca/n1/pub/11-621-m/11-621-m2025011-eng.htm
- Canadian Centre for Cyber Security: ransomware is the top cybercrime threat facing Canada's critical infrastructure. Source: National Cyber Threat Assessment 2025-2026, https://www.cyber.gc.ca/en/guidance/national-cyber-threat-assessment-2025-2026

Note the second fact is about critical infrastructure. Don't stretch it to "every business".

---

## 2. Three-touch outreach sequence

Before sending:
- Personalize every first touch with one real, specific observation. If you can't find one, don't send.
- Every email must meet CASL; see Appendix B.
- Use plain text, with no images or icons.

### Touch 1, day 1: email
Subject: AI tools at [Company]

[First name], [specific observation: e.g. saw [Company] is hiring a second operations coordinator / posted about rolling out Copilot / just opened the Oakville location].

A question I've started asking owners at that stage: if your insurer or your largest client asked tomorrow which AI tools touch client data, could you answer in a day?

I run ClearGlass, an Ontario advisory practice. I help owner-led companies get a clear view of their AI use and security gaps, and a short list of what to fix first.

Open to a 20-minute call in the next two weeks?

Desmond Otieno
ClearGlass Inc.
289-707-0269
[business email]
[mailing address]
Reply "no thanks" and I won't contact you again.

### Touch 1, LinkedIn variant: connection note (under 200 characters)
[First name], noticed [specific observation]. I work with Ontario owners on AI use and security risk. Would be glad to connect.

### Touch 2, day 4 or 5: value follow-up
Subject: Re: AI tools at [Company]

[First name], one data point. Statistics Canada found the share of Canadian businesses using AI to deliver their work doubled in a year, from 6.1% to 12.2% (Q2 2025). In most firms I'd expect the tools to arrive before the rules about which data goes into them.

So the useful question isn't whether your team uses AI. It's whether you'd know if a client file went into a free account.

If it's helpful, I'll send a one-page list of 10 questions to ask your team about AI use. No call needed.

Desmond
[same signature and opt-out line]

### Touch 3, day 10: low-friction close
Subject: Close the loop?

[First name], I'll assume the timing isn't right and won't keep following up.

Two easy options if it is on your list:
1. Reply "list" and I'll send the 10-question AI use checklist.
2. Reply with a week that works and I'll send two 20-minute times.

Desmond
[same signature and opt-out line]

After Touch 3 with no reply: stop. Wait 90 days and re-engage only on a new, specific trigger.

---

## 3. 30-minute discovery call (SPIN)

Research the Situation questions before the call so the call itself is spent on Problem and Implication.

| Minute | Block | Goal |
|---|---|---|
| 0-3 | Open and agenda | Get permission and set the structure |
| 3-8 | Situation | Confirm the current setup (keep this short) |
| 8-15 | Problem | Find specific friction and gaps |
| 15-22 | Implication | Let them put a cost on it, in their own numbers |
| 22-25 | Need-payoff | Let them say what fixing it is worth |
| 25-28 | Decision process | Map MEDDIC |
| 28-30 | Next step | Book a dated next meeting |

**Open (0-3).**
"Thanks for the time. Here's what I'd suggest: I'll ask about how IT and AI are handled today and where it's causing friction. If there's a fit, we agree a next step; if not, I'll tell you. We have until [time]. Anything you want to make sure we cover?"

**Situation (3-8).** Pick two or three.
- Who handles IT today: someone in-house, an outside provider, or a mix?
- Which AI tools are people using for work right now, approved or not?
- Where does your most sensitive information live: client files, financials, HR?
- When is your next cyber insurance renewal, and who filled out the last questionnaire?

**Problem (8-15).**
- Where do you feel least sure about what's happening in your systems?
- Has a client, insurer or auditor asked a security question you couldn't answer quickly? What happened?
- Has anyone put client or employee information into an AI tool? How would you know?
- What happened the last time someone clicked a bad link, or a vendor account was misused?

**Implication (15-22).** Let them do the math; use their numbers, never yours.
- If email or your main system went down for three days, what stops? Who notices first, staff or customers?
- Roughly what does one day of that cost? (worksheet below)
- If your largest client made a security questionnaire a condition of renewal and you couldn't complete it, what is that account worth a year?
- If client information turned up somewhere it shouldn't, through an AI tool, what would you have to do, and who would you have to tell?
- How many hours a month do you personally spend on IT problems?

Downtime cost worksheet (fill it in with the buyer):

```
Revenue at risk per day = (annual revenue / working days per year) x share of revenue that stops
Idle staff cost per day = staff affected x loaded hourly cost x hours per day
Downtime cost per day   = revenue at risk per day + idle staff cost per day
```

Illustration with hypothetical inputs only:
- CAD 10,000,000 revenue / 250 days x 50% = 20,000 per day
- 40 staff x CAD 45 x 7.5 h = 13,500 per day
- Total: 33,500 per day

Never present this as the buyer's number until they have supplied the inputs.

**Need-payoff (22-25).**
- If you had one page showing every AI tool in use and the data it touches, who would you show it to first?
- What would it be worth to answer the next insurance or client questionnaire in a day instead of a week?
- If the top five gaps were closed in 90 days, what would that let you say yes to?

**Decision process (25-28).**
- Besides you, who would weigh in on a decision like this?
- Who approves spending of this size?
- When you've bought outside advisory work before, how did that go, step by step?
- What would you need to see to decide?
- Is a date driving this: a renewal, an audit, a client deadline?

**Next step (28-30).**
"Based on what you've said, the Snapshot would answer [their problem in their words]. I'd suggest a 30-minute call on [day option 1] or [day option 2] with you and [economic buyer] to walk through scope and price. Which works?"

---

## 4. MEDDIC qualification checklist

Score each item: 0 = unknown, 1 = partly known, 2 = confirmed in the buyer's own words.

| Letter | Question to answer | Evidence to capture | Red flag |
|---|---|---|---|
| M: Metrics | What measurable result do they need? | Their downtime cost per day, the account value at risk, the questionnaire deadline | "Just curious", or no number at all |
| E: Economic buyer | Who approves the spend? | Name, title, and whether you have met them | The approver is "someone else" and you can't reach them |
| D: Decision criteria | What will they judge the offer on? | Price, scope, timing, access limits, references | Criteria that only fit a competitor |
| D: Decision process | What steps, stakeholders and approvals are needed? | Steps, dates, procurement, NDA | No dates; "we'll see" |
| I: Identify pain | Which problem creates urgency? | The trigger event and its date | No trigger and no deadline |
| C: Champion | Who will argue for this internally? | Name, and what they gain | No one sells for you when you're not in the room |

Optional MEDDPICC additions, worth 0 to 2 each:
- **P, paper process:** contract, NDA, purchase order, payment terms.
- **C, competition:** the current IT provider, another consultant, or doing nothing.

Qualification rule for this kit: an opportunity counts as qualified at 8 or more out of 12, with the economic buyer named and a dated trigger. Below 8, keep nurturing it; don't write a proposal.

---

## 5. Ten likely objections and responses

1. **"It's too expensive."**
   "Fair. Compared with what? You estimated a day of downtime at [their number], and the Snapshot is a fixed CAD 3,500 with a defined deliverable. If the list it produces isn't worth more than that to you, we shouldn't do it. What number would make it an easy yes?"

2. **"Not the right time. Talk to me after [month]."**
   "Understood. Is anything due before then: your insurance renewal, a client review, the AI rollout? If one of those lands first, the Snapshot is most useful just before it. Want me to put a date on the calendar now, two weeks before [their date]?"

3. **"We don't have internal capacity for a project."**
   "That's why it's built this way. Your side is about three hours: a 60-minute kickoff, two or three short interviews, and the readout. I do the rest. Who would be the right person for the interviews?"

4. **"Our IT company handles security."** (incumbent vendor)
   "Good. This doesn't replace them. Two questions: do they cover which AI tools staff use and what data goes into them? And when your insurer last asked about backups and MFA, who answered? Many providers welcome a written list of priorities. I'm happy to include them in the readout."

5. **"We already have someone for this."**
   "Then you're ahead of most. What does that person cover today, and what's outside their scope? If AI use and the business-impact ranking are already covered, I'll tell you we're not needed."

6. **"Send me some information."**
   "Happy to. So I send the right thing rather than a brochure: is this mainly about AI use, the insurance questionnaire, or a client asking questions? I'll send one page on that, and let's pencil in 15 minutes on [date] to see if it's relevant."

7. **"How do we know you're secure? We're not giving out access."**
   "You shouldn't have to. The Snapshot needs no admin passwords; it's interviews plus screen shares where your team drives. I'll sign your NDA, and anything I keep is listed and deleted at the end. [Add your actual credentials or insurance here only if they are real.]"

8. **"This will disrupt operations."** (implementation risk)
   "The Snapshot changes nothing in your systems. It produces a plan. Your team decides what to change and when, and the 90-day plan is sequenced so the low-disruption fixes come first."

9. **"We're too small to be a target."**
   "Most of what I'd look at first doesn't depend on anyone choosing you: a phished mailbox, a reused password, a vendor account, a client file in a free AI tool. Has anything like that come close at your company, or at a peer's?"

10. **"Who else have you done this for?"**
    - If you have a relevant client who agreed to be named, name them and offer an introduction.
    - If you don't: "I'm early, and I won't pretend otherwise. That's why it's fixed-scope, fixed-fee, and you keep the deliverable whatever happens next. You're buying a defined piece of work, not a promise."
    - Optional, if you choose to offer it: a reduced "founding client" fee in exchange for written permission to use the engagement as a reference. Agree that in writing.

---

## 6. Closing sequence

**A. Problem summary.** Say it back, then confirm.
"Let me check I have it right. [Company] is [situation]. The pressure is [problem in their words], and if it isn't handled before [trigger date], it puts [their metric: account value, downtime cost, renewal] at risk. Did I miss anything?"

**B. Value hypothesis.**
"If the Snapshot gives you a ranked list of AI and security risks, each with a cost, plus a 90-day plan, by [date ten business days from start], you can [their need-payoff: answer the renewal questionnaire, approve the AI rollout, brief the board] with confidence. The test of whether it worked is [their metric]."

**C. Specific next step.**
A 30-minute scope-and-price review with [economic buyer], then a signed one-page scope. Work starts [date].

**D. Two calendar options.** Offer exact times in ET, inside the next five business days:
- Option 1: [Tuesday, Month DD] at 10:00 a.m. ET
- Option 2: [Thursday, Month DD] at 2:00 p.m. ET

**E. Follow-up email after the call.**

Subject: [Company]: summary and next step

[First name],

Thanks for the time today. My notes, so we're working from the same page:

What you're dealing with: [problem in their words].
Why it matters now: [trigger and date].
What it's worth: [their metric and number].

What I'd propose: the AI and Cyber Risk Snapshot. It is 10 business days, CAD 3,500 fixed, and covers:
- an AI tool and data inventory
- 10 baseline security checks
- a ranked risk register
- a 90-day plan
- a 60-minute readout
It needs no admin passwords.

Next step: 30 minutes with you and [economic buyer] to confirm scope. Does [option 1] or [option 2] work?

Desmond Otieno
ClearGlass Inc.
289-707-0269
[business email]
[mailing address]

---

## 7. First-30-day KPIs

Starting targets are guesses at what one person can sustain. Recalibrate after week 2; they are not industry benchmarks.

| KPI | Definition | 30-day starting target |
|---|---|---|
| 1. Outreach sent | Touch 1 messages to named, researched decision makers. Follow-ups don't count | 100 (about 5 per working day) |
| 2. Positive replies | Replies that show willingness to talk or a request for the checklist. Opt-outs and "no" don't count. Rate = positive replies / outreach sent | Track the rate; there's no target until week 2 |
| 3. Discovery calls booked | Calls booked and held, counted separately | 6 held |
| 4. Qualified opportunities | MEDDIC 8 or more out of 12, with the economic buyer named and a dated trigger | 2 |
| 5. Proposals or next steps secured | A written proposal sent, or a meeting with the economic buyer dated | 2 |

Hygiene metrics, checked weekly:
- Opt-out requests: honour each within 10 business days, and log it.
- Bounced emails.
- Hours spent selling versus delivering.

Weekly review, Friday, 20 minutes:
1. Find where the funnel is thinnest.
2. Choose one change for next week.
3. Write it down.
Change one variable at a time.

---

## Appendix A: "10 questions to ask your team about AI use"
This is the checklist offered in Touches 2 and 3. Send it as plain text.

1. Which AI tools are people using for work, including free personal accounts?
2. Which of them are approved, and who approved them?
3. What kinds of information may be pasted or uploaded: client, employee, financial?
4. Are any AI tools connected to company email, files or calendars? With what permissions?
5. Has anyone checked whether each tool's settings let your inputs be used for training?
6. Who can see AI outputs that contain client information?
7. Is AI-generated work reviewed by a person before it reaches a client?
8. Do your client contracts or NDAs say anything about AI or third-party processing?
9. What happens to a person's AI accounts when they leave?
10. Who should staff tell if they think they've shared something they shouldn't have?

## Appendix B: CASL checklist (Canada's Anti-Spam Legislation)
These are requirements, not marketing advice. Get a lawyer to confirm anything you're unsure of.

- **Consent basis:** cold email needs implied or express consent. Implied consent through "conspicuous publication" requires:
  - the address is conspicuously published, for example on the company's own website
  - there is no statement that unsolicited messages are unwanted
  - your message is relevant to the person's business role
  The CRTC has said simple public availability is not enough, and the sender carries the burden of proof. Keep a record of where and when you found each address. Sources: [Bennett Jones on the CRTC Blackstone decision](https://bennettjones.com/Blogs-Section/CRTC-Assesses-Conspicuous-Publication-Basis-of-Implied-Consent-in-CASL-Enforcement-Decision), [Mondaq summary](https://www.mondaq.com/canada/privacy-protection/541038/dear-casl-when-can-i-rely-on-implied-consent).
- **Every message must include:**
  - your name and business name
  - a mailing address
  - a phone number, email or web address, valid for at least 60 days
  - a free, easy unsubscribe method
- **Opt-outs:** honour them within 10 business days. Sources: [Conestoga College CASL summary](https://www.conestogac.on.ca/casl/), [Mondaq on a deficient unsubscribe settlement](https://www.mondaq.com/canada/privacy-protection/445790/crtc-settles-alleged-casl-violation-deficient-unsubscribe-mechanism).
- **Don'ts:** don't buy lists, scrape personal emails, or guess email formats for people who haven't published their address.
- **LinkedIn:** follow LinkedIn's own rules. Treat direct messages with the same care.

## Appendix C: Inputs that would change this kit
1. Your real credentials, certifications, and any past work you can name with permission.
2. Your territory: Halton and Hamilton only, or GTA or Ontario-wide; and whether you'll meet in person.
3. Whether you have professional liability (E&O) insurance and a standard services contract.
4. The business email domain and mailing address to use in outreach.
5. Your capacity: hours per week for selling, and how many Snapshots you can deliver per month.
