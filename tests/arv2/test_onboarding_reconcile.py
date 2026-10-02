"""The catalog reconciler: fixed prompt + strict schema, decisions validated, never raises."""

from __future__ import annotations

import asyncio
import json

from pydantic import SecretStr

from clue_api.arv2.onboarding_lineage import CatalogProduct
from clue_api.arv2.onboarding_reconcile import (
    RECONCILE_SYSTEM_PROMPT,
    ExistingProduct,
    OpenRouterCatalogReconciler,
    reconcile_output_schema,
)

EXISTING = (
    ExistingProduct(
        "prd_1",
        "Referrals AI Agent",
        (),
        "https://x.io/referral-management",
        "AI referral-management product.",
    ),
    ExistingProduct(
        "prd_2",
        "Aura AI Scribe",
        ("Aura",),
        "https://x.io/ambient",
        "Ambient clinical documentation.",
    ),
)
CANDIDATES = (
    CatalogProduct(
        name="Referral Management AI Agent",
        short_description="Automates referral processing.",
        aliases=(),
        official_url="https://x.io/referral-management",
    ),
    CatalogProduct(
        name="HEDIS AI Workflows",
        short_description="HEDIS screening coordination.",
        aliases=(),
        official_url="https://x.io/hedis",
    ),
    CatalogProduct(
        name="Referral Mgmt Agent",
        short_description="Automates referral processing.",
        aliases=(),
        official_url=None,
    ),
)


def _answer(decisions: list[dict]) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({"decisions": decisions})}}],
        "usage": {"cost": 0.0012, "prompt_tokens": 900, "completion_tokens": 200},
        "id": "gen_x",
    }


def test_the_request_carries_the_fixed_prompt_the_strict_schema_and_both_lists(
    make_caller, scripted_transport
) -> None:
    transport = scripted_transport(
        status=200,
        body=_answer(
            [
                {
                    "candidate": "Referral Management AI Agent",
                    "decision": "same_as_existing",
                    "product_id": "prd_1",
                    "candidate_name": None,
                    "confidence": "high",
                    "reason": "same page and job",
                },
                {
                    "candidate": "HEDIS AI Workflows",
                    "decision": "new_product",
                    "product_id": None,
                    "candidate_name": None,
                    "confidence": "high",
                    "reason": "distinct page",
                },
                {
                    "candidate": "Referral Mgmt Agent",
                    "decision": "same_as_candidate",
                    "product_id": None,
                    "candidate_name": "Referral Management AI Agent",
                    "confidence": "medium",
                    "reason": "same description",
                },
            ]
        ),
    )
    reconciler = OpenRouterCatalogReconciler(
        caller_factory=lambda: make_caller(transport),
        api_key=SecretStr("k"),
        model="openai/gpt-5-mini",
        base_url="https://openrouter.ai/api/v1",
    )
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    body = transport.requests[0].json_body
    assert body["model"] == "openai/gpt-5-mini" and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": RECONCILE_SYSTEM_PROMPT}
    payload = json.loads(body["messages"][1]["content"])
    assert [p["product_id"] for p in payload["products_on_file"]] == ["prd_1", "prd_2"]
    assert [c["name"] for c in payload["candidates"]] == [c.name for c in CANDIDATES]
    assert body["response_format"]["json_schema"]["schema"] == reconcile_output_schema()
    assert [d.decision for d in decisions] == [
        "same_as_existing",
        "new_product",
        "same_as_candidate",
    ]
    assert decisions[0].product_id == "prd_1"
    assert decisions[2].candidate_name == "Referral Management AI Agent"


def test_an_invalid_reference_or_missing_candidate_degrades_to_new_low(
    make_caller, scripted_transport
) -> None:
    transport = scripted_transport(
        status=200,
        body=_answer(
            [
                {
                    "candidate": "Referral Management AI Agent",
                    "decision": "same_as_existing",
                    "product_id": "prd_404",
                    "candidate_name": None,
                    "confidence": "high",
                    "reason": "x",
                },
                # HEDIS omitted entirely; Referral Mgmt points at itself
                {
                    "candidate": "Referral Mgmt Agent",
                    "decision": "same_as_candidate",
                    "product_id": None,
                    "candidate_name": "Referral Mgmt Agent",
                    "confidence": "high",
                    "reason": "x",
                },
            ]
        ),
    )
    reconciler = OpenRouterCatalogReconciler(
        caller_factory=lambda: make_caller(transport),
        api_key=SecretStr("k"),
        model="m",
        base_url="https://o",
    )
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    assert [(d.candidate, d.decision, d.confidence) for d in decisions] == [
        ("Referral Management AI Agent", "new_product", "low"),
        ("HEDIS AI Workflows", "new_product", "low"),
        ("Referral Mgmt Agent", "new_product", "low"),
    ]
    assert all(d.reason.startswith("reconciler_invalid") for d in decisions)


def test_a_provider_failure_never_raises(make_caller, scripted_transport) -> None:
    transport = scripted_transport(status=500, body={"error": "boom"})
    reconciler = OpenRouterCatalogReconciler(
        caller_factory=lambda: make_caller(transport),
        api_key=SecretStr("k"),
        model="m",
        base_url="https://o",
    )
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    assert len(decisions) == 3
    assert all(
        d.decision == "new_product"
        and d.confidence == "low"
        and d.reason.startswith("reconciler_unavailable")
        for d in decisions
    )


def test_with_no_existing_products_and_one_candidate_no_call_is_made(
    make_caller, scripted_transport
) -> None:
    transport = scripted_transport(status=200, body=_answer([]))
    reconciler = OpenRouterCatalogReconciler(
        caller_factory=lambda: make_caller(transport),
        api_key=SecretStr("k"),
        model="m",
        base_url="https://o",
    )
    decisions = asyncio.run(reconciler.reconcile(existing=(), candidates=CANDIDATES[:1]))
    assert transport.requests == [] and [d.decision for d in decisions] == ["new_product"]
