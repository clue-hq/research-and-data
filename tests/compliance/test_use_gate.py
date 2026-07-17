"""M10.3 (appropriateness/use gate) — pure decision tests + one DB test per §M10.3 criterion.

The decision is a pure function of ``(use_class, jurisdiction, client_policy)`` (``decide_use``), so
the bulk runs without a database (in ``make check``). :class:`UseGateImpl.evaluate` is exercised
against a live Postgres (skips without one, like the M9 / M10.1 suites) because it reads the
contact's resolved regime via ``current_value(contact.jurisdiction)`` and records the verdict in the
``use_decision`` side table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Jurisdiction, Posture, SourceScope, UseDisposition
from clue_core import (
    AccountStatus,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    UseDecision,
    UseGate,
    UseReason,
    VerificationStatus,
    is_outreach_promotable,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import (
    SPAN_COMPLIANCE_USE_GATE,
    SPAN_VERIFICATION_FAITHFULNESS_JUDGE,
    InMemorySink,
    collect_spans,
)
from clue_research.api.composition import VERIFICATION_GATE_ORDER
from clue_research.claimstore import insert_claim
from clue_research.compliance import (
    DEFAULT_CLIENT_POLICY,
    ClientPolicy,
    SensitiveOverride,
    UseGateImpl,
    decide_use,
    load_client_policy,
)
from clue_research.compliance.use_gate import (
    METRIC_USE_GATE_EVALUATIONS,
    METRIC_USE_GATE_USABLE,
)
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse

from .conftest import rollback_conn, run_async

_PRO = UseClass.PROFESSIONAL_PUBLIC
_PERSONAL = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
_SENSITIVE = UseClass.SENSITIVE


# =====================================================================================
# Pure decision (no DB)
# =====================================================================================


def test_decide_use_default_policy_matrix() -> None:  # AC1, AC3 (pure halves)
    p = DEFAULT_CLIENT_POLICY
    assert decide_use(_PRO, Jurisdiction.GDPR, p) == (True, UseReason.ALLOWED)
    assert decide_use(_PERSONAL, Jurisdiction.GDPR, p) == (True, UseReason.ALLOWED)
    # AC2 (pure half): sensitive locked under the default policy, with the typed reason.
    assert decide_use(_SENSITIVE, Jurisdiction.GDPR, p) == (False, UseReason.SENSITIVE_LOCKED)


def test_sensitive_hard_floor_overrides_policy() -> None:  # AC2 — floor is in the gate, not config
    # Bypass validation to forge an illegal "sensitive is USABLE" policy (an Option-2 client trying
    # to config-bypass Art. 9). decide_use must STILL lock it — the floor lives in the gate, so no
    # config can make special-category data usable for outreach (Doc D §4).
    illegal = ClientPolicy.model_construct(
        posture=Posture.GATHER_BROADLY_GATE_AT_USE,
        allow_map={
            _PRO: UseDisposition.USABLE,
            _PERSONAL: UseDisposition.USABLE,
            _SENSITIVE: UseDisposition.USABLE,
        },
        regime_overrides={},
        version=1,
    )
    assert decide_use(_SENSITIVE, Jurisdiction.US_STATE, illegal) == (
        False,
        UseReason.SENSITIVE_LOCKED,
    )
    assert decide_use(_SENSITIVE, Jurisdiction.GDPR, illegal) == (False, UseReason.SENSITIVE_LOCKED)

    # the floor also outranks a per-regime override (the M10.4 "switch down per regime" lever) — the
    # decide_use floor must win even if a sensitive regime_override slips past validation.
    via_override = ClientPolicy.model_construct(
        posture=Posture.GATHER_BROADLY_GATE_AT_USE,
        allow_map={
            _PRO: UseDisposition.USABLE,
            _PERSONAL: UseDisposition.USABLE,
            _SENSITIVE: UseDisposition.STORED_UNUSABLE,
        },
        regime_overrides={Jurisdiction.GDPR: {_SENSITIVE: UseDisposition.USABLE}},
        version=1,
    )
    assert decide_use(_SENSITIVE, Jurisdiction.GDPR, via_override) == (
        False,
        UseReason.SENSITIVE_LOCKED,
    )


def test_decide_use_disallowed_when_not_usable() -> None:  # AC3 (configurable half)
    # a client policy that locks personal-public → the gate disallows it for the regime.
    p = ClientPolicy(
        allow_map={
            _PRO: UseDisposition.USABLE,
            _PERSONAL: UseDisposition.STORED_UNUSABLE,
            _SENSITIVE: UseDisposition.STORED_UNUSABLE,
        }
    )
    assert decide_use(_PERSONAL, Jurisdiction.GDPR, p) == (
        False,
        UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
    )
    # NOT_STORED is also not usable (the claim shouldn't exist, but if it does it cannot be used)
    p2 = ClientPolicy(
        allow_map={
            _PRO: UseDisposition.NOT_STORED,
            _PERSONAL: UseDisposition.USABLE,
            _SENSITIVE: UseDisposition.STORED_UNUSABLE,
        }
    )
    assert decide_use(_PRO, Jurisdiction.GDPR, p2) == (
        False,
        UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
    )


def test_decide_use_per_regime_override() -> (
    None
):  # per-jurisdiction relaxation (design strict, switch down)
    # personal-public usable everywhere by the base map, but STRICTER in GDPR via a per-regime
    # override — "stricter usability for EU_GDPR than US where configured" (M10.4 relaxation lever,
    # exercised here as a config lookup, never a branch).
    p = ClientPolicy(
        regime_overrides={Jurisdiction.GDPR: {_PERSONAL: UseDisposition.STORED_UNUSABLE}}
    )
    assert decide_use(_PERSONAL, Jurisdiction.GDPR, p) == (
        False,
        UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
    )
    assert decide_use(_PERSONAL, Jurisdiction.US_STATE, p) == (True, UseReason.ALLOWED)  # base map


def test_use_policy_validators() -> None:
    # an incomplete allow-map is rejected (every use-class needs a disposition)
    with pytest.raises(ValidationError):
        ClientPolicy(allow_map={_PRO: UseDisposition.USABLE})
    # sensitive may never be config-marked USABLE (the Art. 9 floor is not config-bypassable)
    with pytest.raises(ValidationError):
        ClientPolicy(
            allow_map={
                _PRO: UseDisposition.USABLE,
                _PERSONAL: UseDisposition.USABLE,
                _SENSITIVE: UseDisposition.USABLE,
            }
        )
    # ...and the floor is not bypassable per regime either: a sensitive regime_override is rejected
    with pytest.raises(ValidationError):
        ClientPolicy(regime_overrides={Jurisdiction.GDPR: {_SENSITIVE: UseDisposition.USABLE}})


def test_use_policy_disposition_for() -> None:
    p = ClientPolicy(
        regime_overrides={Jurisdiction.GDPR: {_PERSONAL: UseDisposition.STORED_UNUSABLE}}
    )
    assert p.disposition_for(_PERSONAL, Jurisdiction.GDPR) is UseDisposition.STORED_UNUSABLE
    assert (
        p.disposition_for(_PERSONAL, Jurisdiction.US_STATE) is UseDisposition.USABLE
    )  # falls through to base
    assert (
        p.disposition_for(_PRO, Jurisdiction.GDPR) is UseDisposition.USABLE
    )  # not overridden → base


def test_sensitive_override_relaxes_floor_for_its_field() -> (
    None
):  # M10.4 — the only floor relaxation
    # a legally-reviewed per-field override is the ONLY sanctioned way a sensitive claim becomes
    # usable; it is scoped to its exact field_key and never relaxes any other field.
    policy = ClientPolicy(
        sensitive_overrides=(
            SensitiveOverride(
                field_key="contact.facet.health_advocacy",
                lawful_basis="art_9_2_e_manifestly_made_public",
                reviewed_by="dpo-2026-014",
            ),
        )
    )
    assert decide_use(
        _SENSITIVE, Jurisdiction.GDPR, policy, field_key="contact.facet.health_advocacy"
    ) == (True, UseReason.ALLOWED)
    # a different sensitive field stays locked (the override is per-field, not a blanket relaxation)
    assert decide_use(
        _SENSITIVE, Jurisdiction.GDPR, policy, field_key="contact.facet.religion"
    ) == (False, UseReason.SENSITIVE_LOCKED)
    # and with no field_key the floor holds (default-deny)
    assert decide_use(_SENSITIVE, Jurisdiction.GDPR, policy) == (False, UseReason.SENSITIVE_LOCKED)


def test_sensitive_override_requires_reviewed_basis() -> None:
    # a blank field_key / lawful_basis / reviewed_by is rejected — an un-reviewed override is
    # exactly the bypass the Art. 9 floor forbids (Doc D §4).
    for kwargs in (
        {"field_key": "", "lawful_basis": "b", "reviewed_by": "r"},
        {"field_key": "contact.facet.x", "lawful_basis": "  ", "reviewed_by": "r"},
        {"field_key": "contact.facet.x", "lawful_basis": "b", "reviewed_by": ""},
    ):
        with pytest.raises(ValidationError):
            SensitiveOverride(**kwargs)  # type: ignore[arg-type]


def test_client_policy_gather_and_store_helpers() -> None:  # the M8 / M4.6-facing seam
    # store_sensitive sub-flag: sensitive is gated by it; non-sensitive is storable by default.
    minimal = ClientPolicy(store_sensitive=False)
    assert minimal.should_store(_SENSITIVE) is False
    assert minimal.should_store(_PRO) is True
    assert ClientPolicy(store_sensitive=True).should_store(_SENSITIVE) is True
    # ...but a NOT_STORED disposition ("not retained at all") is honored for ANY class, not just
    # sensitive — the client's do-not-retain intent must not be silently ignored.
    not_stored = ClientPolicy(
        allow_map={
            _PRO: UseDisposition.USABLE,
            _PERSONAL: UseDisposition.NOT_STORED,
            _SENSITIVE: UseDisposition.STORED_UNUSABLE,
        }
    )
    assert not_stored.should_store(_PERSONAL) is False
    assert not_stored.should_store(_PRO) is True
    # gather_scope: empty = no narrowing (all sources); a non-empty allow-list restricts.
    assert ClientPolicy().gathers_source("any_source") is True
    scoped = ClientPolicy(gather_scope=frozenset({"linkedin", "company_site"}))
    assert scoped.gathers_source("linkedin") is True
    assert scoped.gathers_source("data_broker") is False


def test_is_outreach_promotable_truth_table() -> None:  # AC5/AC6 — strong AND usable
    usable = UseDecision(
        claim_id=new_claim_id(),
        usable_for_outreach=True,
        reason=UseReason.ALLOWED,
        policy_version=1,
    )
    locked = UseDecision(
        claim_id=new_claim_id(),
        usable_for_outreach=False,
        reason=UseReason.SENSITIVE_LOCKED,
        policy_version=1,
    )
    strong = _facet_claim(new_entity_id(), use_class=_PRO, binding=IdentityBinding.STRONG)
    weak = _facet_claim(new_entity_id(), use_class=_PRO, binding=IdentityBinding.WEAK)
    assert is_outreach_promotable(strong, usable) is True
    assert (
        is_outreach_promotable(strong, locked) is False
    )  # accurate-but-not-usable → not promotable
    assert (
        is_outreach_promotable(weak, usable) is False
    )  # weak binding short-circuits (failed M9.4)
    assert is_outreach_promotable(weak, locked) is False


def test_use_gate_registered_last_in_verification_order() -> None:  # AC5 — runs after M9.4/M9.3
    order = VERIFICATION_GATE_ORDER
    assert order[-1] == "use_gate"
    assert order.index("use_gate") > order.index("identity_binding") > order.index("faithfulness")


def test_use_reason_migration_tuple_matches_core() -> None:
    # Pure no-DB drift guard (runs in `make check`): the migration's hand-copied reason tuple must
    # equal core.UseReason exactly AND in order (mirrors the M9.3 migration-tuple guard).
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/8074999828fe_m10_3_use_gate_tables.py"
    )
    spec = importlib.util.spec_from_file_location("_m103_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert tuple(v.value for v in UseReason) == module._USE_REASON


def test_allow_map_migration_default_matches_code() -> None:
    # Pure no-DB drift guard (mirrors the M9.4 jsonb-default guard): the migration's hand-written
    # client_policy.allow_map SQL DEFAULT must equal the Python conservative default, so the two
    # cannot diverge (a default-row that omits allow_map relies on the SQL literal).
    import json
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/8074999828fe_m10_3_use_gate_tables.py"
    ).read_text()
    match = re.search(r"allow_map\s+jsonb NOT NULL DEFAULT\s+'(\{.*?\})'", src, re.DOTALL)
    assert match is not None
    sql_default = json.loads(match.group(1))
    assert sql_default == {
        uc.value: disp.value for uc, disp in DEFAULT_CLIENT_POLICY.allow_map.items()
    }


def test_use_gate_impl_satisfies_frozen_protocol() -> None:  # AC8 — hot-swappable behind the seam
    # The M10.3 impl is structurally the Beat-0 core.compliance.UseGate seam M12/M13 call (no DB to
    # build it) — pins UseGateImpl.evaluate to the frozen signature (mirrors the M9.1/M9.5 seam
    # tests), so a future rename/signature drift fails the suite instead of silently breaking M12.
    assert isinstance(UseGateImpl(_CLIENT), UseGate)


def test_m12_consumer_binds_to_seam_not_impl() -> (
    None
):  # AC8 — a swap leaves the M12 consumer intact
    # any UseGate impl satisfies the seam; is_outreach_promotable works unchanged on its
    # UseDecision — proving M12 binds to the seam, never to the concrete UseGateImpl.
    class _StubGate:
        async def evaluate(self, claim: Claim) -> UseDecision:
            return UseDecision(
                claim_id=claim.id,
                usable_for_outreach=True,
                reason=UseReason.ALLOWED,
                policy_version=1,
            )

    assert isinstance(_StubGate(), UseGate)
    strong = _facet_claim(new_entity_id(), use_class=_PRO, binding=IdentityBinding.STRONG)
    decision = run_async(_StubGate().evaluate(strong))
    assert is_outreach_promotable(strong, decision) is True


# =====================================================================================
# DB-gated behaviour (one per acceptance criterion)
# =====================================================================================

_CLIENT = "client-m10-usegate"


def _gate(
    conn: AsyncConnection,
    *,
    client_id: str = _CLIENT,
    policy: ClientPolicy | None = None,
    record: bool = True,
    sink: InMemorySink | None = None,
) -> UseGateImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return UseGateImpl(
        client_id,
        policy=policy if policy is not None else DEFAULT_CLIENT_POLICY,
        conn_factory=factory,
        record_decisions=record,
        sink=sink,
    )


def _facet_claim(
    contact: EntityId,
    *,
    use_class: UseClass,
    binding: IdentityBinding = IdentityBinding.STRONG,
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
) -> Claim:
    return Claim(
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.test_hook",
        value_json="runs the Berlin marathon",
        source_url="https://www.linkedin.com/in/jana",
        evidence_span="Jana Doe ran the Berlin marathon in 2025.",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        identity_binding=binding,
        use_class=use_class,
        verification_status=verification_status,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
    )


async def _account(conn: AsyncConnection) -> EntityId:
    return await insert_account_entity(
        conn, canonical_name="Acme GmbH", primary_domain="acme.de", status=AccountStatus.ACTIVE
    )


async def _contact(conn: AsyncConnection, account_id: EntityId) -> EntityId:
    return await insert_contact_entity(
        conn, account_entity_id=account_id, full_name="Jana Doe", status=AccountStatus.ACTIVE
    )


async def _write_jurisdiction(
    conn: AsyncConnection, contact: EntityId, regime: str, *, client_id: str = _CLIENT
) -> None:
    """Persist a contact.jurisdiction claim (as M10.1 would) so the gate's regime read resolves."""
    claim = Claim(
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key="contact.jurisdiction",
        value_json={
            "regime": regime,
            "confidence": 0.9,
            "derived_from": "contact_location",
            "jurisdiction_unknown": False,
        },
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
    )
    await insert_claim(conn, stamp_reuse(claim, tenant_id=client_id))


