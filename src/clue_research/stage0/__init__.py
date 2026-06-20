"""`clue_research.stage0` — Stage 0 Front Edge (M5).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M5.

Beat-0 froze the cross-milestone seam in ``core`` (see ``docs/specs/_beat0-contract-freeze.md``):
M5's ``REVERSE_PROFILING``/``ICP_CONFIRMED`` phases *implement* ``PhaseHandler`` from
:mod:`clue_research.core.execution`, and M5.1 calls the M9 ``FaithfulnessJudge`` (the
:mod:`clue_research.core.verification` protocol, injected) for tier-4 client claims. Imports and
lookalike seeds reach M6 through the claim store — M5 imports no sibling milestone package.
"""
