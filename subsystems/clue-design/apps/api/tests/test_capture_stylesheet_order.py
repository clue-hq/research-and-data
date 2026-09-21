"""Captured CSS must retain the source cascade before fragments are extracted."""

from __future__ import annotations

import asyncio

from lumen_ingestion.capture.net import FetchResult
from lumen_ingestion.capture.rendered import collect_stylesheets
from playwright.sync_api import sync_playwright


class Fetcher:
    def __init__(self, files):
        self.files = files
        self.requested = []

    async def fetch_many(self, requests):
        result = []
        for request in requests:
            self.requested.append(request.url)
            value = self.files.get(request.url)
            if value is None:
                result.append(FetchResult(url=request.url, kind="css", ok=False, diagnostics=[]))
            else:
                result.append(
                    FetchResult(
                        url=request.url,
                        kind="css",
                        ok=True,
                        body=value.encode(),
                        final_url=request.url,
                    )
                )
        return result


def test_link_style_interleaving_and_repeated_link_occurrences_are_preserved():
    fetcher = Fetcher({"https://example.com/a.css": ".x {color:red}"})
    sheets, _ = asyncio.run(
        collect_stylesheets(
            [
                {"href": "https://example.com/a.css", "text": None},
                {"href": None, "text": ".x {color:blue}"},
                {"href": "https://example.com/a.css", "text": None},
            ],
            fetcher,
        )
    )
    assert [s.url for s in sheets] == [
        "https://example.com/a.css",
        "inline:1",
        "https://example.com/a.css",
    ]
    assert fetcher.requested.count("https://example.com/a.css") == 1


def test_import_occurs_before_parent_rules_with_its_own_base_url():
    fetcher = Fetcher(
        {
            "https://example.com/css/main.css": '@import "nested/fonts.css"; .x{color:blue}',
            "https://example.com/css/nested/fonts.css": ".x{color:red;background:url(bg.png)}",
        }
    )
    sheets, diagnostics = asyncio.run(
        collect_stylesheets([{"href": "https://example.com/css/main.css", "text": None}], fetcher)
    )
    assert [s.url for s in sheets] == [
        "https://example.com/css/nested/fonts.css",
        "https://example.com/css/main.css",
    ]
    assert "bg.png" in sheets[0].text
    assert not any("@import" in s.text for s in sheets)
    assert not diagnostics


def test_disabled_owner_and_media_conditions_survive_capture():
    sheets, _ = asyncio.run(
        collect_stylesheets(
            [
                {"href": None, "text": ".x{color:red}", "disabled": True},
                {"href": None, "text": ".x{color:blue}", "media": "(max-width: 600px)"},
            ],
            Fetcher({}),
        )
    )
    assert sheets[0].text == "" and sheets[0].disabled is True
    assert sheets[0].raw_text == ".x{color:red}"
    assert "@media (max-width: 600px)" in sheets[1].text
    assert sheets[1].source_order == [1]


def test_inline_import_resolves_from_observed_page_and_nested_chain_retains_order():
    fetcher = Fetcher(
        {
            "https://example.com/base/first.css": '@import "second.css"; .x{color:green}',
            "https://example.com/base/second.css": ".x{color:red}",
        }
    )
    sheets, _ = asyncio.run(
        collect_stylesheets(
            [{"href": None, "text": '@import "first.css"; .x{color:blue}'}],
            fetcher,
            base_url="https://example.com/base/page",
        )
    )
    assert [s.url for s in sheets] == [
        "https://example.com/base/second.css",
        "https://example.com/base/first.css",
        "inline:0",
    ]
    assert not any("@import" in s.text for s in sheets)


