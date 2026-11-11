"""No footprint test reaches the real network to open a short link by accident."""

from __future__ import annotations

import pytest

from clue_api.footprint import short_links
from clue_spend.transport import ScriptedTransport


@pytest.fixture(autouse=True)
def _no_real_short_links(monkeypatch):
    monkeypatch.setattr(short_links, "TRANSPORT", lambda: ScriptedTransport([]))
