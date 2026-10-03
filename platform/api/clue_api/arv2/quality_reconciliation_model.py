"""Historical replay helper; production reconciliation uses the account Deep Agent runtime.

Retained for isolated comparison scripts that explicitly select the former leaf-call approach.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from clue_api.arv2.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.structuring_client import parse_reply_text
from clue_api.arv2.transport import HttpxTransport
from clue_config import GatewayConfig, Secrets, Settings
from clue_db import ConnFactory


def build_generator(
    settings: Settings,
    secrets: Secrets,
    conn_factory: ConnFactory,
    artifacts: ArtifactSink | None,
) -> Callable[[Any, dict[str, Any]], Awaitable[Mapping[str, object]]]:
    api_key = secrets.openrouter_api_key
    if api_key is None:
        raise RuntimeError("account reconciliation needs CLUE_OPENROUTER_API_KEY")

    async def generate(scope: Any, packet: dict[str, Any]) -> Mapping[str, object]:
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
        )
        system = packet["_editorial_system"]
        public_packet = {k: v for k, v in packet.items() if not k.startswith("_")}
        request = openrouter_chat_request(
            base_url=GatewayConfig().base_url,
            api_key=api_key,
            model=settings.arv2_display_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(public_packet, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            max_tokens=16000,
            timeout_s=settings.arv2_display_timeout_s,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label="account-reconciliation-v1",
            request=request,
            estimate=SpendEstimate(usd=Decimal("0.02")),
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={
                "job_id": str(scope.job_id),
                "workspace_id": scope.workspace_id,
                "purpose": "account_reconciliation",
                "execution_id": packet["_execution_id"],
            },
        )
        hop = asyncio.create_task(asyncio.to_thread(caller.call, spec))
        try:
            try:
                result = await asyncio.shield(hop)
            except asyncio.CancelledError:
                # Preserve billing truth for a request already dispatched; never start another.
                await hop
                raise
        finally:
            async with conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=artifacts,
                    stamp=LedgerStamp(
                        workspace_id=scope.workspace_id,
                        project_id=scope.project_id,
                        job_id=scope.job_id,
                    ),
                )
        return parse_reply_text(openrouter_message_text(result.json()), raw_ref=result.raw_ref)

    return generate
