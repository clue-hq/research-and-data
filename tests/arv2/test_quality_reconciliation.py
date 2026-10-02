"""Focused routing preserves evidence and rejects ambiguous local citations."""

from uuid import uuid4

import pytest

from clue_api.arv2.display.recipes import SYSTEM_RECIPES
from clue_api.arv2.quality_reconciliation import PROMPT, parse_updates
from clue_api.arv2.quality_reconciliation_routing import (
    candidate_sections,
    compact_claim,
    replace_citations,
)


def test_unknown_topics_are_considered_not_dropped():
    recipes = [r for r in SYSTEM_RECIPES if r.page != "contact" and r.shared_from is None]
    result = candidate_sections(
        {"field_key": "contact.research_finding", "value": {"topic": "unclassified"}}, recipes
    )
    assert result == {f"{r.page}/{r.section_key}" for r in recipes}
    voice = candidate_sections(
        {"field_key": "contact.research_finding", "value": {"topic": "public statement"}}, recipes
    )
    assert "overview/why-they-fit" in voice and "insights/buying-signals" in voice


def test_original_wording_and_qualifications_survive_compaction():
    text = 'John Doe: "Keep the precise words and the important constraint."'
    claim = compact_claim(
        {
            "id": uuid4(),
            "entity_id": uuid4(),
            "field_key": "contact.research_finding",
            "value_json": {
                "finding": text,
                "qualifications": ["Historical"],
                "dossier_entry": {"original": {"finding": text}, "section": "Public voice"},
            },
            "source_url": "https://example.test/post",
            "evidence_span": text,
            "conclusion": "uncertain",
            "superseded_by": None,
        }
    )
    assert claim["value"]["finding"] == text
    assert claim["value"]["qualifications"] == ["Historical"]
    assert claim["value"]["section"] == "Public voice"
    assert "dossier_entry" not in claim["value"]


def test_local_aliases_and_section_ownership():
    id = str(uuid4())
    packet = {
        "aliases": {"C1": id},
        "allowed_sections": ["overview/why-they-fit"],
        "input": {"unavailable_claims": [], "people": []},
    }
    update = {
        "page": "overview",
        "section": {"key": "why-they-fit", "intro": [{"text": "Quoted words", "claimIds": ["C1"]}]},
    }
    assert str(parse_updates({"updates": [update]}, packet)[0][1].intro[0].claim_ids[0]) == id
    assert parse_updates({"updates": []}, packet) == []
    with pytest.raises(ValueError, match="unique supplied"):
        parse_updates({"updates": [update, update]}, packet)
    with pytest.raises(ValueError, match="Unknown citation"):
        replace_citations({"claimIds": ["C999"]}, {"C1": id})
    packet["input"]["unavailable_claims"] = ["C1"]
    with pytest.raises(ValueError, match="unavailable"):
        parse_updates({"updates": [update]}, packet)
    assert PROMPT.is_file()


@pytest.mark.parametrize("malformed", [False, True])
def test_model_uses_pinned_prompt_shared_meter_and_trace_even_on_bad_reply(monkeypatch, malformed):
    import asyncio
    import json
    from contextlib import asynccontextmanager, contextmanager
    from decimal import Decimal
    from types import SimpleNamespace

    from pydantic import SecretStr

    from clue_api.arv2 import quality_reconciliation_model as model
    from clue_spend import calls
    from clue_spend.errors import RawParseError
    from clue_spend.transport import HttpResponse

    seen, drained, traces = [], [], []
    original_observation = calls.observation

    @contextmanager
    def observation(name, **kwargs):
        traces.append((name, kwargs["as_type"]))
        with original_observation(name, **kwargs) as span:
            yield span

    class Transport:
        def send(self, request):
            seen.append(json.loads(request.body))
            return HttpResponse(
                status=200,
                body=json.dumps(
                    {
                        "id": "offline-provider-request",
                        "model": "offline-editor",
                        "choices": [
                            {
                                "message": {
                                    "content": "invalid-json" if malformed else '{"updates": []}'
                                }
                            }
                        ],
                        "usage": {"cost": "0.012", "prompt_tokens": 12, "completion_tokens": 3},
                    }
                ).encode(),
            )

    @asynccontextmanager
    async def connection():
        yield None

    async def drain(conn, *, raw, ledger, artifacts, stamp):
        drained.extend(ledger.rows)
        assert raw.drain() and stamp.workspace_id == "test-workspace"

    monkeypatch.setattr(model, "HttpxTransport", Transport)
    monkeypatch.setattr(model, "drain_provider_calls", drain)
    monkeypatch.setattr(calls, "observation", observation)
    scope = SimpleNamespace(workspace_id="test-workspace", project_id="project", job_id=uuid4())
    generate = model.build_generator(
        SimpleNamespace(arv2_display_model="offline-editor", arv2_display_timeout_s=180),
        SimpleNamespace(openrouter_api_key=SecretStr("test-only")),
        connection,
        None,
    )
    packet = {
        "_editorial_system": "Exact pinned instructions",
        "_execution_id": str(uuid4()),
        "changed": ["C1"],
    }
    if malformed:
        with pytest.raises(RawParseError):
            asyncio.run(generate(scope, packet))
    else:
        assert asyncio.run(generate(scope, packet)) == {"updates": []}
    assert len(seen) == 1
    assert seen[0]["messages"][0]["content"] == "Exact pinned instructions"
    assert json.loads(seen[0]["messages"][1]["content"]) == {"changed": ["C1"]}
    assert any(row.cost_usd == Decimal("0.012") for row in drained)
    assert ("openrouter.chat/completions", "generation") in traces
