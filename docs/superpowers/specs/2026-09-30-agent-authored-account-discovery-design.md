# Agent-authored account discovery — design

**Date:** 2026-09-30 · **Branch:** `discovery/target-discovery-trial` · **Status:** draft for founder review

## 1. Why

Conduit AI's first live discovery (hotel-operators ICP, 3 accounts) returned three hotel-software
vendors — the seller's competitors, not its buyers. The isolated trial
(`docs/superpowers/drafts/2026-09-30-target-discovery-trial/README.md`, $8.11) found:

- **The discovery brief is compiled mechanically from the ICP document** (`compile_brief`): the
  query is the body's first paragraph (for this ICP, the buyer's *need* sentence), the Websets
  criteria are gate `rule` texts verbatim, and the document's exclusions are never used.
- **The ICP-synthesis skill writes gates as inline YAML**, so a comma inside a value splits it and
  the parser keeps only the first part ("There is a named guest-experience").
- **A failed hard gate does not exclude**: `fit = passes / gates` shows a failed "operates hotels"
  as "Medium".
- **The failure is intermittent**: production's exact input returned 3/3 vendors in one of three
  count-3 runs and 0 at count 10.
- **A brief written by an agent from the same documents fixed it**: arm G returned 19/19 real hotel
  operators, unprompted adding a company-type query and a "not a hotel-tech vendor" criterion.
- **Negatively worded gates ("is not a vendor") make the Answer verifier return false `fail`s** —
  three real targets wrongly excluded in arm G.
- **Exa `/search` with the company category** was 29/29 on the kind of company across both ICPs,
  for ~$0.01 a long list, but returns the same companies for the same query.

## 2. Founder rulings this design implements (2026-09-30)

1. **The Head of ABM writes the discovery brief** — query, criteria, gates, source — on every
   call, from the pinned ICP, persona and plan documents and its conversation with the user.
   Documents are the agent's memory and context; **nothing parses them into a search**. This
   supersedes the R4 principle "the ICP document is the program" and the 2026-09-11 ruling that
   every ICP names its own criteria gates.
2. **The brief is internal.** No confirmation card and nothing in chat: it would expose how Clue
   finds accounts, and it is built from the user's own conversation anyway.
3. **Shape C:** bookkeeping stays in the platform, judgement goes to the agent. Inside one run the
   platform only tops up with the same brief; loosening, rewriting or switching source is the
   agent's decision after the run.
4. **While a discovery runs in a thread, that thread is busy**: the user can type, but the message
   is held until the discovery is over.
5. **One discovery at a time per project.** A second thread's agent gets a refusal naming the
   conversation where one is running.
6. **The user can stop a running discovery.**
7. **The Head of ABM is woken at the end of every run** (filled or short) with the run's summary.
8. **Gates are phrased positively, with a role**: `must`, `must_not`, `prefer`.
9. **Excluded companies stay off the accounts table**, recorded only on the run. (Narrows the
   2026-09-11 ruling that every verified company joins the project.)
10. **At most three top-ups** inside one run.
11. **The agent relaunches at most once on its own** after a short run; after that it asks the human.
12. **Shipped skills, prompts and examples are industry-agnostic** — placeholders such as
    `<kind of buyer>` and `<the seller's kind of product>`, never a real industry.
13. **Needs are allowed in the brief.** What the brief must avoid is wording the seller's
    competitors would also satisfy.

## 3. The tool: `launch_arv2_discovery@2`

```text
project_id      the project
target_count    how many companies to find (1–500)
source          "websets" | "search"
query           1–2 sentences: what kind of company to find
criteria        1–5 short, checkable statements the search filters on
gates           2–8 checks run on every company found, each:
                  key    short snake_case name
                  rule   one positive statement of fact
                  test   how to check it on public pages
                  role   "must" | "must_not" | "prefer"
```

- **Preconditions stay**: a confirmed product set and a confirmed ICP pinned to the project. The
  pinned ICP version is recorded on the run as the context the agent was reading; the tool reads
  no text out of it. `compile_brief` is no longer on the discovery path.
