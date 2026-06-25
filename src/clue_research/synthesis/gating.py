"""M11.3 — the tier-4 synthesis **gating policy** (the governed layer's policy-as-code).

This module is the single, testable source of truth for the invariants that turn the M11.1/M11.2
tier-4 resolvers from raw providers into a *governed* layer (substrate §11 step 6 — "LLM research
agents as tier-4 field-fillers, behind the judge"):

* **what is a synthesis field** — a field a tier-4 M11 resolver (Exa Deep / Parallel Task) fills;
* **Pass-B-only** — a deep account-synthesis field is resolved ONLY in mode M2 (account profiling),
  never in Pass A scoring (Doc C §1 — deep narratives are computed on high-tier accounts in Pass B);
* **the account-only personal-data firewall** — a synthesis field handled by this path is
  account-class; tier-4 *contact* synthesis (``contact.facet.*``) is Doc D / M10's, never this path
  (Doc C §2, Doc D §7).

It is pure ``core``-typed policy. ``synthesis/`` may import only ``core``/``config``/``obs`` + the
M1–M4 services (``claimstore``/``sources``/``icp``/``identity``), never ``verification/`` or
``resolvers/`` (the worker-independence contract). So the **runtime** judge-gating pipeline
(``pre_spend → resolve → corroboration → faithfulness → promote``, the PF-7
``VERIFICATION_GATE_ORDER``) is composed at the ``api`` root, not here — this module names + guards
its *inputs*, and is the guard the composition root calls as defense-in-depth before the M11
synthesis path resolves a field. Two pieces of the gating are **already enforced by the substrate**
and are NOT re-implemented here:

* the merge view (M1.2) already excludes an unverified / judge-failed tier-4 claim from
  ``current_value`` (``MergePolicy.require_verified_tier4``); and
* the M11 resolvers already return ``[]`` for a contact entity / contact-class field (the firewall
  is structural at the source).

So a synthesized value reaches ``current_value`` only after the faithfulness judge (M9.3) marks it
``verified`` — empty/flagged is the correct output otherwise (substrate §6, conventions §5).
"""

from __future__ import annotations

from clue_research.core import (
    Claim,
    EntityType,
    FieldClass,
    FieldDef,
    ResearchMode,
    VerificationStatus,
)

# The tier-4 M11 synthesis providers (the source_keys whose presence in a field's tier_plan marks it
# as LLM-synthesis-filled). Adding a third tier-4 provider is one entry here — nothing else changes.
SYNTHESIS_SOURCE_KEYS: frozenset[str] = frozenset({"exa_deep", "parallel_task"})

# The field-classes the *account*-synthesis path may write — account-level, use-class-neutral.
# Mirrors the resolver's ``_ACCOUNT_SYNTHESIS_CLASSES`` (its structural firewall); the two packages
# cannot import each other (worker independence), so the set is declared in both — a one-shared-
# constant-in-core consolidation is a post-integration DRY item, like ``normalize_host``.
ACCOUNT_SYNTHESIS_CLASSES: frozenset[FieldClass] = frozenset(
    {FieldClass.CORE, FieldClass.ACCOUNT, FieldClass.ACCOUNT_RESONANCE, FieldClass.PACK}
)

# Mode M2 (account profiling) — the ONLY research_mode a deep account-synthesis field is resolved in
# (Pass B). Pass A scoring (M6) never touches a ``deep`` field, and contact profiling (mode M4) is
# M10's contact path — neither writes an account-synthesis claim.
PASS_B_MODE: ResearchMode = ResearchMode.ACCOUNT_PROFILING


class SynthesisGateError(ValueError):
    """A tier-4 synthesis-gating invariant was violated (Pass-B-only or the account-only firewall).

    Raised by the guards the composition root calls before the M11 synthesis path resolves a field;
    a programming/wiring error, never a normal "the fact doesn't exist" miss (that is an empty
    result, which is a *correct* output)."""


def is_synthesis_field(field: FieldDef) -> bool:
    """True if a tier-4 M11 synthesis resolver (Exa Deep / Parallel Task) is in ``field``'s
    ``tier_plan`` — i.e. this field is (partly) filled by LLM synthesis, the *least*-trusted source
    (substrate §4). The defining property; ``pass_kind == DEEP`` is an invariant of such fields
    (asserted in the M11.3 tests), not the test used here."""
    return any(key in SYNTHESIS_SOURCE_KEYS for key in field.tier_plan)


