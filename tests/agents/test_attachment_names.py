"""One rule for an attached file's name on disk (review M-11, 2026-10-30).

The platform read and the design agents' folder writer both reduce a person's filename to one safe
path segment; the rule lives once, in clue_agents, which both may import.
"""

from __future__ import annotations

from clue_agents.attachment_names import safe_attachment_name


def test_a_name_is_one_segment_that_never_climbs() -> None:
    assert safe_attachment_name("../x.png") == "x.png"
    assert safe_attachment_name("..\\win.png") == "win.png"
    assert safe_attachment_name("a/b/.hidden.md") == "hidden.md"
    assert safe_attachment_name("ünï code.md") == "ünï code.md"
    assert safe_attachment_name("..") == "attachment"
    assert safe_attachment_name("") == "attachment"


def test_a_name_fits_the_disk_and_keeps_its_extension() -> None:
    name = safe_attachment_name("報" * 120 + ".pdf")
    assert len(name.encode("utf-8")) <= 240 and name.endswith(".pdf")
