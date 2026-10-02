# A3 — Clue's ICP (v1, 2026-08-31)

Derived from `product-context.md` (the live site, quoted) + the founder's three hard rules.
This is the spec that `discovery.md` queries against and `candidates.json` scores against.

---

## 0. The one-sentence ICP

> **A US-headquartered, Series A–C B2B software company selling a high-ACV product to a small,
> named list of accounts, whose GTM team is 2–15 people, who has publicly committed to an
> outbound/ABM motion (hiring for it, or its founders complaining about it), and who has *not*
> already installed an enterprise ABM platform.**

The founder's hard rules are **gates, not scores** — fail any one and the account is out
regardless of everything else:

| # | Hard rule | Operational test | Why |
|---|---|---|---|
| **H1** | **United States** | HQ in the US per the company's own site/LinkedIn/funding announcement | LinkedIn+Meta ad activation, US direct-mail fulfilment, and a US-jurisdiction personal-data posture (Doc D) are all cheapest and least risky domestically. Also: the founder's rule. |
| **H2** | **Series A and above** | A named priced round (Series A/B/C/D) with a date and at least one named investor | Below Series A there is no budget, no marketing hire, and no named-account list. Above Series C the buyer becomes procurement-shaped and likely already owns 6sense/Demandbase. |
| **H3** | **Pain is quantifiable** | At least one piece of *external, citable* evidence that ABM production is a bottleneck **with a number attached to it** (see §3) | Clue's entire pitch is a throughput claim ("More output, same headcount"). If we can't count the bottleneck, we can't price the value and the demo has no anchor. |

**H3 is the rule that does the work.** H1 and H2 are cheap filters anyone can run; H3 is what
separates "fits the firmographics" from "will actually take the meeting."

---

## 1. Firmographics

| Dimension | Target | Acceptable | Out |
|---|---|---|---|
| HQ country | United States | US HQ with remote-distributed team | Anywhere else (**H1**) |
| Funding stage | **Series A or Series B** | Series C, or a large Seed extension **only if** ≥$15M raised and a VP Marketing is in seat | Pre-seed, Seed, bootstrapped, public, PE-owned (**H2**) |
| Last round | Raised within 24 months | 24–36 months | >36 months with no new round (dead-money risk) |
| Headcount | 30–300 | 20–500 | <20 (no team to buy for) or >800 (procurement + incumbent ABM stack) |
| Marketing team size | **2–15** | 1 (if founder-led, see P4) or 16–25 | >25 (they can already produce 1:1 in-house; we're competing with their agency roster) |
| ACV / deal size | **$25k–$250k** | $15k–$500k | <$10k (the economics of a per-account microsite + direct mail never clear) |
| GTM motion | Named-account / outbound / land-and-expand enterprise | Hybrid PLG-with-an-enterprise-tier | Pure self-serve PLG, pure inbound |
| Customer type | B2B | B2B2C | B2C (**disqualifier**) |

## 2. Vertical priorities — my picks, and the justification

I rank four verticals. Ranking is *not* alphabetical; it reflects how well each one satisfies H3
(quantifiable pain) and how well it matches what Clue actually produces (microsites, LinkedIn/Meta
ads, direct mail).

### V1 — **B2B SaaS selling into enterprise / mid-market with a named-account list** — PRIORITY 1
*Examples of shape: infrastructure, data, security, fintech-infra, vertical SaaS with big logos.*
**Why first:** three independent reasons converge. (a) **They already believe in ABM** — this is
the only vertical where "account-based marketing" is native vocabulary, so there is no category
education cost. (b) **The pain is natively quantifiable**: target-account lists are literal numbers
("our top 200 accounts"), and the gap between list size and campaigns shipped is arithmetic
anyone's VP Marketing can do in their head. (c) **The buyer and the champion are the same two
people Clue's site addresses** (VP Marketing, Head of Growth) and they are reachable on LinkedIn,
which is one of the two ad channels Clue activates. Risk: also the most contested market — 6sense,
Demandbase, Mutiny, Folloze, RollWorks all sell here. Mitigation is the disqualifier in §4.

### V2 — **Healthcare / life-sciences-adjacent B2B SaaS** (payers, providers, pharma-services,
clinical-ops, healthcare-fintech) — PRIORITY 2
**Why second, not first:** the *quantifiable pain is unusually sharp here* — the buying universe is
genuinely finite and enumerable (there are ~6,000 US hospitals, ~1,000 health systems, a few dozen
national payers, ~20 top-20 pharma), so "we have 400 possible customers and 3 marketers" is a
literal, defensible sentence, and the ACV is high enough ($50k–$500k) that a per-account microsite
plus a physical executive report is trivially ROI-positive. Buying committees are also large and
role-differentiated (clinical + IT + finance + compliance), which is exactly what Clue's
"Buying committees … precise role-based audiences" capability is for. **Why not first:** two real
frictions — (i) compliance review is slower and personal-data-driven personalization draws a
privacy question early (the appropriateness/use gate matters more here); (ii) LinkedIn works but
Meta targeting is weaker for clinical audiences, so one of Clue's two paid channels is partly
neutralized. Net: higher value per won account, longer cycle. Worth 30–40% of the list.

