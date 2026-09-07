# 2026-09-07 — ARV2 onboarding O2: Exa Agent surface, templates, mappers

Plan: docs/superpowers/plans/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md.
Branch: `onboarding/o2-exa-agent-surface` (worktree `semarang-o2`). Not pushed.

- `ExaClient.agent_run` (create → poll → settle; Bearer auth; the effort's fixed price reserved on
  the create leg, polls reserve nothing; metered on the completed body; `failed`/`cancelled`/
  `timed_out` returned, never raised — the driver's failure law, ARV2-ONBOARDING-PLAN.md §3).
- `onboarding_requests.py`: overview (contract-verbatim), reviews, per-product, persona evidence
  (the last is a `/search` deep-reasoning request, kept inside Exa's depth-2 / ten-property limits).
- `onboarding_documents.py`: `KnowledgeDocument` + four mappers; fixture = the 2026-09-07 sample run.
- Live (Task 3, run once — do not re-run casually, it is paid): `low`-effort company-overview
  Agent run — status `completed`, cost $0.025 metered, 14 polls, ~65 s wall time.
- Guards: import guard + cost provision extended (`ExaAgentRun`, `KnowledgeDocument`); README
  documents the Agent surface and the O2 templates/mappers; `pyyaml` added to `clue-api`.
- `KnowledgeDocument.cost` is `CallCost | None` — the mappers are pure, so it is the settling
  call's cost when built from a call and `None` otherwise. That is the cost-provision guard's
  documented exception, and it is named in the package README as the guard's docstring requires.
- Not done here (by design): settings (O1), the driver and artifact persistence (O3), the
  evidence tool registration (O4).

## Final review fix wave (2026-09-07, commit after the close-out)

Three findings from the whole-branch review, all fixed in one commit; no behaviour change.

1. **Strict-mypy narrowing in the mappers.** `company_overview_document` used
   `facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}` — two separate
   `.get` calls, so mypy could not narrow and inferred `Any | dict[Any, Any] | None`, producing 9
   `union-attr`/`arg-type` errors (lines 191, 202, 214–217, 230, 240–241) under the root
   `strict = true`. Each `.get` is now bound to a local (`raw_facts`, `raw_sections`) and narrowed
   once into a `Mapping[str, Any]`. `uv run mypy platform/api/clue_api/arv2` is now clean, so
   `make check`'s typecheck step is no longer red on this branch.
   *Deliberately not changed:* `product_research_document`'s `front.update({key: data.get(key) ...})`
   loop. It produces **no** mypy error, and "narrowing" it would change front-matter semantics —
   a missing key must stay an explicit `null` in the contract, which `data.get(key)` gives.
2. **A test for the unparseable Agent create.** `agent_run`'s `no_run_id` branch (a non-terminal
   create body carrying no `id`) had no coverage; without it the client would poll
   `GET /agent/runs/None` for the whole timeout. `test_a_create_with_no_run_id_gives_up_immediately_rather_than_polling_nothing`
   pins `status="unparseable"`, `error_code="no_run_id"`, `run_id is None`, `polls == 0`, one
   request on the wire.
3. **Explicit failure-note suffix.** `_failure_note` ended with `.rstrip(" —")`, which strips a
   character *set* and so would eat a real trailing em dash from a provider message. The em-dash
   suffix is now appended only when `error_message` is truthy. Proven equivalent on every other
   input (empty/None message still yields the bare code line).

Gates after the wave: 298 offline ARV2 tests pass (297 + the new one), `ruff check` and
`ruff format --check` clean, `uv run mypy platform/api/clue_api/arv2` reports no issues. The eight
mapper tests were not edited and stayed green. Live tests and `make check` were still not run —
they cost real provider money.

Money note: `make check` and every `tests/arv2/*_live.py` were deliberately NOT run at close-out or
at the fix wave — with real keys in `.env` they make paid provider calls. The gates run here were
the offline ARV2 suite, ruff check, ruff format --check, and mypy over the package.
