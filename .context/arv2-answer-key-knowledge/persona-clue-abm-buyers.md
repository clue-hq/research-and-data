---
kind: audience-persona
icp_key: clue-abm-buyers
icp_version: 1
personas:
  - role: economic_buyer
    titles: ["CEO", "Co-Founder & CEO", "Chief Revenue Officer", "CRO", "Chief Marketing Officer", "CMO"]
    buying_triggers:
      - "A priced round announced with 'go-to-market' or 'sales and marketing' in the stated use of proceeds"
      - "A founder post or podcast about leaving founder-led sales or about outbound cost"
      - "A new CRO, CMO or VP Marketing announced in the last nine months"
      - "An acquisition rumour or refuted acquisition story (the company must show independent momentum)"
    evidence_urls:
      - "https://www.probook.ai/letter"
      - "https://www.globenewswire.com/news-release/2026/06/23/3316215/0/en/Probook-Raises-40M-from-Andreessen-Horowitz-and-Sequoia-to-Scale-the-AI-Operating-System-for-Home-Services.html"
  - role: champion
    titles: ["VP Marketing", "VP of Marketing", "Head of Growth", "Head of Growth Marketing", "Head of Marketing", "Director of Demand Generation", "Senior Manager, ABM", "ABM Manager"]
    buying_triggers:
      - "An open ABM, integrated-campaigns or account-based requisition on the company's own board"
      - "A requisition that describes list-building or account research as the job"
      - "The champion joined in the last nine months (a 'why I joined' post is the tell)"
      - "Two or more concurrent marketing openings"
    evidence_urls:
      - "https://jobs.ashbyhq.com/zafran-security"
      - "https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf"
  - role: user
    titles: ["SDR Manager", "Sales Development Manager", "Growth Marketing Manager", "Demand Generation Manager", "Marketing Manager", "Business Development Representative", "Sales Development Representative"]
    buying_triggers:
      - "An SDR or BDR requisition that names a defined target list ('the list exists')"
      - "A BDR seat filed under the marketing department"
      - "Outbound tooling absent from the job requirements (no sales-engagement platform named)"
    evidence_urls:
      - "https://www.probook.ai/careers"
      - "https://jobs.ashbyhq.com/zafran-security"
  - role: technical_evaluator
    titles: ["Co-Founder & CTO", "CTO", "Head of Revenue Operations", "Revenue Operations Lead", "Marketing Operations Manager"]
    buying_triggers:
      - "A marketing-operations or RevOps requisition that lists the CRM and outbound stack to be operated"
      - "A CRM or marketing-automation migration visible in job requirements or the site's technology footprint"
    evidence_urls:
      - "https://jobs.ashbyhq.com/zafran-security"
  - role: blocker
    titles: ["CFO", "VP Finance", "Head of Procurement", "Chief Information Security Officer"]
    buying_triggers:
      - "A stated hiring freeze, layoff or down-round (spend scrutiny rises)"
      - "A security-vendor buyer: the CISO reviews any tool that touches customer and prospect data"
    evidence_urls: []
---

# Personas — Clue's ABM buyers (stand-in v1, answer-key workspace)

