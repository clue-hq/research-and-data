"""Contract §3.1 rows 5 and 8: derive ``core.employee_range`` / ``core.revenue_band``.

Both rows own **no acquisition source** (their ownership tuple in
:data:`~clue_api.comprehensive_research_contract.COMPREHENSIVE_ACCOUNT_FIELD_SOURCES` is empty):
they are *reused* when the workspace already holds a fresh governed claim, otherwise *derived*
from the governed employee-count / annual-revenue evidence already on file, otherwise left
honestly unresolved. Nothing here spends a provider credit and nothing here invents a value.

Three rules this module exists to make un-restatable:

* **Provenance (founder-ratified, absolute).** A derived claim carries
  ``ClaimProvenanceKind.PLATFORM_INFERRED`` and the *source claim's own*
  ``extraction_method`` / ``source_tier`` / ``source_url`` / ``evidence_span`` / ``artifact_key``
  **and its external-research operation/snapshot/request lineage** — the band's evidence is
  exactly the evidence of the number it restates, down to the immutable provider snapshot that
  produced it. Carrying ``source_key`` + ``artifact_key`` while dropping the three snapshot refs
  used to mint a half-lineaged Exa claim that the ``claim_validate_external_research_lineage``
  trigger (correctly) refuses; live on 2026-08-20 that raw ``DBAPIError`` escaped as
  ``execution_failed`` and paused a running account job. It is **never** written
  as ``ExtractionMethod.HUMAN``: a platform rule is not a person. A source claim that *is* human
  asserted is therefore not derived from at all (it would either launder a human assertion into a
  machine method or write the forbidden one), and settles ``derivation_source_not_derivable``.
* **Vocabulary is registered, not invented.** The revenue bands are the registered
  ``core.revenue_band`` enumeration (:data:`REVENUE_BAND_OPTIONS`, mirrored by the field's
  ``value_schema`` enum and by the Websets enrichment mapping). ``core.employee_range`` is a
  registered ``{label, min, max}`` object with no closed label list, so the deterministic bucket
  boundaries live here — in this one module — and nowhere else.
* **Idempotent on ``(entity, field, run)``**, like every other claim write on this path: a replayed
  assessment reuses the claim it already wrote rather than appending a second one.

A field whose source claim is absent, stale, conflicted or evidence-less is **not** derived; it
settles ``derivation_source_missing`` so the coverage ledger says why the profile row is empty.
A write the database refuses because the restated lineage cannot be proven settles the same way
(``derivation_lineage_unprovable``) rather than escaping: an unprovable band is an honest gap, and
one mechanical write failure must never take a whole research job down with it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    ClaimProvenanceKind,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
    revalidate_with,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    current_value,
    insert_claim,
    record_run_lineage,
)
from clue_research.discovery_scoring.discovery import REVENUE_BAND_OPTIONS
from clue_research.identity import stamp_reuse

#: Which governed field each derive-only §3.1 row restates. Frozen at runtime: these are contract
#: rows, not configuration.
DERIVED_ACCOUNT_FIELD_SOURCES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "core.employee_range": "core.employee_count",
        "core.revenue_band": "core.annual_revenue",
    }
)

#: The deterministic headcount buckets, ``(min, max_or_None, label)``, contiguous and exhaustive
#: over every positive headcount. ``core.employee_range`` registers only the ``{label, min, max}``
#: shape (no closed label vocabulary), so these boundaries are declared once, here.
_EMPLOYEE_BANDS: Final[tuple[tuple[int, int | None, str], ...]] = (
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 500, "201-500"),
    (501, 1_000, "501-1000"),
    (1_001, 5_000, "1001-5000"),
    (5_001, 10_000, "5001-10000"),
    (10_001, None, "10001+"),
)

#: The registered ``core.revenue_band`` enumeration paired with its upper bound (exclusive, USD).
#: The labels are read from :data:`REVENUE_BAND_OPTIONS` rather than retyped, so a registry change
#: breaks this table loudly instead of silently minting an unregistered band.
_REVENUE_BAND_CEILINGS: Final[tuple[Decimal | None, ...]] = (
    Decimal(1_000_000),
    Decimal(10_000_000),
    Decimal(50_000_000),
    Decimal(100_000_000),
    Decimal(500_000_000),
    Decimal(1_000_000_000),
    None,
)

#: Why a derive-only field did not settle into a value.
DERIVATION_SOURCE_MISSING: Final = "derivation_source_missing"
DERIVATION_SOURCE_NOT_DERIVABLE: Final = "derivation_source_not_derivable"
DERIVATION_LINEAGE_UNPROVABLE: Final = "derivation_lineage_unprovable"
DERIVED: Final = "derived"
EXISTING_CLAIM_FRESH: Final = "existing_claim_fresh"

#: The exact ``RAISE EXCEPTION`` texts of ``claim_validate_external_research_lineage`` (migration
#: ``f9281fac77e1``). Matched verbatim, together with the plpgsql ``raise_exception`` SQLSTATE, so
#: the conversion below stays narrow: every other database error on the same INSERT — an integrity
#: violation, a workspace-scope refusal, an immutability trigger — must keep propagating.
_LINEAGE_REFUSAL_MESSAGES: Final = (
    "exa_deep claims require complete operation, snapshot, request, and result artifact lineage",
    "claim external research lineage does not match snapshot/result evidence",
)
_RAISE_EXCEPTION_SQLSTATE: Final = "P0001"


def _is_lineage_refusal(error: DBAPIError) -> bool:
    """Whether this INSERT failure is the lineage trigger refusing an unprovable derived claim."""

    original = error.orig
    if original is None:
        return False
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate is None:
        cause = getattr(original, "__cause__", None)
        sqlstate = getattr(cause, "sqlstate", None)
    if sqlstate != _RAISE_EXCEPTION_SQLSTATE:
        return False
    text_of = str(original)
    return any(message in text_of for message in _LINEAGE_REFUSAL_MESSAGES)


class AccountFieldDerivationError(RuntimeError):
    """The registered band vocabulary and this module's thresholds have drifted apart."""


