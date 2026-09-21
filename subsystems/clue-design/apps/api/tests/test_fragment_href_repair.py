"""Exact href derivatives keep the captured payload and its styling intact."""

import copy
from types import SimpleNamespace

import pytest
from lumen_api.fragments.artifact import build_fragment_artifact
from lumen_api.fragments.href_repair import build_href_repair
from lumen_api.fragments.refs import FragmentRefused, fragment_wrapper_class
from lumen_api.fragments.slots import SlotSpec
from selectolax.lexbor import LexborHTMLParser


@pytest.fixture
def captured():
    return build_fragment_artifact(
        html=(
            '<section class="cards"><h2>Native cards</h2>'
            '<a class="cta" href="/demo">Bound CTA</a>'
            '<a href="/demo" data-example="/demo">First</a>'
            '<a href="/demo">Second</a><p>/demo stays copy</p>'
            '<img src="/asset-store/' + "a" * 64 + '"></section>'
        ),
        css=(
            ":root{--accent:red}.cards{animation:fade 1s;color:var(--accent)}"
            "@media(max-width:600px){.cards{padding:12px}}"
            "@keyframes fade{from{opacity:0}to{opacity:1}}"
            '.cards:after{content:"lumen-frag-unrelated";background:url(/asset-store/'
            + "b" * 64
            + ")}"
        ),
        slots=[SlotSpec(key="cta_href", kind="href", selector="a.cta")],
        rehosted={},
    )


def test_href_derivative_preserves_everything_except_vetted_links_and_namespace(captured):
    original = copy.deepcopy(captured.payload)
    repair = build_href_repair(original, {"/demo": "https://client.example/demo?a=1&b=2"})
    payload = repair.artifact.payload
    assert repair.match_counts == {"/demo": 3}
    assert payload["html"] == original["html"].replace(
        'href="/demo"', 'href="https://client.example/demo?a=1&amp;b=2"'
    )
    expected_manifest = copy.deepcopy(original["slot_manifest"])
    expected_manifest["cta_href"]["fallback"] = "https://client.example/demo?a=1&b=2"
    assert payload["slot_manifest"] == expected_manifest
    assert payload["asset_digests"] == original["asset_digests"]
    old = fragment_wrapper_class(captured.fragment_id)
    new = fragment_wrapper_class(repair.artifact.fragment_id)
    assert payload["css"].replace(new, old) == original["css"]
    assert old not in payload["css"]
    assert original == captured.payload
    assert repair.artifact.fragment_id != captured.fragment_id
    assert build_href_repair(original, {"/demo": "https://client.example/demo?a=1&b=2"}) == repair


def test_href_map_is_simultaneous_and_only_touches_anchor_href(captured):
    source = copy.deepcopy(captured.payload)
    source["html"] += '<a href="/next">Next</a><svg><use href="#icon"></use></svg>'
    repaired = build_href_repair(source, {"/demo": "/next", "/next": "/last"})
    links = LexborHTMLParser(repaired.artifact.payload["html"]).css("a")
    assert [node.attributes["href"] for node in links] == ["/next"] * 3 + ["/last"]
    assert 'href="#icon"' in repaired.artifact.payload["html"]
    assert 'data-example="/demo"' in repaired.artifact.payload["html"]


@pytest.mark.parametrize(
    "replacements",
    [
        {},
        [],
        {"/demo": "/demo"},
        {"/missing": "/fixed"},
        {"/demo": "javascript:alert(1)"},
        {"/demo": "java\tscript:alert(1)"},
        {"/demo": "data:text/html,test"},
        {"/demo": ""},
        {"/demo": None},
        {"/demo": "x" * 2049},
        {f"/{i}": f"/new/{i}" for i in range(9)},
    ],
)
def test_href_derivative_refuses_invalid_or_ineffective_maps_before_build(captured, replacements):
    original = copy.deepcopy(captured.payload)
    with pytest.raises(FragmentRefused):
        build_href_repair(original, replacements)
    assert original == captured.payload


def test_href_derivative_does_not_rewrite_css_strings_or_asset_urls(captured):
    source = copy.deepcopy(captured.payload)
    wrapper = fragment_wrapper_class(captured.fragment_id)
    source["css"] += f'.{wrapper}::before{{content:".{wrapper} fade--{wrapper}"}}'
    repaired = build_href_repair(source, {"/demo": "/fixed"})
    assert f'content:".{wrapper} fade--{wrapper}"' in repaired.artifact.payload["css"]
    assert source["asset_digests"] == repaired.artifact.payload["asset_digests"]


def test_href_derivative_rebases_nested_starting_style_and_scope(captured):
    source = copy.deepcopy(captured.payload)
    old = fragment_wrapper_class(captured.fragment_id)
    source["css"] += (
        f"@starting-style{{@scope (.{old}){{.{old} .cards{{animation:nested--{old} 1s}}"
        f"@keyframes nested--{old}{{from{{opacity:0}}to{{opacity:1}}}}}}}}"
    )
    repair = build_href_repair(source, {"/demo": "/fixed"})
    new = fragment_wrapper_class(repair.artifact.fragment_id)
    assert repair.artifact.payload["css"].replace(new, old) == source["css"]
    assert old not in repair.artifact.payload["css"]


