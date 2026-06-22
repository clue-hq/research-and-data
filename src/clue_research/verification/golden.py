"""M9.6 — the hand-verified golden set (the eval ground truth) + its DB round-trip (ENG-156).

The golden set is what an accuracy claim is *defended against* (substrate §6): a hand-verified
collection of ``(entity, field, expected_value, expected_source, expected_tier)`` fixtures spanning
the four research modes (M1–M4) and the field-classes, including **negative fixtures** — planted
defects (a fabrication, a same-name trap, a stale fact, an unsupported span) each of which a
*specific* verification mechanism must catch (its documented expected catch, M09 §M9.6).

A fixture has two halves: the **expectation** (a :class:`~clue_research.evals.GoldClaim` — the value
a correct run should produce and the provenance bar it must clear) and, for the eval to actually run
a mechanism, the **planted produced claim** plus its context (the resolved contact/account a gate
reads). :class:`GoldPack` carries both. The expectations are also the *row* form
(``golden_fixture``): the in-code pack is the *file* form, the DB rows are seeded from it and the
human spot-check loop ingests reviewed production claims back as new rows — both valid per the spec.

This module lives in ``verification`` (not ``evals``) because it reads/writes the store; it reuses
the core-only ``evals`` shapes (``GoldSet``/``GoldClaim``/``FixtureKind``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    AccountEntity,
    AccountStatus,
    Claim,
    ContactEntity,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    UtcDatetime,
    account_claim,
    contact_claim,
    new_entity_id,
    new_run_id,
    parse_value_json,
    serialize_value_json,
)
from clue_research.evals import FixtureKind, GoldClaim, GoldEntity, GoldSet

GOLD_SUITE = "verification"

# A fixed reference instant so the freshness fixtures (stale vs fresh) are deterministic.
_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)


class GoldPack(BaseModel):
    """The full eval pack: the gold expectations, the planted *produced* claims a run would emit,
    and the resolved context (contacts/accounts) the mechanisms read. The harness scores
    ``produced`` against ``gold`` (rubrics) and runs the M9 mechanisms over ``produced`` +
    ``contacts`` / ``accounts`` (per-mechanism metrics). ``now`` is the reference instant the
    freshness mechanism measures from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold: GoldSet
    produced: tuple[Claim, ...] = ()
    contacts: dict[EntityId, ContactEntity] = {}
    accounts: dict[EntityId, AccountEntity] = {}
    now: UtcDatetime = _NOW

    def produced_index(self) -> dict[tuple[EntityId, str], Claim]:
        """Produced claims keyed by ``(entity_id, field_key)`` — the join the harness scores on."""
        return {(claim.entity_id, str(claim.field_key)): claim for claim in self.produced}


