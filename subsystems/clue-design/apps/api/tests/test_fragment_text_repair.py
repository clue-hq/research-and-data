"""Account copy can change without reconstructing captured visual/behavior markup."""

import copy

import pytest

from lumen_api.fragments.artifact import build_fragment_artifact
from lumen_api.fragments.href_repair import build_href_repair
from lumen_api.fragments.refs import FragmentRefused
from lumen_api.fragments.slots import SlotSpec


@pytest.fixture
def source():
    return build_fragment_artifact(
        html='<section class="features"><h2>Generic overview</h2>'
        "<div><h3><span>Handle requests</span></h3><p>Original explanation</p></div>"
        '<details><summary><span>Generic question?</span><svg><path d="M0 0"></path></svg></summary>'
        '<p>Generic answer.</p></details><img src="/asset-store/' + "a" * 64 + '">'
        '<p data-keep="same">Bound body</p><a href="/demo">Book a demo</a></section>',
        css=".features{font-family:serif;font-size:18px;border-radius:14px;background:#123}"
        ".features h3{font-size:48px;font-weight:400}@media(max-width:768px){.features h3{font-size:32px}}",
        slots=[SlotSpec(key="body", kind="text", selector="p[data-keep]")],
        rehosted={},
    )


def inventory(source, **kwargs):
    from lumen_api.fragments.text_repair import inspect_text_targets

    return inspect_text_targets(source.payload["html"], **kwargs)


def edit(source, old, new):
    target = next(row for row in inventory(source)["targets"] if row["text"] == old)
    return {"path": target["path"], "expected": old, "replacement": new}


def test_copy_variant_preserves_source_styles_assets_structure_and_slots(source):
    before = copy.deepcopy(source.payload)
    edits = [
        edit(source, "Handle requests", "A shared request handoff"),
        edit(source, "Generic question?", "Which requests stay with the team?"),
    ]
    repair = build_href_repair(source.payload, text_edits=edits)
    after = repair.artifact.payload
    assert after["html"] == before["html"].replace(
        "Handle requests", "A shared request handoff"
    ).replace("Generic question?", "Which requests stay with the team?")
    assert (
        after["css"].replace(repair.artifact.wrapper_class, source.wrapper_class) == before["css"]
    )
    assert after["asset_digests"] == before["asset_digests"]
    assert after["slot_manifest"] == before["slot_manifest"]
    assert source.payload == before
    assert repair.text_match_paths == [e["path"] for e in edits]
    assert build_href_repair(source.payload, text_edits=edits) == repair


def test_text_inventory_is_paged_and_names_blocked_bindings(source):
    whole = inventory(source)
    pages = []
    offset = 0
    while True:
        page = inventory(source, offset=offset, limit=2)
        pages.extend(page["targets"])
        offset = page["next_offset"]
        if offset is None:
            break
    assert pages == whole["targets"]
    assert len({row["path"] for row in pages}) == len(pages)
    bound = next(row for row in pages if row["text"] == "Bound body")
    assert bound["editable"] is False and bound["reason"] == "existing_text_slot"
    anchor = next(row for row in pages if row["text"] == "Book a demo")
    assert anchor["reason"] == "use_anchor_label_repair"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda edits: edits + edits,
        lambda edits: [{**edits[0], "expected": "Stale text"}],
        lambda edits: [{**edits[0], "path": ":nth-child(900)"}],
        lambda edits: [{**edits[0], "path": "section"}],
        lambda edits: [{**edits[0], "replacement": ""}],
    ],
)
def test_invalid_target_edits_refuse_without_partial_change(source, mutate):
    before = copy.deepcopy(source.payload)
    with pytest.raises(FragmentRefused):
        build_href_repair(
            source.payload, text_edits=mutate([edit(source, "Handle requests", "New")])
        )
    assert source.payload == before


def test_text_edit_cannot_mask_existing_binding(source):
    with pytest.raises(FragmentRefused, match="slot"):
        build_href_repair(source.payload, text_edits=[edit(source, "Bound body", "Unbound")])


def test_text_edit_escapes_markup_without_changing_source_structure(source):
    repair = build_href_repair(
        source.payload, text_edits=[edit(source, "Generic answer.", "<script>x</script> & facts")]
    )
    assert "&lt;script&gt;x&lt;/script&gt; &amp; facts" in repair.artifact.payload["html"]
    assert "<script>" not in repair.artifact.payload["html"]


