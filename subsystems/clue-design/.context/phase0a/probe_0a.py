#!/usr/bin/env python3
"""Increment 0a — empirical probes for seeding the agent from a live scene.

Builds a REAL saved document (the image-baseline GTM/hero poster, saved through
the actual POST /documents flow into a scratch sqlite DB), then measures:

  Probe 1  seeded turn doing a trivial `#id` modify — does it compile & apply?
           (+ the LUMD0901 missing-target variant)
  Probe 2  a turn that re-authors an existing NodeId — does LUMD0401 reject the
           whole block, and does anything partial leak into the scene?
  Probe 3  human delete + recreate through the document ops/undo API — do
           NodeIds stay stable/predictable? Is id reuse after delete allowed?

Everything runs against the REAL Rust core helper (target/debug/lumen-api-helper)
and the REAL FastAPI app (TestClient) — no fakes. Results are written to
.context/phase0a/PROBE-RESULTS.json (raw) for the write-up.

Usage:
    LUMEN_CORE_HELPER=$PWD/target/debug/lumen-api-helper \
    PYTHONPATH=apps/api:apps/agent_runtime \
    <venv-python> .context/phase0a/probe_0a.py
"""

from __future__ import annotations

import base64
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO / "apps" / "agent_runtime"))

os.environ.setdefault("LUMEN_CORE_HELPER", str(REPO / "target" / "debug" / "lumen-api-helper"))

RESULTS: dict = {"probes": {}}
FIXTURE = REPO / "apps" / "api" / "tests" / "fixtures" / "image_baseline"
DESIGN_LUMEN = (FIXTURE / "design.lumen").read_text(encoding="utf-8")

SCRATCH = Path(tempfile.mkdtemp(prefix="lumen-probe0a-"))
os.environ["LUMEN_API_DATABASE_PATH"] = str(SCRATCH / "probe.sqlite3")
os.environ["LUMEN_AGENT_TRACE_DIR"] = str(SCRATCH / "runs")
ASSET_STORE = SCRATCH / "asset-store"
ASSET_STORE.mkdir(parents=True, exist_ok=True)

from lumen_api.core import CoreClient  # noqa: E402
from lumen_deepagent.config import AgentRuntimeConfig  # noqa: E402
from lumen_deepagent.tools import LumenDesignTools  # noqa: E402


def build_saved_doc_scene(core: CoreClient) -> dict:
    """Reproduce the live flow that produced the GTM poster: ingest the hero
    image asset, upsert it, compile the poster DSL, preflight for geometry."""
    scene = core.new_scene("doc_probe_0a", "GTM hero poster (probe 0a)")
    png = (FIXTURE / "reference_source.png").read_bytes()
    ingest = core.ingest_asset(
        store_root=str(ASSET_STORE),
        bytes_base64=base64.b64encode(png).decode("ascii"),
        asset_id="hero_image",
        label="Hero image",
        declared_mime_type="image/png",
        kind="raster_image",
        license={"name": "generated", "allows_commercial_use": True},
        provenance={"created_by": "probe_0a", "method": "fixture"},
        source={"kind": "generated", "request_id": "probe-0a", "model": "fixture"},
        raise_on_error=False,
    )
    record = (ingest.get("asset") or {}).get("record") or {}
    assert record, f"asset ingest failed: {ingest}"
    compile_resp = core.compile_dsl_into_scene(scene, DESIGN_LUMEN)
    out = compile_resp.get("dsl", {}).get("compile_output", {})
    assert not out.get("halted_at"), f"baseline DSL halted: {out.get('halted_at')}"
    scene = compile_resp["scene"]
    resp = core.apply_operations(scene, [{"kind": "upsert_asset", "asset": record}])
    scene = resp["scene"]
    kit = core.platform_default_brand_kit()
    pre = core.preflight_scene(scene, kit)
    scene = pre.get("scene", scene)
    return scene


def save_document(scene: dict) -> tuple[dict, object]:
    """Save the scene as a REAL document through POST /documents (TestClient)."""
    from fastapi.testclient import TestClient
    from lumen_api.main import create_app

    client = TestClient(create_app())
    created = client.post("/documents", json={"title": "GTM hero poster", "scene": scene})
    assert created.status_code == 200, created.text
    doc = created.json()
    doc_id = doc["document"]["id"] if "document" in doc else doc["id"]
    fetched = client.get(f"/documents/{doc_id}")
    assert fetched.status_code == 200, fetched.text
    return fetched.json(), client


def seeded_tools(seed_scene: dict, prompt: str) -> LumenDesignTools:
    config = AgentRuntimeConfig.from_env(REPO)
    return LumenDesignTools(config, prompt, initial_scene=copy.deepcopy(seed_scene))


