"""The rendered-capture backend dispatcher (stealth default, loud fallback).

Capture PoC findings (2026-08-30) these pin: plain automation Chromium is
refused the goods on bot-walled and WebGL-hero sites, so the stealth backend
leads; but a missing/broken stealth lane must degrade to plain Chromium with a
WARNING on the snapshot — never silently — and a stealth capture must say it
was one (info), so the kit's diagnostics always name the capture provenance.
"""

from __future__ import annotations

import asyncio

import pytest

import lumen_ingestion.capture.rendered as rendered
from lumen_ingestion.capture.snapshot import SiteSnapshot


def _snapshot() -> SiteSnapshot:
    return SiteSnapshot(
        requested_url="https://example.com",
        final_url="https://example.com",
        fetched_at="2026-08-30T00:00:00+00:00",
        tier="rendered",
        html="<html></html>",
    )


def _noop(stage: str, progress: float) -> None:
    return None


@pytest.fixture
def calls(monkeypatch):
    seen: dict[str, int] = {"stealth": 0, "chromium": 0}

    async def fake_stealth(url, fetcher, reporter, *, fetched_at, measure_states=False):
        seen["stealth"] += 1
        return _snapshot()

    async def fake_chromium(url, fetcher, reporter, *, fetched_at, measure_states=False):
        seen["chromium"] += 1
        return _snapshot()

    monkeypatch.setattr(rendered, "_fetch_rendered_stealth", fake_stealth)
    monkeypatch.setattr(rendered, "_fetch_rendered_chromium", fake_chromium)
    return seen


def test_stealth_is_the_default_and_stamps_its_provenance(calls, monkeypatch) -> None:
    monkeypatch.delenv("LUMEN_RENDER_STEALTH", raising=False)
    snap = asyncio.run(rendered.fetch_rendered("https://example.com", None, _noop, fetched_at="t"))
    assert calls == {"stealth": 1, "chromium": 0}
    assert any(d["code"] == "LUMI0535" for d in snap.diagnostics)


def test_stealth_failure_falls_back_to_chromium_with_a_warning(calls, monkeypatch) -> None:
    monkeypatch.delenv("LUMEN_RENDER_STEALTH", raising=False)

    async def broken_stealth(url, fetcher, reporter, *, fetched_at, measure_states=False):
        calls["stealth"] += 1
        raise RuntimeError("no stealth browser on this host")

    monkeypatch.setattr(rendered, "_fetch_rendered_stealth", broken_stealth)
    snap = asyncio.run(rendered.fetch_rendered("https://example.com", None, _noop, fetched_at="t"))
    assert calls == {"stealth": 1, "chromium": 1}
    warning = next(d for d in snap.diagnostics if d["code"] == "LUMI0536")
    assert warning["severity"] == "warning"
    assert "fell back to plain Chromium" in warning["message"]


def test_kill_switch_disables_the_stealth_lane_silently(calls, monkeypatch) -> None:
    monkeypatch.setenv("LUMEN_RENDER_STEALTH", "0")
    snap = asyncio.run(rendered.fetch_rendered("https://example.com", None, _noop, fetched_at="t"))
    assert calls == {"stealth": 0, "chromium": 1}
    # Disabled-by-operator is a choice, not a failure: no fallback warning.
    assert not any(d["code"] in ("LUMI0535", "LUMI0536") for d in snap.diagnostics)
