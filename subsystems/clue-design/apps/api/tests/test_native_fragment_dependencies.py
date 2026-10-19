"""Native dependency custody/compatibility, without a database or providers."""
import copy
import json

import pytest

from lumen_api.fragments.artifact import build_fragment_artifact, parse_fragment_payload
from lumen_api.fragments.refs import FragmentRefused
from lumen_api.fragments.native import native_dependencies_for_subtree
from lumen_api.fragments.render import fragment_render_map, fragment_package_schema_refusal

HTML = ('<div id="lumen-tabs-t" class="lumen-tabs" data-lumen-tabs="true">'
        '<div role="tablist" class="lumen-tabs-list">'
        '<button id="a_tab" role="tab" aria-controls="a_panel">A</button></div>'
        '<div id="a_panel" role="tabpanel" aria-labelledby="a_tab">Panel</div></div>')
DEPENDENCIES = {"version": 1, "platform_runtime": 2, "tabs": [
    {"root_id": "lumen-tabs-t", "items": [{"tab_id": "a_tab", "panel_id": "a_panel"}]}
]}


def test_capture_cannot_opt_into_native_behavior_via_markup():
    artifact = build_fragment_artifact(html=HTML, css="", rehosted={})
    assert artifact.payload["schema_version"] == 1
    assert "native_dependencies" not in artifact.payload
    assert "data-lumen-tabs" not in artifact.payload["html"]
    assert parse_fragment_payload(artifact.payload_bytes) == artifact.payload


def test_native_descriptor_is_hashed_and_reaches_the_render_map():
    captured = build_fragment_artifact(html=HTML, css="", rehosted={})
    native = build_fragment_artifact(html=HTML, css="", rehosted={},
                                     native_dependencies=DEPENDENCIES)
    assert native.fragment_id != captured.fragment_id
    assert native.payload["schema_version"] == 2
    assert parse_fragment_payload(native.payload_bytes) == native.payload
    package = {"schema_version": 2, "fragments": {native.fragment_id: native.payload}}
    assert fragment_package_schema_refusal(package) is None
    assert fragment_render_map(package, [native.fragment_id])[native.fragment_id][
        "native_dependencies"] == DEPENDENCIES
    corrupt = copy.deepcopy(native.payload)
    corrupt["schema_version"] = 1
    with pytest.raises(FragmentRefused):
        parse_fragment_payload(json.dumps(corrupt).encode())


@pytest.mark.parametrize("html", [
    HTML + '<span id="a_tab"></span>',
    HTML.replace('aria-controls="a_panel"', 'aria-controls="outside"'),
    HTML.replace('id="a_panel"', 'id="missing"'),
    HTML.replace('</button>', '</button><button role="tab">Foreign</button>'),
])
def test_broken_or_ambiguous_owned_targets_refuse(html):
    with pytest.raises(FragmentRefused):
        build_fragment_artifact(html=html, css="", rehosted={},
                                native_dependencies=DEPENDENCIES)


def test_unknown_native_version_refuses_at_mint_and_read():
    bad = {**DEPENDENCIES, "platform_runtime": 999}
    with pytest.raises(FragmentRefused):
        build_fragment_artifact(html=HTML, css="", rehosted={}, native_dependencies=bad)
    payload = build_fragment_artifact(html=HTML, css="", rehosted={}).payload
    payload.update(schema_version=2, native_dependencies=bad)
    with pytest.raises(FragmentRefused):
        parse_fragment_payload(json.dumps(payload).encode())


def test_descriptor_is_derived_only_from_checked_subtree():
    doc = {"pages": [{"id": "home", "nodes": {
        "root": {"kind": "section", "children": ["t"]},
        "t": {"kind": "component", "component": "tabs", "children": ["a"]},
        "a": {"kind": "container", "children": ["label", "body"]},
        "label": {"kind": "text"}, "body": {"kind": "text"},
        "orphan": {"kind": "component", "component": "dialog"},
    }}]}
    assert native_dependencies_for_subtree(doc, "home", "root") == DEPENDENCIES
    doc["pages"][0]["nodes"]["t"]["component"] = "nav_menu"
    with pytest.raises(FragmentRefused):
        native_dependencies_for_subtree(doc, "home", "root")


def test_href_variant_retains_native_dependencies_and_original_bytes():
    from lumen_api.fragments.href_repair import build_href_repair

    source = build_fragment_artifact(
        html=HTML + '<a href="https://example.test/old">Next</a>',
        css="", rehosted={}, native_dependencies=DEPENDENCIES,
    )
    before = source.payload_bytes
    derived = build_href_repair(source.payload, {"https://example.test/old": "https://example.test/new"})
    assert parse_fragment_payload(derived.artifact.payload_bytes)["native_dependencies"] == DEPENDENCIES
    assert source.payload_bytes == before


def test_mixed_document_package_never_downgrades_native_page(monkeypatch):
    from lumen_api.fragments import render

    pages = {"native": {"schema_version": 2, "fragments": {}, "missing": []},
             "captured": {"schema_version": 1, "fragments": {}, "missing": []}}
    monkeypatch.setattr(render, "build_fragment_render_package", lambda *a, page_id, **k: pages[page_id])
    package = render.build_fragment_render_package_for_document(
        None, workspace_id="offline", web_doc={"pages": [{"id": key} for key in pages]},
    )
    assert package["schema_version"] == 2


def test_external_command_target_cannot_leave_the_typed_subtree():
    doc = {"pages": [{"id": "home", "nodes": {
        "root": {"kind": "section", "children": ["trigger"]},
        "trigger": {"kind": "button", "command": "show_modal", "command_target": "external"},
        "external": {"kind": "component", "component": "dialog"},
    }}]}
    with pytest.raises(FragmentRefused, match="button dependencies"):
        native_dependencies_for_subtree(doc, "home", "root")


def test_inspection_reports_native_declaration_without_claiming_behavior_pass():
    from lumen_api.fragments.behavior import inspect_fragment_behavior

    result = inspect_fragment_behavior(HTML, DEPENDENCIES)
    assert result["controller_status"] == "declared_native_runtime"
    assert result["behavior_test"] == "not_performed"
    assert result["declared_native_control_count"] == 1
    mixed = inspect_fragment_behavior(HTML + '<button aria-pressed="false">Foreign</button>', DEPENDENCIES)
    assert mixed["controller_status"] == "mixed_native_and_unretained"
    assert inspect_fragment_behavior(HTML)["controller_status"] == "controller_not_retained"


def test_native_render_requires_the_explicit_helper_capability(monkeypatch):
    from lumen_api.core import CoreClient

    core = CoreClient()
    requests = []
    monkeypatch.setattr(core, "_run", lambda request: requests.append(request) or {"html": ""})
    core.web_render({}, "home", mode="delivery", fragments={"fixture": {"html": HTML}})
    core.web_render({}, "home", mode="delivery", fragments={"fixture": {
        "html": HTML, "native_dependencies": DEPENDENCIES,
    }})
    assert [request["action"] for request in requests] == ["web_render", "web_render_native_fragments"]
