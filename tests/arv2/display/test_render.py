"""S4 exit gate: claim values render deterministically, aliases hide urls, near-duplicates fold."""

from __future__ import annotations

from datetime import UTC, datetime

from clue_api.arv2.display.render import (
    DisplayClaim,
    alias_table,
    dedupe_near_duplicates,
    render_value_text,
)


def test_media_wrapped_values_render_their_text() -> None:
    assert (
        render_value_text(
            "contact.facet.voice_quote",
            {
                "text": "It is a side hobby",
                "media_url": "https://x",
                "media_timestamp": "00:05",
            },
        )
        == "It is a side hobby"
    )


def test_objects_and_lists_render_deterministically_without_urls_leaking_as_keys() -> None:
    v = {"what": "Cisco acquisition rumor", "status": "REFUTED", "empty": None}
    assert render_value_text("account.reputation_risk", v) == (
        "status: REFUTED; what: Cisco acquisition rumor"
    )
    assert render_value_text("x", ["a", {"b": 1}]) == "a; b: 1"
    assert render_value_text("x", 42) == "42"
    assert len(render_value_text("x", "y" * 5000)) <= 1201


def _dc(
    i: str,
    value: str,
    *,
    safe: bool = True,
    quote: str | None = None,
    field: str = "contact.facet.hobby",
    ts: int = 0,
) -> DisplayClaim:
    return DisplayClaim(
        claim_id=i,
        field_key=field,
        value=value,
        quote=quote,
        observed_at=None,
        priority=2,
        outreach_safe=safe,
        subject=None,
        media_timestamp=None,
        use_class=None,
        source_url=None,
        entity_id="e",
        extraction_method="api",
        source_key=None,
        collected_at=datetime(2026, 9, 1, tzinfo=UTC).replace(second=ts),
    )


def test_near_duplicates_collapse_within_a_flag_group_but_not_across() -> None:
    a = _dc("a", "cocktail YouTuber (side hobby)")
    b = _dc(
        "b",
        "Cocktail YouTuber, a side hobby, creator of the Cocktail Chemistry channel",
        quote="long quote here",
        ts=1,
    )
    c = _dc(
        "c",
        "Hosts Cocktail Chemistry videos as a side hobby, runs Patreon for support",
        safe=False,
    )
    kept, dropped = dedupe_near_duplicates([a, b, c])
    assert {k.claim_id for k in kept} == {"b", "c"}
    assert dropped == {"a": "b"}


def test_alias_table_is_stable_and_never_carries_urls() -> None:
    rows, aliases = alias_table([_dc("z", "v1", ts=2), _dc("y", "v2", ts=1)])
    assert [r["id"] for r in rows] == ["c1", "c2"] and aliases == {"c1": "y", "c2": "z"}
    assert all("source_url" not in r and "sourceUrl" not in r for r in rows)
