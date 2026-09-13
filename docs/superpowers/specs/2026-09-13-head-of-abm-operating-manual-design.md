# The Head of ABM's operating knowledge library — inventory and design

**Date:** 2026-09-13. **Status:** study complete; design proposed for founder review. **Lane:**
`research-streaming`, worktree `san-salvador`. **Evidence:** five read-only inventories, every
claim cited to `file:line`, in `docs/superpowers/research/2026-09-13-head-of-abm-manual/`:
`A-tools.md` (2,207 lines), `B-context-and-workspace.md` (932), `C-domain-model.md` (1,350),
`D-authority-gates-and-human-surfaces.md` (984), `E-runtime-and-sibling-agents.md` (1,793).

**Relation to other work:** this is the knowledge layer the reorganisation spec
(`2026-09-13-agent-workspace-reorganization-design.md`) needs to make its skills small. It
supersedes nothing; it names defects that the lane-1 plans should absorb (§7).

---

## 1. What the study found, in one page

The agent is told about itself in three places that do not agree: the system prompt (v8, 82
lines), the Stage-0 skill (v26, 245 lines), and a generated "resolved resource and capability
map" appended to the prompt on every model call. Everything else it needs is either in code
comments, in database CHECK constraints, or nowhere.

- **Tools.** 21 governed tools are granted. The skill teaches 16. Three of the 21 cannot work
  today (`get_research_view@1` is flag-off and pins a row the ARV2 lane never writes;
  `submit_ingestion@1` has no engine at any composition root; the directive pair
  `draft_account_research_directive@5` / `open_directive_confirmation_gate@1` writes rows no
  granted tool reads). The capability map shows each tool as `name@version effect=<class>` and
  nothing else; the one-line description is the model's only guidance. (A §1–9, summary table)
- **Vocabulary.** 22 domain terms the agent reads or writes and has no word for: `outreach_safe`,
  `use_class`, `signal_priority`, source tier, `needs_review` vs `suspended`, job `stage`,
  `refreshing`, `added_via`, `merged_into`, "settled", `fit`, "verified" (a verdict exists),
  "shown", the five personas and their display order, live claims vs current value,
  `write_markers`, the three gate kinds it cannot open. (C, closing section)
- **Vocabularies live in comments.** Every status set (`not_started / in_progress / needs_review /
  completed / suspended`; candidate `pending / pass / partial / unclear / duplicate_of_existing /
  not_chosen_before`; `unverified / verified / rejected`) is a `#:` comment in the read tools,
  so it never reaches the JSON schema the model sees. (B §6.3)
- **The registry is invisible.** 161 registered claim fields with descriptions; no card, file,
  prompt or skill lists one. The guessed prefix `firmographic` on 2026-09-13 followed. (B §6.2)
- **Runtime facts never told (27).** The 3-refusal budget shared across all tools and counted per
  parallel call; the separate 2-repair finalize budget; the 16 KiB receipt bound; 600-char
  truncation of failure messages; 52 supersteps and a 300 s wall clock; only `finalize_turn`'s
  `user_message` reaches the human; a failed turn shows the human nothing; one turn per thread and
  queued messages are invisible; `status.md` is frozen for the turn while the read tools are live;
  `replayed: true` receipts after a crash; a stop keeps committed effects; L6 history is evicted
  oldest-first with no marker; `assumptions` are stored but never shown; ICP fit verdicts are
  gated away from the agent that launched them. (E, "What the agent is never told")
- **Prompt says, code does not enforce (13 rules).** "Never widen the set", "never launch from an
  earlier message", "never write a plan on the first turn", "no em dashes", "no fact without a
  file", and the skill's claim that the platform refuses an unrouted finalization (true only on
  the dev trial). (D §B)
