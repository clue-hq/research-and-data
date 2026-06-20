"""`clue_research.discovery_scoring` — Discovery (mode M1) + Pass A Scoring (M6).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M6.

Beat-0 froze the cross-milestone seam in ``core`` (see ``docs/specs/_beat0-contract-freeze.md``):
M6's ``DISCOVERY``/``SCORING``/``TIER_CHECKPOINT`` phases *implement* ``PhaseHandler`` from
:mod:`clue_research.core.execution` (the checkpoint pauses via ``PhaseResult(status=PAUSED)``), the
Pass-A scorer returns ``core.Score``, and budget checks call the injected ``BudgetEngine``. Imported
accounts (M5) converge here through the claim store, not an import — M6 imports no sibling package.
"""
