"""design_record_site_section (Lane B Task 14, Contract 4): one compiled agent section, recorded
with the props schema its own module declares, per workspace, never publicly served."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.toolbelt.site_sections import SiteSectionRefused

MODULE = 'import { z } from "zod";\nexport const schema = z.object({ id: z.string(), surface: z.string() });\nexport function render() { return null; }\n'
SOURCE = "export const schema = z.object({ id: z.string(), surface: z.string() });\n"
CSS = ".px-6{padding-inline:1.5rem}"
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


@pytest.fixture()
def client(tmp_path: Path, design_storage):
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _record(client, workspace_id: str, **overrides):
    body = {"name": "StepsBand", "source": SOURCE, "module_js": MODULE, "css": CSS, **overrides}
    return client.app.state.design_tools.invoke(
        "design_record_site_section", body, workspace_id=workspace_id, actor="agent", actor_id="run_sections_1"
    )


def test_a_section_is_recorded_with_its_own_schema(client, workspace_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import site_render

    read: list[str] = []
    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: read.append(module_js) or SCHEMA)
    result = _record(client, workspace_id)
    digest = hashlib.sha256(MODULE.encode()).hexdigest()
    assert result.references == {
        "digest": digest, "name": "StepsBand",
        "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "css_sha256": hashlib.sha256(CSS.encode()).hexdigest(),
    }
    assert read == [MODULE]
    (row,) = HybridRepository(workspace_id).get_site_sections([digest])
    assert row["props_schema"] == SCHEMA and row["created_by_run_id"] == "run_sections_1"
    blobs = make_blob_store(client.app)
    assert blobs.read(digest).decode() == MODULE
    assert blobs.read(row["css_sha256"]).decode() == CSS
    # The same module again records nothing new.
    assert _record(client, workspace_id).references["digest"] == digest
    assert len(HybridRepository(workspace_id).list_latest_site_sections()) == 1


def test_a_module_whose_schema_cannot_be_read_is_refused_and_nothing_is_recorded(
    client, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_api import site_render

    def refuse(module_js, **_):
        raise site_render.SiteRenderError("render.failed", "`schema` must be a zod object")

    monkeypatch.setattr(site_render, "read_section_schema", refuse)
    with pytest.raises(SiteSectionRefused) as refused:
        _record(client, workspace_id)
    assert refused.value.code == "render.failed" and "zod object" in refused.value.message
    assert HybridRepository(workspace_id).list_latest_site_sections() == []


def test_a_bad_section_name_is_refused_before_anything_runs(client, workspace_id: str) -> None:
    from pydantic import ValidationError

    # The invoker validates the body against the input model before any check runs
    # (clue_toolbelt/invoker.py:187), so a bad name never reaches the schema read or the store.
    with pytest.raises(ValidationError):
        _record(client, workspace_id, name="stepsBand")


def test_the_section_loader_serves_what_a_site_pins_and_refuses_the_rest(
    client, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_api import site_render
    from lumen_api.site_doc_inputs import load_section_modules
    from lumen_api.site_workspace_view import load_site_section_modules

    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: SCHEMA)
    digest = _record(client, workspace_id).references["digest"]
    repo, blobs = HybridRepository(workspace_id), make_blob_store(client.app)
    assert client.app.state.site_section_loader is load_site_section_modules
    (module,) = load_site_section_modules(repo, blobs, {"StepsBand": digest})
    assert (module.name, module.digest, module.module_js, module.css, module.props_schema) == (
        "StepsBand", digest, MODULE, CSS, SCHEMA)
    # Lane A's pin check accepts it: the bytes hash to the pinned digest.
    assert load_section_modules(load_site_section_modules, repo, blobs, {"agent_sections": {"StepsBand": digest}})
    for pins in ({"StepsBand": "0" * 64}, {"OtherName": digest}):
        with pytest.raises(site_render.SiteRenderError) as missing:
            load_site_section_modules(repo, blobs, pins)
        assert missing.value.code == site_render.SECTION_MODULE_MISSING

