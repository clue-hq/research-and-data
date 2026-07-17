"""M10.3 — the appropriateness/use gate (impl of the frozen ``core.compliance.UseGate``).

This is the *second* gate Doc D was written to add (Doc D §3/§5). The accuracy/identity gates
(M9.3 faithfulness, M9.4 identity-binding) answer "is it true, and is it *this* person?"; this gate
answers the orthogonal **"may we lawfully and tastefully *use* this true claim on this person, in
this jurisdiction, for this client?"** A `contact.facet.*` claim may drive outreach **only if it
clears both** — a true, well-sourced, correctly-attributed personal fact can still be unlawful or
tasteless to use, and that is a *separately measurable* failure (Doc D §5; conventions §5). The two
gates live in separate modules and emit separate spans on purpose.

:class:`UseGateImpl` implements the Beat-0 :class:`clue_core.compliance.UseGate` protocol,
so M12 (``narrative``) and others call it through the ``core`` seam without importing ``compliance``
(the import-linter independence contract); M10 supplies the impl, injected at the ``api`` root
**last** in the verification sequence (``…faithfulness → identity_binding → use_gate``; PF-7 /
Doc D §7 — "is it this person?" before "may we use it?"). ``evaluate(claim)``:

1. the decision is a **pure** function of ``(use_class, resolved_jurisdiction, client_policy)``
   (:func:`decide_use`) — the claim's immutable ``use_class`` (stamped at extraction by M10.2), the
   contact's *current* resolved regime read via M10.1's ``contact.jurisdiction`` claim
   (:meth:`_resolved_regime`, **fail-closed** to the strict regime when unknown — Doc D §1), and the
   versioned :class:`ClientPolicy` allow-map (M10.4 postures-as-config);
2. **the hard floor (Doc D §4):** ``sensitive`` (special-category) data is **never usable** for
   outreach under *any* posture — enforced in the gate itself (not left to config), so even an
   Option-2 "gather broadly" policy that stored it cannot make it usable except via an explicit,
   legally-reviewed per-field :class:`SensitiveOverride` (M10.4's ``sensitive_overrides`` register);
3. the verdict is recorded in the ``use_decision`` side table (PF-2 — a verdict settable *after* the
   immutable claim is inserted, never a born ``claim`` column), idempotent per
   ``(claim_id, policy_version)`` and **refreshed in place** when a jurisdiction re-resolution flips
   it under the same policy version (so M12 always reads the current verdict);
4. its own ``compliance.use_gate`` span (distinct from the faithfulness-judge span) carries
   ``(use_class, regime, policy_version, usable, reason)`` and the "share usable" metric (Doc C §6).

The composite M12 calls — "a hook is promotable iff strong identity-binding **and** usable" — is the
frozen :func:`clue_core.compliance.is_outreach_promotable` (it takes the claim *and* this
decision, since the verdict lives in the side table, not on the claim). A claim that failed
identity-binding is excluded upstream (``merge`` drops weak-bound contacts; the composite re-asserts
strong), so the use gate is the appropriateness axis *only* and never folds binding into its verdict
(that would conflate the two gates Doc D §5 keeps apart).

Policy-as-data (conventions §2): the allow-map, per-regime relaxation, gather/store scope, override
register, and ``version`` are versioned :class:`ClientPolicy` rows in ``client_policy`` (per-client
overridable; read via :func:`load_client_policy`; the three postures materialize into it via
:mod:`clue_research.compliance.posture`), so a posture switch is a config row, not code (Doc D §6).
Architecture: Doc D §3/§5/§6/§7; docs/specs/M10-compliance-and-personal-data.md §M10.3/§M10.4.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    UseClass,
    UseDecision,
    UseReason,
    decode_jsonb,
)
from clue_research.claimstore import TenantScope, current_value
from clue_research.compliance.fields import CONTACT_JURISDICTION
from clue_research.config import (
    DEFAULT_POSTURE,
    STRICT_DEFAULT_REGIME,
    Jurisdiction,
    JurisdictionPolicy,
    Posture,
    SourceScope,
    UseDisposition,
)
from clue_research.db import ConnFactory, transaction
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


class SensitiveOverride(BaseModel):
    """One legally-reviewed exception that lets the gate clear a ``sensitive`` claim for a specific
    field (Doc D §4; M10.4). This is the **only** sanctioned relaxation of the Art. 9 hard floor —
    *not* a blanket config toggle (the ``allow_map`` / ``regime_overrides`` floor is fixed).
    Every entry must carry an explicit ``lawful_basis`` (e.g. an Art. 9(2) condition) and a
    ``reviewed_by`` so the relaxation is narrow, per-field, and auditable; an entry missing
    either is rejected (an override with no reviewed basis is exactly the bypass the floor exists to
    prevent)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str  # the specific contact.facet.* field this override authorizes
    lawful_basis: str  # the explicit Art. 9 condition relied on (non-empty)
    reviewed_by: str  # who reviewed/approved the exception (non-empty, auditable)
    note: str = ""

    @field_validator("field_key", "lawful_basis", "reviewed_by")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "a sensitive override requires field_key, lawful_basis, and reviewed_by "
                "— a blank entry is the un-reviewed bypass the Art. 9 floor forbids (Doc D §4)"
            )
        return value.strip()


