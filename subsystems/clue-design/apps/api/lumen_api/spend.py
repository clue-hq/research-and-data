"""The design subsystem's spend seam (lane 3 slice 5).

One ``ProviderCaller`` per unit of work — an ingestion job, a design-leg turn, one API request —
carried in a contextvar so the clients that spend (image provider, ingestion models, ad-DNA,
the logo vendor, the ad-library vendor) do not thread a caller through every signature. The scope
drains onto
``provider_call_ledger`` when the unit ends. A call made with no scope open is still recorded
(in memory) and warned about once, so a missed scope is visible and never silently unpriced.

The drain itself is INJECTED (``drain_fn``). The library drain — ``clue_spend.drain_provider_calls``
— writes rows and nothing else; the platform hangs its own incident bookkeeping off the same drain
by passing a function that wraps it. That keeps the bookkeeping written once, on the platform side,
without this module knowing the platform exists. The default is the bare library drain, so a design
process running alone still lands every row.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

from clue_obs.langfuse import LangfuseRunRegistry
from clue_spend import (
    BufferedLedger,
    BufferedRawSink,
    CallSpec,
    CostReading,
    DrainReport,
    HttpRequest,
    HttpResponse,
    HttpxTransport,
    LedgerStamp,
    ProviderCaller,
    SpendEstimate,
    Transport,
    drain_provider_calls,
    openrouter_cost_reader,
    openrouter_halt_rule,
)

log = logging.getLogger(__name__)

#: How a scope lands its buffered rows. Takes the whole drain rather than a hook, so a caller that
#: needs more than "write the rows" (the platform's provider-incident recorder) writes that once,
#: at its own composition root, instead of once per design executor.
DrainFn = Callable[
    ["object", BufferedRawSink, BufferedLedger, LedgerStamp], Awaitable[DrainReport]
]

#: Every design-side OpenRouter call's incident provider; its ledger rows keep ``openrouter``.
DESIGN_MODEL_PROVIDER = "openrouter_design"

_SCOPE: ContextVar["SpendScope | None"] = ContextVar("lumen_spend_scope", default=None)


async def _default_drain(
    conn: object,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    stamp: LedgerStamp,
) -> DrainReport:
    """Write the rows and nothing else. ``artifacts=None``: the design lane's bodies are not
    persisted to the platform's artifact store, so the rows land citing nothing there."""
    return await drain_provider_calls(
        conn,  # type: ignore[arg-type]
        raw=raw,
        ledger=ledger,
        artifacts=None,
        stamp=stamp,
    )


@dataclass
class SpendScope:
    stamp: LedgerStamp
    caller: ProviderCaller
    raw: BufferedRawSink
    ledger: BufferedLedger
    drain_fn: DrainFn = field(default=_default_drain)
    langfuse_ids: LangfuseRunRegistry | None = None


def _new_scope(
    stamp: LedgerStamp,
    transport: Transport | None,
    drain_fn: DrainFn | None = None,
    sleep: Callable[[float], None] | None = None,
) -> SpendScope:
    raw, ledger = BufferedRawSink(), BufferedLedger()
    caller = ProviderCaller(
        transport=transport or HttpxTransport(),
        raw_sink=raw,
        ledger=ledger,
        now=lambda: datetime.now(UTC),
        **({} if sleep is None else {"sleep": sleep}),
    )
    return SpendScope(
        stamp=stamp,
        caller=caller,
        raw=raw,
        ledger=ledger,
        drain_fn=drain_fn if drain_fn is not None else _default_drain,
    )


