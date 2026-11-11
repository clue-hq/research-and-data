"""The treg client: one paid call through the spend wrapper, cost read from treg's own header."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from clue_api.footprint.treg_client import TregReply, treg_call
from clue_config.secrets import Secrets
from clue_spend import redact_headers
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderHalted, ProviderTransportError
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport

TOKEN = SecretStr("treg-secret-token")


def wire(*responses):
    transport = ScriptedTransport(list(responses))
    raw, ledger = MemoryRawSink(), MemoryLedger()
    caller = ProviderCaller(
        transport=transport,
        raw_sink=raw,
        ledger=ledger,
        now=lambda: datetime.now(UTC),
        sleep=lambda _: None,
    )
    return caller, transport, raw, ledger


def reply(body, status=200, cost_micro="1500"):
    headers = {"content-type": "application/json", "X-Treg-Call-Id": "call-1"}
    if cost_micro is not None:
        headers["X-Treg-Cost-Micro"] = cost_micro
    return HttpResponse(status, headers, json.dumps(body).encode())


def test_cost_comes_from_header():
    caller, transport, _, ledger = wire(reply({"posts": []}))
    out = treg_call(caller, TOKEN, "fetchinio.linkedin.user.posts", {"profileUrlOrUrn": "x"})
    assert isinstance(out, TregReply)
    assert out.cost_usd == 0.0015 and out.status == 200 and out.call_id == "call-1"
    assert out.body == {"posts": []}
    sent = transport.requests[0]
    assert sent.url.startswith("https://treg.to/call/fetchinio.linkedin.user.posts?")
    assert "profileUrlOrUrn=x" in sent.url
    result_rows = [r for r in ledger.rows if r.phase == "result"]
    assert result_rows[0].cost_usd == Decimal("0.0015")


def test_provider_4xx_is_returned_not_raised():
    caller, *_ = wire(reply({"message": "Company not found"}, status=404, cost_micro="0"))
    out = treg_call(caller, TOKEN, "scrapecreators.x.v1-linkedin-company-posts", {"url": "u"})
    assert out.status == 404 and out.cost_usd == 0 and out.body == {"message": "Company not found"}


def test_5xx_raises_transport_error():
    caller, *_ = wire(*[reply({"error": "down"}, status=503, cost_micro=None)] * 5)
    with pytest.raises(ProviderTransportError):
        treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "illumio"})


def test_token_never_in_ledger_row():
    caller, transport, raw, ledger = wire(reply({"ok": True}))
    treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "illumio"})
    assert transport.requests[0].headers["X-Treg-Token"] == "treg-secret-token"
    persisted = (
        json.dumps([str(r) for r in ledger.rows])
        + json.dumps([str(rec) for rec, _ in raw.records])
        + "".join(body.decode(errors="ignore") for _, body in raw.records)
    )
    assert "treg-secret-token" not in persisted
    assert redact_headers({"X-Treg-Token": "t"})["X-Treg-Token"] == "***"


def test_treg_key_loads_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLUE_TREG_API_KEY", "abc")
    assert Secrets(_env_file=None).treg_api_key.get_secret_value() == "abc"


# --- treg's own refusals (shapes probed live 2026-11-11) ---------------------------------------


def treg_refusal(status, detail):
    return HttpResponse(
        status,
        {"content-type": "application/json", "X-Treg-Error": "1", "X-Treg-Call-Id": "call-1"},
        json.dumps({"detail": detail}).encode(),
    )


def test_out_of_credit_stops_treg():
    """A 402 means treg will not sell: the call raises and every later treg call on this caller is
    refused without touching the wire (money truth blocks, as for Exa and AI Ark)."""
    caller, transport, _, ledger = wire(treg_refusal(402, "insufficient_balance"), reply({}))
    with pytest.raises(ProviderHalted) as first:
        treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "ada"})
    assert first.value.reason_code == "payment_required"
    with pytest.raises(ProviderHalted):
        treg_call(caller, TOKEN, "fetchinio.linkedin.user.posts", {"profileUrlOrUrn": "x"})
    assert len(transport.requests) == 1
    assert [r.outcome for r in ledger.rows if r.phase == "result"] == ["halted"]


def test_refused_key_stops_treg():
    caller, *_ = wire(treg_refusal(401, "invalid token"))
    with pytest.raises(ProviderHalted) as halted:
        treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "ada"})
    assert halted.value.reason_code == "auth_invalid"


def test_a_relayed_provider_401_does_not_stop_treg():
    """Only treg's own refusal (marked X-Treg-Error) is about our key; a provider's 401 relayed
    through treg is that provider's answer."""
    caller, *_ = wire(reply({"message": "unauthorized"}, status=401, cost_micro="0"))
    out = treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "ada"})
    assert out.status == 401 and out.treg_error is False


def test_treg_error_mark_is_kept():
    caller, *_ = wire(treg_refusal(403, "capability_pinned"))
    out = treg_call(caller, TOKEN, "tikhub.x.user.posts", {"screen_name": "ada"})
    assert out.status == 403 and out.treg_error is True
