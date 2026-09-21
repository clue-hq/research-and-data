"""W1.5 — `search_assets` finds things.

The 2026-08-20 live acceptance walk
(`_memory/2026-08-20-imagery-acceptance-after-asset-url-fix.md`, run
`run_03144653644947508f2585349c68d2c1`) recorded five of six searches returning
`0 real asset result(s)` — including two that named an asset id the author went
on to place successfully by id. That run's own `trace.jsonl` carries the six
calls verbatim; the five failures are reproduced here as fixtures.

The defect they share is not tokenization and not the (then-empty) descriptions:
**every one of the five passed `kind=image`, and no asset record's `kind` is ever
the string `"image"`.** The engine's record vocabulary is `raster_image` /
`vector` / `logo` / `font`; the AGENT's vocabulary — the one the scene lane's
contact sheet and the brand card show it — is `image` / `logo`. `search_assets`
compared the two with `==`, so the kind filter emptied the candidate set before
any matching ran. The one query that passed no kind filter returned 8 results.

These tests pin the fix: kind-vocabulary reconciliation, an exact-id fast path
across all THREE manifests, ranked any-token matching, px/view/status columns on
every row, and an empty result that names the inventory it searched.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import web_substrate as ws
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- fixtures ----------------------------------------------------------------


def _record(
    asset_id: str,
    *,
    kind: str = "raster_image",
    label: str = "Asset",
    filename: str | None = None,
    width: int = 1600,
    height: int = 1000,
    status: str = "ready",
    tags: list[str] | None = None,
) -> dict:
    record: dict = {
        "id": asset_id,
        "label": label,
        "kind": kind,
        "status": status,
        "source": {"kind": "brand_guide", "source_asset_id": asset_id},
        "media": {
            "mime_type": "image/png",
            "filename": filename or f"{asset_id}.png",
            "digest": {"algorithm": "sha256", "value": asset_id[-16:].rjust(64, "0")},
            "location": {"provider": "opaque_asset_store", "opaque_ref": "sha256/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        },
        "raster": {"pixel_width": width, "pixel_height": height},
        "license": {"name": "client_owned"},
        "provenance": {"source_label": "manual upload"},
        "tags": tags or [],
    }
    return record


def _tools(tmp_path: Path, **cfg) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=tmp_path / "store",
        **cfg,
    )
    seed = {
        "schema_version": 1,
        "id": "doc_web_test",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {"id": "root", "kind": "container", "classes": "", "new_tab": False}
                },
            }
        ],
        "assets": {},
    }
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


def _stripe_tools(tmp_path: Path) -> LumenWebTools:
    """The 2026-08-20 run's asset shape, described the way W1.4 now describes it.

    Same four ids, same record kinds (`raster_image` / `vector`), same split
    across manifests: the SVG wordmark and the bento background came from the
    approved kit, the payment card and globe from the workspace library.
    """
    kit = {
        "asset_ing_61a219a05909b652": {
            "record": _record(
                "asset_ing_61a219a05909b652",
                kind="vector",
                label="Stripe wordmark",
                filename="logo.svg",
                width=2560,
                height=512,
            ),
            "title": "Stripe primary wordmark",
            "description": "The Stripe wordmark in brand indigo on transparency.",
        },
        "asset_ing_2b0928ca4f3a3c70": {
            "record": _record(
                "asset_ing_2b0928ca4f3a3c70",
                label="Payment bento background",
                filename="payment-bento-background.jpg",
                width=2460,
                height=1060,
            ),
            "title": "Abstract fluid wave",
            "description": (
                "An abstract orange-to-pink gradient ribbon flowing across a "
                "dark field, used as an atmospheric payment backdrop."
            ),
        },
    }
    library = {
        "asset_ing_f8ded0d6b5a66d21": {
            "record": _record(
                "asset_ing_f8ded0d6b5a66d21",
                label="Card placeholder",
                filename="card-placeholder_2x.png",
                width=1200,
                height=760,
            ),
            "title": "Payment card UI",
            "description": "A rendered payment card resting on a checkout surface.",
            "usage": "Product-UI bands only.",
            "tags": ["product-ui"],
        },
        "asset_ing_f0453686516c12c8": {
            "record": _record(
                "asset_ing_f0453686516c12c8",
                label="Money movement fallback",
                filename="money-movement-fallback_2x.png",
                width=1400,
                height=1400,
            ),
            "title": "Globe with payment arc",
            "description": "A globe with a connection arc tracing money movement.",
            "tags": ["globe"],
        },
    }
    return _tools(tmp_path, brand_kit_assets=kit, asset_library=library)


def _search(tools: LumenWebTools, q: str, **kwargs) -> dict:
    return json.loads(tools.search_assets(q, **kwargs))


def _ids(result: dict) -> list[str]:
    return [row["asset_id"] for row in result["results"]]


# --- the five live failures, verbatim ----------------------------------------
#
# Queries copied from `run_03144653644947508f2585349c68d2c1/trace.jsonl`,
# `web_assets_searched` payloads. Every one returned 0 before W1.5.


def test_live_failure_abstract_gradient_ribbon_stripe(tmp_path: Path):
    result = _search(_stripe_tools(tmp_path), "abstract gradient ribbon Stripe", kind="image")

    assert result["count"] >= 1
    # The kit's bento background is the asset whose description carries the
    # gradient ribbon — the one the director actually wanted.
    assert result["results"][0]["asset_id"] == "asset_ing_2b0928ca4f3a3c70"


def test_live_failure_payment(tmp_path: Path):
    result = _search(_stripe_tools(tmp_path), "payment", kind="image")

    assert result["count"] >= 1
    # Three of the four assets say "payment" somewhere; the biggest wins the tie.
    assert "asset_ing_2b0928ca4f3a3c70" in _ids(result)


def test_live_failure_globe(tmp_path: Path):
    result = _search(_stripe_tools(tmp_path), "globe", kind="image")

    assert _ids(result)[0] == "asset_ing_f0453686516c12c8"


def test_live_failure_library_id_with_context_words(tmp_path: Path):
    """`'asset_ing_f8ded0d6b5a66d21 payment card'` — an id the author placed by
    hand seconds later. The id rides with context words, so an exact-equality
    fast path is not enough: any TOKEN that is an asset id resolves."""
    result = _search(
        _stripe_tools(tmp_path), "asset_ing_f8ded0d6b5a66d21 payment card", kind="image"
    )

    assert _ids(result)[0] == "asset_ing_f8ded0d6b5a66d21"
    assert result["results"][0]["id_match"] is True


def test_live_failure_second_library_id_with_context_words(tmp_path: Path):
    result = _search(
        _stripe_tools(tmp_path), "asset_ing_f0453686516c12c8 globe payment arc", kind="image"
    )

    assert _ids(result)[0] == "asset_ing_f0453686516c12c8"


def test_the_sixth_live_query_is_no_longer_decided_by_the_kind_filter(tmp_path: Path):
    """The one call of the six that WORKED passed no kind filter, and returned 8
    of the workspace's assets. That asymmetry was the tell.

    Here the same query is run both ways over the same fixture. Before W1.5 the
    filtered run returned NOTHING; now `kind="image"` changes nothing, because
    none of these four records is a `logo` or a `font`.
    """
    tools = _stripe_tools(tmp_path)
    query = "Stripe Payments product UI checkout dashboard developer code finance"

    unfiltered = _ids(_search(tools, query))
    filtered = _ids(_search(_stripe_tools(tmp_path), query, kind="image"))

    # Two of the four fixture assets carry a word from this query: the wordmark
    # ("Stripe") and the card ("product", and the whole word "UI"). The globe and
    # the bento background carry none — honest misses, not filter artifacts. The
    # bento background matched before the short-token fix ONLY because "ui" fell
    # inside "fluid", which is exactly the false hit that fix removes.
    assert sorted(unfiltered) == [
        "asset_ing_61a219a05909b652",
        "asset_ing_f8ded0d6b5a66d21",
    ]
    assert filtered == unfiltered


# --- the kind vocabulary ------------------------------------------------------


def test_kind_image_matches_raster_and_vector_records(tmp_path: Path):
    """The root cause, pinned directly: `kind="image"` is the agent's word for
    every non-logo, non-font record."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_r": {"record": _record("asset_r", kind="raster_image", label="Ribbon")},
            "asset_v": {"record": _record("asset_v", kind="vector", label="Ribbon")},
            "asset_l": {"record": _record("asset_l", kind="logo", label="Ribbon")},
        },
    )

    images = _search(tools, "Ribbon", kind="image")
    logos = _search(tools, "Ribbon", kind="logo")

    assert sorted(_ids(images)) == ["asset_r", "asset_v"]
    assert _ids(logos) == ["asset_l"]


