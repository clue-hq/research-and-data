"""FI-2 slice 1 — the flag-gated, workspace-scoped, Band-2 read surface for the frontend.

One router package at the api composition root (`docs/specs/FI-2-workspace-account-layer.md` §7),
composed over untouched mechanism surfaces. Task 1 ships the foundation only: the flag gate, the
structural workspace dependency, the FI-1 error envelope, the per-request id, CORS, and a health
probe; the accounts list/detail/contacts endpoints land on top of it in Tasks 2–4.
"""

from __future__ import annotations

from clue_api.frontend_read.app import (
    CORS_ALLOW_METHODS,
    FRONTEND_READ_PREFIX,
    REQUEST_ID_HEADER,
    build_frontend_read_probe_router,
    build_frontend_read_router,
    frontend_read_workspace_resolver,
    install_frontend_read_surface,
)

__all__ = [
    "CORS_ALLOW_METHODS",
    "FRONTEND_READ_PREFIX",
    "REQUEST_ID_HEADER",
    "build_frontend_read_probe_router",
    "build_frontend_read_router",
    "frontend_read_workspace_resolver",
    "install_frontend_read_surface",
]
