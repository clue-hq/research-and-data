"""Target-lock — mode-M2 profiling's structural anti-hallucination constraint (M8.1).

The prototype's single research agent *drifted* to similarly-named orgs and fabricated facts.
M2 (account profiling) promotes "do not drift" from a prompt plea into a **structural** property of
the mode (staged-flow §5/§8): every account claim is pinned to the *resolved* entity, and a
synthesized (open-web / tier-4) claim whose evidence does not bind to that entity is rejected before
it counts as the aspect's output.

Two pure pieces, both over ``core`` types only (so this stays import-trivial and unit-testable
without a DB):

* :func:`build_target_lock` turns a resolved :class:`~clue_research.core.AccountEntity` into the
  shared :class:`~clue_research.core.TargetLock` context (canonical domain + identifiers + a
  no-drift
  instruction) — the same shape M9.1's ``PreSpendGate.assemble_target_lock`` produces, so the
  synthesis prompt and the post-fill validator read one lock.
* :func:`binds_to_entity` is the validator the M8.1 worker applies to drift-prone claims (tier ≥ 3):
  the claim's ``evidence_span`` / ``source_url`` must reference a *strong* identifier of **this**
  entity (its registrable domain, a registry id, or its canonical name co-occurring with a geo
  disambiguator). The bare canonical name is **not** sufficient — that is exactly the same-name trap
  (two companies share "Acme"; only the domain/registry-id/geo disambiguates).

Deterministic tiers (1–2: official APIs / the entity's own domain) are entity-scoped *by
construction* — the resolver was handed the resolved entity — so they need no binding check; the
drift risk is the open web (staged-flow §8). A tier-4 claim with **no** evidence span never binds
(and could never be promoted anyway — :func:`core.can_be_promoted`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import JsonValue

from clue_research.core import AccountEntity, Claim, TargetLock
from clue_research.identity import registrable_domain

# Open-web / synthesis tiers — where the prototype drifted (staged-flow §8). Tiers 1–2 are
# deterministic, entity-scoped by the resolver, so they are trusted to bind without a check.
_BINDING_CHECK_MIN_TIER = 3


def build_target_lock(account: AccountEntity) -> TargetLock:
    """Build the :class:`~clue_research.core.TargetLock` for a resolved account (M8.1).

    Mirrors M9.1's ``assemble_target_lock``: the canonical domain is the strong key, with the
    registry ids / canonical name / aliases / hq geo as the disambiguator bundle, plus a
    model-facing
    no-drift instruction for any tier-4 synthesis prompt. The lock binds to the account's *resolved*
    ``id`` — never a free-text name.
    """
    domain = registrable_domain(account.primary_domain) if account.primary_domain else None
    identifiers: dict[str, JsonValue] = {"canonical_name": account.canonical_name}
    if domain is not None:
        identifiers["primary_domain"] = domain
    if account.registry_ids:
        identifiers["registry_ids"] = dict(account.registry_ids)
    if account.aliases:
        identifiers["aliases"] = list(account.aliases)
    if account.hq_geo:
        identifiers["hq_geo"] = dict(account.hq_geo)
    no_drift = (
        f"Only assert facts about {account.canonical_name}"
        + (f" (official domain {domain})" if domain else "")
        + ". Reject any evidence about a similarly-named but different company; if the source does "
        "not clearly concern this exact entity, return nothing rather than guess."
    )
    return TargetLock(
        entity_id=account.id,
        no_drift_instruction=no_drift,
        canonical_domain=domain,
        identifiers=identifiers,
    )


def is_lockable(lock: TargetLock) -> bool:
    """Whether the entity carries a *strong enough* identifier to be target-locked at all.

    Lockable iff there is a domain, a registry id, **or** a canonical name plus a geo disambiguator.
    A name-only entity is **not** lockable (it cannot be disambiguated from a same-name stranger),
    so
    the worker refuses to spend open-web research on it and leaves the field empty/flagged — a
    correct output (staged-flow §8: better empty than a same-name fabrication).
    """
    ids = lock.identifiers
    if lock.canonical_domain:
        return True
    if ids.get("registry_ids"):
        return True
    return bool(ids.get("canonical_name") and ids.get("hq_geo"))


def requires_binding_check(claim: Claim) -> bool:
    """Whether a claim must be evidence-bound to the entity before it counts (tier ≥ 3 — the
    open-web / synthesis tiers where drift happens; staged-flow §8)."""
    return claim.source_tier >= _BINDING_CHECK_MIN_TIER


def _geo_tokens(geo: object) -> list[str]:
    # Skip ≤2-char tokens ("US"/"UK") — too short to disambiguate and prone to substring false-binds
    # (errs toward rejecting, the safe direction). A fuller geo match is an M9.6 follow-up.
    if not isinstance(geo, dict):
        return []
    out: list[str] = []
    for value in geo.values():
        if isinstance(value, (str, int, float)) and len(str(value).strip()) >= 3:
            out.append(str(value).strip().lower())
    return out


def _str_values(values: Iterable[object]) -> list[str]:
    return [str(v).strip().lower() for v in values if str(v).strip()]


def _host_present(domain: str, haystack_lower: str) -> bool:
    """Whether ``domain`` appears as a **complete registrable host**, not a substring of a longer
    one. The negative look-around on the DNS host charset ``[a-z0-9.-]`` blocks both left-prefix
    collisions (``notacme.com`` for ``acme.com``) and longer-suffix collisions (``acme.co.uk`` /
    ``acme.com.au`` for ``acme.co`` / ``acme.com``) that a bare substring test would false-bind on
    (``registrable_domain`` does no public-suffix reduction, so the raw test was unsafe)."""
    pattern = rf"(?<![a-z0-9.-]){re.escape(domain)}(?![a-z0-9.-])"
    return re.search(pattern, haystack_lower) is not None


def _token_present(token: str, haystack_lower: str) -> bool:
    """Whether ``token`` appears as a complete alphanumeric token (a registry id / geo token), not a
    substring of a longer one (``abc123`` must not bind in ``abc123456789``; ``york`` not in
    ``yorktown``)."""
    pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
    return re.search(pattern, haystack_lower) is not None


def _name_is_complete(name: str, cased: str) -> bool:
    """Whether ``name`` appears in ``cased`` (original case) as the **complete** org reference — a
    word-bounded match NOT immediately continued by another Capitalised word.

    Closes the same-name *prefix* trap (a word boundary alone does not: ``\\bAcme\\b`` matches in
    "Acme Robotics"). When the locked name is a strict prefix of a longer org name in the evidence
    ("Acme" vs "Acme Robotics"), the trailing ``\\s+[A-Z]`` lookahead rejects it; a name followed by
    punctuation, a lowercase word, or end-of-text ("Acme, in Boston" / "Acme is hiring") binds. The
    case check needs original-case text, so this reads ``cased``, erring toward reject."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"
    for m in re.finditer(pattern, cased, re.IGNORECASE):
        if not re.match(r"\s+[A-Z]", cased[m.end() :]):
            return True
    return False