@contextmanager
def spend_scope(
    stamp: LedgerStamp,
    *,
    transport: Transport | None = None,
    drain_fn: DrainFn | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[SpendScope]:
    """Open one unit of work's spend scope.

    ``transport`` and ``sleep`` are the test seams (the second so a test can prove the retry
    arithmetic without paying law 2's twelve-second backoff); production omits both.
    """
    scope = _new_scope(stamp, transport, drain_fn, sleep)
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> SpendScope | None:
    return _SCOPE.get()


_UNSCOPED: SpendScope | None = None
_UNSCOPED_WARNED = False


def reset_unscoped_for_tests(*, transport: Transport | None = None) -> None:
    global _UNSCOPED, _UNSCOPED_WARNED
    _UNSCOPED = _new_scope(LedgerStamp(workspace_id="unscoped"), transport)
    _UNSCOPED_WARNED = False


def caller() -> ProviderCaller:
    """The open scope's caller, or the process-wide unscoped fallback (warned about once)."""
    global _UNSCOPED, _UNSCOPED_WARNED
    scope = _SCOPE.get()
    if scope is not None:
        return scope.caller
    if _UNSCOPED is None:
        _UNSCOPED = _new_scope(LedgerStamp(workspace_id="unscoped"), None)
    if not _UNSCOPED_WARNED:
        _UNSCOPED_WARNED = True
        log.warning(
            "spend.unscoped_call: a design spend path ran with no spend scope open; "
            "rows stay in memory"
        )
    return _UNSCOPED.caller


def openrouter_call(
    *,
    operation: str,
    body: dict,
    label: str,
    timeout_s: float,
    api_key: str,
    base_url: str,
    estimate_usd: Decimal = Decimal(0),
    extras: Mapping[str, object] | None = None,
    extra_headers: Mapping[str, str] | None = None,
    max_attempts: int = 4,
    cost_reader: Callable[[HttpResponse], CostReading] | None = openrouter_cost_reader,
    path: str = "/chat/completions",
    include_usage: bool = True,
) -> HttpResponse:
    """One OpenRouter call through the scope's caller, priced by its usage block.

    ``usage: {"include": True}`` is added to a chat/completions body: without it OpenRouter omits
    the ``usage`` block the cost reader prices from, and the row would fall back to an estimate of
    zero. ``include_usage=False`` is for the Images API, which takes no such key and whose cost is
    looked up from the generation id afterwards instead.

    ``max_attempts`` replaces the hand-rolled retry loops the clients carried — the caller retries
    the statuses in ``CallSpec.retry_statuses`` and applies law 2's backoff. The five ingestion/ad
    clients pass ``2``, their historical count.
    """
    wire = {**body, "usage": {"include": True}} if include_usage else dict(body)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    request = HttpRequest(
        method="POST",
        url=base_url.rstrip("/") + path,
        headers=headers,
        body=json.dumps(wire).encode("utf-8"),
        timeout_s=timeout_s,
    )
    spec = CallSpec(
        provider="openrouter",
        operation=operation,
        label=label,
        request=request,
        estimate=SpendEstimate(usd=estimate_usd),
        max_attempts=max_attempts,
        halt_rule=openrouter_halt_rule,
        cost_reader=cost_reader,
        # The row stays provider='openrouter' (the cost views group by it); the incident a refusal
        # opens is the design provider's (design 2026-10-31).
        extras={"incident_provider": DESIGN_MODEL_PROVIDER, **(extras or {})},
    )
    return caller().call(spec).response


def image_generation_cost_reader(response: HttpResponse) -> CostReading:
    """Price an Images-API call from OpenRouter's own metering.

    The response carries a ``usage`` block like a chat completion (verified live 2026-10-04 on
    ``openai/gpt-image-2.5-flare``: on a BYOK key ``cost`` is 0 and the OpenAI charge is in
    ``cost_details.upstream_inference_cost``), so it is read by the same BYOK-aware reader. The
    generation id is NOT in the body; it arrives in the ``x-generation-id`` header.

    Only a response without a usable ``usage`` block falls back to the ``/generation?id=``
    lookup. ``OpenRouterGenerationCost.cost_cents`` answers in CENTS — the ledger holds USD, so
    the reading divides. A lookup that fails answers ``None``, which the wrapper records as "the
    provider did not tell us" (the estimate stands in), never as zero.
    """
    reading = openrouter_cost_reader(response)
    if reading.cost_usd is not None:
        generation_id = reading.provider_request_id
        return CostReading(
            cost_usd=reading.cost_usd,
            provider_request_id=generation_id,
            extras={**reading.extras, **({"generation_id": generation_id} if generation_id else {})},
        )
    try:
        payload = json.loads(response.body)
    except ValueError:
        payload = {}
    generation_id = (payload.get("id") if isinstance(payload, dict) else None) or response.headers.get(
        "x-generation-id"
    )
    if not generation_id:
        return CostReading()
    lookup = _generation_lookup()
    if lookup is None:
        return CostReading()
    cents = lookup.cost_cents(str(generation_id))
    if cents is None:
        return CostReading()
    return CostReading(
        cost_usd=Decimal(cents) / Decimal(100),
        provider_request_id=str(generation_id),
        extras={"generation_id": str(generation_id)},
    )


@lru_cache(maxsize=4)
def _generation_lookup_for(base_url: str, api_key: str) -> object | None:
    from clue_gateway.agent_model import OpenRouterGenerationCost
    from pydantic import SecretStr

    if not base_url or not api_key:
        return None
    return OpenRouterGenerationCost(base_url=base_url, api_key=SecretStr(api_key))


def _generation_lookup():
    """The ``/generation?id=`` reader, built once per (base_url, api_key) from the image model's
    own configuration — the Images API and its meter are the same deployment."""
    from py_lumen_config import settings

    return _generation_lookup_for(
        settings.image_model_base_url.strip(), settings.image_model_api_key.strip()
    )


#: How the gateway's cost-source vocabulary maps onto the ledger's. They are ALMOST the same
#: three words and deliberately not quite: ``clue_gateway.metadata.CostSource`` is
#: ``metered | estimate | unpriced``, while ``clue_spend.CostSource`` is
#: ``metered | estimate | free``. ``unpriced`` means "this model is on no price sheet", which is
#: NOT the ledger's ``free`` ("nobody was ever going to charge for this") — reading it as free
#: would quietly declare an unmeasured call to have cost nothing. It therefore maps to
#: ``estimate``, and the row carries the estimate columns at their zero default with
#: ``cost_usd`` NULL: an honest "we do not know", never a measured zero.
_LEDGER_COST_SOURCE = {"metered": "metered", "estimate": "estimate", "unpriced": "estimate"}


def record_collected_model_call(
    scope: SpendScope, call, *, operation: str, label: str
) -> None:
    """Turn one collected model call into this scope's ledger row.

    ``call`` is a ``lumen_agent.usage_collector.CollectedModelCall`` — a receipt the design
    runtime's callback COPIED off the governed gateway's own stamps. Nothing is priced here: the
    cents the gateway settled become USD, and an unsettled call lands with ``cost_usd`` NULL.

    The shape mirrors ``clue_spend.calls.ProviderCaller._settle``'s result row, because a cost
    dashboard must not be able to tell which of the two wrote a row: one ``result``-phase row per
    call, ``attempts=1`` (the gateway client owns its own retries, and a receipt describes the
    answer, not the attempts behind it), ``http_status`` NULL (this path never saw the wire), and
    the token counts, the answering model and the Langfuse ids in ``extras`` beside the
    ``cost_source`` marker every result row carries.
    """
    import uuid

    from clue_spend import LedgerRow

    cost_source = _LEDGER_COST_SOURCE.get(call.cost_source or "", "estimate")
    scope.ledger.record(
        LedgerRow(
            row_id=str(uuid.uuid4()),
            call_id=str(call.run_id),
            phase="result",
            provider="openrouter",
            operation=operation,
            label=label,
            recorded_at=call.completed_at,
            http_status=None,
            latency_ms=int(call.latency_ms),
            attempts=1,
            cost_usd=None if call.cost_cents is None else call.cost_cents / 100,
            outcome="ok" if call.status == "completed" else "client_error",
            error_code=call.error_code,
            extras={
                "model": call.answering_model,
                "prompt_tokens": call.input_tokens,
                "completion_tokens": call.output_tokens,
                "cached_prompt_tokens": call.cache_read_input_tokens,
                "cost_source": cost_source,
                "langfuse_trace_id": call.langfuse_trace_id,
                "langfuse_observation_id": call.langfuse_observation_id,
                "incident_provider": DESIGN_MODEL_PROVIDER,
                **(
                    {"provider_failure": call.provider_failure}
                    if getattr(call, "provider_failure", None)
                    else {}
                ),
            },
        )
    )


async def drain(scope: SpendScope, conn) -> DrainReport:
    """Land this scope's buffered rows through whatever drain it was opened with."""
    return await scope.drain_fn(conn, scope.raw, scope.ledger, scope.stamp)


def drain_sync(scope: SpendScope) -> DrainReport:
    """Drain from a synchronous executor: one private engine, one loop, one transaction.

    Mechanically ``DesignStoreBridge._run``, and for its reasons — NOT ``clue_db.get_engine()``,
    which the brief named: that accessor returns the PROCESS-GLOBAL engine, which raises outright
    in a design worker (no ``db_lifespan`` is active there) and is bound to a different event loop
    where one is. A private engine on this call's own loop is the only shape that works from a
    synchronous executor, so the drain owns one and disposes of it.

    ``run_isolated`` because some callers are already inside a loop (the ingestion pipeline drives
    capture with its own ``asyncio.run``); it hands those to a one-shot worker thread rather than
    letting ``asyncio.run`` refuse.
    """
    from clue_db import create_engine

    from .design_store import run_isolated

    async def run() -> DrainReport:
        engine = create_engine()
        try:
            async with engine.connect() as conn, conn.begin():
                return await drain(scope, conn)
        finally:
            await engine.dispose()

    return run_isolated(run())


def check_provider_keys_sync(*, role: str = "design-api") -> None:
    """The start-up key check for the design API (design 2026-10-31 §6.3).

    The design API holds no process-global engine, so — like :func:`drain_sync` — the check owns
    a private engine on its own loop and disposes of it. Run from a daemon thread at start-up so
    the app never waits on it; never raises.
    """
    from clue_db import create_engine
    from clue_spend.key_check import check_provider_keys, startup_environ

    from .design_store import run_isolated

    async def run() -> None:
        engine = create_engine()
        try:
            await check_provider_keys(engine.begin, role=role, environ=startup_environ())
        finally:
            await engine.dispose()

    try:
        run_isolated(run())
    except Exception as error:  # noqa: BLE001 - the check must never stop a start-up
        # By type only: no traceback whose frames could hold the environment's keys.
        log.error("provider_keys.check_failed role=%s error=%s", role, type(error).__name__)


__all__ = [
    "DrainFn",
    "check_provider_keys_sync",
    "SpendScope",
    "caller",
    "current_scope",
    "drain",
    "drain_sync",
    "image_generation_cost_reader",
    "openrouter_call",
    "record_collected_model_call",
    "reset_unscoped_for_tests",
    "spend_scope",
    "drain_safely",
]


#: Pauses between drain attempts. A drain fails on a transient database fault far more often than
#: on a bad row — live 2026-10-04 a design turn's whole spend (an image generation and a Brandfetch
#: call) was dropped because Postgres answered "too many clients" for one moment at turn end.
_DRAIN_BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 15.0)