def test_browser_cascade_matches_source_for_import_and_owner_conditions():
    files = {
        "https://example.com/main.css": (
            '@import "base.css" layer(brand) supports(display:grid) screen; .x{color:blue}'
        ),
        "https://example.com/base.css": ".x{color:red;padding:3px}",
    }
    records = [
        {"href": "https://example.com/main.css", "text": None},
        {"href": None, "text": ".x{color:green}", "media": "(max-width:600px)"},
        {"href": None, "text": ".x{color:pink}", "disabled": True},
    ]
    sheets, _ = asyncio.run(collect_stylesheets(records, Fetcher(files)))
    captured = (
        "".join("<style>" + s.text + "</style>" for s in sheets) + '<div class="x">Text</div>'
    )
    source = (
        '<link rel="stylesheet" href="https://example.com/main.css">'
        '<style media="(max-width:600px)">.x{color:green}</style>'
        '<style id="off">.x{color:pink}</style><div class="x">Text</div>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def route(r):
            text = files.get(r.request.url)
            if text is None:
                r.abort()
            else:
                r.fulfill(status=200, content_type="text/css", body=text)

        page.route("**/*", route)
        for width in (1440, 375):
            page.set_viewport_size({"width": width, "height": 800})
            page.set_content(source)
            page.eval_on_selector("#off", "e=>{e.sheet.disabled=true}")
            original = page.eval_on_selector(
                ".x", "e=>[getComputedStyle(e).color,getComputedStyle(e).padding]"
            )
            page.set_content(captured)
            actual = page.eval_on_selector(
                ".x", "e=>[getComputedStyle(e).color,getComputedStyle(e).padding]"
            )
            assert actual == original
        browser.close()


def test_rendered_snapshot_passes_page_base_to_inline_imports():
    from lumen_ingestion.capture.rendered import _snapshot_from_harvest

    fetcher = Fetcher({"https://example.com/base/theme.css": ".x{color:red}"})
    snapshot = asyncio.run(
        _snapshot_from_harvest(
            "https://example.com/",
            {
                "html": '<html><body><p class="x">Hello</p></body></html>',
                "shot": b"png",
                "final_url": "https://example.com/base/page",
                "data": {"sheets": [{"text": '@import "theme.css";', "href": None}]},
            },
            fetcher,
            [],
            fetched_at="2026-09-20T00:00:00Z",
        )
    )
    assert "https://example.com/base/theme.css" in [s.url for s in snapshot.stylesheets]


def test_stylesheet_evidence_round_trips_in_disposable_storage(workspace_id, design_storage):
    from lumen_ingestion.capture.snapshot import SiteSnapshot
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.site_snapshot import persist_site_snapshots, read_site_snapshot

    sheets, _ = asyncio.run(
        collect_stylesheets(
            [
                {"href": None, "text": ".x{color:red}", "disabled": True},
                {"href": None, "text": ".x{color:blue}", "media": "screen"},
            ],
            Fetcher({}),
        )
    )
    snapshot = SiteSnapshot(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        fetched_at="2026-09-20T00:00:00Z",
        tier="rendered",
        html="<p>x</p>",
        stylesheets=sheets,
    )
    job = IngestionJobStore(workspace_id=workspace_id).create(
        "website", {"url": snapshot.requested_url}
    )["job_id"]
    (ref,) = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=job, storage=design_storage
    )
    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=ref.snapshot_id
    )
    assert loaded.stylesheets[0].disabled is True
    assert loaded.stylesheets[0].raw_text == ".x{color:red}"
    assert loaded.stylesheets[1].source_order == (1,)
    assert loaded.stylesheets[1].media == "screen"


def test_active_import_traverses_cached_disabled_top_level_sheet():
    fetcher = Fetcher(
        {
            "https://example.com/a.css": '@import "b.css"; .a{}',
            "https://example.com/b.css": '@import "c.css"; .b{}',
            "https://example.com/c.css": ".c{color:red}",
        }
    )
    sheets, diagnostics = asyncio.run(
        collect_stylesheets(
            [
                {"href": "https://example.com/a.css", "text": None},
                {"href": "https://example.com/b.css", "text": None, "disabled": True},
            ],
            fetcher,
        )
    )
    assert any(".c{color:red}" in s.text for s in sheets)
    assert not diagnostics


def test_invalid_block_import_is_not_fetched_and_parse_error_does_not_abort():
    fetcher = Fetcher({"https://example.com/invalid.css": ".x{color:red}"})
    sheets, diagnostics = asyncio.run(
        collect_stylesheets(
            [{"href": None, "text": '@import "invalid.css" { color:red }\n .x{color:blue} }'}],
            fetcher,
            base_url="https://example.com/",
        )
    )
    assert fetcher.requested == []
    assert ".x{color:blue}" in "".join(s.text for s in sheets)
    assert diagnostics


