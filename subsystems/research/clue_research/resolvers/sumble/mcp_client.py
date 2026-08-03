"""Minimal, typed Sumble Streamable-HTTP MCP client.

The client deliberately owns only the MCP wire protocol.  It does not choose tools, authorize
spend, retry paid calls, or materialize claims.  Those decisions belong to the governed adapter
and its durable caller.

Sumble's MCP server is an OAuth-protected Streamable-HTTP endpoint.  Product composition supplies
an access-token provider; this module never reads environment variables or persists credentials.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, TypeAdapter

from clue_core import ResolverError, RetryableResolverError

SUMBLE_MCP_ENDPOINT: Final = "https://mcp.sumble.com/"
SUMBLE_MCP_PROTOCOL_VERSION: Final = "2025-06-18"
SUMBLE_MCP_CLIENT_NAME: Final = "clue-sumble-mcp"
SUMBLE_MCP_CLIENT_VERSION: Final = "1.0.0"

_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class SumbleMcpError(ResolverError):
    """The Sumble MCP server or response violated the pinned transport contract."""


class SumbleMcpAuthenticationRequired(SumbleMcpError):
    """The configured bearer token is absent, expired, or not authorized for Sumble MCP."""

    def __init__(self, *, resource_metadata_url: str | None = None) -> None:
        self.resource_metadata_url = resource_metadata_url
        suffix = (
            f"; authorize against {resource_metadata_url}"
            if resource_metadata_url is not None
            else ""
        )
        super().__init__(f"Sumble MCP authentication is required{suffix}")


class SumbleMcpRetryableTransportError(RetryableResolverError):
    """A pre-dispatch/read-only MCP request may be retried by its durable owner."""


class SumbleMcpProtocolError(SumbleMcpError):
    """A response is not valid JSON-RPC/MCP for the request that produced it."""


class SumbleMcpToolError(SumbleMcpError):
    """Sumble returned a terminal tool execution error."""


class SumbleMcpAccessTokenProvider(Protocol):
    async def access_token(self) -> SecretStr: ...


class StaticSumbleMcpAccessTokenProvider:
    """Small composition helper for an already-acquired OAuth access token.

    Production can inject a refreshing vault-backed implementation of the same protocol.  The
    secret is intentionally excluded from representations and error messages by ``SecretStr``.
    """

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    async def access_token(self) -> SecretStr:
        return self._token


class McpHttpResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes = b""


class McpHttpTransport(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> McpHttpResponse: ...


class HttpxMcpHttpTransport:
    """One-attempt HTTP transport.

    ``follow_redirects`` stays disabled so an authentication redirect can never turn a protocol
    call into an HTML login response.  Retry belongs above this boundary because ``tools/call``
    may already have consumed credits when the response is lost.
    """

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")
        self._timeout = timeout_seconds

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> McpHttpResponse:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, headers=dict(headers), content=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SumbleMcpRetryableTransportError(
                "Sumble MCP transport failed before a response was received"
            ) from exc
        return McpHttpResponse(
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.content,
        )


class SumbleMcpImplementation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str
    version: str


class SumbleMcpInitializeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    protocolVersion: str
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    serverInfo: SumbleMcpImplementation
    instructions: str | None = None


class SumbleMcpToolDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = Field(min_length=1)
    description: str | None = None
    inputSchema: dict[str, JsonValue]
    outputSchema: dict[str, JsonValue] | None = None
    annotations: dict[str, JsonValue] | None = None

    @property
    def canonical_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json", exclude_none=True)


class SumbleMcpToolCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tools: tuple[SumbleMcpToolDescriptor, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_tools(cls, tools: tuple[SumbleMcpToolDescriptor, ...]) -> SumbleMcpToolCatalog:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise SumbleMcpProtocolError("Sumble MCP advertised duplicate tool names")
        canonical = [tool.canonical_payload for tool in sorted(tools, key=lambda item: item.name)]
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return cls(tools=tuple(sorted(tools, key=lambda item: item.name)), fingerprint=digest)

    def require(self, name: str) -> SumbleMcpToolDescriptor:
        matches = [tool for tool in self.tools if tool.name == name]
        if len(matches) != 1:
            raise SumbleMcpProtocolError(f"Sumble MCP tool {name!r} is not in the pinned catalog")
        return matches[0]


class SumbleMcpContentBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: str
    text: str | None = None


class SumbleMcpToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    content: tuple[SumbleMcpContentBlock, ...] = ()
    structuredContent: JsonValue | None = None
    isError: bool = False

    def deterministic_payload(self) -> JsonValue:
        """Return only a machine-checkable payload; never parse narrative prose heuristically."""

        if self.isError:
            raise SumbleMcpToolError("Sumble MCP tool returned isError=true")
        if self.structuredContent is not None:
            return self.structuredContent
        text_blocks = [block.text for block in self.content if block.type == "text"]
        if len(text_blocks) != 1 or text_blocks[0] is None:
            raise SumbleMcpProtocolError(
                "Sumble MCP result has no structuredContent or single JSON text block"
            )
        try:
            decoded = json.loads(text_blocks[0])
        except json.JSONDecodeError as exc:
            raise SumbleMcpProtocolError(
                "Sumble MCP text result is narrative rather than exact JSON"
            ) from exc
        return _JSON_VALUE.validate_python(decoded)


class SumbleMcpToolExchange(BaseModel):
    """The exact deterministic tool result returned to the governed/durable layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jsonrpc_request_id: int
    session_id: str | None
    tool_name: str
    result: SumbleMcpToolResult
    payload: JsonValue
    raw_response: dict[str, JsonValue]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _resource_metadata(headers: Mapping[str, str]) -> str | None:
    challenge = headers.get("www-authenticate", "")
    marker = 'resource_metadata="'
    if marker not in challenge:
        return None
    tail = challenge.split(marker, 1)[1]
    return tail.split('"', 1)[0] or None


