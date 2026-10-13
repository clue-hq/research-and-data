"""B7 (Lane B Task 17): a site request's spend and model calls land where every design turn's do."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage

from clue_spend import HttpRequest, HttpResponse, LedgerStamp
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.site.harness import run_site_turn
from lumen_api import spend
from site_fixtures import FakeAssets, ScriptedModel, call, garner_site, inputs_for, png


class _Transport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.sent: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return self.responses.pop(0)


def _priced(cost: float) -> HttpResponse:
    body = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": cost}, "model": "test/image"}
    return HttpResponse(status=200, body=json.dumps(body).encode())


def test_an_image_made_inside_a_request_is_charged_to_the_requests_scope(tmp_path: Path) -> None:
    seen: list = []

    def generate(**kwargs):
        # The provider's own path: one priced call through the open scope's caller.
        seen.append(spend.current_scope())
        spend.openrouter_call(operation="design.site.generate_image", body={"model": "test/image"},
                              label="site image", timeout_s=1, api_key="k", base_url="https://or.example/api/v1")
        return SimpleNamespace(image_bytes=png("white", (64, 36)), mime_type="image/png", width=64, height=36,
                               model="test/image", provenance={}, license=None)

    model = ScriptedModel(messages=iter([
        AIMessage(content="", tool_calls=[call("generate_image", {"prompt": "A calm classroom, morning light"}, 1)]),
        AIMessage(content="Made one image."),
    ]))
    with spend.spend_scope(LedgerStamp(workspace_id="ws_site", job_id=uuid4()), transport=_Transport([_priced(0.04)])) as scope:
        run_site_turn("Add a hero image.", config=AgentRuntimeConfig.from_env(),
                      inputs=inputs_for(assets=FakeAssets(), image_generate=generate),
                      workspace=tmp_path / "workspace", site=garner_site(), run_id="run_cost", model=model)
    assert seen == [scope], "generate_image ran outside the request's spend scope"
    assert [row.phase for row in scope.ledger.rows if row.phase == "result"] == ["result"]
    assert scope.caller.totals().usd == Decimal("0.04")


def test_the_site_model_is_labelled_design_site_at_the_gateway(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent import harness as platform_harness

    built: list[tuple[str, str]] = []

    def fresh(runtime_config, model_id, *, role):
        built.append((model_id, role))
        return ScriptedModel(messages=iter([AIMessage(content="Nothing to change.")]))

    monkeypatch.setattr(platform_harness, "_fresh_model", fresh)
    config = AgentRuntimeConfig.from_env()
    run_site_turn("Look only.", config=config, inputs=inputs_for(), workspace=tmp_path / "workspace",
                  site=garner_site(), run_id="run_role")
    # One orchestrator model, the configured one (never a new model env), labelled for usage capture.
    assert built == [(config.orchestrator_model, "design_site")]
