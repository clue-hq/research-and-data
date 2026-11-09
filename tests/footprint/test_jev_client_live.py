"""Live: Jev on a long transcript. Spends real money (about $0.003); run by name only.

Set ``JEV_LIVE_CASE`` to a JSON file ``{"person": {...}, "recording": {...}, "deepgram": path,
"repeat": n, "expect_label": "Speaker N"}``; the Deepgram utterances are repeated ``n`` times to
reach the length under test. Skipped without the case file or an OpenRouter key.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clue_api.footprint.jev_client import check_speaker
from clue_config.secrets import Secrets
from clue_config.settings import Settings
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpxTransport


def _lines(deepgram: Path, repeat: int) -> list[str]:
    raw = json.loads(deepgram.read_text())
    results = raw.get("results") or raw["result"]["results"]
    lines, offset = [], 0.0
    span = max(u["end"] for u in results["utterances"])
    for _ in range(repeat):
        for u in results["utterances"]:
            start = int(u["start"] + offset)
            lines.append(
                f"[{start // 60:02d}:{start % 60:02d}] Speaker {u['speaker']}: {u['transcript']}"
            )
        offset += span
    return lines


@pytest.mark.skipif(not os.environ.get("JEV_LIVE_CASE"), reason="JEV_LIVE_CASE not set")
def test_long_transcript_live():
    case = json.loads(Path(os.environ["JEV_LIVE_CASE"]).read_text())
    key = Secrets().openrouter_api_key
    if key is None:
        pytest.skip("no OpenRouter key")
    settings = Settings()
    lines = _lines(Path(case["deepgram"]), int(case.get("repeat", 1)))
    caller = ProviderCaller(
        transport=HttpxTransport(),
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        now=lambda: datetime.now(UTC),
        sleep=time.sleep,
    )
    started = time.monotonic()
    check = check_speaker(
        caller,
        key,
        settings.arv2_speaker_check_model,
        person=case["person"],
        recording=case["recording"],
        lines=lines,
        max_chars=int(os.environ.get("JEV_LIVE_MAX_CHARS", settings.arv2_speaker_check_max_chars)),
    )
    chars = sum(len(line) + 1 for line in lines)
    print(
        f"chars={chars} windows={check.windows} state={check.state} label={check.label} "
        f"p={check.label_probabilities} cost={check.cost_usd} secs={time.monotonic() - started:.1f} "
        f"reason={check.reason}"
    )
    assert check.state == "answered"
    assert check.label == case["expect_label"]