def test_logo_search_finds_fetched_svg_and_raster_assets(tmp_path: Path):
    """Fetched logos retain image storage kinds; that must not hide them as logos."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_library_logo": {"record": _record(
                "asset_library_logo", kind="vector", label="Example corporate logo",
                tags=["target-account", "logo-ladder"],
            )},
        },
        brand_kit_assets={
            "asset_kit_logo": {"record": _record(
                "asset_kit_logo", kind="raster_image", label="Example corporate logo",
                tags=["target-account", "logo-ladder"],
            )},
        },
    )
    tools.web_doc["assets"]["asset_document_logo"] = _record(
        "asset_document_logo", kind="vector", label="Example corporate logo",
        tags=["target-account", "logo-ladder"],
    )
    tools.web_doc["assets"]["asset_document_logo"]["provenance"] = {
        "created_by": "brandfetch", "source_label": "brandfetch",
    }
    tools.config.brand_kit_assets["asset_kit_logo"]["record"]["provenance"] = {
        "created_by": "logo_ladder", "source_label": "website",
    }
    tools.config.asset_library["asset_library_logo"]["record"]["provenance"] = {
        "created_by": "logo_ladder", "source_label": "website",
    }

    result = _search(tools, "Example corporate logo", kind="logo")
    assert set(_ids(result)) == {
        "asset_document_logo", "asset_kit_logo", "asset_library_logo",
    }
    assert {row["origin"] for row in result["results"]} == {
        "document", "brand_kit", "library",
    }
    # This filter is an additional semantic alias, not a rewrite of storage kinds.
    assert set(_ids(_search(tools, "Example", kind="image"))) == set(_ids(result))
    exact = _search(tools, "asset_document_logo", kind="logo")["results"][0]
    assert exact["kind"] == "vector"
    assert "kind_note" not in exact


def test_logo_search_does_not_infer_identity_from_labels_or_non_image_tags(tmp_path: Path):
    tools = _tools(tmp_path, asset_library={
        "asset_photo": {"record": _record(
            "asset_photo", label="Example logo on a building",
        )},
        "asset_pdf": {"record": _record(
            "asset_pdf", kind="document", label="Example logo guide",
            tags=["target-account", "logo-ladder"],
        )},
        "asset_partial": {"record": _record(
            "asset_partial", label="Example logo", tags=["target-account"],
        )},
    })
    tools.config.asset_library["asset_pdf"]["record"]["provenance"] = {
        "created_by": "brandfetch", "source_label": "brandfetch",
    }
    assert _search(tools, "Example", kind="logo")["results"] == []


def test_the_raw_record_kind_still_filters(tmp_path: Path):
    """Reconciliation ADDS the agent vocabulary; it does not remove the engine's."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_r": {"record": _record("asset_r", kind="raster_image", label="Ribbon")},
            "asset_v": {"record": _record("asset_v", kind="vector", label="Ribbon")},
        },
    )

    assert _ids(_search(tools, "Ribbon", kind="raster_image")) == ["asset_r"]


