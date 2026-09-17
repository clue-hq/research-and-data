# Frontend spec — the three account screens, with every link inline

**For:** building or modifying the frontend with Codex.
**Subject:** Zafran Security (zafran.io), researched 2 Sep 2026; people researched 1–2 Sep 2026.
**Source of every sentence:** `.context/arv2-one-account-aiark/claims_zafran.json` (174 claim rows) and the
Person-Depth dossiers. Nothing below is invented; every link is a real URL from those runs.

This file has four parts:

1. **The visual grammar** — how a link, a date, a contact mention, a priority, a copy-line and an empty
   state look, and the JSON the frontend reads.
2. **Screen 1 — Insights** (`/accounts/{account}/insights`)
3. **Screen 2 — Account Overview** (`/accounts/{account}`)
4. **Screen 3 — Contact** (`/accounts/{account}/contacts/{contact}`), Nick Fisher
5. **Link register** — every URL used above, with its date and favicon URL.

Updates the founder asked for are in: the Gong item states its intent (a strength, not a problem);
"Reach" is no longer a section (its facts are rail rows, its one piece of advice is the first opener);
the rail shows numbers with no provider names; "Role in the deal" is "Why this person"; tenures are
computed from the real start dates.

---

## Part 1 — The visual grammar

### 1.1 The source chip (the link)

Every factual sentence carries at least one **source chip**, inline, immediately after the clause it
supports (or at the end of the sentence when the whole sentence comes from one source). It is the
only way a source is ever shown. In this file a chip is written as:

`[domain](url) · verified 2 Sep 2026`  — and, where the source itself has a date —
`[domain](url) · posted 18 May 2026 · verified 1 Sep 2026`

Rendered, a chip is one inline element:

```
┌────────────────────────────────────────────┐
│ ▣ jobs.ashbyhq.com · verified 2 Sep 2026   │   ▣ = 14px favicon of the domain
└────────────────────────────────────────────┘
```

- **Favicon:** `https://www.google.com/s2/favicons?domain={domain}&sz=32` (free, no key, 150 ms,
  returns a PNG for every domain we tested). Cache it on our side. Swap to Brandfetch's Logo API
  (`https://cdn.brandfetch.io/{domain}/w/32/h/32?c={CLIENT_ID}`, free, 500k requests/month, no
  attribution) when a real logo instead of a favicon matters.
- **Label:** the bare domain, `www.` stripped (`linkedin.com`, `zafran.io`, `youtube.com`).
- **Date:** `verified {d Mon yyyy}` = the day our research fetched and checked the page (`observedAt`
  on the claim). If the source has its own publish date, show `posted …` first, then `verified …`.
  For media: `[youtube.com](…) · 00:30 · verified 2 Sep 2026` (the timestamp of the quote).
- **Facts with no public page** (an email check, a database record): no link, a lock-style icon,
  and just the date: `verified 31 Aug 2026`. The provider name never appears on the page; it lives
  in the hover card only.
- **Hover card:** page title · the verbatim quote the claim rests on · `posted` / `verified` dates ·
  provider (small, grey) · "Open ↗".
- **Click:** opens the URL in a new tab. Never navigates away.
- Style: 12px, muted foreground, 1px hairline border, 4px radius, no underline; the favicon is the
  only colour. Chips never wrap the sentence's meaning: they sit after the clause, not inside it.

### 1.2 The contact chip (a person mentioned)

`→ Nick Fisher` in this file = a **contact chip**: 20px avatar (initials fallback) + name, inline.
Click → that person's contact page. Hover → title · persona · verified email state. Every person
named in an insight gets one; the chip appears once per item, at the end of the body.

### 1.3 Section, item, priority, copy-line, empty state

- **Section (H1):** fixed product vocabulary, never model-written. 16px semibold, 24px top margin,
  optional count ("Buying signals · 4").
- **Item:** an **H2** (one line, ≤110 characters, bold 14px: the fact and why it matters) and a
  **body** (2–5 sentences, 14px regular, links inline). Items are separated by 16px, no cards.
- **Priority:** P1 items carry a 2px left accent in the brand colour and sort first inside their
  section. P2 default. P3 collapse under "Show 3 more" per section.
- **Copy-line** (contact screen only): the line the user pastes. Rendered as a quiet box under the
  body with the channel tag as its label (`In your email`, `On the landing page`, `In the platform`,
  `In the direct-mail brief`, `Brief the design agent with`) and a **Copy** button. v1 cannot send
  email, so this box *is* the deliverable; in v2 the same text seeds the email draft.
- **Empty state:** a section with no claims prints one line, grey:
  `No {section name} information found for {name}.` It never hides the H1.
- **Do not mention / Context only:** rendered muted, with a lock icon on the H1, collapsed by
  default on Insights, always open on the contact screen.
- **"New since your last visit":** a thin divider on Insights above items whose `verifiedAt` is
  later than the user's last visit.

### 1.4 What the frontend reads

One new slot on account detail and on contact detail; `claimIds` resolve against the existing
`evidence[]` list, which gains the chip fields.

