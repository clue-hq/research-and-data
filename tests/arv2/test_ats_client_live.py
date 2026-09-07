"""The ATS client against the three real boards — Global Constraint 3: no replay, no mocks.

Every call here is free and keyless, so these tests never skip: if they fail, either a provider
changed its wire shape or a subject company changed its board, and both are things the lane must
learn about from a red test rather than from a silently empty account profile.

The boards under test are the brief's answer keys: Zafran Security and Probook on Ashby (§11),
Translucent on Greenhouse and Smarsh on Lever.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from clue_api.arv2.ats_client import (
    AtsBoard,
    BoardNotFound,
    board_url,
    fetch_postings,
    find_board,
)
from clue_api.arv2.calls import ProviderCaller

#: A board reference the brief pins as *not* existing. Zafran's real slug is ``zafran-security``;
#: ``zafran`` is exactly the plausible-looking guess the smoke test made eight of.
GUESSED_ZAFRAN_BOARD = AtsBoard("ashby", "zafran", "https://zafran.io/careers")


def _ledger_rows(path: Path, call_id: str) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [row for row in rows if row["call_id"] == call_id]


def _assert_free_and_audited(raw_ref: str | None, ledger_path: Path) -> dict[str, object]:
    """Both ledger rows exist, the fetch cost nothing, and the raw body is on disk (law 1).

    ``cost_source == "free"`` is asserted rather than the mere absence of a cost: an unlabelled
    zero is indistinguishable from a paid call whose provider went silent, and telling those two
    apart is the whole reason the label exists.
    """
    assert raw_ref is not None
    record = json.loads(Path(raw_ref).read_text(encoding="utf-8"))
    rows = _ledger_rows(ledger_path, str(record["call_id"]))
    assert [row["phase"] for row in rows] == ["estimate", "result"]
    assert Decimal(str(rows[1]["cost_usd"])) == Decimal(0)
    assert Decimal(str(rows[1]["estimate_usd"])) == Decimal(0)
    assert rows[1]["over_ceiling"] is False
    assert rows[1]["raw_ref"] == raw_ref
    assert rows[1]["extras"]["cost_source"] == "free"
    return record


def test_zafrans_ashby_slug_is_read_off_its_own_careers_page(
    make_caller: Callable[..., ProviderCaller],
) -> None:
    """The homepage names no board; ``/careers`` names ``zafran-security``. Nothing is guessed."""
    board = find_board("https://zafran.io", make_caller())

    assert board is not None, "zafran.io publishes an Ashby board; failing to read it is the bug"
    assert (board.kind, board.slug) == ("ashby", "zafran-security")
    assert "zafran.io" in board.source_url


def test_zafrans_board_serves_dated_listed_postings_for_nothing(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path
) -> None:
    """The cheapest account signal in the lane: open reqs, dated, for $0 and one raw record."""
    board = AtsBoard("ashby", "zafran-security", "https://www.zafran.io/careers")

    result = fetch_postings(board, make_caller())

    assert result.url == board_url(board)
    assert len(result.postings) >= 1
    dated = [p for p in result.postings if p.published_at is not None]
    assert dated, "Ashby publishes publishedAt on every posting"
    for posting in dated:
        assert posting.title
        assert posting.is_listed is not None, "Ashby is the one board that states isListed"
        assert posting.days_open is not None and posting.days_open >= 0
        assert posting.url and posting.url.startswith("https://jobs.ashbyhq.com/zafran-security/")
    assert any(p.description_plain for p in result.postings)

    # The uniform provision: the postings carry the cost of the request that produced them, and
    # that cost is the same row the ledger holds — not a second, softer opinion about it.
    assert result.cost.cost_source == "free"
    assert result.cost.cost_usd == Decimal(0)
    assert result.cost.provider == "ashby"
    assert result.cost.ledger_row_id == result.ledger_row_id
    assert result.cost.raw_ref == result.raw_ref

    _assert_free_and_audited(result.raw_ref, arv2_raw_root / "ledger.jsonl")


def test_probooks_slug_is_read_from_a_link_whose_text_alone_says_careers(
    make_caller: Callable[..., ProviderCaller],
) -> None:
    """probook.ai has no ``/careers`` route at all — its board hangs off ``/company``.

    This is the case that justifies following the homepage's own links: every conventional path
    404s, and the only route to the slug is an anchor whose *text* reads "Careers" while its href
    says ``/company#open-roles``.
    """
    board = find_board("https://probook.ai", make_caller())

    assert board is not None
    assert (board.kind, board.slug) == ("ashby", "probook")


def test_the_greenhouse_board_normalises_its_escaped_content_to_text(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path
) -> None:
    """Translucent on Greenhouse: departments, an office location, escaped ``content``."""
    board = AtsBoard("greenhouse", "translucent", "https://job-boards.greenhouse.io/translucent")

    result = fetch_postings(board, make_caller())

    assert len(result.postings) >= 1
    described = [p for p in result.postings if p.description_plain]
    assert described, "content=true was requested, so every posting should carry a description"
    for posting in described:
        assert "<p>" not in (posting.description_plain or ""), "HTML must be flattened to text"
        assert "&lt;" not in (posting.description_plain or ""), "entities must be resolved"
    assert any(p.published_at is not None for p in result.postings)
    assert any(p.department for p in result.postings)
    assert all(p.is_listed is None for p in result.postings), "Greenhouse states no listing flag"

    _assert_free_and_audited(result.raw_ref, arv2_raw_root / "ledger.jsonl")


def test_the_lever_board_normalises_its_bare_array_envelope(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path
) -> None:
    """Smarsh on Lever: no ``jobs`` key, ``text`` for the title, millisecond ``createdAt``."""
    board = AtsBoard("lever", "smarsh", "https://jobs.lever.co/smarsh")

    result = fetch_postings(board, make_caller())

    assert len(result.postings) >= 1
    for posting in result.postings:
        assert posting.title, "Lever's title lives under `text`, not `title`"
        assert posting.description_plain, "Lever serves descriptionPlain on every posting"
        assert posting.published_at is not None and posting.days_open is not None
        assert posting.url and posting.url.startswith("https://jobs.lever.co/smarsh/")
    assert any(p.department or p.team or p.location for p in result.postings)

    _assert_free_and_audited(result.raw_ref, arv2_raw_root / "ledger.jsonl")


def test_a_slug_nobody_published_is_a_typed_not_found_not_a_crash(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path
) -> None:
    """The smoke test's lesson, live: a guessed slug 404s, and the 404 is still fully audited.

    The raw record and both ledger rows exist for the miss as well as the hit — a negative that
    leaves no trace is a negative nobody can distinguish from a call that was never made.
    """
    caller = make_caller()

    with pytest.raises(BoardNotFound) as raised:
        fetch_postings(GUESSED_ZAFRAN_BOARD, caller)

    assert raised.value.slug == "zafran"
    assert raised.value.url == board_url(GUESSED_ZAFRAN_BOARD)

    rows = [
        json.loads(line)
        for line in (arv2_raw_root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    misses = [
        row
        for row in rows
        if row["provider"] == "ashby" and row["label"] == "zafran" and row["phase"] == "result"
    ]
    assert misses, "the refused fetch must still have written its result row"
    ledger = misses[-1]
    assert ledger["http_status"] == 404
    assert ledger["outcome"] == "client_error"
    assert Decimal(str(ledger["cost_usd"])) == Decimal(0)
    assert Path(str(ledger["raw_ref"])).exists()
