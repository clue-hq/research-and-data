"""Stage three of the catalog identity ladder: one batched model call per run that decides, for
every lineup entry the fingerprint and spelling stages could not place, whether it is the SAME
offering as a product on file (or as an earlier candidate in the same batch) or a genuinely NEW
one — with each entry's official page as evidence. Validated 2026-09-08 on the four Insight Health
catalogs (28 → 18 rows, no wrong merge, identical on gpt-5-mini and grok-4.6).

The model never merges anything by itself: it returns decisions with a confidence, and the
synchronizer applies only ``high`` automatically; the rest become rows flagged for the gate.
The call goes through R1's :class:`~clue_api.arv2.calls.ProviderCaller` (estimate → raw record →
ledger row) and this module NEVER raises: any failure is a full set of ``new_product``/``low``
decisions carrying the reason, so a reconciler outage degrades the run to "mint everything and let
a human look", which is exactly what the ladder did before this stage existed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import SecretStr

from clue_api.arv2.calls import CallResult, CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.onboarding_lineage import CatalogProduct
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_obs import get_logger

log = get_logger("clue_api.arv2.onboarding_reconcile")

__all__ = [
    "RECONCILE_SYSTEM_PROMPT",
    "CatalogReconciler",
    "ExistingProduct",
    "OpenRouterCatalogReconciler",
    "ReconcileDecision",
    "reconcile_output_schema",
]

Decision = Literal["same_as_existing", "same_as_candidate", "new_product"]
Confidence = Literal["high", "medium", "low"]

_DECISIONS: tuple[str, ...] = ("same_as_existing", "same_as_candidate", "new_product")
_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")

RECONCILE_SYSTEM_PROMPT = (
    "You reconcile a seller's product catalog. Given the products already on file (id, name, "
    "aliases, official page URL, description) and candidate entries just discovered, decide for "
    "EACH candidate whether it is the SAME offering as one on file, the SAME offering as an "
    "EARLIER candidate in this list, or a genuinely NEW offering. Judge by what the offering is. "
    "Evidence rules: (1) the same official_url is strong evidence of the same offering — but some "
    "companies present several offerings on one page, so if the descriptions describe different "
    "jobs they are different products even on one page; (2) different product-specific pages are "
    "strong evidence of different offerings; a homepage, pricing or listing URL is not evidence "
    "either way; (3) wording differences alone (spacing, 'AI', 'Agent', trademark marks, word "
    "order) never make a new product. Never invent products. Answer with exactly one decision per "
    "candidate, in the candidates' order. Return JSON only."
)

#: The pre-spend reservation for the one call (law 2). It only has to be the right order of
#: magnitude — the real cost is read back from OpenRouter's own metering.
_ESTIMATE = SpendEstimate(usd=Decimal("0.01"))


@dataclass(frozen=True)
class ExistingProduct:
    """One product already on the spine, as the model is shown it."""

    product_id: str
    name: str
    aliases: tuple[str, ...]
    official_url: str | None
    description: str


@dataclass(frozen=True)
class ReconcileDecision:
    """What the ladder learned about one candidate. ``confidence`` gates the automatic merge."""

    candidate: str
    decision: Decision
    product_id: str | None
    candidate_name: str | None
    confidence: Confidence
    reason: str


class CatalogReconciler(Protocol):
    """The seam the synchronizer holds. One decision per candidate, in order; never raises."""

    async def reconcile(
        self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]
    ) -> tuple[ReconcileDecision, ...]: ...


def reconcile_output_schema() -> dict[str, Any]:
    """The strict JSON schema the answer must satisfy — every field required, nothing extra."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["decisions"],
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "candidate",
                        "decision",
                        "product_id",
                        "candidate_name",
                        "confidence",
                        "reason",
                    ],
                    "properties": {
                        "candidate": {"type": "string"},
                        "decision": {"type": "string", "enum": list(_DECISIONS)},
                        "product_id": {"type": ["string", "null"]},
                        "candidate_name": {"type": ["string", "null"]},
                        "confidence": {"type": "string", "enum": list(_CONFIDENCES)},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }


def _fallback(candidates: Sequence[CatalogProduct], reason: str) -> tuple[ReconcileDecision, ...]:
    """Every candidate as a new product at ``low`` confidence — the ladder's honest default."""
    return tuple(
        ReconcileDecision(entry.name, "new_product", None, None, "low", reason)
        for entry in candidates
    )