def node_fingerprints(scene: dict) -> dict:
    return {
        nid: json.dumps(node, sort_keys=True)
        for nid, node in (scene.get("nodes") or {}).items()
    }


def probe_1(seed_scene: dict) -> dict:
    """Trivial `modify #id` on a seeded scene."""
    result: dict = {}
    tools = seeded_tools(seed_scene, "Change the headline copy")
    before = node_fingerprints(tools.scene)

    modify = '#headline text("Calmer clinics, faster triage") s(936,180)'
    payload = json.loads(tools.compile_dsl_block(modify))
    summary = payload.get("compile", {})
    result["modify_status"] = summary.get("status")
    result["applied_operations"] = summary.get("applied_operations")
    result["operation_count"] = summary.get("operation_count")
    result["halted_at"] = summary.get("halted_at")
    result["diagnostics"] = summary.get("diagnostics")

    after = node_fingerprints(tools.scene)
    headline = tools.scene.get("nodes", {}).get("headline", {})
    result["headline_content_after"] = (headline.get("kind") or {}).get("content")
    result["headline_changed"] = before.get("headline") != after.get("headline")
    result["untouched_nodes_identical"] = sorted(
        nid for nid in before if nid != "headline" and before[nid] != after.get(nid)
    )
    result["node_count_before_after"] = [len(before), len(after)]

    # LUMD0901 variant: modify a MISSING id — what exactly does it return?
    tools2 = seeded_tools(seed_scene, "Modify a node that does not exist")
    missing = json.loads(tools2.compile_dsl_block("#no_such_node s(100,100)"))
    ms = missing.get("compile", {})
    result["missing_target"] = {
        "status": ms.get("status"),
        "halted_at": ms.get("halted_at"),
        "first_diag": (ms.get("diagnostics") or [{}])[0],
    }
    return result


def probe_2(seed_scene: dict) -> dict:
    """Re-author an existing NodeId — expect LUMD0401 whole-block rejection."""
    result: dict = {}

    # 2a: pure re-author (new page + existing id as a fresh element).
    tools = seeded_tools(seed_scene, "Re-author the headline")
    before = node_fingerprints(tools.scene)
    pages_before = sorted((tools.scene.get("pages") or {}).keys())
    reauthor = (
        "page second_page size(1080,1350,px)\n"
        '  headline text "Re-authored headline" s(936,210)\n'
    )
    payload = json.loads(tools.compile_dsl_block(reauthor))
    summary = payload.get("compile", {})
    after = node_fingerprints(tools.scene)
    pages_after = sorted((tools.scene.get("pages") or {}).keys())
    result["reauthor"] = {
        "status": summary.get("status"),
        "halted_at": summary.get("halted_at"),
        "applied_operations": summary.get("applied_operations"),
        "operation_count": summary.get("operation_count"),
        "first_diag": (summary.get("diagnostics") or [{}])[0],
        "scene_changed_nodes": sorted(
            nid for nid in set(before) | set(after) if before.get(nid) != after.get(nid)
        ),
        "pages_before": pages_before,
        "pages_after": pages_after,
    }

    # 2b: PARTIAL leak check — a valid modify line BEFORE the re-author line.
    # Does the pre-halt edit land, or is the whole block atomic?
    tools2 = seeded_tools(seed_scene, "Mixed valid + re-author block")
    before2 = node_fingerprints(tools2.scene)
    mixed = (
        '#kicker text("UPDATED KICKER")\n'
        'headline text "Re-authored headline" s(936,210)\n'
    )
    payload2 = json.loads(tools2.compile_dsl_block(mixed))
    summary2 = payload2.get("compile", {})
    after2 = node_fingerprints(tools2.scene)
    result["mixed_block"] = {
        "status": summary2.get("status"),
        "halted_at": summary2.get("halted_at"),
        "applied_operations": summary2.get("applied_operations"),
        "first_diag": (summary2.get("diagnostics") or [{}])[0],
        "kicker_changed": before2.get("kicker") != after2.get("kicker"),
        "kicker_content_after": (
            (tools2.scene.get("nodes", {}).get("kicker", {}).get("kind") or {}).get("content")
        ),
        "scene_changed_nodes": sorted(
            nid
            for nid in set(before2) | set(after2)
            if before2.get(nid) != after2.get(nid)
        ),
    }
    return result


