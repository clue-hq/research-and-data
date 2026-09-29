"""The edge gate: only the Cloudflare Worker may name the public hostname (spec §5.2)."""

from __future__ import annotations

import hmac

from fastapi import Request

from clue_obs import get_logger
from clue_spine.hostnames import is_valid_hostname

PUBLIC_HOST_HEADER = "x-clue-public-host"
EDGE_AUTH_HEADER = "x-clue-edge-auth"
log = get_logger("clue_page_origin.edge")


class EdgeRefused(Exception):
    """403 with an empty body (never echo the presented header value)."""


class BadPublicHost(Exception):
    """400: the claimed public host is not a hostname."""


class EdgeGate:
    def __init__(self, *, secret: str | None, trust_host_header: bool) -> None:
        if trust_host_header and secret:
            raise ValueError(
                "CLUE_PAGES_TRUST_HOST_HEADER=true cannot be combined with CLUE_PAGES_EDGE_SECRET"
            )
        if not trust_host_header and not secret:
            raise ValueError(
                "CLUE_PAGES_EDGE_SECRET is required unless"
                " CLUE_PAGES_TRUST_HOST_HEADER=true (dev only)"
            )
        self._secret = secret
        self._trust_host_header = trust_host_header

    def public_host(self, request: Request) -> str:
        if self._trust_host_header:
            raw = request.headers.get("host", "")
            host = raw.rsplit(":", 1)[0] if ":" in raw and not raw.endswith("]") else raw
        else:
            presented = request.headers.get(EDGE_AUTH_HEADER)
            assert self._secret is not None
            if presented is None or not hmac.compare_digest(
                presented.encode("utf-8"), self._secret.encode("utf-8")
            ):
                log.warning(
                    "pages.edge.refused",
                    client=request.client.host if request.client else None,
                    claimed_host=request.headers.get(PUBLIC_HOST_HEADER),
                )
                raise EdgeRefused()
            host = request.headers.get(PUBLIC_HOST_HEADER, "")
        host = host.strip().lower().rstrip(".")
        if not is_valid_hostname(host):
            raise BadPublicHost()
        return host
