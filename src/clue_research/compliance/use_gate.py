"""M10.3 — the appropriateness/use gate (impl of the frozen ``core.compliance.UseGate``).

This is the *second* gate Doc D was written to add (Doc D §3/§5). The accuracy/identity gates
(M9.3 faithfulness, M9.4 identity-binding) answer "is it true, and is it *this* person?"; this gate
answers the orthogonal **"may we lawfully and tastefully *use* this true claim on this person, in
this jurisdiction, for this client?"** A `contact.facet.*` claim may drive outreach **only if it
clears both** — a true, well-sourced, correctly-attributed personal fact can still be unlawful or
tasteless to use, and that is a *separately measurable* failure (Doc D §5; conventions §5). The two
gates live in separate modules and emit separate spans on purpose.

:class:`UseGateImpl` implements the Beat-0 :class:`clue_research.core.compliance.UseGate` protocol,
so M12 (``narrative``) and others call it through the ``core`` seam without importing ``compliance``
(the import-linter independence contract); M10 supplies the impl, injected at the ``api`` root
**last** in the verification sequence (``…faithfulness → identity_binding → use_gate``; PF-7 /
Doc D §7 — "is it this person?" before "may we use it?"). ``evaluate(claim)``:

1. the decision is a **pure** function of ``(use_class, resolved_jurisdiction, client_policy)``
   (:func:`decide_use`) — the claim's immutable ``use_class`` (stamped at extraction by M10.2), the
   contact's *current* resolved regime read via M10.1's ``contact.jurisdiction`` claim
   (:meth:`_resolved_regime`, **fail-closed** to the strict regime when unknown — Doc D §1), and the
   versioned :class:`UsePolicy` allow-map (M10.4 postures-as-config);
2. **the hard floor (Doc D §4):** ``sensitive`` (special-category) data is **never usable** for
   outreach under *any* posture — enforced in the gate itself (not left to config), so even an
   Option-2 "gather broadly" policy that stored it cannot make it usable absent an explicit,
   legally-reviewed override (the M10.4 override register; none here);
3. the verdict is recorded in the ``use_decision`` side table (PF-2 — a verdict settable *after* the
   immutable claim is inserted, never a born ``claim`` column), idempotent per
   ``(claim_id, policy_version)`` and **refreshed in place** when a jurisdiction re-resolution flips
   it under the same policy version (so M12 always reads the current verdict);
4. its own ``compliance.use_gate`` span (distinct from the faithfulness-judge span) carries
   ``(use_class, regime, policy_version, usable, reason)`` and the "share usable" metric (Doc C §6).

The composite M12 calls — "a hook is promotable iff strong identity-binding **and** usable" — is the
frozen :func:`clue_research.core.compliance.is_outreach_promotable` (it takes the claim *and* this
decision, since the verdict lives in the side table, not on the claim). A claim that failed
identity-binding is excluded upstream (``merge`` drops weak-bound contacts; the composite re-asserts
strong), so the use gate is the appropriateness axis *only* and never folds binding into its verdict
(that would conflate the two gates Doc D §5 keeps apart).

Policy-as-data (conventions §2): the allow-map, per-regime relaxation, and ``version`` are versioned
:class:`UsePolicy` rows in ``client_policy`` (per-client overridable; read via
:func:`load_client_policy`), so a posture switch is a config row, not code (Doc D §6). Architecture:
Doc D §3/§5/§6/§7; docs/specs/M10-compliance-and-personal-data.md §M10.3.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, current_value
from clue_research.compliance.fields import CONTACT_JURISDICTION
from clue_research.config import (
    DEFAULT_POSTURE,
    STRICT_DEFAULT_REGIME,
    Jurisdiction,
    JurisdictionPolicy,
    Posture,
    UseDisposition,
)
from clue_research.core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    UseClass,
    UseDecision,
    UseReason,
)
from clue_research.db import transaction
from clue_research.obs import (
    ATTR_CACHE_HIT,
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_SOURCE_TIER,
    SPAN_COMPLIANCE_USE_GATE,
    MetricSink,
    apply_attributes,
    get_logger,
    get_metric_sink,
    traced_step,
)

_log = get_logger(__name__)

# --- M10-local metric names (the "share usable" appropriateness surface, Doc C §6) ------------
# share usable = usable / evaluations; the appropriateness axis, distinct from the M9.3/M9.4
# accuracy/identity surfaces. Defined here so M10.3 stays self-contained (no obs/metrics.py edit).
METRIC_USE_GATE_EVALUATIONS = "research.compliance.use_gate.evaluations"
METRIC_USE_GATE_USABLE = "research.compliance.use_gate.usable"
METRIC_USE_GATE_NOT_USABLE = "research.compliance.use_gate.not_usable"

# --- M10-local span attribute keys (short non-secret values; pass the obs redaction value-shape
# heuristic — an enum string / a bool / a small int. A raw claim_id UUID would not, so the claim is
# identified on the span by entity/field/tier and linked precisely via the use_decision row.) -----
_ATTR_USE_CLASS = "compliance.use_gate.use_class"
_ATTR_REGIME = "compliance.use_gate.regime"
_ATTR_USABLE = "compliance.use_gate.usable"
_ATTR_REASON = "compliance.use_gate.reason"
_ATTR_POLICY_VERSION = "compliance.use_gate.policy_version"


# --- policy-as-data ---------------------------------------------------------

# The conservative-default allow-map, sourced from the M0.4 config skeleton so it is defined
# ONCE (DRY): the same Option-1 map the JurisdictionPolicy skeleton carries (professional-public +
# personal-public-non-sensitive usable; sensitive stored-but-locked).
_DEFAULT_ALLOW_MAP: dict[UseClass, UseDisposition] = dict(JurisdictionPolicy().allow_map)


class UsePolicy(BaseModel):
    """The use-gate policy as data (policy-as-data, conventions §2; Doc D §6) — what the gate reads.

    A small gate-facing model (the M9.4 ``BindingPolicy`` analogue), persisted as the
    ``client_policy`` side table and read via :func:`load_client_policy`. Postures are **not forks**
    (Doc D §6): the ``posture`` is a descriptive label; ``allow_map`` is the *authoritative*
    materialized posture — the ``use_class → disposition`` parameters the gate decides on.
    ``regime_overrides`` is the per-regime relaxation read down from the strict default (the
    "design strict, switch down" lever; M10.4 fills these). ``version`` is recorded on every
    :class:`UseDecision`; bumping it is a config change, not code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    posture: Posture = DEFAULT_POSTURE
    allow_map: dict[UseClass, UseDisposition] = Field(
        default_factory=lambda: dict(_DEFAULT_ALLOW_MAP)
    )
    # regime -> (use_class -> disposition). A regime present here overrides the base allow-map for
    # the listed use-classes *only* (a partial per-regime relaxation); absent regimes/use-classes
    # fall through to ``allow_map``. M10.4 authors these; empty = the base map applies everywhere.
    regime_overrides: dict[Jurisdiction, dict[UseClass, UseDisposition]] = Field(
        default_factory=dict
    )
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check(self) -> UsePolicy:
        """Every use-class has a base disposition; ``sensitive`` may never be config-marked USABLE
        (the gate floors it regardless, but a config row trying to bypass the Art. 9 floor is a
        misconfiguration that must fail loudly, not silently — mirrors ``JurisdictionPolicy``)."""
        missing = [uc for uc in UseClass if uc not in self.allow_map]
        if missing:
            raise ValueError(f"allow_map missing dispositions for use-classes: {missing}")
        if self.allow_map[UseClass.SENSITIVE] is UseDisposition.USABLE:
            raise ValueError(
                "sensitive (special-category) data may not be marked USABLE — it is excluded from "
                "outreach by default regardless of posture (Doc D §4); the gate floors it. Use "
                "STORED_UNUSABLE / NOT_STORED, or the M10.4 legally-reviewed override register."
            )
        # The floor is not config-bypassable per regime either: a regime_override marking sensitive
        # USABLE is the same Art. 9 misconfiguration and must fail loudly (the gate floors it at
        # runtime regardless, but the promise is fail-closed at config load too).
        for regime, overrides in self.regime_overrides.items():
            if overrides.get(UseClass.SENSITIVE) is UseDisposition.USABLE:
                raise ValueError(
                    f"sensitive may not be marked USABLE in regime_overrides[{regime.value}] — "
                    "the Art. 9 floor is not config-bypassable per regime (Doc D §4); the gate "
                    "floors it. Use the M10.4 legally-reviewed override register."
                )
        return self

    def disposition_for(self, use_class: UseClass, regime: Jurisdiction) -> UseDisposition:
        """The disposition for ``use_class`` under ``regime`` — the per-regime override if one is
        configured, else the base allow-map (the "switch down per regime" lookup, not a branch)."""
        override = self.regime_overrides.get(regime)
        if override is not None and use_class in override:
            return override[use_class]
        return self.allow_map[use_class]


