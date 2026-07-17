# `clue_research/api/` — composition root + FastAPI app layer

**Status:** the deep-profiling composition root (`composition.py`), the M12 narrative wiring (`narrative_wiring.py`), and the **M12.3 output/handoff FastAPI surface** (`handoff_app.py` + `handoff_wiring.py`) are shipped. The front-edge (M5) and review (M13) surfaces are still to come.

**Spec:** [`docs/specs/M00-foundations-and-shared-contracts.md`](../../../docs/specs/M00-foundations-and-shared-contracts.md) §M0.1 · [`docs/specs/M12-value-narrative-and-handoff.md`](../../../docs/specs/M12-value-narrative-and-handoff.md) §M12.3

The composition root where the otherwise-independent milestone packages are wired together, and the FastAPI app layer:

- **`composition.py`** — the M8 deep-profiling wiring (field packs, worker registry, M9 governance seams).
- **`narrative_wiring.py`** — M12: the `account.value_narrative` field pack, the Client-Knowledge retriever stub, and the M12.2 handoff-assembler construction.
- **`handoff_app.py`** — the M12.3 read-only handoff HTTP surface (the terminal seam of the subsystem): `GET` one handoff (+ provenance index), list a run's ready handoffs, resolve any value's provenance. Tenant-scoped (the auth seam), schema-versioned, no write path.
- **`handoff_wiring.py`** — the durable-backed readiness reader, the `HandoffService` builder, and the `CampaignPhase.HANDOFF` phase handler that drives the durable emit/notify outbox.

## Modular boundary (M0.1 / ENG-101)

**Nothing else in `clue_research` may import `api/`.** It is the outermost layer; dependencies point inward only.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