- **Validation** is structural only (counts, non-empty fields, known roles, key format). Wording
  is the agent's.
- **The whole brief is stored on the run** (`brief_json`) so a run is auditable and replayable.
- **`relaxed_enabled` is removed.**
- **New refusals:** `discovery_in_progress` (names the running run and its thread),
  `brief_invalid` (names the field). The existing project / ICP / product-set refusals stay.
- `@1` stays registered for replay and leaves the Head of ABM's profile.

## 4. What one run does

1. **Round 1** asks the chosen source for `target_count` companies with the agent's query and
   criteria, excluding every company this project's earlier discoveries found.
2. **Every company returned** is verified per company, as today: a website check to lock the
   domain, then one Exa Answer per gate, always asking the `rule` as written. Code applies the
   role:
   - a failed `must` or a passed `must_not` → **excluded**: recorded on the run with the gate,
     quote and source; never added to the project's accounts; not counted toward `target_count`;
   - otherwise → joins the project's accounts with its verdicts and a fit over its `must` and
     `prefer` gates (pass = 1, unclear = ½).
   An unclear verdict never excludes.
3. **Top-ups:** while the run has shown fewer than `target_count`, the platform asks again for the
   shortfall with the **same brief**, excluding every company seen so far (excluded ones included).
4. **The run ends** on the first of: *filled*; *dry* (a round returned nothing new); *round cap*
   (`CLUE_ARV2_DISCOVERY_MAX_TOPUPS`, default 3, so at most 4 searches); *wall clock* (the existing
   per-run limit); *stopped*.

