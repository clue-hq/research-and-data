"""The spend layer's observer, bound for platform clients that keep their own HTTP stack.

Exa Websets, Composio, Cloudflare and Clerk report every answer through this observer, so their
calls land on ``provider_call_ledger`` and a refusal (a 402, a quota used up) opens a provider
incident — the founders are told (design ``2026-10-31-provider-credit-and-key-alerts`` §6.4).
"""

from __future__ import annotations

from functools import partial

from clue_db import ConnFactory, transaction
from clue_spend import Observe, record_observed_call

#: Providers that bill per call or per result. Their observed rows say ``estimate``; every other
#: observed provider charges nothing per call and says ``free``.
_BILLED = frozenset({"exa_websets"})


def cost_source_for(provider: str) -> str:
    return "estimate" if provider in _BILLED else "free"


def provider_observer(
    provider: str, *, workspace_id: str | None = None, conn_factory: ConnFactory = transaction
) -> Observe:
    """The observer one client of ``provider`` reports to; ``workspace_id`` when the call is one
    workspace's, ``None`` when the client serves several (a fleet loop) or none yet."""
    return partial(
        record_observed_call,
        provider=provider,
        conn_factory=conn_factory,
        workspace_id=workspace_id,
        cost_source=cost_source_for(provider),
    )