class OpenRouterCatalogReconciler:
    """The model stage, over one OpenRouter chat call per run."""

    def __init__(
        self,
        *,
        caller_factory: Callable[[], ProviderCaller],
        api_key: SecretStr,
        model: str,
        base_url: str,
        timeout_s: float = 120.0,
    ) -> None:
        self._caller_factory = caller_factory
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_s = timeout_s

    async def reconcile(
        self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]
    ) -> tuple[ReconcileDecision, ...]:
        """Decide every candidate in one call. Any failure degrades; nothing here raises."""
        if not candidates:
            return ()
        if not existing and len(candidates) == 1:
            # Nothing to compare against and nothing to compare with: the answer is knowable
            # without spending, and a call whose only possible reply is "new" is a call not worth
            # making.
            return (
                ReconcileDecision(
                    candidates[0].name,
                    "new_product",
                    None,
                    None,
                    "high",
                    "nothing on file to compare with",
                ),
            )
        payload = {
            "products_on_file": [
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "aliases": list(product.aliases),
                    "official_url": product.official_url,
                    "description": product.description,
                }
                for product in existing
            ],
            "candidates": [
                {
                    "name": entry.name,
                    "official_url": entry.official_url,
                    "description": entry.short_description,
                }
                for entry in candidates
            ],
        }
        request = openrouter_chat_request(
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            messages=[
                {"role": "system", "content": RECONCILE_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "reconciliation",
                    "strict": True,
                    "schema": reconcile_output_schema(),
                },
            },
            temperature=0,
            timeout_s=self._timeout_s,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label="catalog-reconcile",
            request=request,
            estimate=_ESTIMATE,
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={"candidates": len(candidates), "products_on_file": len(existing)},
        )

        def _send() -> CallResult:
            # R1's rule: a fresh caller per hop, built inside the worker thread — its halt latch
            # and totals are unlocked mutable state.
            return self._caller_factory().call(spec)

        try:
            result = await asyncio.to_thread(_send)
            if result.response.status != 200:
                raise RuntimeError(f"openrouter status {result.response.status}")
            answer = json.loads(openrouter_message_text(result.json()))
            # A reply that parsed but is not the shape asked for is a *bad answer*, not an outage:
            # it goes to the validator, which turns every candidate into new/low with the invalid
            # reason, rather than being reported as the provider being unavailable.
            decisions = answer.get("decisions") if isinstance(answer, dict) else None
        except Exception as error:  # noqa: BLE001 — a step outcome for the synchronizer, never a raise
            log.warning("onboarding_reconcile.unavailable", reason=str(error)[:200])
            return _fallback(candidates, f"reconciler_unavailable: {str(error)[:120]}")
        return _validate(decisions, existing=existing, candidates=candidates)


def _validate(
    raw: object,
    *,
    existing: Sequence[ExistingProduct],
    candidates: Sequence[CatalogProduct],
) -> tuple[ReconcileDecision, ...]:
    """One decision per candidate, references checked; anything malformed is new/low, never a raise.

    The model is trusted for judgement and for nothing else: an id that names no product on file, a
    candidate pointing at itself or at a LATER candidate (which would make the merge order-
    dependent), a missing entry, an unknown enum — each becomes a plain ``new_product`` at ``low``,
    so the worst a bad answer can do is leave a duplicate for the human gate.
    """
    by_candidate: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("candidate"), str):
                by_candidate.setdefault(item["candidate"], item)
    ids = {product.product_id for product in existing}
    out: list[ReconcileDecision] = []
    for index, candidate in enumerate(candidates):
        item = by_candidate.get(candidate.name)
        if item is None:
            out.append(_invalid(candidate, "no decision returned"))
            continue
        decision, confidence = item.get("decision"), item.get("confidence")
        reason = str(item.get("reason") or "")[:500]
        if decision not in _DECISIONS or confidence not in _CONFIDENCES:
            out.append(_invalid(candidate, "malformed decision"))
            continue
        if decision == "same_as_existing":
            if item.get("product_id") not in ids:
                out.append(_invalid(candidate, "unknown product id"))
                continue
            out.append(
                ReconcileDecision(
                    candidate.name,
                    "same_as_existing",
                    str(item["product_id"]),
                    None,
                    confidence,
                    reason,
                )
            )
            continue
        if decision == "same_as_candidate":
            earlier = {entry.name for entry in candidates[:index]}
            if item.get("candidate_name") not in earlier:
                out.append(_invalid(candidate, "candidate reference is not an earlier candidate"))
                continue
            out.append(
                ReconcileDecision(
                    candidate.name,
                    "same_as_candidate",
                    None,
                    str(item["candidate_name"]),
                    confidence,
                    reason,
                )
            )
            continue
        out.append(ReconcileDecision(candidate.name, "new_product", None, None, confidence, reason))
    return tuple(out)


def _invalid(candidate: CatalogProduct, detail: str) -> ReconcileDecision:
    """A candidate whose answer could not be used: mint it, flag it, and say why."""
    return ReconcileDecision(
        candidate.name, "new_product", None, None, "low", f"reconciler_invalid: {detail}"
    )
