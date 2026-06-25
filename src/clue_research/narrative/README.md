# `clue_research/narrative/` — Value Narrative & Handoff

**Status:** M12.1 + M12.2 + M12.3 shipped.

**Spec:** [`docs/specs/M12-value-narrative-and-handoff.md`](../../../docs/specs/M12-value-narrative-and-handoff.md)

The per-persona value narrative (account claims × client knowledge), the `account_handoff` contract object + provenance index, and the transport-agnostic boundary to the content layer — where this subsystem's output is assembled and served.

- **M12.1 — positioning step** (`positioner.py`): joins verified account claims × Client-Knowledge into per-`(account, persona)` `account.value_narrative` claims-with-provenance, behind the M9.3 faithfulness judge.
- **M12.2 — `account_handoff` assembler** (`handoff.py` / `handoff_store.py`): the pure, deterministic store-read that gathers Outputs 1–4 into the frozen `core.handoff.AccountHandoff` + provenance index, materialised per `(client, account, icp segment)`.
- **M12.3 — output/handoff boundary** (`service.py` / `handoff_events.py` / `publisher.py` / `readiness.py` / `health.py`): the transport-agnostic read service (list / get / resolve-provenance), the durable `handoff_event` emit/notify outbox, the `HandoffPublisher` adapter seam (D2), the injected readiness seam (the M7 campaign-run phase), and per-handoff verification health (Doc C §6). The FastAPI HTTP surface itself lives at the `api` composition root (`api/handoff_app.py`) — `narrative` stays transport-agnostic.

## Modular boundary (M0.1 / ENG-101)

May import only `core/`, `config/`, and `obs/` from within `clue_research`. Components communicate by reading/writing typed **claims** in `claimstore/`, not by importing each other; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
