"""Versioned healthcare account-deep source-profile binding for M8B E2.

The shared healthcare pack remains unchanged. This helper writes only the named workspace/ICP
override, excludes Parallel Task by omission, and confines technology acquisition to the CORE
slot where a deliberately registered technographic field can select it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldClass
from clue_research.icp import (
    SourceWeight,
    WeightedSource,
    register_source_profile_override,
)

HEALTHCARE_ACCOUNT_DEEP_PACK_KEY = "healthcare_practice"
HEALTHCARE_OFFICIAL_PAGE_SOURCE = "firecrawl_site"
HEALTHCARE_EXCLUDED_ACCOUNT_DEEP_SOURCES = frozenset({"parallel_task"})


async def bind_healthcare_account_deep_source_override(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    icp_key: str,
    version: int,
    official_page_source: str = HEALTHCARE_OFFICIAL_PAGE_SOURCE,
) -> None:
    """Register the accepted M8B section 4.3 override without mutating the shared pack."""

    if official_page_source in HEALTHCARE_EXCLUDED_ACCOUNT_DEEP_SOURCES:
        raise ValueError("the official-page source cannot be an excluded research product")
    await register_source_profile_override(
        conn,
        HEALTHCARE_ACCOUNT_DEEP_PACK_KEY,
        workspace_id,
        (
            WeightedSource(source_key="sumble_jobs", weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key=official_page_source, weight=SourceWeight.HIGH, rank=2),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=3),
        ),
        field_class=FieldClass.ACCOUNT,
        icp_key=icp_key,
        version=version,
    )
    await register_source_profile_override(
        conn,
        HEALTHCARE_ACCOUNT_DEEP_PACK_KEY,
        workspace_id,
        (
            WeightedSource(source_key="sumble_tech_stack", weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key=official_page_source, weight=SourceWeight.HIGH, rank=2),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=3),
        ),
        field_class=FieldClass.CORE,
        icp_key=icp_key,
        version=version,
    )
    await register_source_profile_override(
        conn,
        HEALTHCARE_ACCOUNT_DEEP_PACK_KEY,
        workspace_id,
        (
            WeightedSource(source_key=official_page_source, weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=2),
        ),
        field_class=FieldClass.ACCOUNT_RESONANCE,
        icp_key=icp_key,
        version=version,
    )


__all__ = [
    "HEALTHCARE_ACCOUNT_DEEP_PACK_KEY",
    "HEALTHCARE_EXCLUDED_ACCOUNT_DEEP_SOURCES",
    "HEALTHCARE_OFFICIAL_PAGE_SOURCE",
    "bind_healthcare_account_deep_source_override",
]