def test_kind_image_never_returns_a_document_record(tmp_path: Path):
    """`AssetKind` also has `document` and `other`, and a PDF-ingested workspace
    really holds `document` rows — `capture/pdf.py::_ingest_reference_pdf`
    stores the brand-guide PDF itself as one, and the library manifest filters
    only `archived`. `_use_library_asset` has no kind guard, so a PDF returned
    under `kind="image"` is a PDF the author can place in an `<img>`. The kind
    table is an allow-list for exactly this reason."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_pdf": {"record": _record("asset_pdf", kind="document", label="Brand guide")},
            "asset_png": {"record": _record("asset_png", label="Brand guide cover")},
        },
    )

    assert _ids(_search(tools, "Brand guide", kind="image")) == ["asset_png"]


def test_a_document_record_is_still_findable_on_its_own_terms(tmp_path: Path):
    """Not hidden — just not an image. It answers to its raw kind and to no
    filter at all, with its true kind stated."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_pdf": {"record": _record("asset_pdf", kind="document", label="Brand guide")}
        },
    )

    assert _ids(_search(tools, "Brand guide", kind="document")) == ["asset_pdf"]
    unfiltered = _search(tools, "Brand guide")
    assert _ids(unfiltered) == ["asset_pdf"]
    assert unfiltered["results"][0]["kind"] == "document"


