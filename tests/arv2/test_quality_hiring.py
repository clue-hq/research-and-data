from datetime import date

from clue_api.arv2.quality_hiring import current_hiring_state, hiring_context


def test_elapsed_closing_overrides_reachable_board_and_future_date_does_not_prove_open():
    today = date(2026, 9, 23)
    expired = hiring_context(
        {"validThrough": "2026-08-01T12:00:00+05:30"},
        observed=today,
        confirmed_board=True,
        listed=True,
    )
    assert expired["hiring_state"] == "historical"
    future = hiring_context(
        {"expiresAt": "2026-10-30"}, observed=today, confirmed_board=False, listed=None
    )
    assert future["hiring_state"] == "unknown"
    opened = hiring_context({}, observed=today, confirmed_board=True, listed=None)
    assert opened["hiring_state"] == "open"
    assert opened["observed_on"] == "2026-09-23"
    assert (
        hiring_context({"status": "closed"}, observed=today, confirmed_board=True, listed=True)[
            "hiring_state"
        ]
        == "closed"
    )
    assert (
        current_hiring_state({**opened, "closing_at": "2026-09-24"}, date(2026, 9, 25))
        == "historical"
    )
