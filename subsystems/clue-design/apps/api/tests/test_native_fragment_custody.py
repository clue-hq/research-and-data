"""Durable native dependency retention across registry, isolation and export maps."""
import pytest
from clue_storage import FsStorage

from test_fragment_repair import _mint_broken, _registry
from test_native_fragment_dependencies import HTML, DEPENDENCIES
from lumen_api.core import CoreClient
from lumen_api.fragments import FragmentRefused, set_web_fragment_status
from lumen_api.fragments.isolation import build_isolation_page, isolation_web_doc
from lumen_api.fragments.registry import read_web_fragment
from lumen_api.fragments.render import build_fragment_render_package_for_document, fragment_render_map


def test_native_repair_custody_and_raw_repair_refusal(tmp_path, _isolated_design_workspace):
    ws = _isolated_design_workspace
    storage = FsStorage(tmp_path / "blobs")
    original = _mint_broken(ws, storage)
    registry = _registry(ws, storage, tmp_path / "cache")
    result = registry.mint_repair(
        replaces=original["fragment_id"], html=HTML, css="", rung=2,
        note="offline native repair", native_dependencies=DEPENDENCIES,
    )
    fid = result["fragment_id"]
    assert result["status"] == "draft"
    loaded = read_web_fragment(storage, workspace_id=ws, fragment_id=fid)
    assert loaded.payload["native_dependencies"] == DEPENDENCIES
    set_web_fragment_status(workspace_id=ws, fragment_id=fid, status="approved")
    assert registry.resolve_insertable(fid)["render"]["native_dependencies"] == DEPENDENCIES
    package = build_fragment_render_package_for_document(
        storage, workspace_id=ws, web_doc=isolation_web_doc(fid),
    )
    assert package["schema_version"] == 2
    assert fragment_render_map(package, [fid])[fid]["native_dependencies"] == DEPENDENCIES
    core = CoreClient()
    isolated = build_isolation_page(core, loaded)
    assert 'data-lumen-tabs="true"' in isolated.html
    assert "lumen-runtime v2" in isolated.html
    with pytest.raises(FragmentRefused, match="raw HTML/CSS repair"):
        registry.mint_repair(replaces=fid, html=loaded.html, css=".changed{color:red}",
                             rung=1, note="unsupported raw change")
    assert read_web_fragment(storage, workspace_id=ws, fragment_id=fid).payload == loaded.payload