def test_an_unknown_future_kind_keeps_its_own_name(tmp_path: Path):
    """`other`, or a kind added after this code was written, must not silently
    become an image — it matches its own name or no filter."""
    tools = _tools(
        tmp_path,
        asset_library={"asset_x": {"record": _record("asset_x", kind="other", label="Thing")}},
    )

    assert _ids(_search(tools, "Thing", kind="image")) == []
    assert _ids(_search(tools, "Thing", kind="other")) == ["asset_x"]
    assert _ids(_search(tools, "Thing")) == ["asset_x"]


def test_a_named_document_id_still_returns_under_kind_image(tmp_path: Path):
    """The named-id path is the one place a kind mismatch does not filter — it
    annotates instead, so the agent learns the PDF is a PDF."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_pdf": {"record": _record("asset_pdf", kind="document", label="Brand guide")}
        },
    )

    row = _search(tools, "asset_pdf", kind="image")["results"][0]

    assert row["kind"] == "document"
    assert "document" in row["kind_note"]


# --- the exact-id fast path across all three manifests ------------------------


def test_exact_id_resolves_from_the_document_registry(tmp_path: Path):
    tools = _tools(tmp_path)
    tools.web_doc["assets"] = {"asset_doc_hero": _record("asset_doc_hero", label="Hero")}

    result = _search(tools, "asset_doc_hero")

    assert _ids(result) == ["asset_doc_hero"]
    assert result["results"][0]["origin"] == "document"


def test_exact_id_resolves_from_the_kit_manifest(tmp_path: Path):
    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_kit_hero": {"record": _record("asset_kit_hero")}},
    )

    result = _search(tools, "asset_kit_hero")

    assert _ids(result) == ["asset_kit_hero"]
    assert result["results"][0]["origin"] == "brand_kit"


def test_exact_id_resolves_from_the_asset_library(tmp_path: Path):
    tools = _tools(
        tmp_path, asset_library={"asset_lib_hero": {"record": _record("asset_lib_hero")}}
    )

    result = _search(tools, "asset_lib_hero")

    assert _ids(result) == ["asset_lib_hero"]
    assert result["results"][0]["origin"] == "library"


def test_exact_id_beats_a_richer_token_match(tmp_path: Path):
    """The named id comes first even when another asset scores higher on words."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_named": {"record": _record("asset_named", label="plain")},
            "asset_wordy": {
                "record": _record("asset_wordy", label="globe payment arc gradient"),
                "description": "globe payment arc gradient",
            },
        },
    )

    result = _search(tools, "asset_named globe payment arc gradient")

    assert _ids(result)[0] == "asset_named"


