"""The onboarding half of a workspace repair plan (spec 2026-10-25 §3.4 A). Read-only.

**Which attempt counts.** The newest ``full`` run is the onboarding; every ``repair`` run started
after it is laid over it. For each step — keyed by kind and subject — the newest attempt wins, so
a step a repair already fixed is not planned again and its gap disappears.

**What is planned.** Every step whose newest attempt ``failed``, re-run as a small ``repair`` run
instead of the ~$2 full walk:

- a failed ``catalog_sync`` re-runs ``lineup`` (which runs the catalog sync again);
- a failed ``synthesis`` (the ICP turn) re-runs it, and the driver writes the personas of the ICPs
  it registers, so its personas are not planned separately;
- ``empty`` is a correct outcome (nobody could find reviews) and is never planned.

**Never two at once.** While any ``full`` or ``repair`` run is queued or running, nothing is
planned: the open run may fix it, and a second run would race it on the same documents.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.exa_client import AGENT_EFFORT_ESTIMATE_USD, DEEP_REASONING_ESTIMATE_USD
from clue_config import Settings

#: Per-step estimates that no setting decides. Fixed figures, labelled as estimates wherever they
#: are shown; correct them here. The ICP and persona turns are model spend only — placeholders
#: until recent real turns are measured (spec 2026-10-25 §3.4 "Estimated cost").
SYNTHESIS_ESTIMATE_USD = Decimal("1.00")
PERSONA_ESTIMATE_USD = Decimal("0.50")
CATALOG_RECONCILE_ESTIMATE_USD = Decimal("0.02")
#: One vision call per asset description (the design describer), used by the kit half.
DESCRIPTION_ESTIMATE_USD = Decimal("0.002")

NOT_ONBOARDED = "no onboarding has run for this workspace; start one"


@dataclass(frozen=True)
class PlannedStep:
    kind: str
    subject_ref: str | None
    reason: str
    estimate_usd: Decimal

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject_ref": self.subject_ref,
            "reason": self.reason,
            "estimate_usd": str(self.estimate_usd),
        }


@dataclass(frozen=True)
class OnboardingRepairPlan:
    steps: tuple[PlannedStep, ...] = ()
    in_flight: tuple[str, ...] = ()
    brand_id: str | None = None
    company_domain: str | None = None
    company_name: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "steps": [step.as_json() for step in self.steps],
            "in_flight": list(self.in_flight),
            "brand_id": self.brand_id,
            "company_domain": self.company_domain,
        }


def step_estimate_usd(kind: str, settings: Settings) -> Decimal:
    efforts = {
        "overview": settings.onboarding_overview_effort,
        "reviews": settings.onboarding_reviews_effort,
        "product_research": settings.onboarding_product_effort,
        "customers": settings.onboarding_customers_effort,
    }
    if kind in efforts:
        return AGENT_EFFORT_ESTIMATE_USD.get(efforts[kind], Decimal("1.00"))
    if kind == "lineup":
        return 2 * DEEP_REASONING_ESTIMATE_USD + CATALOG_RECONCILE_ESTIMATE_USD
    if kind == "synthesis":
        return SYNTHESIS_ESTIMATE_USD
    if kind == "persona":
        return PERSONA_ESTIMATE_USD
    return Decimal(0)


async def plan_onboarding_repair(
    conn: AsyncConnection, *, workspace_id: str, settings: Settings | None = None
) -> OnboardingRepairPlan:
    settings = settings or Settings()
    full = (
        (
            await conn.execute(
                text(
                    "SELECT r.run_id, r.brand_id, r.company_domain, r.requested_at, b.name"
                    " FROM onboarding_run r LEFT JOIN brand b ON b.brand_id = r.brand_id"
                    " WHERE r.workspace_id = :w AND r.kind = 'full'"
                    " ORDER BY r.requested_at DESC LIMIT 1"
                ),
                {"w": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if full is None:
        return OnboardingRepairPlan(in_flight=(NOT_ONBOARDED,))
    context: dict[str, Any] = {
        "brand_id": str(full["brand_id"]),
        "company_domain": str(full["company_domain"]),
        "company_name": str(full["name"] or full["company_domain"]),
    }
    open_run = (
        (
            await conn.execute(
                text(
                    "SELECT kind, status FROM onboarding_run WHERE workspace_id = :w"
                    " AND kind IN ('full', 'repair') AND status IN ('queued', 'running')"
                    " ORDER BY requested_at DESC LIMIT 1"
                ),
                {"w": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if open_run is not None:
        note = f"a {open_run['kind']} onboarding run is {open_run['status']}"
        return OnboardingRepairPlan(in_flight=(note,), **context)

    attempts = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (s.kind, coalesce(s.subject_ref, ''))"
                    " s.kind, s.subject_ref, s.status, s.failure_code"
                    " FROM onboarding_step s JOIN onboarding_run r ON r.run_id = s.run_id"
                    " WHERE r.workspace_id = :w AND (r.run_id = :full OR (r.kind = 'repair'"
                    " AND r.requested_at >= :at))"
                    " ORDER BY s.kind, coalesce(s.subject_ref, ''), r.requested_at DESC,"
                    " s.started_at DESC NULLS LAST"
                ),
                {"w": workspace_id, "full": full["run_id"], "at": full["requested_at"]},
            )
        )
        .mappings()
        .all()
    )
    failed = {
        (row["kind"], row["subject_ref"]): row["failure_code"]
        for row in attempts
        if row["status"] == "failed"
    }
    planned: dict[tuple[str, str | None], str] = {}
    for (kind, subject), code in failed.items():
        if kind == "catalog_sync":
            planned.setdefault(("lineup", None), f"the product catalog sync failed ({code})")
        elif kind == "persona" and ("synthesis", None) in failed:
            continue  # the re-run ICP turn writes its own personas
        else:
            label = f"{kind} {subject}" if subject else kind
            planned[(kind, subject)] = f"{label}: the last attempt failed ({code})"
    steps = tuple(
        PlannedStep(
            kind=kind,
            subject_ref=subject,
            reason=reason,
            estimate_usd=step_estimate_usd(kind, settings),
        )
        for (kind, subject), reason in sorted(
            planned.items(), key=lambda item: (item[0][0], item[0][1] or "")
        )
    )
    return OnboardingRepairPlan(steps=steps, **context)


async def research_gaps(conn: AsyncConnection, *, workspace_id: str) -> list[dict[str, Any]]:
    """Every research or ICP step whose newest attempt failed, in plain words (spec §5.2).

    The same merge as the planner — the newest full run with every later repair run laid over
    it — so a gap a repair fixed disappears. ``empty`` is a correct outcome, never a gap.
    """
    full = (
        await conn.execute(
            text(
                "SELECT run_id, requested_at FROM onboarding_run WHERE workspace_id = :w"
                " AND kind = 'full' ORDER BY requested_at DESC LIMIT 1"
            ),
            {"w": workspace_id},
        )
    ).first()
    if full is None:
        return []
    rows = (
        await conn.execute(
            text(
                "SELECT * FROM (SELECT DISTINCT ON (s.kind, coalesce(s.subject_ref, ''))"
                " s.kind, s.subject_ref, s.status, s.failure_code, s.failure_message"
                " FROM onboarding_step s JOIN onboarding_run r ON r.run_id = s.run_id"
                " WHERE r.workspace_id = :w AND (r.run_id = :full OR (r.kind = 'repair'"
                " AND r.requested_at >= :at))"
                " ORDER BY s.kind, coalesce(s.subject_ref, ''), r.requested_at DESC,"
                " s.started_at DESC NULLS LAST) newest WHERE status = 'failed'"
                " ORDER BY kind, coalesce(subject_ref, '')"
            ),
            {"w": workspace_id, "full": full.run_id, "at": full.requested_at},
        )
    ).mappings()
    return [
        {
            "area": "research",
            "item": f"{row['kind']}:{row['subject_ref']}" if row["subject_ref"] else row["kind"],
            "code": row["failure_code"],
            "message": (row["failure_message"] or "")[:200] or None,
        }
        for row in rows
    ]


async def brand_kit_gaps(conn: AsyncConnection, *, workspace_id: str) -> list[dict[str, Any]]:
    """The newest kit-building job's own ``gaps`` (spec §5.1), as onboarding-view entries."""
    from clue_design.ingestion import list_recent
    from clue_design.kit_repair import KIT_BUILDING_KINDS

    jobs = await list_recent(conn, workspace_id=workspace_id, limit=1, kinds=KIT_BUILDING_KINDS)
    evidence = (jobs[0].get("evidence") if jobs else None) or {}
    gaps = evidence.get("gaps") if isinstance(evidence, dict) else None
    return [
        {
            "area": "brand_kit",
            "item": str(gap.get("area") or "unknown"),
            "code": gap.get("reason"),
            "message": f"{gap.get('failed', 1)} failed",
        }
        for gap in (gaps if isinstance(gaps, list) else [])
        if isinstance(gap, dict)
    ]