async def _insert_facet(conn: AsyncConnection, claim: Claim, *, client_id: str = _CLIENT) -> Claim:
    await insert_claim(conn, stamp_reuse(claim, tenant_id=client_id))
    return claim


async def _decision_rows(
    conn: AsyncConnection, claim_id: ClaimId
) -> list[tuple[bool, str, str, int]]:
    rows = (
        await conn.execute(
            text(
                "SELECT usable_for_outreach, reason, regime, policy_version FROM use_decision "
                "WHERE claim_id = :c ORDER BY evaluated_at"
            ),
            {"c": str(claim_id)},
        )
    ).all()
    return [(bool(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]


async def _pg_enum_labels(conn: AsyncConnection, type_name: str) -> set[str]:
    rows = (
        await conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typname = :n"
            ),
            {"n": type_name},
        )
    ).all()
    return {r[0] for r in rows}


@pytest.mark.usefixtures("require_compliance_db")
def test_use_reason_enum_matches_core() -> None:
    """The DB use_reason enum stays in lock-step with core.UseReason (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = await _pg_enum_labels(conn, "use_reason")
        assert labels == {v.value for v in UseReason}

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_professional_public_usable_allowed() -> None:  # AC1 + AC7 (span)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PRO))

            with collect_spans() as exporter:
                decision = await _gate(conn).evaluate(claim)

            assert decision.usable_for_outreach is True
            assert decision.reason is UseReason.ALLOWED
            assert decision.policy_version == DEFAULT_CLIENT_POLICY.version
            # the verdict is recorded in the side table, decided under the GDPR regime
            rows = await _decision_rows(conn, claim.id)
            assert rows == [(True, "allowed", "gdpr", DEFAULT_CLIENT_POLICY.version)]
            # AC7: its own span fired, distinct from the faithfulness-judge span, and CARRIES the
            # required (use_class, regime, policy_version, decision) dimensions. The custom keys are
            # not STANDARD_ATTRIBUTES, so the obs redaction chokepoint stringifies values (bool/int)
            finished = exporter.get_finished_spans()
            spans = [s for s in finished if s.name == SPAN_COMPLIANCE_USE_GATE]
            assert spans, "the use gate must emit its dedicated span"
            assert SPAN_VERIFICATION_FAITHFULNESS_JUDGE not in {s.name for s in finished}
            attrs = dict(spans[0].attributes or {})
            assert attrs.get("compliance.use_gate.use_class") == "professional-public"
            assert attrs.get("compliance.use_gate.regime") == "gdpr"
            assert attrs.get("compliance.use_gate.usable") in (True, "True")
            assert attrs.get("compliance.use_gate.reason") == "allowed"
            assert attrs.get("compliance.use_gate.policy_version") in (
                DEFAULT_CLIENT_POLICY.version,
                str(DEFAULT_CLIENT_POLICY.version),
            )

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_sensitive_locked_under_every_posture() -> None:  # AC2 — hard floor
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "us_state")  # the most permissive regime
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_SENSITIVE))

            # an Option-2 "gather broadly" posture: maximally permissive on non-sensitive —
            # sensitive must STILL be locked (the gate floor, not config).
            option2 = ClientPolicy(
                posture=Posture.GATHER_BROADLY_GATE_AT_USE,
                allow_map={
                    _PRO: UseDisposition.USABLE,
                    _PERSONAL: UseDisposition.USABLE,
                    _SENSITIVE: UseDisposition.STORED_UNUSABLE,
                },
            )
            decision = await _gate(conn, policy=option2).evaluate(claim)
            assert decision.usable_for_outreach is False
            assert decision.reason is UseReason.SENSITIVE_LOCKED

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_personal_public_configurable() -> None:  # AC3
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PERSONAL))

            # default (Option 1): usable
            assert (await _gate(conn).evaluate(claim)).usable_for_outreach is True
            # config-only change: a policy that locks personal-public for the regime → not usable
            stricter = ClientPolicy(
                allow_map={
                    _PRO: UseDisposition.USABLE,
                    _PERSONAL: UseDisposition.STORED_UNUSABLE,
                    _SENSITIVE: UseDisposition.STORED_UNUSABLE,
                },
                version=2,
            )
            decision = await _gate(conn, policy=stricter).evaluate(claim)
            assert decision.usable_for_outreach is False
            assert decision.reason is UseReason.USE_CLASS_DISALLOWED_FOR_REGIME
            assert decision.policy_version == 2  # the recorded version tracks the policy

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_accurate_but_not_usable_are_separate() -> None:  # AC4
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            # an ACCURATE (verification_status=verified) but SENSITIVE claim
            claim = await _insert_facet(
                conn,
                _facet_claim(
                    contact, use_class=_SENSITIVE, verification_status=VerificationStatus.VERIFIED
                ),
            )
            decision = await _gate(conn).evaluate(claim)

            # the use gate locks it for outreach...
            assert decision.usable_for_outreach is False
            assert decision.reason is UseReason.SENSITIVE_LOCKED
            # ...without touching the accuracy verdict: the claim is still `verified`, and the use
            # decision lives in its OWN table — the two axes are never conflated (Doc D §5).
            status = (
                await conn.execute(
                    text("SELECT verification_status FROM claim WHERE id = :i"),
                    {"i": str(claim.id)},
                )
            ).scalar_one()
            assert status == "verified"
            assert len(await _decision_rows(conn, claim.id)) == 1

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_idempotent_reevaluation() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PRO))
            sink = InMemorySink()

            first = await _gate(conn, sink=sink).evaluate(claim)
            second = await _gate(conn, sink=sink).evaluate(claim)

            assert first == second
            # one row (the UNIQUE (claim_id, policy_version) idempotency key); the identical replay
            # writes nothing new and emits NO fresh metric (the "share usable" ratio stays exact).
            assert len(await _decision_rows(conn, claim.id)) == 1
            assert (
                sink.counter(
                    METRIC_USE_GATE_EVALUATIONS,
                    field_key="contact.facet.test_hook",
                    reason="allowed",
                )
                == 1.0
            )
            assert (
                sink.counter(
                    METRIC_USE_GATE_USABLE, field_key="contact.facet.test_hook", reason="allowed"
                )
                == 1.0
            )

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_regime_reresolution_refreshes_decision() -> None:  # M10.3×M10.1 — settable post-insert
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PERSONAL))
            # a policy where personal-public is usable everywhere EXCEPT GDPR (per-regime override)
            policy = ClientPolicy(
                regime_overrides={Jurisdiction.GDPR: {_PERSONAL: UseDisposition.STORED_UNUSABLE}}
            )

            # contact resolves US_STATE → usable
            await _write_jurisdiction(conn, contact, "us_state")
            assert (await _gate(conn, policy=policy).evaluate(claim)).usable_for_outreach is True

            # jurisdiction re-resolves to GDPR → the SAME (claim, policy_version) decision flips and
            # the row is refreshed in place (one row, now not usable) so M12 reads the current one
            await _write_jurisdiction(conn, contact, "gdpr")
            refreshed = await _gate(conn, policy=policy).evaluate(claim)
            assert refreshed.usable_for_outreach is False
            rows = await _decision_rows(conn, claim.id)
            assert rows == [(False, "use_class_disallowed_for_regime", "gdpr", 1)]

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_verdict_stable_regime_reresolution_refreshes_audit_regime() -> None:  # M10.3×M10.1 audit
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PRO))

            # under the DEFAULT policy professional-public is usable in BOTH us_state and gdpr, so a
            # re-resolution keeps the SAME verdict — but the deciding-regime audit column must still
            # track the live regime (the cache must not treat a verdict-stable regime change as a
            # no-op, else the M10.3×M10.1 audit column the migration added goes stale).
            await _write_jurisdiction(conn, contact, "us_state")
            await _gate(conn).evaluate(claim)
            assert (await _decision_rows(conn, claim.id)) == [(True, "allowed", "us_state", 1)]

            await _write_jurisdiction(conn, contact, "gdpr")
            await _gate(conn).evaluate(claim)
            # still one row (same policy_version), verdict unchanged, but regime refreshed to gdpr
            assert (await _decision_rows(conn, claim.id)) == [(True, "allowed", "gdpr", 1)]

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_unknown_regime_fails_closed_to_strict() -> None:  # _resolved_regime branch (c)
    # A present `contact.jurisdiction` claim whose regime string is not a known Jurisdiction (a
    # future regime an older deploy doesn't recognise) → the gate fails closed to the strict default
    # rather than crashing or relaxing. (The schema requires a string `regime`, so the "missing/non-
    # string regime" branch is unreachable through a validly-inserted claim — it stays defensive.)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await insert_claim(
                conn,
                stamp_reuse(
                    Claim(
                        entity_id=contact,
                        entity_type=EntityType.CONTACT,
                        field_key="contact.jurisdiction",
                        value_json={"regime": "atlantis", "jurisdiction_unknown": False},
                        source_tier=1,
                        extraction_method=ExtractionMethod.HUMAN,
                        confidence=0.9,
                        run_id=new_run_id(),
                        research_mode=ResearchMode.CONTACT_PROFILING,
                    ),
                    tenant_id=_CLIENT,
                ),
            )
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PERSONAL))
            await _gate(conn).evaluate(claim)
            assert (await _decision_rows(conn, claim.id))[0][2] == "gdpr"  # strict default

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_no_jurisdiction_fails_closed_to_strict() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)  # NO jurisdiction claim
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PERSONAL))

            decision = await _gate(conn).evaluate(claim)
            # decided under the strict-default regime (absence of evidence never relaxes governance)
            rows = await _decision_rows(conn, claim.id)
            assert rows[0][2] == "gdpr"  # STRICT_DEFAULT_REGIME
            assert decision.usable_for_outreach is True  # personal-public usable by the base map

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_record_false_skips_side_table() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_PRO))

            decision = await _gate(conn, record=False).evaluate(claim)
            assert decision.usable_for_outreach is True  # still returns the verdict
            assert await _decision_rows(conn, claim.id) == []  # but writes no row

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_evaluate_rejects_non_personal_claims() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            # a contact claim with no use_class (not use-class-tagged) → the gate rejects it
            untagged = Claim(
                entity_id=contact,
                entity_type=EntityType.CONTACT,
                field_key="contact.location",
                value_json={"country": "DE"},
                source_url="https://example.com/profile",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
            )
            with pytest.raises(ValueError, match="use-class-tagged"):
                await _gate(conn).evaluate(untagged)

            # the other guard: an ACCOUNT-entity claim (e.g. account.resonance.*) is rejected — the
            # gate is contact-axis only (resonance is excluded upstream by the M8.2 firewall).
            account_claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.hq_location",
                value_json={"country": "DE"},
                source_url="https://example.com/acme",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                use_class=UseClass.PROFESSIONAL_PUBLIC,  # set → the entity-type guard fires first
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            with pytest.raises(ValueError, match="CONTACT claims only"):
                await _gate(conn).evaluate(account_claim)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_default_and_overlay() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # no row → the built-in default
            assert await load_client_policy(conn, client_id=_CLIENT) == DEFAULT_CLIENT_POLICY

            # a per-client row with a PARTIAL allow-map override (only personal-public changes) is
            # layered over the default → complete, version recorded, the unspecified entries default
            await conn.execute(
                text(
                    "INSERT INTO client_policy (policy_id, client_id, posture, allow_map, version) "
                    "VALUES (:pid, :cid, 'conservative_default', "
                    "CAST(:am AS jsonb), 3)"
                ),
                {
                    "pid": "p-overlay",
                    "cid": _CLIENT,
                    "am": '{"personal-public-non-sensitive": "stored_unusable"}',
                },
            )
            loaded = await load_client_policy(conn, client_id=_CLIENT)
            assert loaded.version == 3
            assert loaded.allow_map[_PERSONAL] is UseDisposition.STORED_UNUSABLE  # overridden
            assert loaded.allow_map[_PRO] is UseDisposition.USABLE  # default carried through
            assert loaded.allow_map[_SENSITIVE] is UseDisposition.STORED_UNUSABLE

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_rejects_sensitive_usable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a config row that tries to mark sensitive USABLE fails to load (fail-closed — the
            # Art. 9 floor is not config-bypassable; the CHECK permits the jsonb, the model rejects)
            await conn.execute(
                text(
                    "INSERT INTO client_policy (policy_id, client_id, allow_map, version) "
                    "VALUES ('p-bad', :cid, CAST(:am AS jsonb), 1)"
                ),
                {"cid": _CLIENT, "am": '{"sensitive": "usable"}'},
            )
            with pytest.raises(ValidationError):
                await load_client_policy(conn, client_id=_CLIENT)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_rejects_sensitive_usable_via_regime_override() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # the floor is not config-bypassable per regime either: a regime_overrides row marking
            # sensitive USABLE also fails to load (fail-closed at config load, not just at the gate)
            await conn.execute(
                text(
                    "INSERT INTO client_policy (policy_id, client_id, regime_overrides, version) "
                    "VALUES ('p-bad-regime', :cid, CAST(:ro AS jsonb), 1)"
                ),
                {"cid": _CLIENT, "ro": '{"gdpr": {"sensitive": "usable"}}'},
            )
            with pytest.raises(ValidationError):
                await load_client_policy(conn, client_id=_CLIENT)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_reads_posture_columns() -> None:  # M10.4 column round-trip
    async def _run() -> None:
        async with rollback_conn() as conn:
            # an Option-3-shaped row: source-scoped, do-not-store-sensitive, an explicit gather
            # allow-list, and a reviewed sensitive override — all read back by the loader.
            await conn.execute(
                text(
                    "INSERT INTO client_policy "
                    "(policy_id, client_id, posture, source_scope, store_sensitive, "
                    " gather_scope, sensitive_overrides, version) "
                    "VALUES (:pid, :cid, 'professional_public_only', 'professional_public_only', "
                    " false, CAST(:gs AS jsonb), CAST(:so AS jsonb), 4)"
                ),
                {
                    "pid": "p-posture",
                    "cid": _CLIENT,
                    "gs": '["linkedin", "company_site"]',
                    "so": (
                        '[{"field_key": "contact.facet.health_advocacy", '
                        '"lawful_basis": "art_9_2_e", "reviewed_by": "dpo-1"}]'
                    ),
                },
            )
            loaded = await load_client_policy(conn, client_id=_CLIENT)
            assert loaded.posture is Posture.PROFESSIONAL_PUBLIC_ONLY
            assert loaded.source_scope is SourceScope.PROFESSIONAL_PUBLIC_ONLY
            assert loaded.store_sensitive is False
            assert loaded.gather_scope == frozenset({"linkedin", "company_site"})
            assert loaded.version == 4
            override = loaded.sensitive_override_for("contact.facet.health_advocacy")
            assert override is not None and override.reviewed_by == "dpo-1"

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_sensitive_override_makes_claim_usable_via_gate() -> None:  # AC2 — the reviewed exception
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_jurisdiction(conn, contact, "gdpr")
            claim = await _insert_facet(conn, _facet_claim(contact, use_class=_SENSITIVE))

            # without an override the sensitive claim is locked...
            locked = await _gate(conn, record=False).evaluate(claim)
            assert locked.usable_for_outreach is False
            assert locked.reason is UseReason.SENSITIVE_LOCKED

            # ...with a reviewed override for this exact field it clears (the only floor relaxation)
            policy = ClientPolicy(
                sensitive_overrides=(
                    SensitiveOverride(
                        field_key="contact.facet.test_hook",
                        lawful_basis="art_9_2_a_explicit_consent",
                        reviewed_by="dpo-2026-014",
                    ),
                )
            )
            allowed = await _gate(conn, policy=policy).evaluate(claim)
            assert allowed.usable_for_outreach is True
            assert allowed.reason is UseReason.ALLOWED

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_reads_option2_store_sensitive_true() -> (
    None
):  # AC2 store-bit round-trip
    async def _run() -> None:
        async with rollback_conn() as conn:
            # an Option-2 row stores sensitive (store_sensitive=true) — the loader must read the
            # TRUE case back (the existing round-trip only exercises the false/minimize case).
            await conn.execute(
                text(
                    "INSERT INTO client_policy "
                    "(policy_id, client_id, posture, source_scope, store_sensitive, version) "
                    "VALUES (:pid, :cid, 'gather_broadly_gate_at_use', 'full_sweep', true, 5)"
                ),
                {"pid": "p-opt2", "cid": _CLIENT},
            )
            loaded = await load_client_policy(conn, client_id=_CLIENT)
            assert loaded.posture is Posture.GATHER_BROADLY_GATE_AT_USE
            assert loaded.store_sensitive is True
            assert loaded.should_store(_SENSITIVE) is True  # stored — the gate still locks its use
            assert loaded.version == 5

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_load_client_policy_rejects_malformed_override_entry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a sensitive_overrides element that is not an object (a bare string) must fail loudly
            # at load, not be silently dropped to an empty register (the Art. 9 register must show).
            await conn.execute(
                text(
                    "INSERT INTO client_policy "
                    "(policy_id, client_id, sensitive_overrides, version) "
                    "VALUES ('p-bad-ovr', :cid, CAST(:so AS jsonb), 1)"
                ),
                {"cid": _CLIENT, "so": '["contact.facet.health"]'},
            )
            with pytest.raises(ValidationError):
                await load_client_policy(conn, client_id=_CLIENT)

    run_async(_run())