DEFAULT_USE_POLICY = UsePolicy()


# --- the pure decision (DB-free, unit-testable) -----------------------------


def decide_use(
    use_class: UseClass, regime: Jurisdiction, policy: UsePolicy
) -> tuple[bool, UseReason]:
    """The appropriateness verdict ``(usable_for_outreach, reason)`` for a personal claim — the pure
    core of the gate, a function of ``(use_class, regime, client_policy)`` only (Doc D §3).

    The **hard floor first** (Doc D §4, AC2): ``sensitive`` special-category data is *never* usable
    for outreach under any posture — enforced here in the gate, not delegated to the allow-map, so
    an Option-2 policy (or a buggy config) can never make it usable. Everything else reads the
    policy's per-regime disposition: ``USABLE`` → allowed; ``STORED_UNUSABLE`` / ``NOT_STORED`` →
    not usable for this use-class in this regime. An empty hook is correct (universal rule)."""
    if use_class is UseClass.SENSITIVE:
        return False, UseReason.SENSITIVE_LOCKED
    if policy.disposition_for(use_class, regime) is UseDisposition.USABLE:
        return True, UseReason.ALLOWED
    return False, UseReason.USE_CLASS_DISALLOWED_FOR_REGIME


# --- the UseGate ------------------------------------------------------------


