"""Contract 4 (Lane B Task 16): the section-link secret is a documented, optional secret."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets

REPO = Path(__file__).resolve().parents[1]


def test_the_section_link_secret_is_an_optional_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_SITE_SECTION_LINK_SECRET", raising=False)
    assert "site_section_link_secret" in Secrets.model_fields
    assert Secrets(_env_file=None).site_section_link_secret is None  # type: ignore[call-arg]


def test_both_env_examples_document_it_as_a_placeholder() -> None:
    for example in (REPO / ".env.example", REPO / "subsystems" / "clue-design" / ".env.example"):
        assert re.search(
            r"^CLUE_SITE_SECTION_LINK_SECRET=$", example.read_text(encoding="utf-8"), re.MULTILINE
        ), example
