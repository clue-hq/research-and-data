"""`clue_research.verification` — Verification Layer (M9).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M9.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M9 *implements* the ``PreSpendGate``,
``FaithfulnessJudge``, ``IdentityBindingGate`` and ``Freshness`` protocols from
:mod:`clue_research.core.verification` (the gates M5.1/M7/M8/M11 call). The M9-internal
``Corroborator``, the ``verify()`` umbrella and the eval harness stay in this package.
"""
