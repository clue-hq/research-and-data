"""E1 wire-contract tests for Exa CSV imports and import-only Websets."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import SecretStr

from clue_research.adapters.exa_websets import (
    ExaCreateEnrichment,
    ExaCreateImportRef,
    ExaCreateImportRequest,
    ExaCreateWebsetRequest,
    ExaWebsetEnrichmentFormat,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetsClient,
)


def _import_response() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": "import_e1_wire",
        "object": "import",
        "status": "pending",
        "format": "csv",
        "entity": {"type": "company"},
        "title": "Selected accounts",
        "count": 1,
        "metadata": {"clueFingerprint": "a" * 64},
        "failedReason": None,
        "failedAt": None,
        "failedMessage": None,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "uploadUrl": "https://upload.example.invalid/csv?signature=secret-value",
        "uploadValidUntil": (now + timedelta(hours=1)).isoformat(),
    }


def test_import_create_and_upload_use_exact_distinct_auth_boundaries() -> None:
    async def scenario() -> None:
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST" and request.url.path.endswith("/imports"):
                return httpx.Response(201, json=_import_response(), request=request)
            if request.method == "PUT" and request.url.host == "upload.example.invalid":
                return httpx.Response(200, request=request)
            raise AssertionError(f"unexpected request {request.method} {request.url}")

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = ExaWebsetsClient(api_key=SecretStr("exa-test-secret"), client=http)
        request = ExaCreateImportRequest(
            size=31,
            count=1,
            entity=ExaWebsetEntity(type=ExaWebsetEntityType.COMPANY),
            title="Selected accounts",
            metadata={"clueFingerprint": "a" * 64},
        )
        exchange = await client.create_import(request)
        csv_bytes = b"url\nhttps://insighthealth.ai/\n"
        await client.upload_import_csv(upload_url=exchange.response.upload_url, content=csv_bytes)
        await http.aclose()

        assert len(seen) == 2
        assert seen[0].headers["x-api-key"] == "exa-test-secret"
        # Independent provider-contract oracle.  Do not compare the transport with the same
        # serializer that produced its body: that allowed the required CSV discriminator to
        # disappear while this test remained green.
        assert json.loads(seen[0].content) == {
            "size": 31,
            "count": 1,
            "format": "csv",
            "entity": {"type": "company"},
            "title": "Selected accounts",
            "csv": {"identifier": 0},
            "metadata": {"clueFingerprint": "a" * 64},
        }
        assert seen[0].content == request.canonical_bytes()
        assert "x-api-key" not in seen[1].headers
        assert seen[1].headers["content-type"] == "text/csv"
        assert seen[1].content == csv_bytes
        assert "secret-value" not in repr(exchange)
        assert b"secret-value" not in exchange.response.sanitized_bytes()

    asyncio.run(scenario())


def test_import_only_webset_serializes_import_singular_and_no_search() -> None:
    request = ExaCreateWebsetRequest(
        imports=(ExaCreateImportRef(source="import", id="import_e1_wire"),),
        enrichments=(
            ExaCreateEnrichment(
                description="Find the official LinkedIn company URL.",
                format=ExaWebsetEnrichmentFormat.URL,
                metadata={"clueFieldKey": "core.company_linkedin_url"},
            ),
        ),
        external_id="clue-e1-" + "b" * 64,
        metadata={"clueOperationKind": "targeted_import_enrichment"},
    )

    payload = json.loads(request.canonical_bytes())
    assert payload["import"] == [{"id": "import_e1_wire", "source": "import"}]
    assert "imports" not in payload
    assert "search" not in payload
    assert payload["enrichments"][0]["metadata"]["clueFieldKey"] == ("core.company_linkedin_url")