def _conn_factory_default() -> AbstractAsyncContextManager[AsyncConnection]:
    """Default connection source — one committed transaction per ``evaluate`` (the jurisdiction read
    + the verdict upsert are atomic; the decision is pure, no external call to hold a connection
    across). Indirected so the engine resolves lazily at call time; tests inject a rollback factory.
    """
    return transaction()


class UseGateImpl:
    """The M10.3 appropriateness/use gate (implements ``clue_research.core.compliance.UseGate``).

    Constructed per (client) context at the ``api`` root with the resolved :class:`UsePolicy`
    (loaded via :func:`load_client_policy`), a connection factory (defaults to a committed
    transaction per evaluate), and an optional metric sink. It reads the contact's resolved regime
    under the client's tenant scope and records the verdict in ``use_decision``.
    ``record_decisions=False`` skips the write (callers needing the verdict; read-only tests)."""

    def __init__(
        self,
        client_id: str,
        *,
        policy: UsePolicy = DEFAULT_USE_POLICY,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]] = (
            _conn_factory_default
        ),
        record_decisions: bool = True,
        sink: MetricSink | None = None,
    ) -> None:
        self._client_id = client_id
        self._policy = policy
        self._conn_factory = conn_factory
        self._record = record_decisions
        self._sink = sink
        self._scope = TenantScope.for_tenant(client_id)

    async def evaluate(self, claim: Claim) -> UseDecision:
        """Decide whether ``claim`` may drive outreach; record the ``use_decision`` verdict and emit
        the ``compliance.use_gate`` span + metrics. Idempotent on ``(claim_id, policy_version)`` —
        an identical re-evaluation writes nothing and emits no fresh metric; a jurisdiction
        re-resolution that flips the verdict under the same policy version refreshes the stored row.

        Runs **only** on contact personal claims: the gate is the contact-axis appropriateness check
        (``account.resonance.*`` personal-adjacent data is excluded by the M8.2 resonance firewall,
        not gated here), and a claim with no ``use_class`` was never use-class-tagged (M10.2) — both
        are caller errors, so it raises rather than silently returning a permissive verdict."""
        if claim.entity_type is not EntityType.CONTACT:
            raise ValueError(
                "the use gate evaluates CONTACT claims only — it is the contact-axis "
                "appropriateness gate (account.resonance.* is excluded by the M8.2 firewall)"
            )
        if claim.use_class is None:
            raise ValueError(
                "the use gate evaluates use-class-tagged personal claims — claim.use_class is None "
                "(M10.2 stamps use_class at extraction; the gate runs after, on tagged claims)"
            )
        use_class = claim.use_class
        policy_version = self._policy.version
        with traced_step(
            SPAN_COMPLIANCE_USE_GATE,
            **{
                ATTR_ENTITY_ID: str(claim.entity_id),
                ATTR_FIELD_KEY: str(claim.field_key),
                ATTR_SOURCE_TIER: int(claim.source_tier),
            },
        ) as span:
            async with self._conn_factory() as conn:
                regime = await self._resolved_regime(conn, claim.entity_id)
                usable, reason = decide_use(use_class, regime, self._policy)
                cache_hit = False
                if self._record:
                    existing = await self._load_cached(conn, claim.id, policy_version)
                    if existing == (usable, reason, regime):
                        cache_hit = True  # identical replay (same verdict AND deciding regime)
                    else:
                        # first write, a flipped verdict, OR a verdict-stable regime re-resolution —
                        # all refresh the row in place so the audit regime tracks the live one.
                        await self._upsert_decision(conn, claim.id, usable, reason, regime)
            decision = UseDecision(
                claim_id=claim.id,
                usable_for_outreach=usable,
                reason=reason,
                policy_version=policy_version,
            )
            apply_attributes(
                span,
                {
                    _ATTR_USE_CLASS: use_class.value,
                    _ATTR_REGIME: regime.value,
                    _ATTR_USABLE: usable,
                    _ATTR_REASON: reason.value,
                    _ATTR_POLICY_VERSION: policy_version,
                    ATTR_CACHE_HIT: cache_hit,
                },
            )
            self._emit_metrics(str(claim.field_key), usable, reason, cache_hit=cache_hit)
            return decision

    async def _resolved_regime(
        self, conn: AsyncConnection, contact_entity_id: EntityId
    ) -> Jurisdiction:
        """The contact's *current* resolved regime from its ``contact.jurisdiction`` claim (M10.1),
        read via ``current_value`` under the client's tenant scope. **Fails closed** to the strict
        regime whenever the jurisdiction is absent or unparseable — absence of evidence never
        relaxes governance (Doc D §1), so a contact never gets a permissive verdict by default."""
        cv = await current_value(conn, contact_entity_id, CONTACT_JURISDICTION, scope=self._scope)
        if cv is None or not isinstance(cv.value_json, Mapping):
            return STRICT_DEFAULT_REGIME
        raw = cv.value_json.get("regime")
        if not isinstance(raw, str):
            return STRICT_DEFAULT_REGIME
        try:
            return Jurisdiction(raw)
        except ValueError:
            _log.warning(
                "contact.jurisdiction carries an unknown regime %r; failing closed to %r",
                raw,
                STRICT_DEFAULT_REGIME.value,
            )
            return STRICT_DEFAULT_REGIME

    async def _load_cached(
        self, conn: AsyncConnection, claim_id: ClaimId, policy_version: int
    ) -> tuple[bool, UseReason, Jurisdiction] | None:
        """The recorded ``(usable_for_outreach, reason, regime)`` for ``(claim_id, policy_version)``
        (the ``use_decision`` UNIQUE), or ``None`` on a miss. The deciding ``regime`` is part of the
        tuple so a verdict-stable jurisdiction re-resolution (same usable/reason, different regime)
        is **not** mistaken for an identical replay — the audit column is refreshed, never stale."""
        row = (
            await conn.execute(
                text(
                    "SELECT usable_for_outreach, reason, regime FROM use_decision "
                    "WHERE claim_id = :claim_id AND policy_version = :policy_version"
                ),
                {"claim_id": str(claim_id), "policy_version": policy_version},
            )
        ).first()
        if row is None:
            return None
        return bool(row[0]), UseReason(row[1]), Jurisdiction(row[2])

    async def _upsert_decision(
        self,
        conn: AsyncConnection,
        claim_id: ClaimId,
        usable: bool,
        reason: UseReason,
        regime: Jurisdiction,
    ) -> None:
        """Record the verdict for ``(claim_id, policy_version)`` (settable post-insert; PF-2).
        ``ON CONFLICT DO UPDATE`` refreshes the row when a jurisdiction re-resolution flips the
        verdict under the same policy version, so M12 reads the current decision; a concurrent first
        write is safe (last writer wins with the same deterministic verdict)."""
        await conn.execute(
            text(
                """
                INSERT INTO use_decision
                    (claim_id, usable_for_outreach, reason, regime, policy_version)
                VALUES
                    (:claim_id, :usable, CAST(:reason AS use_reason), :regime, :policy_version)
                ON CONFLICT (claim_id, policy_version) DO UPDATE SET
                    usable_for_outreach = EXCLUDED.usable_for_outreach,
                    reason = EXCLUDED.reason,
                    regime = EXCLUDED.regime,
                    evaluated_at = now()
                """
            ),
            {
                "claim_id": str(claim_id),
                "usable": usable,
                "reason": reason.value,
                "regime": regime.value,
                "policy_version": self._policy.version,
            },
        )

    def _emit_metrics(
        self, field_key: str, usable: bool, reason: UseReason, *, cache_hit: bool
    ) -> None:
        if cache_hit:
            return  # an identical replay emits no signal — keeps the "share usable" ratio exact
        sink = self._sink or get_metric_sink()
        labels = {"field_key": field_key, "reason": reason.value}
        sink.add(METRIC_USE_GATE_EVALUATIONS, 1, labels)
        if usable:
            sink.add(METRIC_USE_GATE_USABLE, 1, labels)
        else:
            sink.add(METRIC_USE_GATE_NOT_USABLE, 1, labels)