def test_id_with_mismatched_kind_returns_honestly(tmp_path: Path):
    """A named id is never silently dropped for its kind. It comes back with its
    TRUE kind stated, so the agent learns what it actually asked for."""
    tools = _tools(
        tmp_path,
        asset_library={"asset_lib_mark": {"record": _record("asset_lib_mark", kind="logo")}},
    )

    result = _search(tools, "asset_lib_mark", kind="image")

    assert _ids(result) == ["asset_lib_mark"]
    row = result["results"][0]
    assert row["kind"] == "logo"
    assert "logo" in row["kind_note"]


def test_an_unknown_id_does_not_fabricate_a_hit(tmp_path: Path):
    tools = _tools(
        tmp_path, asset_library={"asset_lib_hero": {"record": _record("asset_lib_hero")}}
    )

    result = _search(tools, "asset_does_not_exist")

    assert result["count"] == 0


# --- ranked any-token matching ------------------------------------------------


def test_a_description_token_hits(tmp_path: Path):
    """W1.4 supplies descriptions; W1.5 makes them searchable by ANY token."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_ribbon": {
                "record": _record("asset_ribbon", label="bg-04"),
                "description": "An abstract gradient ribbon over a dark field.",
            },
            "asset_other": {"record": _record("asset_other", label="bg-05")},
        },
    )

    assert _ids(_search(tools, "gradient ribbon")) == ["asset_ribbon"]


def test_more_matched_tokens_outrank_fewer(tmp_path: Path):
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_one": {"record": _record("asset_one", label="gradient")},
            "asset_two": {"record": _record("asset_two", label="gradient ribbon teal")},
        },
    )

    assert _ids(_search(tools, "gradient ribbon teal")) == ["asset_two", "asset_one"]


def test_equal_token_hits_break_on_pixel_area(tmp_path: Path):
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_small": {
                "record": _record("asset_small", label="ribbon", width=400, height=300)
            },
            "asset_big": {
                "record": _record("asset_big", label="ribbon", width=2400, height=1200)
            },
        },
    )

    assert _ids(_search(tools, "ribbon")) == ["asset_big", "asset_small"]


def test_a_long_token_matches_as_a_substring(tmp_path: Path):
    """3+ characters match freely — this is what makes "payment" find
    "payments", the plural robustness the search actually needs."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_p": {"record": _record("asset_p", label="Payments hero")},
        },
    )

    assert _ids(_search(tools, "payment")) == ["asset_p"]


