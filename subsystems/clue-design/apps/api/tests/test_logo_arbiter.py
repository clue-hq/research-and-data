"""One arbiter picks each cell from the candidates both sources propose.

Every fixture here carries REAL bytes, because the whole point of the arbiter is
that it measures ink instead of trusting a label. The first test pins what those
bytes measure as, so the rest can say "proven" and mean it.
"""

from __future__ import annotations

import io


def _svg(fill: str = "#101820", width: int = 240, height: int = 48) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect x="4" y="6" width="200" height="30" fill="{fill}"/></svg>'
    ).encode()


def _png(width: int, height: int, rgb: tuple) -> bytes:
    """Flat art on transparency, like a real logo file."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(
        [width // 8, height // 4, width * 7 // 8, height * 3 // 4], fill=rgb + (255,)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


DARK_INK = (58, 38, 26)  # freshcontext's brown: art for LIGHT surfaces
WHITE_INK = (250, 250, 250)  # art for DARK surfaces
ORANGE_INK = (240, 138, 44)  # mid-tone: measures `unknown`


def _vendor(cell: str, body: bytes, content_type: str, *, url: str,
            vendor_type: str = "logo", width=None, height=None):
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    return FamilyCell(
        cell=cell, body=body, content_type=content_type, source=SOURCE_BRANDFETCH,
        origin_url=url,
        evidence={"vendor": "brandfetch", "vendor_type": vendor_type,
                  "width": width, "height": height},
    )


def _ladder(cell: str, body: bytes, content_type: str, *, url: str,
            lockup: str = "wordmark", width=None, height=None):
    from lumen_ingestion.logo_family import SOURCE_LADDER, FamilyCell

    return FamilyCell(
        cell=cell, body=body, content_type=content_type, source=SOURCE_LADDER,
        origin_url=url,
        evidence={"ladder_slot": "light", "lockup": lockup,
                  "width": width, "height": height},
    )


# --------------------------------------------------------------------------- #
# fixture sanity: the bytes measure what the rest of this file assumes
# --------------------------------------------------------------------------- #


def test_the_fixture_bytes_measure_the_verdicts_the_other_tests_assume():
    from lumen_ingestion.logo_arbiter import measure_verdict

    assert measure_verdict(
        _ladder("dark_lockup", _svg("#ffffff"), "image/svg+xml", url="https://a/w.svg")
    ) == "dark_variant"
    assert measure_verdict(
        _ladder("light_lockup", _svg(), "image/svg+xml", url="https://a/d.svg")
    ) == "light_variant"
    assert measure_verdict(
        _vendor("dark_lockup", _png(310, 176, DARK_INK), "image/png", url="https://a/m.png")
    ) == "light_variant"
    assert measure_verdict(
        _ladder("dark_lockup", _png(400, 100, WHITE_INK), "image/png", url="https://a/w.png")
    ) == "dark_variant"
    assert measure_verdict(
        _ladder("light_mark", _png(180, 180, ORANGE_INK), "image/png", url="https://a/i.png")
    ) == "unknown"
    # No bytes, no measurement -- and no exception.
    assert measure_verdict(
        _ladder("light_lockup", b"", "image/png", url="https://a/none.png")
    ) == "unknown"


# --------------------------------------------------------------------------- #
# ink first
# --------------------------------------------------------------------------- #


def test_a_dark_cell_takes_the_ladders_white_svg_over_the_vendors_dark_png():
    """The freshcontext failure in miniature: the vendor's `theme` label said dark,
    its ink says light, and the site's real on-dark file was being thrown away."""
    from lumen_ingestion.logo_arbiter import choose_cells

    vendor = _vendor("dark_lockup", _png(310, 176, DARK_INK), "image/png",
                     url="https://cdn.brandfetch.io/fc/logo.png", width=310, height=176)
    ladder = _ladder("dark_lockup", _svg("#ffffff"), "image/svg+xml",
                     url="https://freshcontext.ai/images/wordmark-ondark.svg")

    cells, alternatives, notes = choose_cells({"dark_lockup": [vendor, ladder]})

    chosen = cells["dark_lockup"]
    assert chosen.source == "ladder"
    assert chosen.origin_url.endswith("wordmark-ondark.svg")
    assert chosen.evidence["measured_verdict"] == "dark_variant"
    assert chosen.evidence["arbitration"]["proven"] is True
    assert chosen.evidence["arbitration"]["beat"] == ["brandfetch:logo.png"]
    assert any("dark_lockup" in note and "brandfetch" in note for note in notes)

    # The beaten asset is real and stays available: the agent judges the fit.
    assert len(alternatives) == 1
    loser = alternatives[0]
    assert loser.source == "brandfetch"
    assert loser.cell == "dark_lockup"
    assert loser.evidence["competed_for"] == "dark_lockup"
    assert loser.evidence["lost_to"] == "ladder:wordmark-ondark.svg"
    assert loser.evidence["measured_verdict"] == "light_variant"
    assert loser.evidence["reason"] == (
        "ink measured light_variant, not proven for a dark surface"
    )


