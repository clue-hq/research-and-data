"""exa_search_evidence@1: fixed request, bounded output, refusals before spend (plan §4.5)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaDeepResult
from clue_api.onboarding_evidence_tools import (
    EXA_SEARCH_EVIDENCE_TOOL_NAME,
    ExaSearchEvidenceInput,
    ExaSearchEvidenceOutput,
    ExaSearchEvidenceTool,
)
from clue_core import operation_id_from_key
from clue_toolbelt import ToolContext, ToolEffectClass
from tests.arv2.test_provider_ledger_db import FakeArtifacts


@asynccontextmanager
async def _no_db() -> AsyncIterator[None]:
    """The drain executes no SQL when nothing was buffered; the offline fakes buffer nothing."""
    yield None


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-evidence",
        actor="agent",
        conn_factory=_no_db,  # type: ignore[arg-type]
        operation_id=operation_id_from_key("o4-evidence", "test"),
    )


def _deep(passages: object, grounding: object) -> ExaDeepResult:
    cost = CallCost(
        cost_usd=Decimal("0.015"),
        credits=Decimal(0),
        media_seconds=0,
        cost_source="metered",
        provider="exa",
        operation="deep-reasoning",
        raw_ref="raw/e",
        ledger_row_id="row-e",
    )
    return ExaDeepResult(
        output_text="{}",
        output_object={"passages": passages},
        report_text=None,
        grounding=grounding,
        results=(),
        status=200,
        cost_usd=Decimal("0.015"),
        request_id="req_e",
        raw_ref="raw/e",
        ledger_row_id="row-e",
        cost=cost,
        retried=False,
    )


class FakeExa:
    def __init__(self, result: ExaDeepResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def deep_reasoning(self, **kw: object) -> ExaDeepResult:
        self.calls.append(kw)
        return self.result


def test_descriptor_is_spend_typed_recipe_safe_and_pinned() -> None:
    tool = ExaSearchEvidenceTool(enabled=True, client_factory=None, artifacts=None)
    d = tool.descriptor
    assert d.name == EXA_SEARCH_EVIDENCE_TOOL_NAME and d.version == "1"
    assert d.effect_class is ToolEffectClass.SPEND
    assert d.recipe_safe and d.replay.operation_id_required
    assert d.pin_requirements == ("skill",)
    assert d.parameter_policy.safe_display_fields == ("query", "num_results")


@pytest.mark.parametrize(
    ("enabled", "factory", "artifacts", "code"),
    [
        (
            False,
            lambda label, raw, ledger: FakeExa(_deep([], [])),
            FakeArtifacts(),
            "persona_evidence_disabled",
        ),
        (True, None, FakeArtifacts(), "exa_not_configured"),
        (True, lambda label, raw, ledger: FakeExa(_deep([], [])), None, "artifacts_not_configured"),
    ],
)
def test_it_refuses_before_spend_when_off_or_unconfigured(
    enabled: bool, factory: object, artifacts: object, code: str
) -> None:
    async def scenario() -> None:
        tool = ExaSearchEvidenceTool(enabled=enabled, client_factory=factory, artifacts=artifacts)  # type: ignore[arg-type]
        failures = await tool.preconditions(
            ExaSearchEvidenceInput(query="pain of practice managers"), _ctx()
        )
        assert [f.reason_code for f in failures] == [code]

    asyncio.run(scenario())


def test_it_sends_the_fixed_template_and_maps_grounding_onto_passages() -> None:
    async def scenario() -> None:
        fake = FakeExa(
            _deep(
                [
                    {
                        "quote": "We lose two hours a day to faxes.",
                        "speaker_role": "Practice manager",
                        "org_type": "GI practice",
                        "topic": "pain",
                    },
                    {
                        "quote": "Prior auth is the bottleneck.",
                        "speaker_role": "Referral coordinator",
                    },
                ],
                [
                    {
                        "field": "passages[0].quote",
                        "citations": [{"url": "https://r.example/1", "title": "Reddit thread"}],
                        "confidence": "high",
                    },
                    {
                        "field": "passages[1]",
                        "citations": [{"url": "https://r.example/2", "title": "Forum"}],
                        "confidence": "medium",
                    },
                ],
            )
        )
        tool = ExaSearchEvidenceTool(
            enabled=True, client_factory=lambda label, raw, ledger: fake, artifacts=FakeArtifacts()
        )
        ctx = _ctx()
        inputs = ExaSearchEvidenceInput(
            query="how practice managers describe referral fax pain",
            include_domains=["reddit.com"],
            num_results=4,
        )
        assert await tool.preconditions(inputs, ctx) == ()
        result = await tool.invoke(inputs, ctx)
        output = ExaSearchEvidenceOutput.model_validate(result.references)
        assert [p.url for p in output.passages] == [
            "https://r.example/1",
            "https://r.example/2",
        ]
        assert output.passages[0].title == "Reddit thread"
        assert output.passages[1].org_type is None
        assert output.cost_usd == "0.015" and output.request_id == "req_e"
        call = fake.calls[0]
        from clue_api.arv2.onboarding_requests import (
            PERSONA_EVIDENCE_SYSTEM_PROMPT,
            persona_evidence_output_schema,
        )

        assert call["system_prompt"] == PERSONA_EVIDENCE_SYSTEM_PROMPT
        assert call["output_schema"] == persona_evidence_output_schema()
        assert call["include_domains"] == ["reddit.com"] and call["num_results"] == 4
        assert call["label"].startswith("exa_search_evidence:")

    asyncio.run(scenario())


def test_an_empty_or_unparseable_answer_is_an_empty_list_never_an_error() -> None:
    async def scenario() -> None:
        fake = FakeExa(_deep(None, None))
        fake.result = ExaDeepResult(**{**fake.result.__dict__, "output_object": None})
        tool = ExaSearchEvidenceTool(
            enabled=True, client_factory=lambda label, raw, ledger: fake, artifacts=FakeArtifacts()
        )
        result = await tool.invoke(ExaSearchEvidenceInput(query="q"), _ctx())
        assert ExaSearchEvidenceOutput.model_validate(result.references).passages == []

    asyncio.run(scenario())


def test_input_bounds_are_enforced_by_the_schema() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="x" * 401)
    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="q", num_results=11)
    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="q", include_domains=["a"] * 6)