- **Code enforces, prompt never mentions (18 refusals).** ICP gate keyed on the project so a second
  thread gets `icp_gate_already_presented_elsewhere`; a human edit invalidates a pending gate
  (`GATE_SUBJECT_STALE`); a design leg blocks gate answers; `domain_refs` outside four object
  types are silently dropped; `user_message` capped at 65,536 chars. (D §A)
- **Context gaps (13).** `product/catalog.md` has no product ids although two skills say to read
  them there; `context_availability` is hardcoded "unavailable" since ruling D5 and reads as
  missing knowledge; the budget card is a literal with no scale; gate state is invisible between
  turns; attached refs name an id but not the file that holds the row. (B §6)
- **Two structural contradictions.** The prompt teaches specialist delegation and the map says it
  is withheld. The only spend gate feeds the retired lane; the live ARV2 launches are gated by the
  ICP pin and the product set, which are human gate receipts, but by nothing else. (D §C, E rows
  15–16)

The conclusion: a manual is not decoration. Today the agent is asked to be honest about things it
cannot name and careful about limits it cannot see.

## 2. Principles for the library

1. **One fact, one home.** Every value the agent can be asked about has exactly one authoritative
   chapter; skills and tool descriptions point there instead of restating it.
2. **Generated where the code is the source.** Tool contracts, refusal codes, status vocabularies,
   the field registry, error strings and limits are rendered from descriptors, enums, the registry
   table and settings by a build step, and a drift test fails when the code moves. Hand-written
   prose is reserved for judgment: how to do a task well, what to say to a human, what a term
   means for the work.
3. **Disclosed, then opened.** Chapters are files in the workspace. The capability map lists each
   with a one-line summary and its path (the mechanism skills already use,
   `registry.py:298-315`); the model opens a chapter with `read_file` when the summary matches
   its need. Nothing is preloaded except the index.
4. **Cross-referenced by path.** A chapter names other chapters by their materialized workspace
   path (`.deepagent/skills/manual-<chapter>/<version>/SKILL.md`, written by the builder from a
   `manual:<chapter>` token). A skill says "what the read tools return and refuse is in
   `manual-tools`". A tool's `model_description` ends with "Manual: <path>#<tool>". The glossary
   is the vocabulary authority and every chapter links unknown words to it.
5. **Honest about enforcement.** Every rule states whether code enforces it or only the prompt
   asks for it. A safety net that is not installed is not described as installed.
6. **Versioned and pinned as skills.** Each chapter is an immutable catalog skill with a digest
   in the profile and the resource manifest; changing a chapter is a new version of that chapter
   (ruling M-1).
7. **Grants nothing.** The manual describes; the profile, the recipe and the toolbelt decide.

## 3. The inventory: what the agent needs to know

Grouped as the manual's chapters. Each item names its source of truth so the build step and the
drift test know where to read. `[gen]` = generated from code; `[hand]` = written by a person and
founder-reviewed; `[live]` = comes from a card or file at turn time, the manual only explains it.

### 3.1 Who you are and what a turn is

- Identity, seniority, writing rules (from prompt v8) `[hand]`.
- The turn: submission → execution id → workspace → context → rounds → `finalize_turn`;
  statuses `requested / context_ready / running / awaiting_input / completed / failed / cancelled
  / abandoned / privacy_tombstoned` `[gen]` (E §1.2); failure codes and what each means `[gen]`
  (E §1.3).
- Limits: 24 model rounds, 52 supersteps, 300 s wall clock, 8,192 output tokens per call,
  65,536-char `user_message`, 64 assumptions, 64 next actions `[gen]` (E §1.4, D §4.2).
- The two repair budgets: 3 governed refusals per turn shared across tools and counted per
  parallel call; 2 finalize repairs; what the fourth and third refusals do `[gen]` (E §1.5).
- The receipt: what a `GovernedOperationReceipt` is, `replayed`, the 16 KiB bound, spill (after
  lane-1 plan 4) `[gen]`.
