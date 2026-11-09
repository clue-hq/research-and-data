# 2026-11-10 — Exa Agent account-discovery trial (standalone)

Branch `trial/exa-agent-discovery` (cut in the trenton worktree from `fix/design-reference-ads`
HEAD f674f8112). Founder ask: try Exa Agent for account discovery as a standalone trial before any
platform design or code change.

## What exists
- `trials/exa-agent-discovery/`: `system_prompt.md` (instruction block, founder-reviewed draft),
  `output_schema.json`, `build_context.py` (ICP + catalog + customers table -> context JSON),
  `run_trial.py` (one `POST /agent/runs`, poll, save), `check_quotes.py` (reopens every cited URL
  via Exa /contents and checks the quote is on the page). Commit b82495820.
- Customer data (Illumio context, run outputs) lives only in the session scratchpad.

## Founder rulings in this conversation (2026-11-10)
- Hard gates decide whether a company is listed; competitors (main business = same product) are
  left out.
- A company that passes but builds in-house, or uses a competitor with no sign of switching, is
  kept as **caveat** with a remark and does NOT count toward the number asked for (ask 5, the
  caveat one is a sixth). Contract ending in 3–6 months or user dissatisfaction = **opportunity**,
  keeps a company top.
- Wanted later (not built): a remark column on the target-accounts table, and platform discovery
  counting only top companies. Product change after the trial.

## Facts established reading the current flow (research-trial branch, Head of ABM v87)
- Head of ABM writes the brief itself (`launch_arv2_discovery@3`: query, 1–5 criteria, 2–8 gates
  with must/must_not/prefer, exclude, source websets|search); taught by stage0-interview v60 §7b.
- `search` mode sends only the query to Exa; criteria are used only by websets.
- Verification = one Exa /answer for the website + one per gate per company, 4 in flight; only
  the date-window guard remains in code. `manual-discovery@v33` still describes the removed
  quote-on-page and right-company guards (doc drift, unfixed).

## Exa Agent API notes
- `input.exclusion` takes `[{"<output field>": value}]`; `[{"domain": "..."}]` was accepted.
- Fixed efforts: minimal $0.012, low $0.025, medium $0.10, high $0.50, xhigh $1.00; auto metered
  (default cap $5), ultra $20. Streaming emits run status events only, not items.
- The platform's `ExaClient.agent_run` has no `input`/`budget` support; the trial calls httpx.

## Runs
- run1: effort high, Illumio global-banks-insurers ICP, target 5 top. (Result below when done.)
- run1 result: completed in 191 s, $0.50 (agentCompute 0.2 + 60 searches 0.3), stopReason
  `iteration_limit_reached`. 8 companies: 5 top (PNC, Travelers, U.S. Bank, DTCC, Standard
  Chartered), 3 caveat (Lloyds: VMware Cloud Foundation deal; NatWest: named NSX product owner;
  MetLife: employee LinkedIn says Cisco Secure Workload). None is on Illumio's customer list.
  In-house, contract timing and dissatisfaction: "not found" for all 8. Quote check: 26/35 on
  page; 5 not found (mostly homepages), 4 pages unfetchable. Several gates marked unclear although
  the quote answers them (served_market with "Headquartered in London").
- run2: effort auto (cap $5): completed in 234 s, $1.35 (agentCompute 1.11, 49 searches 0.25),
  stopReason `schema_satisfied`. 7 companies, all US: 5 top (U.S. Bank, PNC, KeyBank, Allstate,
  State Farm), 2 caveat (MetLife: Cisco Secure Workload again; Liberty Mutual: Cisco ISE/TrustSec
  from an old Jamf blog). Gates 27/28 pass, mostly from SEC filings/company pages; quotes 30/30 on
  page. Some hybrid_estate passes rest on loose quotes (PNC, Allstate). In-house, contract timing,
  dissatisfaction: "not found" for all 7 again. Overlap with run1: U.S. Bank, PNC, MetLife.
- run3 (prompt d8cbec479: look first for reasons to act now, rank by them, never drop a fitting
  company, spread markets): auto, 264 s, $0.97 (28 searches), schema_satisfied. 5 top, 0 caveat:
  Crédit Mutuel Arkéa (FR, reported €100M cyber heist 2026-11), TruStage (US, July 2026
  cyberattack, interim CIO, rebuilding in cloud), Barclays (UK, data-warehouse cloud migration),
  Deutsche Bank (DE, core banking migration running old+new in parallel), Aflac (US, Aflac Japan
  breach 2026-06; agent noted US not affected). Quotes 28/28 on page. Competitor, in-house,
  contract, dissatisfaction: none found for any. List shape now matches the hand discovery's
  (breach victims, migrations, Europe) though no company overlaps it.

## Design decisions (2026-11-10, brainstorming with the founder)
Recorded in `docs/superpowers/specs/exa-agent-discovery/README.md` (§3 decisions, §4 open
questions) with sketches in `mockups/`. In short: Head of ABM keeps writing the brief; one Exa Agent
run with its progress stream shown in the chat ("Searching for …" lines only); that chat's composer
blocked (Stop when empty, greyed Send with a draft); other chats free; no new table columns —
ranking via Overall fit / Fit score, caveat = light orange badge with a light gray hover bubble in
a portal. Full design document still to write.
