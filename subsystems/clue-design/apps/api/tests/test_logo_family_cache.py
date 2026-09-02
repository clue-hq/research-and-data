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


def _alternative():
    """One vetted asset that is not a cell — a vendor icon — shaped like a cell."""
    from lumen_agent.tools.logo_fetch import PreparedLogo

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "00000049454e44ae426082"
    )
    return PreparedLogo(
        cell="unclassified",
        source="brandfetch",
        asset_id="asset_ing_0badc0ffee000000",
        label="Acme logo (alternative: icon)",
        body=png,
        content_type="image/png",
        provenance={
            "created_by": "brandfetch",
            "source_label": "brandfetch",
            "confidence": 0.9,
        },
        source_ref={"kind": "website", "url": "https://a/icon.png", "captured_at": "t"},
        evidence={
            "cell": "unclassified",
            "source": "brandfetch",
            "vendor_type": "icon",
            "competed_for": None,
            "reason": "vendor type 'icon' is not a family cell",
        },
    )


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
        alternatives=[_alternative()],
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
    # The alternatives are part of the family: they round-trip with it.
    assert [a.cell for a in got.alternatives] == ["unclassified"]
    alternative = got.alternatives[0]
    assert alternative.body == _alternative().body
    assert alternative.label == "Acme logo (alternative: icon)"
    assert alternative.evidence["reason"].startswith("vendor type 'icon'")


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


def test_a_cell_whose_bytes_left_custody_makes_the_whole_family_a_miss(
    design_blob_store: DesignBlobStore, app
) -> None:
    """The row can outlive the bytes (a moved backend root, a restore without the object store,
    an out-of-band delete), and a row-level probe would call that healthy. The cache probes
    CUSTODY instead, so a family whose bytes are gone is reported as a MISS and the next dispatch
    refetches — half a 2x2 is not the family that was asked for."""
    import hashlib
    import os

    from clue_design.storage import design_storage_key
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    outcome = _outcome()
    cache.put("https://acme.com/", outcome)
    assert cache.get("https://acme.com/") is not None

    # Remove the bytes out-of-band (the row survives; custody is no longer READABLE) — the
    # suite's established idiom, `test_asset_custody.py`'s key-resolved unlink.
    digest = hashlib.sha256(outcome.prepared[0].body).hexdigest()
    key = design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    Path(app.state.storage._root).joinpath(*key.split("/")).unlink()
    assert design_blob_store.exists(digest), "the row still claims custody"

    assert cache.get("https://acme.com/") is None


def test_an_alternative_whose_bytes_left_custody_makes_the_whole_family_a_miss(
    design_blob_store: DesignBlobStore, app
) -> None:
    """Same rule as a cell: half a family is not the family the dispatch asked for, and an
    alternative the agent cannot place is not a hit either."""
    import hashlib
    import os

    from clue_design.storage import design_storage_key
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    outcome = _outcome()
    cache.put("https://acme.com/", outcome)
    assert cache.get("https://acme.com/") is not None

    digest = hashlib.sha256(outcome.alternatives[0].body).hexdigest()
    key = design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    Path(app.state.storage._root).joinpath(*key.split("/")).unlink()

    assert cache.get("https://acme.com/") is None


def test_cache_errors_degrade_to_a_miss_and_never_raise(
    design_blob_store: DesignBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is an OPTIMIZATION, never a gate: the fetch path must survive a cache that is
    entirely broken. A read error is a miss; a write error is logged and swallowed, because the
    turn already holds the family it was going to store."""
    from clue_design import logo_family_cache as dal
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(dal, "get_logo_family", boom)
    monkeypatch.setattr(dal, "upsert_logo_family", boom)
    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    cache.put("https://acme.com/", _outcome())  # must not raise
    assert cache.get("https://acme.com/") is None  # a read error is a miss


def test_put_with_nothing_prepared_writes_nothing(design_blob_store: DesignBlobStore) -> None:
    """A `needs_review` fetch prepared nothing. Caching that as a family would serve an empty
    2x2 back as a hit and suppress the refetch — so `put` refuses it and stores no row."""
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    empty = _outcome()
    empty.prepared = []
    empty.cells = {}
    cache.put("https://acme.com/", empty)
    assert cache.get("https://acme.com/") is None


def test_agent_runtime_config_carries_the_cache_and_client_id_fields():
    import dataclasses

    from lumen_agent.config import AgentRuntimeConfig

    names = {f.name for f in dataclasses.fields(AgentRuntimeConfig)}
    assert "logo_family_cache" in names and "brandfetch_client_id" in names
