#!/usr/bin/env python3
"""Increment 0a — exit-criterion e2e trace.

Runs the REAL /agent/turn-preview path (run_agent_turn_preview → provider
quality loop → real LLM via .env creds) with the working scene SEEDED from the
saved GTM poster doc, asking for one trivial targeted edit. Captures the full
response + trace dir so we can see exactly what a seeded turn does today,
BEFORE any continuation-mode work (that's 0b).

Usage:
    PYTHONPATH=apps/api:apps/agent_runtime <venv-python> .context/phase0a/e2e_0a.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO / "apps" / "agent_runtime"))

# The API process loads .env; this standalone runner must do the same.
for line in (REPO / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("LUMEN_CORE_HELPER", str(REPO / "target" / "debug" / "lumen-api-helper"))

from lumen_api.core import CoreClient  # noqa: E402
from lumen_api.main import run_agent_turn_preview  # noqa: E402
from lumen_api.models import AgentTurnPreviewRequest  # noqa: E402

sys.path.insert(0, str(REPO / ".context" / "phase0a"))
from probe_0a import build_saved_doc_scene  # noqa: E402


def main() -> int:
    core = CoreClient(repo_root=REPO)
    print("[e2e] building + saving the GTM poster scene…")
    scene = build_saved_doc_scene(core)
    print(f"[e2e] seed scene: {sorted(scene['nodes'].keys())}")

    payload = AgentTurnPreviewRequest(
        prompt=(
            "Change the headline text to 'Calmer clinics, faster triage'. "
            "Keep everything else exactly as it is."
        ),
        scene=scene,
        document_id="doc_probe_0a",
        active_page_id="hero_poster",
        selected_node_id="headline",
        max_iterations=3,
    )
    print(f"[e2e] running run_agent_turn_preview (model={os.environ.get('LUMEN_AGENT_MODEL')})…")
    result = run_agent_turn_preview(payload, REPO)

    summary = {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "stop_reason": result.get("stop_reason"),
        "summary": result.get("summary"),
        "trace_dir": result.get("trace_dir"),
        "operation_count": len(result.get("operations") or []),
        "operation_kinds": [op.get("kind") for op in (result.get("operations") or [])[:40]],
        "dsl_blocks": result.get("dsl_blocks"),
        "diagnostics": result.get("diagnostics"),
        "draft_scene_headline": (
            ((result.get("draft_scene") or {}).get("nodes") or {})
            .get("headline", {})
            .get("kind", {})
        ),
        "draft_scene_node_ids": sorted(((result.get("draft_scene") or {}).get("nodes") or {}).keys()),
        "draft_scene_page_ids": sorted(((result.get("draft_scene") or {}).get("pages") or {}).keys()),
    }
    out = Path(__file__).parent / "E2E-RESULT.json"
    full = Path(__file__).parent / "E2E-RESULT-FULL.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    slim = dict(result)
    slim.pop("draft_scene", None)
    full.write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2)[:3000])
    print(f"\n[e2e] summary -> {out}\n[e2e] full (sans scene) -> {full}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
