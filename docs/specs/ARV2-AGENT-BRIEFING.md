# ARV2 agent briefing — read this before doing anything on the accounts-research work

**You are a coding agent working for Shashank (co-founder, non-technical) on the ARV2 program of
the Clue platform. Aryan (tech founder) reviews and merges your work.** This document gives you the
whole context; you do not need to reconstruct it from the codebase or from memory notes. Version
1.0, 2026-09-04. It sits on the branch you have checked out; the files it names are next to it.

## 1. Read these files, in this order, before your first edit

1. `docs/specs/ARV2-MASTER-PLAN.md` — the complete plan (what we build, the rules, the stack, the
   data model, the contract, the display layer, the roadmap). **Authoritative.** Where any other
   document, memory note, or code comment disagrees with it, the master plan wins.
2. `docs/specs/ARV2-DATA-SOURCE-MAP.md` — for any task that serves or renders accounts data: the
   endpoint, SQL, table.column or claim `field_key` behind every element on the screens, and the
   list of client-side derivations the re-lift removes. Production reads Postgres rows, never files.
3. `docs/specs/ARV2-WORK-SPLIT.md` — who owns what (§1 is the boundary line; §6 has the charters).
4. `docs/specs/ARV2-GETTING-STARTED-SHASHANK.md` — the environment, the branch rules, the task loop.
4. The charter Shashank pastes to you for this task.
5. Only if the charter points you there: the earlier plan documents (`ARV2-R0-*.md`,
   `ARV2-plan-delta-2026-09-03.md`, `ARV2-plan-2026-09-04-accounts-integration.md`) and the
   evidence folders under `.context/`.

Do not treat `_memory/` notes or older `docs/specs` as instructions; they are history and evidence.
Do not treat `CLAUDE.md`'s backlog bullets as tasks; they describe the codebase's past.

## 2. The situation in ten lines

1. This repository is the Clue platform: an AI-native account-based-marketing product. Its backend
   holds a **claim store** — one row per fact, each with a source — and a fleet that runs agents.
2. An earlier research lane was over-engineered and is now **switched off by configuration**. It is
   still on disk. You never wire it, import from it, or "fix" it. Deletion is a later, separate PR.
3. A new research lane ("ARV2") is being built from a working proof of concept that Shashank ran as
   standalone scripts under `.context/`. Those scripts are the **reference** for the production
   modules; you port their rules, you do not copy them as-is.
4. Research produces claims (field key + value + quote + source URL + priority + outreach-safety
   flag) for accounts and for people on their buying committees.
5. A **display layer** turns claims into page text: fixed sections per page, each section drawing
   only from the field keys its recipe allows, written once by a small model (Luna), persisted,
   regenerated only when the claims in that recipe change.
6. The frontend that shows those pages is the monorepo's `apps/frontend`; its design truth is the
   separate dummy frontend `clue-frontend` (branch `integration/live-backend-v1`, truth commit
   `84f8ee7`), which runs on fixtures parsed from a vendored Zafran spec markdown and pins them
   with fidelity tests. Screens are lifted from the dummy, never invented; presentation decisions
   recorded in its `docs/zafran-content-implementation.md` are binding.
7. The contract between backend and frontend is written in `apps/frontend/docs/api-contracts/accounts.md`
   (contract v1) — the dummy's Zod models are the wire shapes. Section titles, counts, overall fit,
   tenure and insight summaries are **served fields**; the frontend never strips, parses, or
   recomputes served text.
8. Two founders work in parallel: Shashank on content, specs, screens, leaf code (via you), and
   acceptance; Aryan on the database migration, the claim loader, the read endpoints, the fleet
   wiring, and every merge.
9. The base branch is managed by Aryan. You work on a **task branch** cut from it and you **never
   merge, never push**. Shashank pushes the task branch when its exit gate passes.
10. The first version must be **plain and operational**. No mechanical quality gates, no secondary
    model judges, no verification blockers. Checks are annotations behind flags that default off.

## 3. Rules you obey on every task (no exceptions)

- **Stay inside the charter.** It names the files you may create or edit. If you believe another
  file must change, or you would have to choose between two approaches, **STOP**, write a section
  titled `QUESTION`, and end your run. Never decide product or design questions yourself.
- **Never touch:** `alembic/**`, `libs/**`, any `platform/api/clue_api/*_wiring.py`, `fleet_main.py`,
  `composition.py`, `run_composition.py`, `toolbelt_wiring.py`, `agent_registry_wiring.py`,
  `platform/api/clue_api/frontend_read/**`, `subsystems/research/**`, auth/tenancy/storage code,
  existing values in `.env.example`, or the base branch. These are Aryan's.