- What reaches the human: only `finalize_turn.user_message`; plan cards from `domain_refs` of
  four object types; gate cards from `open_gate_refs`; `assumptions` are stored, not shown; a
  failed turn shows nothing `[gen]` (D §4, E row 7–8).
- Freshness: `status.md`, `decisions.md`, brand documents and the ICP pin are frozen for the turn;
  the read tools are live; queued human messages are invisible; history is evicted oldest-first
  under 96,000 bytes `[hand over gen facts]` (E rows 10–11, 20).
- After a crash: another worker resumes the same execution against re-verified bytes; receipts
  you do not remember are `replayed: true` `[hand]` (E row 12).
- Money: `limit_millicents` is a per-plan estimate ceiling, not a running total; you cannot see
  cost, tokens, latency or logs and must not estimate them `[hand]` (E rows 14, 27).

### 3.2 Your workspace

- The mounts and folders, per the reorganisation spec: `brand/`, `project/`, `thread/`, `inputs/`,
  `context/`, `work/`, `reads/`, `outputs/`, `.deepagent/`; which are read-only, which persist,
  which are snapshotted; quotas `[gen from profile + layout]`.
- The file tools as they really behave: `read_file` offsets and limits are lines, default 2,000;
  `grep` is substring, not regex; `glob` is `fnmatch` over a flat list; `ls` never marks a
  directory (until plan 1 adds mount entries); `edit_file` refuses `replace_all` `[gen]` (A §8–9).
- Every card and what it says: project card fields including `context_availability` and why it
  reads "unavailable"; budget card; brand knowledge index; project library index; focus and
  attached-ref files and how to find the row behind an attached id `[gen]` (B §2, §6.6–6.9).
- Every document format: ICP front matter (`kind`, `icp_key`, `product_ids`, `hard_gates{key,
  rule, test}`, `exclusions`, `persona_map`, `qualifier_fields`, `derived_from`, `version`),
  persona front matter and the eleven sections, plan front matter with `version:`, catalog and
  product files and where product ids actually live `[gen from writers]` (C §6.2–6.4, B §6.1).
- `status.md` section by section, which rows feed each line, and what "N/M finished", "person
  research only", "verified", "shown" mean `[gen]` (B §6.4, C §3.4).

### 3.3 Tools (one chapter per tool, plus an index)

