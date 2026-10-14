"""Fakes for the page origin: an in-memory registry + publish store, no database."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from clue_page_origin import EdgeGate, ServedPage, ServedPublish, create_page_origin_app

SECRET = "edge-secret-for-tests"
HOST = "acme.pages.test"
WS = "ws_acme"


def _sha(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


class FakePageReads:
    def __init__(self) -> None:
        self.hostnames: dict[str, str] = {HOST: WS}
        self.publishes: dict[tuple[str, str], ServedPublish] = {}
        self.pages: dict[tuple[str, str, str], str] = {}
        self.fallbacks: dict[str, str] = {}
        self.favicons: dict[str, tuple[str, bytes]] = {}
        self.assets: dict[tuple[str, str], tuple[str, bytes]] = {}
        self.public: dict[str, tuple[str, bytes]] = {}

    def publish(
        self,
        slug: str,
        html: str,
        *,
        noindex: bool = False,
        routes: dict[str, str] | None = None,
        workspace_id: str = WS,
        delivery: str = "web",
        script_hashes: tuple[str, ...] = (),
    ) -> None:
        """Publish a site; ``routes`` are its F5 page rows (none = a pre-F5 publish); ``delivery``
        "site" marks a Puck site publish (Wave 2 Contract 3) and "site_live" a live one, as its
        manifest does; ``script_hashes`` are a live page's import-map hashes (``manifest.live``)."""
        manifest = {
            "slug": slug,
            **({"robots": "noindex"} if noindex else {}),
            **({"delivery": delivery} if delivery in ("site", "site_live") else {}),
            **({"live": {"script_hashes": list(script_hashes)}} if script_hashes else {}),
        }
        manifest_json = json.dumps(
            manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        self.publishes[(workspace_id, slug)] = ServedPublish(
            html=html,
            html_digest=_sha(html),
            manifest_json=manifest_json,
            manifest_digest=_sha(manifest_json),
            noindex=noindex,
            delivery=delivery,
            script_hashes=tuple(script_hashes),
        )
        for route, page_html in (routes or {}).items():
            self.pages[(workspace_id, slug, route)] = page_html

    async def workspace_for_hostname(self, hostname: str) -> str | None:
        return self.hostnames.get(hostname)

    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None:
        return self.publishes.get((workspace_id, slug))

    async def active_page(self, workspace_id: str, slug: str, route: str) -> ServedPage | None:
        # Mirrors DbPageReads: the publish must be live; then its page row, else ``/`` falls
        # back to the publish's own html (a pre-F5 publish), else nothing.
        publish = self.publishes.get((workspace_id, slug))
        if publish is None:
            return None
        html = self.pages.get((workspace_id, slug, route))
        if html is not None:
            return ServedPage(
                html=html,
                html_digest=_sha(html),
                noindex=publish.noindex,
                delivery=publish.delivery,
                script_hashes=publish.script_hashes,
            )
        if route == "/":
            return ServedPage(
                html=publish.html,
                html_digest=publish.html_digest,
                noindex=publish.noindex,
                delivery=publish.delivery,
                script_hashes=publish.script_hashes,
            )
        return None

    async def fallback_url(self, workspace_id: str) -> str | None:
        return self.fallbacks.get(workspace_id)

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        return self.favicons.get(workspace_id)

    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None:
        return self.assets.get((workspace_id, sha256))

    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None:
        return self.public.get(sha256)


@pytest.fixture
def reads() -> FakePageReads:
    return FakePageReads()


@pytest.fixture
def client(reads: FakePageReads) -> TestClient:
    app = create_page_origin_app(reads=reads, gate=EdgeGate(secret=SECRET, trust_host_header=False))
    return TestClient(app)


@pytest.fixture
def dev_client(reads: FakePageReads) -> TestClient:
    app = create_page_origin_app(reads=reads, gate=EdgeGate(secret=None, trust_host_header=True))
    return TestClient(app)


def edge(host: str = HOST, *, secret: str | None = SECRET) -> dict[str, str]:
    headers = {"X-Clue-Public-Host": host}
    if secret is not None:
        headers["X-Clue-Edge-Auth"] = secret
    return headers