def test_repeated_import_occurrences_retain_different_conditions_and_fetch_once():
    fetcher = Fetcher({"https://example.com/base.css": ".x{color:red}"})
    sheets, diagnostics = asyncio.run(
        collect_stylesheets(
            [
                {
                    "href": None,
                    "text": '@import "base.css" screen; @import "base.css" print; .x{color:blue}',
                }
            ],
            fetcher,
            base_url="https://example.com/",
        )
    )
    imported = [s for s in sheets if s.url.endswith("/base.css")]
    assert (
        len(imported) == 2
        and "@media screen" in imported[0].text
        and "@media print" in imported[1].text
    )
    assert fetcher.requested == ["https://example.com/base.css"]
    assert not diagnostics


def test_cycle_and_depth_bound_report_missing_rules_without_unbounded_fetch(monkeypatch):
    from lumen_ingestion.capture import stylesheets as module

    monkeypatch.setattr(module, "MAX_IMPORT_DEPTH", 2)
    fetcher = Fetcher(
        {
            f"https://example.com/{i}.css": f'@import "{i + 1}.css"; .x{i}{{color:red}}'
            for i in range(6)
        }
    )
    sheets, diagnostics = asyncio.run(
        collect_stylesheets([{"href": "https://example.com/0.css", "text": None}], fetcher)
    )
    assert len(fetcher.requested) == 3
    assert any("bounds" in d["message"] for d in diagnostics)
    assert any(".x2" in s.text for s in sheets)


def test_malformed_import_url_does_not_abort_valid_css():
    fetcher = Fetcher({})
    sheets, diagnostics = asyncio.run(
        collect_stylesheets(
            [{"href": None, "text": '@import "https://[bad/style.css"; .x{color:blue}'}],
            fetcher,
            base_url="https://example.com/",
        )
    )
    assert fetcher.requested == []
    assert ".x{color:blue}" in "".join(s.text for s in sheets)
    assert diagnostics


def test_browser_import_conditions_and_anonymous_layers_match_source():
    cases = [
        ('@import "base.css" supports(selector(.x));', ".x{padding:3px}"),
        (
            '@import "base.css" supports((display: grid) and (not (display: bogus)));',
            ".x{padding:5px}",
        ),
        (
            '@import "base.css" layer(one) print; '
            "@layer two{.x{color:blue}} @layer one{.x{color:red}}",
            ".x{padding:7px}",
        ),
        (
            '@import "base.css" layer; @import "base.css" layer;',
            '.x{color:red!important} @import "late.css"; .x{padding:3px}',
        ),
        (
            '@import "base.css" layer; @layer named{.x{color:green}}',
            ".x{color:red} @layer nested{.x{padding:4px}} .x{color:blue}",
        ),
    ]
    prepared = []
    for main, base in cases:
        files = {"https://example.com/main.css": main, "https://example.com/base.css": base}
        sheets, _ = asyncio.run(
            collect_stylesheets(
                [{"href": "https://example.com/main.css", "text": None}], Fetcher(files)
            )
        )
        prepared.append((main, base, files, sheets))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for main, base, files, sheets in prepared:

            def route(r, _request, files=files):
                if r.request.url in files:
                    r.fulfill(status=200, content_type="text/css", body=files[r.request.url])
                else:
                    r.abort()

            page.route("**/*", route)
            page.set_content(
                '<link rel="stylesheet" href="https://example.com/main.css">'
                '<div class="x">Text</div>'
            )
            original = page.eval_on_selector(
                ".x", "e=>[getComputedStyle(e).color,getComputedStyle(e).padding]"
            )
            page.set_content(
                "".join("<style>" + s.text + "</style>" for s in sheets)
                + '<div class="x">Text</div>'
            )
            actual = page.eval_on_selector(
                ".x", "e=>[getComputedStyle(e).color,getComputedStyle(e).padding]"
            )
            assert actual == original, (main, base, original, actual)
            page.unroute("**/*", route)
        browser.close()


def test_repeated_invalid_imports_have_bounded_diagnostics_and_keep_valid_rules():
    text = '@import "https://[bad/x.css"; ' * 400 + ".x{color:blue}"
    sheets, diagnostics = asyncio.run(
        collect_stylesheets([{"href": None, "text": text}], Fetcher({}))
    )
    assert len(diagnostics) <= 256
    assert any("truncated" in d["message"] for d in diagnostics)
    assert ".x{color:blue}" in "".join(s.text for s in sheets)
