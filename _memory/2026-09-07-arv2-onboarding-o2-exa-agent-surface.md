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

## Open follow-up (found at O2 close-out, NOT fixed here)

`uv run mypy platform/api/clue_api/arv2` reports **9 `union-attr` errors in
`onboarding_documents.py`** (lines 202, 214–217, 230, 240–241), all from the same idiom:

```python
facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
```

Two separate `.get` calls, so mypy cannot narrow and infers `Any | dict[Any, Any] | None`; the
later `facts.get(...)` / `sections.get(...)` / `c.get(...)` then trip strict mode. **No runtime
bug** — the `isinstance` guard means the value is never `None` in practice, and the 297 offline
tests pass. But `platform/api/clue_api` is in the root mypy `files` under `strict = true`, so
`make check`'s `typecheck` step is red on this branch. The fix is mechanical and behaviour-free
(bind each `.get` to a local once, then `isinstance`-narrow it). Left to the O2 owner to rule on
rather than edited silently, because the file is Task 4's shipped code and outside this task's
brief. Pre-existing at HEAD `86e778deb`; the O2 close-out commit does not touch it.

Money note: `make check` and every `tests/arv2/*_live.py` were deliberately NOT run at close-out —
with real keys in `.env` they make paid provider calls. The gates run here were the offline ARV2
suite, ruff check, ruff format --check, and mypy over the package.
