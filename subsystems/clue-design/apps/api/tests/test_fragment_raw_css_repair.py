"""Raw repair regressions with real fragment primitives and no database writes."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from lumen_api import agent_cloned_sections as agent
from lumen_api.fragments import FragmentRefused, build_fragment_artifact
from lumen_api.fragments import registry as custody
from lumen_api.fragments.cssscope import scope_fragment_css
from lumen_api.fragments.refs import fragment_wrapper_class
from lumen_api.fragments.registry import LoadedFragment
from lumen_ingestion.sections.slotdetect import detect_slots

HTML = '<section class="band"><h2>For your team</h2><p>Product detail.</p></section>'
CSS = '.band { height: 3200px } .band h2 { color: #123456 }'


@pytest.fixture
def repair_registry(monkeypatch, tmp_path):
    """Replace only durable I/O; sanitation, scoping, addressing and repair decisions stay real."""
    source = build_fragment_artifact(
        html=HTML, css=CSS, rehosted={}, slots=detect_slots(HTML).specs,
    )
    original = {
        'fragment_id': source.fragment_id, 'status': 'approved', 'section_role': 'hero',
        'label': 'Original hero', 'source_url': 'https://seller.example/product',
        'source_kit_id': 'kit_seller', 'source_kit_version': 4,
        'provenance': {'page_url': 'https://seller.example/product', 'section_index': 2},
        'degraded': True, 'degraded_reason': 'dead_height',
    }
    rows = {source.fragment_id: deepcopy(original)}
    artifacts = {source.fragment_id: source}
    repo = SimpleNamespace(find_web_fragment=lambda fragment_id: rows.get(fragment_id))
    monkeypatch.setattr(agent.DurableAgentClonedSectionRegistry, '_repository', lambda _: repo)
    monkeypatch.setattr(
        agent, 'read_web_fragment',
        lambda _storage, *, workspace_id, fragment_id: LoadedFragment(
            deepcopy(rows[fragment_id]), deepcopy(artifacts[fragment_id].payload),
        ),
    )

    def persist(_storage, *, artifact, **metadata):
        row = {**metadata, 'fragment_id': artifact.fragment_id, 'status': 'draft'}
        rows.setdefault(artifact.fragment_id, row)
        artifacts.setdefault(artifact.fragment_id, artifact)
        return rows[artifact.fragment_id], artifact

    monkeypatch.setattr(custody, '_persist_fragment_artifact', persist)
    instance = agent.DurableAgentClonedSectionRegistry(
        blobs=SimpleNamespace(workspace_id='ws_repair_test', storage=object()),
        cache_dir=tmp_path,
    )
    return instance, source, original, rows, artifacts


def test_css_only_repair_changes_geometry_without_changing_markup(repair_registry):
    registry, source, original, rows, artifacts = repair_registry
    result = registry.mint_repair(
        replaces=source.fragment_id, html=HTML, css=CSS.replace('3200px', 'auto'),
        rung=3, note='Remove artificial height',
    )
    repaired = artifacts[result['fragment_id']]
    assert repaired.payload['html'] == source.payload['html']
    assert 'height: auto' in repaired.payload['css']
    assert result['derived_from'] == source.fragment_id
    assert result['preserves_pin_content'] is True
    assert rows[source.fragment_id] == original
    assert source.payload['css'].find('height: 3200px') >= 0
    assert rows[result['fragment_id']]['source_kit_id'] == 'kit_seller'
    assert rows[result['fragment_id']]['source_url'] == 'https://seller.example/product'


def test_copy_edit_with_inspected_css_has_one_working_namespace(repair_registry):
    registry, source, _, _, artifacts = repair_registry
    result = registry.mint_repair(
        replaces=source.fragment_id, html=HTML.replace('your team', 'your operations'),
        css=source.payload['css'], rung=2, note='Account copy only',
    )
    new = artifacts[result['fragment_id']]
    assert result['preserves_pin_content'] is False
    old_wrapper = fragment_wrapper_class(source.fragment_id)
    new_wrapper = fragment_wrapper_class(new.fragment_id)
    assert old_wrapper not in new.payload['css']
    assert f'.{new_wrapper} .band ' in new.payload['css']
    assert f'.{new_wrapper} .{new_wrapper}' not in new.payload['css']


@pytest.mark.parametrize('inspected', [False, True])
def test_identical_markup_and_effective_css_remain_a_noop(repair_registry, inspected):
    registry, source, original, rows, _ = repair_registry
    with pytest.raises(FragmentRefused, match='repairs nothing') as failure:
        registry.mint_repair(
            replaces=source.fragment_id, html=HTML,
            css=source.payload['css'] if inspected else CSS, rung=1, note='No changes',
        )
    assert failure.value.code == 'fragment.repair_unchanged'
    assert rows == {source.fragment_id: original}


def test_inspected_css_edit_keeps_nested_rules_keyframes_and_custodied_assets(repair_registry):
    registry, source, _, _, artifacts = repair_registry
    old = fragment_wrapper_class(source.fragment_id)
    digest = 'a' * 64
    css = (
        f'.{old} {{ --label: "{old}" }} '
        f'@media (max-width: 768px) {{ .{old} .band {{ height: auto; '
        f'animation: reveal--{old} 1s; background: url(/asset-store/{digest}) }} }} '
        f'@keyframes reveal--{old} {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}'
    )
    result = registry.mint_repair(
        replaces=source.fragment_id, html=HTML, css=css, rung=3, note='Responsive CSS fix',
    )
    repaired = artifacts[result['fragment_id']]
    new = fragment_wrapper_class(repaired.fragment_id)
    assert f'.{new} {{' in repaired.payload['css']
    assert f'.{new} .band {{' in repaired.payload['css']
    assert '@media (max-width: 768px)' in repaired.payload['css']
    assert f'@keyframes reveal--{new}' in repaired.payload['css']
    assert f'animation: reveal--{new} 1s' in repaired.payload['css']
    assert f'--label: "{old}"' in repaired.payload['css']
    assert f'/asset-store/{digest}' in repaired.payload['css']
    assert repaired.payload['asset_digests'] == [digest]


def test_inspected_css_still_refuses_external_asset_before_custody(repair_registry):
    registry, source, original, rows, _ = repair_registry
    old = fragment_wrapper_class(source.fragment_id)
    with pytest.raises(FragmentRefused):
        registry.mint_repair(
            replaces=source.fragment_id, html=HTML,
            css=f'.{old} .band {{ background: url(https://unheld.example/photo.png) }}',
            rung=3, note='Invalid external bytes',
        )
    assert rows == {source.fragment_id: original}


@pytest.mark.parametrize('relationship', ['+', '~', '||'])
def test_retargeting_cannot_escape_to_a_wrapper_sibling(relationship):
    with pytest.raises(FragmentRefused) as failure:
        scope_fragment_css(
            f'.lumen-frag-1111111111111111:hover {relationship} .outside {{ color: red }}',
            fragment_id='frag_2222222222222222', source_fragment_id='frag_1111111111111111',
            rehosted={},
        )
    assert failure.value.code == 'fragment.css_scope_escape'


def test_retargeting_preserves_root_qualifiers_and_scopes_new_rules():
    result = scope_fragment_css(
        'html.dark .lumen-frag-1111111111111111 .band { color: red } '
        '.fresh { max-width: 100% } '
        '.lumen-frag-3333333333333333 .other { color: blue }',
        fragment_id='frag_2222222222222222', source_fragment_id='frag_1111111111111111',
        rehosted={},
    )
    assert 'html.dark .lumen-frag-2222222222222222 .band' in result.css
    assert '.lumen-frag-2222222222222222 .fresh' in result.css
    # Only the declared source gets normalized; a foreign scope never grants global styling.
    assert '.lumen-frag-2222222222222222 .lumen-frag-3333333333333333 .other' in result.css


def test_fragment_identity_accounts_for_source_scope_semantics():
    css = '.lumen-frag-1111111111111111 .band { color: red }'
    retargeted = build_fragment_artifact(
        html=HTML, css=css, rehosted={}, source_fragment_id='frag_1111111111111111',
    )
    foreign = build_fragment_artifact(
        html=HTML, css=css, rehosted={}, source_fragment_id='frag_3333333333333333',
    )
    assert retargeted.fragment_id != foreign.fragment_id
    # Source-local ids are irrelevant when the resulting CSS has the same meaning.
    unscoped_a = build_fragment_artifact(
        html=HTML, css=CSS, rehosted={}, source_fragment_id='frag_1111111111111111',
    )
    unscoped_b = build_fragment_artifact(
        html=HTML, css=CSS, rehosted={}, source_fragment_id='frag_3333333333333333',
    )
    assert unscoped_a == unscoped_b


def test_scope_prelude_retargets_parsed_classes_but_preserves_attribute_strings():
    old = 'lumen-frag-1111111111111111'
    new = 'lumen-frag-2222222222222222'
    result = scope_fragment_css(
        f'@scope (:is(.{old}, .{old}.active)) to ([data-label="{old}"]) '
        f'{{ .{old} .band {{ height: auto }} }}',
        fragment_id='frag_2222222222222222', source_fragment_id='frag_1111111111111111',
        rehosted={},
    )
    assert f'@scope (:is(.{new}, .{new}.active))' in result.css
    assert f'to ([data-label="{old}"])' in result.css
    assert f'.{new} .band {{' in result.css
    assert f'.{old}' not in result.css
