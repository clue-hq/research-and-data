# CRM integration — trial 1 findings (2026-10-21)

The first end-to-end trial of Phase 1 (reads) on the local nashville stack, driven in the Claude
desktop in-app browser by Claude with the founder signed in. Nothing below has been fixed yet: the
founder asked to record first and discuss before acting.

## Setup
- Stack: `./scripts/dev_stack_nashville.sh up` on `clue_nashville_pm`, migrated in place to
  `3b800d603402`. Head of ABM `v76` (uncommitted Task 11 catalog), recipe 36, manual v22.
- Workspace: Conduit AI (`ws_3c96…`), a new Home project "Conduit AI sales analytics", chat
  `thr_5a44…`.
- CRM: the HubSpot developer test account (Composio dev project, managed auth config), seeded with
  20 companies, 66 contacts, 36 deals (14 won, 14 lost, 8 open; a 260,000 outlier).

## What happened, step by step
1. **Ask.** "Can you connect our CRM so you can read our deals and work out our real sales
   numbers?" The agent called `connect_crm` and the new card rendered (Choose CRM state), matching
   the Figma design: 520 px, 20 px padding, 8 px radius, 1 px border, title 18/24 bold, 64 px rows,
   32 px buttons, every icon loaded at its design size.
2. **Connect.** The founder clicked Connect. The card switched to Authorizing ("Connecting…",
   spinner line, Cancel). The founder finished HubSpot's consent in **Arc** (already signed in to
   HubSpot there). Composio marked the account ACTIVE, but our side stayed `open` (see F1).
3. **Callback, completed by hand.** Claude opened the same callback URL in the in-app browser
   (signed in to Clue). The callback page said "HubSpot is connected"; the connection row became
   `active`, the request `fulfilled`, and one `crm_connected` turn was queued on the chat.