# --- policy loader (mirror M9.3 load_judge_policy / M9.4 load_binding_policy) ------------------


def _as_object(raw: object) -> dict[str, object]:
    """Decode a jsonb column to a dict: SQLAlchemy/asyncpg may hand back an already-decoded ``dict``
    or a ``str``/``bytes`` payload (mirrors ``load_binding_policy``'s defensive decode). Anything
    that is not an object decodes to ``{}``."""
    if isinstance(raw, (bytes, bytearray, str)):
        raw = json.loads(raw)
    return raw if isinstance(raw, dict) else {}


def _parse_allow_map(raw: object) -> dict[UseClass, UseDisposition]:
    return {UseClass(str(k)): UseDisposition(str(v)) for k, v in _as_object(raw).items()}


def _parse_regime_overrides(
    raw: object,
) -> dict[Jurisdiction, dict[UseClass, UseDisposition]]:
    return {
        Jurisdiction(regime): _parse_allow_map(overrides)
        for regime, overrides in _as_object(raw).items()
    }


async def load_client_policy(conn: AsyncConnection, *, client_id: str | None = None) -> UsePolicy:
    """Load the most-specific :class:`UsePolicy` for a scope: per-client → global default row →
    :data:`DEFAULT_USE_POLICY`. The latest ``version`` within the matched scope wins (deterministic
    ``created_at``/``policy_id`` tie-break, so a duplicate same-version global row can never resolve
    non-deterministically). Returns the built-in default when no row matches (policy-as-data;
    fail-soft).

    A row's ``allow_map`` is layered **over** the conservative default, so a config row only needs
    to list the entries it changes (a partial override; mirrors the config skeleton's "a client
    override replaces individual entries") and is always complete. A row that tries to mark
    ``sensitive`` USABLE fails :class:`UsePolicy` validation at load (fail-closed — the Art. 9 floor
    is not config-bypassable; use the M10.4 override register), surfacing the misconfiguration
    loudly rather than silently relaxing governance."""
    candidates: list[str | None] = []
    if client_id is not None:
        candidates.append(client_id)
    candidates.append(None)  # the global default row

    for scope_client in candidates:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT posture, allow_map, regime_overrides, version FROM client_policy
                    WHERE client_id IS NOT DISTINCT FROM :client_id
                    ORDER BY version DESC, created_at DESC, policy_id DESC
                    LIMIT 1
                    """
                ),
                {"client_id": scope_client},
            )
        ).first()
        if row is not None:
            return UsePolicy(
                posture=Posture(row[0]),
                allow_map={**_DEFAULT_ALLOW_MAP, **_parse_allow_map(row[1])},
                regime_overrides=_parse_regime_overrides(row[2]),
                version=int(row[3]),
            )
    return DEFAULT_USE_POLICY
