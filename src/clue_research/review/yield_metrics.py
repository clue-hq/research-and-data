"""M13.3 — per-(ICP, field-class, source) yield metrics (the reweight input).

``compute_yield`` combines two read-only provenance sources, no new collection (staged-flow §7e):

* the M4.6 ``source_yield`` telemetry (``get_source_yield``) — precision (claims that survived M9 ÷
  produced), coverage (fields filled), freshness, cost per surviving claim;
* the M13.2 labeled dataset (``read_labeled_dataset``) — the **downstream signal**: the
  accepted-account / reply rate among the accounts each source contributed to, attributed via each
  disposition's frozen ``contributing_source_keys``.

``sources`` stays disposition-unaware (it never reads the disposition tables); the cross-table
downstream term is joined here — the one place that legitimately sees both (``review`` may import
``sources`` and owns ``labeled_dataset``). D7: with no shared sales outcomes the rate is ``None``
and ``has_downstream_signal`` is ``False`` — the loop reweights on verification-survival +
coverage + cost with reduced confidence (spec §M13.3 open decisions).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import CostCents, EntityId, FieldClass
from clue_research.review.disposition import DispositionType
from clue_research.review.labeled_dataset import read_labeled_dataset
from clue_research.sources import SourceYieldStat, get_source_yield

# Account-level sales outcomes that count toward the downstream signal (substrate §9 / staged-flow
# §7e). ``claim_*`` dispositions are claim-level review actions, not account outcomes;
# ``account_contacted`` is activity, not a result — both are excluded from the rate.
_POSITIVE_OUTCOMES: frozenset[DispositionType] = frozenset(
    {
        DispositionType.ACCOUNT_ACCEPTED,
        DispositionType.REPLY_RECEIVED,
        DispositionType.MEETING_BOOKED,
        DispositionType.CLOSED_WON,
    }
)
_NEGATIVE_OUTCOMES: frozenset[DispositionType] = frozenset(
    {
        DispositionType.ACCOUNT_REJECTED,
        DispositionType.CLOSED_LOST,
    }
)
_OUTCOME_TYPES: frozenset[DispositionType] = _POSITIVE_OUTCOMES | _NEGATIVE_OUTCOMES


class SourceYield(BaseModel):
    """One (field-class, source) slot's full M13.3 yield: the telemetry-derived terms (precision /
    coverage / freshness / cost, from :class:`SourceYieldStat`) plus the downstream signal (the
    accepted/reply rate among accounts this source fed). ``downstream_signal`` is ``None`` when no
    shared sales outcome touched the source (D7); ``downstream_accounts`` is the support count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stat: SourceYieldStat
    downstream_signal: float | None = None
    downstream_accounts: int = 0

    @property
    def field_class(self) -> FieldClass | None:
        return self.stat.field_class

    @property
    def source_key(self) -> str:
        return self.stat.source_key

    @property
    def precision(self) -> float | None:
        return self.stat.precision

    @property
    def freshness_score(self) -> float | None:
        return self.stat.freshness_score

    @property
    def cost_per_surviving_claim(self) -> CostCents | None:
        return self.stat.cost_per_surviving_claim


class YieldMetrics(BaseModel):
    """The per-(field-class, source) yield for one ``(client, icp_key, icp_spec_version)`` — the
    deterministic reweight input. ``has_downstream_signal`` records whether any sales outcome was
    available (D7: the loop notes reduced confidence when ``False``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str
    icp_key: str
    icp_spec_version: int | None = None
    sources: tuple[SourceYield, ...] = ()
    has_downstream_signal: bool = False

    def by_source_key(self) -> dict[str, list[SourceYield]]:
        """Group the slots by ``source_key`` (a source may appear once per field-class)."""
        out: dict[str, list[SourceYield]] = {}
        for s in self.sources:
            out.setdefault(s.source_key, []).append(s)
        return out


async def compute_yield(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str,
    icp_spec_version: int | None = None,
) -> YieldMetrics:
    """Compute the per-(field-class, source) yield for a pinned ICP segment+version (M13.3).

    Read-only aggregation over existing provenance (no new collection, spec §M13.3 AC): the M4.6
    telemetry (``get_source_yield``) plus the M13.2 labeled dataset (``read_labeled_dataset``). The
    downstream signal is the share of *accounts* (deduped by ``account_entity_id``) with a positive
    sales outcome among those carrying any outcome, attributed to each disposition's contributing
    sources.
    """
    stats = await get_source_yield(
        conn, client_id=client_id, icp_key=icp_key, icp_version=icp_spec_version
    )
    rows = await read_labeled_dataset(
        conn, client_id=client_id, icp_key=icp_key, icp_spec_version=icp_spec_version
    )

    positive_accounts: dict[str, set[EntityId]] = {}
    outcome_accounts: dict[str, set[EntityId]] = {}
    for row in rows:
        if row.disposition_type not in _OUTCOME_TYPES:
            continue
        is_positive = row.disposition_type in _POSITIVE_OUTCOMES
        for source_key in set(row.contributing_source_keys):
            outcome_accounts.setdefault(source_key, set()).add(row.account_entity_id)
            if is_positive:
                positive_accounts.setdefault(source_key, set()).add(row.account_entity_id)

    def _downstream(source_key: str) -> float | None:
        seen = outcome_accounts.get(source_key)
        if not seen:
            return None
        return len(positive_accounts.get(source_key, set())) / len(seen)

    sources = tuple(
        SourceYield(
            stat=stat,
            downstream_signal=_downstream(stat.source_key),
            downstream_accounts=len(outcome_accounts.get(stat.source_key, set())),
        )
        for stat in stats
    )
    return YieldMetrics(
        client_id=client_id,
        icp_key=icp_key,
        icp_spec_version=icp_spec_version,
        sources=sources,
        has_downstream_signal=bool(outcome_accounts),
    )
