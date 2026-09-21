from __future__ import annotations

from uuid import UUID

from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_TASK_PRIORITY,
    ARV2_DISCOVERY_TASK_PRIORITY,
    ARV2_DISPLAY_DEDUP_PREFIX,
    ARV2_DISPLAY_TASK_PRIORITY,
    arv2_display_work_id,
)


def test_a_display_page_work_id_is_one_id_per_subject_and_page() -> None:
    subject = "5c1a5a7e-2a5c-4f8a-9d5f-6f0e6b3c1a11"
    overview = arv2_display_work_id("account", subject, "overview")
    assert isinstance(overview, UUID)
    assert overview == arv2_display_work_id("account", subject, "overview")
    assert overview != arv2_display_work_id("account", subject, "insights")
    assert overview != arv2_display_work_id("contact", subject, "contact")


def test_display_pages_yield_to_research_and_discovery() -> None:
    # The fleet orders by ASCENDING priority: research (-100) and discovery (-90) go first.
    assert ARV2_ACCOUNT_TASK_PRIORITY < ARV2_DISCOVERY_TASK_PRIORITY
    assert ARV2_DISCOVERY_TASK_PRIORITY < ARV2_DISPLAY_TASK_PRIORITY < 0
    assert ARV2_DISPLAY_DEDUP_PREFIX == "arv2-display-page:"
