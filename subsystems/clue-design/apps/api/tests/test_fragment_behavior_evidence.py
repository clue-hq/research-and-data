"""Snapshot affordances are evidence of states, not recovered controllers."""

import json
from types import SimpleNamespace


def inspect(html: str) -> dict:
    from lumen_api.fragments.behavior import inspect_fragment_behavior

    return inspect_fragment_behavior(html)


def test_four_feature_controls_report_frozen_states_and_custodied_media() -> None:
    html = '<section>' + ''.join(
        f'<button aria-pressed="{str(i == 0).lower()}"><h3>Feature {i}</h3></button>'
        f'<img alt="Feature {i} artwork" class="opacity-{100 if i == 0 else 0}" '
        f'src="/asset-store/{str(i) * 64}">'
        for i in range(4)
    ) + '</section>'
    result = inspect(html)
    assert result['controller_status'] == 'controller_not_retained'
    assert result['behavior_test'] == 'not_performed'
    assert result['stateful_control_count'] == 4
    assert result['hidden_state_candidate_count'] == 3
    assert result['asset_digests'] == [str(i) * 64 for i in range(4)]
    assert result['controls'][0]['label'] == 'Feature 0'
    assert result['controls'][0]['state'] == {'aria-pressed': 'true'}
    assert result['relationships'] == 'not_inferred'


def test_native_details_and_popover_controls_are_not_foreign_controller_defects() -> None:
    result = inspect('''<details><summary aria-expanded="false">Details</summary>
        <p hidden>Details body</p></details>
        <button popovertarget="menu" aria-expanded="false">Menu</button>
        <div id="menu" popover>Menu body</div>
        <button commandfor="dialog" command="show-modal" aria-controls="dialog">Open</button>
        <dialog id="dialog">Dialog</dialog>''')
    assert result['controller_status'] == 'not_assessed'
    assert result['stateful_control_count'] == 0


def test_ordinary_links_buttons_and_decorative_hidden_art_are_not_script_proof() -> None:
    result = inspect('<a href="#details">Details</a><button>More</button><img class="opacity-0">')
    assert result['controller_status'] == 'not_assessed'
    assert result['stateful_control_count'] == 0
    assert result['hidden_state_candidate_count'] == 1


def test_tabs_and_controlled_panels_retain_exact_ids_without_guessing_a_pairing() -> None:
    result = inspect('''<div role="tablist"><button id="tab-a" role="tab"
        aria-selected="false" aria-controls="panel-a">Operations</button></div>
        <div id="panel-a" role="tabpanel" hidden><img alt="Operations"></div>''')
    assert result['controls'][0]['target_id'] == 'panel-a'
    assert result['hidden_states'][0]['element_id'] == 'panel-a'
    assert result['hidden_states'][0]['markers'] == ['hidden_attribute']
    assert result['relationships'] == 'not_inferred'


def test_evidence_is_bounded_without_omitting_total_counts() -> None:
    html = ''.join(
        '<button aria-pressed="false">' + 'x' * 400 + '</button>'
        f'<img class="opacity-0" alt="{"y" * 400}" src="/asset-store/{i:064x}">'
        for i in range(50)
    )
    result = inspect(html)
    assert result['stateful_control_count'] == 50
    assert result['hidden_state_candidate_count'] == 50
    assert result['truncated'] is True
    assert len(result['controls']) <= 12
    assert len(result['hidden_states']) <= 12
    assert len(result['asset_digests']) <= 24
    assert len(json.dumps(result)) < 9500


def test_inline_hidden_state_is_observed_but_css_selector_semantics_are_not_invented() -> None:
    result = inspect('''<button aria-pressed="true">One</button>
        <img style="opacity: 0; transform: translateX(10px)" alt="Hidden state">
        <img class="md:opacity-0" alt="Responsive state">''')
    assert result['hidden_state_candidate_count'] == 1
    assert result['hidden_states'][0]['markers'] == ['inline_opacity_zero']


def test_remote_addresses_and_scripts_never_become_dependencies() -> None:
    result = inspect('''<button aria-pressed="false">One</button>
        <script src="https://example.test/app.js"></script>
        <img src="https://example.test/image.png" class="opacity-0">''')
    assert result['asset_digests'] == []
    assert 'https://' not in json.dumps(result)


def test_agent_source_inspection_derives_behavior_from_stored_payload(
    monkeypatch, tmp_path,
) -> None:
    from lumen_api import agent_cloned_sections

    original = '<button aria-pressed="false">Review replies</button>'
    stored = SimpleNamespace(
        row={'provenance': {'untrusted_extra': 'not exposed'}},
        payload={'html': original, 'css': ''}, slot_manifest={},
    )
    reads = []

    def read(storage, *, workspace_id, fragment_id):
        reads.append((workspace_id, fragment_id))
        return stored

    monkeypatch.setattr(agent_cloned_sections, 'read_web_fragment', read)
    registry = agent_cloned_sections.DurableAgentClonedSectionRegistry(
        blobs=SimpleNamespace(workspace_id='ws_scope', storage=None), cache_dir=tmp_path,
    )
    result = registry.read_source('frag_source')
    assert reads == [('ws_scope', 'frag_source')]
    assert result['behavior_evidence']['controller_status'] == 'controller_not_retained'
    assert result['html'] == stored.payload['html'] == original
    assert 'untrusted_extra' not in result['behavior_evidence']


def test_many_renditions_do_not_hide_the_primary_asset_of_later_panel_states() -> None:
    first = 'a' * 64
    last = 'f' * 64
    variants = ', '.join(f'/asset-store/{i:064x} {i + 1}w' for i in range(30))
    result = inspect(f'<img src="/asset-store/{first}" srcset="{variants}">'
                     f'<img src="/asset-store/{last}" class="opacity-0">')
    assert first in result['asset_digests']
    assert last in result['asset_digests']
