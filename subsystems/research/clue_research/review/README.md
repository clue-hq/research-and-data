# `clue_research/review/` — Review, Feedback & Observability

**Status:** M13.1 (Tier-1 review surface) implemented; M13.2/M13.3/M13.4 pending.

**Spec:** [`docs/specs/M13-review-feedback-observability.md`](../../../docs/specs/M13-review-feedback-observability.md)

Tier-1 human review surface, disposition → training-data capture, the source-yield / scoring learning loop, and the client-facing cost & progress surface.

## Modular boundary (import-linter `independence` contract)

May import the shared base (`core/`, `config/`, `obs/`) **and the M1–M4 services** (`claimstore/`, `identity/`, `icp/`, `sources/`) — the ban is strictly worker→sibling-worker: `review` must **never** import `verification/`, `compliance/`, `discovery_scoring/`, `narrative/`, `durable/`, `profiling/`, `stage0/`, `synthesis/`, `adapters/`, or `resolvers/`. Cross-package results (e.g. faithfulness/use-gate verdicts, the campaign resume) arrive through injected `core` seams wired at the `api` composition root; workers return claim-id references, not blobs.

The full machine-enforced rule set lives in
[`docs/specs/M00-foundations-and-shared-contracts.md` §M0.1](../../../docs/specs/M00-foundations-and-shared-contracts.md)
and [`docs/specs/_conventions.md` §2](../../../docs/specs/_conventions.md); the executable form is the
`[tool.importlinter]` contracts in `pyproject.toml` (run `make contracts`).