def test_a_short_token_does_not_match_inside_a_longer_word(tmp_path: Path):
    """"ui" is a word an author searches for, but two characters land inside
    ordinary English constantly ("fl(ui)d") — and a false hit here becomes a
    ranked RESULT the director may place. Short tokens match a whole word or the
    start of one, nothing else."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_fluid": {"record": _record("asset_fluid", label="Abstract fluid wave")},
            "asset_ui": {"record": _record("asset_ui", label="Checkout UI panel")},
            "asset_uix": {"record": _record("asset_uix", label="uikit sprite")},
        },
    )

    found = _ids(_search(tools, "ui"))

    assert "asset_fluid" not in found
    assert sorted(found) == ["asset_ui", "asset_uix"]  # whole word + prefix


def test_stop_words_alone_do_not_match_everything(tmp_path: Path):
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_a": {"record": _record("asset_a", label="ribbon")},
            "asset_b": {"record": _record("asset_b", label="globe")},
        },
    )

    # "of the" carries no signal; only "globe" should decide the result set.
    assert _ids(_search(tools, "a photo of the globe")) == ["asset_b"]


# --- result shape -------------------------------------------------------------


def test_rows_carry_px_and_a_view_target(tmp_path: Path):
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_lib_hero": {
                "record": _record("asset_lib_hero", label="Hero", width=2460, height=1060)
            }
        },
    )

    row = _search(tools, "Hero")["results"][0]

    assert row["px"] == "2460x1060"
    assert row["view"] == "asset:asset_lib_hero"


def test_px_is_absent_when_the_record_states_no_dimensions(tmp_path: Path):
    record = _record("asset_lib_flat", label="Hero")
    record.pop("raster")
    tools = _tools(tmp_path, asset_library={"asset_lib_flat": {"record": record}})

    row = _search(tools, "Hero")["results"][0]

    assert "px" not in row
    assert row["view"] == "asset:asset_lib_flat"


def test_status_is_annotated_only_when_it_is_not_ready(tmp_path: Path):
    """W1.1's deferred finding: the library placement path REFUSES a non-ready
    record. Hiding such assets would re-blind the agent, so search annotates."""
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_ready": {"record": _record("asset_ready", label="Ribbon")},
            "asset_pending": {
                "record": _record("asset_pending", label="Ribbon", status="pending")
            },
        },
    )

    rows = {row["asset_id"]: row for row in _search(tools, "Ribbon")["results"]}

    assert set(rows) == {"asset_ready", "asset_pending"}
    assert "status" not in rows["asset_ready"]
    assert rows["asset_pending"]["status"] == "pending"


def test_view_asset_text_annotates_a_non_ready_status(tmp_path: Path):
    from PIL import Image

    store = tmp_path / "store"
    ref = "sha256/cc/cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    (store / "sha256/cc").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 40), (1, 2, 3)).save(store / ref, format="PNG")
    record = _record("asset_pending", label="Ribbon", status="pending")
    record["media"]["location"]["opaque_ref"] = ref
    # The resolver treats `media.digest.value` as the record's byte identity
    # (primary over the location ref), so the digest must name the bytes this
    # test actually wrote.
    record["media"]["digest"]["value"] = "c" * 64
    tools = _tools(tmp_path, asset_library={"asset_pending": {"record": record}})

    text = "\n".join(
        block["text"]
        for block in tools._view_content("asset:asset_pending")
        if block.get("type") == "text"
    )

    assert "status pending" in text


def test_view_asset_text_omits_a_ready_status(tmp_path: Path):
    from PIL import Image

    store = tmp_path / "store"
    ref = "sha256/dd/dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    (store / "sha256/dd").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 40), (1, 2, 3)).save(store / ref, format="PNG")
    record = _record("asset_ready", label="Ribbon")
    record["media"]["location"]["opaque_ref"] = ref
    tools = _tools(tmp_path, asset_library={"asset_ready": {"record": record}})

    text = "\n".join(
        block["text"]
        for block in tools._view_content("asset:asset_ready")
        if block.get("type") == "text"
    )

    assert "status" not in text


# --- the honest empty ---------------------------------------------------------


def test_empty_results_name_the_inventory_and_the_filter(tmp_path: Path):
    tools = _stripe_tools(tmp_path)
    tools.web_doc["assets"] = {"asset_doc_hero": _record("asset_doc_hero")}

    result = _search(tools, "kangaroo", kind="image")

    assert result["count"] == 0
    note = result["note"]
    assert "0 results for 'kangaroo'" in note
    assert "kind=image" in note
    assert "1 document" in note
    assert "2 brand kit" in note
    assert "2 library" in note


def test_empty_results_state_an_empty_inventory_too(tmp_path: Path):
    result = _search(_tools(tmp_path), "kangaroo")

    assert result["count"] == 0
    assert "0 document, 0 brand kit, 0 library assets" in result["note"]
    assert "kind=" not in result["note"]


def test_the_empty_note_only_suggests_dropping_a_filter_that_was_applied(
    tmp_path: Path,
):
    """Advice about a knob the agent never turned is noise that teaches nothing."""
    tools = _stripe_tools(tmp_path)

    unfiltered = _search(tools, "kangaroo")["note"]
    filtered = _search(_stripe_tools(tmp_path), "kangaroo", kind="image")["note"]

    assert "kind filter" not in unfiltered
    assert "exact asset id" in unfiltered
    assert "drop the kind filter" in filtered


# --- the grounding source cap never eats the answer ---------------------------


def _fill_grounding_budget(tools: LumenWebTools) -> None:
    """Burn the run's whole grounded-source budget on unrelated sources."""
    for index in range(ws._GROUNDED_SOURCE_MAX):
        tools._register_grounding_source(
            {"source_id": f"filler_{index}", "kind": "asset", "asset_id": f"filler_{index}"}
        )


