# `clue_research/stage0/` — Stage 0 Front Edge (M5)

**Spec:** [`docs/specs/M05-stage0-front-edge.md`](../../../docs/specs/M05-stage0-front-edge.md)

Stage 0 front edge: client reverse-profiling → versioned Client Knowledge Base (M5.1), ICP synthesis & proposal (M5.2), and the import + hybrid-lookalike entry scenarios (M5.3/M5.4). Stage 0 is the *seed of research* — every downstream direction is determined here.

## Status

- **M5.1 — reverse-profiling → versioned Client Knowledge Base — DONE.** `reverse_profile()` orchestration (`client_kb.py`), the `client.*` field set + Doc B §2 surface taxonomy (`fields.py`), the claim-native KB version ledger (the `client.kb_version` marker — no new table), the `ReverseProfilingHandler` (`PhaseHandler` for `REVERSE_PROFILING`), and the stage0-local tenant-private reuse policy (`reuse.py`).
- M5.2 / M5.3 / M5.4 — pending.

## Modular boundary (Beat-0 import-linter contract)

`stage0` is a milestone-worker package: it **may** import the shared base (`core`, `config`, `obs`, `db`) and the M1–M4 services (`claimstore`, `identity`, `icp`, `sources`) and the LLM `gateway`; it **may not** import a sibling milestone package (`discovery_scoring`, `durable`, `verification`, `profiling`, `narrative`, `compliance`, `synthesis`, `review`, `adapters`), the `resolvers` package, any provider SDK, or `api`. Components coordinate through the **claim store** (typed claims), not by importing each other.

Consequences honoured here:
- **M5↔M6 convergence is store-mediated** — M5 writes resolved candidate accounts as claims/`account_entity` rows; M6 scores them. Neither imports the other.
- **The M9 judge and M0.4 gateway are the frozen `core` protocols, injected** (never `clue_research.verification` / a vendor SDK). Concrete instances are wired at the `api` composition root, where `CampaignRun.register_phase_handler(ReverseProfilingHandler(...))` registers the phase handler.
- **The live Firecrawl/CRM resolver wiring** (a client-knowledge `ClaimExtractor` + `register_scrape_resolver`) is api-composition-root integration, since it needs `resolvers`/`adapters` types. The reverse-profiling *orchestration* drives the waterfall purely through the `sources` seam (`plan_sources`/`resolve_field`) and is tested by binding fakes via `sources.bind_resolver`.

The machine-enforced rule set is the `[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`); see [`docs/specs/_beat0-contract-freeze.md`](../../../docs/specs/_beat0-contract-freeze.md).
