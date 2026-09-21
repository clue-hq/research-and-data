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
`clue_api/web_search_tool.py`, registered UNGRANTED (counts 141→142 / 161→162); (3) recipe0-stage0@31;
(4) `head-of-abm@v61` = prompt v14 (the "Look things up in this order" paragraph) + the pin +
`manual-*@v8` (`make manual`; 11 hand-written chapters re-minted by version line + paths only) +
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
