# Puck spike, phase 2: our agent on Puck (a lean agent harness)

**Date:** 2026-10-07
**Status:** draft for founder approval.
**Branch:** `spike/puck-phase1` (trial area only; no platform code changes).
**Builds on:**
- phase 1 findings: `trials/puck-spike/FINDINGS.md`, all gates passed;
- the web-agent trials: `trials/web-agent/`;
- Ploy's playbook (Build Site Page, Brand Adherence, Copywriting skills).

## The question

When our own agent (the deepagents runtime, grok-4.6) works on Puck pages, using plain JSON
for pages and plain React for sections, with a minimal harness:
- **Does it understand Puck's semantics easily?**
- **Is it clearly more productive** than today's website agent: cost, time, edit speed and quality?

## Founder rulings this plan carries (2026-10-07)

- **It is an agent, not a fixed pipeline.** Leanness comes from a small harness and short,
  non-contradictory skills, not from removing the agent.
- **Build with care.** This spike measures capability and efficiency before any platform work.
- **Brand theming is enforced by structure.** Pages are JSON that may reference only registered
  components. Style props are token choices only. New React sections must pass a token-only
  check.

## Why we expect it to be better (the hypothesis being tested)

Today's website agent cost $3.20 for 26 calls (trial 1), or $1.12 when staged. Three causes:
- a custom grammar it had to be taught: WebDoc, Rust tree ops, slot and repair ladders, 38
  bespoke tools, ~109k words of skills;
- one conversation that kept growing, to 200k tokens per call;
- screenshot-tile review, about 47% of tokens.

Ploy's agent is fast because it works in a medium models know (React/TS files), with a few
general tools, short skills, a platform service that hands it a bounded reading list, and one
full-page screenshot to review. Puck pages are JSON and Puck sections are React, both media
models know.

## The harness (everything the agent gets)

**Runtime.** Our deepagents runtime (`create_deep_agent`, 0.6.12):
- the file backend rooted at a run workspace;
- skills loading;
- our context-clearing middleware, with the rule adapted so a newer `render_page` clears older
  screenshots;
- a checkpointer, so a session can take follow-up edits.

Model calls go through our gateway (`lumen_agent.llm.init_model`). The model is an env setting
(grok-4.6 today). None of the website agent's tools or prompts are used.

*As built (T3, 2026-10-08):* the agent is composed with LangChain's `create_agent` and the
deepagents middleware we want (file tools with write permissions, skills, malformed-call patching),
the way the platform's scene solo graph is composed (`lumen_agent/harness.py`). `create_deep_agent`
always adds a subagent tool, a todo tool and a base prompt; leaving them out is part of what is
measured. No summarization middleware (context clearing covers screenshots; measured in E2). Also
built: tool calls from one response run in the order written (a test fails without it); a finish
guard (a turn cannot end on an invalid page; two reminders, then "completed with errors"); the
40-call safety stop. A build starts with no `page.json` or `shell.json`, because the file tools
refuse to overwrite a file; later changes are edits. The fixed prompt is about 3.4k tokens (system
prompt with the skills list about 1.2k, 11 tool schemas about 2.1k), against about 52k on the
platform agent.

**Workspace (plain files):**

```
brief.md            the delegation brief (from a finished platform run, or written for the test)
plan.md             the agent's own plan and memory (message plan at the top)
page.json           the Puck page being built (one route); site shell in shell.json
catalog/
  index.md          every section available, one line each, in source-page order
  clones/<id>.md    a clone: source page, role, its slots (kind + original text), its other
                    visible text (usable as text replacements), its links
  sections.md       our own sections: purpose, fields, allowed token choices (from the Zod schemas)
brand/brand.md      the brand's token choices in words (surfaces, heading roles, button), and the
                    asset list (id, description, file)
research/           the account's overview and insights pages (from the platform reads)
seller/             the seller's files (the same selection as the staged copy stage)
fetched/            pages the agent opened with fetch_page (also the evidence corpus)
```

The catalog is our version of Ploy's "Design System page-build plan". It is a bounded list of
what exists, so the agent never explores raw HTML or CSS.

**Tools.** The standard file tools (deepagents) plus four of ours:

| Tool | What it does |
|---|---|
| `validate_page` | Runs `scripts/validate-page.ts` (TypeScript, the same Zod schemas the components use) over `page.json` and `shell.json`, returning exact errors. |
| `render_page` | Saves the page to the spike's site file and returns one desktop (1440) and one mobile (375) full-page screenshot, scaled down, from the published route. |
| `web_search` | The platform's `web_search`, used for the seller's published case studies. |
| `fetch_page` | Opens a page and saves its text under `fetched/`. Numbers and quotes on the page must come from saved pages or the research and seller files. |

