# 2026-09-22 — `web_search@1` design session (lome lane, branch `research-streaming-v3`)

Spec: `docs/superpowers/specs/2026-09-22-web-search-tool-design.md` — founder-approved section by
section in chat; written spec awaiting the founder's read before the implementation plan.

## Rulings taken (founder, 2026-09-22)
- Plain Exa `/search`, `type=deep-lite`, `outputSchema {"type":"text"}`, highlights on, ≤10
  results — "nothing more high config than this". Optional, absent-unless-passed:
  `include_domains`, `exclude_domains`, the two published-date bounds.
- Both roles get it: Head-of-ABM (`v61`) and design (`design@v3`, both lanes through the
  PR #67 platform-reads seam). Direct governed tool over the in-house client — NOT MCP, NOT
  `exa_py` from a harness (both bypass the provider ledger).
- Last resort, by PROMPT not code: claims first for an account/contact, seller knowledge files
  first for the seller; web search only when those are empty, vague or inconclusive, and the
  answer says which facts came from search. Results are text; never promoted into a claim.
- No per-turn search budget (no-pre-emptive-caps ruling 2026-09-08); no skill-pin guard.
- The M-series specs are history, not governance: one dated line at M8B item 15 + the master
  plan's Track O "Exa MCP" item; M8C/M8D/M06A untouched.

## Facts verified in the repo
- `platform/api/clue_api/arv2/exa_client.py::search` already passes `type` through and takes
  `highlights`/`num_results`; lacks `excludeDomains` and `outputSchema` on `/search` (two keys).
- `exa_search_evidence@1` (`onboarding_evidence_tools.py`) is the tool-shape precedent (SPEND,
  AT_LEAST_ONCE, refuses before spend); granted only to onboarding synthesis.
- The registry refuses a grant no profile pins (`agent_registry_wiring.py`); manual-drift gate in
  `tests/agents/test_manual_drift.py`.
- Design injection: `design_platform_reads.py` (platform) → `lumen_agent/platform_reads.py`
  (runtime) → both `harness.py` and `harness_web.py` call `make_platform_read_tools`.
- `CLUE_EXA_API_KEY` present in `.env.example` and this lane's `.env`; no new flag.

## Plan (written 2026-09-22, after the founder approved the spec)
`docs/superpowers/plans/2026-09-22-web-search-tool.md` — eight tasks: (1) `excludeDomains` +
`outputSchema` on the client's `/search` body and `output_text` on the result; (2) the tool module
`clue_api/web_search_tool.py`, registered UNGRANTED (counts 141→142 / 161→162); (3) recipe0-stage0@32;
(4) `head-of-abm@v62` = prompt v15 (the "Look things up in this order" paragraph) + the pin +
`manual-*@v9` (`make manual`; 11 hand-written chapters re-minted by version line + paths only) +
`tool_notes.yaml` entry + frontend label `Search the web` + composer pin; (5) `design@v3`;
(6) `DesignPlatformReads.web_search` + the fourth LangChain tool in `make_platform_read_tools`
(both harnesses already call it); (7) scene tools skill "Web search" section + the two web-lane
prompt sentences; (8) M8B item 15 line, master-plan Track O note, spec status, memory.

**Correction found while planning:** the journaled invoker's `ToolContext` carries NO project id,
so the tool's ledger row is workspace-stamped on both roles (as `exa_search_evidence@1` is);
spec §2.2 rewritten to say so. Project attribution lives in the journal (the execution's `project`
pin on Head-of-ABM; the leg's turn on design).

**Facts the plan relies on (verified):** a catalog `sha256` is `shasum -a 256` of the file bytes;
tool pin digests come off `build_toolbelt(storage=None).descriptor('web_search','1')`; every
Head-of-ABM tool declares `pin_requirements=("project",)` and `Stage0StepPinProvider` adds the
execution's project pin for tools whose body names none (`run_python` precedent) — `web_search`
joins that set; the manual's four generated chapters are the builder's alone
(`MANUAL_VERSION`/`PROFILE_VERSION` in `clue_agents/manual/build.py`); the frontend `TOOL_LABELS`
map is what "The human sees" renders from; `test_recipe_contracts.py::test_operation_id_requirements_are_explicit`
enumerates every operation-bound address, so the tool must be added there.

## Next
Founder picks the execution mode (subagent-driven, Opus implementers, Fable reviews — or inline).
Live proofs (spec §4 items 5–6) are founder-triggered and spend Exa cents.

## Closing entry — LANDED 2026-09-22 (branch `feat/add-general-purpose-web-search-exa`, off `research-streaming-v3`)

All eight plan tasks are implemented and committed locally (never pushed). The spec's offline
acceptance (§4 items 1–4) is met; the two live proofs (§4.5–4.6) are founder-triggered and owed.

**The eight implementation commits, in order:**
1. `722814d91` feat(exa): `excludeDomains` and `outputSchema` on `/search`; deep-lite answer on the result
2. `9c561aa74` feat(toolbelt): `web_search@1` registered ungranted
3. `515a53412` feat(recipe): `recipe0-stage0@32` admits `web_search@1`; conversation runtime pins 31
4. `fd1906021` feat(head-of-abm): v61 grants `web_search@1` — prompt v15; recipe 32; manual v9
5. `74ad68d93` fix(head-of-abm): v61 — web_search fields carry their meaning into the manual; prompt v15 without em dashes
6. `a1778a950` feat(registry): `design@v3` pins `web_search@1`
7. `fefcdb6ce` feat(design): web_search rides the platform-reads seam — fourth tool in both harnesses
8. `cd2f9ca91` docs(design-agent): web search is the last resort — scene tools skill and web-lane prompt

(This record — M8B item 15, the master plan's Track O line, the spec status, this entry — is the
ninth commit.)

**Digests measured on the live descriptor / files:**
- `web_search@1` input schema `61f98fac6f56398866ea7e61539ede2f836d4e23b9a2a54ea8897a0eb80084a6`
- `web_search@1` output schema `45a58c07eb605b0f248bb7e60b9b30ec604a15202d5b1b3e0e0819f9b7f20599`
- prompt v15 `717a4ab82b537885b2b513f4b632e71b674adad1c81fa44c7d35f46d5a423718`
- HEAD_OF_ABM manifest `6bcb427f387d4e46c890b1ec435d3c7703e6731e848c8dde1f96fc7142a8e3da`

**Gate run at close (one invocation, 2026-09-22):** `tests/arv2/test_exa_client.py`,
`tests/api/test_web_search_tool.py`, `tests/api/test_toolbelt_wiring.py`,
`tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`,
`tests/api/test_recipe_contracts.py`, `tests/agents/test_catalog.py`,
`tests/agents/test_manual_builder.py`, `tests/agents/test_manual_drift.py`,
`tests/api/test_c8_trial_surface.py`, `tests/api/test_comprehensive_research_contract.py`,
`tests/api/test_client_knowledge_privacy_s4e.py`,
`tests/architecture/test_provider_tool_schema_gate.py`,
`tests/agents/test_governed_tool_arguments.py`, `tests/api/test_design_platform_reads_db.py`
— **197 passed, 0 failed, 0 skipped, exit 0** (DB-marked tests against the throwaway
`clue_lome_sdd`@55040, never the lane DB). `make manual-check` → "4 manual chapters are current",
exit 0.

**Owed, founder-triggered (spends real Exa cents, this lane's stack + real `CLUE_EXA_API_KEY`):**
1. A Head-of-ABM turn in a project chat about something the platform never researched (the Austin
   GI practice-manager workshop invite): expect a `web_search` receipt in the journal, one
   `provider_call_ledger` row with `provider='exa'`, `operation='search'`, workspace-stamped, and
   a reply that says which facts came from the search.
2. A design leg for an event page on the same subject: expect `platform_reads_attached` to list
   four tools, a `platform_read` trace event with `tool: web_search`, and a `web_search@1` row in
   `tool_invocation` under the leg's workspace.

Record both here when they run.

### Rulings and deferred minors (SDD ledger, `.superpowers/sdd/2026-09-22-web-search-tool/progress.md`)

**Rulings taken during execution:**
- T2→T3: if `test_operation_id_requirements_are_explicit` goes red while the tool is still
  ungranted, make the Task-3 edit inside Task 2.
- T2→T4: Task 4 flips the two `ROLE_UNAVAILABLE` asserts to `AVAILABLE` when the grant lands.
- Task 4: `head-of-abm@v62` may be amended by a follow-up commit — it was minted on this branch
  and never pushed, so catalog immutability (a shared version) is not violated.
- Task 4: `description=` on the tool's pydantic fields is required, so the generated manual tables
  carry each field's meaning instead of `—`.
- Task 4: prompt v15's new paragraph carries no em dashes (the prompt's own output rule).
- Task 6: DB-marked tests run against the throwaway `clue_lome_sdd`@55040, never the lane DB.

**Minors deferred (none blocking):**
- Task 1: `_search_result`'s docstring opens "Shape a ``/search`` body" — it shapes a result from
  the body; wording only.
- Task 2: `highlights={}` on the wire is unproven against live Exa; the live proof decides
  (fallback `{"maxCharacters": 2000}`).
- Task 4: `tool_notes.yaml`'s header still says "granted by head-of-abm@v58" (pre-existing), and
  the `web_search` entry sits after `run_python` rather than alphabetically (nothing reads it
  positionally).
- Task 6: the DB test pokes `search_tool._client_factory` (a test-only double, loud if renamed);
  `ToolInvoker.invoke` does not enforce `pin_requirements` on this seam (same as the other reads).
- Task 7: the scene-tools skill paragraph keeps one em dash (house style of the design knowledge
  docs); `prompts.py` carries 9 pre-existing E501s, untouched.

## Close-out (controller, 2026-09-22, after Task 8)
Tenth commit `be8024cbb` (final fix wave: spec status names the feature branch; `_search_result`
docstring). Full focused gate run FIRST-HAND by the controller against the throwaway
`clue_lome_sdd`@55040: 211 passed in 55 s across 16 files (platform + design runtime), `make
manual-check` current. Branch `feat/add-general-purpose-web-search-exa`, 10 commits
722814d91..be8024cbb, local only. Owed: the two live proofs (spec §4.5–4.6), founder-triggered;
the first live call also settles whether Exa accepts `contents.highlights: {}` (fallback
`{"maxCharacters": 2000}`).

## Residuals worked (founder-requested, 2026-09-22)
- `tool_notes.yaml`: header names the active profile via `PROFILE_VERSION` instead of a fixed
  version; the `web_search` entry sits alphabetically (after `submit_ingestion`). No chapter moved.
- Design DB test builds `WebSearchTool(client_factory=…)` directly; no private-attribute poke.
- The design seam refuses `project_unbound` before the invoker when the leg carries no project —
  the execution layer asserts the tool's `project` pin only on head-of-abm's path, and this seam
  runs outside an execution (new DB test `test_a_leg_without_a_project_cannot_search`).
- The scene skill's "Web search" paragraph has no em dash.

## Merge onto `origin/research-streaming` (2026-09-22, at their `9835b11f2`)
`0bdac1757` on the base (automatic project targeting) had minted the SAME numbers we had —
`head-of-abm@v61`, prompt `v14`, `manual-*@v8`, `recipe0-stage0@31` — for a different change.
Resolution: their side taken verbatim for every collided catalog/recipe/code/test file, then our
layer RE-MINTED on top: `head-of-abm@v62` (= their v61 + `web_search@1` pin, prompt `v15` = their
v14 + our "Look things up in this order" paragraph, `manual-*@v9`), `design@v3` unchanged (their
design profile is still v2 and identical), `recipe0-stage0@32` = their v31 + `web_search@1`,
`CONVERSATION_RECIPE_VERSION = 32`. Digests re-measured (tool schema digests unchanged; prompt
`3406c4d7…`; HEAD_OF_ABM manifest `611426b2…`). Doc conflicts (`_memory/README.md`, the
display-prewrite spec) unioned.
**Base defects found and handled here:** (1) two Alembic heads on the base (`2b702a116c15`,
`46f04ac18b28`) — joined by `7c4fe6965720`; (2) seven base tests left stale by `0bdac1757`
(toolbelt name set/counts 144/166, authority count 144 + the two ungranted gates, catalog list
missing `icp-authoring@v3`/`stage0-interview@v35`, the four trial-surface tests) — fixed;
(3) `tests/execution/test_recipes.py` — two DB tests red on the base (their seed list moved v29 to
the historical list, so `versions == range(1..max)` and the `@19` promotion cannot pass) — NOT
fixed, base-owned; (4) the base pins `CONVERSATION_RECIPE_VERSION = 30` while granting
`configure_project_targeting@1` that only v31 admits — moot after our 32.
Gate on the merged tree: 225 passed across 18 files (`clue_lome_sdd`), `make manual-check`
current, one Alembic head. Lane DB `clue_lome` must run `alembic upgrade head` before the next `up`.
