"""The turn-start card of a chat's own files (F3 Phase 2, WS-28, spec D-23).

Pure function over the restored file list: no disk, no database, no clock of its own. The ages
the tests pin are exact because ``now`` is passed in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clue_agents.workspace_snapshot import Receipt, SnapshotEntry, SnapshotManifest, tier_for
from clue_api.agent_workspace_files_card import (
    WORKSPACE_FILES_MAX_LISTED,
    WORKSPACE_FILES_MEDIA_TYPE,
    build_workspace_files_card,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _entry(
    path: str,
    *,
    written_at: datetime,
    size: int = 3,
    receipt: Receipt | None = None,
    expired_at: datetime | None = None,
) -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        sha256="a" * 64,
        size=size,
        media_type="text/plain",
        tier=tier_for(path),
        written_at=written_at,
        receipt=receipt,
        expired_at=expired_at,
    )


def test_card_lists_live_files_with_age_and_expired_files_with_receipts() -> None:
    """What the agent still has, how old it is, and what is gone with the way to get it again."""

    manifest = SnapshotManifest(
        entries=(
            _entry("scratch/a", written_at=NOW - timedelta(days=2)),
            _entry(
                "reads/r.json",
                written_at=NOW - timedelta(days=5),
                receipt=Receipt(
                    source="run_crm_action",
                    operation_id="op-1",
                    produced_at=NOW - timedelta(days=5),
                    details={"tool": "run_crm_action"},
                    read_again="Call run_crm_action again with the same parameters.",
                ),
                expired_at=NOW - timedelta(days=3),
            ),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    assert card["schema_version"] == "1"
    assert card["generated_at"] == NOW.isoformat()
    assert card["live"] == [
        {
            "path": "scratch/a",
            "folder": "scratch",
            "size": 3,
            "age_hours": 48,
            "tier": "working_file",
        }
    ]
    assert card["omitted"] == {}
    expired = card["expired"]
    assert isinstance(expired, list)
    assert len(expired) == 1
    assert expired[0]["path"] == "reads/r.json"
    assert expired[0]["tier"] == "raw_input"
    assert expired[0]["expired_at"] == (NOW - timedelta(days=3)).isoformat()
    assert expired[0]["receipt"]["source"] == "run_crm_action"
    assert expired[0]["receipt"]["operation_id"] == "op-1"
    assert expired[0]["receipt"]["details"] == {"tool": "run_crm_action"}
    assert expired[0]["receipt"]["read_again"] == (
        "Call run_crm_action again with the same parameters."
    )
    # Founder-reviewed wording (Task 8): the key is part of the contract from the start, so the
    # agent-facing sentence is one edit away and never a schema change.
    assert "note" in card


def test_card_bounds_the_live_list_and_says_what_was_left_out() -> None:
    """A long list is cut, and the agent is told how many it was not shown, by folder."""

    manifest = SnapshotManifest(
        entries=tuple(
            _entry(f"work/f{index:04d}.txt", written_at=NOW - timedelta(hours=1))
            for index in range(250)
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    live = card["live"]
    assert isinstance(live, list)
    assert len(live) == WORKSPACE_FILES_MAX_LISTED == 200
    assert [item["path"] for item in live[:2]] == ["work/f0000.txt", "work/f0001.txt"]
    assert card["omitted"] == {"work": 50}


def test_an_empty_or_missing_manifest_gives_an_empty_card() -> None:
    """A brand-new chat, or snapshots switched off: the card is honest rather than absent."""

    for manifest in (None, SnapshotManifest(entries=())):
        card = build_workspace_files_card(manifest, now=NOW)
        assert card["live"] == []
        assert card["expired"] == []
        assert card["omitted"] == {}


def test_an_expired_entry_with_no_receipt_still_reads_as_a_receipt() -> None:
    """Task 5 stamps one on every expiry; the card does not depend on that to hold its shape."""

    manifest = SnapshotManifest(
        entries=(
            _entry(
                "work/large_tool_results/clip.txt",
                written_at=NOW - timedelta(days=9),
                expired_at=NOW - timedelta(days=1),
            ),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    expired = card["expired"]
    assert isinstance(expired, list)
    assert expired[0]["receipt"] == {
        "source": "unknown",
        "operation_id": None,
        "produced_at": None,
        "details": {},
        "read_again": "",
    }


def test_the_card_counts_whole_hours_and_never_a_negative_age() -> None:
    """``age_hours`` is floored, and a file written after ``now`` is zero rather than nonsense."""

    manifest = SnapshotManifest(
        entries=(
            _entry("outputs/done.md", written_at=NOW - timedelta(hours=3, minutes=59)),
            _entry("scratch/ahead.md", written_at=NOW + timedelta(minutes=5)),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    live = card["live"]
    assert isinstance(live, list)
    assert {item["path"]: item["age_hours"] for item in live} == {
        "outputs/done.md": 3,
        "scratch/ahead.md": 0,
    }
    assert {item["path"]: item["tier"] for item in live} == {
        "outputs/done.md": "work_product",
        "scratch/ahead.md": "working_file",
    }


def test_the_media_type_names_this_card() -> None:
    assert WORKSPACE_FILES_MEDIA_TYPE == "application/vnd.clue.agent-workspace-files+json"