def test_an_unproven_candidate_wins_only_when_it_is_the_only_one():
    from lumen_ingestion.logo_arbiter import choose_cells

    vendor = _vendor("dark_lockup", _png(310, 176, DARK_INK), "image/png",
                     url="https://cdn.brandfetch.io/fc/logo.png", width=310, height=176)

    cells, alternatives, notes = choose_cells({"dark_lockup": [vendor]})

    assert alternatives == []  # one candidate beat nothing
    chosen = cells["dark_lockup"]
    assert chosen.source == "brandfetch"
    assert chosen.evidence["arbitration"]["proven"] is False
    assert chosen.evidence["measured_verdict"] == "light_variant"
    assert any("unverified" in note for note in notes)


# --------------------------------------------------------------------------- #
# then completeness, format, size, source
# --------------------------------------------------------------------------- #


def test_a_light_cell_takes_the_bigger_of_two_proven_wordmarks():
    """The second freshcontext failure: the header's short form beat the complete
    wordmark because the wordmark slot was only ever a fallback."""
    from lumen_ingestion.logo_arbiter import choose_cells

    short = _ladder("light_lockup", _png(310, 176, DARK_INK), "image/png",
                    url="https://freshcontext.ai/logo-mark.png", width=310, height=176)
    complete = _ladder("light_lockup", _png(1162, 571, DARK_INK), "image/png",
                       url="https://freshcontext.ai/wordmark.png", width=1162, height=571)

    cells, alternatives, _ = choose_cells({"light_lockup": [short, complete]})

    assert cells["light_lockup"].origin_url.endswith("wordmark.png")
    # The short form lost on size, not on ink, and the reason says which.
    assert [a.origin_url for a in alternatives] == [
        "https://freshcontext.ai/logo-mark.png"
    ]
    assert alternatives[0].evidence["reason"] == (
        "lost on completeness, format or size to wordmark.png"
    )
    assert alternatives[0].evidence["lost_to"] == "ladder:wordmark.png"


def test_an_svg_beats_a_larger_raster():
    from lumen_ingestion.logo_arbiter import choose_cells

    raster = _ladder("light_lockup", _png(1162, 571, DARK_INK), "image/png",
                     url="https://acme.com/wordmark.png", width=1162, height=571)
    vector = _ladder("light_lockup", _svg(), "image/svg+xml",
                     url="https://acme.com/wordmark.svg")

    cells, _, _ = choose_cells({"light_lockup": [raster, vector]})

    assert cells["light_lockup"].origin_url.endswith("wordmark.svg")


def test_the_vendor_wins_an_exact_tie():
    from lumen_ingestion.logo_arbiter import choose_cells

    vendor = _vendor("light_lockup", _svg(), "image/svg+xml",
                     url="https://cdn.brandfetch.io/acme/lockup.svg")
    ladder = _ladder("light_lockup", _svg(), "image/svg+xml",
                     url="https://acme.com/lockup.svg")

    cells, _, _ = choose_cells({"light_lockup": [ladder, vendor]})

    assert cells["light_lockup"].source == "brandfetch"


def test_a_proven_vendor_asset_wins_a_dark_cell_on_size_through_the_normal_key():
    """No special case for the vendor: make the ladder raster the bigger one and
    the same key hands the cell straight back."""
    from lumen_ingestion.logo_arbiter import choose_cells

    vendor = _vendor("dark_lockup", _png(400, 100, WHITE_INK), "image/png",
                     url="https://cdn.brandfetch.io/acme/white.png", width=400, height=100)
    smaller = _ladder("dark_lockup", _png(200, 50, WHITE_INK), "image/png",
                      url="https://acme.com/small-white.png", width=200, height=50)
    bigger = _ladder("dark_lockup", _png(900, 300, WHITE_INK), "image/png",
                     url="https://acme.com/big-white.png", width=900, height=300)

    cells, _, _ = choose_cells({"dark_lockup": [vendor, smaller]})
    assert cells["dark_lockup"].source == "brandfetch"

    cells, _, _ = choose_cells({"dark_lockup": [vendor, bigger]})
    assert cells["dark_lockup"].origin_url.endswith("big-white.png")


def test_empty_candidate_lists_yield_no_cell():
    from lumen_ingestion.logo_arbiter import choose_cells

    assert choose_cells({}) == ({}, [], [])
    assert choose_cells({"light_lockup": [], "dark_mark": []}) == ({}, [], [])
