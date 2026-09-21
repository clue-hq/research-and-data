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

## Next
Founder reads the spec → `superpowers:writing-plans` → implementation (Opus subagents, Fable
reviews). Live proofs (spec §4 items 5–6) are founder-triggered and spend Exa cents.