What `validate_page` checks:
- registered component types only;
- props match each section's schema (style props are enums of token choices; there are no
  colour, size, class or style fields);
- clone ids and slot keys exist;
- every text replacement's `find` text exists in that clone;
- image URLs come only from the brand's asset list;
- one primary destination;
- every number in the page's visible text appears in the evidence corpus (research, seller
  files, fetched pages);
- no wording from the brief's "Notes for Design" section;
- no person named in the account's research.

*Founder ruling 2026-10-08:* the last three are judgement, not contracts, and were removed from
`validate_page`; they live only in the prompt and skills. The validator checks contracts. One
primary destination stays a blocking check for now ("none of these should be blocking ideally").

Stretch, only in experiment 5: `write_section`. It writes a new React section file and runs a
type check plus a token-only lint (no hex colours, no arbitrary pixel values, no inline styles,
no `className` props). It does not join the catalog without founder approval.

**Error handling and retries (founder ask, 2026-10-07):**

1. **The agent's own mistakes.**
   - `validate_page` returns actionable errors: where (section id and field), what is wrong, and
     the allowed values, for example `section "proof" field surface: "green" is not allowed; use
     one of page, card, muted, brandSubtle, brand, inverse`.
   - The agent fixes them and validates again.
   - `render_page` and finishing refuse while the page is invalid.
