"""M9.4 (ENG-144) — identity-binding gate: strong vs weak contact claims.

Every §M9.4 acceptance criterion has a dedicated test. The pure classifier (handle match, identifier
co-occurrence, the strength scorer) runs without a database (in ``make check``); the
``IdentityBindingGateImpl.classify`` behaviour is exercised against a live Postgres (skips without
one, like the M9.1/M9.2/M9.3 suites) because it reads the resolved ``contact_entity`` / parent
``account_entity`` / ``source_manifest`` prior and writes the ``identity_binding_eval`` audit +
``binding_policy`` config + the ``claim.verification_status`` drift backstop.

The gate has no LLM call (classification is deterministic), so the DB tests inject the test's own
rollback-bound connection and assert the audit row, the status backstop, the metric, and the span.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import insert_claim
from clue_research.core import (
    AccountStatus,
    Claim,
    ClaimFlavor,
    ClaimId,
    ContactEntity,
    DiscoveryProvenance,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    VerificationStatus,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.obs import (
    SPAN_VERIFICATION_IDENTITY_BINDING,
    InMemorySink,
    collect_spans,
)
from clue_research.verification import (
    DEFAULT_BINDING_POLICY,
    BindingPolicy,
    IdentityBindingGateImpl,
    classify_binding,
    count_identifier_matches,
    handle_matches,
    load_binding_policy,
    normalize_url,
    strength_from_signals,
)
from clue_research.verification.identity_binding import (
    METRIC_IDENTITY_BINDING_CLASSIFICATIONS,
    METRIC_IDENTITY_BINDING_STRONG,
    METRIC_IDENTITY_BINDING_WEAK,
)

from .conftest import rollback_conn, run_async

_LINKEDIN = "https://www.linkedin.com/in/jane-doe"


def _contact_entity(
    *,
    entity_id: EntityId | None = None,
    account_entity_id: EntityId | None = None,
    full_name: str | None = "Jane Doe",
    linkedin_url: str | None = _LINKEDIN,
    verified_email: str | None = None,
    geo: dict[str, object] | None = None,
) -> ContactEntity:
    """An in-memory :class:`ContactEntity` for the pure classifier tests."""
    return ContactEntity(
        id=entity_id or new_entity_id(),
        account_entity_id=account_entity_id or new_entity_id(),
        full_name=full_name,
        linkedin_url=linkedin_url,
        verified_email=verified_email,
        geo=geo,
    )


def _contact_claim(
    *,
    entity_id: EntityId | None = None,
    field_key: str = "contact.facet.hobby",
    value: object = "rock climbing",
    source_url: str | None = "https://blog.example.com/post",
    source_key: str | None = "exa",
    tier: int = 2,
    span: str | None = "Jane Doe enjoys rock climbing.",
    identity_binding: IdentityBinding | None = IdentityBinding.WEAK,
    use_class: UseClass | None = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    entity_type: EntityType = EntityType.CONTACT,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
) -> Claim:
    """Build an in-memory contact claim. ``contact.facet.*`` requires identity_binding + use_class
    at construction (the born provenance the immutable column carries); a non-facet contact field
    or an account claim leaves them ``None``."""
    return Claim(
        entity_id=entity_id or new_entity_id(),
        entity_type=entity_type,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_url=source_url,
        source_key=source_key,
        source_tier=tier,  # type: ignore[arg-type]
        extraction_method=ExtractionMethod.SCRAPE,
        evidence_span=span,
        confidence=0.9,  # type: ignore[arg-type]
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=identity_binding,
        use_class=use_class,
        verification_status=status,
    )


# --- pure unit (no DB) ------------------------------------------------------


def test_normalize_url() -> None:
    assert normalize_url(_LINKEDIN) == "linkedin.com/in/jane-doe"
    assert normalize_url("https://www.linkedin.com/in/jane-doe/") == "linkedin.com/in/jane-doe"
    assert normalize_url("linkedin.com/in/jane-doe?utm=x") == "linkedin.com/in/jane-doe"
    assert normalize_url(None) is None
    assert normalize_url("") is None
    # a scheme-less URL whose PATH contains '//' must still parse the host (two-pass parse), not be
    # mis-read as path-only and dropped.
    assert normalize_url("acme.com/a//b") == "acme.com/a//b"
    assert normalize_url("linkedin.com/in/jane//x") == "linkedin.com/in/jane//x"


def test_handle_matches_verified_profile() -> None:
    contact = _contact_entity(linkedin_url=_LINKEDIN)
    # source_url IS the verified profile → handle match.
    assert handle_matches(_contact_claim(source_url=_LINKEDIN), contact)
    # a sub-path of the profile → match (separator-anchored prefix).
    assert handle_matches(_contact_claim(source_url=_LINKEDIN + "/detail/recent-activity"), contact)
    # a different profile that merely shares a prefix → NO match (anti same-name).
    assert not handle_matches(
        _contact_claim(source_url="https://linkedin.com/in/jane-doe-2"), contact
    )
    # a random web page → no match.
    assert not handle_matches(_contact_claim(source_url="https://blog.example.com/x"), contact)


def test_handle_matches_verified_email_in_source_url_not_span() -> None:
    contact = _contact_entity(linkedin_url=None, verified_email="jane@acme.com")
    # the email in the SOURCE_URL (where the evidence lives) → handle match.
    in_url = _contact_claim(source_url="https://acme.com/team?contact=jane@acme.com", span="x")
    assert handle_matches(in_url, contact)
    # the email only in the attacker-controllable evidence_span BODY → NOT a handle match (anyone
    # can print 'contact jane@acme.com' on a page about someone else; a forged binding is the trap).
    in_span = _contact_claim(
        source_url="https://news.example.com/a", span="Quote from jane@acme.com."
    )
    assert not handle_matches(in_span, contact)


def test_handle_matches_email_substring_not_matched() -> None:
    # token-boundary: jane@acme.com must not match inside maryjane@acme.community (another person).
    contact = _contact_entity(linkedin_url=None, verified_email="jane@acme.com")
    longer = _contact_claim(source_url="https://x.com/?e=maryjane@acme.community", span="x")
    assert not handle_matches(longer, contact)


def test_handle_matches_bare_host_profile_no_path() -> None:
    # a malformed host-only linkedin_url must NOT prefix-match an arbitrary /in/ on that host.
    contact = _contact_entity(linkedin_url="https://linkedin.com")
    claim = _contact_claim(source_url="https://linkedin.com/in/someone-else")
    assert not handle_matches(claim, contact)


def test_count_identifier_matches_word_boundary() -> None:
    contact = _contact_entity(full_name="Jane Doe", geo={"city": "Denver"})
    span = "Jane Doe, an engineer at Acme Robotics in Denver, loves climbing."
    count, matched = count_identifier_matches(
        span,
        contact,
        account_name="Acme Robotics",
        account_aliases=(),
        identifier_set=("full_name", "employer", "geo"),
    )
    assert count == 3 and set(matched) == {"full_name", "employer", "geo"}
    # a name-only mention → 1 (employer/geo absent).
    count2, matched2 = count_identifier_matches(
        "Jane Doe wrote a post.",
        contact,
        account_name="Acme Robotics",
        account_aliases=(),
        identifier_set=("full_name", "employer", "geo"),
    )
    assert count2 == 1 and matched2 == ["full_name"]


def test_count_identifier_no_substring_false_positive() -> None:
    # a contact named "Al" must not match inside "Alabama" (word-boundary, not substring).
    contact = _contact_entity(full_name="Al", geo=None)
    count, _ = count_identifier_matches(
        "A trip to Alabama.",
        contact,
        account_name=None,
        account_aliases=(),
        identifier_set=("full_name",),
    )
    assert count == 0


def test_strength_from_signals_handle_is_strong() -> None:
    strength, score = strength_from_signals(
        handle_match=True,
        verified_handle_sufficient=True,
        identifier_count=0,
        k=2,
        prior=None,
        weak_source_requires_handle=True,
    )
    assert strength is IdentityBinding.STRONG and score == 1.0


def test_strength_from_signals_k_identifiers_is_strong() -> None:
    # ≥K identifiers from a STRONG-prior (trusted) source, no handle → strong (criterion 2).
    strong, score = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=2,
        k=2,
        prior=IdentityBinding.STRONG,
        weak_source_requires_handle=True,
    )
    assert strong is IdentityBinding.STRONG and score == 1.0
    # one identifier short of K → weak.
    weak, score2 = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=1,
        k=2,
        prior=IdentityBinding.STRONG,
        weak_source_requires_handle=True,
    )
    assert weak is IdentityBinding.WEAK and score2 == pytest.approx(0.5)


def test_strength_from_signals_untrusted_prior_requires_handle() -> None:
    # the critical same-name fix: a source whose prior is NOT explicitly strong (None/undeclared or
    # weak) cannot reach strong on identifiers alone — it needs a verified handle. None is the
    # tier-4 open-web case (the most attacker-controllable path), so it must fail closed.
    for prior in (None, IdentityBinding.WEAK):
        strength, score = strength_from_signals(
            handle_match=False,
            verified_handle_sufficient=True,
            identifier_count=3,
            k=2,
            prior=prior,
            weak_source_requires_handle=True,
        )
        assert strength is IdentityBinding.WEAK
        assert score == pytest.approx(0.5)  # coverage 1.0 halved for a non-trusted source


def test_strength_from_signals_handle_not_sufficient_scores_low() -> None:
    # verified_handle_sufficient=False + a handle but no identifiers → WEAK, and score must NOT be
    # the 1.0 reserved for a *sufficient* handle (the score must reflect the strength signal).
    strength, score = strength_from_signals(
        handle_match=True,
        verified_handle_sufficient=False,
        identifier_count=0,
        k=2,
        prior=None,
        weak_source_requires_handle=True,
    )
    assert strength is IdentityBinding.WEAK and score < 1.0


def test_strength_from_signals_name_only_never_strong() -> None:
    # the spec's WEAK is "name match only": one matched identifier that is just the name is never
    # strong, even at K=1 from a trusted source — a corroborating non-name identifier is required.
    strength, _ = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=1,
        k=1,
        prior=IdentityBinding.STRONG,
        weak_source_requires_handle=True,
        non_name_identifier=False,
    )
    assert strength is IdentityBinding.WEAK
    # a single NON-name identifier (e.g. employer) at K=1 from a trusted source → strong.
    ok, _ = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=1,
        k=1,
        prior=IdentityBinding.STRONG,
        weak_source_requires_handle=True,
        non_name_identifier=True,
    )
    assert ok is IdentityBinding.STRONG


def test_strength_from_signals_weak_source_needs_handle() -> None:
    # a WEAK-prior source with K identifiers but NO handle → still weak (same-name guard), score
    # halved.
    strength, score = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=2,
        k=2,
        prior=IdentityBinding.WEAK,
        weak_source_requires_handle=True,
    )
    assert strength is IdentityBinding.WEAK and score == pytest.approx(0.5)
    # policy relaxed → the same identifiers now reach strong (config, not code).
    relaxed, _ = strength_from_signals(
        handle_match=False,
        verified_handle_sufficient=True,
        identifier_count=2,
        k=2,
        prior=IdentityBinding.WEAK,
        weak_source_requires_handle=False,
    )
    assert relaxed is IdentityBinding.STRONG


def test_classify_binding_verified_handle_strong() -> None:
    contact = _contact_entity(linkedin_url=_LINKEDIN)
    claim = _contact_claim(entity_id=contact.id, source_url=_LINKEDIN, span="A post by the author.")
    binding = classify_binding(claim, contact)
    assert binding.strength is IdentityBinding.STRONG
    assert binding.strength_score == 1.0
    assert binding.contact_entity_id == claim.entity_id
    assert binding.signals["verified_handle_match"] is True


def test_classify_binding_name_only_weak() -> None:
    contact = _contact_entity(linkedin_url=_LINKEDIN, full_name="Jane Doe")
    claim = _contact_claim(source_url="https://blog.example.com/x", span="Jane Doe wrote a post.")
    binding = classify_binding(claim, contact)
    assert binding.strength is IdentityBinding.WEAK


def test_classify_binding_unresolved_contact_is_weak() -> None:
    # no resolved contact → we cannot confirm it is this person → weak (the safe default).
    binding = classify_binding(_contact_claim(), None)
    assert binding.strength is IdentityBinding.WEAK
    assert binding.strength_score == 0.0
    assert binding.signals["contact_resolved"] is False


def test_classify_binding_k_change_flips_strength() -> None:
    # AC5 (pure form): same claim+contact, raising K in policy flips strong → weak, no code change.
    # A trusted (STRONG-prior) source so criterion 2 is in play without a handle.
    contact = _contact_entity(full_name="Jane Doe", geo={"city": "Denver"})
    claim = _contact_claim(span="Jane Doe in Denver.", source_url="https://web.example.com/x")
    at_k2 = classify_binding(
        claim,
        contact,
        account_name="Acme",
        manifest_prior=IdentityBinding.STRONG,
        policy=BindingPolicy(min_identifiers_k=2),
    )
    at_k3 = classify_binding(
        claim,
        contact,
        account_name="Acme",
        manifest_prior=IdentityBinding.STRONG,
        policy=BindingPolicy(min_identifiers_k=3),
    )
    assert at_k2.strength is IdentityBinding.STRONG  # full_name + geo = 2
    assert at_k3.strength is IdentityBinding.WEAK  # needs 3


def test_classify_binding_name_only_at_k1_is_weak() -> None:
    # even at K=1 from a trusted source, a name-only match is weak (name does not self-corroborate).
    contact = _contact_entity(full_name="Jane Doe", geo=None)
    claim = _contact_claim(span="Jane Doe.", source_url="https://web.example.com/x")
    binding = classify_binding(
        claim,
        contact,
        manifest_prior=IdentityBinding.STRONG,
        policy=BindingPolicy(min_identifiers_k=1, strong_identifier_set=("full_name", "employer")),
    )
    assert binding.strength is IdentityBinding.WEAK
    assert binding.signals["identifier_matches"] == ["full_name"]


def test_classify_binding_handle_not_sufficient_falls_through() -> None:
    # with verified_handle_sufficient=False, a handle alone does not make it strong — it must also
    # meet criterion 2 (a corroborating identifier); otherwise weak, and not scored 1.0.
    contact = _contact_entity(linkedin_url=_LINKEDIN, full_name="Jane Doe", geo=None)
    claim = _contact_claim(source_url=_LINKEDIN, span="A post.")  # handle match, no identifiers
    binding = classify_binding(
        claim, contact, policy=BindingPolicy(verified_handle_sufficient=False)
    )
    assert binding.strength is IdentityBinding.WEAK
    assert binding.strength_score < 1.0


def test_binding_policy_fingerprint_is_content_addressed() -> None:
    base = BindingPolicy()
    assert base.fingerprint() == BindingPolicy().fingerprint()  # deterministic
    # every classification-affecting field (and the version) changes the fingerprint.
    assert base.fingerprint() != BindingPolicy(min_identifiers_k=3).fingerprint()
    assert base.fingerprint() != BindingPolicy(strong_identifier_set=("full_name",)).fingerprint()
    assert base.fingerprint() != BindingPolicy(verified_handle_sufficient=False).fingerprint()
    assert base.fingerprint() != BindingPolicy(weak_source_requires_handle=False).fingerprint()
    assert base.fingerprint() != BindingPolicy(policy_version=2).fingerprint()
    # identifier-set ORDER does not change it (sorted in the fingerprint).
    assert (
        BindingPolicy(strong_identifier_set=("full_name", "employer")).fingerprint()
        == BindingPolicy(strong_identifier_set=("employer", "full_name")).fingerprint()
    )


def test_classify_binding_identifier_set_change() -> None:
    # dropping "employer" from the set lowers the count (config-driven).
    contact = _contact_entity(full_name="Jane Doe", geo=None)
    claim = _contact_claim(
        span="Jane Doe at Acme Robotics.", source_url="https://web.example.com/x"
    )
    full = classify_binding(
        claim,
        contact,
        account_name="Acme Robotics",
        policy=BindingPolicy(strong_identifier_set=("full_name", "employer")),
    )
    name_only = classify_binding(
        claim,
        contact,
        account_name="Acme Robotics",
        policy=BindingPolicy(strong_identifier_set=("full_name",)),
    )
    assert full.signals["identifier_count"] == 2
    assert name_only.signals["identifier_count"] == 1


def test_binding_policy_defaults() -> None:
    assert DEFAULT_BINDING_POLICY.min_identifiers_k == 2
    assert DEFAULT_BINDING_POLICY.strong_identifier_set == ("full_name", "employer", "geo")
    assert DEFAULT_BINDING_POLICY.verified_handle_sufficient is True
    assert DEFAULT_BINDING_POLICY.weak_source_requires_handle is True
    assert DEFAULT_BINDING_POLICY.policy_version == 1


def test_classify_non_contact_and_discovery_raise() -> None:
    # the gate runs only on contact FIELD claims: an account claim and a contact discovery claim
    # both raise (account claims untouched — AC4; binding is field-claim provenance, not discovery).
    gate = IdentityBindingGateImpl()
    account_claim = _contact_claim(
        field_key="account.synth",
        entity_type=EntityType.ACCOUNT,
        identity_binding=None,
        use_class=None,
    )
    with pytest.raises(ValueError, match="CONTACT claims only"):
        run_async(gate.classify(account_claim))

    entity = new_entity_id()
    run = new_run_id()
    discovery_claim = Claim(
        entity_id=entity,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet",
        value_json="found",
        source_url="https://exa.local/x",
        source_tier=2,  # type: ignore[arg-type]
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,  # type: ignore[arg-type]
        run_id=run,
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        claim_flavor=ClaimFlavor.DISCOVERY,
        discovery_provenance=DiscoveryProvenance(
            entity_id=entity,
            found_via="exa_search",
            matched_signal="role plausibility",
            discovery_confidence=0.8,  # type: ignore[arg-type]
            run_id=run,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        ),
    )
    with pytest.raises(ValueError, match="discovery-provenance claims"):
        run_async(gate.classify(discovery_claim))


def test_migration_defaults_match_code_defaults() -> None:
    """Pure no-DB drift guard (runs in ``make check``): the migration's DB defaults for the binding
    policy must match the code :data:`DEFAULT_BINDING_POLICY`, so a default drift fails the build
    loudly without a database (mirrors the M9.2/M9.3 static guards)."""
    import json
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/971febbe2906_m9_4_identity_binding_gate_tables.py"
    ).read_text()
    # the DB DEFAULT for min_identifiers_k matches the code default (tolerant of column whitespace).
    k_match = re.search(r"min_identifiers_k\s+int\s+NOT NULL DEFAULT (\d+)", src)
    assert k_match is not None
    assert int(k_match.group(1)) == DEFAULT_BINDING_POLICY.min_identifiers_k
    # the DB DEFAULT identifier-set array matches the code default (order-independent set check).
    set_match = re.search(r"strong_identifier_set\s+jsonb NOT NULL DEFAULT '(\[[^']*\])'", src)
    assert set_match is not None
    assert set(json.loads(set_match.group(1))) == set(DEFAULT_BINDING_POLICY.strong_identifier_set)
    # the two same-name-guard booleans + the version default (load-bearing flags must not drift).
    for column, expected in (
        ("verified_handle_sufficient", DEFAULT_BINDING_POLICY.verified_handle_sufficient),
        ("weak_source_requires_handle", DEFAULT_BINDING_POLICY.weak_source_requires_handle),
    ):
        m = re.search(rf"{column}\s+boolean NOT NULL DEFAULT (true|false)", src)
        assert m is not None, f"no DB default found for {column}"
        assert (m.group(1) == "true") is expected
    v_match = re.search(r"version\s+int NOT NULL DEFAULT (\d+)", src)
    assert v_match is not None
    assert int(v_match.group(1)) == DEFAULT_BINDING_POLICY.policy_version


# --- DB-gated behaviour -----------------------------------------------------


def _gate(
    conn: AsyncConnection,
    *,
    policy: BindingPolicy = DEFAULT_BINDING_POLICY,
    sink: InMemorySink | None = None,
) -> IdentityBindingGateImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return IdentityBindingGateImpl(policy=policy, conn_factory=factory, sink=sink)


async def _account(
    conn: AsyncConnection, *, name: str = "Acme Robotics", domain: str = "acme.com"
) -> EntityId:
    return await insert_account_entity(  # type: ignore[return-value]
        conn, canonical_name=name, primary_domain=domain, status=AccountStatus.ACTIVE
    )


async def _contact(
    conn: AsyncConnection,
    account_id: EntityId,
    *,
    full_name: str = "Jane Doe",
    linkedin_url: str | None = _LINKEDIN,
    verified_email: str | None = None,
    geo: dict[str, object] | None = None,
) -> EntityId:
    return await insert_contact_entity(  # type: ignore[return-value]
        conn,
        account_entity_id=account_id,
        full_name=full_name,
        linkedin_url=linkedin_url,
        verified_email=verified_email,
        geo=geo,
        status=AccountStatus.ACTIVE,
    )


async def _status(conn: AsyncConnection, claim_id: ClaimId) -> str:
    row = (
        await conn.execute(
            text("SELECT verification_status FROM claim WHERE id = :id"), {"id": claim_id}
        )
    ).first()
    assert row is not None
    return row[0]


async def _eval_rows(conn: AsyncConnection, claim_id: ClaimId) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM identity_binding_eval WHERE claim_id = :id"),
                {"id": claim_id},
            )
        ).scalar_one()
    )


@pytest.mark.usefixtures("require_verification_db")
def test_facet_from_verified_linkedin_is_strong() -> None:
    # AC1: a contact.facet.* claim sourced from the contact's verified LinkedIn profile → strong;
    # the eval row is written and (strong) the status is left eligible (unverified, not promoted).
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            claim = _contact_claim(
                entity_id=contact,
                source_url=_LINKEDIN,
                span="On her profile, Jane Doe lists rock climbing.",
                identity_binding=IdentityBinding.STRONG,  # born-stamped strong
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.STRONG
            assert binding.signals["verified_handle_match"] is True
            assert await _eval_rows(conn, claim.id) == 1
            assert (
                await _status(conn, claim.id) == "unverified"
            )  # eligible, not promoted by the gate

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_name_only_web_match_is_weak_and_excluded_from_merge() -> None:
    # AC2: a name-only web match (different employer, no verified handle) → weak, stored for audit,
    # and excluded from the merge view's current_value (the handoff usable set) though it exists.
    async def _run() -> None:
        from clue_research.claimstore import current_value
        from clue_research.claimstore.tenancy import ALL_TENANTS

        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", linkedin_url=_LINKEDIN)
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://randomblog.example.com/post",  # NOT the verified handle
                span="A different Jane Doe at Globex wrote this.",  # name only; wrong employer
                identity_binding=IdentityBinding.WEAK,  # born weak (the waterfall prior)
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.WEAK
            assert await _eval_rows(conn, claim.id) == 1
            # born-weak → status stays unverified (spec: "never advance past unverified")...
            assert await _status(conn, claim.id) == "unverified"
            # ...and the merge view excludes a weak-bound contact claim from current truth.
            cv = await current_value(conn, claim.entity_id, claim.field_key, scope=ALL_TENANTS)
            assert cv is None

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_same_name_trap_distinct_contacts() -> None:
    # AC3: two real people sharing a name resolve to distinct contact_entity_ids; a claim carrying
    # one person's verified handle is strong for THAT contact, but a name-only claim for the OTHER
    # contact (a different person, no handle) is weak — it does not promote on the look-alike.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account_a = await _account(conn, name="Acme", domain="acme.com")
            account_b = await _account(conn, name="Globex", domain="globex.com")
            jane_a = await _contact(
                conn, account_a, full_name="Jane Doe", linkedin_url="https://linkedin.com/in/jane-a"
            )
            jane_b = await _contact(
                conn, account_b, full_name="Jane Doe", linkedin_url="https://linkedin.com/in/jane-b"
            )
            assert jane_a != jane_b
            # claim for A on A's verified profile → strong for A.
            claim_a = _contact_claim(
                entity_id=jane_a,
                source_url="https://linkedin.com/in/jane-a",
                span="Jane Doe's post.",
            )
            # claim for B is just a name match (B's profile is jane-b; this cites jane-a / a blog).
            claim_b = _contact_claim(
                entity_id=jane_b,
                source_url="https://blog.example.com/x",
                span="Jane Doe wrote this.",
            )
            await insert_claim(conn, claim_a, validate_field=False)
            await insert_claim(conn, claim_b, validate_field=False)
            bind_a = await _gate(conn).classify(claim_a)
            bind_b = await _gate(conn).classify(claim_b)
            assert bind_a.strength is IdentityBinding.STRONG
            assert bind_b.strength is IdentityBinding.WEAK

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_strong_via_identifiers_no_handle_trusted_source() -> None:
    # strong via criterion 2 (≥K identifiers co-occur) even without a verified-handle match — but
    # ONLY from a STRONG-prior (trusted) source (``crm``); the parent-account name (employer) read
    # from account_entity. A non-trusted source on the same span is weak (the same-name guard / the
    # critical fix), covered by test_critical_untrusted_source_name_match_is_weak below.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", geo={"city": "Denver"})
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://news.example.com/a",  # not the handle
                source_key="crm",  # a STRONG-prior (trusted) seed source
                span="Jane Doe, an engineer at Acme Robotics in Denver, was promoted.",
                identity_binding=IdentityBinding.STRONG,
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.STRONG
            assert binding.signals["verified_handle_match"] is False
            assert binding.signals["identifier_count"] >= 2
            assert binding.signals["source_prior"] == "strong"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_critical_untrusted_source_name_match_is_weak() -> None:
    # the CRITICAL same-name fix: a tier-4 open-web source carries NO binding prior (NULL), so a
    # handle-less span that name-drops the target (name + employer + geo) must NOT forge a strong
    # binding from attacker-controllable text — it fails closed to WEAK.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", geo={"city": "Denver"})
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://attacker.example.com/post",  # not the handle
                source_key="exa_deep",  # tier-4 open-web, NULL prior → fail closed
                tier=2,
                span="Jane Doe, an engineer at Acme Robotics in Denver, loves climbing.",
                identity_binding=IdentityBinding.WEAK,
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.WEAK  # the identifier match is not trusted
            assert binding.signals["source_prior"] is None  # exa_deep declares no prior
            assert binding.signals["identifier_count"] >= 2  # the identifiers DID match...

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_drift_born_strong_classified_weak_is_rejected() -> None:
    # the defensive backstop: a claim BORN strong (a mis-stamped / un-refined prior) that the gate
    # classifies WEAK is set REJECTED — a wrong immutable column must not ride into the usable set.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, full_name="Jane Doe", linkedin_url=_LINKEDIN)
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://randomblog.example.com/x",  # not the handle
                span="Jane Doe is mentioned briefly.",  # name-only
                identity_binding=IdentityBinding.STRONG,  # BORN strong (drift)
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.WEAK
            assert await _status(conn, claim.id) == "rejected"  # backstop fired
            # and the REJECTED backstop (not the immutable column, which wrongly says STRONG) is the
            # causal lever that removes the claim from the usable set (merge.exclude_rejected).
            from clue_research.claimstore import current_value
            from clue_research.claimstore.tenancy import ALL_TENANTS

            cv = await current_value(conn, claim.entity_id, claim.field_key, scope=ALL_TENANTS)
            assert cv is None
            # the immutable identity_binding column was NOT rewritten — it is still 'strong'.
            born = (
                await conn.execute(
                    text("SELECT identity_binding FROM claim WHERE id = :id"), {"id": claim.id}
                )
            ).scalar_one()
            assert born == "strong"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_gate_never_mutates_immutable_identity_binding() -> None:
    # the central invariant: the gate NEVER rewrites claim.identity_binding (immutable born
    # provenance, 0004 trigger) — it only moves the mutable verification_status. A born-STRONG claim
    # the gate classifies WEAK keeps its 'strong' column and only its status flips.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, full_name="Jane Doe", linkedin_url=_LINKEDIN)
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://randomblog.example.com/x",  # not the handle → weak
                span="Jane Doe briefly.",  # name-only
                identity_binding=IdentityBinding.STRONG,  # born strong
            )
            await insert_claim(conn, claim, validate_field=False)
            before = (
                await conn.execute(
                    text("SELECT identity_binding FROM claim WHERE id = :id"), {"id": claim.id}
                )
            ).scalar_one()
            await _gate(conn).classify(claim)
            after = (
                await conn.execute(
                    text("SELECT identity_binding FROM claim WHERE id = :id"), {"id": claim.id}
                )
            ).scalar_one()
            assert before == after == "strong"  # the immutable column is untouched
            assert await _status(conn, claim.id) == "rejected"  # only the mutable status moved

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_born_none_non_facet_contact_weak_is_rejected_and_excluded() -> None:
    # a plain non-facet contact claim may be born with identity_binding=None (the DB CHECK requires
    # a binding only for contact.facet.*). For such a claim the column carries no exclusion signal,
    # so the gate's REJECTED backstop is the ONLY thing keeping a name-only weak claim out
    # of the usable set — verify it both flips the status AND drops it from current_value.
    async def _run() -> None:
        from clue_research.claimstore import current_value
        from clue_research.claimstore.tenancy import ALL_TENANTS

        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, full_name="Jane Doe", linkedin_url=_LINKEDIN)
            claim = _contact_claim(
                entity_id=contact,
                field_key="contact.role_on_committee",  # non-facet → binding NOT required at insert
                value="champion",
                source_url="https://blog.example.com/x",  # not the handle → weak
                span="Jane Doe.",  # name-only
                identity_binding=None,  # born None (permitted for non-facet contact fields)
                use_class=None,
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.WEAK
            assert await _status(conn, claim.id) == "rejected"  # backstop is load-bearing here
            cv = await current_value(conn, claim.entity_id, claim.field_key, scope=ALL_TENANTS)
            assert cv is None  # excluded by the REJECTED status, not the (None) column

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_policy_k_change_via_config_changes_classification() -> None:
    # AC5 (DB form): raising min_identifiers_k in a binding_policy row flips the classification with
    # no code change (load_binding_policy reads it). Re-classifying the SAME claim under a changed
    # policy re-runs (the cache is content-fingerprint-keyed, not version-keyed) and the verdict
    # flips strong → weak — proving AC5 on one claim, not two distinct claims.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", geo={"city": "Denver"})
            span = "Jane Doe in Denver."  # full_name + geo = 2 identifiers, no employer mention
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://web.example.com/x",
                source_key="crm",  # STRONG-prior (trusted) source → criterion 2 in play
                span=span,
            )
            await insert_claim(conn, claim, validate_field=False)

            # default K=2 → strong.
            default_policy = await load_binding_policy(conn)
            assert default_policy.min_identifiers_k == 2
            first = await _gate(conn, policy=default_policy).classify(claim)
            assert first.strength is IdentityBinding.STRONG

            # a global policy row with K=3 → the SAME claim re-classifies (new fingerprint) → weak.
            await conn.execute(
                text(
                    "INSERT INTO binding_policy (policy_id, client_id, min_identifiers_k) "
                    "VALUES ('global', NULL, 3)"
                )
            )
            k3 = await load_binding_policy(conn)
            assert k3.min_identifiers_k == 3
            second = await _gate(conn, policy=k3).classify(claim)
            assert second.strength is IdentityBinding.WEAK  # same claim, re-run, flipped
            assert (
                await _eval_rows(conn, claim.id) == 2
            )  # two audit rows (one per policy fingerprint)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_strong_binding_metric_emitted() -> None:
    # AC6: the strong-binding share metric is emitted (classifications + strong/weak counters).
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            strong_claim = _contact_claim(
                entity_id=contact,
                source_url=_LINKEDIN,
                span="Her profile.",
                identity_binding=IdentityBinding.STRONG,
            )
            weak_claim = _contact_claim(
                entity_id=contact,
                source_url="https://blog.example.com/x",
                span="Jane Doe.",
                identity_binding=IdentityBinding.WEAK,
            )
            await insert_claim(conn, strong_claim, validate_field=False)
            await insert_claim(conn, weak_claim, validate_field=False)
            gate = _gate(conn, sink=sink)
            await gate.classify(strong_claim)
            await gate.classify(weak_claim)
            field = "contact.facet.hobby"
            assert sink.counter(METRIC_IDENTITY_BINDING_CLASSIFICATIONS, field_key=field) == 2
            assert sink.counter(METRIC_IDENTITY_BINDING_STRONG, field_key=field) == 1
            assert sink.counter(METRIC_IDENTITY_BINDING_WEAK, field_key=field) == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_runs_before_use_gate_stub() -> None:
    # AC7: the binding gate runs before any use-gate hook — a weak claim never reaches the M10 stub.
    # M10 is not built; we model the ordering against the GATE'S DURABLE OUTPUT (not the in-memory
    # binding): the M10 use-gate will iterate the usable set (current_value) and read the
    # identity_binding_eval verdict. After the gate runs, a weak claim is BOTH absent from
    # current_value AND recorded weak in the audit, so a downstream use-gate keyed on those can
    # never see it — the ordering is a property of the gate's output, not the test's own if-stmt.
    seen_by_use_gate: list[ClaimId] = []

    async def _use_gate_stub(conn: AsyncConnection, claim: Claim) -> None:
        # a faithful M10 stub: only acts on claims that survived into the usable set (current_value)
        # AND are recorded strong in the binding audit. It does NOT branch on an in-memory verdict.
        from clue_research.claimstore import current_value
        from clue_research.claimstore.tenancy import ALL_TENANTS

        cv = await current_value(conn, claim.entity_id, claim.field_key, scope=ALL_TENANTS)
        strength = (
            await conn.execute(
                text(
                    "SELECT strength FROM identity_binding_eval WHERE claim_id = :id "
                    "ORDER BY evaluated_at DESC LIMIT 1"
                ),
                {"id": claim.id},
            )
        ).scalar()
        if cv is not None and strength == "strong":
            seen_by_use_gate.append(claim.id)

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            # born None (non-facet) so the gate's REJECTED backstop — not the column — does the
            # exclusion, exercising the real ordering artifact a use-gate keys on.
            weak_claim = _contact_claim(
                entity_id=contact,
                field_key="contact.role_on_committee",
                value="champion",
                source_url="https://blog.example.com/x",
                span="Jane Doe.",
                identity_binding=None,
                use_class=None,
            )
            await insert_claim(conn, weak_claim, validate_field=False)
            binding = await _gate(conn).classify(weak_claim)
            assert binding.strength is IdentityBinding.WEAK
            await _use_gate_stub(conn, weak_claim)
            assert weak_claim.id not in seen_by_use_gate  # never reached the use-gate

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_account_claim_untouched_contact_eval_written() -> None:
    # AC4: account claims are untouched (the gate raises); a contact claim gets an eval row.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            contact_claim = _contact_claim(
                entity_id=contact, source_url=_LINKEDIN, span="Her profile."
            )
            await insert_claim(conn, contact_claim, validate_field=False)
            await _gate(conn).classify(contact_claim)
            assert await _eval_rows(conn, contact_claim.id) == 1

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_idempotent_replay_no_new_row_no_double_count() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            sink = InMemorySink()
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            claim = _contact_claim(entity_id=contact, source_url=_LINKEDIN, span="Her profile.")
            await insert_claim(conn, claim, validate_field=False)
            gate = _gate(conn, sink=sink)
            first = await gate.classify(claim)
            second = await gate.classify(claim)  # same (claim, policy_version) → cache hit
            assert first.strength is second.strength
            assert await _eval_rows(conn, claim.id) == 1  # no new row
            # the replay does not double-count the metric (share stays exact).
            assert (
                sink.counter(
                    METRIC_IDENTITY_BINDING_CLASSIFICATIONS, field_key="contact.facet.hobby"
                )
                == 1
            )

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_eval_row_content_persists_and_replays() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            claim = _contact_claim(entity_id=contact, source_url=_LINKEDIN, span="Her profile.")
            await insert_claim(conn, claim, validate_field=False)
            gate = _gate(conn)
            first = await gate.classify(claim)
            row = (
                await conn.execute(
                    text(
                        "SELECT strength, strength_score, evidence_signals_json, "
                        "contact_entity_id, policy_version "
                        "FROM identity_binding_eval WHERE claim_id = :id"
                    ),
                    {"id": claim.id},
                )
            ).first()
            assert row is not None
            assert row[0] == "strong"
            assert row[1] == pytest.approx(1.0)
            assert isinstance(row[2], dict) and row[2]["verified_handle_match"] is True
            assert EntityId(row[3]) == claim.entity_id
            assert row[4] == DEFAULT_BINDING_POLICY.policy_version
            # the cache replay reconstructs the same Binding from the row.
            second = await gate.classify(claim)
            assert second.strength is first.strength
            assert second.strength_score == pytest.approx(first.strength_score)
            assert second.contact_entity_id == first.contact_entity_id

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_eval_fractional_score_round_trips() -> None:
    # the non-trivial 0<score<1 path M12 actually consumes: a one-short-of-K WEAK match → coverage
    # 0.5 → must persist and reconstruct exactly through double precision + the cache replay.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", geo={"city": "Denver"})
            # one identifier (full_name) short of the default K=2 from a STRONG-prior source → weak,
            # score = coverage = 1/2 = 0.5 (name-only never strong, and one short of K).
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://news.example.com/a",
                source_key="crm",
                span="Jane Doe wrote something.",  # only the name co-occurs
            )
            await insert_claim(conn, claim, validate_field=False)
            gate = _gate(conn)
            first = await gate.classify(claim)
            assert first.strength is IdentityBinding.WEAK
            assert first.strength_score == pytest.approx(0.5)
            stored = (
                await conn.execute(
                    text("SELECT strength_score FROM identity_binding_eval WHERE claim_id = :id"),
                    {"id": claim.id},
                )
            ).scalar_one()
            assert float(stored) == pytest.approx(0.5)
            replay = await gate.classify(claim)  # cache hit
            assert replay.strength_score == pytest.approx(first.strength_score)

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_load_binding_policy_per_client_then_global_then_default() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # no rows → built-in default.
            assert await load_binding_policy(conn) == DEFAULT_BINDING_POLICY
            # a global row is read when no client row matches.
            await conn.execute(
                text(
                    "INSERT INTO binding_policy (policy_id, client_id, min_identifiers_k, version) "
                    "VALUES ('global', NULL, 3, 1)"
                )
            )
            glob = await load_binding_policy(conn, client_id="acme")
            assert glob.min_identifiers_k == 3
            # a per-client row wins over the global one.
            await conn.execute(
                text(
                    "INSERT INTO binding_policy (policy_id, client_id, min_identifiers_k, version) "
                    "VALUES ('acme', 'acme', 4, 1)"
                )
            )
            cli = await load_binding_policy(conn, client_id="acme")
            assert cli.min_identifiers_k == 4

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_source_prior_weak_blocks_strong_without_handle() -> None:
    # the source manifest prior informs the classification: a WEAK-prior source (e.g. a generic web
    # search) cannot reach strong on identifier-count alone — even with name+employer+geo present.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, name="Acme Robotics")
            contact = await _contact(conn, account, full_name="Jane Doe", geo={"city": "Denver"})
            # find a WEAK-prior source in the seed manifests; fall back to one we know is weak.
            weak_src = (
                await conn.execute(
                    text(
                        "SELECT source_key FROM source_manifest "
                        "WHERE identity_binding_strength = 'weak' LIMIT 1"
                    )
                )
            ).scalar()
            if weak_src is None:
                pytest.skip("no weak-prior source in the seed manifests")
            claim = _contact_claim(
                entity_id=contact,
                source_url="https://web.example.com/x",
                source_key=str(weak_src),
                span="Jane Doe, an engineer at Acme Robotics in Denver.",
            )
            await insert_claim(conn, claim, validate_field=False)
            binding = await _gate(conn).classify(claim)
            assert binding.strength is IdentityBinding.WEAK  # blocked by the weak source prior
            assert binding.signals["source_prior"] == "weak"

    run_async(_run())


@pytest.mark.usefixtures("require_verification_db")
def test_span_emitted_with_strength_score_handle() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, linkedin_url=_LINKEDIN)
            claim = _contact_claim(entity_id=contact, source_url=_LINKEDIN, span="Her profile.")
            await insert_claim(conn, claim, validate_field=False)
            await _gate(conn).classify(claim)

    with collect_spans() as exporter:
        run_async(_run())
    spans = [
        s for s in exporter.get_finished_spans() if s.name == SPAN_VERIFICATION_IDENTITY_BINDING
    ]
    assert spans, "the identity-binding gate must emit its dedicated span"
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("verification.identity_binding.strength") == "strong"
    assert "verification.identity_binding.score" in attrs
    assert attrs.get("verification.identity_binding.handle_match") in (True, "True")
    assert attrs.get("cache_hit") in (False, "False")
