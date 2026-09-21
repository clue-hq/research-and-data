"""Standalone offline tests; never collect the API's database fixtures."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import tinycss2
from lumen_api.fragments import editor_preflight as preflight

GUARD = ':not(:where([data-lumen-fragment="true"] *))'
WORKTREE = Path(__file__).resolve().parents[4]


def test_subject_guards_preserve_every_other_source_byte():
    css = "/* keep */ h3 /* after */,\n::before { content: 'x'; /* unchanged */ }\n"
    assert preflight.qualify_preflight(css) == (
        "/* keep */ h3"
        + GUARD
        + " /* after */,\n"
        + GUARD
        + "::before { content: 'x'; /* unchanged */ }\n"
    )


def test_selector_functions_and_nested_supports_keep_subject_and_order():
    css = (
        "@supports (display: grid) { :where(select:is([multiple], [size])) "
        "optgroup option {padding:20px!important} }"
    )
    assert preflight.qualify_preflight(css) == css.replace("option {", "option" + GUARD + " {")


@pytest.mark.parametrize(
    "css",
    [
        '@import "other.css";',
        "@layer base {h3{color:red}}",
        "@media all {h3{color:red}}",
        "@keyframes x {to{opacity:0}}",
        "h3{} garbage",
        "h3::before > p{color:red}",
        'h3{content:"</style>"}',
        "h3\x00{color:red}",
        "h3, {color:red}",
    ],
)
def test_unsupported_grammar_refuses_the_entire_transform(css):
    with pytest.raises(preflight.PreflightError):
        preflight.qualify_preflight(css)


def test_transform_has_explicit_input_and_selector_bounds():
    with pytest.raises(preflight.PreflightError):
        preflight.qualify_preflight("/*" + "x" * preflight.MAX_PREFLIGHT_BYTES + "*/")
    with pytest.raises(preflight.PreflightError):
        preflight.qualify_preflight(
            ",".join("h3" for _ in range(preflight.MAX_SELECTORS + 1)) + "{color:red}"
        )


def test_pinned_resource_and_runtime_have_exact_provenance():
    source = preflight.preflight_source()
    assert hashlib.sha256(source.encode()).hexdigest() == preflight.PREFLIGHT_SHA256
    manifest = json.loads(preflight.resource_path("tailwind-preflight-4.3.3.json").read_text())
    assert manifest["version"] == preflight.TAILWIND_VERSION == "4.3.3"
    assert manifest["preflight_sha256"] == preflight.PREFLIGHT_SHA256
    assert manifest["browser_sha256"] == preflight.BROWSER_SHA256
    assert "MIT License" in preflight.resource_path("LICENSE.tailwindcss").read_text()
    assert not preflight.supported_runtime(b"unknown runtime")
    assert preflight.BROWSER_SRI.startswith("sha256-")


def test_resource_tampering_fails_closed(monkeypatch, tmp_path):
    bad = tmp_path / "bad.css"
    bad.write_text("h3{color:red}")
    original = preflight.resource_path
    monkeypatch.setattr(
        preflight, "resource_path", lambda name: bad if name.endswith(".css") else original(name)
    )
    with pytest.raises(preflight.PreflightError, match="digest"):
        preflight.preflight_source()


def test_compiler_prefix_keeps_original_layer_and_import_order():
    text = preflight.preflight_compiler_prefix()
    assert text.startswith("@layer theme, base, components, utilities;")
    assert text.index('@import "tailwindcss/theme.css"') < text.index("@layer base {")
    assert text.index("@layer base {") < text.index('@import "tailwindcss/utilities.css"')
    assert "tailwindcss/preflight" not in text
    assert "@scope" not in text
    assert text.count(GUARD) == 77
    assert preflight.preflight_source() in text.replace(GUARD, "")


def test_canonical_compiler_location_keeps_large_source_css_opaque():
    from lumen_api.fragments.editor_compiler import editor_compiler_block

    css = "@theme { --color-primary: red; }"
    html = (
        '<!doctype html><html><head><style type="text/tailwindcss">'
        + css
        + "</style><style>"
        + "x" * 100_000
        + "</style></head><body></body></html>"
    )
    block = editor_compiler_block(html)
    assert html[block.content_start : block.content_end] == css
    assert html[block.element_end :].startswith("<style>")


@pytest.mark.parametrize(
    "html",
    [
        '<html><head></head><body><style type="text/tailwindcss">x</style></body></html>',
        '<html><head><script>"<style type="text/tailwindcss">x</style>"</script></head></html>',
        '<html><head><style type="text/tailwindcss">x</style>'
        '<style type="text/tailwindcss">y</style></head></html>',
    ],
)
def test_noncanonical_compiler_location_refuses(html):
    from lumen_api.fragments.editor_compiler import EditorCompilerError, editor_compiler_block

    with pytest.raises(EditorCompilerError):
        editor_compiler_block(html)


def _runtime():
    assert os.environ.get("CLUE_DATABASE_URL"), "explicit disposable DSN required even offline"
    assert os.environ.get("LUMEN_EMBEDDED_FLEET_WORKER") == "0"
    runtime = WORKTREE / "apps/frontend/node_modules/@tailwindcss/browser/dist/index.global.js"
    assert runtime.is_file(), "existing local runtime required; never download during a test"
    value = runtime.read_bytes()
    assert preflight.supported_runtime(value), "this test must use the pinned upstream runtime"
    return value.decode()


def _tokens(items):
    out = []
    for t in items:
        if t.type in ("whitespace", "comment"):
            continue
        if t.type == "function":
            out.append((t.type, t.name, _tokens(t.arguments)))
        elif hasattr(t, "content"):
            out.append((t.type, _tokens(t.content)))
        else:
            out.append((t.type, getattr(t, "value", None), getattr(t, "unit", None)))
    return out


@pytest.mark.parametrize("transport", ["external", "inline"])
@pytest.mark.parametrize(
    "override",
    [
        "",
        "@layer base {img{display:inline} h3{font-weight:500}}",
        "@layer base {img{display:inline!important} [hidden]{display:block!important}}",
        "@layer base {:where(img){display:inline}}",
        "@layer base.native {img{display:inline!important}[hidden]{display:block!important}}",
        "@layer utilities {img{display:inline!important}[hidden]{display:block!important}}",
    ],
)
def test_real_browser_keeps_native_cascade_and_fragment_ua_defaults(transport, override):
    from playwright.sync_api import sync_playwright

    runtime = _runtime()
    fields = [
        "fontSize",
        "fontFamily",
        "fontWeight",
        "lineHeight",
        "margin",
        "padding",
        "border",
        "display",
        "backgroundColor",
        "color",
        "boxSizing",
        "maxWidth",
        "verticalAlign",
    ]
    element = (
        '<h3 id="P-h3">Heading</h3><button id="P-button">Button</button>'
        '<img id="P-img"><span id="P-hidden" hidden>Hidden</span>'
        '<input id="P-file" type="file"><div id="P-pseudo"></div>'
    )
    native = element.replace("P-", "native-") + '<div id="native-p7" class="p-7 bg-primary"></div>'
    source = (
        element.replace("P-", "source-")
        + '<div data-lumen-fragment="true"><h3 id="source-nested">Nested</h3></div>'
    )
    context = (
        "source-context{all:initial;display:block;font:18px/1.4 Arial} "
        '#source-pseudo::before,#native-pseudo::before{content:"x"}'
    )
    raw = (
        '<!doctype html><html><head><style type="text/tailwindcss">'
        "@theme {--color-primary:#123456;}</style>RUNTIME<style>"
        + context
        + "</style><style>"
        + override
        + "</style></head><body>"
        + native
        + '<div data-lumen-fragment="true"><source-context>'
        + source
        + "</source-context></div></body></html>"
    )
    read = (
        '() => Object.fromEntries([...document.querySelectorAll("[id]")].map(e=>{'
        "const s=getComputedStyle(e);"
        "return [e.id,Object.fromEntries(FIELDS.map(k=>[k,s[k]]))]}))"
    ).replace("FIELDS", json.dumps(fields))
    values = {}
    compiled = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for mode in ("source", "before", "after"):
            page = browser.new_page()
            page.route(
                "**/*",
                lambda route: (
                    route.fulfill(content_type="application/javascript", body=runtime)
                    if route.request.url == "https://runtime.invalid/tailwind.js"
                    else route.abort()
                ),
            )
            if mode == "source":
                html = (
                    "<!doctype html><style>"
                    + context
                    + "</style><source-context>"
                    + source
                    + "</source-context>"
                )
            else:
                html = raw
                if mode == "after":
                    html = html.replace(
                        '<style type="text/tailwindcss">',
                        '<style type="text/tailwindcss">' + preflight.preflight_compiler_prefix(),
                        1,
                    )
                if transport == "external":
                    html = html.replace(
                        "RUNTIME", '<script src="https://runtime.invalid/tailwind.js"></script>'
                    )
                else:
                    html = html.replace("RUNTIME", "").replace(
                        "</head>", "<script>" + runtime + "</script></head>"
                    )
            page.set_content(html)
            if mode != "source":
                page.wait_for_function(
                    '[...document.querySelectorAll("head > style")].some(e=>'
                    'e.textContent.startsWith("/*! tailwindcss") && '
                    'e.textContent.includes(".p-7"))'
                )
                compiled[mode] = next(
                    s
                    for s in page.locator("head > style").all_text_contents()
                    if s.startswith("/*! tailwindcss")
                )
            values[mode] = page.evaluate(read)
            page.close()
        browser.close()
    assert {k: v for k, v in values["before"].items() if k.startswith("native-")} == {
        k: v for k, v in values["after"].items() if k.startswith("native-")
    }
    if not override:
        assert values["source"] == {
            k: v for k, v in values["after"].items() if k.startswith("source-")
        }
        assert values["before"]["source-h3"] != values["source"]["source-h3"]
        assert _tokens(tinycss2.parse_component_value_list(compiled["before"])) == _tokens(
            tinycss2.parse_component_value_list(compiled["after"].replace(GUARD, ""))
        )


@pytest.mark.parametrize("value", [[], {"version": "different"}])
def test_provenance_shape_or_version_drift_refuses(monkeypatch, tmp_path, value):
    bad = tmp_path / "manifest.json"
    bad.write_text(json.dumps(value))
    original = preflight.resource_path
    monkeypatch.setattr(
        preflight, "resource_path", lambda name: bad if name.endswith(".json") else original(name)
    )
    with pytest.raises(preflight.PreflightError):
        preflight.preflight_source()


def _html(
    body='<div class="lumen-fragment" data-lumen-fragment="true"><h3>Source</h3></div>',
    *,
    compiler="@theme {}",
    script="",
):
    return (
        '<!doctype html><html><head><style type="text/tailwindcss">'
        + compiler
        + "</style>\n"
        + script
        + "<style>/* unrelated source CSS */</style></head><body>"
        + body
        + "</body></html>"
    )


def test_external_runtime_is_pinned_with_sri_without_rewriting_markup():
    raw = _html(script='<script src="/vendor/tailwind-browser.js"></script>')
    result, diagnostics = preflight.qualify_fragment_preflight(
        raw, runtime_src="/vendor/tailwind-browser.js"
    )
    assert preflight.preflight_compiler_prefix() in result
    assert 'integrity="' + preflight.BROWSER_SRI + '" crossorigin="anonymous"' in result
    assert result.split("</head>", 1)[1] == raw.split("</head>", 1)[1]
    assert not diagnostics
    assert preflight.qualify_fragment_preflight(
        result, runtime_src="/vendor/tailwind-browser.js"
    ) == (result, [])


def test_inline_runtime_unknown_bytes_keeps_original_input_and_warns():
    raw = _html()
    result, diagnostics = preflight.qualify_fragment_preflight(raw, runtime_bytes=b"unknown")
    assert result == raw
    assert diagnostics[0]["code"] == "fragment.editor_preflight_runtime_unsupported"


def test_native_only_or_marker_text_does_not_activate_the_hook():
    raw = _html(body='<h3>data-lumen-fragment="true"</h3>')
    assert preflight.qualify_fragment_preflight(raw, runtime_bytes=b"unknown") == (raw, [])


@pytest.mark.parametrize(
    "compiler,script",
    [
        ('@import "tailwindcss";', '<script src="/vendor/tailwind-browser.js"></script>'),
        ("@theme {}", '<script src="/other.js"></script>'),
        ("@theme {}", '<script defer src="/vendor/tailwind-browser.js"></script>'),
    ],
)
def test_unowned_import_or_runtime_shape_stays_byte_identical(compiler, script):
    raw = _html(compiler=compiler, script=script)
    changed, diagnostics = preflight.qualify_fragment_preflight(
        raw, runtime_src="/vendor/tailwind-browser.js"
    )
    assert changed == raw
    assert diagnostics and diagnostics[0]["severity"] == "warning"


@pytest.mark.parametrize(
    "sandbox,cross_origin,cors,tamper,expected",
    [
        (False, False, False, False, True),
        (False, True, False, False, False),
        (True, False, False, False, False),
        (True, False, True, False, True),
        (True, True, True, False, True),
        (True, False, True, True, False),
    ],
)
def test_external_sri_enforces_bytes_in_real_sandboxed_srcdoc(
    sandbox,
    cross_origin,
    cors,
    tamper,
    expected,
):
    import html as html_module

    from playwright.sync_api import sync_playwright

    runtime = _runtime()
    url = (
        "https://cdn.invalid" if cross_origin else "https://editor.invalid"
    ) + "/vendor/tailwind-browser.js"
    raw = _html(script='<script src="' + url + '"></script>').replace(
        "</body>", '<div id="native-proof" class="p-7">Native</div></body>'
    )
    rendered, diagnostics = preflight.qualify_fragment_preflight(raw, runtime_src=url)
    assert not diagnostics
    markup = (
        (
            '<!doctype html><iframe sandbox="allow-scripts" srcdoc="'
            + html_module.escape(rendered, quote=True)
            + '"></iframe>'
        )
        if sandbox
        else rendered
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def route_handler(route):
            if route.request.url == "https://editor.invalid/":
                return route.fulfill(content_type="text/html", body=markup)
            if route.request.url == url:
                # Playwright injects ACAO automatically when absent. Explicit denial
                # is essential: otherwise a missing deployment header falsely passes.
                return route.fulfill(
                    content_type="application/javascript",
                    body=runtime + ("\n/* changed */" if tamper else ""),
                    headers={"access-control-allow-origin": "*" if cors else ""},
                )
            return route.abort()

        page.route("**/*", route_handler)
        page.goto("https://editor.invalid/", wait_until="networkidle")
        frame = page.frames[1] if sandbox else page.main_frame
        compiled = frame.evaluate(
            '[...document.querySelectorAll("style")].some(e=>'
            'e.textContent.startsWith("/*! tailwindcss"))'
        )
        assert compiled is expected
        if expected:
            assert (
                frame.eval_on_selector("#native-proof", "e=>getComputedStyle(e).padding") == "28px"
            )
        browser.close()


def _agent_render_function(runtime_path):
    """Compile the actual method without importing application/DB composition roots."""
    import ast
    import logging
    from types import SimpleNamespace

    path = WORKTREE / "subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py"
    tree = ast.parse(path.read_text())
    method = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_render_page_html"
    )
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    namespace = {
        "Path": Path,
        "os": os,
        "logger": logging.getLogger("offline-test"),
        "TAILWIND_RUNTIME_MARKER": "data-lumen-tailwind-runtime",
        "_TAILWIND_RUNTIME_ENV": "LUMEN_TAILWIND_RUNTIME",
        "_TAILWIND_RUNTIME_CANDIDATES": (),
        "tailwind_runtime_path": lambda root: runtime_path,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[])),
            str(path),
            "exec",
        ),
        namespace,
    )
    raw = _html()
    subject = SimpleNamespace(
        core=SimpleNamespace(web_render=lambda *a, **kw: {"html": raw}),
        web_doc={},
        page_id="home",
        asset_base_url=None,
        config=SimpleNamespace(repo_root=str(WORKTREE), brand_kit=None),
        _font_face_css=lambda: "",
        _fragment_render_map=lambda: {},
        _fragment_css=lambda: "",
        _fragment_diagnostics=lambda: [],
    )
    return namespace["_render_page_html"](subject), raw, tree


@pytest.mark.parametrize("kind", ["supported", "unsupported", "missing"])
def test_actual_agent_inline_method_uses_once_read_bytes_and_blocks_unverified_review(kind):
    import ast
    from types import SimpleNamespace

    class Runtime:
        calls = 0

        def read_bytes(self):
            self.calls += 1
            return _runtime().encode() if kind == "supported" else b"/* unsupported runtime */"

    runtime = Runtime() if kind != "missing" else None
    (rendered, diagnostics, unsettled), raw, tree = _agent_render_function(runtime)
    assert unsettled is (kind != "supported")
    if runtime:
        assert runtime.calls == 1
    if kind == "supported":
        assert preflight.preflight_compiler_prefix() in rendered
    elif kind == "unsupported":
        assert preflight.preflight_compiler_prefix() not in rendered
        assert diagnostics[0]["code"] == "fragment.editor_preflight_runtime_unsupported"
        assert (
            raw.split('<style type="text/tailwindcss">', 1)[1].split("</style>", 1)[0] in rendered
        )
    # Execute the real review acceptance condition and public flag branches.
    condition = next(
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "settled" for t in n.targets)
    )
    assert eval(
        compile(ast.Expression(condition), "<review-gate>", "eval"),
        {"critique": SimpleNamespace(settled=True), "tailwind_missing": unsettled},
    ) is (not unsettled)
    branches = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Name)
        and n.test.id == "tailwind_missing"
    ]
    for branch in branches:
        state = {"tailwind_missing": unsettled, "diagnostics": diagnostics, "result": {}}
        exec(compile(ast.Module(body=[branch], type_ignores=[]), "<public-flag>", "exec"), state)
        expected = (
            {}
            if kind == "supported"
            else {
                "tailwind_runtime_unverified"
                if kind == "unsupported"
                else "tailwind_runtime_missing": True
            }
        )
        assert state["result"] == expected


def test_core_applies_external_hook_and_defers_inline_without_changing_delivery(monkeypatch):
    from lumen_api.core import CoreClient

    raw = _html(script='<script src="/vendor/tailwind-browser.js"></script>')
    core = object.__new__(CoreClient)
    monkeypatch.setattr(core, "_run", lambda request: {"html": raw, "diagnostics": []})
    external = core.web_render({}, "home", tailwind_runtime_src="/vendor/tailwind-browser.js")
    assert preflight.BROWSER_SRI in external["html"]
    assert core.web_render({}, "home")["html"] == raw
    assert core.web_render({}, "home", mode="delivery")["html"] == raw


@pytest.mark.parametrize("transport", ["external", "inline"])
def test_compiler_imports_never_escape_to_network_and_keep_native_tokens(transport):
    """Real navigation catches native speculative imports that set_content misses."""
    from playwright.sync_api import sync_playwright

    runtime = _runtime()
    url = "https://proof.invalid/vendor/tailwind-browser.js"
    raw = _html(
        script=f'<script src="{url}"></script>' if transport == "external" else "",
        compiler="@theme {--color-primary:#123456;}",
    ).replace(
        "</body>",
        '<div id="native-tokens" class="p-7 bg-primary text-red-500 rounded-lg '
        'font-mono text-2xl">Native utilities</div></body>',
    )
    kwargs = (
        {"runtime_src": url} if transport == "external" else {"runtime_bytes": runtime.encode()}
    )
    qualified, diagnostics = preflight.qualify_fragment_preflight(raw, **kwargs)
    assert not diagnostics
    measured = {}
    requests = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, html in (("baseline", raw), ("qualified", qualified)):
            if transport == "inline":
                html = html.replace("</head>", "<script>" + runtime + "</script></head>")
            page = browser.new_page()
            unowned = []

            def handle(route, _request, page_html=html, blocked=unowned):
                if route.request.url == "https://proof.invalid/":
                    return route.fulfill(content_type="text/html", body=page_html)
                if transport == "external" and route.request.url == url:
                    return route.fulfill(
                        content_type="application/javascript",
                        body=runtime,
                        headers={"access-control-allow-origin": "*"},
                    )
                blocked.append(route.request.url)
                return route.abort()

            page.route("**/*", handle)
            page.goto("https://proof.invalid/", wait_until="networkidle")
            measured[name] = page.eval_on_selector(
                "#native-tokens",
                """e => {
                  const s=getComputedStyle(e);
                  return Object.fromEntries(['padding','color','backgroundColor',
                    'borderRadius','fontFamily','fontSize'].map(k=>[k,s[k]]));
                }""",
            )
            requests[name] = unowned
            page.close()
        browser.close()
    assert measured["qualified"] == measured["baseline"]
    assert measured["qualified"]["padding"] == "28px"
    assert measured["qualified"]["backgroundColor"] == "rgb(18, 52, 86)"
    assert measured["qualified"]["fontSize"] == "24px"
    assert requests == {"baseline": [], "qualified": []}
