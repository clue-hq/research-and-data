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
* **M9.3** (``faithfulness``) — :class:`FaithfulnessJudgeImpl` (the LLM-as-judge claim-level
  entailment gate over tier-4 synthesized claims, the ``FaithfulnessJudge`` impl),
  :class:`JudgePolicy`/:func:`load_judge_policy` (policy data), and the pure
  :func:`parse_judge_response`/:func:`build_judge_messages`/:func:`status_for_verdict`/
  :func:`needs_re_retrieval` helpers.
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
from clue_research.verification.faithfulness import (
    DEFAULT_JUDGE_POLICY,
    PROMPT_VERSION,
    PROMPTS,
    FaithfulnessJudgeImpl,
    JudgePolicy,
    ParsedVerdict,
    build_judge_messages,
    load_judge_policy,
    needs_re_retrieval,
    parse_judge_response,
    status_for_verdict,
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
    # M9.3 — faithfulness judge
    "FaithfulnessJudgeImpl",
    "JudgePolicy",
    "DEFAULT_JUDGE_POLICY",
    "load_judge_policy",
    "ParsedVerdict",
    "build_judge_messages",
    "parse_judge_response",
    "status_for_verdict",
    "needs_re_retrieval",
    "PROMPT_VERSION",
    "PROMPTS",
]
