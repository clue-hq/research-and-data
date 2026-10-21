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
- **F4 — `write_brand_document` can never be called by the agent.** *Fixed 2026-10-21 (`1e88e9242`): the input is now `markdown`; a guard test fails the build for any tool input named like raw content (one listed exception, `write_project_document@1`), and a test runs the tool through the real plan builder and validator. Live re-check passed 2026-10-21: asked in the trial chat to rebuild and publish, the agent re-read its CRM reads, ran `run_python` 8 times, recorded the confirmed facts and called `write_brand_document` twice with no refusal — `company/sales-motion.md` v1 and `proof/customers.md` v3 (v2 superseded; 44 rows, 12 added) are `ready` and render in Brand context; numbers match trial 1 (14/14, 50 %, median 48,500 USD, outlier 260,000 set aside, cycle 76.5 days). 7 min, 18 model calls, $1.09. The drafts and tables stayed in `outputs/` after the turn, owner-writable (AW-6 stopgap working).* The plan validator
  (`clue_execution/graph.py`, `_RAW_BODY_KEYS`) rejects any plan whose node bindings contain a key
  named `body` (also `content`, `text`, …): "raw_body_key: raw body content is forbidden". The tool's
  input has a field named `body`, and the key is present even when it is null, so **both** the
  inline path and the `from_file` path are refused before the tool runs (6 refusals in this trial).
  The DB tests called the tool directly, not through the agent's plan, so they never saw it.
  Likely fix: rename the field (e.g. `markdown`, as `manage_products` uses `page_markdown`), and add
  a test that runs the tool through plan validation. **Defect in Task 9.**

### Should fix
- **F1 — The OAuth callback only works in a browser signed in to Clue.** *Dropped 2026-10-21 (R-10.9): works as intended.* Composio returns the
  browser to `localhost:3060/integrations/crm/callback?…`, a protected page; Arc had no Clue session,
  so it bounced to sign-in and never called `/crm/complete`. The connection stayed pending although
  Composio had it ACTIVE. Options to discuss: let the callback page finish without a Clue session
  (the request id + Composio's own account check already prove the attempt), or have the backend
  confirm pending attempts itself (Composio webhook, or check the account when the card is next
  read), so the link can be opened anywhere.
- **F2 — A turn the server starts is not shown in an open chat until reload.** *Fixed 2026-10-21 (R-10.1; commits `b3c4882b7`, `a17124c52`, `f3dda2920`, review fixes `7a14ca5ad`, `99a7530a1`): a thread-level SSE stream sends every turn's lifecycle frames; an open, visible chat re-reads the thread once for a turn it has not seen and attaches it. Live check on the trial chat in two tabs: a message sent in tab 1 appeared in tab 2 within 3 s (queued → thinking → answer) with no reload; hiding tab 2 closed its stream, a turn ran meanwhile, and showing it reopened from its cursor and caught up; a tab hidden before any turn frame reopened from the hello's start point (`Last-Event-ID: 10073`). A server-started wake turn was proven by `test_a_server_queued_wake_turn_is_announced`, not live (it would have made the agent publish the brand documents unattended) — to run with the F4 re-check. The discovery 5 s re-read is replaced by the stream, with a 30 s thread-list safety re-read only while a discovery holds the thread (a run released with nobody to wake writes no turn frame).* The chat re-reads a
  thread on a timer only while a discovery holds it; the `crm_connected` wake ran on the worker, but
  the page showed nothing until it was reloaded. **Uncommitted change already made** (before the
  founder asked to pause): the card asks the chat to re-read the thread once when it sees the CRM
  connect (`rereadThread()` on the chat controller). To discuss: keep that, or a general mechanism
  for every server-started turn (a thread-level event stream or a short re-read while any queued
  turn exists).
- **F3 — `outputs/` is emptied at the end of every turn (by design).** *Direction decided 2026-10-21 (now AW-1–AW-8 in `docs/superpowers/specs/agent-workspace/rulings.md`): a machine-independent agent workspace (versioned snapshot of agent-made files in R2, local disk only a cache), with tiered retention and receipts; built in its own worktree. Interim since `f799a9830`: `outputs/` is kept for the chat's later turns instead of emptied (AW-6).* `snapshot_outputs(empty_after=
  True)` saves the folder as artifacts, then clears it. The next turn could not find last turn's
  `won-deals.csv` or its drafts and recomputed everything (turns 4 and 5 ~11 minutes). Founder's
  view: this should not happen in general. To discuss before any change (it touches the agent
  workspace contract for every turn, not only CRM).

### Smaller
- **F5 — Composio's action search is narrow.** *Deferred 2026-10-21 (R-10.11).* The agent made 14 `find_crm_actions` calls; it did
  not find `HUBSPOT_GET_DEALS` (on our allowlist and named in the skill) and fell back to computing
  cycle time from create/close dates. Options: let `run_crm_action` take any allowlisted slug the
  skill names without a search (it already can — the agent assumed it must search first), and/or
  make `find_crm_actions` also match the allowlist itself.
- **F6 — Slow turns.** *Dropped 2026-10-21 (R-10.10).* Analysis 7.4 min, write attempt 8.3 min, partly from F3/F4. Most model calls
  were 15–25 s. Worth a look after F3/F4.
- **F7 — Underscores in chat messages render as italics.** *Dropped 2026-10-21 (R-10.10).* `run_python`, `write_brand_document`,
  `from_file` appeared as "runpython", "writebranddocument" in both the user's and the agent's
  messages. General chat markdown, not CRM-specific.
- **F8 — Callback page background** covers only the top part of the tab; the rest is white.
- **F9 — Seed data limits.** Stage history is artificial (deals created straight into their final
  stage), so "where deals stall" and "where demos come from" were honestly "not available". The
  test CRM's companies (software, finance…) do not match Conduit's ICP — the agent rightly flagged
  it. A seed that mirrors the test brand's ICP and walks deals through stages would exercise more.

- **F10 — A turn can reason for over 11 minutes with nothing to stop it** (found during the F2
  live check, 2026-10-21). A test message saying "do not call any tools" clashed with the required
  `finalize_turn` step; Grok 4.6 reasoned about the conflict, then kept generating unrelated
  reasoning ("count the units in groups of twenty…") for 11+ minutes until it was stopped by hand.
  The recorded spend for the two test turns is $0.19 (the cancelled call is likely not counted).
  To discuss: whether a single model call needs a time or token ceiling (the standing ruling is no
  pre-emptive caps), and whether a message that forbids tools should be told that the turn's own
  finish step is not a tool in that sense.

- **F11 — The CRM skill asks for a file the workspace deletes** (found in the F4 re-check). *Fixed 2026-10-21 (R-10.12, option 2): the skill no longer asks for the script, and the sales motion explains its own computation and cites the CRM and date, never a workspace file.* The
  skill says to save the analysis script as `outputs/sales-analysis.py`, but a sandbox run may only
  leave `.json .md .txt .yaml .csv .xlsx .docx .pptx .pdf .png`, so the `.py` file is removed after
  the run; the agent said so honestly ("The workspace would not keep a .py file"). The CSV check
  tables were kept. Options to discuss: let the sandbox keep `.py` under `outputs/`, or have the
  skill save the script as `.txt` / inside the document's method section. Skill wording needs
  founder review either way.

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
