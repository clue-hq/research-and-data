"""Route-table workspace-seam guard (O4).

Seam enforcement is opt-in per route — one ``Depends(repository)`` (or
``dependencies=[Depends(resolve_workspace_id)]``) per function, by hand — so a
new route that forgets the dependency ships silently exempt. That is exactly
how ``/font-library`` and ``/agent/turn-preview`` sat accidentally headerless
until D2.5A retrofitted them, and the spot-check tests in
``test_workspace_seam.py`` pin only a handful of routes. This guard closes the
class: it walks the FULL route table, issues a headerless request to every
route, and asserts the O4 contract — everything 401s
``workspace.header_required`` except the reviewed allowlist below.

Behavioral on purpose: the dependency tree could be introspected statically,
but a headerless-request probe asserts what production actually enforces,
whatever mechanism a route uses. Dependencies resolve before body/query
validation (pinned by ``test_workspace_seam.py``'s incomplete-body case), so
dummy path params and empty bodies never mask the 401.

A route that genuinely must serve headerless gets an ALLOWLIST entry here —
with its justification — in the same review as its implementation. Allowlist
drift is guarded in both directions: an exempt route that STARTS demanding
the header fails too (the exemption is contract, not leftovers).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from lumen_api.main import create_app

# The O4 exemptions, ratified at D2.5A (three) + D7's token-gated stream. The O6b public
# serving group was a fourth entry until custom-domain publishing S1 deleted those routes —
# the page origin serves published pages, and this app has no public surface left.
# Every entry names WHY it may answer a headerless request.
ALLOWLIST: dict[Tuple[str, str], str] = {
    # Process-wide engine stamp, read by the editor's version handshake
    # before any workspace context exists.
    ("GET", "/build-info"): "engine handshake, no tenant state",
    # Content-addressed public bytes: published pages and the origin-"null"
    # srcdoc preview iframe cannot send a header; the unguessable sha256 is
    # the gate (ruling R-D4-7).
    ("GET", "/asset-store/{digest}"): "public content-addressed bytes",
    # D7 run-event stream: EventSource-style consumers cannot send headers;
    # authenticated by a single-use stream token whose MINT is header-gated.
    ("GET", "/agent/runs/{run_id}/events"): "single-use stream token carries tenancy",
    # Liveness for Railway's health check, the uptime monitors and the CI boot smoke test
    # (first deployment spec §9.5): answers before any workspace exists and touches no tenant state.
    ("GET", "/healthz"): "process liveness, no tenant state",
}

_PARAM = re.compile(r"{[^}]+}")


def ungated_routes(app: FastAPI) -> List[str]:
    """Every (method, path) that violates the O4 route-table contract."""
    bare = TestClient(app)  # deliberately NO X-Workspace-Id header
    violations: List[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue  # starlette internals (openapi/docs), not API surface
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            probe_path = _PARAM.sub("1", route.path)
            response = bare.request(method, probe_path)
            detail = {}
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("detail"), dict):
                    detail = body["detail"]
            except ValueError:
                pass
            demands_header = (
                response.status_code == 401
                and detail.get("code") == "workspace.header_required"
            )
            if (method, route.path) in ALLOWLIST:
                if demands_header:
                    violations.append(
                        f"{method} {route.path}: allowlisted as exempt but now demands "
                        "the workspace header — remove its ALLOWLIST entry"
                    )
            elif not demands_header:
                violations.append(
                    f"{method} {route.path}: answered a headerless request with "
                    f"HTTP {response.status_code} — every route needs "
                    "Depends(repository) / Depends(resolve_workspace_id), or a "
                    "justified ALLOWLIST entry in this file"
                )
    return violations


def test_every_route_enforces_the_workspace_seam(tmp_path: Path, design_storage) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    violations = ungated_routes(app)
    assert not violations, "O4 route-table contract violated:\n  " + "\n  ".join(violations)


def test_the_guard_detects_an_ungated_route(tmp_path: Path, design_storage) -> None:
    """The guard's detection power, pinned: plant a route that forgets the
    seam dependency (the exact historical failure shape) and the walk must
    name it. If this ever passes vacuously, the guard above proves nothing."""
    app = create_app(tmp_path / "engine-cache", storage=design_storage)

    @app.get("/guard-selftest-ungated")
    def scratch() -> dict:  # pragma: no cover - exists only to be flagged
        return {"ok": True}

    flagged = [v for v in ungated_routes(app) if "/guard-selftest-ungated" in v]
    assert flagged, "the route-table guard failed to flag a deliberately ungated route"