```ts
type Evidence = {
  claimId: string;
  sourceUrl: string | null;        // null for email checks / database records
  sourceDomain: string | null;     // "jobs.ashbyhq.com"
  faviconUrl: string | null;       // resolved server-side, cached
  title: string | null;            // page title for the hover card
  quote: string | null;            // verbatim evidence span
  publishedAt: string | null;      // ISO date, when the source has one
  verifiedAt: string;              // ISO date, when we fetched/checked it
  mediaTimestamp: string | null;   // "00:30" for audio/video quotes
  provider: string | null;         // hover card only
  outreachSafe: boolean;
};

type DisplayBlock = {
  page: "insights" | "overview" | "contact";
  sections: Array<{
    key: string; h1: string; empty: boolean;
    items: Array<{
      h2: string;
      body: Array<{ text: string; claimIds: string[] }>;   // each sentence → its chips
      sendLine: { channel: string; text: string; claimIds: string[] } | null;
      contactRefs: Array<{ contactId: string; name: string }>;
      priority: 1 | 2 | 3;
    }>;
  }>;
};
```

Rail rows are plain fields (`core.*`, `contact.*`), not display blocks: the rail never goes through
the display model.

---

## Part 2 — Screen 1: Insights  (`/accounts/zafran-security/insights`)

**Top strip:** 42 insights · 5 people · Researched 2 Sep 2026 · 3 new since your last visit

## Account insights

### Buying signals · 4

