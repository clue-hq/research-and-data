# M8 Track B → deep-profiling integration merge

**Date:** 2026-06-22 · **Result branch:** `m8/integrate-track-b` (local; **not pushed**) · merge commit `8839835`.
Builds on [[2026-06-22-m8-trackb-committee-contact-design]] (Track B build) and [[2026-06-22-m8-kickoff-handoff]] (the two-axis plan).

## What this was
Merge Track B (`m8/track-b-committee-contact` @ `32d139c` — M8.3 committee ENG-142 + M8.4 contact ENG-149) into the Track-A-merged integration tip `origin/m8/deep-profiling` @ `5217973` (M8.1 account + M8.2 resonance, PR#17). Merge base = the M8 seed `5922a56`.

## Branch mechanic (why not literally on `m8/deep-profiling`)
The local `m8/deep-profiling` branch is **checked out in the sibling `jerusalem` worktree** and is **stale** (still at the seed `5922a56`) — git refuses to check it out here, and moving another worktree's checked-out branch would corrupt its index. So the merge was done on a fresh branch `m8/integrate-track-b` created off `origin/m8/deep-profiling` (the real Track-A tip). **To promote:** `git push origin m8/integrate-track-b:m8/deep-profiling` (or fast-forward `m8/deep-profiling` to `8839835`). User owns the push.

## Conflicts (exactly two — confirmed by `merge-tree` before executing)
Resolved as a **pure union; no logic moved, no test file edited**:
1. `src/clue_research/profiling/__init__.py` — union of both axes' imports + `__all__` (39 exports). Zero symbol collisions; merged docstring.
2. `tests/profiling/conftest.py` (add/add) — **superset harness**. Kept Track A's auto-seeding `rollback_conn(*, seed_pack: bool = True)` (seeds core+deep **only**, not committee) + `require_db` + `conn_session_factory`; kept Track B's `seed_packs` (core+deep+committee) + `require_profiling_db` + doubles (`FakeCommitteeSource`/`FakeGateway`/`FakeFacetResolver`, `make_candidate`, `insert_test_account/contact`, `icp_spec`); kept ONE resolver-clear autouse fixture; `__all__` += `require_db`, `conn_session_factory`.
All other Track B files landed as disjoint adds (Track A = top-level modules; Track B = `committee/` + `contact/` subpackages).

## The one real tension and why the superset is safe (recon-verified)
Track A's DB tests call `rollback_conn()` zero-arg and **rely on auto-seed** (3 tests read seeded `account.resonance.employee_sentiment` without registering it). Track B's DB tests call `rollback_conn()` zero-arg then **seed explicitly**, and `committee/test_committee_fields.py` wants a clean DB to prove committee-pack registration. Keeping `seed_pack=True` default satisfies both because:
- **Pack loaders are idempotent** — `claimstore/registry.py::register_field` (line ~286) is read-then-conditional-insert; a 2nd registration of an identical def on the **same open transaction** (read-your-own-writes) is a no-op, never re-INSERTs, never raises. So Track B's later `seed_packs` over an auto-seeded conn is a harmless no-op (+committee fresh insert).
- **Auto-seed excludes committee**, and committee keys (`contact.role_on_committee`/`contact.persona`) are **disjoint** from core+deep keys, so `test_committee_fields`' direct `load_committee_pack` is still a genuine first-insert; its assertions are committee-key-specific (verified) → unaffected. `test_admission` asserts nothing about the field registry → inert.

## DRY / architecture (recon: do NOT unify in the merge)
Every cross-track overlap is parallel-by-design or a pre-flagged cross-package follow-up: SessionFactory alias (Track A `aspect_worker.py` vs Track B `runtime.py` vs `discovery_scoring`), `RunContext.from_params` vs inline `ctx.params` reads in Track B workers, `aspect_key_for`/`durable.planning._aspect_key` 3-way dup (hoist to `core.field`), `_first_json_object` / `normalize_host` repo-wide extractors. The two axes register **disjoint aspect keys** (`account`/`account.resonance` vs `committee`/`contact.facet`) → compose cleanly at the api root. None touched here.

## Verification (all green)
- `make check`: **804 passed / 604 skipped**; **import-contracts 11 kept / 0 broken**.
- Full profiling DB suite (both tracks) on the clean per-workspace DB `postgresql+asyncpg://clue:clue@localhost:55100/clue` (the `clue-pg-montpellier` container): **144 passed / 0 skipped** — the definitive coexistence proof (Track A auto-seed-dependent + Track B committee-only/admission under one conftest).
- Single alembic head `089dc65b5814`; **no new migrations**.
- Merge commit `8839835` has both parents (`5217973` + `32d139c`); nothing dropped vs either parent.

## api composition-root wiring — PARTIALLY LANDED (see [[2026-06-22-m8-api-composition-root]])
The core of the one coordination point now lives in `src/clue_research/api/composition.py`: `load_research_packs` (all packs + manifests), `build_worker_registry`/`build_profiling_workers` (both axes registered into the M7 `WorkerRegistry`), the `VerificationBindingClassifier` adapter (the M9.4×M8.4 born-binding stamp), and `build_pre_spend_gate` + injection into the account axis (M9.1). 8 `tests/api/` integration tests green (incl. the M9.4 born==verdict and M9.1 spend⇒gate-decision E2E). **Still deferred** (worker-internal/M7 changes, not pure composition): committee/contact pre-spend-gate seams (design-ambiguous keying), `durable.graph` campaign-coordinate param-threading, the campaign-run orchestration, the latent eval-fixture gap, and the DRY follow-ups above. Full detail + rationale in [[2026-06-22-m8-api-composition-root]].

## Not done (by policy / scope)
- **Not pushed**, no PR (local-only per CLAUDE.md; user promotes `m8/integrate-track-b` → `m8/deep-profiling`).
- **Linear** ENG-142/ENG-149 not touched this session (left In Progress with the build+audit comments) — offer to add an integration note if wanted.