def is_account_synthesis_field(field: FieldDef) -> bool:
    """True if ``field`` is an **account-class** synthesis field — the M11 account-synthesis path's
    domain. A contact-class synthesis field (``contact.facet.*``) is governed by Doc D / M10, never
    written by this path (the personal-data firewall)."""
    return is_synthesis_field(field) and field.field_class in ACCOUNT_SYNTHESIS_CLASSES


def guard_account_only(field: FieldDef) -> None:
    """Personal-data firewall: refuse to run the account-synthesis path on a contact-class synthesis
    field. Tier-4 *contact* synthesis (``contact.facet.*``) is M10-governed (use-class tagging at
    extraction + the appropriateness/use gate + identity-binding), never this path (Doc C §2, Doc D
    §7). A no-op for a non-synthesis field (this path never sees it).

    Note: a ``PACK``-class field is treated as account-class here (``classify_field_key`` returns
    ``PACK`` for any vertical namespace, which has no safe scope default — ``core``), so this
    *field-level* guard alone cannot distinguish an account-pack from a (hypothetical) contact-pack
    synthesis field. The account-only guarantee for a pack field is **completed by the resolver's
    ``entity.entity_type is ACCOUNT`` check** (``resolvers.grounded``), which returns ``[]`` for any
    contact entity before the field-class test — so the two layers together hold the firewall."""
    if is_synthesis_field(field) and field.field_class not in ACCOUNT_SYNTHESIS_CLASSES:
        raise SynthesisGateError(
            f"{field.field_key!r} is a {field.field_class.value} (contact-class) synthesis field — "
            "tier-4 contact synthesis is governed by M10, not the account-synthesis path "
            "(the personal-data firewall)"
        )


def guard_pass_b(field: FieldDef, research_mode: ResearchMode) -> None:
    """Pass-B-only: a deep account-synthesis field is resolved ONLY in mode M2 (account profiling),
    never Pass A scoring (substrate §3 the ``deep`` tag; Doc C §1). A no-op for a non-account-
    synthesis field."""
    if is_account_synthesis_field(field) and research_mode is not PASS_B_MODE:
        raise SynthesisGateError(
            f"{field.field_key!r} is a deep account-synthesis field — it may be resolved only in "
            f"mode M2 ({PASS_B_MODE.value}), not {research_mode.value} (Pass-B-only)"
        )


def guard_synthesis_resolution(field: FieldDef, research_mode: ResearchMode) -> None:
    """The combined pre-resolution guard the ``api`` composition root calls before the M11 synthesis
    path resolves a field: the account-only firewall **and** Pass-B-only. (The live call site is the
    deferred api-root integration; this is the one tested source of truth for both invariants.)"""
    guard_account_only(field)
    guard_pass_b(field, research_mode)


def is_governed_synthesis_claim(claim: Claim) -> bool:
    """True if ``claim`` is a written **account-synthesis** claim (a tier-4 account claim) — the
    population the M11.3 invariants and the per-field verification-health surface (``health.py``)
    apply to. A tier-4 *contact* claim is M10's (excluded); a tier≤3 claim is not synthesis."""
    return claim.source_tier == 4 and claim.entity_type is EntityType.ACCOUNT


def assert_pass_b_claim(claim: Claim) -> None:
    """Defense-in-depth: a *written* account-synthesis claim must carry mode M2 (the Pass-B-only
    invariant, checked on the produced claim). Structurally already true — the M8 deep worker stamps
    ``research_mode=account_profiling`` — so this only ever fires on a wiring regression. A no-op
    for a non-account-synthesis claim."""
    if is_governed_synthesis_claim(claim) and claim.research_mode is not PASS_B_MODE:
        raise SynthesisGateError(
            f"account-synthesis claim {claim.id} for {claim.field_key!r} was written in mode "
            f"{claim.research_mode.value}, not mode M2 ({PASS_B_MODE.value}) — Pass-B-only violated"
        )


def synthesis_claim_is_promotable(claim: Claim) -> bool:
    """Whether a written account-synthesis claim has cleared the bar to be surfaced as current
    truth: the faithfulness judge (M9.3) marked it ``verified``. This RESTATES the M1.2 merge gate
    (``MergePolicy.require_verified_tier4``) at the field level for readability/eval — the merge
    view is the authoritative enforcer; an un-verified synthesis claim is correctly left
    empty/flagged."""
    return is_governed_synthesis_claim(claim) and (
        claim.verification_status is VerificationStatus.VERIFIED
    )