class ClientPolicy(BaseModel):
    """The per-client posture policy as data (policy-as-data, conventions §2; Doc D §6) — the seam
    M10.3 reads for usability and M8 / the M4.6 planner read for gather/store scope.

    The three deep-research postures (Doc D §6) are **not permanent forks**: ``posture`` is a
    descriptive label, and every posture is materialized into the SAME parameters on this one model
    (see :mod:`clue_research.compliance.posture`). Nothing reads ``posture`` as a branch.

    *Use-side* (read by the M10.3 gate): ``allow_map`` is the authoritative ``use_class →
    disposition`` map; ``regime_overrides`` is the per-regime relaxation read down from the strict
    default ("design strict, switch down", a lookup not a branch). *Gather/store-side* (read by M8 /
    M4.6 at integration): ``source_scope`` is the collection-time lever (Option 3 scopes to
    professional-public surfaces), ``store_sensitive`` the Doc D §4 minimization sub-flag, and
    ``gather_scope`` an optional explicit source-key allow-list. ``sensitive_overrides`` is the
    legally-reviewed register — the only sanctioned relaxation of the Art. 9 floor. ``version`` is
    recorded on every :class:`UseDecision`; bumping it is a config change, not code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    posture: Posture = DEFAULT_POSTURE
    allow_map: dict[UseClass, UseDisposition] = Field(
        default_factory=lambda: dict(_DEFAULT_ALLOW_MAP)
    )
    # regime -> (use_class -> disposition). A regime present here overrides the base allow-map for
    # the listed use-classes *only* (a partial per-regime relaxation); absent regimes/use-classes
    # fall through to ``allow_map``. Empty = the base map applies everywhere.
    regime_overrides: dict[Jurisdiction, dict[UseClass, UseDisposition]] = Field(
        default_factory=dict
    )
    # --- gather/store-side (Doc D §6; read by M8 / the M4.6 planner at integration) ---
    source_scope: SourceScope = SourceScope.FULL_SWEEP
    store_sensitive: bool = False  # Option 1/3 minimize; Option 2 stores all (gate still locks use)
    gather_scope: frozenset[str] = frozenset()  # explicit source-key allow-list (empty = no narrow)
    sensitive_overrides: tuple[SensitiveOverride, ...] = ()
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check(self) -> ClientPolicy:
        """Every use-class has a base disposition; ``sensitive`` may never be config-marked USABLE
        in ``allow_map`` *or* ``regime_overrides`` (the gate floors it regardless, but a config row
        trying to bypass the Art. 9 floor is a misconfiguration that must fail loudly —
        the *only* sanctioned relaxation is the reviewed ``sensitive_overrides`` register)."""
        missing = [uc for uc in UseClass if uc not in self.allow_map]
        if missing:
            raise ValueError(f"allow_map missing dispositions for use-classes: {missing}")
        if self.allow_map[UseClass.SENSITIVE] is UseDisposition.USABLE:
            raise ValueError(
                "sensitive (special-category) data may not be marked USABLE — it is excluded from "
                "outreach by default regardless of posture (Doc D §4); the gate floors it. Use "
                "STORED_UNUSABLE / NOT_STORED, or the reviewed sensitive_overrides register."
            )
        for regime, overrides in self.regime_overrides.items():
            if overrides.get(UseClass.SENSITIVE) is UseDisposition.USABLE:
                raise ValueError(
                    f"sensitive may not be marked USABLE in regime_overrides[{regime.value}] — "
                    "the Art. 9 floor is not config-bypassable per regime (Doc D §4); the gate "
                    "floors it. Use the legally-reviewed sensitive_overrides register."
                )
        return self

    def disposition_for(self, use_class: UseClass, regime: Jurisdiction) -> UseDisposition:
        """The disposition for ``use_class`` under ``regime`` — the per-regime override if one is
        configured, else the base allow-map (the "switch down per regime" lookup, not a branch)."""
        override = self.regime_overrides.get(regime)
        if override is not None and use_class in override:
            return override[use_class]
        return self.allow_map[use_class]

    def usable_use_classes(self, regime: Jurisdiction) -> frozenset[UseClass]:
        """The use-classes usable for outreach under ``regime`` (the named introspection seam).
        ``sensitive`` is never included — the gate floors it (a per-field reviewed override is
        the only exception, and that is decided per claim, not surfaced as a regime-wide class)."""
        return frozenset(
            uc
            for uc in (UseClass.PROFESSIONAL_PUBLIC, UseClass.PERSONAL_PUBLIC_NON_SENSITIVE)
            if self.disposition_for(uc, regime) is UseDisposition.USABLE
        )

    def should_store(self, use_class: UseClass) -> bool:
        """Whether a claim of ``use_class`` may be *persisted* at all (Doc D §4 minimization;
        M8 reads this at the insert site). A use-class the allow-map marks ``NOT_STORED`` (the
        strictest disposition — "not retained at all") is never stored, for any class; otherwise it
        is storable, except ``sensitive`` which is additionally gated by the ``store_sensitive``
        sub-flag (so Option 1/3 minimize special-category data while Option 2 stores it)."""
        if self.allow_map[use_class] is UseDisposition.NOT_STORED:
            return False
        return use_class is not UseClass.SENSITIVE or self.store_sensitive

    def gathers_source(self, source_key: str) -> bool:
        """Whether the M4.6 planner may consult ``source_key`` (Doc D §6 Option 3 source-scoping).
        An empty ``gather_scope`` imposes no narrowing (the ``source_scope`` lever governs);
        a non-empty allow-list restricts collection to exactly its members."""
        return not self.gather_scope or source_key in self.gather_scope

    def sensitive_override_for(self, field_key: str | None) -> SensitiveOverride | None:
        """The legally-reviewed override authorizing a ``sensitive`` claim for ``field_key``, or
        ``None`` (the floor holds). The only sanctioned relaxation of the Art. 9 hard floor."""
        if field_key is None:
            return None
        for override in self.sensitive_overrides:
            if override.field_key == field_key:
                return override
        return None


DEFAULT_CLIENT_POLICY = ClientPolicy()


# --- the pure decision (DB-free, unit-testable) -----------------------------


def decide_use(
    use_class: UseClass,
    regime: Jurisdiction,
    policy: ClientPolicy,
    *,
    field_key: str | None = None,
) -> tuple[bool, UseReason]:
    """The appropriateness verdict ``(usable_for_outreach, reason)`` for a personal claim — the pure
    core of the gate, a function of ``(use_class, regime, client_policy)`` only (Doc D §3).

    The **hard floor first** (Doc D §4, AC2): ``sensitive`` special-category data is *never* usable
    for outreach under any posture — enforced here in the gate, not delegated to the allow-map, so
    an Option-2 policy (or a buggy config) can never make it usable. The only sanctioned relaxation
    is a reviewed :class:`SensitiveOverride` for this exact ``field_key`` (M10.4) — a narrow,
    per-field, audited exception, never a blanket toggle. Everything else reads the policy's
    per-regime disposition: ``USABLE`` → allowed; ``STORED_UNUSABLE`` / ``NOT_STORED`` → not usable
    for this use-class in this regime. An empty hook is correct (universal rule)."""
    if use_class is UseClass.SENSITIVE:
        if policy.sensitive_override_for(field_key) is not None:
            return True, UseReason.ALLOWED  # the legally-reviewed per-field exception (Doc D §4)
        return False, UseReason.SENSITIVE_LOCKED
    if policy.disposition_for(use_class, regime) is UseDisposition.USABLE:
        return True, UseReason.ALLOWED
    return False, UseReason.USE_CLASS_DISALLOWED_FOR_REGIME


# --- the UseGate ------------------------------------------------------------


class UseGateImpl:
    """The M10.3 appropriateness/use gate (implements ``clue_core.compliance.UseGate``).

    Constructed per (client) context at the ``api`` root with the resolved :class:`ClientPolicy`
    (loaded via :func:`load_client_policy`), a connection factory (defaults to a committed
    transaction per evaluate), and an optional metric sink. It reads the contact's resolved regime
    under the client's tenant scope and records the verdict in ``use_decision``.
    ``record_decisions=False`` skips the write (callers needing the verdict; read-only tests)."""

    def __init__(
        self,
        client_id: str,
        *,
        policy: ClientPolicy = DEFAULT_CLIENT_POLICY,
        conn_factory: ConnFactory = transaction,
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
                usable, reason = decide_use(
                    use_class, regime, self._policy, field_key=str(claim.field_key)
                )
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
    or a ``str``/``bytes`` payload (the shared ``core.decode_jsonb`` round-trip). Anything that is
    not an object decodes to ``{}``."""
    decoded = decode_jsonb(raw)
    return decoded if isinstance(decoded, dict) else {}