**Per source:**
- **websets** — each round is its own webset excluding the earlier ones (today's mechanism).
- **search** — each round is one Exa `/search` with `category: "company"` asking for 2× the
  shortfall, with `exclude_domains` set to every domain already seen.

**Stop** (`POST /frontend/v1/projects/{project_id}/discovery-runs/{run_id}/stop`): cancels the
current webset (Exa stops finding and billing), reads it once more to put what was already billed
on the ledger, keeps every company already verified, marks the run `stopped`, and releases both
locks via the normal end path.

**The summary**, built by code and stored on the run (`summary_json`): asked, shown, excluded,
unclear; excluded counts per gate with one example company each; the criteria success rates of the
last Websets search; rounds run; why the run ended; spend.

**The wake:** when a run ends, the platform queues a derived Head-of-ABM turn in the launching
thread whose message is the summary, using the derived-turn mechanism design legs already use (no
user bubble; the durable row stays). The thread stays busy and the project lock held until that
turn finishes; then any queued user message is delivered.

**Removed:** the automatic relaxed search, `relaxed_criteria()`, `compile_brief` on the discovery
path, and the settings `CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS` and
`CLUE_ARV2_DISCOVERY_RELAXED_AUTO`.

## 5. Locks

- **Project lock, structural:** a partial unique index on `arv2_discovery_run (workspace_id,
  project_id)` over the active statuses, so two simultaneous launches cannot both succeed. The
  launch maps the violation to `discovery_in_progress` with the running run's id and
  `launched_thread_id`.
- **Thread busy:** `threads_running()` also counts a thread whose discovery run is active, so the
  sidebar and composer show it, and a turn submitted to that thread is held (not refused) until
  the run's wake turn finishes — the same queue that holds a message during a running turn.

## 6. The Head of ABM's instructions (founder-reviewed text)

### 6.1 `stage0-interview` v43, section 7b

```markdown
## 7b. Discover accounts for this project

When the human asks you to find accounts, and this project has a confirmed ICP and a
confirmed product set, you run the discovery yourself with `launch_arv2_discovery`, and you
write the search. The ICP, persona and plan documents are your notes about who the seller sells
to. Read them, and what the human told you in this project, before you write anything. Write
the search in your own words; do not copy sentences out of the documents.

### What you write

- `target_count`: the number of accounts the human asked for.
- `query`: one or two sentences saying what kind of company to find. Say what the company is
  and what it does, and add what it needs when that helps find the right companies.
- `criteria`: one to five short statements that every company found must satisfy. Each must be
  something the company's public pages can answer. Put the identity fact first. Every extra
  criterion shrinks the list, so leave out anything that is only nice to have.
- `gates`: two to eight checks run on every company found. Write each `rule` as a positive
  statement of fact — "The company sells <product> to <kind of buyer>", never "The company is
  not a <product> vendor". Then choose its `role`:
  - `must`: the company is excluded when this is false. Use it for the identity fact.
  - `must_not`: the company is excluded when this is true. Use it for the seller's competitors
    and anything the ICP rules out.
  - `prefer`: scored, never excludes.
  An unclear answer never excludes a company.
- `source`: `websets` or `search`.
  - `websets` finds a wider and different set of companies each time. It takes minutes and costs
    more. Use it unless you have a reason not to.
  - `search` is fast and cheap and finds companies by kind very well, but it returns the same
    companies for the same query. Use it when websets came back short, or for a quick first list.

Before you call, check the query and every criterion against the seller's competitors: the
companies that sell the same kind of product as the seller to these same buyers. Ask of each
sentence: "Would a company that sells what the seller sells also match this?" A sentence about a
need often does: "companies that need <the seller's kind of product>" matches both the buyers
that need it and the competitors that sell it. When the answer is yes:
- rewrite the sentence so it is about the buyer doing or running the thing ("<kind of buyer>
  that run their own <activity>"), not about the product ("<the product> for <kind of buyer>"),
  and
- add a `must_not` gate for the competitors ("The company sells <the seller's kind of product>
  to <kind of buyer>").

### What happens next

The platform searches, checks every company against your gates, and adds the companies that
pass to this project's accounts. If some are excluded or already known, it searches again with
the same brief — never a looser one — up to three more times. While it runs, this conversation
is busy: the human's next message waits until the discovery is over.

A successful call means the discovery is running. Say that in one or two sentences, and say the
accounts will appear on this project's accounts table. Never describe your query, criteria or
gates to the human.

### When it ends

You then get a turn that starts with the discovery's summary. Read it, then:

- **It found what was asked for:** tell the human how many accounts were added and where to see
  them. If companies were excluded, say how many and why in one sentence, in the human's terms
  (for example "three sell the same kind of product as you").
- **It found fewer:** say how many it found. Then decide from the summary what to do:
  - One rule excluded most companies, and you think it is stricter than the human needs:
    launch again with that one rule loosened, and tell the human which requirement you relaxed.
  - The query returned the wrong kind of company: rewrite the query and launch again.
  - `websets` came back short: try `search` (or the other way round).
  - The market looks small: tell the human, and ask whether to widen the ICP.
  Launch again at most once on your own. After that, ask the human first.

### Other conversations

Only one discovery runs in a project at a time. If the tool answers `discovery_in_progress`,
tell the human a discovery is already running in another conversation of this project and that
you can start one when it finishes. Do not retry.

When the human asks for more accounts, call `read_discovery_run` first and say what the last run
found. Then launch a new run with the number they want now. Each run skips every company this
project has already found.
```

### 6.2 Tool note (`manual/tool_notes.yaml`)

```yaml
launch_arv2_discovery:
  before: >-
    If you have not read section 7b of the stage0-interview skill ("Discover accounts for this
    project") in this conversation, read it before you call this tool. It says how to write the
    query, the criteria and the gates.
  afterwards: >-
    A discovery run is queued with the brief you wrote. It checks every company against your
    gates, adds the ones that pass to this project's accounts, and searches again with the same
    brief for any shortfall, up to three more times. This conversation is busy until it ends;
    you then get a turn that starts with its summary.
  refusals:
    discovery_in_progress: A discovery is already running in another conversation of this project. Tell the human, and do not retry.
    brief_invalid: Fix the field the message names and call again.
```

The pre-call pointer's field name follows the manual's existing format (checked in the plan); the
wording is as above.

### 6.3 The wake turn's message (built by code)

```text
Discovery finished (run <id>). Asked for <n>, added <n>, excluded <n>, unclear <n>.
Ended: <filled | dry | round cap (<k> searches) | wall clock | stopped>.
Excluded by: <gate_key> (<role>) <n> — e.g. <company>; …
Criteria pass rates, last search: "<criterion>" <p>%; …
Spend: $<x>.
```

## 7. Frontend

- **Reuse the thread's running state** (sidebar badge, composer state) for an active discovery. The
  one new string — the composer line *"Finding accounts — your message will be sent when discovery
  finishes."* — needs a founder / co-founder design ruling before it ships (no designed slot yet).
- **Stop** reuses the composer's existing stop control, which calls the new stop route while a
  discovery is active. (The plan confirms that control and its states first.)
- **Accounts table:** unchanged; excluded companies never reach it.
- Integration stays at the frontend's repository seam; no transport code in components.

## 8. Versions, settings and data

| Piece | Change |
|---|---|
| `launch_arv2_discovery@2` | new tool; `@1` kept for replay, dropped from the profile |
| `stage0-interview` | v42 → v43 (section 7b) |
| `head-of-abm` profile | v69 → v70: grants `@2`, pins skill v43, re-pinned tool digests (and a Recipe #0 bump if the profile requires one) |
| `manual/tool_notes.yaml` | the note in 6.2 |
| `icp-synthesis` skill | next version: the block-YAML format in §9 |
| settings | add `CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3` (`.env` and `.env.example`); remove `CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS` and `CLUE_ARV2_DISCOVERY_RELAXED_AUTO` |

**One reversible Alembic migration** (hash id, chained to the single head):
- `arv2_discovery_run`: `brief_json`, `source`, `launched_thread_id`, `end_reason`,
  `summary_json`; the project-lock partial unique index.
- `arv2_discovery_candidate`: an `excluded` disposition and the excluding gate key.
- `arv2_discovery_search`: `source`.

All databases hold development data only, so there is no backfill; the driver refuses a run
without a brief by name.

## 9. The ICP-synthesis comma fix

The agent reads ICP documents, so they must stop losing text. The `icp-synthesis` skill's format
block changes from inline `{…}` to block YAML with quoted values:

```yaml
hard_gates:
  - key: "<stable_key>"
    rule: "<one sentence>"
    test: "<how a researcher checks it>"
qualifier_fields:
  - field_key: "account.<some_key>"
    description: "<the research instruction>"
    display: "rail"
```

ICP authoring **refuses** front matter whose gate or qualifier row carries a key with no value
that is not a known field — the comma-split signature — instead of storing it. Existing broken ICPs
are development data and are regenerated.

## 10. Testing and proof

**Offline:** brief validation; role application (unclear never excludes); the round loop against
fake Websets and `/search` clients (filled, dry, round cap, wall clock, stopped); the summary; the
ICP-authoring refusal.

**Database:** the project lock (including two simultaneous launches); Stop releasing both locks;
the wake turn queued and the held user message delivered after it; excluded companies never joining
the project's accounts.

**Frontend:** the busy composer and Stop at the repository seam.

**Live, on the lane stack:** through the app, the Head of ABM discovers for the hotel ICP (10, then
3 × 3) and the Clue ICP, graded with the trial's method; a deliberately short run where the agent
decides the next step; Stop mid-run; a second thread refused by the project lock.

`scripts/trial_target_discovery.py` stays as the offline evaluation tool for tuning the skill's
wording on the Exa Websets playground.

## 11. Out of scope

- AI Ark industry-filtered company search as a third source (trial arm F).
- The Head of ABM verifying candidates itself; Exa Answer remains the per-company verifier.
- Tuning the section 7b wording beyond this draft — to be done with the founder on the Exa
  playground after the agent is built.