### V3 — **Fintech / vertical-SaaS selling to a small enumerable market** (banks, credit unions,
insurers, logistics, construction, gov-tech) — PRIORITY 3
**Why:** the same "finite universe, high ACV" logic as V2 without the compliance drag. There are
~4,500 US banks and ~4,600 credit unions; a Series B selling core-banking or fraud tooling has a
list, not a funnel. Direct mail materially outperforms email into these conservative buyers, which
plays to Clue's most differentiated agent. **Why third:** smaller pool of Series-A+ US companies
that fit, and their marketing teams are often 1–2 people (too small — falls to P4 economics).

### V4 — **B2B agencies / GTM consultancies** (ABM agencies, demand-gen shops, brand studios)
— PRIORITY 4, and **only as a deliberate second-order bet**
**Why on the list at all:** an agency is the single most *quantifiably* pained buyer in existence —
their bottleneck **is** their P&L. "We bill 12 accounts per strategist and each 1:1 program takes
three weeks" is a number they say out loud in their own marketing. They also multiply distribution:
one agency win puts Clue in front of ten of its clients. **Why last:** (a) most are not
venture-funded, so **H2 disqualifies the overwhelming majority** — only a handful of US agencies
have a Series A; (b) they will resell/white-label, which is a different contract, different
support load, and a channel-conflict question a pre-GA company should not answer yet; (c) they may
be building the same thing. **Practical ruling: allow agencies through only if they clear H2 with a
genuine priced round** — i.e. tech-enabled-services companies, not classic agencies. In practice
this means very few will survive discovery, and that is the correct outcome for v1.

**Deliberately excluded verticals:** e-commerce/DTC (B2C), consumer fintech, dev-tools with pure
PLG bottoms-up motion (no named-account list), crypto (ad-channel restrictions on LinkedIn/Meta,
volatile budgets), and hardware/manufacturing (long cycles, wrong channels for microsites).

## 3. Quantifiable-pain evidence classes (H3) — the heart of the ICP

An account satisfies H3 when **≥1 Tier-1 signal** or **≥2 Tier-2 signals** are found with a
citable source. Every signal below must be recorded with a verbatim quote + source URL — the
claim-with-provenance rule applies to ICP evidence too.

### Tier 1 — direct, dated, numeric (each alone satisfies H3)
| Code | Signal | What it looks like in the wild | Why it's Tier 1 |
|---|---|---|---|
| **Q1** | **A GTM job req that describes list-building / account research as the job** | "Build and maintain target account lists", "conduct account research to inform outreach", "own our 1:1 ABM pilot for our top 100 accounts" | They are about to spend $120k–$180k/yr on a human to do what Clue's Deep Research agent does. That is the price anchor, and it has a number. |
| **Q2** | **A stated account-list size against a stated team size** | "our top 250 target accounts" + a marketing team of 4 on LinkedIn | The ratio *is* the pitch. 250 accounts ÷ 4 people is the whole demo. |
| **Q3** | **A founder/CMO post or podcast complaining about outbound/ABM production cost** | "we spent two weeks researching 30 accounts and shipped 4 campaigns" | Self-declared, dated, quotable pain — and a warm opener. |
| **Q4** | **A recent round explicitly earmarked for go-to-market expansion** | "$32M Series B to expand our enterprise go-to-market" | Budget + mandate + a deadline, all in one sentence with investors' names on it. |

