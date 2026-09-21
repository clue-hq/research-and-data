"""Read capability stays workspace scoped; recovery order follows the source."""

from types import SimpleNamespace

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry


def test_recovered_siblings_sort_at_parent_position_not_mint_time():
    rows = [
        {"fragment_id": "footer", "provenance": {"page_url": "x", "section_index": 2}},
        {
            "fragment_id": "hero",
            "provenance": {
                "page_url": "x",
                "section_index": 3,
                "dom_path": [1, 0, 0],
                "recovery": {
                    "mode": "authored-descendant-after-refusal",
                    "parent_section_index": 0,
                    "parent_dom_path": [1, 0],
                },
            },
        },
    ]
    assert [
        r["fragment_id"]
        for r in sorted(rows, key=DurableAgentClonedSectionRegistry._document_order)
    ] == ["hero", "footer"]


def test_registry_offers_read_only_source_flow_capability(tmp_path):
    registry = DurableAgentClonedSectionRegistry(
        blobs=SimpleNamespace(workspace_id="ws_isolated"), cache_dir=tmp_path
    )
    assert callable(getattr(registry, "prepare_source_flows", None)), (
        "snapshot-backed assembly read capability is missing"
    )


def registry_for(monkeypatch, tmp_path, rows, load):
    from lumen_api import agent_cloned_sections as module

    calls = []
    repo = SimpleNamespace(
        find_web_fragment=lambda fid: next(r for r in rows if r["fragment_id"] == fid),
        validate_fragment_reference_changes=lambda **kw: calls.append(kw),
    )
    registry = DurableAgentClonedSectionRegistry(
        blobs=SimpleNamespace(workspace_id="ws_isolated", storage=object()), cache_dir=tmp_path
    )
    monkeypatch.setattr(registry, "_repository", lambda: repo)
    monkeypatch.setattr(module, "read_site_snapshot", load, raising=False)
    return registry, calls


def test_snapshot_loaded_once_scoped_and_groups_have_no_release_side_effect(monkeypatch, tmp_path):
    from test_source_flow import members, snapshot

    rows = members()
    reads = []

    def load(storage, **kw):
        reads.append(kw)
        return snapshot(".outer{display:flow-root}.inner{padding-top:13px}")

    registry, gates = registry_for(monkeypatch, tmp_path, rows, load)
    result = registry.prepare_source_flows([r["fragment_id"] for r in rows])
    assert reads == [{"workspace_id": "ws_isolated", "snapshot_id": "snapshot_held"}]
    assert len(gates) == 2 and len(result["groups"]) == 1 and result["gaps"] == []
    assert all("status" not in r for r in rows)


def test_missing_snapshot_is_an_explicit_gap(monkeypatch, tmp_path):
    from test_source_flow import members

    rows = members()

    def load(*args, **kw):
        raise FileNotFoundError("frozen bytes absent")

    registry, _ = registry_for(monkeypatch, tmp_path, rows, load)
    result = registry.prepare_source_flows([r["fragment_id"] for r in rows])
    assert result["groups"] == []
    assert result["gaps"][0]["code"] == "source_flow.snapshot_unavailable"
    assert result["gaps"][0]["member_ids"] == [r["fragment_id"] for r in rows]


def test_repaired_member_refuses_the_entire_incompatible_group(monkeypatch, tmp_path):
    from test_source_flow import members, snapshot

    rows = members()
    repair = {
        "fragment_id": "frag_repair",
        "derived_from": rows[0]["fragment_id"],
        "provenance": {},
    }
    registry, _ = registry_for(monkeypatch, tmp_path, [*rows, repair], lambda *a, **kw: snapshot())
    result = registry.prepare_source_flows([repair["fragment_id"], rows[1]["fragment_id"]])
    assert result["groups"] == [] and result["gaps"][0]["code"] == "source_flow.incompatible_repair"