def _jsonrpc_messages(response: McpHttpResponse) -> tuple[dict[str, JsonValue], ...]:
    content_type = response.headers.get("content-type", "").lower()
    candidates: list[object] = []
    if "text/event-stream" in content_type:
        for line in response.body.decode("utf-8").splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                if raw:
                    try:
                        candidates.append(json.loads(raw))
                    except json.JSONDecodeError as exc:
                        raise SumbleMcpProtocolError("Sumble MCP emitted invalid SSE JSON") from exc
    elif response.body:
        try:
            candidates.append(json.loads(response.body))
        except json.JSONDecodeError as exc:
            raise SumbleMcpProtocolError("Sumble MCP emitted invalid JSON") from exc
    messages: list[dict[str, JsonValue]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise SumbleMcpProtocolError("Sumble MCP JSON-RPC message is not an object")
        messages.append(cast(dict[str, JsonValue], _JSON_VALUE.validate_python(candidate)))
    return tuple(messages)


class SumbleMcpClient:
    """Stateful Streamable-HTTP MCP session with an injected OAuth token provider."""

    def __init__(
        self,
        *,
        token_provider: SumbleMcpAccessTokenProvider,
        transport: McpHttpTransport | None = None,
        endpoint: str = SUMBLE_MCP_ENDPOINT,
    ) -> None:
        self._token_provider = token_provider
        self._transport = transport or HttpxMcpHttpTransport()
        self._endpoint = endpoint
        self._session_id: str | None = None
        self._initialize_result: SumbleMcpInitializeResult | None = None
        self._next_request_id = 1

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def initialize(self) -> SumbleMcpInitializeResult:
        if self._initialize_result is not None:
            return self._initialize_result
        result, response, _ = await self._request(
            "initialize",
            {
                "protocolVersion": SUMBLE_MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": SUMBLE_MCP_CLIENT_NAME,
                    "version": SUMBLE_MCP_CLIENT_VERSION,
                },
            },
        )
        try:
            initialized = SumbleMcpInitializeResult.model_validate(result)
        except Exception as exc:
            raise SumbleMcpProtocolError("invalid Sumble MCP initialize result") from exc
        if initialized.protocolVersion != SUMBLE_MCP_PROTOCOL_VERSION:
            raise SumbleMcpProtocolError(
                "Sumble MCP negotiated an unexpected protocol version "
                f"{initialized.protocolVersion!r}"
            )
        self._session_id = response.headers.get("mcp-session-id")
        self._initialize_result = initialized
        await self._notification("notifications/initialized", {})
        return initialized

    async def list_tools(self) -> SumbleMcpToolCatalog:
        await self.initialize()
        cursor: str | None = None
        tools: list[SumbleMcpToolDescriptor] = []
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, JsonValue] = {}
            if cursor is not None:
                params["cursor"] = cursor
            result, _, _ = await self._request("tools/list", params)
            raw_tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(raw_tools, list):
                raise SumbleMcpProtocolError("Sumble MCP tools/list omitted its tools array")
            try:
                tools.extend(SumbleMcpToolDescriptor.model_validate(item) for item in raw_tools)
            except Exception as exc:
                raise SumbleMcpProtocolError("invalid Sumble MCP tool descriptor") from exc
            next_cursor = result.get("nextCursor") if isinstance(result, dict) else None
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise SumbleMcpProtocolError("Sumble MCP returned an invalid tools cursor")
            if next_cursor in seen_cursors:
                raise SumbleMcpProtocolError("Sumble MCP tools pagination cursor repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return SumbleMcpToolCatalog.from_tools(tuple(tools))

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> SumbleMcpToolExchange:
        await self.initialize()
        request_id = self._next_request_id
        result, _, raw_message = await self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
            forced_request_id=request_id,
        )
        try:
            parsed = SumbleMcpToolResult.model_validate(result)
        except Exception as exc:
            raise SumbleMcpProtocolError("invalid Sumble MCP tools/call result") from exc
        payload = parsed.deterministic_payload()
        return SumbleMcpToolExchange(
            jsonrpc_request_id=request_id,
            session_id=self._session_id,
            tool_name=name,
            result=parsed,
            payload=payload,
            raw_response=raw_message,
        )

    async def _notification(self, method: str, params: Mapping[str, JsonValue]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        response = await self._post(payload)
        if response.status_code not in {200, 202, 204}:
            self._raise_http(response)

    async def _request(
        self,
        method: str,
        params: Mapping[str, JsonValue],
        *,
        forced_request_id: int | None = None,
    ) -> tuple[dict[str, JsonValue], McpHttpResponse, dict[str, JsonValue]]:
        request_id = forced_request_id or self._next_request_id
        self._next_request_id = max(self._next_request_id, request_id + 1)
        response = await self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        if response.status_code != 200:
            self._raise_http(response)
        messages = _jsonrpc_messages(response)
        matching = [message for message in messages if message.get("id") == request_id]
        if len(matching) != 1:
            raise SumbleMcpProtocolError(
                f"Sumble MCP response did not contain exactly one reply for id {request_id}"
            )
        message = matching[0]
        if message.get("jsonrpc") != "2.0":
            raise SumbleMcpProtocolError("Sumble MCP response has an invalid jsonrpc version")
        if "error" in message:
            error = message.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise SumbleMcpToolError(f"Sumble MCP JSON-RPC error code {code!r}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise SumbleMcpProtocolError("Sumble MCP response result is not an object")
        return cast(dict[str, JsonValue], _JSON_VALUE.validate_python(result)), response, message

    async def _post(self, payload: Mapping[str, object]) -> McpHttpResponse:
        token = await self._token_provider.access_token()
        headers = {
            "authorization": f"Bearer {token.get_secret_value()}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": SUMBLE_MCP_PROTOCOL_VERSION,
        }
        if self._session_id is not None:
            headers["mcp-session-id"] = self._session_id
        response = await self._transport.post(
            self._endpoint,
            headers=headers,
            body=_canonical_bytes(payload),
        )
        normalized = response.model_copy(
            update={"headers": {key.lower(): value for key, value in response.headers.items()}}
        )
        if normalized.status_code == 401:
            raise SumbleMcpAuthenticationRequired(
                resource_metadata_url=_resource_metadata(normalized.headers)
            )
        return normalized

    @staticmethod
    def _raise_http(response: McpHttpResponse) -> None:
        if response.status_code == 401:
            raise SumbleMcpAuthenticationRequired(
                resource_metadata_url=_resource_metadata(response.headers)
            )
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            raise SumbleMcpRetryableTransportError(
                f"Sumble MCP returned retryable HTTP {response.status_code}"
            )
        raise SumbleMcpProtocolError(f"Sumble MCP returned HTTP {response.status_code}")


__all__ = [
    "HttpxMcpHttpTransport",
    "McpHttpResponse",
    "McpHttpTransport",
    "StaticSumbleMcpAccessTokenProvider",
    "SUMBLE_MCP_ENDPOINT",
    "SUMBLE_MCP_PROTOCOL_VERSION",
    "SumbleMcpAccessTokenProvider",
    "SumbleMcpAuthenticationRequired",
    "SumbleMcpClient",
    "SumbleMcpContentBlock",
    "SumbleMcpError",
    "SumbleMcpInitializeResult",
    "SumbleMcpProtocolError",
    "SumbleMcpRetryableTransportError",
    "SumbleMcpToolCatalog",
    "SumbleMcpToolDescriptor",
    "SumbleMcpToolError",
    "SumbleMcpToolExchange",
    "SumbleMcpToolResult",
]
