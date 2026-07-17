"""`clue_research.verification` — Verification Layer (M9).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M9.

Beat-0 froze this package's cross-milestone seam in ``core`` (see
``docs/specs/_beat0-contract-freeze.md``): M9 *implements* the ``PreSpendGate``,
``FaithfulnessJudge``, ``IdentityBindingGate`` and ``Freshness`` protocols from
:mod:`clue_core.verification` (the gates M5.1/M7/M8/M11 call). The M9-internal
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
* **M9.4** (``identity_binding``) — :class:`IdentityBindingGateImpl` (the strong-vs-weak
  contact-claim gate, the ``IdentityBindingGate`` impl), :class:`BindingPolicy`/
  :func:`load_binding_policy` (policy data), and the pure
  :func:`classify_binding`/:func:`handle_matches`/:func:`count_identifier_matches`/
  :func:`strength_from_signals` helpers.
* **M9.5** (``freshness``) — :class:`FreshnessImpl` (the freshness TTL engine + re-research cadence,
  the ``Freshness`` impl), :class:`CadencePolicy`/:func:`load_cadence_policy` (policy data), the
  :class:`AgeOutCandidate` value type, and the pure :func:`staleness`/:func:`reference_time`/
  :func:`retention_horizon_for` helpers.
* **M9.6** (``eval_harness`` + ``golden``) — the eval battery filling the M0.6 ``evals`` scaffold:
  :class:`VerificationEvalHarness`, the five pure mechanism metrics (:func:`gate_block_metric`/
  :func:`corroboration_metric`/:func:`faithfulness_metric`/:func:`identity_binding_metric`/
  :func:`freshness_metric`), the :func:`check_regressions` CI gate, the :class:`GatewayJudge`
  (M9.3-backed LLM judge), the hand-verified :func:`verification_gold_pack` + ``golden_fixture``
  round-trip, ``eval_run`` persistence, and the human spot-check sampler.
"""

from __future__ import annotations

# EqualityMode relocated to ``core`` (M9.2×M1.2 — merge/corroborator shared equality); re-exported.
# reference_time likewise relocated to ``core`` (M9.5 DRY consolidation — one merge/freshness fold).
from clue_core import AgeOutCandidate, EqualityMode, reference_time
from clue_research.verification.corroboration import (
    DEFAULT_CORROBORATION_POLICY,
    CorroborationPolicy,
    CorroborationResult,
    Corroborator,
    ValueGroup,
    group_by_agreement,
    independent_source_count,
    values_agree,
)
from clue_research.verification.eval_harness import (
    METRIC_EVAL_MECHANISM_RECALL,
    METRIC_EVAL_REGRESSIONS,
    METRIC_EVAL_RUBRIC_PASS_RATE,
    GatewayJudge,
    SpotCheckSample,
    VerificationEvalHarness,
    check_regressions,
    corroboration_metric,
    faithfulness_metric,
    freshness_metric,
    gate_block_metric,
    identity_binding_metric,
    ingest_spot_check,
    record_eval_run,
    regression_exit_code,
    sample_promoted_claims,
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
from clue_research.verification.freshness import (
    DEFAULT_CADENCE_POLICY,
    METRIC_FRESHNESS_DUE,
    METRIC_FRESHNESS_EXPIRED,
    METRIC_FRESHNESS_SCANNED,
    METRIC_FRESHNESS_STALE,
    CadencePolicy,
    FreshnessImpl,
    load_cadence_policy,
    retention_horizon_for,
    staleness,
)
from clue_research.verification.golden import (
    GOLD_SUITE,
    GoldPack,
    ingest_golden_fixture,
    load_golden_fixtures,
    seed_golden_fixtures,
    verification_gold_pack,
)
from clue_research.verification.identity_binding import (
    DEFAULT_BINDING_POLICY,
    SUPPORTED_IDENTIFIER_KINDS,
    BindingPolicy,
    IdentityBindingGateImpl,
    classify_binding,
    count_identifier_matches,
    handle_matches,
    load_binding_policy,
    normalize_url,
    strength_from_signals,
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
    # M9.4 — identity-binding gate
    "IdentityBindingGateImpl",
    "BindingPolicy",
    "DEFAULT_BINDING_POLICY",
    "SUPPORTED_IDENTIFIER_KINDS",
    "load_binding_policy",
    "classify_binding",
    "handle_matches",
    "count_identifier_matches",
    "strength_from_signals",
    "normalize_url",
    # M9.5 — freshness TTL engine + re-research cadence
    "FreshnessImpl",
    "CadencePolicy",
    "DEFAULT_CADENCE_POLICY",
    "AgeOutCandidate",
    "load_cadence_policy",
    "staleness",
    "reference_time",
    "retention_horizon_for",
    "METRIC_FRESHNESS_SCANNED",
    "METRIC_FRESHNESS_STALE",
    "METRIC_FRESHNESS_EXPIRED",
    "METRIC_FRESHNESS_DUE",
    # M9.6 — eval harness + golden set + rubric scoring
    "VerificationEvalHarness",
    "GatewayJudge",
    "check_regressions",
    "regression_exit_code",
    "gate_block_metric",
    "corroboration_metric",
    "faithfulness_metric",
    "identity_binding_metric",
    "freshness_metric",
    "verification_gold_pack",
    "GoldPack",
    "GOLD_SUITE",
    "seed_golden_fixtures",
    "load_golden_fixtures",
    "ingest_golden_fixture",
    "record_eval_run",
    "SpotCheckSample",
    "sample_promoted_claims",
    "ingest_spot_check",
    "METRIC_EVAL_RUBRIC_PASS_RATE",
    "METRIC_EVAL_MECHANISM_RECALL",
    "METRIC_EVAL_REGRESSIONS",
]
