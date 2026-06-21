"""`clue_research.verification` — Verification Layer (M9).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M9.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M9 *implements* the ``PreSpendGate``,
``FaithfulnessJudge``, ``IdentityBindingGate`` and ``Freshness`` protocols from
:mod:`clue_research.core.verification` (the gates M5.1/M7/M8/M11 call). The M9-internal
``Corroborator``, the ``verify()`` umbrella and the eval harness stay in this package.

Implemented so far:

* **M9.1** (``pre_spend``) — :class:`PreSpendGateImpl` (the ``PreSpendGate`` impl),
  :func:`assemble_target_lock`, the :class:`PreSpendPolicy`/:class:`GateSpec` policy-as-data, and
  :func:`load_pre_spend_policy`.
* **M9.2** (``corroboration``) — :class:`Corroborator` (the deterministic ≥N-independent-tier≤3
  promotion + conflict-flag pass), :class:`EqualityMode`/:class:`CorroborationPolicy` (policy data),
  and the :class:`CorroborationResult`/:class:`ValueGroup` value types.
"""

from __future__ import annotations

from clue_research.verification.corroboration import (
    DEFAULT_CORROBORATION_POLICY,
    CorroborationPolicy,
    CorroborationResult,
    Corroborator,
    EqualityMode,
    ValueGroup,
    group_by_agreement,
    independent_source_count,
    values_agree,
)
from clue_research.verification.pre_spend import (
    DEFAULT_PRE_SPEND_POLICY,
    GateSpec,
    PreSpendGateImpl,
    PreSpendPolicy,
    assemble_target_lock,
    load_pre_spend_policy,
    parse_gate_spec,
    run_lock_token,
)

__all__ = [
    # M9.1 — pre-spend schema/identity gate
    "PreSpendGateImpl",
    "PreSpendPolicy",
    "DEFAULT_PRE_SPEND_POLICY",
    "GateSpec",
    "parse_gate_spec",
    "load_pre_spend_policy",
    "assemble_target_lock",
    "run_lock_token",
    # M9.2 — corroboration rules
    "Corroborator",
    "CorroborationPolicy",
    "DEFAULT_CORROBORATION_POLICY",
    "CorroborationResult",
    "ValueGroup",
    "EqualityMode",
    "values_agree",
    "group_by_agreement",
    "independent_source_count",
]