**Provenance.** A stand-in for the `audience-persona` artifact the onboarding synthesis agent (O4,
skill `audience-persona` v1) will author from live evidence. Every quoted fact below comes from a
proof-of-concept run's saved response (`.context/arv2-clue-sample-v3`, `.context/arv2-one-account-
aiark`, `.context/arv2-smoke-cluehq`); everything else is marked inference. Sections follow the O4
skill's eleven headings, shortened. The research lane reads `titles[]` for committee resolution and
`buying_triggers[]` as signal instructions; the frontend reads `role` for committee chips.

## economic_buyer

1. **Role and snapshot.** The founder-CEO or the revenue chief at a 30-to-300-person, Series A-or-
   later B2B software company. They own the number, they approved the GTM hires, and they feel the
   gap between the target list and the pipeline personally. Probook's CEO wrote that he was scaling
   "go-to-market team against surging demand" (https://www.globenewswire.com/news-release/2026/06/23/3316215/0/en/Probook-Raises-40M-from-Andreessen-Horowitz-and-Sequoia-to-Scale-the-AI-Operating-System-for-Home-Services.html).
2. **Titles.** CEO; Co-Founder & CEO; Chief Revenue Officer; CRO; Chief Marketing Officer; CMO.
3. **Daily reality.** Board updates on pipeline coverage (inference). Hiring GTM leaders and
   watching ramp time (Probook: 13 open roles, 6 GTM, per its careers page). Deciding which named
   accounts get founder time (inference).
4. **Core fears.** Burning the round on headcount that does not convert. Being outspent by
   incumbents with ABM platforms. A stalled category story after a public rumour.
5. **Deep motivations.** Prove the go-to-market machine works without them in every deal; reach
   the top of the market before competitors do.
6. **Critical pain points.** Founder-led sales past its ceiling: "Being stuck in founder-led sales
   isn't a flex" (Probook CEO post, quoted in `.context/arv2-clue-sample-v3/CLUE-SAMPLE-RUN.md`).
   Named-account programs capped by the size of the marketing team.
7. **Buying triggers.** See front matter.
8. **Trust builders.** "Show me the account you researched for us, with sources." "Prove the
   output is ours, not a template."
9. **Trust killers.** Fabricated facts about their own company. A pitch that ignores the round
   they just announced. Vendor-speak about "AI" without a produced artifact.
10. **Language and channels.** "Pipeline coverage", "named accounts", "founder-led". LinkedIn
    posts, founder podcasts, investor announcements.
11. **How the products serve them.** Clue's site states the economic claim directly: "More output,
    same headcount" and "The depth once reserved for ten strategic accounts can now extend across
    the entire market without adding the team required to produce it" (https://www.cluehq.ai).

## champion

1. **Role and snapshot.** The marketing or growth leader who owns the account-based program and
   usually the requisition that describes it. At Zafran the Head of Growth Marketing (joined May
   2025) owns an open "Senior Manager, ABM & Integrated Campaigns" seat published 2026-06-17
   (https://jobs.ashbyhq.com/zafran-security).
2. **Titles.** VP Marketing; Head of Growth; Head of Growth Marketing; Head of Marketing;
   Director of Demand Generation; Senior Manager, ABM; ABM Manager.
3. **Daily reality.** Running campaigns across a 2-to-15-person team while hiring for the roles
   that would do the account research (Zafran: 27 open requisitions at research time). Sourcing
   account context by hand before every 1:1 program (inference from the requisition text).
4. **Core fears.** Shipping generic campaigns to strategic accounts. Losing the ABM headcount
   request. Being measured on pipeline they cannot produce fast enough.
5. **Deep motivations.** Run a program that sales respects; be the person who made ABM real.
6. **Critical pain points.** "Days lost gathering account context" and "Creative rebuilt for
   every channel" (Clue's own before/after, https://www.cluehq.ai, quoted as the problem the
   champion recognises). A 77-day-open ABM requisition (Zafran, as of 2026-09-02).
7. **Buying triggers.** See front matter.
8. **Trust builders.** "Show me a microsite built for one of my accounts." "Prove you cite
   sources for every claim."
9. **Trust killers.** Wrong facts about a target account. A template with the logo swapped.
   Anything that needs a six-month implementation.
10. **Language and channels.** "ABM", "integrated campaigns", "1:1 and 1:few", "account
    intelligence". LinkedIn, marketing communities, vendor comparison threads.
11. **How the products serve them.** "Custom research: define the questions, sources, and signals
    Clue investigates for every account" and "Microsites: not a page with the company name swapped
    in, an experience shaped around the account" (https://www.cluehq.ai).

## user

1. **Role and snapshot.** The person who works the list every day: an SDR or BDR, a demand-gen or
   growth marketing manager. Probook's SDR requisition says it plainly: "We have a clearly defined
   target: the top home service operators in America. The list exists. … What we need now is
   someone to go get them" (https://www.probook.ai/careers).
2. **Titles.** SDR Manager; Sales Development Manager; Growth Marketing Manager; Demand Generation
   Manager; Marketing Manager; Business Development Representative; Sales Development Representative.
3. **Daily reality.** Researching accounts one at a time before outreach; assembling openers from
   LinkedIn and news by hand; operating whatever outbound tooling exists (inference; Probook's
   footprint showed no CRM, sales-engagement or ABM platform detected, per the v3 run).
4. **Core fears.** Sending the wrong fact to a senior buyer. Quota without a research budget.
5. **Deep motivations.** Book meetings that hold; spend time talking, not searching.
6. **Critical pain points.** Manual account research; no verified contact data; every touch built
   from scratch.
7. **Buying triggers.** See front matter.
8. **Trust builders.** "Show me the quote and the URL behind every line." "Prove the email is
   verified."
9. **Trust killers.** Unsourced claims; stale job data; a tool that adds steps to the day.
10. **Language and channels.** "Openers", "hooks", "verified email", "sequence". Sales
    communities, LinkedIn.
11. **How the products serve them.** "Deep Research: Clue brings together 50+ company, market,
    intent, leadership and personal signals … into one sourced account" (https://www.cluehq.ai).

## technical_evaluator

1. **Role and snapshot.** The technical co-founder or CTO at a company this size, or the revenue-
   or marketing-operations lead who owns the CRM. Zafran's stack footprint (HubSpot-hosted pages,
   Google Workspace mail) was read from its site during the one-account run.
2. **Titles.** Co-Founder & CTO; CTO; Head of Revenue Operations; Revenue Operations Lead;
   Marketing Operations Manager.
3. **Daily reality.** Keeping the CRM and marketing automation coherent; reviewing any vendor that
   writes into them (inference).
4. **Core fears.** A tool that pollutes the CRM; a vendor with no data-handling story.
5. **Deep motivations.** Fewer point tools; audiences and creative that sync cleanly.
6. **Critical pain points.** "Strategy scattered across teams and tools" (https://www.cluehq.ai).
7. **Buying triggers.** See front matter.
8. **Trust builders.** "Show me how audiences sync to LinkedIn, Meta and the CRM." "Prove
   personal data is governed."
9. **Trust killers.** Opaque data sourcing; no export path; a closed system.
10. **Language and channels.** "Integration", "sync", "data governance". Vendor docs, security
    questionnaires.
11. **How the products serve them.** "Native activation: sync audiences and creative across
    LinkedIn, Meta, CRM, sales, and direct mail" (https://www.cluehq.ai).

## blocker

1. **Role and snapshot.** Finance or procurement at any account; the CISO at a security vendor
   such as Zafran, where any tool touching prospect data is reviewed (inference).
2. **Titles.** CFO; VP Finance; Head of Procurement; Chief Information Security Officer.
3. **Daily reality.** Approving spend against the plan; vendor risk review (inference).
4. **Core fears.** Another marketing tool with unclear ROI; a data incident from a vendor.
5. **Deep motivations.** Predictable spend; defensible vendor list.
6. **Critical pain points.** Not their pain to solve; they gate it.
7. **Buying triggers.** See front matter. A refuted acquisition story (Zafran, July 2026) means
   spend scrutiny is high and the champion needs a cost-per-account number.
8. **Trust builders.** "Show me cost per account." "Prove personal data stays within its use
   class."
9. **Trust killers.** Open-ended pricing; no DSAR or erasure story.
10. **Language and channels.** "Vendor risk", "budget line", "ROI". Procurement portals, security
    reviews.
11. **How the products serve them.** "Human in the loop: review the strategy, refine the creative,
    and approve what goes live" (https://www.cluehq.ai). Cost per account is recorded per provider
    call on the research ledger.
