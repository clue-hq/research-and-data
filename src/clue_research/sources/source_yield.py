"""Per-source yield telemetry — the learning-loop substrate (M4.6 / ENG-129).

"Always log which source produced each fact" (the Clay note) made into the adaptive loop's input
(staged-flow §7e / Doc C §6). M4.6 *emits and stores* append-only measurement rows per
(ICP, field-class, source) — coverage (claims/fields produced), precision substrate (claims that
survived M9 verification), cost, freshness, plus a disposition hook; **M13 reweights** the source
profiles (``source_profile`` / ``source_profile_override``) from the aggregate, through the same
config seam (so the learning loop is a config writer, not an engine change).

Name note: this is the **DB telemetry writer** (the ``source_yield`` table). It is distinct from
:func:`clue_obs.otel.record_source_yield`, the M0.5 in-memory *metrics counter* keyed by source;
the two are complementary — the counter is a live dashboard signal, this is the durable, queryable
substrate the reweight reads. M4.6 writes the table; the obs counter stays a metrics emitter.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CostCents, FieldClass, RunId, serialize_value_json

# The recency horizon the freshness_score decays over (M13.3): a surviving claim at-or-past this age
# scores 0.0, a brand-new one 1.0, linearly between. ~6 months — long enough a stale-but-live
# field still registers, short enough that a source feeding ancient claims is visibly down-weighted.
_FRESHNESS_HORIZON_SECONDS: float = 180 * 86_400


class SourceYieldStat(BaseModel):
    """An aggregate of the yield measurements for one (field-class, source) slot.

    Sums the append-only rows; :attr:`precision` is the read-side ratio (claims that survived M9 /
    claims produced) — the signal M13 reweights on. ``None`` precision means the source produced no
    claims yet (nothing to judge). M13.3 (Decision 4) extends this in place with two more reweight
    terms — :attr:`cost_per_surviving_claim` and :attr:`freshness_score` — read from the columns the
    telemetry already records; the per-source ``downstream_signal`` term needs disposition data and
    is computed by the loop (``review``), not here (``sources`` stays disposition-unaware).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_class: FieldClass | None
    source_key: str
    measurements: int
    claims_total: int
    claims_verified: int
    fields_filled: int
    cost_cents: CostCents
    # mean age (seconds) of this slot's measured claims; None when no row recorded a freshness.
    avg_freshness_seconds: float | None = None

    @property
    def precision(self) -> float | None:
        """claims that survived verification / claims produced (``None`` if none produced)."""
        return self.claims_verified / self.claims_total if self.claims_total else None

    @property
    def cost_per_surviving_claim(self) -> CostCents | None:
        """``cost_cents`` spent per claim that survived verification (M13.3 cost term) — the cost of
        a *useful* claim, not a raw one. ``None`` when nothing survived (no denominator)."""
        return self.cost_cents / self.claims_verified if self.claims_verified else None

    @property
    def freshness_score(self) -> float | None:
        """A ``[0,1]`` recency score (M13.3 freshness term): ``1.0`` brand-new, ``0.0`` at/past the
        :data:`_FRESHNESS_HORIZON_SECONDS` horizon, linear between. ``None`` when no measurement
        recorded a freshness (nothing to age)."""
        if self.avg_freshness_seconds is None:
            return None
        return max(0.0, 1.0 - self.avg_freshness_seconds / _FRESHNESS_HORIZON_SECONDS)


def _field_class_value(field_class: FieldClass | str | None) -> str | None:
    if field_class is None:
        return None
    return field_class.value if isinstance(field_class, FieldClass) else field_class


_INSERT = text(
    """
    INSERT INTO source_yield (
        client_id, icp_key, icp_version, field_class, source_key, run_id,
        claims_total, claims_verified, fields_filled, cost_cents, freshness_seconds, disposition
    ) VALUES (
        :client_id, :icp_key, :icp_version, CAST(:field_class AS field_class), :source_key, :run_id,
        :claims_total, :claims_verified, :fields_filled, :cost_cents, :freshness_seconds,
        CAST(:disposition AS jsonb)
    )
    """
)