class AccountFieldDerivation(BaseModel):
    """What one derive-only §3.1 row settled to, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str
    claim_id: ClaimId | None = None
    source_claim_id: ClaimId | None = None
    reason: str

    @property
    def settled(self) -> bool:
        """Whether the field now has a live governed value (derived or reused)."""

        return self.claim_id is not None


def employee_range_value(headcount: int) -> JsonValue:
    """The registered ``{label, min, max}`` band for an exact headcount."""

    if headcount < 1:
        raise ValueError("headcount must be positive to band")
    for minimum, maximum, label in _EMPLOYEE_BANDS:
        if headcount >= minimum and (maximum is None or headcount <= maximum):
            value: dict[str, JsonValue] = {"label": label, "min": minimum}
            if maximum is not None:
                value["max"] = maximum
            return value
    raise AccountFieldDerivationError(f"no employee band covers headcount {headcount}")


def revenue_band_value(amount_usd: Decimal) -> str:
    """The registered ``core.revenue_band`` member for an exact USD annual revenue."""

    if len(_REVENUE_BAND_CEILINGS) != len(REVENUE_BAND_OPTIONS):
        raise AccountFieldDerivationError(
            "the registered revenue-band vocabulary and the derivation thresholds have drifted"
        )
    if amount_usd < 0:
        raise ValueError("annual revenue cannot be negative")
    for ceiling, band in zip(_REVENUE_BAND_CEILINGS, REVENUE_BAND_OPTIONS, strict=True):
        if ceiling is None or amount_usd < ceiling:
            return band
    raise AccountFieldDerivationError(f"no revenue band covers {amount_usd}")


def _derived_value(field_key: str, source_value: JsonValue) -> JsonValue | None:
    """Map a governed source value onto its band, or ``None`` when it is not mappable."""

    if field_key == "core.employee_range":
        if isinstance(source_value, bool) or not isinstance(source_value, int):
            return None
        if source_value < 1:
            return None
        return employee_range_value(source_value)
    if field_key == "core.revenue_band":
        if not isinstance(source_value, Mapping):
            return None
        # A band is a USD band. A figure in another currency is not converted here — an unfaithful
        # band is worse than an honest gap.
        currency = source_value.get("currency")
        if not isinstance(currency, str) or currency.upper() != "USD":
            return None
        amount = source_value.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
            return None
        try:
            parsed = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return None
        if parsed < 0:
            return None
        return revenue_band_value(parsed)
    raise AccountFieldDerivationError(f"{field_key} is not a derived account field")


async def _live_source_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: EntityId,
    field_key: str,
) -> Claim | None:
    """The exact claim that currently *wins* ``field_key``, when it is governed evidence.

    Governed means: it won the merge, it is fresh, it is not in an open conflict and it carries an
    evidence span. Anything else is not something a derivation may restate as fact.
    """

    scope = WorkspaceScope.for_workspace(workspace_id)
    merged = await current_value(conn, account_entity_id, field_key, scope=scope)
    if merged is None or not merged.evidence_backed:
        return None
    for claim in await claims_for(conn, account_entity_id, field_key, scope=scope):
        if claim.id == merged.provenance.claim_id:
            return claim
    return None


async def derive_account_fields(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: ProjectRunId,
    account_entity_id: EntityId,
    field_keys: Sequence[str],
) -> tuple[AccountFieldDerivation, ...]:
    """Settle every requested derive-only §3.1 row, in the order requested.

    Field keys that are not derive-only rows are ignored: this function answers only for the rows
    the contract says are derived, so a caller may pass a whole directive's field list.
    """

    requested = tuple(key for key in field_keys if key in DERIVED_ACCOUNT_FIELD_SOURCES)
    if not requested:
        return ()
    # Every claim written below carries the project run as its ``run_id`` (the lineage trigger
    # requires the run to be registered), so the project lens can back-join it. Idempotent, and
    # ordered before the writes: a run that wrote nothing is inert, an unattributable claim is not.
    await record_run_lineage(
        conn,
        run_id=UUID(str(project_run_id)),
        workspace_id=workspace_id,
        kind="enrichment",
        project_id=project_id,
        project_run_id=UUID(str(project_run_id)),
    )
    outcomes: list[AccountFieldDerivation] = []
    for field_key in requested:
        outcomes.append(
            await _derive_one(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                field_key=field_key,
            )
        )
    return tuple(outcomes)


async def _derive_one(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_entity_id: EntityId,
    field_key: str,
) -> AccountFieldDerivation:
    # §3.1 "reuse **or** derive": a fresh governed claim already answers the row, so nothing is
    # derived over it. This is also the idempotent replay path — the claim this run wrote a moment
    # ago is exactly such a claim.
    existing = await _live_source_claim(
        conn,
        workspace_id=workspace_id,
        account_entity_id=account_entity_id,
        field_key=field_key,
    )
    if existing is not None:
        return AccountFieldDerivation(
            field_key=field_key,
            claim_id=existing.id,
            reason=EXISTING_CLAIM_FRESH,
        )
    source = await _live_source_claim(
        conn,
        workspace_id=workspace_id,
        account_entity_id=account_entity_id,
        field_key=DERIVED_ACCOUNT_FIELD_SOURCES[field_key],
    )
    if source is None:
        return AccountFieldDerivation(field_key=field_key, reason=DERIVATION_SOURCE_MISSING)
    if source.extraction_method is ExtractionMethod.HUMAN:
        # The provenance rule is absolute in both directions: a derived claim may not be labelled
        # ``human``, and a human assertion may not be relabelled as machine extraction.
        return AccountFieldDerivation(
            field_key=field_key,
            source_claim_id=source.id,
            reason=DERIVATION_SOURCE_NOT_DERIVABLE,
        )
    value = _derived_value(field_key, source.value_json)
    if value is None:
        return AccountFieldDerivation(
            field_key=field_key,
            source_claim_id=source.id,
            reason=DERIVATION_SOURCE_NOT_DERIVABLE,
        )
    claim = revalidate_with(
        stamp_reuse(
            account_claim(
                entity_id=account_entity_id,
                field_key=field_key,
                value_json=value,
                source_tier=source.source_tier,
                extraction_method=source.extraction_method,
                confidence=source.confidence,
                run_id=RunId(project_run_id),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=source.source_url,
                evidence_span=source.evidence_span,
                # The band is only as freshly observed as the number it restates.
                observed_at=source.observed_at,
                provenance_kind=ClaimProvenanceKind.PLATFORM_INFERRED,
            ),
            workspace_id=workspace_id,
        ),
        source_key=source.source_key,
        artifact_key=source.artifact_key,
        # The band restates the number, so it restates the number's *whole* evidence chain — the
        # immutable provider operation/snapshot/request that produced it, not just the result
        # artifact. These are the source claim's own refs, never minted here: a source with no
        # external-research lineage (a deterministic API, a scrape) derives a claim with none
        # either, which is exactly what its evidence is.
        source_operation_ref=source.source_operation_ref,
        source_snapshot_ref=source.source_snapshot_ref,
        source_request_ref=source.source_request_ref,
    )
    try:
        # A SAVEPOINT so a refused write cannot poison the surrounding transaction: this function
        # settles several rows and the caller reads/writes coverage on the same connection.
        async with conn.begin_nested():
            claim_id = await insert_claim(conn, claim)
    except DBAPIError as error:
        if not _is_lineage_refusal(error):
            raise
        # The database proved this restatement's evidence chain cannot be verified. The honest
        # answer is an empty, reasoned row — never an invented ref, and never a dead job: this
        # settles like any other underivable source so coverage reports the gap and the account
        # agent walks on to finalization. The trigger stays the authority and is untouched.
        return AccountFieldDerivation(
            field_key=field_key,
            source_claim_id=source.id,
            reason=DERIVATION_LINEAGE_UNPROVABLE,
        )
    return AccountFieldDerivation(
        field_key=field_key,
        claim_id=claim_id,
        source_claim_id=source.id,
        reason=DERIVED,
    )


__all__ = [
    "DERIVATION_LINEAGE_UNPROVABLE",
    "DERIVATION_SOURCE_MISSING",
    "DERIVATION_SOURCE_NOT_DERIVABLE",
    "DERIVED",
    "DERIVED_ACCOUNT_FIELD_SOURCES",
    "EXISTING_CLAIM_FRESH",
    "AccountFieldDerivation",
    "AccountFieldDerivationError",
    "derive_account_fields",
    "employee_range_value",
    "revenue_band_value",
]