def verification_gold_pack() -> GoldPack:
    """Build the hand-verified golden pack: positives + the four negative-mechanism traps, spanning
    M1 (account_discovery) / M2 (account_profiling) / M3 (committee_discovery) / M4
    (contact_profiling) and the field-classes. Each mode carries ≥1 positive and ≥1 negative; each
    of the faithfulness / identity-binding / freshness mechanisms has a planted negative fixture
    (the pre-spend-gate and corroboration mechanisms are scenario-driven in the harness — negative
    is constructed, since the ``fixture_kind`` taxonomy covers only the evidence/identity/freshness
    traps)."""
    run = new_run_id()

    # --- entities -----------------------------------------------------------
    novacore = AccountEntity(
        id=new_entity_id(),
        canonical_name="NovaCore",
        primary_domain="novacore.io",
        status=AccountStatus.CANDIDATE,  # discovered (mode M1), not yet promoted to active
    )
    acme = AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme Robotics",
        primary_domain="acme.com",
        status=AccountStatus.ACTIVE,
    )
    globex = AccountEntity(
        id=new_entity_id(),
        canonical_name="Globex Industrial",
        primary_domain="globex.com",
        status=AccountStatus.ACTIVE,
    )
    jane_acme = ContactEntity(
        id=new_entity_id(),
        account_entity_id=acme.id,
        full_name="Jane Doe",
        linkedin_url="https://www.linkedin.com/in/jane-acme",
    )
    # the same-name OTHER person — a real, distinct contact under a different account (the trap).
    jane_globex = ContactEntity(
        id=new_entity_id(),
        account_entity_id=globex.id,
        full_name="Jane Doe",
        linkedin_url="https://www.linkedin.com/in/jane-globex",
    )
    sam = ContactEntity(
        id=new_entity_id(),
        account_entity_id=acme.id,
        full_name="Sam Rivera",
        linkedin_url="https://www.linkedin.com/in/sam-rivera",
    )

    accounts = {a.id: a for a in (novacore, acme, globex)}
    contacts = {c.id: c for c in (jane_acme, jane_globex, sam)}

    gold_entities: list[GoldEntity] = []
    produced: list[Claim] = []

    def _acct(
        entity: AccountEntity,
        field_key: str,
        *,
        expected: object,
        produced_value: object,
        tier: int,
        method: ExtractionMethod,
        mode: ResearchMode,
        kind: FixtureKind = FixtureKind.POSITIVE,
        span: str | None = None,
        source_url: str | None = "https://api.example.com/x",
        days_old: float = 5.0,
        max_tier: int = 3,
        requires_span: bool = True,
    ) -> None:
        gold_entities.append(
            GoldEntity(
                entity_id=entity.id,
                entity_type=EntityType.ACCOUNT,
                claims=(
                    GoldClaim(
                        field_key=field_key,
                        expected_value=expected,  # type: ignore[arg-type]
                        max_source_tier=max(tier, max_tier),
                        requires_evidence_span=requires_span,
                        fixture_kind=kind,
                        mode=mode,
                        expected_source_url=source_url,
                    ),
                ),
            )
        )
        produced.append(
            account_claim(
                entity_id=entity.id,
                field_key=field_key,
                value_json=produced_value,  # type: ignore[arg-type]
                source_tier=tier,
                extraction_method=method,
                confidence=0.9,
                run_id=run,
                research_mode=mode,
                source_url=source_url,
                evidence_span=span,
                observed_at=_NOW - timedelta(days=days_old),
            )
        )

    def _contact(
        entity: ContactEntity,
        field_key: str,
        *,
        expected: object,
        produced_value: object,
        mode: ResearchMode,
        kind: FixtureKind = FixtureKind.POSITIVE,
        binding: IdentityBinding = IdentityBinding.STRONG,
        use_class: UseClass = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        span: str | None = None,
        source_url: str = "https://www.linkedin.com/in/jane-acme",
        days_old: float = 5.0,
        tier: int = 2,
    ) -> None:
        gold_entities.append(
            GoldEntity(
                entity_id=entity.id,
                entity_type=EntityType.CONTACT,
                claims=(
                    GoldClaim(
                        field_key=field_key,
                        expected_value=expected,  # type: ignore[arg-type]
                        max_source_tier=3,
                        requires_evidence_span=True,
                        fixture_kind=kind,
                        mode=mode,
                        expected_source_url=source_url,
                    ),
                ),
            )
        )
        produced.append(
            contact_claim(
                entity_id=entity.id,
                field_key=field_key,
                value_json=produced_value,  # type: ignore[arg-type]
                source_tier=tier,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=run,
                research_mode=mode,
                identity_binding=binding,
                use_class=use_class,
                source_url=source_url,
                evidence_span=span,
                observed_at=_NOW - timedelta(days=days_old),
            )
        )

    # --- M1 account_discovery -----------------------------------------------
    _acct(
        novacore,
        "core.employee_count",
        expected=120,
        produced_value=120,  # correct
        tier=1,
        method=ExtractionMethod.API,
        mode=ResearchMode.ACCOUNT_DISCOVERY,
        max_tier=1,
        requires_span=False,
        source_url="https://api.example.com/firmographics",
    )
    _acct(
        novacore,
        "account.operational_pain",
        expected="data silos slow delivery",
        produced_value="data silos slow delivery",  # fabricated: the span contradicts it
        tier=4,
        method=ExtractionMethod.LLM_SYNTHESIS,
        mode=ResearchMode.ACCOUNT_DISCOVERY,
        kind=FixtureKind.NEGATIVE_FABRICATION,
        span="NovaCore's CEO praised their unified, frictionless data platform.",
        source_url="https://exa.example.com/novacore-synthesis",
        max_tier=4,
    )

    # --- M2 account_profiling -----------------------------------------------
    _acct(
        acme,
        "account.recent_funding",
        expected={"round": "B", "amount_usd": 8_000_000},
        produced_value={"round": "B", "amount_usd": 8_000_000},  # correct
        tier=2,
        method=ExtractionMethod.SCRAPE,
        mode=ResearchMode.ACCOUNT_PROFILING,
        span="Acme Robotics raised an $8M Series B led by Initech Ventures.",
        source_url="https://news.example.com/acme-series-b",
    )
    _acct(
        acme,
        "core.industry",
        expected="robotics",
        produced_value="agriculture",  # WRONG (a swapped resolver returned a known-wrong value)
        tier=2,
        method=ExtractionMethod.SCRAPE,
        mode=ResearchMode.ACCOUNT_PROFILING,
        span="Acme Robotics builds autonomous warehouse robots.",
        source_url="https://acme.com/about",
    )
    _acct(
        acme,
        "account.strategic_move",
        expected="acquiring BetaCorp",
        produced_value="acquiring BetaCorp",  # unsupported: the span is about an unrelated fact
        tier=4,
        method=ExtractionMethod.LLM_SYNTHESIS,
        mode=ResearchMode.ACCOUNT_PROFILING,
        kind=FixtureKind.NEGATIVE_UNSUPPORTED,
        span="Acme Robotics appointed a new CFO last quarter.",
        source_url="https://exa.example.com/acme-synthesis",
        max_tier=4,
    )
    _acct(
        acme,
        "account.resonance.culture",
        expected="collaborative engineering culture",
        # a FAITHFUL tier-4 synthesis: the value text is grounded in the span (no false positive)
        produced_value="collaborative engineering culture",
        tier=4,
        method=ExtractionMethod.LLM_SYNTHESIS,
        mode=ResearchMode.ACCOUNT_PROFILING,
        span="Reviews describe a collaborative engineering culture with strong peer review.",
        source_url="https://exa.example.com/acme-culture",
        max_tier=4,
    )
    _acct(
        acme,
        "account.resonance.sentiment",
        expected="optimistic about automation",
        # a second FAITHFUL tier-4 positive, so faithfulness *precision* is exercised over >1 sample
        produced_value="optimistic about automation",
        tier=4,
        method=ExtractionMethod.LLM_SYNTHESIS,
        mode=ResearchMode.ACCOUNT_PROFILING,
        span="Staff are broadly optimistic about automation and the new robotics line.",
        source_url="https://exa.example.com/acme-sentiment",
        max_tier=4,
    )
    _acct(
        globex,
        "account.hiring_velocity_eng",
        expected=14,
        produced_value=14,  # value correct, but the fact is stale (400d old, account TTL 180d)
        tier=2,
        method=ExtractionMethod.SCRAPE,
        mode=ResearchMode.ACCOUNT_PROFILING,
        kind=FixtureKind.NEGATIVE_STALE,
        span="Globex Industrial grew its engineering team 14% over the year.",
        source_url="https://news.example.com/globex-hiring",
        days_old=400.0,
    )

    # --- M3 committee_discovery ---------------------------------------------
    _contact(
        sam,
        "contact.role_on_committee",
        expected="champion",
        produced_value="champion",  # correct, on the verified profile (strong binding)
        mode=ResearchMode.COMMITTEE_DISCOVERY,
        span="Sam Rivera, on their profile, leads the evaluation working group.",
        source_url="https://www.linkedin.com/in/sam-rivera",
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    _contact(
        jane_globex,
        "contact.facet.hobby",
        expected="marathon running",
        produced_value="marathon running",  # name-only match on a blog -> the same-name trap
        mode=ResearchMode.COMMITTEE_DISCOVERY,
        kind=FixtureKind.NEGATIVE_SAMENAME,
        binding=IdentityBinding.WEAK,
        span="A Jane Doe finished a marathon, a blog reports.",
        source_url="https://runblog.example.com/post",
    )

    # --- M4 contact_profiling -----------------------------------------------
    _contact(
        jane_acme,
        "contact.facet.recent_post",
        expected="a talk on warehouse autonomy",
        produced_value="a talk on warehouse autonomy",  # correct, verified profile, fresh
        mode=ResearchMode.CONTACT_PROFILING,
        span="On her profile, Jane Doe shared a talk on warehouse autonomy.",
        source_url="https://www.linkedin.com/in/jane-acme",
    )
    _contact(
        jane_acme,
        "contact.facet.conference_talk",
        expected="keynote at RoboExpo",
        produced_value="keynote at RoboExpo",  # value fine, but stale (120d old, facet TTL 90d)
        mode=ResearchMode.CONTACT_PROFILING,
        kind=FixtureKind.NEGATIVE_STALE,
        span="On her profile, Jane Doe gave a keynote at RoboExpo.",
        source_url="https://www.linkedin.com/in/jane-acme",
        days_old=120.0,
    )
    _contact(
        jane_globex,
        "contact.facet.recent_award",
        expected="industry innovator award",
        produced_value="industry innovator award",  # name-only on a blog -> the same-name trap
        mode=ResearchMode.CONTACT_PROFILING,
        kind=FixtureKind.NEGATIVE_SAMENAME,
        binding=IdentityBinding.WEAK,
        span="A Jane Doe won an award, an industry blog notes.",
        source_url="https://awardsblog.example.com/post",
    )

    gold = GoldSet(name=GOLD_SUITE, entities=tuple(gold_entities))
    return GoldPack(
        gold=gold,
        produced=tuple(produced),
        contacts=contacts,
        accounts=accounts,
        now=_NOW,
    )


# --- DB round-trip (golden_fixture) -----------------------------------------


async def seed_golden_fixtures(conn: AsyncConnection, gold: GoldSet) -> int:
    """Persist the gold expectations to ``golden_fixture`` (the row form), returning the count of
    *newly* inserted rows. Idempotent: ``ON CONFLICT (entity_ref, field_key, fixture_kind) DO
    NOTHING`` so re-seeding adds nothing (the in-code pack is the source of truth; this materializes
    it for the human-spot-check ingest path and the M13.4 surface)."""
    inserted = 0
    for entity in gold.entities:
        for claim in entity.claims:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO golden_fixture
                        (entity_ref, field_key, expected_value_json, expected_source_url,
                         expected_tier, requires_evidence_span, fixture_kind, mode)
                    VALUES
                        (:entity_ref, :field_key, CAST(:value AS jsonb), :source_url, :tier,
                         :requires_span, CAST(:kind AS fixture_kind), CAST(:mode AS research_mode))
                    ON CONFLICT (entity_ref, field_key, fixture_kind) DO NOTHING
                    """
                ),
                {
                    "entity_ref": str(entity.entity_id),
                    "field_key": str(claim.field_key),
                    "value": serialize_value_json(claim.expected_value),
                    "source_url": claim.expected_source_url,
                    "tier": int(claim.max_source_tier),
                    "requires_span": claim.requires_evidence_span,
                    "kind": claim.fixture_kind.value,
                    "mode": claim.mode.value if claim.mode is not None else None,
                },
            )
            inserted += result.rowcount or 0
    return inserted


async def load_golden_fixtures(conn: AsyncConnection, *, name: str = GOLD_SUITE) -> GoldSet:
    """Read the gold expectations back from ``golden_fixture`` into a :class:`GoldSet` (grouped by
    entity). The inverse of :func:`seed_golden_fixtures` — so a swap can score against the durable,
    versioned ground truth, not just the in-code pack."""
    rows = (
        await conn.execute(
            text(
                """
                SELECT entity_ref, field_key, expected_value_json, expected_source_url,
                       expected_tier, requires_evidence_span, fixture_kind, mode
                FROM golden_fixture
                ORDER BY entity_ref, field_key, fixture_kind
                """
            )
        )
    ).all()

    grouped: dict[str, list[GoldClaim]] = {}
    entity_order: list[str] = []
    for entity_ref, field_key, value, source_url, tier, requires_span, kind, mode in rows:
        ref = str(entity_ref)
        if ref not in grouped:
            grouped[ref] = []
            entity_order.append(ref)
        grouped[ref].append(
            GoldClaim(
                field_key=field_key,
                expected_value=value
                if not isinstance(value, (bytes, bytearray))
                else parse_value_json(bytes(value)),
                max_source_tier=int(tier) if tier is not None else 3,
                requires_evidence_span=bool(requires_span),
                fixture_kind=FixtureKind(kind),
                mode=ResearchMode(mode) if mode is not None else None,
                expected_source_url=source_url,
            )
        )
    entities = tuple(
        # the entity_type is not stored on the fixture row; a fixture's field-class implies it well
        # enough for scoring (contact.* -> contact, else account), and the harness keys on the id.
        GoldEntity(
            entity_id=EntityId(ref),  # type: ignore[arg-type]
            entity_type=(
                EntityType.CONTACT
                if any(str(c.field_key).startswith("contact") for c in grouped[ref])
                else EntityType.ACCOUNT
            ),
            claims=tuple(grouped[ref]),
        )
        for ref in entity_order
    )
    return GoldSet(name=name, entities=entities)


async def ingest_golden_fixture(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_key: str,
    expected_value: object,
    source_url: str | None,
    expected_tier: int,
    mode: ResearchMode | None = None,
    fixture_kind: FixtureKind = FixtureKind.POSITIVE,
) -> bool:
    """Write one ``golden_fixture`` row — the substrate the human spot-check loop ingests a reviewed
    production claim through (M09 §M9.6: "ingests reviewed results back as new golden fixtures").
    Idempotent (``ON CONFLICT (entity_ref, field_key, fixture_kind) DO NOTHING``). Returns whether a
    row was written (``False`` = a fixture for that ``(entity, field, kind)`` already exists)."""
    result = await conn.execute(
        text(
            """
            INSERT INTO golden_fixture
                (entity_ref, field_key, expected_value_json, expected_source_url, expected_tier,
                 fixture_kind, mode)
            VALUES
                (:entity_ref, :field_key, CAST(:value AS jsonb), :source_url, :tier,
                 CAST(:kind AS fixture_kind), CAST(:mode AS research_mode))
            ON CONFLICT (entity_ref, field_key, fixture_kind) DO NOTHING
            RETURNING id
            """
        ),
        {
            "entity_ref": str(entity_id),
            "field_key": str(field_key),
            "value": serialize_value_json(expected_value),
            "source_url": source_url,
            "tier": int(expected_tier),
            "kind": fixture_kind.value,
            "mode": mode.value if mode is not None else None,
        },
    )
    return result.first() is not None
