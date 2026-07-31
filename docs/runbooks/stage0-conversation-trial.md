# Stage 0 conversation trial

This is the first quality test of the research subsystem. It answers a narrow question before Exa,
scraping, API, or full end-to-end testing: **can the Head-of-ABM agent learn the company, product,
project intent, and ICP through a useful conversation, route the information correctly, and retain
it across turns?**

The trial deliberately does not read any campaign directory. It also does not fetch the supplied
website, call Exa, or invoke a scraper. The company name and website entered during setup are
identity seeds only. The website is researched later, in the separate acquisition test.

## What the CLI exercises

- the active `head-of-abm` prompt and `stage0-interview` skill;
- the real DeepAgent tool-calling loop through OpenRouter;
- C5 Recipe 0 and the governed Stage 0 tool surface;
- exact user-turn artifact capture and quote-addressable interview routing;
- typed Client-KB claims with provenance;
- scoped advisory preferences and behavioral learnings;
- project-local intent and unmapped-evidence preservation;
- deterministic readiness evaluation;
- human-only product and ICP confirmation;
- durable conversation history and restart/resume;
- an inspectable report containing claims, memories, statements, ICP/readiness state, model calls,
  and governed tool results.

## Prerequisites

1. Docker Desktop must be running.
2. Set a real OpenRouter key in `.env`:

   ```dotenv
   CLUE_OPENROUTER_API_KEY=your-key
   ```

3. Install dependencies and prepare Postgres:

   ```bash
   make install
   make db-up
   make migrate
   ```

No Exa or Firecrawl key is required for this test.

## Start the trial

From the repository root:

```bash
uv run python scripts/00_stage0_trial.py
```

The CLI asks for four setup values:

1. company/brand name;
2. company website, used only to establish the client identity;
3. the product candidate the conversation is about;
4. a project name.

Then speak naturally. Do not fill a questionnaire. Give the agent the same context you would give
a senior ABM lead, let it ask the next material question, correct it when necessary, and inspect
whether it understands the distinction between:

- facts about the company/product;
- preferences about how work should be done;
- project-specific choices;
- ICP hypotheses;
- assumptions and missing evidence.

Useful commands:

```text
/status
/report
/confirm-product
/synthesize-icp
/confirm-icp 1
/paste
/file PATH
/quit
```

## Sending a multi-line brief as one turn

The prompt reads **one line per turn**, so pasting a multi-paragraph brief directly would split it
into several turns — the agent then re-asks what you already told it and the run burns model calls
on fragments. Use one of the two explicit block-input commands instead (they are also available in
`scripts/clue_trial.py`):

```text
You > /paste
Paste your text, then a line containing only '.':
<paste the whole brief, however many lines and blank lines it has>
.
```

```text
You > /file ~/briefs/product-brief.md
```

Both send the assembled text as a **single** conversation turn. Blank lines and indentation inside
the block are preserved; only the outer whitespace is trimmed. A pasted line that starts with `/`
is content, not a command. `/paste` also ends at Ctrl-D. `/file` accepts a quoted or `~`-prefixed
path and refuses a missing path, a directory, a non-UTF-8 file, an empty file, or anything larger
than 16 KB; either command refusing prints an error and hands the prompt back without touching
durable state. The 16 KB ceiling comes from the routing-honesty guard, not from the API: the agent
must echo your message byte-identically into `record_interview_answer`, so a turn has to fit the
profile's output-token budget (8192 for head-of-abm v6) together with the statements it routes.
Send a longer brief in two or three `/paste` turns.

`/confirm-product`, `/synthesize-icp`, and `/confirm-icp` are explicit human actions; the agent
cannot perform them. `/synthesize-icp` and `/confirm-icp` both require a confirmed product and
refuse with `run /confirm-product first` until you run `/confirm-product`.

ICP synthesis grounds on **both** evidence species: the versioned Client-KB claims and the
project-scoped `project_state` interview statements (what you said about who you want to target).
Corrections win: a statement another statement corrects is superseded and stops steering synthesis
entirely, though it stays in the append-only audit trail. At most the 40 most recent distinct
statements enter one synthesis, and a statement whose captured evidence artifact has been erased is
dropped and listed by id as an exclusion rather than blocking the run.
If neither exists yet, `/synthesize-icp` prints `Not ready: <missing evidence>` and offers **no**
numbered proposal — the ungrounded config floor is recorded under `not_ready_floor` for inspection
but can never be confirmed. Say more about the product and the targets, then try again.

After a grounded `/synthesize-icp`, continue the conversation once so the generated proposals enter
the next turn's frozen context and the agent can critique them before confirmation.

## Resume after quitting

The CLI prints the session slug. Resume it with:

```bash
uv run python scripts/00_stage0_trial.py --session <session-slug>
```

This is an important part of the test: quit after several turns, restart the process, and ask the
agent to summarize the company, product, current ICP hypothesis, exclusions, and open questions.
It should use durable context rather than asking for everything again.

## Inspect the output

After every turn, inspect:

```text
.context/stage0-trials/<session-slug>/report.md
.context/stage0-trials/<session-slug>/transcript.md
.context/stage0-trials/<session-slug>/report.json
.context/stage0-trials/<session-slug>/icp-proposals.json
```

`report.md` is the quick status page. `transcript.md` is the human-readable conversation.
`report.json` is the detailed inspection surface and should be used to verify that confident prose
actually became a supported claim, preference, project statement, or explicit unmapped item.
`icp-proposals.json` appears only after `/synthesize-icp`; it records the synthesis `status`
(`grounded` / `floor_only`), its `reason_codes`, and the `project_statement_ids` that grounded it.
Each proposal element cites both `justifying_claim_ids` and `justifying_statement_ids` — references
only, never a copy of what you said.

## Suggested evaluation

Judge the trial on:

- whether the questions are material rather than form-like;
- whether the agent correctly understands the company and product;
- whether the ICP is specific enough to exclude poor targets;
- whether corrections supersede prior understanding instead of being ignored;
- whether facts, preferences, and project intent land in the correct stores;
- whether unsupported assumptions remain visibly unsupported;
- whether the agent remembers the conversation after a process restart;
- whether the resulting ICP proposal is useful enough to justify proceeding to Exa testing.

This CLI is not the Exa test and not a complete production launch. Once the conversational quality
is acceptable, proceed in order: direct Exa output, website acquisition, API, then the complete
system test.