def _by_origin(result: dict, origin: str) -> list[dict]:
    return [row for row in result["results"] if row["origin"] == origin]


def test_a_full_source_budget_still_returns_the_matched_rows(tmp_path: Path):
    """A budget condition must not read to the agent as "your query matched
    less". Before this, registration failure `break`ed out of the result loop, so
    a full budget silently truncated — or emptied — a result set that had real
    matches, and the honest-empty note then blamed the query."""
    tools = _stripe_tools(tmp_path)
    _fill_grounding_budget(tools)

    result = _search(tools, "payment", kind="image")

    library_rows = _by_origin(result, "library")
    kit_rows = _by_origin(result, "brand_kit")
    assert library_rows and kit_rows
    assert all(
        row["grounding"] == "unregistered — source cap reached" for row in library_rows
    )
    # A kit row never registers a source at all (only `use_library_asset`
    # consumes one), so a full budget is not its story and the annotation would
    # be a lie about a row nothing is wrong with.
    assert all("grounding" not in row for row in kit_rows)


def test_a_full_source_budget_is_named_in_a_note(tmp_path: Path):
    tools = _stripe_tools(tmp_path)
    _fill_grounding_budget(tools)

    result = _search(tools, "payment", kind="image")

    note = result["note"]
    # Only the rows that TRIED to register are counted — the kit row in this
    # result set never does.
    assert f"{len(_by_origin(result, 'library'))} of {result['count']} result(s)" in note
    assert "source budget is full" in note
    assert "needs budget" in note


def test_registered_rows_carry_no_grounding_field(tmp_path: Path):
    result = _search(_stripe_tools(tmp_path), "payment", kind="image")

    assert all("grounding" not in row for row in result["results"])
    assert "note" not in result


# --- only the rows that can SPEND the budget register against it ---------------
#
# `use_library_asset` is the one action that consumes a grounded source.
# `use_brand_asset` registers none (it rewrites the record's source to the brand
# guide), and a document row is already on the page. Registering a source for
# every returned row therefore spent the shared 64-slot budget on rows that were
# never going to need it: a handful of kit-heavy searches exhausted it, and the
# next `use_library_asset` / `fetch_page` hard-failed `asset.grounding_limit`
# mid-turn — a browse of the kit killing a placement it had nothing to do with.


def _kit_heavy_tools(tmp_path: Path) -> tuple[LumenWebTools, str]:
    """A turn whose brand kit alone can fill the whole source budget by search.

    Eight tag groups of eight — eight `limit=8` searches is a plausible browse
    of a real kit, and `8 x 8` is exactly `_GROUNDED_SOURCE_MAX`.
    """
    kit: dict = {}
    for group in range(8):
        for index in range(8):
            asset_id = f"asset_kit_{group}{index}"
            kit[asset_id] = {
                "record": _record(
                    asset_id,
                    label=f"Kit plate {group}{index}",
                    tags=[f"bandgroup{group}"],
                ),
                "title": f"Kit plate {group}{index}",
            }
    library_record = json.loads(
        (REPO_ROOT / "crates/lumen-core/fixtures/assets/uploaded_logo_asset.json").read_text()
    )
    library_id = library_record["id"]
    library = {library_id: {"record": library_record, "title": "Acme primary logo"}}
    return _tools(tmp_path, brand_kit_assets=kit, asset_library=library), library_id


def test_a_kit_heavy_turn_leaves_budget_for_a_later_library_placement(tmp_path: Path):
    tools, library_id = _kit_heavy_tools(tmp_path)

    for group in range(8):
        assert _search(tools, f"bandgroup{group}", kind="image")["count"] == 8

    # Nothing placeable was browsed away: the kit rows cost no budget at all.
    assert tools.grounding_report()["sources"] == []

    placed = json.loads(tools.asset(action="use_library_asset", asset_id=library_id))

    assert placed["status"] == "ok", placed
    assert placed["asset_id"] == library_id


