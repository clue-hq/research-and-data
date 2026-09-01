"""DurableLogoFamilyCache: workspace-scoped get/put, custody-probed reads,
force-refresh overwrite convergence.

The durable half of the vendor-first logo family (Task 7). The dispatch's cache seam is
duck-typed (`get(site) -> LogoFetchOutcome | None` / `put(site, outcome)`), so these tests
drive the real object against the real `design_logo_family` row and the real design blob
store rather than a double: what is worth pinning here is that the row and the BYTES agree,
and that neither travels between tenants.

DB-backed, with the suite's per-test workspace + disposable `FsStorage`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from clue_storage import FsStorage

from lumen_api.design_store import DesignBlobStore
from lumen_api.main import create_app


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def app(tmp_path: Path, design_storage: FsStorage):
    """The app purely as a composition root for `app.state.storage` — these tests exercise the
    capability object directly (it is fleet-side work that holds no request), so no client."""
    return create_app(tmp_path / "engine-cache", storage=design_storage)


@pytest.fixture()
def design_blob_store(app) -> DesignBlobStore:
    from conftest import make_blob_store

    return make_blob_store(app)


@pytest.fixture()
def other_workspace_blob_store(app) -> DesignBlobStore:
    """A SECOND tenant on the same backend (`ensure_workspace=True` creates its row on first
    use), which is what makes the isolation assertion a real cross-tenant read."""
    return DesignBlobStore(app.state.storage, f"ws_test_other_{uuid.uuid4().hex[:12]}")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _outcome(site="https://acme.com/"):
    from lumen_agent.tools.logo_fetch import LogoFetchOutcome, PreparedLogo

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
        b'viewBox="0 0 10 10"><rect width="10" height="10" fill="#123"/></svg>'
    )
    prepared = PreparedLogo(
        cell="light_lockup",
        source="brandfetch",
        asset_id="asset_ing_cafedeadbeef0000",
        label="Acme logo (light_lockup)",
        body=svg,
        content_type="image/svg+xml",
        provenance={
            "created_by": "brandfetch",
            "source_label": "brandfetch",
            "confidence": 0.9,
        },
        source_ref={"kind": "vendor", "url": "https://a/x.svg", "captured_at": "t"},
        evidence={"cell": "light_lockup", "source": "brandfetch"},
    )
    return LogoFetchOutcome(
        status="ok",
        site=site,
        company="Acme",
        prepared=[prepared],
        cells={"light_lockup": "brandfetch"},
    )


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


def test_put_then_get_round_trips_the_family(design_blob_store: DesignBlobStore) -> None:
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    cache.put("https://acme.com/", _outcome())
    got = cache.get("https://www.acme.com/pricing")  # registrable-domain keyed
    assert got is not None
    assert got.cells == {"light_lockup": "brandfetch"}
    assert got.prepared[0].body.startswith(b"<svg")
    assert got.prepared[0].provenance["created_by"] == "brandfetch"


def test_get_unknown_domain_is_none_and_put_converges(
    design_blob_store: DesignBlobStore,
) -> None:
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    assert cache.get("https://nobody.example/") is None
    cache.put("https://acme.com/", _outcome())
    cache.put("https://acme.com/", _outcome())  # idempotent overwrite, no error
    assert cache.get("https://acme.com/") is not None


def test_workspace_isolation_is_fail_closed(
    design_blob_store: DesignBlobStore,
    other_workspace_blob_store: DesignBlobStore,
) -> None:
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    DurableLogoFamilyCache(blobs=design_blob_store).put("https://acme.com/", _outcome())
    foreign = DurableLogoFamilyCache(blobs=other_workspace_blob_store)
    assert foreign.get("https://acme.com/") is None