2. **Stuck loops.** When the same error returns a third time, the tool says so plainly ("third
   failure on this; try a different approach, or leave this section out and say why in the
   plan") and records it.
3. **Tool and provider failures.**
   - Each tool retries transient failures (network, fetch, search) twice with backoff before
     reporting the error.
   - Malformed tool calls return to the model as an error message (deepagents' default) so it
     can retry.
   - The gateway retries model calls and can fall back to a second model.
4. **Bad edits.**
   - Every page write that validates saves a version.
   - A `restore_version` tool lets the agent roll back a change that broke the page or the render,
     instead of patching forward.

A run that still cannot fix something ends "completed with errors" and lists what remains.

**Skills (three, short, written fresh, not copied from the website agent):**
1. **`account-page-copy`.** The approved copy skill (trial overlay version).
2. **`building-with-puck`.** How a page is put together:
   - the catalog;
   - clones vs our sections;
   - slots, text replacements and link replacements;
   - token choices;
   - the shell;
   - reuse first (clone, then our section, then new only as the last option);
   - the order of work.
3. **`page-review`.** One look at the two renders against a short checklist:
   - the first screen says what and for whom;
   - nothing broken or empty;
   - no duplicate images;
   - copy fits its space;
   - mobile works.

   Then fix only what fails.

**System prompt:** under about 800 words. Who the agent is, the workspace, the tools, "read
the skills before starting", and "plan.md first".

**Lean rules for the harness itself:**
- **A rule that code can check lives in `validate_page`,** never in a skill.
- **A new rule enters a skill only when an experiment fails without it,** and the rule names that
  case in the skill's change log.
- **Every run records its numbers:** per call, input and output tokens; then cost, time, tool
  calls, render rounds, validation errors found and fixed, and the size of the prompt and skills.

## Inputs for the experiments

| Case | Brand | Account | Brief | Why |
|---|---|---|---|---|
| A | Garner | Syracuse City School District | Run 3's stored brief (same input as trial 1 and the staged trial) | Head-to-head baseline |
| B | Conduit | Dana.AI | Run 1's stored brief | Rich research. The angle (D3) is still the founder's open decision; used only to test capability. |
| C | Conduit | Atrium Hospitality | A short brief written for the test | Thin research (headcount only), which tests honesty |

## Experiments

**E1. Build a page from the brief** (cases A, B, C; two runs of A to see variance). Recorded:
- calls, tokens, cost, wall time;
- render rounds;
- validation errors (how many, which kinds, fixed by the agent itself or not);
- a founder rating against the hand-built phase-1 pages, both copy and design.

**E2. Edits in the same session** (case A's page). Ten scripted chat requests, each a new turn:
1. Change the hero headline.
2. Swap the proof for a different case study.
3. Add a section about the HDHP and HSA.
4. Make the proof band dark.
5. Move the proof above how-it-works.
6. Hide the logo row.
7. Shorten the four cards.
8. Change every button to "Request the analysis".
9. Use a different photo in the feature split.
10. "Make it feel more premium" (vague, on purpose).

Recorded per edit: success (did exactly what was asked, nothing else changed), time and cost.

**E3. Does it understand Puck?** A tally across all runs of semantic mistakes:
- unknown components;
- invented props;
- wrong slot keys;
- replacements that match nothing;
- non-token styling attempts;
- broken JSON.

Also: how many were caught by `validate_page` versus seen only in a render, and how each ended:
- fixed by the agent on its own;
- fixed after the loop guard;
- rolled back with `restore_version`;
- left unfixed.

**E4. Against the baseline.** One table on case A:

| Run | Cost | Calls |
|---|---|---|
| Run 3 (platform) | $4.14 | 38 |
| Trial 1 | $3.20 | 26 |
| Staged trial | $1.12 | 21 |
| Phase-2 agent | | |

Plus time, render rounds and founder rating.

**E5. Stretch: a new section in React.** Case A with a request the catalog cannot serve (for
example a three-step timeline). The agent writes it with `write_section` and places it, and the
token lint and render show whether it stays on brand.

## Success bar (proposed; the founder may change it)

- **A new page:** under $1 and about 10 minutes; validation errors fixed by the agent itself;
  rated equal to the hand-built pages.
- **An edit:** under $0.05 and about 1 minute; at least 9 of 10 done exactly.
- **Puck semantics:** after the first two runs, no repeated mistake of the same kind.
- **Brand:** zero non-token styling on any page, and the stretch section passes the token lint.

## Tasks, in order

**T1. Contracts and catalog.**
- Zod schemas for our four sections, `ClonedSection` and the shell, used by the components and
  by `scripts/validate-page.ts`.
- A catalog generator that writes `catalog/` and `brand/brand.md` from the exported brand data.
- `tsx` added as a dev dependency.

**T2. Tools.**
- `validate_page`, which shells out to the TypeScript validator;
- `render_page`, using Playwright on the dev server;
- `fetch_page`, which saves text to `fetched/`;
- `restore_version`, with page versions saved on every valid write;
- `web_search`, using the platform reads, composed as in `trials/web-agent/run_trial.py`.

Each tool is tested on the phase-1 pages before the agent sees it. Those pages must validate
clean; a deliberately broken copy must produce the expected errors.

**T3. The agent.**
- The three skills and the system prompt, with their substance shown to the founder in chat
  before they are final.
- A runner, `trials/puck-spike/agent/run_agent.py`: builds the workspace for a case, runs one
  turn or a scripted series of turns on one session, and writes the run record.

**T4. E1, the build runs.**

**T5. E2, the edit runs.**

**T6. E3 and E4.** Tally and table from the run records.

**T7. E5, the stretch.** Only if E1–E2 pass.

**T8. Findings.** `trials/puck-spike/AGENT-FINDINGS.md` and a `_memory` note. Go or no-go for a
platform integration spec, which would cover Head of ABM routing, storage, the Puck editor in our
frontend, publishing and the production notes.

## Spend and safety

- **Model spend:** expected under $15 for all experiments, given ~$0.5–1 per page and cents per
  edit. A safety stop of 40 model calls per turn (generous) is recorded and alerted, not tuned
  down.
- **Data:** the lane database is read only. Nothing is written to platform documents. Runs live
  in `trials/puck-spike/agent-runs/` (gitignored, except the run records committed with the
  findings).
- **Never pushed.**

## Risks

- **Prompt-cache behaviour with file reads of `page.json`.** Re-reading the page each turn could
  grow context. This is measured; if needed, the clearing rule also clears superseded page reads.
- **grok-4.6 as the limit on copy quality** (seen in the staged trial). Model choice is an env
  setting; one extra run of case A on a second model is optional and reported separately.
- **Copy-skill gaps already known** (the proof rule, the hero). They are fixed through E1, with a
  failing case first.

## Planned follow-up: seller component library (founder direction, 2026-10-07)

Our own fixed sections are a starter set. The long-term model, closer to Ploy's, is a library of
**the seller's own components**:
1. **Rebuild once per seller.** The agent rebuilds each captured section once as a real React
   component with typed props (Ploy's shallow refactor: same look, content as data).
2. **Approve by comparison.** Each component is checked by screenshot comparison with the source
   section, and approved by a human.
3. **Register it in Puck.** The agent composes pages from these components (JSON, as today).
4. **New sections in the seller's idiom.** When a page needs a section the site lacks, the agent
   writes one using the seller's theme and the type patterns of its existing sections.

This removes generic sections and makes everything inside a section editable (lists, order,
variants). The theme, the measured values, the catalog (as the seller's component registry),
validation and Puck all carry over.

**Open design questions:**
- running agent-written code safely: built in the offline sandbox, served from the seller's
  preview origin, with the editor canvas hosted there too;
- rebuild cost and quality per seller;
- brand enforcement as a lint check plus human approval.

**Next spike, if phase 2 passes:** rebuild Garner's five most-used clones as components, compare
fidelity, and build a page from them. Phase 2's E5 (the agent writes one React section) is a
small preview.
