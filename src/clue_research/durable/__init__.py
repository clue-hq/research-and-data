"""`clue_research.durable` — Durable Execution (M7).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M7.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M7 *implements* the ``PhaseHandler`` dispatch,
``AspectWorker`` spawning and ``BudgetEngine`` from :mod:`clue_research.core.execution`, and uses
the pure key helpers in :mod:`clue_research.core.idempotency`. It imports those contracts from
``core``, never the phase packages — concrete handlers are registered at the ``api`` root.
"""