For each granted tool `[gen from the descriptor and the tool module]`: address, effect class,
whether it spends, whether it opens a gate, every input field with type, default and bounds,
every refusal code with its meaning and the correct next move, every output field and its bounds,
what becomes true afterwards, what the human sees in chat for it, the skill section that teaches
it, and its manual cross-references. The index is the table in A ("Summary table — all 21
granted tools") plus the framework tools and `finalize_turn` (A, "Part 2"). A refusal's
"next move" is the one hand-written line per code `[hand]`.

### 3.4 The domain

- **Claims** `[gen + hand]`: the row; tiers 1–4 and what each means for trust; `verification_status`
  and that this lane runs unverified; `use_class` and that `sensitive` never leaves the store;
  `identity_binding`; `outreach_safe` and the restricted sections; `signal_priority` as the sort;
  evidence span and source url; live claims vs superseded, `merged_into`; the display gate stated
  predicate for predicate and the promise that `read_account_research` mirrors it; `write_markers`
  such as `source_missing` and `unevidenced` and what they say about checkability (C §1).
- **Fields** `[gen from field_definition]`: all 161 keys grouped by family with description, value
  type, sensitivity, freshness; which families carry claims on this workspace comes from the read
  tool's `prefixes`, not the manual (C §2).
- **Accounts and contacts** `[gen]`: `project_account`, `added_via` (four values, first-add-wins,
  and that a launch stamps `manual`), how `research_status` and `refreshing` are derived, merge
  losers, the 17 overview sections in recipe order, the three restricted keys, when an overview is
  written (`ensure_page` on first page view) (C §3).
- **Research** `[gen]`: run and job statuses with `needs_review` = failed awaiting a human and
  `suspended` = paused (every worker restart suspends in-flight jobs); stages `deep_research →
  synthesis → committee → member_research`; `effort` values; `committee_cap`; what "settled"
  means; the committee → contact → person-job fan-out; what the run read returns and what only
  `status.md` carries (C §4, E §3.1–3.2, row 24–25).
- **Discovery** `[gen]`: run statuses, `pass` strict/relaxed, dispositions and which are stamped
  before any gate, `fit` = passes over gates with unclear as half and `NULL` = unscored,
  `verdicts_json`, approval = "Add to project", unapproved is not rejected (C §5).
- **Documents** `[gen]`: kinds, folders, statuses and the servable set, scope rule, versions and
  `superseded`, `project_icp_pin`, `project_product` selection versions, onboarding run kinds
  (C §6).
- **Decisions** `[gen + hand]`: `volunteered_statement` as the store, routes, the quote and
  entailment rule, latest-correction-wins, DSAR reverse binding, and a closed `route_key`
  vocabulary to replace the 33 ad-hoc keys (proposed in §7) (C §7).
- **Gates** `[gen]`: the six gate kinds, the three the agent can open, decisions, what an
  approval writes, how the answer reaches the next turn (as the human's message JSON, and through
  `status.md`) (C §8, D §2).

### 3.5 Authority

- What you decide alone, what needs a gate, what you can never do, each row marked
  code-enforced or prompt-only `[gen for the enforced set, hand for the rule text]` (D §1, §5).
- The gate refusals the skill never mentions, with the move for each (D §A).
- Spend: what costs money, who authorizes each path, that the live launches are gated by the ICP
  pin and product set and by nothing else, that `request_persona_synthesis` and a design leg's
  first message spend without a gate (D §6).
- The surface: delegation is withheld here; no shell, network, host filesystem, secrets;
  `gate.respond` is a separate human permission (D §1.4–1.8).

### 3.6 Humans and screens

The table in D §3.1 as a chapter `[hand, from the table]`: for each human action the screen name
as the UI labels it, the URL pattern, the control, the backend route, and how the agent learns it
happened (`status.md`, the files, the read tools; never a notification). Includes the corrections:
the Knowledge page has no onboarding control; the Plan tab is not yet mounted; "Delete chat" and
"Pin project" are inert; most tools render as "Complete a project step".

### 3.7 Siblings and background work

One chapter per sibling `[hand over gen facts]` (E §3): what it does, how it is launched, how long
it runs and what stops it (100 rounds / 50 calls per round / 1,800 s for research jobs; live
durations 6–13 min per person job), its statuses, what it produces, and exactly which read shows
its outcome. Includes the design leg's truth today: the Head of ABM does not run while a leg is
open, cannot close one, and the exit judge currently fails so a leg may never close.

### 3.8 Errors

Every string the model can receive `[gen]` (E §5): `GovernedToolFailure` shapes and the
`plan_rejected` issue codes; the file-tool prefixes `quota_exceeded:`, `conflict:`,
`permission_denied:`; finalize refusals; and, per string, the correct next move `[hand]`.

### 3.9 Glossary

Every term above, one line each, linking to its chapter `[hand]`. This is where "settled",
"verified", "shown", "researched", "refreshing", "pinned", "proposed", "servable", "restricted",
"sensitive", "live claim", "merge loser", "gate receipt", "replayed" get their one definition.

## 4. The library on disk (ruling M-1, 2026-09-13: a chapter is a catalog skill)

No new resource kind, no mount. Each chapter is a catalog skill named `manual-<chapter>` under
`platform/agents/catalog/skills/manual-<chapter>/v1/SKILL.md`, with the existing skill front
matter (`roles: [head_of_abm]`, `tools: []`). The profile pins each chapter like any skill; the
generated capability map already discloses every pinned skill with its summary and its
materialized path (`.deepagent/skills/manual-<chapter>/<version>/SKILL.md`); the model opens a
chapter with `read_file`. Fifteen chapters:

```
manual-index                 # the map: one line per chapter with its summary
manual-turn                  # what a turn is, its budgets, what reaches the human
manual-workspace             # folders, mounts, cards, file-tool truths, document formats
manual-tools                 # one section per granted tool (generated)
manual-fields                # the field registry by family (generated)
manual-claims                # tiers, statuses, use classes, the display gate
manual-accounts-research     # accounts, statuses, stages, committees, "settled"
manual-discovery             # runs, passes, dispositions, fit, approval
manual-documents-decisions   # kinds, versions, pins, statements, route keys
manual-gates-authority       # what you decide, what needs a gate, enforced vs asked
manual-humans-screens        # what humans do where, and how you learn it
manual-siblings              # research, discovery, personas, design legs
manual-errors                # every error string and the next move (generated)
manual-limits                # rounds, clocks, caps, quotas, retention (generated)
manual-glossary              # one line per term, linking its chapter
```

Cross-references are written as `manual:<chapter>` in the source and rewritten by the builder to
the materialized path of the pinned version, so links never carry a hand-typed version. Skills
shrink to procedure and point at chapters; the three document skills of lane-1 plan 3 reference
`manual-documents-decisions` rather than restating front matter.

## 5. Generation and drift

- **Builder:** `platform/agents/catalog/manual/build.py` (plan `2026-09-13-operating-manual.md`) renders the `[gen]` chapters from the
  toolbelt descriptors (`build_toolbelt(storage=None, gateway=None)`), the enums in `clue_core`,
  the `field_definition` table (via a committed snapshot `fields.json` refreshed by the same
  script against the lane DB), the profile, `Settings` defaults and the frontend label map. It
  writes `platform/agents/catalog/manual/vN/…`.
- **Drift tests** (`tests/agents/test_manual_drift.py`): every granted tool has a chapter and the
  chapter's refusal codes equal the codes found in the tool module by grep; every enum value in
  the status sets appears in its chapter; the field snapshot's keys equal the registry's active
  keys; the map's manual block lists every chapter; the manual digest in the profile matches.
- **Hand-written chapters** are files the builder copies verbatim; their founder review is the
  gate, as for skills.
- **Vocabulary into schemas:** independently of the manual, the read tools' status fields become
  `Literal[...]` types (or `use_attribute_docstrings=True` on `ToolOutput`) so the JSON schema
  the model sees carries the values. Cheap, and it removes a class of guesses at the source.

## 6. Cross-reference conventions

| From | To | How |
| --- | --- | --- |
| Capability map | `manual/index.md` and every chapter | the generated block in §4 |
| A skill | a chapter or a tool page | inline path in the sentence that needs it |
| A tool's `model_description` | its manual page | trailing "Manual: manual/03-tools/<name>.md" |
| A refusal message | the manual page's refusal row | the code string is the anchor: "no_claims_under_prefix (see manual/03-tools/read_account_research.md)" |
| A chapter | the glossary | the first use of a defined term links `manual/13-glossary.md#<term>` |
| `status.md` | the chapter that defines its words | a footer line "Terms: manual/06-accounts-and-research.md, manual/07-discovery.md" |
| The manual | the skills | "Procedure: skill <name> §N" where a task has a skill |

Links are plain relative paths in backticks so `read_file` can follow them verbatim.

## 7. Defects the study surfaced, and where each lands

| # | Finding | Fix | Where |
| --- | --- | --- | --- |
| 1 | Three dead or dead-ended tools granted (`get_research_view@1`, `draft_account_research_directive@5`, `open_directive_confirmation_gate@1`); `submit_ingestion@1` unwired | ungrant the four at the next profile version; keep registered for replay | lane-1 plan 3's profile bump |
| 2 | `open_design_leg@4` and `inspect_statement_history@1` granted and untaught | a short section in the Stage-0 skill or their manual pages | manual v1 + skill |
| 3 | The surface framing sentence is three profile versions stale and describes the retired flow | rewrite `C6_SURFACE_POLICIES[project_conversation].framing` | hotfix-sized commit, lane 1 |
| 4 | Prompt v8 teaches delegation the surface withholds | drop the paragraph in prompt v9 or condition it on the map | prompt v9 with manual v1 |
| 5 | Skill §6 claims a routing-receipt refusal that only the trial installs | either wire `Stage0RoutingReceiptGuard` in production or delete the sentence; the manual states which | founder decision |
| 6 | Status vocabularies in `#:` comments | `Literal` types on the read tools' output fields | lane-1 plan 4 |
| 7 | `product/catalog.md` has no `product_id` | write `product_id` into the catalog document at synchronize time, or teach the per-product file path | lane-2-adjacent backend fix; manual states the real location meanwhile |
| 8 | `context_availability` hardcoded "unavailable" | replace with a truthful card or drop the field | with the project library index (plan 2) |
| 9 | Budget card is a literal (`external_research_budget_cents: "0"`) | render real values or drop the card | plan 2 |
| 10 | Most tools render as "Complete a project step" | labels for the nine unlabeled tools | lane 2, one commit |
| 11 | ICP fit verdicts are gated away from the agent | a `verdicts` section on `read_account_research` or a dedicated read, outreach-safe by construction because a verdict is not a personal fact | lane-1 plan 4 |
| 12 | `route_key` is free text, 33 ad-hoc keys | a closed vocabulary (`outcome`, `closed_won_pattern`, `list_math`, `channels_tried`, `follow_up_owner`, `day_ninety`, `product_focus`, `icp_scope`, `discovery_target`, `persona_seats`, `preference.<topic>`, `other`) validated by the tool | lane-1 plan 3 or a small follow-on |
| 13 | Skill §1 points to an onboarding control that does not exist | correct the sentence to the real path | manual v1 + skill |
| 14 | Field registry invisible | `manual/05-fields.md` (this design) and the per-account `prefixes` (hotfix) | this design + hotfix |
| 15 | The design leg cannot close (exit judge timeout) | the plan's status header already records it; the manual tells the agent the truth | existing item |
| 16 | `assumptions` never shown to the human | either project them or tell the agent they are not shown | founder decision |
| 17 | Live launches have no spend gate beyond the pins | state it plainly in the manual; a per-run estimate gate is a product decision | founder decision |

## 8. Build order

1. **Now, hand-written:** glossary, turn-and-limits, workspace, authority, humans-and-screens,
   siblings, errors' "next move" lines — from the five inventories, founder-reviewed.
2. **With lane-1 plan 2:** the builder and the generated chapters (tools, fields, statuses,
   errors), the drift tests, `manual@v1` pinned in the profile, the map block, path references in
   the skills. Plan 2 is the right moment because the workspace paths the manual cites settle there.
3. **With lane-1 plans 3–4:** tool pages regenerate as tools retire and arrive; the document
   skills reference the formats chapter; the read tools' `Literal` statuses land.
4. **Defect items** in §7 that are one-commit fixes (3, 10, 13) go in as they are reached; the
   founder decisions (5, 16, 17) are asked before manual v1 is written, because the manual must
   state the answer.

## 9. Open decisions for the founder

1. Routing-receipt guard: wire it in production, or remove the sentence? (§7 item 5)
2. Should `assumptions` reach the human as a card, or be dropped from the finalize contract?
3. Is a spend estimate gate wanted on the ARV2 launches, or is "ICP pin + product set" the
   intended authority? The manual will say whichever is true.
4. The closed `route_key` vocabulary in §7 item 12: accept, amend, or keep free text.
5. ~~One resource or one per chapter~~ — settled by ruling M-1: one catalog skill per chapter,
   because that is what the catalog already does; a generated chapter regenerates on its own
   version without re-reviewing the hand-written ones.
