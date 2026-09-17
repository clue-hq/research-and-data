"""The flag-gated, workspace-scoped read surface the frontend binds to: `/frontend/v1`.

One router package at the api composition root, composed over untouched mechanism surfaces:
:mod:`~clue_api.frontend_read.app` owns the foundation (the flag gate, the structural workspace
dependency, the error envelope, the per-request id, CORS, the health probe) and the endpoint
modules register on top of it.

It serves exactly one wire contract — ARV2's ``contract_v1`` — since 2026-09-09, when the FI-2
payloads, their readers and the ``?contract=`` selector were deleted.
"""

from __future__ import annotations

from clue_api.frontend_read.account_detail import AccountNotFound, read_account_detail
from clue_api.frontend_read.account_workspace import read_account_workspace
from clue_api.frontend_read.accounts_list import InvalidCursorError, list_accounts
from clue_api.frontend_read.app import (
    CORS_ALLOW_METHODS,
    FRONTEND_READ_PREFIX,
    REQUEST_ID_HEADER,
    WorkspaceDep,
    build_frontend_read_probe_router,
    build_frontend_read_router,
    frontend_read_workspace_resolver,
    install_frontend_read_surface,
)
from clue_api.frontend_read.brand_knowledge import (
    KnowledgeDocumentDetailWire,
    KnowledgeTreeWire,
    OnboardingStatusWire,
    read_knowledge_document,
    read_knowledge_tree,
    read_onboarding_status,
    resolve_knowledge_brand,
)
from clue_api.frontend_read.display_pages import DisplayPages, PageRead
from clue_api.frontend_read.project_run_context import latest_project_run_context

__all__ = [
    "CORS_ALLOW_METHODS",
    "FRONTEND_READ_PREFIX",
    "REQUEST_ID_HEADER",
    "AccountNotFound",
    "DisplayPages",
    "InvalidCursorError",
    "KnowledgeDocumentDetailWire",
    "KnowledgeTreeWire",
    "OnboardingStatusWire",
    "PageRead",
    "WorkspaceDep",
    "build_frontend_read_probe_router",
    "build_frontend_read_router",
    "frontend_read_workspace_resolver",
    "install_frontend_read_surface",
    "latest_project_run_context",
    "list_accounts",
    "read_account_detail",
    "read_account_workspace",
    "read_knowledge_document",
    "read_knowledge_tree",
    "read_onboarding_status",
    "resolve_knowledge_brand",
]