**They have been trying to hire an ABM owner for 77 days and have not.**  (P1)
Zafran posted "Senior Manager, ABM & Integrated Campaigns" on 17 June 2026 and it is still open on
2 September [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · posted 17 Jun 2026 · verified 2 Sep 2026.
The job is to "own ABM from the ground up: 1:1 programs for your most strategic targets, 1:few
cluster plays for high-potential segments, and scaled 1:many motions where volume matters",
reporting to the Head of Growth Marketing [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · verified 2 Sep 2026.
What it means for us: the work this seat was created for is the work we do, and nobody is doing it.
→ Vari Kaur → Nick Fisher

**They are standing up a partner channel from zero. The req went live yesterday.**  (P1)
"Director of Alliances" was published on 1 September 2026: "Our partner ecosystem is becoming one
of the fastest ways security teams discover and adopt Zafran, and we're looking for a Director of
Alliances to build that engine from scratch", anchored in global systems integrators
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17) · posted 1 Sep 2026 · verified 2 Sep 2026.
What it means for us: a second net-new GTM motion with no owner yet. Alliance launches need target
lists and partner-specific content, both of which we produce.

**27 open roles, 14 of them in go-to-market.**  (P1)
Sales 11, R&D 8, Marketing 3, Customer Success 1, plus one each in Finance, Product, HR and G&A
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026. Nine were posted in
the last 30 days, four in the last seven [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026.
The CEO's framing to the press: "The development in AI is very fast, and we need more people"
[calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026.
What it means for us: a GTM org growing this fast is when a small marketing team buys the tooling
that makes it look big.

**The BDR team reports into Marketing, not Sales.**  (P2)
The "Business Development Representative" req sits in the Marketing department on Zafran's job
board and requires "regular in-office presence (approximately 3 days a week) at our NYC office"
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · posted 19 Aug 2026 · verified 2 Sep 2026.
What it means for us: pipeline ownership lives under Nick and Vari. A marketing-led purchase does
not need the sales leader's sign-off, only his cooperation.
→ Vari Kaur → Nick Fisher → Tom Anthony

### Money & momentum · 3

**$60M Series C in December 2025, led by Menlo Ventures. $130.5M raised in total.**  (P1)
The round closed on 2 December 2025 with Sequoia Capital, Cyberstarts, Amex Ventures, PSP Growth,
Vintage and Knollwood participating [crunchbase.com](https://www.crunchbase.com/organization/zafran) · verified 22 Aug 2026,
and Zafran said it had "more than tripled" ARR in the year before
[zafran.io](https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai) · posted 2 Dec 2025 · verified 2 Sep 2026.
The full ladder: $5.5M seed and a $25M venture round (March 2024), $40M Series B (September 2024),
$60M Series C (December 2025) [crunchbase.com](https://www.crunchbase.com/organization/zafran) · verified 22 Aug 2026.
What it means for us: nine months after the raise the money is allocated and marketing is expected
to show pipeline this year.

**Two strategic investors joined in 2026: Amex Ventures in February, Cisco Investments in July.**  (P2)
Zafran announced a "strategic investment from Amex Ventures" on 24 February 2026
[zafran.io](https://www.zafran.io/resources/zafran-announces-strategic-investment-from-amex-ventures) · posted 24 Feb 2026 · verified 2 Sep 2026
and a "strategic investment from Cisco Investments" on 22 July 2026
[zafran.io](https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments) · posted 22 Jul 2026 · verified 2 Sep 2026.
What it means for us: strategic money usually precedes enterprise co-selling, which is what the
alliances hire above is for. The investment is safe to reference; the acquisition rumour that
preceded it is not (see Context only).

**Revenue band $10–25M; estimated IT spend $7.6M.**  (P3)
Both are estimates, not company statements · record 22 Aug 2026.
What it means for us: budget is not the constraint on a marketing-tooling purchase here. Headcount
to run it is.

### Tools they already use · 3

**Their SDR stack is Salesforce, LinkedIn Sales Navigator, ZoomInfo and Outreach, in their own words.**  (P1)
The BDR job description says "Utilize tools such as Salesforce, LinkedIn Sales Navigator, ZoomInfo
& Outreach" [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · posted 19 Aug 2026 · verified 2 Sep 2026.
What it means for us: we plug into this stack (Salesforce as the system of record, Outreach for
sequences). We do not replace it, and we should say so in the first email.

**Marketing runs on HubSpot and Salesforce, and no ABM platform is named anywhere.**  (P1)
The ABM req asks for "proficiency in Salesforce, HubSpot and major ABM platforms" and names none
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · verified 2 Sep 2026;
the website is HubSpot-hosted [zafran.io](https://www.zafran.io/) · verified 2 Sep 2026. None of the 27
job descriptions mentions 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Madison Logic
or Clay [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026.
What it means for us: the honest read is that they have not bought an ABM platform. We are not
displacing anyone.

**They mine Gong calls for messaging, and their buyers run CrowdStrike, Akamai, Rapid7 and Palo Alto.**  (P2)
Nick Fisher described "combing through dozens of Gong calls with vuln management teams" to find the
line that "96% of vulnerabilities didn't require patching"
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
What it means for us: per-account research with the source attached is how he already works, done
for him. → Nick Fisher

### How they sell, and who they win · 3

**Named CISO customers on their homepage: Kraft Heinz, Chipotle, Netskope, Ashland.**  (P1)
Ricardo Lafosse (CISO, Kraft Heinz), Dave Estlick (CISO, Chipotle), James Robinson (CISO, Netskope)
and Robert Schuetter (CISO, Ashland) are quoted on zafran.io, alongside an unnamed Fortune 25
healthcare CISO [zafran.io](https://www.zafran.io/) · verified 2 Sep 2026; a press release adds "OpenAI
Selects Zafran for Trusted Access for Cyber"
[zafran.io](https://www.zafran.io/resources/openai-selects-zafran-for-trusted-access-for-cyber) · verified 2 Sep 2026.
What it means for us: this is the shape of account they win. Their 1:1 tier should be Fortune 500
CISOs, and that is the list we build first.

**Their target buyer is the CISO, and they describe their own motion as ABM-driven.**  (P2)
The Director of Product Marketing req asks for positioning that "resonates with CISOs, security
practitioners, and business leaders"
[zafran.io](https://www.zafran.io/open-positions/d67a7de0b50a4b7facfcb168db99148f) · verified 2 Sep 2026;
the platform routes remediation through Jira and ServiceNow, so the technical evaluator sits in
security operations [zafran.io](https://www.zafran.io/ctem-academy/best-vulnerability-management-tools-of-2026) · verified 2 Sep 2026.
What it means for us: persona-keyed content (CISO versus vulnerability-management lead) is the pitch.

**Their public proof points: 99% of critical vulnerabilities not exploitable, 90% de-risked overnight, 87% faster remediation.**  (P2)
"Zafran uses your existing security tools to prove that 99% of critical vulnerabilities are not
exploitable" [zafran.io](https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai) · posted 2 Dec 2025 · verified 2 Sep 2026;
"de-risks 90% of critical vulnerabilities overnight"
[zafran.io](https://www.zafran.io/open-positions/8c2f9f9808bf41349208e2a3d376f40e) · verified 2 Sep 2026;
RemOps content claims an "87%" cut in time per vulnerability
[zafran.io](https://www.zafran.io/resources/beyond-the-hype-remediation-operations-that-delivers-results-yi2h5) · verified 2 Sep 2026.
What it means for us: a landing page that mirrors their own numbers back at their target accounts
is the fastest brand-aligned artifact we can generate.

## Contact insights · 5

**→ Vari Kaur · Head of Growth Marketing · Champion**
**She is personally hiring the ABM seat, and says so publicly.**  (P1)
"Our marketing team at Zafran Security is expanding! 🚀 I'm hiring a Senior Manager, ABM &
Integrated Campaigns" [linkedin.com](https://www.linkedin.com/posts/varinderkaur_our-marketing-team-at-zafran-security-is-activity-7462208819037691907-EQ8X) · posted 18 May 2026 · verified 1 Sep 2026.
"Looking for someone who loves building ABM end-to-end, lead our integrated campaign strategy, and
work shoulder-to-shoulder with Sales to go after the accounts that matter most" (same post).
She holds 6sense (March 2025) and Demandbase (February 2025, February 2021) ABM certifications
[linkedin.com](https://www.linkedin.com/in/varinderkaur) · record 22 Aug 2026.
What it means for us: she knows the category, has trained on the incumbents, and is the first
conversation.

**→ Nick Fisher · VP Marketing · Economic buyer**
**He explained his own buying criteria in public.**  (P1)
"For me, the decision to join a startup comes down to 3 basic criteria": a market with a massive
unsolved problem, a product uniquely poised to solve it, and people who bring something special
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
What it means for us: pitch to his three criteria, in his order. He owns the budget Vari would spend.

**→ Sanaz Yashar · Co-Founder & CEO · Executive sponsor**
**She says her biggest challenge is changing customer habits, not the technology.**  (P1)
"No matter which technology you're bringing to the world, at the end you have to deal with habits"
[podcasters.spotify.com](https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai) · posted 10 Aug 2025 · verified 2 Sep 2026;
"the biggest pain is we don't have enough operators to operate all the different vulnerabilities"
[podcasters.spotify.com](https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai) · 05:14 · verified 2 Sep 2026.
What it means for us: an ABM program framed as changing how a buying committee behaves is her
language.

**→ Tom Anthony · SVP Global Sales · Adjacent buyer**
**Eight years at Okta, joined November 2024, based in San Francisco.**  (P2)
Previously VP Enterprise Sales at Okta and VP Global Sales & Customer Success at Upbound
[linkedin.com](https://www.linkedin.com/in/tomanthonyjr) · record 22 Aug 2026. BDRs do not report to him
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · verified 2 Sep 2026.
What it means for us: bring him in once the 1:1 account list exists. He will want to pick the
accounts.

**→ Ben Seri · Co-Founder & CTO · Technical evaluator**
**Six years as VP of Research at Armis before founding Zafran.**  (P3)
[linkedin.com](https://www.linkedin.com/in/ben-seri) · record 22 Aug 2026. No posts, talks or articles found.
What it means for us: not a stakeholder for a marketing purchase. Skip unless a security-data
integration comes up.

## 🔒 Context only — never use in outreach  (collapsed by default)

- **Cisco acquisition rumour, July 2026: refuted.** Calcalist reported acquisition talks "at a
  steep discount" [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026;
  Globes then reported "Cisco investing in, not acquiring"
  [globes.co.il](https://en.globes.co.il/en/article-cisco-investing-in-not-acquiring-zafran-security-1001550210) · verified 2 Sep 2026;
  Zafran's own release confirms an investment
  [zafran.io](https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments) · posted 22 Jul 2026 · verified 2 Sep 2026. Never mention.
- **Third-party ARR and burn commentary: unresolved.** CTech cited "roughly $20 million" ARR and an
  unnamed executive on "cash burn remains high"
  [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026. Never repeat.
  It does explain the urgency behind 27 open reqs.
- **Co-founder and CPO Snir Havdala left for NVIDIA: confirmed.** Zafran said the move "was planned
  and coordinated"; Itay Nachum (VP Product) took over
  [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026. Do not reference.

---

## Part 3 — Screen 2: Account Overview  (`/accounts/zafran-security`)

**Header:** Zafran Security · zafran.io · Cybersecurity · Series C · New York · **Overall fit: High** · Researched 2 Sep 2026

## What Zafran does

Zafran sells an AI-native "threat exposure management" platform to security teams. It takes the
findings from the scanners a company already owns, works out which vulnerabilities an attacker
could actually exploit, and drives the fix through tools already in place: Jira, ServiceNow and the
existing security controls [zafran.io](https://www.zafran.io/platform) · verified 2 Sep 2026. The company's
own claims are that "99% of critical vulnerabilities are not exploitable"
[zafran.io](https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai) · posted 2 Dec 2025 · verified 2 Sep 2026
and that it "de-risks 90% of critical vulnerabilities overnight"
[zafran.io](https://www.zafran.io/open-positions/8c2f9f9808bf41349208e2a3d376f40e) · verified 2 Sep 2026. It packages a
core platform plus two add-ons, Zafran Discover and Zafran Autonomous Workflows
[calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026.

Founded in 2022 by Sanaz Yashar (CEO), Ben Seri (CTO) and Snir Havdala
[zafran.io](https://www.zafran.io/about) · verified 2 Sep 2026, it is headquartered in New York with its founders
and R&D in Tel Aviv [linkedin.com](https://www.linkedin.com/company/zafran-security) · record 22 Aug 2026. It has
167 employees · record 22 Aug 2026, has raised $130.5M across four rounds, most recently a $60M
Series C led by Menlo Ventures in December 2025
[zafran.io](https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai) · posted 2 Dec 2025 · verified 2 Sep 2026,
and lists Fortune 500 CISOs at Kraft Heinz, Chipotle, Netskope and Ashland as customers
[zafran.io](https://www.zafran.io/) · verified 2 Sep 2026.

## Why they fit  (Overall fit: High)

✓ **US-headquartered, Series C, well past the Series A bar.** New York HQ; $60M Series C on 2 Dec
  2025; $130.5M total [crunchbase.com](https://www.crunchbase.com/organization/zafran) · verified 22 Aug 2026.
✓ **Marketing-led go-to-market with a live ABM need.** An unfilled "Senior Manager, ABM & Integrated
  Campaigns" seat, open 77 days, reporting to the Head of Growth Marketing
  [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · posted 17 Jun 2026 · verified 2 Sep 2026;
  BDRs sit under Marketing [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · verified 2 Sep 2026.
✓ **Quantifiable pain.** 27 open reqs, 14 in GTM [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026,
  and a CEO saying "we need more people" [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026.
✓ **No ABM platform in place.** 27 job descriptions name Salesforce, HubSpot, ZoomInfo, Outreach and
  Sales Navigator [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026, and Nick
  names Gong [linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
  No ABM vendor anywhere.
✓ **They sell to a named, researchable persona.** CISOs at Fortune 500 and high-growth companies
  [zafran.io](https://www.zafran.io/) · verified 2 Sep 2026.
✗ **Small marketing team.** Only two marketing leaders can be named, Nick Fisher and Vari Kaur
  [zafran.io](https://www.zafran.io/about) · verified 2 Sep 2026, with three open marketing reqs
  [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026. Fewer hands to run a program;
  stronger case for one that runs itself.
✗ **Sales leadership is West Coast and eleven sales reqs are regional.** Tom Anthony is in San
  Francisco [linkedin.com](https://www.linkedin.com/in/tomanthonyjr) · record 22 Aug 2026; the 1:1 tier will need his
  buy-in for territory alignment.

## Why now  (top 3 · see all 42 insights →)

1. **The ABM seat has been open 77 days** [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · verified 2 Sep 2026.
   The program exists on paper only. → Vari Kaur
2. **Director of Alliances posted 1 Sep 2026**, a second GTM motion starting "from scratch"
   [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17) · posted 1 Sep 2026 · verified 2 Sep 2026.
3. **Nine months post Series C, two strategic investors added in 2026**
   [zafran.io](https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments) · posted 22 Jul 2026 · verified 2 Sep 2026.
   Pipeline expectations for the year are set.

## Buying committee

| Person | Title | Persona | Reach | Why they matter |
|---|---|---|---|---|
| → Vari Kaur | Head of Growth Marketing | Champion | vari@zafran.io ✓ verified 31 Aug 2026 · [linkedin.com](https://www.linkedin.com/in/varinderkaur) | Owns demand gen and the ABM seat she is hiring; 6sense- and Demandbase-certified. |
| → Nick Fisher | VP Marketing | Economic buyer | nick@zafran.io ✓ verified 31 Aug 2026 · [linkedin.com](https://www.linkedin.com/in/nicholastfisher) 6.8k followers | Runs marketing; Vari reports to him; publishes his own buying criteria. |
| → Sanaz Yashar | Co-Founder & CEO | Executive sponsor | sanaz@zafran.io ✓ verified 2 Sep 2026 · [linkedin.com](https://www.linkedin.com/in/sanaz-yashar) | Public voice on "habits" and under-resourced operators. |
| → Tom Anthony | SVP Global Sales | Adjacent buyer | tom@zafran.io ✓ verified 2 Sep 2026 · [linkedin.com](https://www.linkedin.com/in/tomanthonyjr) | Must align on the 1:1 account list; does not own BDRs. |
| → Ben Seri | Co-Founder & CTO | Technical evaluator | not requested · [linkedin.com](https://www.linkedin.com/in/ben-seri) | Not a stakeholder for this purchase. |

## How to approach

**Lead with marketing, not sales.** Vari is the champion: she is hiring the seat, holds the
certifications, and is 16 months into the role. Nick is the budget. Tom is consulted. Sanaz is the
sponsor only if this becomes a company-level bet.

**The message.** "The ABM program you have been hiring for since June, running on your top 50 CISO
accounts inside HubSpot and Salesforce, without waiting for the hire."

**The proof to show.** Account and committee research at the depth of this page, on peers of their
own named customers (Kraft Heinz, Chipotle, Netskope).

**Tier and channels.** 1:1. Email and LinkedIn to Vari and Nick. A landing page that mirrors their
own 99% / 90% / 87% proof points. Direct mail only for Nick (see his page).

**Timing.** Now. The alliances req and the four postings in the last seven days say next quarter's
GTM plan is being set this month.

## 🔒 Watch-outs  (never in outreach)

- The Cisco acquisition rumour is refuted; a rep repeating it burns the account.
- Third-party ARR and burn commentary is unconfirmed; do not cite.
- The co-founder departure; do not reference.

## Right rail

**Core**
- Account: Zafran Security
- Owner: —
- Industry: Cybersecurity · Risk management · Network security
- Headcount: 167 (51–200)
- Revenue: $10–25M
- Founded: 2022
- HQ: New York, NY
- Funding: Series C · $130.5M total
- Research status: Researched · 2 Sep 2026
- Website: [zafran.io](https://www.zafran.io) · [LinkedIn](https://www.linkedin.com/company/zafran-security) · [X](https://x.com/Zafran_io)
- Overall buying fit: High
- Fit score: —

**Custom**  (the client's own variables; each is a registry row)
- ABM platform in place: None named
- Open GTM roles: 14
- Longest-open marketing req: 77 days
- ATS: Ashby
- Marketing system of record: HubSpot

**Contacts** · 5 (4 with verified email)

**Activity** · Committee confirmed 2 Sep 2026 · Account researched 2 Sep 2026 · Person research 1 Sep 2026

---

## Part 4 — Screen 3: Contact, Nick Fisher  (`/accounts/zafran-security/contacts/nick-fisher`)

**Header:** Nick Fisher · VP Marketing at Zafran Security · **Economic buyer** · New York

**Core rail**
- Name: Nick Fisher
- Account: → Zafran Security
- Title: VP of Marketing · record 22 Aug 2026
- Persona: Economic buyer
- Email: nick@zafran.io ✓ verified 31 Aug 2026
- LinkedIn: [linkedin.com/in/nicholastfisher](https://www.linkedin.com/in/nicholastfisher) · 6,808 followers · creator
- Location: New York, NY · in the NYC office ~3 days a week [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · verified 2 Sep 2026
- Best first channel: LinkedIn, then email
- Education: Columbia Business School MBA (2013) · Vassar BA · record 22 Aug 2026
- At Zafran since: April 2024 (2 years 5 months)
- Reports: Vari Kaur (Head of Growth Marketing)

## Why this person

**He owns marketing at Zafran, and the ABM seat sits in his org.**  (P1)
Nick has been VP of Marketing since April 2024 [linkedin.com](https://www.linkedin.com/in/nicholastfisher) · record 22 Aug 2026.
The unfilled ABM manager req reports to the Head of Growth Marketing, Vari Kaur, who reports to him
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · verified 2 Sep 2026.
> **In the platform:** he is the economic buyer, so his page leads the 1:1 plan. In your email, write to him as the person accountable for pipeline this year, not as the person who will operate the tool.  [Copy]

**He has marketed in this exact category before: Okta, Sysdig, Lookout.**  (P1)
Senior Director of Product Marketing at Okta (2018–2021), VP Product Marketing at Sysdig
(2021–2024), Director of Enterprise Product Marketing at Lookout (2014–2018)
[linkedin.com](https://www.linkedin.com/in/nicholastfisher) · record 22 Aug 2026.
> **In your email:** do not explain ABM; he has run it at scale. Reference the difference between a program run by a three-person team and one run at Okta.  [Copy]

**He does his own customer research, and it shows in the messaging. That is a strength, and it tells you how to sell to him.**  (P1)
He found Zafran's best proof point, "96% of vulnerabilities didn't require patching", by "combing
through dozens of Gong calls with vuln management teams" himself
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
Read this as a buyer who trusts evidence he has seen with his own eyes, not vendor claims. The
limit is scale: he can do that for Zafran's message once, not for every target account.
> **In your email:** "You went through dozens of Gong calls to find the 96% line. That is what we do for each of your target accounts, with the source on every line." On the landing page, show one per-account insight with its citation visible, so he can check it the way he checks Gong.  [Copy]

**He says what he wants in public: "3 basic criteria".**  (P2)
In "Why I joined Zafran Security" he wrote that his decision comes down to "Is this a market with a
massive unsolved problem at the center? Is the product poised to solve it in a unique and valuable
way? Do the people bring something special in creating a world-class company?"
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
> **In your email:** structure the pitch in that order: the problem (the seat is empty), the product (research-grade ABM that runs itself), the people (us).  [Copy]

## Their problem right now

**The ABM seat under him has been open 77 days.**  (P1)
"Senior Manager, ABM & Integrated Campaigns", posted 17 June 2026, still live on 2 September. The
job is to "own ABM from the ground up: 1:1 programs… 1:few cluster plays… scaled 1:many motions"
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · posted 17 Jun 2026 · verified 2 Sep 2026.
> **In your email:** "You've been trying to hire someone to own ABM from the ground up since June. Here is that program already running on your top accounts."  [Copy]

**The team has to look bigger than it is: three marketing reqs open, fourteen GTM roles overall.**  (P1)
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026. Zafran's CEO told the press "we
need more people" [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026.
> **In your email:** lead with output, not features: what a three-person team ships in a week when account-grade research is done for them.  [Copy]

**Whatever he buys has to fit HubSpot, Salesforce and Outreach.**  (P2)
Marketing stack: HubSpot and Salesforce
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · verified 2 Sep 2026;
SDR stack: Salesforce, Sales Navigator, ZoomInfo, Outreach
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · verified 2 Sep 2026;
no ABM platform named [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security) · verified 2 Sep 2026.
> **In your email:** one sentence: "Runs inside HubSpot and Salesforce. Nothing to rip out."  [Copy]

## Openers

**Warm it on LinkedIn first. It is his home channel: creator badge, long-form articles.**  (P1)
[linkedin.com](https://www.linkedin.com/in/nicholastfisher) · record 22 Aug 2026. Comment on the "Why I joined"
article [linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026
or his book post a few days before the email, so the email reads as a follow-up to a conversation
he started, not a cold send.

**The cocktail-chemistry opener. Strongest, and safe: he published it himself.**  (P1)
He created the Cocktail Chemistry YouTube channel in 2014 and wrote the book "Cocktail Chemistry:
The Art and Science of Drinks from Iconic TV Shows and Movies"
[linkedin.com](https://www.linkedin.com/posts/nicholastfisher_if-weve-worked-together-you-may-have-discovered-activity-6932337822636937217-ptV7) · verified 1 Sep 2026
· [simonandschuster.com](https://www.simonandschuster.com/authors/Nick-Fisher/177280135) · verified 2 Sep 2026.
In his own voice: "It is a side hobby for me and one that is quite expensive and time consuming… I
invest a lot in top quality liquors… as well as equipment that I use, whether it's a smoking gun or
immersion circulator" [youtube.com](https://www.youtube.com/watch?v=8_YWBtq4eic) · 00:05–00:30 · verified 2 Sep 2026.
Use once, first line only, never in the subject.
> **In your email:** "Nick, anyone who runs ice experiments to get a Moscow Mule right cares about detail. Here is that level of detail applied to your top 50 accounts, while the ABM seat stays open."  [Copy]

**The empty-seat opener.**  (P1)
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf) · posted 17 Jun 2026 · verified 2 Sep 2026.
> **In your email:** "Since June you've been hiring someone to own ABM from the ground up: 1:1, 1:few, 1:many. Here's the 1:1 tier already built for Zafran: [three named accounts]."  [Copy]

**The Gong opener.**  (P2)
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
> **In your email:** "You found the '96% didn't need patching' line in Gong. Here is what the same digging turns up on Kraft Heinz's peers, with the source on every line."  [Copy]

**The Okta opener.**  (P2)
[linkedin.com](https://www.linkedin.com/in/nicholastfisher) · record 22 Aug 2026.
> **In your email:** "At Okta you had a team for this. At Zafran you have Vari and an open req. This is the version that runs without the team."  [Copy]

## Angles

**Direct mail: bar-grade gear with a two-line card.**  (P1)
He said on camera he buys smoking guns, immersion circulators and "high quality glassware" for the
channel [youtube.com](https://www.youtube.com/watch?v=8_YWBtq4eic) · 00:30 · verified 2 Sep 2026. Ship to the NYC
office [jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13) · verified 2 Sep 2026.
> **In the direct-mail brief:** a good bar tool with a card: "Precision matters. Here's ours."  [Copy]

**Landing page: "The chemistry of ABM", mirroring his own numbers.**  (P1)
Frame it as ingredients (signals), technique (research), the pour (the campaign), and reuse
Zafran's own proof points, 99% not exploitable
[zafran.io](https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai) · posted 2 Dec 2025 · verified 2 Sep 2026,
90% overnight [zafran.io](https://www.zafran.io/open-positions/8c2f9f9808bf41349208e2a3d376f40e) · verified 2 Sep 2026,
87% faster [zafran.io](https://www.zafran.io/resources/beyond-the-hype-remediation-operations-that-delivers-results-yi2h5) · verified 2 Sep 2026,
as the design language.
> **Brief the design agent with:** "The chemistry of ABM — ingredients, technique, the pour. Use Zafran's 99% / 90% / 87% as the visual motif."  [Copy]

**Content: his "3 criteria" as the structure of the pitch.**  (P2)
[linkedin.com](https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf) · verified 1 Sep 2026.
> **On the landing page:** follow his order: problem, product, people.  [Copy]

**Event: a small NYC dinner around the alliances launch.**  (P2)
Director of Alliances posted 1 Sep 2026
[jobs.ashbyhq.com](https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17) · posted 1 Sep 2026 · verified 2 Sep 2026.
> **For the event:** a partner-themed dinner is a reason to get Nick, Vari and Tom in one room.  [Copy]

## 🔒 Do not mention

- **The Cisco acquisition rumour (refuted).** [globes.co.il](https://en.globes.co.il/en/article-cisco-investing-in-not-acquiring-zafran-security-1001550210) · verified 2 Sep 2026
- **Third-party ARR and burn commentary (unconfirmed).** [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026
- **The co-founder's departure.** [calcalistech.com](https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl) · verified 2 Sep 2026
- **The cocktail hook more than once.**

**Empty-state line for any section with no claims:** "No {section} information found for Nick Fisher."

---

## Part 5 — Link register

Every URL above, with the date to show and the favicon URL to render. `record` = a database record
we hold (no public page; the LinkedIn profile is the human-readable locator). `verified` = the day
our research fetched and checked the page.

| domain shown | URL | posted | verified | favicon |
|---|---|---|---|---|
| jobs.ashbyhq.com | https://jobs.ashbyhq.com/zafran-security | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=jobs.ashbyhq.com&sz=32 |
| jobs.ashbyhq.com | https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf (ABM req) | 17 Jun 2026 | 2 Sep 2026 | same |
| jobs.ashbyhq.com | https://jobs.ashbyhq.com/zafran-security/b7b67d8b-b559-4cb8-bc1c-080f268c4c17 (Director of Alliances) | 1 Sep 2026 | 2 Sep 2026 | same |
| jobs.ashbyhq.com | https://jobs.ashbyhq.com/zafran-security/9b7a9e8e-56ac-4358-b312-848dbdfe7e13 (BDR) | 19 Aug 2026 | 2 Sep 2026 | same |
| jobs.ashbyhq.com | https://jobs.ashbyhq.com/zafran-security/2441fd5c-2d63-4f17-a6ee-a7aad50bd2e7 (Sr Technical Marketing Mgr) | 17 Jun 2026 | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/ | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=zafran.io&sz=32 |
| zafran.io | https://www.zafran.io/platform | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/about | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai | 2 Dec 2025 | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/resources/zafran-announces-strategic-investment-from-amex-ventures | 24 Feb 2026 | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments | 22 Jul 2026 | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/resources/openai-selects-zafran-for-trusted-access-for-cyber | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/resources/beyond-the-hype-remediation-operations-that-delivers-results-yi2h5 | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/open-positions/d67a7de0b50a4b7facfcb168db99148f (Director of Product Marketing) | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/open-positions/8c2f9f9808bf41349208e2a3d376f40e | — | 2 Sep 2026 | same |
| zafran.io | https://www.zafran.io/ctem-academy/best-vulnerability-management-tools-of-2026 | — | 2 Sep 2026 | same |
| calcalistech.com | https://www.calcalistech.com/ctechnews/article/s1e1gw3zbl | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=calcalistech.com&sz=32 |
| globes.co.il | https://en.globes.co.il/en/article-cisco-investing-in-not-acquiring-zafran-security-1001550210 | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=globes.co.il&sz=32 |
| crunchbase.com | https://www.crunchbase.com/organization/zafran | — | 22 Aug 2026 (record) | https://www.google.com/s2/favicons?domain=crunchbase.com&sz=32 |
| linkedin.com | https://www.linkedin.com/company/zafran-security | — | 22 Aug 2026 (record) | https://www.google.com/s2/favicons?domain=linkedin.com&sz=32 |
| linkedin.com | https://www.linkedin.com/in/nicholastfisher | — | 22 Aug 2026 (record) | same |
| linkedin.com | https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf | — | 1 Sep 2026 | same |
| linkedin.com | https://www.linkedin.com/posts/nicholastfisher_if-weve-worked-together-you-may-have-discovered-activity-6932337822636937217-ptV7 | — | 1 Sep 2026 | same |
| linkedin.com | https://www.linkedin.com/in/varinderkaur | — | 22 Aug 2026 (record) | same |
| linkedin.com | https://www.linkedin.com/posts/varinderkaur_our-marketing-team-at-zafran-security-is-activity-7462208819037691907-EQ8X | 18 May 2026 | 1 Sep 2026 | same |
| linkedin.com | https://www.linkedin.com/posts/varinderkaur_agenticai-exposuremanagement-vulnerabilitymanagement-activity-7401630503994441728-1g1G | 2 Dec 2025 | 1 Sep 2026 | same |
| linkedin.com | https://www.linkedin.com/in/sanaz-yashar | — | 22 Aug 2026 (record) | same |
| linkedin.com | https://www.linkedin.com/in/tomanthonyjr | — | 22 Aug 2026 (record) | same |
| linkedin.com | https://www.linkedin.com/posts/tomanthonyjr_last-week-the-zafran-security-team-came-together-activity-7437536933347717120-xXxL | — | 2 Sep 2026 | same |
| linkedin.com | https://www.linkedin.com/in/ben-seri | — | 22 Aug 2026 (record) | same |
| podcasters.spotify.com | https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai | 10 Aug 2025 | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=podcasters.spotify.com&sz=32 |
| podcasts.apple.com | https://podcasts.apple.com/us/podcast/ai-summit-sanaz-yashar-co-founder-and-ceo-at-zafran-security/id1749699539?i=1000721382470 | 10 Aug 2025 | 1 Sep 2026 | https://www.google.com/s2/favicons?domain=podcasts.apple.com&sz=32 |
| youtube.com | https://www.youtube.com/watch?v=8_YWBtq4eic ("Supporting Cocktail Chemistry") | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=youtube.com&sz=32 |
| youtube.com | https://www.youtube.com/watch?v=avcD5WVLCYs (Moscow Mule) | — | 2 Sep 2026 | same |
| simonandschuster.com | https://www.simonandschuster.com/authors/Nick-Fisher/177280135 | — | 2 Sep 2026 | https://www.google.com/s2/favicons?domain=simonandschuster.com&sz=32 |
| forbes.com | https://www.forbes.com/sites/thomasbrewster/2024/03/28/she-fled-iran-and-became-an-israeli-spy-now-shes-raised-30-million-for-a-cyber-startup/ | 28 Mar 2024 | 1 Sep 2026 | https://www.google.com/s2/favicons?domain=forbes.com&sz=32 |
| theorg.com | https://theorg.com/org/zafran-security/org-chart/nick-fisher | — | 1 Sep 2026 | https://www.google.com/s2/favicons?domain=theorg.com&sz=32 |
| x.com | https://x.com/Zafran_io | — | 22 Aug 2026 (record) | https://www.google.com/s2/favicons?domain=x.com&sz=32 |
| (no link) | email mailbox checks: vari@ / nick@ 31 Aug 2026; sanaz@ / tom@ 2 Sep 2026 | — | as stated | lock icon |