### Tier 2 — strong circumstantial (need two)
| Code | Signal | Why it counts |
|---|---|---|
| **Q5** | **No ABM/personalization tooling detected** (no 6sense, Demandbase, RollWorks, Mutiny, Folloze, Terminus, Influ2 in job-req tool lists or the site) | The seat is open. Combined with Q1/Q2 this is the highest-conversion shape there is. |
| **Q6** | **Small marketing team + large addressable market** (≤6 marketers, enumerable universe of ≥200 named targets) | The structural version of Q2 when they haven't published a list size. |
| **Q7** | **Multiple concurrent GTM/marketing open roles** (≥2 of: demand gen, growth, ABM, campaign manager, content, product marketing) | They're solving throughput by hiring — the exact substitution Clue undercuts. |
| **Q8** | **Enterprise/named-logo motion evidenced on the site** (customer logos that are large enterprises, a "for enterprise" page, "request a demo" as the only CTA) | Confirms high ACV and named-account selling. |
| **Q9** | **Recent VP Marketing / CMO / Head of Growth hire (<9 months)** | New GTM leader = a new tooling budget and a mandate to show results in two quarters. |
| **Q10** | **Events/field-marketing spend** (conference booths, dinners, roadshows) | They already pay for high-touch per-account motion; direct mail + microsites are the cheaper adjacent spend. |

## 4. Disqualifiers (hard — remove from the list, don't just down-score)

| Code | Disqualifier | Test |
|---|---|---|
| **D1** | **B2C / consumer** | Sells to individuals, not companies |
| **D2** | **Pure PLG self-serve** | Public self-serve signup + published low-tier pricing + no "talk to sales" enterprise path |
| **D3** | **Enterprise ABM platform already installed** | 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic detected in job reqs / site / tech footprint |
| **D4** | **< Series A** (H2) | Pre-seed / seed / bootstrapped / grant-funded |
| **D5** | **Non-US HQ** (H1) | HQ outside the United States |
| **D6** | **A direct competitor** | Sells ABM orchestration, AI SDR/GTM agents, personalized-microsite or intent tooling — they are a competitor, not a customer |
| **D7** | **Public / PE-owned / >800 headcount** | Procurement-shaped buying; wrong stage for a waitlist product |
| **D8** | **Named exclusions for this run** | probook.ai, lassie.ai, avoca, Insight Health, Clue itself |

## 5. Scoring rubric — 0–100

Gates first: **any of D1–D8 or a failure of H1/H2 ⇒ score is void, account removed.** H3 is scored
(not gated) inside the rubric, but an account scoring **0 in the Quantifiable Pain block cannot be
selected** regardless of total — that is the founder's third rule operationalized.

| Block | Weight | Criterion | Points |
|---|---|---|---|
| **A. Quantifiable pain (H3)** | **35** | Q1 job req describing research/list-building | 15 |
| | | Q2 stated list size vs team size, or Q6 small team + big enumerable market | 10 |
| | | Q3 founder/leader public complaint about outbound/ABM cost | 5 |
| | | Q4 round explicitly earmarked for GTM expansion | 5 |
| **B. Motion fit** | **25** | Named-account / enterprise motion evidenced (Q8) | 10 |
| | | High ACV ($25k+) inferable | 8 |
| | | Active outbound/ABM language in their own materials or reqs | 7 |
| **C. Stage & size fit** | **20** | Series A or B (Series C = 6, not 10) | 10 |
| | | Headcount 30–300 | 5 |
| | | Marketing team 2–15 | 5 |
| **D. Open seat / timing** | **15** | Q5 no ABM tooling detected | 7 |
| | | Q9 new GTM leader <9 months, or Q7 ≥2 concurrent GTM reqs | 5 |
| | | Round or GTM-expansion news within 12 months | 3 |
| **E. Channel & artifact fit** | **5** | Their buyers are reachable on LinkedIn/Meta **and** a physical executive report/founder letter would land (finite, senior, addressable committee) | 5 |
| | | | **/100** |

**Bands:** **≥75 = select** (high-fit, worth Agent B's deep research) · **60–74 = strong bench** ·
**45–59 = watch** · **<45 = drop**.

**Confidence discount (honesty rule):** any criterion awarded on inference rather than a citable
source is recorded as `inferred` and its points are **halved**. A candidate whose score depends
mostly on inferred points is reported as such rather than laundered into a clean number.

## 6. What Agent B should try to break

This ICP makes three bets that deep research can falsify, and I want them tested rather than
confirmed:
1. **That Q1 (a research-shaped job req) predicts intent better than Q4 (a fresh round).** My
   ranking assumes it does.
2. **That "no ABM tooling detected" is real absence and not just invisible tooling.** Cheap
   discovery cannot see a 6sense contract; deep research sometimes can.
3. **That healthcare-adjacent (V2) really is second, not first.** If the healthcare candidates come
   back with sharper numbers than the SaaS ones, the vertical order is wrong and should be flipped.