def binds_to_entity(claim: Claim, lock: TargetLock) -> bool:
    """Whether ``claim``'s evidence binds it to the locked entity (the M8.1 target-lock validator).

    Deterministic-tier claims (1–2) are entity-scoped by their resolver and always bind. For a
    drift-prone claim (tier ≥ 3) the ``evidence_span`` / ``source_url`` must reference a *strong*
    identifier of this entity, matched on **token / host boundaries** (never a bare substring, which
    false-binds across related domains/ids/names):

    * its **registrable domain** as a complete host, or
    * one of its **registry ids** as a complete token, or
    * its **canonical name as the complete org reference** *and* a geo token (the name alone — or a
      name that is a *prefix* of a longer org name — is the same-name trap, insufficient).

    A tier-4 claim with no evidence at all never binds (it is unverifiable and unpromotable). A
    conservative validator: when the evidence does not clearly concern this exact entity it returns
    ``False`` (reject), never a guess — the same discipline the no-drift instruction asks of the
    LLM.
    """
    if not requires_binding_check(claim):
        return True

    cased = " ".join(s.strip() for s in (claim.source_url, claim.evidence_span) if s and s.strip())
    if not cased:
        return False  # tier ≥ 3 with no evidence cannot be bound
    haystack = cased.lower()

    if lock.canonical_domain and _host_present(lock.canonical_domain, haystack):
        return True

    registry_ids = lock.identifiers.get("registry_ids")
    if isinstance(registry_ids, dict) and any(
        _token_present(rid, haystack) for rid in _str_values(registry_ids.values())
    ):
        return True

    # Name + geo (the weakest fallback): the name must be the complete org reference (not a prefix
    # of a longer same-name org) AND a geo token must co-occur to disambiguate the same-name trap.
    name = lock.identifiers.get("canonical_name")
    geo = _geo_tokens(lock.identifiers.get("hq_geo"))
    return bool(
        isinstance(name, str)
        and _name_is_complete(name.strip(), cased)
        and any(_token_present(tok, haystack) for tok in geo)
    )


__all__ = [
    "build_target_lock",
    "is_lockable",
    "requires_binding_check",
    "binds_to_entity",
]
