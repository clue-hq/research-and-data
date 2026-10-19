"""Tables for the phase-2 findings, read from the run records (agent-runs/<label>/run.json).

Usage (from the repo root): .venv/bin/python trials/puck-spike/agent/report_tables.py [labels…]
Prints markdown tables; every number in AGENT-FINDINGS.md comes from here, not from memory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "agent-runs"


def turn_row(label: str, number: int, turn: dict) -> dict:
    calls = turn["calls"]
    misses = [
        c
        for c in calls
        if c["input_tokens"] > 15_000 and c["cached_tokens"] < 0.5 * c["input_tokens"]
    ]
    return {
        "run": label,
        "turn": number,
        "status": turn["status"],
        "calls": turn["model_calls"],
        "cost": turn["cost_usd"],
        "seconds": turn["seconds"],
        "renders": turn["render_rounds"],
        "invalid": turn["validations"]["invalid"],
        "max_in": max((c["input_tokens"] for c in calls), default=0),
        "miss_cost": round(sum(c["cost_cents"] for c in misses) / 100, 3),
        "prompt": turn["prompt"][:70],
    }


def main(labels: list[str]) -> None:
    labels = labels or sorted(p.parent.name for p in RUNS.glob("*/run.json"))
    rows = []
    for label in labels:
        record = json.loads((RUNS / label / "run.json").read_text())
        rows += [turn_row(label, n, t) for n, t in enumerate(record["turns"], 1)]
    print(
        "| run | turn | request | status | calls | cost | time | renders | invalid | largest request | cache-miss cost |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['run']} | {r['turn']} | {r['prompt']} | {r['status']} | {r['calls']} | ${r['cost']:.2f} | "
            f"{r['seconds'] / 60:.1f} min | {r['renders']} | {r['invalid']} | {r['max_in']:,} | ${r['miss_cost']:.2f} |"
        )
    total_calls = sum(r["calls"] for r in rows)
    print(
        f"\nTotals: {len(rows)} turns, {total_calls} model calls, ${sum(r['cost'] for r in rows):.2f}, "
        f"{sum(r['invalid'] for r in rows)} validation errors, "
        f"{sum(r['seconds'] for r in rows) / 60:.0f} minutes."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