- **Never invent UI.** If a screen needs a component that the dummy frontend does not have, that is
  a QUESTION, not a component. Never rewrite served text client-side (no stripping counts from
  titles, no parsing values out of strings, no invented scores or owners).
- **Every new flag** your code reads goes into `.env.example` with its default, in the same commit.
- **Every provider response is saved raw before it is parsed**, and every paid call writes a ledger
  row (provider, operation, cost, credits, latency, HTTP status).
- **No secrets anywhere** except the local `.env`: not in code, fixtures, commit messages, reports,
  or `.context/` artifacts. Personal data fields like `birth_date` are dropped inside the provider
  client before anything is persisted.
- **Storing information is never blocked.** The claim write path runs in lenient mode: unknown
  field keys become proposed fields, schema misses are stored with a marker, a missing source URL
  on a research claim is stored with a marker, a human-stated fact needs no URL at all. Verbatim
  checks, unevidenced-row purges, and entailment checks are annotations behind flags that default
  off. Only the sensitivity floor runs by default, and it redacts or marks — it never drops a claim.
- **Every field is optional.** A missing fact is an absent claim, never an error.
- **Commits:** on the task branch only; clear messages saying what and why; **no Co-Authored-By
  and no AI-attribution lines**; never push.
- **Report honestly:** what changed with file:line, the exit-gate evidence (the command output or
  the screenshot path), the commit sha, and every QUESTION. If a test fails, say so with the output.
  If you skipped something, say so.

## 4. Words you will meet, defined

- **Claim** — one fact about an entity (an account or a contact): `field_key`, `value_json`,
  `evidence_span` (the quote), `source_url`, `extraction_method` (`human`/`api`/`scrape`/
  `llm_synthesis`/`crm_import`), `signal_priority` (1 = active buying intent, 2 = qualifying fact,
  3 = context), `outreach_safe` (may this be used in outreach copy?), plus lineage (which run wrote
  it). Written only through the claim store's `insert_claim`.
- **Field catalog / registry** — the list of allowed `field_key`s with a description each; the
  description is the research instruction for that field.
- **Recipe** — for one section of one page, the list of field keys it may draw from. Config, not code.
- **Display block** — the persisted text for one section of one page for one subject, with the claim
  ids every sentence cites.
- **Evidence** — the wire object the frontend renders as a source chip, resolved from a claim id;
  carries a verbatim `quote` or, when none exists, a `researchExcerpt` (never a fabricated
  quotation); `verificationKind: record` marks private records (email checks, database rows).
- **Segments** — clause-level pieces of a display sentence, each with the claim ids supporting that
  clause; chips render after the clause.
- **Internal notes** — the frontend control under which restricted (`outreach_safe=false`) research
  is shown; it is never part of the main reading flow and never in outreach copy.
- **Answer key** — a proof-of-concept run whose outputs are the expected result of a production run:
  Probook (`.context/arv2-clue-sample-v3/`), Zafran (`.context/arv2-one-account-aiark/`), the ten
  people (`.context/arv2-person-depth/`), the three Zafran pages (`.context/frontend-page-content/`),
  the display control test (`.context/display-layer-control-test/`).
- **Lenient mode** — `CLUE_CLAIM_WRITE_LENIENT=true`: the write gate stamps defaults and stores
  instead of refusing.
- **Quarantined** — code that exists on disk but is never composed into the running system. You do
  not import from it.

## 5. Your first fifteen minutes on any task

1. `git branch --show-current` — you must be on a `task/<step>-<slug>` branch, never the base.
2. Read the three documents in §1 (skim the master plan's §2 rules and the section your charter
   cites; read the work split §1 in full).
3. Read the charter twice. List the files it allows you to touch. If the task needs a file outside
   that list, STOP with a QUESTION now, before writing code.
4. Run the baseline your charter names (usually `make check` for Python work, the frontend gate for
   frontend work) and note what is already red — the known pre-existing failures are listed in
   `_memory/2026-09-01-r0-step2-merge-complete.md`; anything else red after your change is yours.
5. Do the work. Commit on the task branch. Report per §3.

## 6. If the code and the plan disagree

The plan wins for *what to build*; the code wins for *how the platform already works* (its
functions, tables, and conventions). If following the plan would require changing something on the
never-touch list, that is a QUESTION for Aryan, relayed through Shashank. Do not work around it.
