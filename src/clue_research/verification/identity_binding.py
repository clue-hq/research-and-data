"""M9.4 — the identity-binding gate: strong vs weak (ENG-144).

The evidence-span rule kills fabrication for *account* facts (M9.3); the **identity-binding gate**
is its *contact-axis* analogue (staged-flow §6/§9). For a personal claim, getting the person *wrong*
in 1:1 outreach is worse than omitting it, so every contact claim carries an ``identity_binding``
strength — **strong** (evidence on the contact's *verified* profile/handle, or ≥K co-occurring
strong identifiers bound to *this* person) or **weak** (the same-name trap). **A weak-bound claim
never promotes and never drives outreach** — better an empty hook than someone else's fact.

:class:`IdentityBindingGateImpl` implements the Beat-0 :class:`clue_core.verification.
IdentityBindingGate` protocol, so callers in other milestone packages (M8.4 contact profiling,
M8.5 ``contact.facet.*``) depend only on the ``core`` seam; the concrete gate is injected at the
``api`` composition root.

**The load-bearing constraint — ``claim.identity_binding`` is immutable, born-stamped provenance.**
It is set at insert (the M4 waterfall stamps the ``source_manifest`` prior; the DB CHECK
``claim_contact_field_requires_governance`` requires it for ``contact.facet.*``) and the 0004
trigger forbids any in-place change (the allow-list is only ``superseded_by/verification_status/
corroborations``). That immutable column is the *authoritative exclusion signal*:
:func:`clue_research.claimstore.merge._is_eligible` drops weak-bound contact claims from
``current_value`` and :func:`clue_core.can_be_promoted` blocks their promotion — both read
the column, not a status. So the gate's job is **not** to rewrite the column but to make it
*authoritative* and to audit/enforce around it. Two surfaces:

* :func:`classify_binding` — the **pure** authoritative classifier. M8.4/M8.5 call it *before
  insert* and stamp ``binding.strength`` as the claim's ``identity_binding`` (born-correct and
  immutable thereafter), upgrading the waterfall's source-prior stamp to a per-claim classification.
* :meth:`IdentityBindingGateImpl.classify` — reads the resolved contact + parent-account name + the
  source prior, calls :func:`classify_binding`, records the append-only ``identity_binding_eval``
  audit row, drives a **defensive** status backstop, and emits the ``verification.identity_binding``
  span + the Doc C §6 "share at strong binding" metric. The backstop touches only the *mutable*
  ``verification_status`` (via :func:`clue_research.claimstore.record_verification`): a claim it
  classifies ``weak`` whose born column wrongly leaves it promotable is set ``rejected`` so it
  cannot ride into the usable set. A ``contact.facet.*`` claim born ``weak`` is already excluded by
  the immutable column, so its status is left ``unverified`` (spec: "never advance past
  unverified"). NOTE the column is the durable guarantee only when it is ``weak``: a plain
  ``contact.*`` (non-facet) claim is allowed to be born with ``identity_binding=None`` (the DB CHECK
  requires a binding only for ``contact.facet.*``), and for *that* claim the gate's ``rejected``
  backstop is the *only* exclusion mechanism (the column carries no signal) — so it must run. A
  ``strong`` claim's status is untouched — it stays eligible for M9.2/M9.3.

The gate is **policy-as-data** (conventions §2): ``min_identifiers_k``, the
``strong_identifier_set``, and the same-name-guard flags are versioned :class:`BindingPolicy` rows
in ``binding_policy`` (per-client overridable; read via :func:`load_binding_policy`), so raising K
or changing the identifier set is a config change — regression-checked by the M9.6 eval battery.
M10's appropriateness/use gate runs **after** this gate on strong-bound claims only (Doc D §7
ordering); this issue exposes the seam (the binding decision), M10 plugs in.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Binding,
    Claim,
    ClaimFlavor,
    ClaimId,
    ContactEntity,
    EntityType,
    IdentityBinding,
    VerificationStatus,
    can_be_promoted,
    decode_jsonb,
    decode_jsonb_scalar,
    serialize_value_json,
)
from clue_core.entity import AccountEntity
from clue_research.claimstore import record_verification
from clue_research.db import ConnFactory, transaction
from clue_research.identity import get_account, get_contact
from clue_research.obs import (
    ATTR_CACHE_HIT,
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_SOURCE_TIER,
    SPAN_VERIFICATION_IDENTITY_BINDING,
    MetricSink,
    apply_attributes,
    get_logger,
    get_metric_sink,
    traced_step,
)

_log = get_logger(__name__)

# Verification-health metrics (Doc C §6 — "share of personal claims at strong binding"). M9-local
# metric name strings (the shared sink accepts any string), defined here so M9.4 stays self-
# contained and never edits the shared obs/metrics.py. The share is ``strong / classifications``;
# ALL three are skipped on a cache replay (an idempotent re-classification) so the ratio stays exact
# (a deliberate, documented divergence from M9.3, which counts ``judgments`` on every call/replay).
#
# NOTE: this is the *live, per-classification* view of the Doc C §6 "strong-binding share". The
# pre-existing ``obs.metrics.record_verification_health`` (``research.verification.contact.{total,
# strong_binding}``) is the *at-rest* view — a batch column-scan over a claim set (M13.4-facing).
# They are two views of the same quantity (live verdict vs. born immutable column) and MUST NOT be
# summed; a consumer picks one. (Reconciling them onto one surface is a backlog item.)
METRIC_IDENTITY_BINDING_CLASSIFICATIONS = "research.verification.identity_binding.classifications"
METRIC_IDENTITY_BINDING_STRONG = "research.verification.identity_binding.strong"
METRIC_IDENTITY_BINDING_WEAK = "research.verification.identity_binding.weak"

# The strong-identifier kinds the per-claim classifier can actually verify against the resolved
# entities (criterion 2). The M09 spec also names ``role``, but a contact's role lives on an
# ``(account, persona)`` committee claim (M2/M8), not on ``contact_entity`` — so ``role`` is NOT
# counted here (it would need a cross-milestone read); a config that lists it is logged + inert.
SUPPORTED_IDENTIFIER_KINDS: frozenset[str] = frozenset({"full_name", "employer", "geo"})

# M9-local span attribute keys (plain strings; the shared ATTR_* cover entity/field/tier/cache_hit).
# Short non-token values (an enum string, a 0..1 float, a bool) pass the obs redaction value-shape
# heuristic; a raw claim_id UUID would not, so the claim is identified on the span by entity/field/
# tier and linked precisely via the identity_binding_eval row's claim_id.
ATTR_BINDING_STRENGTH = "verification.identity_binding.strength"
ATTR_BINDING_SCORE = "verification.identity_binding.score"
ATTR_BINDING_HANDLE_MATCH = "verification.identity_binding.handle_match"


# --- policy-as-data ---------------------------------------------------------


class BindingPolicy(BaseModel):
    """The identity-binding config as data (policy-as-data, conventions §2). Persisted as typed
    columns in ``binding_policy`` (per-client overridable); the gate reads it at construction.
    Changing K or the identifier set is a config change, regression-checked by M9.6.

    * ``min_identifiers_k`` — criterion-2 threshold: ``strong`` needs ≥K of the configured strong
      identifiers co-occurring in the evidence span (the same-name trap defeats a name-only match).
    * ``strong_identifier_set`` — which identifier kinds count toward K. Supported: ``full_name``
      (contact name/aliases), ``employer`` (parent-account name/aliases), ``geo`` (contact
      location). An unsupported/unavailable kind (e.g. ``role`` — not an entity column) never fires.
    * ``verified_handle_sufficient`` — a verified-handle match alone is ``strong`` (criterion 1).
    * ``weak_source_requires_handle`` — a source whose ``source_manifest`` binding prior is **not
      explicitly ``strong``** (i.e. ``weak`` OR undeclared/``NULL``) cannot reach ``strong`` on
      identifier-count alone (it needs a handle match): a name+employer mention on a low-binding /
      unknown open-web page is exactly the same-name trap, and the least-trusted tier-4 open-web
      sources carry no prior — so "fail closed on an unknown prior" (design for the strict case)
      keeps that path from forging a strong binding from attacker-controllable text.
    * ``policy_version`` — the row ``version``, recorded on each audit row and folded into the cache
      :meth:`fingerprint`; bumping it forces a fresh classification.

    The ``identity_binding_eval`` cache is keyed on :meth:`fingerprint` (a hash of the *whole*
    policy content), NOT on ``policy_version`` alone — so an in-place edit of a ``binding_policy``
    row (a new K, a changed identifier set) re-classifies even if the operator forgets to bump the
    version (mirroring M9.3 keying its judge cache on the model id, the content that decides).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_identifiers_k: int = Field(default=2, ge=1)
    strong_identifier_set: tuple[str, ...] = ("full_name", "employer", "geo")
    verified_handle_sufficient: bool = True
    weak_source_requires_handle: bool = True
    policy_version: int = Field(default=1, ge=1)

    def fingerprint(self) -> str:
        """A stable content hash of the policy (the ``identity_binding_eval`` cache key, with
        ``claim_id``). Two policies that differ in ANY classification-affecting field — or in
        ``policy_version`` — get different fingerprints, so a re-classification under changed config
        is a cache miss (fresh verdict + a new audit row), never a stale replay."""
        payload = json.dumps(
            {
                "k": self.min_identifiers_k,
                "set": sorted(self.strong_identifier_set),
                "vhs": self.verified_handle_sufficient,
                "wsrh": self.weak_source_requires_handle,
                "v": self.policy_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_BINDING_POLICY = BindingPolicy()


# --- pure helpers (DB-free, unit-testable) ----------------------------------


def normalize_url(url: str | None) -> str | None:
    """Normalize a URL to ``host/path`` for handle comparison: lowercase host (``www.`` stripped),
    lowercase path with the trailing slash dropped, query/fragment discarded. ``None`` for an
    empty/host-less input.

    Scheme-less and doubled-slash URLs are handled by a two-pass parse (``urlsplit(url).hostname``,
    else ``urlsplit('//' + url).hostname``) — the single ``'//' in url`` heuristic would mis-parse
    ``acme.com/a//b`` (it contains ``//`` yet has no scheme) as path-only and drop the host. (DRY
    note: ``corroboration._host`` does the same host folding; consolidating both onto one shared
    normalizer is a backlog item.)"""
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.hostname or urlsplit("//" + url).hostname or ""
    host = host.lower().removeprefix("www.")
    if not host:
        return None
    # Re-derive the path from whichever parse found the host (so a scheme-less input keeps it).
    path = (parts.path if parts.hostname else urlsplit("//" + url).path).rstrip("/").lower()
    return host + path


def handle_matches(claim: Claim, contact: ContactEntity) -> bool:
    """Whether the claim's evidence is on the contact's *verified* handle (criterion 1).

    True when the claim's ``source_url`` IS the contact's verified ``linkedin_url`` (or a sub-path
    of it — a separator-anchored prefix on a profile that has a real path, so a bare-host or
    prefix-sharing profile never matches an arbitrary path), OR the contact's ``verified_email``
    appears (token-bounded) in the ``source_url`` itself. The strongest signal — the evidence lives
    at the person's own verified profile (the LinkedIn URL / verified email M2 resolved on).

    The email is matched only against ``source_url`` (where the evidence *lives*), NOT the
    ``evidence_span`` body: span text is attacker-controllable tier-4 open-web content, and "contact
    jane@acme.com" printed on a page about *someone else* must not forge a strong handle match. A
    handle match short-circuits to ``strong``, so it has to key on non-forgeable location, not
    content."""
    src = normalize_url(claim.source_url)
    profile = normalize_url(contact.linkedin_url)
    # The prefix arm requires the profile to carry a real path segment (``"/" in profile``), so a
    # malformed bare-host ``linkedin_url`` can only match an exact host, never an arbitrary
    # ``/in/someone-else`` on that host.
    if (
        src is not None
        and profile is not None
        and (src == profile or ("/" in profile and src.startswith(profile + "/")))
    ):
        return True
    email = (contact.verified_email or "").lower().strip()
    return bool(email and _token_present((claim.source_url or "").lower(), email))


def _geo_strings(geo: object) -> list[str]:
    """The human-readable location strings in a contact's ``geo`` dict (city/region/country values),
    skipping country/region *codes* (≤3 chars) that would word-boundary-match noise."""
    if not isinstance(geo, dict):
        return []
    out: list[str] = []
    for value in geo.values():
        if isinstance(value, str) and len(value.strip()) > 3:
            out.append(value)
    return out


def _identifier_values(
    kind: str,
    contact: ContactEntity,
    *,
    account_name: str | None,
    account_aliases: Sequence[str],
) -> list[str]:
    """The candidate strings for one strong-identifier ``kind``, bound to *this* contact. An
    unsupported/unavailable kind (e.g. ``role`` — not an entity column) yields nothing (it never
    contributes to the count), which is honest: we count only identifiers we can actually verify."""
    if kind == "full_name":
        values: list[str] = [contact.full_name or "", *contact.aliases]
    elif kind == "employer":
        values = [account_name or "", *account_aliases]
    elif kind == "geo":
        values = _geo_strings(contact.geo)
    else:
        values = []
    return [v for v in values if v and len(v.strip()) >= 2]


def _token_present(haystack: str, needle: str) -> bool:
    """Word-boundary, case-insensitive containment of ``needle`` in ``haystack`` (so ``"Al"`` does
    not match inside ``"Alabama"`` and ``"Acme"`` matches ``"...at Acme Corp"``). Whitespace in a
    multi-word needle is collapsed to a single literal space."""
    needle = re.sub(r"\s+", " ", needle.strip())
    if len(needle) < 2:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", haystack, re.IGNORECASE) is not None


def count_identifier_matches(
    span: str,
    contact: ContactEntity,
    *,
    account_name: str | None,
    account_aliases: Sequence[str],
    identifier_set: Sequence[str],
) -> tuple[int, list[str]]:
    """Count which of ``identifier_set`` co-occur with *this* contact in ``span`` (criterion 2).

    One kind counts at most once (even if several of its values match); returns the count and the
    matched kinds (for the audit signals). Matching is over the cited ``evidence_span`` only — "the
    evidence co-occurs with ≥K identifiers bound to this contact" (M09 §M9.4)."""
    matched: list[str] = []
    for kind in identifier_set:
        values = _identifier_values(
            kind, contact, account_name=account_name, account_aliases=account_aliases
        )
        if any(_token_present(span, value) for value in values):
            matched.append(kind)
    return len(matched), matched


def strength_from_signals(
    *,
    handle_match: bool,
    verified_handle_sufficient: bool,
    identifier_count: int,
    k: int,
    prior: IdentityBinding | None,
    weak_source_requires_handle: bool,
    non_name_identifier: bool = True,
) -> tuple[IdentityBinding, float]:
    """The binary binding strength + a 0..1 confidence score from the fired signals (pure).

    ``strong`` iff a verified-handle match (criterion 1, when ``verified_handle_sufficient``) OR ≥K
    co-occurring identifiers (criterion 2), subject to two same-name guards:

    * a **name-only** match is never strong — the spec's ``weak`` is "name match only", so criterion
      2 requires at least one *corroborating* identifier beyond the name (``non_name_identifier``;
      e.g. employer or geo). ``{full_name}`` alone is ``weak`` at any K.
    * a source whose ``prior`` is **not explicitly ``strong``** (``weak`` OR undeclared/``None``)
      cannot reach strong on identifiers alone — it needs a handle (the least-trusted tier-4
      open-web sources carry no prior; fail closed on an unknown prior — for the strict case).

    The prior **informs, not overrides** (M09 §M9.4): it cannot make a handle-less, identifier-poor
    claim strong, and it halves the score of an identifier-only match from a non-trusted source.
    ``score``: 1.0 for a *sufficient* verified-handle match; else the K-coverage ``min(1,count/K)``,
    halved when the source prior is not ``strong`` (a non-sufficient handle does NOT inflate it)."""
    meets_k = k > 0 and identifier_count >= k
    coverage = min(1.0, identifier_count / k) if k > 0 else 0.0
    trusted_prior = prior is IdentityBinding.STRONG

    handle_strong = handle_match and verified_handle_sufficient
    blocked_untrusted_source = (
        weak_source_requires_handle and not trusted_prior and not handle_match
    )
    identifier_strong = meets_k and non_name_identifier and not blocked_untrusted_source
    strong = handle_strong or identifier_strong

    if handle_strong:
        score = 1.0
    elif trusted_prior or handle_match:
        score = coverage
    else:
        score = coverage * 0.5
    return (IdentityBinding.STRONG if strong else IdentityBinding.WEAK), round(score, 6)


def classify_binding(
    claim: Claim,
    contact: ContactEntity | None,
    *,
    account_name: str | None = None,
    account_aliases: Sequence[str] = (),
    manifest_prior: IdentityBinding | None = None,
    policy: BindingPolicy = DEFAULT_BINDING_POLICY,
) -> Binding:
    """Classify one contact claim ``strong`` vs ``weak`` (the pure authoritative classifier).

    DB-free: the caller supplies the resolved ``contact`` (and, for the ``employer`` identifier, the
    parent account's name/aliases) and the source prior. M8.4/M8.5 call this *before insert* to
    stamp the claim's ``identity_binding``; the gate calls it after reading those rows. An
    unresolved ``contact`` (``None``) → ``weak``, score 0 (we cannot confirm it is this person).
    ``contact_entity_id`` is the claim's own ``entity_id`` (a contact claim's entity IS the
    contact)."""
    base_signals: dict[str, object] = {
        "min_identifiers_k": policy.min_identifiers_k,
        "source_prior": manifest_prior.value if manifest_prior is not None else None,
    }
    if contact is None:
        signals = {
            **base_signals,
            "contact_resolved": False,
            "verified_handle_match": False,
            "identifier_count": 0,
            "identifier_matches": [],
        }
        return Binding(
            claim_id=claim.id,
            contact_entity_id=claim.entity_id,
            strength=IdentityBinding.WEAK,
            strength_score=0.0,
            signals=signals,  # type: ignore[arg-type]
        )

    handle_match = handle_matches(claim, contact)
    count, matched = count_identifier_matches(
        claim.evidence_span or "",
        contact,
        account_name=account_name,
        account_aliases=account_aliases,
        identifier_set=policy.strong_identifier_set,
    )
    non_name_identifier = any(kind != "full_name" for kind in matched)
    strength, score = strength_from_signals(
        handle_match=handle_match,
        verified_handle_sufficient=policy.verified_handle_sufficient,
        identifier_count=count,
        k=policy.min_identifiers_k,
        prior=manifest_prior,
        weak_source_requires_handle=policy.weak_source_requires_handle,
        non_name_identifier=non_name_identifier,
    )
    signals = {
        **base_signals,
        "contact_resolved": True,
        "verified_handle_match": handle_match,
        "identifier_count": count,
        "identifier_matches": matched,
    }
    return Binding(
        claim_id=claim.id,
        contact_entity_id=claim.entity_id,
        strength=strength,
        strength_score=score,
        signals=signals,  # type: ignore[arg-type]
    )


# --- the IdentityBindingGate ------------------------------------------------


class IdentityBindingGateImpl:
    """The M9.4 identity-binding gate (implements :class:`clue_core.verification.
    IdentityBindingGate`).

    Constructed with the resolved :class:`BindingPolicy`, a connection factory (defaults to a
    committed transaction per classify), and an optional metric sink. Injected at the ``api``
    composition root; per-client policy is loaded via :func:`load_binding_policy`."""

    def __init__(
        self,
        *,
        policy: BindingPolicy = DEFAULT_BINDING_POLICY,
        conn_factory: ConnFactory = transaction,
        record_evals: bool = True,
        sink: MetricSink | None = None,
    ) -> None:
        self._policy = policy
        self._conn_factory = conn_factory
        self._record = record_evals
        self._sink = sink

    async def classify(self, claim: Claim) -> Binding:
        """Classify ``claim``'s identity binding; record the ``identity_binding_eval`` audit row,
        drive the defensive ``verification_status`` backstop, and emit the
        ``verification.identity_binding`` span. Idempotent on ``(claim_id, policy_fingerprint)`` — a
        re-classify under the *same policy content* returns the cached binding and writes no row; a
        changed policy (new K / identifier set / version) misses → a fresh verdict + a new row.

        Runs **only** on contact field claims: an account claim or a discovery-flavored claim is a
        programming error (binding is contact field-claim provenance — account claims untouched,
        M09 §M9.4 acceptance), so it raises rather than silently no-op'ing."""
        if claim.entity_type is not EntityType.CONTACT:
            raise ValueError(
                "identity-binding classifies CONTACT claims only; account claims are untouched "
                "(M9.4 — the gate runs only on contact.*)"
            )
        if claim.claim_flavor is ClaimFlavor.DISCOVERY:
            raise ValueError(
                "identity-binding classifies contact FIELD claims, not discovery-provenance claims "
                "(binding is field-claim provenance for personal data — staged-flow §6/§9)"
            )
        fingerprint = self._policy.fingerprint()
        with traced_step(
            SPAN_VERIFICATION_IDENTITY_BINDING,
            **{
                ATTR_ENTITY_ID: str(claim.entity_id),
                ATTR_FIELD_KEY: str(claim.field_key),
                ATTR_SOURCE_TIER: int(claim.source_tier),
            },
        ) as span:
            async with self._conn_factory() as conn:
                cached = await self._load_cached(conn, claim.id, fingerprint)
                if cached is not None:
                    # Idempotent replay: the binding + status backstop were applied on the first
                    # classification; re-running makes no new row and no status re-write.
                    binding, cache_hit = cached, True
                else:
                    contact = await get_contact(conn, claim.entity_id)
                    account_name, account_aliases = await self._account_identifiers(conn, contact)
                    prior = await self._source_prior(conn, claim.source_key)
                    binding = classify_binding(
                        claim,
                        contact,
                        account_name=account_name,
                        account_aliases=account_aliases,
                        manifest_prior=prior,
                        policy=self._policy,
                    )
                    if self._record:
                        await self._insert_eval(conn, binding, fingerprint)
                        await self._enforce_status(conn, claim, binding)
                    cache_hit = False
            apply_attributes(
                span,
                {
                    ATTR_BINDING_STRENGTH: binding.strength.value,
                    ATTR_BINDING_SCORE: binding.strength_score,
                    ATTR_BINDING_HANDLE_MATCH: bool(binding.signals.get("verified_handle_match")),
                    ATTR_CACHE_HIT: cache_hit,
                },
            )
            self._emit_metrics(str(claim.field_key), binding, cache_hit=cache_hit)
            return binding

    async def _account_identifiers(
        self, conn: AsyncConnection, contact: ContactEntity | None
    ) -> tuple[str | None, tuple[str, ...]]:
        """The parent account's name + aliases for the ``employer`` identifier — read only when the
        contact resolved *and* ``employer`` is a counted identifier (skip the read otherwise)."""
        if contact is None or "employer" not in self._policy.strong_identifier_set:
            return None, ()
        account: AccountEntity | None = await get_account(conn, contact.account_entity_id)
        if account is None:
            return None, ()
        return account.canonical_name, account.aliases

    async def _source_prior(
        self, conn: AsyncConnection, source_key: str | None
    ) -> IdentityBinding | None:
        """The producing source's inherent binding prior (``source_manifest.identity_binding_
        strength``) — informs, never overrides. Read by raw SQL (one column), mirroring
        ``pre_spend._covered_tiers``, so verification never imports the ``sources`` package."""
        if not source_key:
            return None
        row = (
            await conn.execute(
                text("SELECT identity_binding_strength FROM source_manifest WHERE source_key = :k"),
                {"k": source_key},
            )
        ).first()
        if row is None or row[0] is None:
            return None
        return IdentityBinding(row[0])

    async def _enforce_status(self, conn: AsyncConnection, claim: Claim, binding: Binding) -> None:
        """Drive the defensive ``verification_status`` backstop for a contact claim.

        A ``weak`` claim must never enter the usable set. For a claim born ``WEAK`` (a
        ``contact.facet.*`` claim — the DB CHECK requires a non-null binding there), the durable
        guarantee is the immutable ``identity_binding`` column (``merge._is_eligible`` /
        ``can_be_promoted`` exclude it with no status change), so its status is left ``unverified``
        (spec: "never advance past unverified"). The backstop fires whenever the gate classifies
        ``weak`` but the born column leaves the claim promotable — i.e. **drift** (born ``strong``,
        an un-/mis-stamped prior) OR a plain ``contact.*`` claim born with ``identity_binding=None``
        (permitted for non-facet contact fields; the column then carries no exclusion signal, so the
        gate is the *only* thing that can exclude it). In those cases it is set ``rejected`` (the
        only mutable lever) so a wrong/absent column can't carry it into the usable set
        (``merge.exclude_rejected`` then drops it). A ``strong`` claim's status is untouched
        (eligible for M9.2/M9.3)."""
        if (
            binding.strength is IdentityBinding.WEAK
            and can_be_promoted(claim)
            and claim.verification_status is not VerificationStatus.REJECTED
        ):
            await record_verification(conn, claim.id, status=VerificationStatus.REJECTED)

    async def _load_cached(
        self, conn: AsyncConnection, claim_id: ClaimId, fingerprint: str
    ) -> Binding | None:
        """Return the cached :class:`Binding` for ``(claim_id, policy_fingerprint)`` (the
        ``identity_binding_eval`` UNIQUE), or ``None`` on a miss."""
        row = (
            await conn.execute(
                text(
                    "SELECT strength, strength_score, evidence_signals_json, contact_entity_id "
                    "FROM identity_binding_eval "
                    "WHERE claim_id = :claim_id AND policy_fingerprint = :fingerprint"
                ),
                {"claim_id": str(claim_id), "fingerprint": fingerprint},
            )
        ).first()
        if row is None:
            return None
        signals = decode_jsonb_scalar(row[2])
        return Binding(
            claim_id=claim_id,
            contact_entity_id=row[3],
            strength=IdentityBinding(row[0]),
            strength_score=min(1.0, max(0.0, float(row[1]))),
            signals=signals if isinstance(signals, dict) else {},
        )

    async def _insert_eval(self, conn: AsyncConnection, binding: Binding, fingerprint: str) -> None:
        """Append the append-only audit row (the cache). ``ON CONFLICT DO NOTHING`` on the
        ``(claim_id, policy_fingerprint)`` key makes a concurrent first-classification race safe
        (the first binding wins; never a duplicate row). ``policy_version`` rides along as a
        human-readable audit column; the *cache key* is the content fingerprint, so a same-version
        content edit still re-classifies."""
        await conn.execute(
            text(
                """
                INSERT INTO identity_binding_eval
                    (claim_id, contact_entity_id, strength, strength_score, evidence_signals_json,
                     policy_version, policy_fingerprint)
                VALUES
                    (:claim_id, :contact_entity_id, CAST(:strength AS identity_binding),
                     :strength_score, CAST(:signals AS jsonb), :policy_version, :policy_fingerprint)
                ON CONFLICT (claim_id, policy_fingerprint) DO NOTHING
                """
            ),
            {
                "claim_id": str(binding.claim_id),
                "contact_entity_id": str(binding.contact_entity_id),
                "policy_fingerprint": fingerprint,
                "strength": binding.strength.value,
                "strength_score": binding.strength_score,
                "signals": serialize_value_json(dict(binding.signals)),
                "policy_version": self._policy.policy_version,
            },
        )

    def _emit_metrics(self, field_key: str, binding: Binding, *, cache_hit: bool) -> None:
        if cache_hit:
            return  # a replay emits no signal — keeps the strong-binding share exact (idempotent)
        sink = self._sink or get_metric_sink()
        labels = {"field_key": field_key}
        sink.add(METRIC_IDENTITY_BINDING_CLASSIFICATIONS, 1, labels)
        if binding.strength is IdentityBinding.STRONG:
            sink.add(METRIC_IDENTITY_BINDING_STRONG, 1, labels)
        else:
            sink.add(METRIC_IDENTITY_BINDING_WEAK, 1, labels)


async def load_binding_policy(
    conn: AsyncConnection, *, client_id: str | None = None
) -> BindingPolicy:
    """Load the most-specific :class:`BindingPolicy` for a scope: per-client → global default row
    → :data:`DEFAULT_BINDING_POLICY`. The latest ``version`` within the matched scope wins (with a
    deterministic ``created_at``/``policy_id`` tie-break, so a duplicate same-version global row can
    never resolve non-deterministically). Returns the built-in default when no row matches
    (policy-as-data; fail-soft).

    A loaded ``strong_identifier_set`` entry not in :data:`SUPPORTED_IDENTIFIER_KINDS` (e.g. a
    config author copies the spec's ``role``, which the classifier cannot verify) is logged at warn
    level so the silently-inert kind is observable, never a surprise weaker classifier (mirrors
    :func:`load_judge_policy` warning on a retired ``prompt_version``)."""
    candidates: list[str | None] = []
    if client_id is not None:
        candidates.append(client_id)
    candidates.append(None)  # the global default row

    for scope_client in candidates:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT min_identifiers_k, strong_identifier_set, verified_handle_sufficient,
                           weak_source_requires_handle, version
                    FROM binding_policy
                    WHERE client_id IS NOT DISTINCT FROM :client_id
                    ORDER BY version DESC, created_at DESC, policy_id DESC
                    LIMIT 1
                    """
                ),
                {"client_id": scope_client},
            )
        ).first()
        if row is not None:
            identifier_set = decode_jsonb(row[1])
            kinds = tuple(str(x) for x in identifier_set)
            unsupported = [k for k in kinds if k not in SUPPORTED_IDENTIFIER_KINDS]
            if unsupported:
                _log.warning(
                    "binding_policy strong_identifier_set has unsupported kind(s) %s the "
                    "classifier cannot verify; they contribute nothing toward K (supported: %s)",
                    unsupported,
                    sorted(SUPPORTED_IDENTIFIER_KINDS),
                )
            return BindingPolicy(
                min_identifiers_k=int(row[0]),
                strong_identifier_set=kinds,
                verified_handle_sufficient=bool(row[2]),
                weak_source_requires_handle=bool(row[3]),
                policy_version=int(row[4]),
            )
    return DEFAULT_BINDING_POLICY
