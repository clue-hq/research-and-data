#!/usr/bin/env python3
"""Compose one real persisted C7 view through the production runtime (no fixture readers)."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.narrative_wiring import register_narrative_wiring
from clue_api.research_view_runtime import build_production_research_view_runtime
from clue_api.storage_wiring import build_storage_backend
from clue_config import load_settings
from clue_core import (
    EntityId,
    EntityType,
    ProjectRunId,
    ResearchOwnedReference,
    ResearchViewReadRequest,
)
from clue_db import db_lifespan, repeatable_read_transaction


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a real account/contact research view already persisted by the normal "
            "research subsystem. This command performs no acquisition or model call."
        )
    )
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--project-run-id", required=True, type=UUID)
    parser.add_argument("--subject-entity-id", required=True, type=UUID)
    parser.add_argument(
        "--subject-entity-type",
        required=True,
        choices=("account", "contact"),
    )
    parser.add_argument(
        "--product-id",
        help="Defaults to the exact product pinned on the supplied project run.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = load_settings()
    register_compliance_wiring()
    register_narrative_wiring()
    runtime = build_production_research_view_runtime(
        storage=build_storage_backend(settings)
    )
    async with db_lifespan():
        async with repeatable_read_transaction() as conn:
            pinned = (
                await conn.execute(
                    text(
                        """
                        SELECT product_id
                        FROM project_run
                        WHERE id = :project_run_id
                          AND workspace_id = :workspace_id
                          AND project_id = :project_id
                        """
                    ),
                    {
                        "project_run_id": args.project_run_id,
                        "workspace_id": args.workspace_id,
                        "project_id": args.project_id,
                    },
                )
            ).one_or_none()
            route_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM research_view_field_route WHERE active")
                    )
                ).scalar_one()
            )
        if pinned is None:
            raise SystemExit("the supplied project run was not found in that workspace/project")
        if route_count == 0:
            raise SystemExit(
                "no active research-view field routes are registered; run the normal research "
                "startup/pack registration path before inspecting persisted output"
            )
        pinned_product = pinned[0]
        if args.product_id is not None and args.product_id != pinned_product:
            raise SystemExit("--product-id does not match the product pinned on the project run")
        request = ResearchViewReadRequest(
            workspace_id=args.workspace_id,
            project_id=args.project_id,
            project_run_id=ProjectRunId(args.project_run_id),
            subject_entity_id=EntityId(args.subject_entity_id),
            subject_entity_type=EntityType(args.subject_entity_type),
            product_id=pinned_product,
        )
        view = await runtime.composer.compose(request)
        references = tuple(
            item
            for section in view.sections
            for item in section.items
            if isinstance(item, ResearchOwnedReference)
        )
        owner_values = await runtime.owner_references.resolve(request, references)
        return {
            "trial_mode": "production_persisted_read_only",
            "acquisition_performed": False,
            "view": view.model_dump(mode="json"),
            "owner_reference_resolutions": [
                item.model_dump(mode="json") for item in owner_values
            ],
        }


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