4. **Card flipped to Connected by itself** (check tile, HubSpot row with the green badge, "HubSpot
   is connected. Clue carries on in this chat.", "Connected by aryan keshri · today").
5. **Automatic continuation.** The wake turn ran, but the open chat showed nothing until reload
   (F2). After reload: the agent said what Clue can read and that nothing changes, read the
   pipelines and deal properties into `reads/`, and proposed the four definitions from the stage
   names (demo = Appointment Scheduled, qualified demo = Presentation Scheduled, won/lost =
   Closed Won/Lost), asking before computing. ✅ skill §2–§4.
6. **Analysis.** After "Yes, that mapping is right": window 21 Jul–21 Oct, 28 closed deals ("a
   reasonable read"); batch reads of 18 companies and 61 contacts (contacts limited to job title
   and buying role — the agent chose this to avoid personal data); five sandbox runs; tables saved
   to `outputs/`. Numbers checked against the seed: 14 won / 14 lost, win rate 50 %, won avg 66,357
   / median 48,500, range 18,000–260,000, outlier named and set aside, median cycle 76.5 days. ✅
   It reported what it could not establish (stage time, demo channel, currency, costs) and did not
   call amounts dollars without a currency.
7. **Judgement.** It refused to write to the brand until told the portal is Conduit's book of
   record, because the wins (software, finance, healthcare…) do not match Conduit's hotel ICP. ✅
   Exactly the caution wanted.
8. **Write.** After confirmation (+ USD, cost per lead ~$120, cost per demo ~$900) it drafted
   `company/sales-motion.md` and the merged `proof/customers.md` (12 new companies, `CRM:` sources,
   one row per domain) — but **every `write_brand_document` call was refused** (F4). Asked to use
   `from_file`, it rebuilt both drafts (`outputs/` had been emptied, F3) and was refused again.
   Nothing was published; `proof/customers.md` is still v2.

## Findings

### Blocking
- **F4 — `write_brand_document` can never be called by the agent.** *Fixed 2026-10-21 (`1e88e9242`): the input is now `markdown`; a guard test fails the build for any tool input named like raw content (one listed exception, `write_project_document@1`), and a test runs the tool through the real plan builder and validator. Live re-check (publish from the trial chat) still owed.* The plan validator
  (`clue_execution/graph.py`, `_RAW_BODY_KEYS`) rejects any plan whose node bindings contain a key
  named `body` (also `content`, `text`, …): "raw_body_key: raw body content is forbidden". The tool's
  input has a field named `body`, and the key is present even when it is null, so **both** the
  inline path and the `from_file` path are refused before the tool runs (6 refusals in this trial).
  The DB tests called the tool directly, not through the agent's plan, so they never saw it.
  Likely fix: rename the field (e.g. `markdown`, as `manage_products` uses `page_markdown`), and add
  a test that runs the tool through plan validation. **Defect in Task 9.**

### Should fix
- **F1 — The OAuth callback only works in a browser signed in to Clue.** Composio returns the
  browser to `localhost:3060/integrations/crm/callback?…`, a protected page; Arc had no Clue session,
  so it bounced to sign-in and never called `/crm/complete`. The connection stayed pending although
  Composio had it ACTIVE. Options to discuss: let the callback page finish without a Clue session
  (the request id + Composio's own account check already prove the attempt), or have the backend
  confirm pending attempts itself (Composio webhook, or check the account when the card is next
  read), so the link can be opened anywhere.
- **F2 — A turn the server starts is not shown in an open chat until reload.** *Decided 2026-10-21 (R-10.1): live thread stream, open while the tab is visible; plan `docs/superpowers/plans/2026-10-21-chat-thread-stream.md`.* The chat re-reads a
  thread on a timer only while a discovery holds it; the `crm_connected` wake ran on the worker, but
  the page showed nothing until it was reloaded. **Uncommitted change already made** (before the
  founder asked to pause): the card asks the chat to re-read the thread once when it sees the CRM
  connect (`rereadThread()` on the chat controller). To discuss: keep that, or a general mechanism
  for every server-started turn (a thread-level event stream or a short re-read while any queued
  turn exists).
- **F3 — `outputs/` is emptied at the end of every turn (by design).** *Direction decided 2026-10-21 (R-10.4–R-10.8): a machine-independent agent workspace (versioned snapshot of agent-made files in R2, local disk only a cache), with tiered retention and receipts; spec to be written after F2.* `snapshot_outputs(empty_after=
  True)` saves the folder as artifacts, then clears it. The next turn could not find last turn's
  `won-deals.csv` or its drafts and recomputed everything (turns 4 and 5 ~11 minutes). Founder's
  view: this should not happen in general. To discuss before any change (it touches the agent
  workspace contract for every turn, not only CRM).

### Smaller
- **F5 — Composio's action search is narrow.** The agent made 14 `find_crm_actions` calls; it did
  not find `HUBSPOT_GET_DEALS` (on our allowlist and named in the skill) and fell back to computing
  cycle time from create/close dates. Options: let `run_crm_action` take any allowlisted slug the
  skill names without a search (it already can — the agent assumed it must search first), and/or
  make `find_crm_actions` also match the allowlist itself.
- **F6 — Slow turns.** Analysis 7.4 min, write attempt 8.3 min, partly from F3/F4. Most model calls
  were 15–25 s. Worth a look after F3/F4.
- **F7 — Underscores in chat messages render as italics.** `run_python`, `write_brand_document`,
  `from_file` appeared as "runpython", "writebranddocument" in both the user's and the agent's
  messages. General chat markdown, not CRM-specific.
- **F8 — Callback page background** covers only the top part of the tab; the rest is white.
- **F9 — Seed data limits.** Stage history is artificial (deals created straight into their final
  stage), so "where deals stall" and "where demos come from" were honestly "not available". The
  test CRM's companies (software, finance…) do not match Conduit's ICP — the agent rightly flagged
  it. A seed that mirrors the test brand's ICP and walks deals through stages would exercise more.

### Not exercised in this trial
- Salesforce (budget guard, SOQL paging) — covered by offline tests and the Task 8 live read check
  only.
- "Do this later" (by-hand path), Cancel, a failed sign-in, a non-admin member, reconnect/switch.
- The onboarding refresh keeping CRM rows (no CRM rows were published).

## What worked
- The connect card in all three states, driven by the real connection; the callback broadcast and
  the fallback check.
- `connect_crm`, `find_crm_actions`, `run_crm_action` (every read landed in `reads/`, the model saw
  only summaries), `run_python` over those files, `record_interview_answer`.
- The skill's procedure end to end up to the write: definitions confirmed first, window and
  sample-size wording, batching, privacy-minded field choices, honest gaps, outlier handling,
  book-of-record caution, correct numbers.
- No platform API errors during the trial.
