"""Custom-domain publishing S1 Task 6: the delivery CSP and the publish-asset integrity check."""

from __future__ import annotations

import hashlib

import pytest

from clue_design.publishes import (
    DELIVERY_CSP_HEADER,
    DELIVERY_CSP_META,
    SITE_DELIVERY_CSP_HEADER,
    SITE_DELIVERY_CSP_META,
    PublishAssetMismatch,
    check_publish_asset,
    delivery_csp,
    manifest_delivery,
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
