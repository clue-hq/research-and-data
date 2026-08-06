"""Sumble MCP transport, governance, spend safety, and dynamic binding tests."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from clue_core import Entity, EntityType, FieldDef, PassKind, new_entity_id, new_run_id
from clue_research.resolvers.sumble.mcp_adapter import (
    GovernedSumbleMcpAdapter,
    MappingSumbleMcpSnapshotLookup,
    SumbleMcpAcquireResult,
    SumbleMcpAcquireState,
    SumbleMcpDurableAuthorization,
    SumbleMcpFieldBinding,
    SumbleMcpGovernanceError,
    SumbleMcpInvocationOutcome,
    SumbleMcpInvocationPlan,
    SumbleMcpPolicy,
    SumbleMcpSchemaError,
    SumbleMcpSettlementMode,
    SumbleMcpSettlementRule,
    SumbleMcpSnapshot,
    SumbleMcpSnapshotResolver,
    SumbleMcpSpendOutcomeUnknown,
    SumbleMcpToolClass,
    validate_sumble_mcp_arguments,
)
from clue_research.resolvers.sumble.mcp_client import (
    McpHttpResponse,
    StaticSumbleMcpAccessTokenProvider,
    SumbleMcpAuthenticationRequired,
    SumbleMcpClient,
    SumbleMcpProtocolError,
    SumbleMcpToolCatalog,
    SumbleMcpToolDescriptor,
    SumbleMcpToolExchange,
    SumbleMcpToolResult,
)
from tests.db.conftest import run_async

_FIND_ORGANIZATIONS = "FindMatchAnd" + "EnrichOrganizations"
_GET_TECH_STACK = "GetOrganization" + "TechStack"
_FIND_PEOPLE = "FindMatchAnd" + "EnrichPeople"
_UPDATE_PRIORITY_RELEVANCE = "UpdatePriority" + "SignalRelevance"
_LIVE_PROBE_REF = "CLUE_SUMBLE_MCP_" + "LIVE_AUTH_PROBE"
_MCP_POLICY_VERSION = "sumble-mcp-" + "governance-v1"
_INVALID_PROBE_TOKEN = "deliberately-invalid-" + "zero-spend-probe"


def _response(
    payload: object,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> McpHttpResponse:
    return McpHttpResponse(
        status_code=status,
        headers=headers or {"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


class ScriptedTransport:
    def __init__(self, responses: list[McpHttpResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: Any, body: bytes) -> McpHttpResponse:
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body)})
        return self.responses.pop(0)


def _initialize(request_id: int = 1) -> McpHttpResponse:
    return _response(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "sumble", "version": "2026.08"},
            },
        },
        headers={"content-type": "application/json", "mcp-session-id": "session-1"},
    )


def _descriptor(name: str = _FIND_ORGANIZATIONS) -> SumbleMcpToolDescriptor:
    return SumbleMcpToolDescriptor(
        name=name,
        description="Find and enrich organizations",
        inputSchema={
            "type": "object",
            "required": ["reason", "organizations"],
            "additionalProperties": False,
            "properties": {
                "reason": {"type": "string", "minLength": 1},
                "organizations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1000,
                    "items": {
                        "type": "object",
                        "required": ["url"],
                        "additionalProperties": False,
                        "properties": {"url": {"type": "string"}},
                    },
                },
            },
        },
        outputSchema={"type": "object"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    )


def test_client_initializes_paginates_pins_catalog_and_uses_session() -> None:
    transport = ScriptedTransport(
        [
            _initialize(),
            _response({}, status=202),
            _response(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [_descriptor().model_dump(mode="json")],
                        "nextCursor": "page-2",
                    },
                }
            ),
            _response(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {"tools": [_descriptor(_GET_TECH_STACK).model_dump(mode="json")]},
                }
            ),
        ]
    )
    client = SumbleMcpClient(
        token_provider=StaticSumbleMcpAccessTokenProvider(SecretStr("oauth-secret")),
        transport=transport,
    )

    catalog = run_async(client.list_tools())

    assert [tool.name for tool in catalog.tools] == [
        _FIND_ORGANIZATIONS,
        _GET_TECH_STACK,
    ]
    assert len(catalog.fingerprint) == 64
    assert transport.calls[0]["body"]["method"] == "initialize"
    assert transport.calls[1]["body"]["method"] == "notifications/initialized"
    assert transport.calls[2]["body"]["method"] == "tools/list"
    assert transport.calls[3]["body"]["params"] == {"cursor": "page-2"}
    assert all(
        call["headers"]["authorization"] == "Bearer oauth-secret" for call in transport.calls
    )
    assert "mcp-session-id" not in transport.calls[0]["headers"]
    assert all(call["headers"].get("mcp-session-id") == "session-1" for call in transport.calls[1:])


def test_client_parses_sse_and_accepts_only_deterministic_tool_payload() -> None:
    tool_body = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "content": [{"type": "text", "text": "ignored narrative"}],
            "structuredContent": {
                "id": "req-1",
                "credits_used": 2,
                "credits_remaining": 98,
                "organizations": [{"employee_count": 125}],
            },
            "isError": False,
        },
    }
    transport = ScriptedTransport(
        [
            _initialize(),
            _response({}, status=202),
            McpHttpResponse(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                body=(f"event: message\ndata: {json.dumps(tool_body)}\n\n").encode(),
            ),
        ]
    )
    client = SumbleMcpClient(
        token_provider=StaticSumbleMcpAccessTokenProvider(SecretStr("fixture")),
        transport=transport,
    )

    exchange = run_async(
        client.call_tool(
            _FIND_ORGANIZATIONS,
            {
                "reason": "Resolve one account for MCP contract testing",
                "organizations": [{"url": "acme.example"}],
            },
        )
    )

    assert exchange.payload["credits_used"] == 2  # type: ignore[index]
    assert exchange.session_id == "session-1"
    assert len(transport.calls) == 3

    with pytest.raises(SumbleMcpProtocolError, match="narrative"):
        SumbleMcpToolResult(
            content=({"type": "text", "text": "The company has around 125 people."},)
        ).deterministic_payload()


def test_client_surfaces_oauth_resource_without_leaking_token() -> None:
    challenge = (
        'Bearer error="invalid_token", resource_metadata="https://mcp.sumble.com/'
        '.well-known/oauth-protected-resource"'
    )
    transport = ScriptedTransport(
        [_response({}, status=401, headers={"www-authenticate": challenge})]
    )
    client = SumbleMcpClient(
        token_provider=StaticSumbleMcpAccessTokenProvider(SecretStr("do-not-leak")),
        transport=transport,
    )

    with pytest.raises(SumbleMcpAuthenticationRequired) as caught:
        run_async(client.initialize())

    assert caught.value.resource_metadata_url == (
        "https://mcp.sumble.com/.well-known/oauth-protected-resource"
    )
    assert "do-not-leak" not in str(caught.value)


@pytest.mark.skipif(
    os.environ.get(_LIVE_PROBE_REF) != "1",
    reason="set CLUE_SUMBLE_MCP_LIVE_AUTH_PROBE=1 for the zero-spend live catalog probe",
)
def test_live_sumble_mcp_endpoint_negotiates_and_advertises_the_pinned_tools() -> None:
    client = SumbleMcpClient(
        token_provider=StaticSumbleMcpAccessTokenProvider(SecretStr(_INVALID_PROBE_TOKEN))
    )

    initialized = run_async(client.initialize())
    catalog = run_async(client.list_tools())

    assert initialized.protocolVersion == "2025-06-18"
    assert initialized.serverInfo.name == "Sumble"
    names = {tool.name for tool in catalog.tools}
    assert {
        _FIND_ORGANIZATIONS,
        "FindMatchAndEnrichJobs",
        _GET_TECH_STACK,
        _FIND_PEOPLE,
        "SearchSignals",
        "RunSqlQuery",
    } <= names
    assert len(catalog.fingerprint) == 64


class FakeClient:
    def __init__(
        self,
        exchange: SumbleMcpToolExchange | Exception,
        *,
        initialize_error: Exception | None = None,
    ) -> None:
        self.exchange = exchange
        self.initialize_error = initialize_error
        self.calls = 0

    async def initialize(self) -> None:
        if self.initialize_error is not None:
            raise self.initialize_error
        return None

    async def call_tool(self, name: str, arguments: Any) -> SumbleMcpToolExchange:
        del name, arguments
        self.calls += 1
        if isinstance(self.exchange, Exception):
            raise self.exchange
        return self.exchange


class FakeJournal:
    def __init__(self, acquire: SumbleMcpAcquireResult) -> None:
        self.acquire_result = acquire
        self.acquire_calls = 0
        self.commits = 0
        self.unknown: list[SumbleMcpToolExchange | None] = []

    async def acquire(self, **kwargs: Any) -> SumbleMcpAcquireResult:
        del kwargs
        self.acquire_calls += 1
        return self.acquire_result

    async def commit(self, **kwargs: Any) -> SumbleMcpSnapshot:
        self.commits += 1
        plan: SumbleMcpInvocationPlan = kwargs["plan"]
        exchange: SumbleMcpToolExchange = kwargs["exchange"]
        return SumbleMcpSnapshot(
            source_key=plan.source_key,
            tool_name=plan.tool_name,
            request_fingerprint=plan.request_fingerprint,
            catalog_fingerprint=plan.catalog_fingerprint,
            provider_request_id=kwargs["provider_request_id"],
            provider_units_charged=kwargs["provider_units_charged"],
            credits_remaining=kwargs["credits_remaining"],
            payload=exchange.payload,
            response_artifact_key="artifacts/sumble/sha256-deadbeef",
            cost_cents_charged=Decimal(1),
        )

    async def mark_spend_unknown(self, **kwargs: Any) -> None:
        self.unknown.append(kwargs["exchange"])


def _catalog(name: str = _FIND_ORGANIZATIONS) -> SumbleMcpToolCatalog:
    return SumbleMcpToolCatalog.from_tools((_descriptor(name),))


def _plan(catalog: SumbleMcpToolCatalog) -> SumbleMcpInvocationPlan:
    return SumbleMcpInvocationPlan(
        workspace_id="workspace-1",
        project_run_id=new_run_id(),
        account_id=new_entity_id(),
        source_key=f"sumble_mcp:{catalog.fingerprint[:12]}:organizations",
        tool_name=_FIND_ORGANIZATIONS,
        arguments={
            "reason": "Resolve one account for the governed field plan",
            "organizations": [{"url": "acme.example"}],
        },
        catalog_fingerprint=catalog.fingerprint,
        provider_contract_version="sumble-mcp-catalog-v1",
        policy_version=_MCP_POLICY_VERSION,
        observation_window="project-run:test",
        field_bindings=(
            SumbleMcpFieldBinding(
                field_key="account.custom_mcp_metric",
                value_pointer="/organizations/0/custom_metric",
                source_url_pointer="/organizations/0/source_url",
            ),
        ),
        maximum_provider_units=Decimal(2),
        expected_value_credits=Decimal(3),
        maximum_cost_cents=Decimal(1),
        settlement=SumbleMcpSettlementRule(
            mode=SumbleMcpSettlementMode.PROVIDER_RECEIPT,
            credits_used_pointer="/credits_used",
            credits_remaining_pointer="/credits_remaining",
            provider_request_id_pointer="/id",
        ),
    )


def _authorization(plan: SumbleMcpInvocationPlan) -> SumbleMcpDurableAuthorization:
    return SumbleMcpDurableAuthorization(
        operation_id="operation-1",
        durable_reservation_key="reservation-1",
        request_fingerprint=plan.request_fingerprint,
        catalog_fingerprint=plan.catalog_fingerprint,
        provider_units_reserved=plan.maximum_provider_units,
        cost_cents_reserved=plan.maximum_cost_cents,
    )


def _exchange(*, credits_used: int | None = 2) -> SumbleMcpToolExchange:
    payload: dict[str, Any] = {
        "id": "request-1",
        "credits_remaining": 98,
        "organizations": [
            {
                "custom_metric": "HIPAA-ready intake automation",
                "source_url": "https://sumble.com/l/org/acme",
            }
        ],
    }
    if credits_used is not None:
        payload["credits_used"] = credits_used
    return SumbleMcpToolExchange(
        jsonrpc_request_id=3,
        session_id="session-1",
        tool_name=_FIND_ORGANIZATIONS,
        result=SumbleMcpToolResult(structuredContent=payload),
        payload=payload,
        raw_response={"structuredContent": payload},
    )


def test_governed_adapter_requires_exact_schema_and_authorization_before_dispatch() -> None:
    catalog = _catalog()
    plan = _plan(catalog)
    bad = plan.model_copy(
        update={
            "arguments": {
                "reason": "Adversarial argument check",
                "organizations": [],
                "sql": "DROP TABLE x",
            }
        }
    )
    client = FakeClient(_exchange())
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )
    adapter = GovernedSumbleMcpAdapter(client=client, journal=journal)  # type: ignore[arg-type]

    with pytest.raises(SumbleMcpSchemaError, match="undeclared"):
        run_async(adapter.invoke(plan=bad, authorization=_authorization(bad), catalog=catalog))

    assert client.calls == 0
    assert journal.acquire_calls == 0


def test_actual_style_local_schema_refs_and_bounds_fail_before_dispatch() -> None:
    descriptor = _descriptor().model_copy(
        update={
            "inputSchema": {
                "$defs": {
                    "OrganizationInput": {
                        "type": "object",
                        "required": ["url"],
                        "additionalProperties": False,
                        "properties": {"url": {"type": "string", "minLength": 1}},
                    }
                },
                "type": "object",
                "required": ["reason", "organizations"],
                "additionalProperties": False,
                "properties": {
                    "reason": {"type": "string", "minLength": 1},
                    "organizations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1000,
                        "items": {"$ref": "#/$defs/OrganizationInput"},
                    },
                },
            }
        }
    )

    with pytest.raises(SumbleMcpSchemaError, match="undeclared"):
        validate_sumble_mcp_arguments(
            {
                "reason": "contract test",
                "organizations": [{"url": "acme.example", "sql": "unsafe"}],
            },
            descriptor,
        )
    with pytest.raises(SumbleMcpSchemaError, match="too short"):
        validate_sumble_mcp_arguments(
            {"reason": "", "organizations": [{"url": "acme.example"}]},
            descriptor,
        )


def test_governance_denies_mutation_sql_signals_and_contact_reveal_by_default() -> None:
    policy = SumbleMcpPolicy(
        allowed_tool_names=frozenset({_UPDATE_PRIORITY_RELEVANCE, "RunSqlQuery", "SearchSignals"}),
        allowed_tool_classes=frozenset(
            {
                SumbleMcpToolClass.MUTATION,
                SumbleMcpToolClass.DATABASE,
                SumbleMcpToolClass.SIGNALS,
            }
        ),
    )
    for name in (_UPDATE_PRIORITY_RELEVANCE, "RunSqlQuery", "SearchSignals"):
        with pytest.raises(SumbleMcpGovernanceError):
            policy.authorize(tool_name=name, contact_reveal=False)
    with pytest.raises(SumbleMcpGovernanceError, match="contact reveal"):
        SumbleMcpPolicy(
            allowed_tool_names=frozenset({_FIND_PEOPLE}),
            allowed_tool_classes=frozenset({SumbleMcpToolClass.PEOPLE}),
        ).authorize(tool_name=_FIND_PEOPLE, contact_reveal=True)


def test_catalog_tool_must_advertise_read_only_non_destructive_execution() -> None:
    catalog = SumbleMcpToolCatalog.from_tools(
        (_descriptor().model_copy(update={"annotations": None}),)
    )
    plan = _plan(catalog)
    client = FakeClient(_exchange())
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )

    with pytest.raises(SumbleMcpGovernanceError, match="read-only"):
        run_async(
            GovernedSumbleMcpAdapter(
                client=client,
                journal=journal,  # type: ignore[arg-type]
            ).invoke(plan=plan, authorization=_authorization(plan), catalog=catalog)
        )

    assert client.calls == 0
    assert journal.acquire_calls == 0


def test_oauth_failure_happens_before_paid_dispatch_lease() -> None:
    catalog = _catalog()
    plan = _plan(catalog)
    client = FakeClient(
        _exchange(),
        initialize_error=SumbleMcpAuthenticationRequired(
            resource_metadata_url=("https://mcp.sumble.com/.well-known/oauth-protected-resource")
        ),
    )
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )

    with pytest.raises(SumbleMcpAuthenticationRequired):
        run_async(
            GovernedSumbleMcpAdapter(
                client=client,
                journal=journal,  # type: ignore[arg-type]
            ).invoke(plan=plan, authorization=_authorization(plan), catalog=catalog)
        )

    assert journal.acquire_calls == 0
    assert journal.unknown == []


def test_contact_reveal_hidden_in_tool_arguments_is_rejected_before_reservation() -> None:
    catalog = _catalog()
    plan = _plan(catalog).model_copy(
        update={
            "arguments": {
                "reason": "Attempting a hidden contact reveal",
                "organizations": [{"url": "acme.example"}],
                "select": {"attributes": ["work_email"]},
            }
        }
    )
    # Use a descriptor that allows the select key so this assertion exercises personal-data
    # governance, rather than the generic additional-properties guard.
    descriptor = _descriptor().model_copy(
        update={
            "inputSchema": {
                **_descriptor().inputSchema,
                "properties": {
                    **_descriptor().inputSchema["properties"],  # type: ignore[dict-item]
                    "select": {"type": "object"},
                },
            }
        }
    )
    reveal_catalog = SumbleMcpToolCatalog.from_tools((descriptor,))
    plan = plan.model_copy(update={"catalog_fingerprint": reveal_catalog.fingerprint})
    client = FakeClient(_exchange())
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )

    with pytest.raises(SumbleMcpGovernanceError, match="not declared"):
        run_async(
            GovernedSumbleMcpAdapter(
                client=client,
                journal=journal,  # type: ignore[arg-type]
            ).invoke(
                plan=plan,
                authorization=_authorization(plan),
                catalog=reveal_catalog,
            )
        )

    assert client.calls == 0
    assert journal.acquire_calls == 0


def test_paid_adapter_commits_exact_receipt_and_terminal_replay_makes_zero_calls() -> None:
    catalog = _catalog()
    plan = _plan(catalog)
    authorization = _authorization(plan)
    client = FakeClient(_exchange())
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )
    adapter = GovernedSumbleMcpAdapter(client=client, journal=journal)  # type: ignore[arg-type]

    completed = run_async(adapter.invoke(plan=plan, authorization=authorization, catalog=catalog))

    assert completed.outcome is SumbleMcpInvocationOutcome.COMPLETED
    assert completed.provider_calls == 1
    assert completed.snapshot is not None
    assert completed.snapshot.provider_units_charged == Decimal(2)
    assert journal.commits == 1

    replay_journal = FakeJournal(
        SumbleMcpAcquireResult(
            state=SumbleMcpAcquireState.REPLAY,
            lease_key="reservation-1",
            snapshot=completed.snapshot,
        )
    )
    replay_client = FakeClient(AssertionError("provider must not be called on replay"))
    replay = run_async(
        GovernedSumbleMcpAdapter(
            client=replay_client,
            journal=replay_journal,  # type: ignore[arg-type]
        ).invoke(plan=plan, authorization=authorization, catalog=catalog)
    )

    assert replay.outcome is SumbleMcpInvocationOutcome.REPLAYED
    assert replay.provider_calls == 0
    assert replay_client.calls == 0


def test_missing_credit_receipt_is_persisted_as_unknown_and_never_committed() -> None:
    catalog = _catalog()
    plan = _plan(catalog)
    client = FakeClient(_exchange(credits_used=None))
    journal = FakeJournal(
        SumbleMcpAcquireResult(state=SumbleMcpAcquireState.DISPATCH, lease_key="reservation-1")
    )
    adapter = GovernedSumbleMcpAdapter(client=client, journal=journal)  # type: ignore[arg-type]

    with pytest.raises(SumbleMcpSpendOutcomeUnknown, match="credit receipt"):
        run_async(adapter.invoke(plan=plan, authorization=_authorization(plan), catalog=catalog))

    assert client.calls == 1
    assert journal.commits == 0
    assert journal.unknown == [client.exchange]


def test_snapshot_resolver_materializes_a_field_that_has_no_hardcoded_sumble_mapping() -> None:
    catalog = _catalog()
    plan = _plan(catalog)
    account = Entity(entity_id=plan.account_id, entity_type=EntityType.ACCOUNT)
    snapshot = SumbleMcpSnapshot(
        source_key=plan.source_key,
        tool_name=plan.tool_name,
        request_fingerprint=plan.request_fingerprint,
        catalog_fingerprint=plan.catalog_fingerprint,
        provider_request_id="request-1",
        provider_units_charged=Decimal(2),
        credits_remaining=98,
        payload=_exchange().payload,
        response_artifact_key="artifacts/sumble/sha256-deadbeef",
        cost_cents_charged=Decimal(1),
    )
    resolver = SumbleMcpSnapshotResolver(
        source_key=plan.source_key,
        snapshots=MappingSumbleMcpSnapshotLookup({(plan.account_id, plan.source_key): snapshot}),
        bindings=plan.field_bindings,
        charge_field=plan.field_bindings[0].field_key,
    )

    claims = resolver.resolve(
        account,
        FieldDef(
            field_key="account.custom_mcp_metric",
            value_type="str",
            pass_kind=PassKind.DEEP,
        ),
    )

    assert len(claims) == 1
    assert claims[0].value_json == "HIPAA-ready intake automation"
    assert claims[0].source_url == "https://sumble.com/l/org/acme"
    assert claims[0].artifact_key == snapshot.response_artifact_key
    assert claims[0].cost_cents == Decimal(1)