def _as_array(raw: object) -> list[object]:
    """Decode a jsonb array column to a list (same defensive decode as :func:`_as_object`)."""
    decoded = decode_jsonb(raw)
    return list(decoded) if isinstance(decoded, list) else []


def _parse_allow_map(raw: object) -> dict[UseClass, UseDisposition]:
    return {UseClass(str(k)): UseDisposition(str(v)) for k, v in _as_object(raw).items()}


def _parse_regime_overrides(
    raw: object,
) -> dict[Jurisdiction, dict[UseClass, UseDisposition]]:
    return {
        Jurisdiction(regime): _parse_allow_map(overrides)
        for regime, overrides in _as_object(raw).items()
    }


def _parse_sensitive_overrides(raw: object) -> tuple[SensitiveOverride, ...]:
    # Every array element is validated — a non-object element raises (fail-loud, like the sibling
    # _parse_allow_map / _parse_regime_overrides), never silently dropped: a malformed entry in the
    # Art. 9 override register must surface, not vanish into an empty register no operator can see.
    return tuple(SensitiveOverride.model_validate(entry) for entry in _as_array(raw))


async def load_client_policy(
    conn: AsyncConnection, *, client_id: str | None = None
) -> ClientPolicy:
    """Load the most-specific :class:`ClientPolicy` for a scope: per-client → global default row →
    :data:`DEFAULT_CLIENT_POLICY`. The latest ``version`` in the matched scope wins (deterministic
    ``created_at``/``policy_id`` tie-break, so a duplicate same-version global row can never resolve
    non-deterministically). Returns the built-in default when no row matches (policy-as-data;
    fail-soft).

    A row's ``allow_map`` is layered **over** the conservative default, so a config row only needs
    to list the entries it changes (a partial override; mirrors the config skeleton's "a client
    override replaces individual entries") and is always complete. A row that tries to mark
    ``sensitive`` USABLE (in ``allow_map`` or ``regime_overrides``), or carries a blank
    ``sensitive_overrides`` entry, fails :class:`ClientPolicy` validation at load (fail-closed — the
    Art. 9 floor is not config-bypassable; only a reviewed per-field override relaxes it), surfacing
    the misconfiguration loudly rather than silently relaxing governance."""
    candidates: list[str | None] = []
    if client_id is not None:
        candidates.append(client_id)
    candidates.append(None)  # the global default row

    for scope_client in candidates:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT posture, allow_map, regime_overrides, source_scope, store_sensitive,
                           gather_scope, sensitive_overrides, version
                    FROM client_policy
                    WHERE client_id IS NOT DISTINCT FROM :client_id
                    ORDER BY version DESC, created_at DESC, policy_id DESC
                    LIMIT 1
                    """
                ),
                {"client_id": scope_client},
            )
        ).first()
        if row is not None:
            return ClientPolicy(
                posture=Posture(row[0]),
                allow_map={**_DEFAULT_ALLOW_MAP, **_parse_allow_map(row[1])},
                regime_overrides=_parse_regime_overrides(row[2]),
                source_scope=SourceScope(row[3]),
                store_sensitive=bool(row[4]),
                gather_scope=frozenset(str(s) for s in _as_array(row[5])),
                sensitive_overrides=_parse_sensitive_overrides(row[6]),
                version=int(row[7]),
            )
    return DEFAULT_CLIENT_POLICY