def probe_3(doc: dict, client) -> dict:
    """Delete + recreate through the real document ops/undo API."""
    result: dict = {}
    doc_id = doc.get("id") or (doc.get("document") or {}).get("id")
    scene = doc.get("scene") or (doc.get("document") or {}).get("scene")
    headline = copy.deepcopy(scene["nodes"]["headline"])
    parent_id = next(
        nid for nid, node in scene["nodes"].items() if "headline" in (node.get("children") or [])
    )
    index = scene["nodes"][parent_id]["children"].index("headline")

    def get_scene() -> dict:
        got = client.get(f"/documents/{doc_id}")
        assert got.status_code == 200, got.text
        body = got.json()
        return body.get("scene") or (body.get("document") or {}).get("scene")

    # 3a: delete via the editor's op, then UNDO — same id back?
    deleted = client.post(
        f"/documents/{doc_id}/operations",
        json={
            "operations": [{"kind": "remove_node", "node_id": "headline"}],
            "actor": {"kind": "human"},
            "intent": "probe: human deletes headline",
        },
    )
    result["delete_status_code"] = deleted.status_code
    if deleted.status_code != 200:
        result["delete_error"] = deleted.text[:500]
        return result
    scene_after_delete = get_scene()
    result["headline_gone_after_delete"] = "headline" not in scene_after_delete["nodes"]

    undone = client.post(f"/documents/{doc_id}/undo")
    result["undo_status_code"] = undone.status_code
    if undone.status_code == 200:
        scene_after_undo = get_scene()
        restored = scene_after_undo["nodes"].get("headline")
        result["undo_restores_same_id"] = restored is not None
        result["undo_restored_node_identical"] = (
            json.dumps(restored, sort_keys=True) == json.dumps(headline, sort_keys=True)
            if restored
            else False
        )
        result["undo_parent_children"] = scene_after_undo["nodes"][parent_id]["children"]
    else:
        result["undo_error"] = undone.text[:500]

    # 3b: delete, then RECREATE with the SAME id via insert_node — allowed?
    deleted2 = client.post(
        f"/documents/{doc_id}/operations",
        json={
            "operations": [{"kind": "remove_node", "node_id": "headline"}],
            "actor": {"kind": "human"},
            "intent": "probe: delete before same-id recreate",
        },
    )
    assert deleted2.status_code == 200, deleted2.text
    recreate_node = copy.deepcopy(headline)
    recreate_node["computed"] = None
    recreated = client.post(
        f"/documents/{doc_id}/operations",
        json={
            "operations": [
                {
                    "kind": "insert_node",
                    "parent": {"kind": "node", "id": parent_id},
                    "index": index,
                    "node": recreate_node,
                }
            ],
            "actor": {"kind": "human"},
            "intent": "probe: recreate headline with the same id",
        },
    )
    result["same_id_recreate_status_code"] = recreated.status_code
    if recreated.status_code == 200:
        scene_after_recreate = get_scene()
        result["same_id_recreate_present"] = "headline" in scene_after_recreate["nodes"]
        result["same_id_recreate_children"] = scene_after_recreate["nodes"][parent_id]["children"]
    else:
        result["same_id_recreate_error"] = recreated.text[:800]

    return result


def main() -> int:
    core = CoreClient(repo_root=REPO)
    print("[setup] building the GTM poster scene through the real pipeline…")
    scene = build_saved_doc_scene(core)
    print(f"[setup] scene built: {len(scene['nodes'])} nodes, {len(scene['pages'])} pages")
    doc, client = save_document(scene)
    doc_id = doc.get("id") or (doc.get("document") or {}).get("id")
    saved_scene = doc.get("scene") or (doc.get("document") or {}).get("scene")
    assert saved_scene, f"unexpected document payload keys: {list(doc.keys())}"
    print(f"[setup] saved document {doc_id} via POST /documents")
    RESULTS["setup"] = {
        "document_id": doc_id,
        "node_ids": sorted(saved_scene["nodes"].keys()),
        "page_ids": sorted(saved_scene["pages"].keys()),
        "scratch": str(SCRATCH),
    }

    print("[probe 1] seeded trivial modify #headline …")
    RESULTS["probes"]["probe_1_seeded_modify"] = probe_1(saved_scene)
    print(json.dumps(RESULTS["probes"]["probe_1_seeded_modify"], indent=2)[:1200])

    print("[probe 2] seeded re-author of an existing id …")
    RESULTS["probes"]["probe_2_reauthor_id"] = probe_2(saved_scene)
    print(json.dumps(RESULTS["probes"]["probe_2_reauthor_id"], indent=2)[:1600])

    print("[probe 3] human delete + recreate through the document API …")
    RESULTS["probes"]["probe_3_id_stability"] = probe_3(doc, client)
    print(json.dumps(RESULTS["probes"]["probe_3_id_stability"], indent=2)[:1200])

    out = Path(__file__).parent / "PROBE-RESULTS.json"
    out.write_text(json.dumps(RESULTS, indent=2) + "\n", encoding="utf-8")
    print(f"\n[done] raw results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