def drain_safely(scope: SpendScope, *, sleep: Callable[[float], None] | None = None) -> None:
    """Persist receipts without changing an already-completed work result on a drain error.

    Each attempt moves the buffered rows into a staging scope and drains that; a failed attempt
    puts them back, so a fault after the library drain has emptied its buffers (mid-insert) costs
    nothing either. Only when every attempt fails are the rows lost, and the error then says how
    many rows and how much recorded money went with them.
    """
    import time
    from dataclasses import replace

    pause = sleep or time.sleep
    attempts = len(_DRAIN_BACKOFF_S) + 1
    for attempt in range(1, attempts + 1):
        raw_items, rows = scope.raw.drain(), scope.ledger.drain()
        if not raw_items and not rows:
            return
        staged = replace(scope, raw=BufferedRawSink(), ledger=BufferedLedger())
        for _ref, record, body in raw_items:
            staged.raw.save(record, body)
        for row in rows:
            staged.ledger.record(row)
        try:
            drain_sync(staged)
            return
        except Exception:
            for _ref, record, body in raw_items:
                scope.raw.save(record, body)
            for row in rows:
                scope.ledger.record(row)
            if attempt == attempts:
                results = [row for row in rows if row.phase == "result"]
                log.exception(
                    "spend.drain_failed rows_lost=%d result_rows_lost=%d usd_lost=%s operations=%s",
                    len(rows),
                    len(results),
                    sum((row.cost_usd or Decimal(0) for row in results), Decimal(0)),
                    sorted({row.operation for row in results}),
                )
                return
            log.warning("spend.drain_retry attempt=%d of %d", attempt, attempts, exc_info=True)
            pause(_DRAIN_BACKOFF_S[attempt - 1])