def test_a_library_row_still_registers_its_source_when_search_returns_it(
    tmp_path: Path,
):
    """The other half of the rule — the row that CAN be placed by
    `use_library_asset` still arrives grounded, exactly as before."""
    tools = _stripe_tools(tmp_path)

    result = _search(tools, "payment", kind="image")

    registered = {source["asset_id"] for source in tools.grounding_report()["sources"]}
    assert registered == {row["asset_id"] for row in _by_origin(result, "library")}
    assert _by_origin(result, "brand_kit")  # the kit row was returned, uncited


def test_zero_results_can_only_ever_mean_zero_matches(tmp_path: Path):
    """The invariant behind the honest-empty note: because a matched row is
    never dropped, an empty result set can never be a suppressed one, so the
    note never has to guess which it is describing."""
    tools = _stripe_tools(tmp_path)
    _fill_grounding_budget(tools)

    matched = _search(tools, "payment", kind="image")
    unmatched = _search(tools, "kangaroo", kind="image")

    assert matched["count"] > 0  # a full budget did NOT empty a matching search
    assert unmatched["count"] == 0
    assert "0 results for 'kangaroo'" in unmatched["note"]


def test_search_works_with_no_library_manifest_at_all(tmp_path: Path):
    """A turn with kit assets but no library manifest used to be a hard tool
    error; the kit is a real inventory and must still be searchable."""
    tools = _tools(
        tmp_path,
        asset_library=None,
        brand_kit_assets={"asset_kit_hero": {"record": _record("asset_kit_hero", label="Hero")}},
    )

    assert _ids(_search(tools, "Hero")) == ["asset_kit_hero"]


# --- unchanged contracts ------------------------------------------------------


def test_the_same_id_in_two_manifests_appears_once(tmp_path: Path):
    """Precedence is `view("asset:<id>")`'s own resolution order — document,
    then brand kit, then library — so search and view can never disagree about
    which record an id names."""
    record = _record("asset_shared", label="Hero")
    tools = _tools(
        tmp_path,
        asset_library={"asset_shared": {"record": record, "title": "Library title"}},
        brand_kit_assets={"asset_shared": {"record": record, "title": "Kit title"}},
    )

    result = _search(tools, "Hero")

    assert _ids(result) == ["asset_shared"]
    assert result["results"][0]["origin"] == "brand_kit"


def test_precedence_matches_view_asset_resolution_order(tmp_path: Path):
    """The registry wins over both manifests, exactly as `_view_asset` does it."""
    record = _record("asset_shared", label="Hero")
    tools = _tools(
        tmp_path,
        asset_library={"asset_shared": {"record": record, "title": "Library title"}},
        brand_kit_assets={"asset_shared": {"record": record, "title": "Kit title"}},
    )
    tools.web_doc["assets"] = {"asset_shared": record}

    assert _search(tools, "Hero")["results"][0]["origin"] == "document"


def test_search_never_mutates_the_web_doc(tmp_path: Path):
    tools = _stripe_tools(tmp_path)
    before = json.dumps(tools.web_doc, sort_keys=True)

    _search(tools, "payment", kind="image")

    assert json.dumps(tools.web_doc, sort_keys=True) == before


def test_limit_is_still_bounded_at_twenty(tmp_path: Path):
    tools = _tools(tmp_path, asset_library={"a": {"record": _record("a")}})

    assert json.loads(tools.search_assets("a", limit=21))["error_code"] == (
        "asset_search.bad_limit"
    )
    assert json.loads(tools.search_assets("a", limit=0))["error_code"] == (
        "asset_search.bad_limit"
    )


def test_results_register_grounding_sources(tmp_path: Path):
    tools = _stripe_tools(tmp_path)

    result = _search(tools, "globe", kind="image")

    sources = tools.grounding_report()["sources"]
    assert [source["asset_id"] for source in sources] == _ids(result)