@pytest.fixture
def custody(monkeypatch, tmp_path, captured):
    from lumen_api import agent_cloned_sections as capability
    from lumen_api.fragments import registry as store

    original = {
        "fragment_id": captured.fragment_id,
        "status": "approved",
        "section_role": "hero",
        "source_url": "https://client.example",
        "label": "Captured",
        "degraded": True,
        "degraded_reason": "dead_height",
        "provenance": {
            "snapshot_id": "snap_held",
            "dead_height_check": {"assessed": True, "degraded": True},
        },
    }
    persisted = []
    released = []
    rows = {}

    def read(_storage, *, workspace_id, fragment_id):
        assert workspace_id == "ws_held"
        if fragment_id != captured.fragment_id:
            raise FragmentRefused("fragment.unresolved", "not held")
        return store.LoadedFragment(original, captured.payload)

    def persist(_storage, **kwargs):
        persisted.append(kwargs)
        artifact = kwargs["artifact"]
        row = rows.setdefault(
            artifact.fragment_id,
            {
                "fragment_id": artifact.fragment_id,
                "status": "draft",
                "derived_from": kwargs["derived_from"],
                "derived_reason": kwargs["derived_reason"],
            },
        )
        return row, artifact

    def release(*, workspace_id, fragment_id, status):
        assert workspace_id == "ws_held"
        released.append(fragment_id)
        rows[fragment_id]["status"] = status
        return rows[fragment_id]

    monkeypatch.setattr(store, "read_web_fragment", read)
    monkeypatch.setattr(store, "_persist_fragment_artifact", persist)
    monkeypatch.setattr(store, "web_fragment_exists", lambda **kw: kw["fragment_id"] in rows)
    monkeypatch.setattr(capability, "set_web_fragment_status", release)
    registry = capability.DurableAgentClonedSectionRegistry(
        blobs=SimpleNamespace(storage=object(), workspace_id="ws_held"),
        cache_dir=tmp_path,
    )
    monkeypatch.setattr(
        registry,
        "_repository",
        lambda: SimpleNamespace(
            find_web_fragment=lambda fragment_id: (
                original if fragment_id == captured.fragment_id else None
            ),
        ),
    )
    return SimpleNamespace(
        registry=registry,
        original=original,
        persisted=persisted,
        released=released,
        rows=rows,
        capability=capability,
    )


def test_href_registry_preserves_capture_quality_and_reports_convergence(custody, captured):
    args = {
        "replaces": captured.fragment_id,
        "replacements": {"/demo": "/fixed"},
        "rung": 1,
        "note": "Restore navigation",
    }
    first = custody.registry.mint_href_repair(**args)
    assert first["status"] == "approved" and first["lineage_kept"] is True
    assert first["converged"] is False
    stored = custody.persisted[0]
    assert stored["workspace_id"] == "ws_held"
    assert stored["degraded"] is True and stored["degraded_reason"] == "dead_height"
    assert stored["provenance"]["snapshot_id"] == "snap_held"
    assert stored["provenance"]["dead_height_check"] == {"assessed": True, "degraded": True}
    assert stored["provenance"]["repair"]["source"] == "captured_href_repair"
    second = custody.registry.mint_href_repair(**{**args, "note": "A different explanation"})
    assert second["fragment_id"] == first["fragment_id"] and second["converged"] is True
    assert second["lineage_kept"] is False
    assert second["derived_reason"] == first["derived_reason"]
    assert second["requested_derived_reason"] != second["derived_reason"]
    assert len(custody.released) == 1


@pytest.mark.parametrize("mapping", [{"/absent": "/fixed"}, {"/demo": "javascript:x"}, {}])
def test_href_registry_validates_before_persisting_or_releasing(custody, captured, mapping):
    with pytest.raises(FragmentRefused):
        custody.registry.mint_href_repair(
            replaces=captured.fragment_id,
            replacements=mapping,
            rung=1,
            note="Restore navigation",
        )
    assert not custody.persisted and not custody.released


def test_href_registry_refuses_foreign_source_without_persistence(custody):
    with pytest.raises(FragmentRefused, match="workspace holds no such fragment"):
        custody.registry.mint_href_repair(
            replaces="frag_foreign",
            replacements={"/demo": "/fixed"},
            rung=1,
            note="Restore navigation",
        )
    assert not custody.persisted and not custody.released


def test_href_registry_reports_minted_fragment_when_release_is_unconfirmed(
    custody, captured, monkeypatch
):
    def fail_release(**kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(custody.capability, "set_web_fragment_status", fail_release)
    with pytest.raises(FragmentRefused) as caught:
        custody.registry.mint_href_repair(
            replaces=captured.fragment_id,
            replacements={"/demo": "/fixed"},
            rung=1,
            note="Restore navigation",
        )
    assert caught.value.code == "repair.release_unconfirmed"
    assert caught.value.reference in custody.rows
    assert len(custody.persisted) == 1 and not custody.released
