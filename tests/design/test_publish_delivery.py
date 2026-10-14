"""Custom-domain publishing S1 Task 6: the delivery CSP and the publish-asset integrity check."""

from __future__ import annotations

import hashlib

import pytest

from clue_design.publishes import (
    DELIVERY_CSP_HEADER,
    DELIVERY_CSP_META,
    SITE_DELIVERY_CSP_HEADER,
    SITE_DELIVERY_CSP_META,
    SITE_LIVE_DELIVERY,
    PublishAssetMismatch,
    check_publish_asset,
    delivery_csp,
    live_script_hashes,
    manifest_delivery,
    site_live_csp,
)

EXPECTED_META = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' data:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; object-src 'none'; worker-src 'none'; frame-src 'self' data: blob:; "
    "base-uri 'none'; form-action 'none'"
)


def test_csp_is_byte_exact_and_only_the_header_names_frame_ancestors() -> None:
    assert DELIVERY_CSP_META == EXPECTED_META
    assert DELIVERY_CSP_HEADER == EXPECTED_META + "; frame-ancestors 'self'"
    assert delivery_csp(meta=True) == DELIVERY_CSP_META
    assert delivery_csp() == DELIVERY_CSP_HEADER
    assert "http" not in DELIVERY_CSP_HEADER


def test_check_publish_asset_accepts_matching_bytes() -> None:
    data = b"console.log(1)"
    digest = hashlib.sha256(data).hexdigest()
    assert (
        check_publish_asset(
            data=data, media_type="text/javascript; charset=utf-8", digest=digest, extension="js"
        )
        == "text/javascript; charset=utf-8"
    )


@pytest.mark.parametrize(
    ("media_type", "digest_ok", "extension"),
    [
        ("text/css; charset=utf-8", True, "js"),  # media type vs URL
        ("text/javascript; charset=utf-8", False, "js"),  # bytes vs digest
        ("text/javascript; charset=utf-8", True, "png"),  # unknown extension
    ],
)
def test_check_publish_asset_refuses(media_type: str, digest_ok: bool, extension: str) -> None:
    data = b"body{}"
    digest = hashlib.sha256(data).hexdigest() if digest_ok else "0" * 64
    with pytest.raises(PublishAssetMismatch):
        check_publish_asset(data=data, media_type=media_type, digest=digest, extension=extension)


SITE_HEADER = (
    "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
)


def test_the_site_csp_is_contract_3_byte_for_byte() -> None:
    assert SITE_DELIVERY_CSP_HEADER == SITE_HEADER
    assert SITE_HEADER.removesuffix("; frame-ancestors 'self'") == SITE_DELIVERY_CSP_META
    assert delivery_csp(delivery="site") == SITE_DELIVERY_CSP_HEADER
    assert delivery_csp(meta=True, delivery="site") == SITE_DELIVERY_CSP_META
    assert delivery_csp() == DELIVERY_CSP_HEADER  # a web publish is unchanged


def test_only_a_manifest_that_says_site_gets_the_site_policy() -> None:
    assert manifest_delivery({"delivery": "site"}) == "site"
    for other in ({}, {"delivery": "web"}, {"delivery": "SITE"}, None, "site"):
        assert manifest_delivery(other) == "web"


HASH = "sha256-" + "A" * 43 + "="


def test_the_live_policy_runs_only_our_own_files_and_the_hashed_import_map() -> None:
    header = site_live_csp([HASH], meta=False)
    assert header == (
        "default-src 'none'; script-src 'self' 'sha256-" + "A" * 43 + "='; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
        "media-src 'self'; connect-src 'self'; object-src 'none'; worker-src 'none'; "
        "frame-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
    )
    assert site_live_csp([HASH], meta=True) == header.removesuffix("; frame-ancestors 'self'")
    assert "unsafe-eval" not in header and "'unsafe-inline'" not in header.split("style-src")[0]


def test_a_manifest_names_its_delivery_and_only_well_formed_hashes_are_used() -> None:
    assert manifest_delivery({"delivery": SITE_LIVE_DELIVERY}) == "site_live"
    assert manifest_delivery({"delivery": "site"}) == "site"
    assert manifest_delivery({"delivery": "anything"}) == "web"
    manifest = {
        "delivery": "site_live",
        "live": {"script_hashes": [HASH, "sha256-x' 'unsafe-eval", 7]},
    }
    assert live_script_hashes(manifest) == (HASH,)
    assert delivery_csp(delivery="site_live", script_hashes=(HASH,)) == site_live_csp(
        [HASH], meta=False
    )
