# Account discovery on Exa Agent — decisions so far (2026-11-10)

Status: **design in progress, not yet a full design.** This records what was found, tried and
decided in the conversation of 2026-11-10, so the written design can be finished from it. No
platform code has changed. The trial lives in `trials/exa-agent-discovery/` on branch
`trial/exa-agent-discovery`.

## 1. How discovery works today (read from the code, Head of ABM v87)

- The person asks in a project chat. The Head of ABM writes the search itself and calls
  `launch_arv2_discovery@3` with `target_count`, `query`, 1–5 `criteria`, 2–8 `gates` (each
  `must`, `must_not` or `prefer`), `exclude` (existing customers from
  `brand/knowledge/proof/customers.md`, plus the seller's domains) and `source` (`websets` or
  `search`). Section 7b of `stage0-interview@v60` teaches it. The brief is never shown to the
  person.
- The launch (`clue_api/arv2/discovery_launch.py`) checks the pinned confirmed ICP, writes the run,
  and queues a fleet task. One discovery per project at a time; the chat that launched it is busy
  and messages sent meanwhile are held, then answered.
- The fleet driver (`clue_api/arv2/discovery_driver.py`) runs up to four rounds of the same brief.
  `websets` sends the query and criteria to Exa Websets; `search` sends **only the query** to Exa
  search (criteria are unused). Each company found gets one Exa `/answer` call for its real website
  and one per gate (4 in flight). Only a date-window check remains in code. A failed `must` or
  passed `must_not` excludes; the rest join the project with a fit over `must` and `prefer` gates.
  AI Ark fills firmographics. The chat gets a summary turn when the run ends.
- Drift found: `manual-discovery@v33` still tells the agent about quote-on-page and right-company
  checks that were removed from code on 2026-10-01.

## 2. The trial (Illumio, confirmed ICP "global banks and insurers", ask: 5 top companies)

One Exa Agent run (`POST /agent/runs`) with the instruction block in
`trials/exa-agent-discovery/system_prompt.md` and the output in `output_schema.json`; every cited
quote is then re-fetched and checked (`check_quotes.py`).

| Run | Effort | Cost / time | Result | Quotes on page |
| --- | --- | --- | --- | --- |
| 1 | high | $0.50 / 3 min | 5 top + 3 caveat; ran out of steps; many gates unclear | 26/35 |
| 2 | auto | $1.35 / 4 min | 5 top + 2 caveat, all US; big obvious names | 30/30 |
| 3 | auto, with "reasons to act now" | $0.97 / 4.5 min | 5 top across FR, US, UK, DE, each with a dated trigger (breach, attack, migration) | 28/28 |

- Production has no platform discovery run for Illumio. The baseline is the hand discovery of
  2026-11-02 (U.S. Bank, Erie Insurance, Nordea, chosen for reasons to act now: new CISO, a
  ransomware attack, outages and DORA). Run 3 matches its kind of list; no company overlaps it.
- Weak in every run: in-house builds, contract end dates and named unhappy users were never found;
  "uses a competitor" was found only in runs 1–2. No check for a quiet existing customer beyond the
  exclusion list (the hand discovery counted employee profiles naming the seller's product).
- Exa's stream (`Accept: text/event-stream`) sends progress while the run works —
  `agent_run.search_trace` (plain-English "Searching for …"), `agent_run.source.added` (each page)
  — but the companies arrive only in `agent_run.completed`.

## 3. Founder decisions (2026-11-10)

**What the run finds**
1. The Head of ABM keeps writing the brief. It fills the trial's instruction template, including
   the seller-specific examples of a reason to act now.
2. Hard gates decide whether a company is listed. The seller's competitors (main business = the
   same kind of product) and existing customers are left out.
3. A company that fits but builds the tool in-house, or uses a competitor with no sign of
   switching, is a **caveat**: kept, with a remark saying why, and **not counted** toward the
   number asked for (ask 5 → 5 counted, the caveat one is a sixth). A contract ending in 3–6
   months or clear unhappiness is an **opportunity** and keeps a company top.
4. **Where to look first:** search recent events in the market (breaches, ransomware and outages,
   new security and technology leaders, data-centre and cloud migrations, regulatory findings and
   deadlines, new Zero Trust or resilience programmes) as well as the profile; fill the list with
   companies that have a reason to act now first.
5. Rank top companies by how strong and recent their reasons to act now are. A fitting company with
   no reason is still top and still counts; it comes after the ones with a reason. Never leave a
   company out for having no reason to act now.
6. Prefer a spread across the profile's markets rather than one country.
7. Every finding carries its source URL and the exact quote, or says "not found".

**How it runs**
8. **One** Exa Agent run per discovery (effort `auto` in the trial). No two-stage find-then-check
   split.
9. Exa's progress stream is shown in the chat while it runs; no accounts appear until it ends.

**What the person sees** (sketches in `mockups/`)
10. In the chat that asked: under the Head of ABM's "I've started looking…" message, a live list of
    the agent's "Searching for …" lines only (not the pages it opens), with a timer. When the run
    ends the list collapses to a one-line "Discovery finished · time · searches", and the Head of
    ABM posts its summary.
11. That chat's message box is blocked while discovery runs: **Stop** shows while the box is empty;
    once a draft is typed the button becomes a greyed-out Send; clearing the draft brings Stop
    back. The composer uses its existing disabled state, with no new visuals. (To check in the
    design: today the backend accepts and holds messages sent during a discovery.)
12. Other chats of the same project can send messages normally; only a second discovery is refused
    while one runs.
13. Accounts table: **no new columns.** Priority is expressed through the existing Overall fit and
    Fit score columns (the agent's ranking becomes the fit score, so sorting by fit puts the most
    urgent first and caveat companies after).
14. A caveat company shows a **light orange "Caveat" badge** in its Overall fit cell. Hovering the
    badge opens the reason in a floating bubble in the brand's light gray (gray-50 background,
    gray-400 border), drawn in its own top layer so no table edge can clip it — the existing
    `src/components/ui/hover-card.tsx` already renders in a portal. The badge stays light orange.

**Settled in the second round (2026-11-10)**
15. A top company's remark (its reason to act now) shows **only on the account's page**, not on
    the table. Only caveat companies get the hover bubble.
16. A run that ends with fewer top companies than asked **searches again**, the way discovery
    retries today (up to three more rounds, leaving out every company already seen).
17. **No quote re-check in code.** `check_quotes.py` stays a trial tool only.
18. **No separate check** for competitor use or quiet existing customers; the one run is enough.

## 4. Open questions

- How the agent's ranking maps onto Fit score and Overall fit (today fit is the share of gates
  passed; Fit score = fit × 100, Overall fit = High at 0.70 and above, Medium at 0.40 and above,
  else Low). Proposal under discussion: the agent gives each company its own 0–100 fit score.
- Production Exa account: whether it is zero-data-retention (then a run's result is retrievable
  for only 10 minutes and `previousRunId` is unavailable).
