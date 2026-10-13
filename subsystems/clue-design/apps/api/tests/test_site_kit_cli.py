"""lumen_api.site_kit_cli: one runner for site-kit's CLIs, JSON in, JSON out (Lane B Task 3)."""

from __future__ import annotations

import json

import pytest

from lumen_api.site_kit_cli import (
    SITE_KIT_DIR,
    SiteKitCliError,
    _child_env,
    build_site_catalog,
    compile_section_source,
    run_site_kit_bundle,
    section_toolchain_missing,
    site_kit_toolchain_missing,
    validate_site_files,
)
from site_kit_support import ensure_site_kit_dist

FIXTURES = SITE_KIT_DIR / "test" / "fixtures"


def _brand() -> dict:
    return {
        "slug": "garner",
        "kit": json.loads((FIXTURES / "kit.json").read_text()),
        "fonts": [],
        "assets": {},
        "clones": {},
    }


def test_the_validator_answers_with_its_own_errors() -> None:
    ensure_site_kit_dist()
    result = validate_site_files({"pages": {}, "shell": None}, _brand(), {})
    assert result["valid"] is False
    assert any(error.startswith("page.json: does not exist yet") for error in result["errors"])


def test_the_validator_reads_page_files_given_as_text() -> None:
    ensure_site_kit_dist()
    result = validate_site_files({"pages": {"/": "{ not json"}, "shell": "{}"}, _brand(), {})
    assert result["valid"] is False and result["errors"]


def test_the_catalog_comes_back_as_files() -> None:
    ensure_site_kit_dist()
    files = build_site_catalog(_brand(), "Garner Health")
    assert {"catalog/index.md", "catalog/sections.md", "brand/brand.md"} <= set(files)
    assert files["brand/brand.md"].startswith("# Brand: Garner Health")


def test_a_catalog_answer_without_files_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import site_kit_cli

    monkeypatch.setattr(site_kit_cli, "run_site_kit_bundle", lambda *args, **kwargs: {"something": 1})
    with pytest.raises(SiteKitCliError) as bad_output:
        build_site_catalog(_brand(), "Garner Health")
    assert bad_output.value.code == "site_kit.bad_output"


def test_a_missing_node_and_a_missing_bundle_are_typed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SiteKitCliError) as missing_node:
        run_site_kit_bundle("validate-site.mjs", {}, node_bin="definitely-not-node")
    assert missing_node.value.code == "site_kit.toolchain_missing"
    monkeypatch.setenv("LUMEN_SITE_KIT_DIST", str(tmp_path))
    with pytest.raises(SiteKitCliError) as missing_bundle:
        run_site_kit_bundle("validate-site.mjs", {}, what="the site validator")
    assert missing_bundle.value.code == "site_kit.cli_missing"
    assert missing_bundle.value.detail.startswith("the site validator is not built")
    assert site_kit_toolchain_missing() is not None


def test_node_runs_with_a_stripped_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "secret")
    env = _child_env()
    assert set(env) <= {"PATH", "HOME", "TMPDIR"}
    assert "secret" not in json.dumps(env)


def test_lane_as_validator_runs_through_the_shared_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import site_doc_validate

    seen: list[tuple[str, str]] = []

    def fake_bundle(bundle, payload, *, timeout_s, node_bin, what):
        seen.append((bundle, what))
        return {"valid": False, "errors": ["page.json: x"]}

    monkeypatch.setattr(site_doc_validate, "run_site_kit_bundle", fake_bundle)
    errors = site_doc_validate.run_site_validator({"pages": {}, "shell": None}, {}, section_schemas={}, site_images=[])
    assert errors == ["page.json: x"] and seen == [("validate-site.mjs", "the site validator")]


EXAMPLE = (SITE_KIT_DIR / "test" / "fixtures" / "section-example.tsx").read_text()


@pytest.mark.skipif(section_toolchain_missing() is not None, reason=f"section toolchain: {section_toolchain_missing()}")
def test_a_section_compiles_through_the_cli() -> None:
    answer = compile_section_source(name="QuoteBand", source=EXAMPLE, brand=_brand())
    assert answer["ok"] is True and "export" in answer["moduleJs"]
    refused = compile_section_source(name="QuoteBand", source=EXAMPLE.replace("text-ink-secondary", "text-red-500"), brand=_brand())
    assert refused["ok"] is False and any('class "text-red-500"' in error for error in refused["errors"])