def test_split_styled_text_does_not_flatten_children():
    artifact = build_fragment_artifact(
        html="<section><p>Plain <em>emphasis</em></p></section>", css="", rehosted={}, slots=[]
    )
    with pytest.raises(FragmentRefused):
        build_href_repair(
            artifact.payload,
            text_edits=[
                {
                    "path": ":nth-child(1) > :nth-child(1)",
                    "expected": "Plain emphasis",
                    "replacement": "Flat",
                }
            ],
        )


def test_target_accessible_name_conflict_refuses():
    artifact = build_fragment_artifact(
        html='<section><button aria-label="Other"><span>Visible</span></button></section>',
        css="",
        rehosted={},
        slots=[],
    )
    with pytest.raises(FragmentRefused, match="accessible"):
        build_href_repair(artifact.payload, text_edits=[edit(artifact, "Visible", "Changed")])


@pytest.mark.parametrize(
    "path", [":nth-child(1):nth-child(1)", ":nth-child(1) > ", ":nth-child(01) > :nth-child(1)"]
)
def test_only_inventory_canonical_paths_are_accepted(source, path):
    with pytest.raises(FragmentRefused):
        build_href_repair(
            source.payload,
            text_edits=[
                {
                    "path": path,
                    "expected": "Generic overview",
                    "replacement": "Changed",
                }
            ],
        )


def test_unaddressable_bare_text_is_not_advertised_as_editable():
    from lumen_api.fragments.text_repair import inspect_text_targets

    result = inspect_text_targets("Bare text<section><p>Content</p></section>")
    assert not next(row for row in result["targets"] if row["path"] == "")["editable"]


def test_stored_paths_count_hidden_siblings_and_select_only_one_duplicate():
    source = build_fragment_artifact(
        html='<section><p class="hidden">Repeated</p><p>Repeated</p></section>',
        css="",
        rehosted={},
        slots=[SlotSpec(key="hidden", kind="visibility", selector=".hidden")],
    )
    path = ":nth-child(1) > :nth-child(2)"
    repair = build_href_repair(
        source.payload,
        text_edits=[
            {
                "path": path,
                "expected": "Repeated",
                "replacement": "Chosen account copy",
            }
        ],
    )
    from selectolax.lexbor import LexborHTMLParser

    assert [p.text() for p in LexborHTMLParser(repair.artifact.payload["html"]).css("p")] == [
        "Repeated",
        "Chosen account copy",
    ]


def test_whitespace_entities_and_icon_subtree_survive():
    source = build_fragment_artifact(
        html='<section><summary>  More &amp;\n better <svg><path d="M0 0"></path></svg></summary></section>',
        css="",
        rehosted={},
        slots=[],
    )
    repair = build_href_repair(
        source.payload,
        text_edits=[
            {
                "path": ":nth-child(1) > :nth-child(1)",
                "expected": "More & better",
                "replacement": "One & only",
            }
        ],
    )
    assert repair.artifact.payload["html"] == source.payload["html"].replace(
        "More &amp;\n better", "One &amp; only"
    )


def test_entire_batch_validates_before_deriving_even_with_a_valid_first_edit(source):
    before = copy.deepcopy(source.payload)
    edits = [
        edit(source, "Generic overview", "Account relevance"),
        {**edit(source, "Handle requests", "New"), "expected": "Stale"},
    ]
    with pytest.raises(FragmentRefused, match="expected text"):
        build_href_repair(source.payload, text_edits=edits)
    assert source.payload == before


def test_canonical_and_campaign_text_derivatives_do_not_converge(source):
    edits = [edit(source, "Handle requests", "Account handoffs")]
    canonical = build_href_repair(source.payload, text_edits=edits)
    variant = build_href_repair(
        source.payload, text_edits=edits, text_edit_scope="campaign_variant"
    )
    assert canonical.artifact.fragment_id != variant.artifact.fragment_id
    assert canonical.artifact.payload["html"] == variant.artifact.payload["html"]


@pytest.mark.parametrize(
    "decoration", ["<svg><title>Arrow</title></svg>", '<span aria-hidden="true">Decorative</span>']
)
def test_inventory_expected_text_matches_eligible_leaf_with_decorative_descendants(decoration):
    source = build_fragment_artifact(
        html="<section><summary>Read more" + decoration + "</summary></section>",
        css="",
        rehosted={},
        slots=[],
    )
    row = next(r for r in inventory(source)["targets"] if r["tag"] == "summary")
    assert row["editable"]
    repair = build_href_repair(
        source.payload,
        text_edits=[
            {
                "path": row["path"],
                "expected": row["text"],
                "replacement": "Account workflow",
            }
        ],
    )
    assert repair.artifact.payload["html"] == source.payload["html"].replace(
        "Read more", "Account workflow"
    )