async def record_source_yield(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str,
    source_key: str,
    field_class: FieldClass | str | None = None,
    icp_version: int | None = None,
    run_id: RunId | None = None,
    claims_total: int = 0,
    claims_verified: int = 0,
    fields_filled: int = 0,
    cost_cents: CostCents = Decimal(0),
    freshness_seconds: int | None = None,
    disposition: dict[str, object] | None = None,
) -> None:
    """Append one yield measurement for ``source_key`` under an ICP/field-class slot.

    Append-only (the source-profile discipline): one row per measurement; M13 aggregates them via
    :func:`get_source_yield`. ``claims_verified`` is the precision substrate (claims that survived
    M9; ``0`` until the verifier exists — the ``disposition`` jsonb is the forward hook for richer
    downstream signal). The DB CHECKs reject a malformed write (negative counts, ``verified`` >
    ``total``, negative cost/freshness).
    """
    await conn.execute(
        _INSERT,
        {
            "client_id": client_id,
            "icp_key": icp_key,
            "icp_version": icp_version,
            "field_class": _field_class_value(field_class),
            "source_key": source_key,
            "run_id": run_id,
            "claims_total": claims_total,
            "claims_verified": claims_verified,
            "fields_filled": fields_filled,
            "cost_cents": cost_cents,
            "freshness_seconds": freshness_seconds,
            "disposition": (serialize_value_json(disposition) if disposition is not None else None),
        },
    )


def _to_field_class(raw: object) -> FieldClass | None:
    return FieldClass(raw) if isinstance(raw, str) else None


async def get_source_yield(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str | None = None,
    icp_version: int | None = None,
    source_key: str | None = None,
    field_class: FieldClass | str | None = None,
) -> list[SourceYieldStat]:
    """Aggregate the yield measurements per (field-class, source) — the M13 / audit read.

    Sums the append-only rows for ``client_id`` (optionally narrowed by ICP key / ICP version /
    source / field-class), grouped by ``(field_class, source_key)``. ``icp_version`` lets M13 read a
    pinned version's telemetry without pooling versions that may carry different source profiles.
    The aggregate is what the learning loop reweights on; a test asserts a write is readable here.
    """
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT field_class, source_key,
                           COUNT(*) AS measurements,
                           COALESCE(SUM(claims_total), 0) AS claims_total,
                           COALESCE(SUM(claims_verified), 0) AS claims_verified,
                           COALESCE(SUM(fields_filled), 0) AS fields_filled,
                           COALESCE(SUM(cost_cents), 0) AS cost_cents,
                           AVG(freshness_seconds) AS avg_freshness_seconds
                    FROM source_yield
                    WHERE client_id = :client_id
                      AND (CAST(:icp_key AS text) IS NULL OR icp_key = :icp_key)
                      AND (CAST(:icp_version AS int) IS NULL OR icp_version = :icp_version)
                      AND (CAST(:source_key AS text) IS NULL OR source_key = :source_key)
                      AND (CAST(:field_class AS text) IS NULL
                           OR field_class = CAST(:field_class AS field_class))
                    GROUP BY field_class, source_key
                    ORDER BY source_key, field_class NULLS FIRST
                    """
                ),
                {
                    "client_id": client_id,
                    "icp_key": icp_key,
                    "icp_version": icp_version,
                    "source_key": source_key,
                    "field_class": _field_class_value(field_class),
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        SourceYieldStat(
            field_class=_to_field_class(row["field_class"]),
            source_key=str(row["source_key"]),
            measurements=int(row["measurements"]),
            claims_total=int(row["claims_total"]),
            claims_verified=int(row["claims_verified"]),
            fields_filled=int(row["fields_filled"]),
            cost_cents=row["cost_cents"],
            avg_freshness_seconds=(
                float(row["avg_freshness_seconds"])
                if row["avg_freshness_seconds"] is not None
                else None
            ),
        )
        for row in rows
    ]
