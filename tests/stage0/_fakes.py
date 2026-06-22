"""Test doubles for M5 (stage0) — fake resolvers/judge wired through the real seams.

`stage0` cannot import `resolvers`/`adapters` (the import-linter one-way worker seam), so the live
client-knowledge extractor + Firecrawl wiring is api-composition-root integration. The
reverse-profiling *orchestration* is exercised here by binding a fake
:class:`~clue_research.core.resolver.Resolver` to a real seeded ``source_key`` via
``sources.bind_resolver`` — the same dispatch the production waterfall uses — so M5.1's loop,
budget, versioning and coverage are tested end-to-end and deterministically.
Tests (unlike milestone packages) may import anything.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    Claim,
    Completion,
    EmbeddingResult,
    Entity,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    JudgeResult,
    JudgeVerdict,
    Message,
    ResearchMode,
    account_claim,
    new_claim_id,
    new_run_id,
)
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    TierBand,
    TierCutoffs,
    create_icp_spec,
    rubric_to_slot,
)
from clue_research.stage0 import (
    ClientInput,
    ClientKnowledgeBaseRef,
    ICPSpecRef,
    VolunteeredMaterial,
    reverse_profile,
)


class FakeResolver:
    """A :class:`~clue_research.core.resolver.Resolver` that returns a canned claim per field.

    ``values`` maps ``field_key -> value_json``; a field absent from it is a hard miss (``[]``). The
    claim's ``source_tier`` MUST equal the bound manifest's tier (the waterfall asserts it), so a
    fake bound to ``firecrawl_site`` (tier-2) uses ``tier=2``. ``run_id``/``research_mode`` are
    placeholders the waterfall overwrites."""

    def __init__(
        self,
        *,
        tier: int,
        values: dict[str, JsonValue],
        extraction_method: ExtractionMethod = ExtractionMethod.SCRAPE,
        source_url: str | None = "https://client.example",
        confidence: float = 0.9,
        cost_cents: Decimal = Decimal("1.0"),
    ) -> None:
        self.tier = tier
        self._values = values
        self._method = extraction_method
        self._source_url = source_url
        self._confidence = confidence
        self._cost = cost_cents

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if field.field_key not in self._values:
            return []
        return [
            account_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=self._values[field.field_key],
                source_tier=self.tier,
                extraction_method=self._method,
                confidence=self._confidence,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=self._source_url,
                evidence_span="reverse-profiled from the client surface",
                cost_cents=self._cost,
            )
        ]


class FakeCrmResolver:
    """A tier-1 ``crm`` :class:`~clue_research.core.resolver.Resolver` (M5.3 import enrichment).

    Returns a single ``account.crm_relationship_status`` claim (``extraction_method=crm_import``,
    tier-1, no ``source_url``) for every account — modelling the client's CRM. Bound to the ``crm``
    source_key via ``sources.bind_resolver`` (the same dispatch the production waterfall uses); the
    waterfall stamps the claim ``tenant_private`` because ``crm_import`` is a private method."""

    def __init__(self, *, relationship: str = "customer") -> None:
        self.tier = 1
        self._relationship = relationship

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if field.field_key != "account.crm_relationship_status":
            return []
        return [
            account_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=self._relationship,
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=1.0,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                evidence_span="client CRM",
            )
        ]


async def build_confirmed_icp(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str = "primary",
    fit_threshold: float = 0.5,
) -> ICPSpecRef:
    """Create + activate a confirmed ``ICPSpec`` whose fit rubric is the *presence* of a client-CRM
    relationship (``account.crm_relationship_status``, BOOLEAN) with one ``min_fit`` tier band — so
    a CRM-enriched account back-scores FIT and an un-enriched one falls below the floor (NON_FIT).
    Returns the M5.2 :class:`ICPSpecRef` ``import_accounts`` back-scores against."""
    rubric = ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key="account.crm_relationship_status",
                    weight=1.0,
                    transform=ScoringTransform.BOOLEAN,
                ),
            )
        ),
        intent=SubRubric(entries=()),
        tier_cutoffs=TierCutoffs(
            bands=(TierBand(tier="high", min_fit=fit_threshold),),
            fallback_tier="low",
        ),
    )
    spec = await create_icp_spec(
        conn,
        client_id=client_id,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=("account.crm_relationship_status",),
        scoring_rubric=rubric_to_slot(rubric),
        activate=True,
    )
    return ICPSpecRef(client_id=client_id, icp_key=spec.icp_key, icp_version=spec.version)


async def build_confirmed_icp_on_field(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str,
    fit_field: str,
    fit_threshold: float = 0.5,
) -> ICPSpecRef:
    """Like :func:`build_confirmed_icp` but with the fit rubric keyed on an arbitrary registered
    scoring ``fit_field`` (BOOLEAN presence). Used by M5.4's per-ICP partition test: two ICPs keyed
    on different fields make the *same* entity fit one ICP and miss the other, so the seed assembler
    partitions it to the right segment (a healthcare customer seeds only that ICP — D5)."""
    rubric = ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(field_key=fit_field, weight=1.0, transform=ScoringTransform.BOOLEAN),
            )
        ),
        intent=SubRubric(entries=()),
        tier_cutoffs=TierCutoffs(
            bands=(TierBand(tier="high", min_fit=fit_threshold),),
            fallback_tier="low",
        ),
    )
    spec = await create_icp_spec(
        conn,
        client_id=client_id,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=(fit_field,),
        scoring_rubric=rubric_to_slot(rubric),
        activate=True,
    )
    return ICPSpecRef(client_id=client_id, icp_key=spec.icp_key, icp_version=spec.version)


class RecordingJudge:
    """A :class:`~clue_research.core.verification.FaithfulnessJudge` that records the claims it
    judged and returns a fixed verdict (default ``SUPPORTED``)."""

    def __init__(self, verdict: JudgeVerdict = JudgeVerdict.SUPPORTED) -> None:
        self.verdict = verdict
        self.judged: list[Claim] = []

    async def judge(self, claim: Claim) -> JudgeResult:
        self.judged.append(claim)
        return JudgeResult(
            claim_id=claim.id,
            verdict=self.verdict,
            score=0.9,
            rationale="fake",
        )


class FakeGateway:
    """A :class:`~clue_research.core.LLMGateway` returning a canned completion (M5.2 synthesis).

    ``text`` is the (JSON) body ``complete`` returns; ``raise_exc`` makes ``complete`` raise so the
    graceful-degradation-to-floor path is exercised. ``calls`` records the (model, messages) of each
    call so a test can assert the model id / that the prompt was bounded. ``embed`` is unused by
    M5.2 (synthesis is a completion call) — it returns an empty result."""

    def __init__(self, text: str = "", *, raise_exc: bool = False) -> None:
        self._text = text
        self._raise = raise_exc
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, messages))
        if self._raise:
            raise RuntimeError("synthetic gateway failure")
        return Completion(model=model, text=self._text)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model)


async def build_client_kb(
    conn: AsyncConnection,
    *,
    client_id: str,
    suffix: str,
    asserted: dict[str, JsonValue],
) -> ClientKnowledgeBaseRef:
    """Build a versioned Client Knowledge Base by reverse-profiling a fresh client whose volunteered
    deck asserts ``asserted`` (``client.*`` field_key -> value) — high-trust tier-1 claims. A unique
    ``suffix`` gives a brand-new client entity (no resolver needed; the waterfall simply misses the
    un-asserted fields). Returns the M5.1 :class:`ClientKnowledgeBaseRef` M5.2 reads from."""
    result = await reverse_profile(
        conn,
        ClientInput(
            name=f"Synth Co {suffix}",
            website=f"https://synth-{suffix}.example",
            materials=(
                VolunteeredMaterial(
                    kind="deck",
                    label="pitch deck",
                    content="client-volunteered facts",
                    asserted_fields=asserted,
                ),
            ),
        ),
        client_id=client_id,
    )
    return result.ref


def make_tier4_claim(entity_id: object, field_key: str, *, with_span: bool) -> Claim:
    """A tier-4 LLM-synthesis claim (optionally span-less) for promotion/merge tests."""
    return Claim(
        id=new_claim_id(),
        entity_id=entity_id,  # type: ignore[arg-type]
        entity_type="account",  # type: ignore[arg-type]
        field_key=field_key,
        value_json="synthesized value",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        evidence_span="grounded span" if with_span else None,
        confidence=0.7,
        source_url="https://synth.example",
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )
