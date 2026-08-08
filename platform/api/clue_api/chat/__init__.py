"""The production chat surface (FI Lane D).

Slice D0 lands REQ-21's durable shell: thread CRUD over the governed toolbelt, and the paginated
cold-load reads a transcript rehydrates from. Turn submission (D2), token streaming (D3), and the
gate/approval flow (D4) join this package later; the router, principal seam, and error envelope
here are what they attach to.
"""

from __future__ import annotations

from clue_api.chat.principal import (
    CHAT_PERMISSIONS,
    PERMISSION_GATE_RESPOND,
    PERMISSION_PROJECT_READ,
    PERMISSION_THREAD_READ,
    PERMISSION_THREAD_WRITE,
    PrincipalResolver,
    ProductionPrincipalRequired,
    RequestPrincipal,
    build_dev_principal_resolver,
)
from clue_api.chat.router import (
    CHAT_PREFIX,
    REQUEST_ID_HEADER,
    bind_principal_resolver,
    build_chat_router,
    chat_principal_resolver,
    chat_workspace_resolver,
    install_chat_surface,
)

__all__ = [
    "CHAT_PERMISSIONS",
    "CHAT_PREFIX",
    "PERMISSION_GATE_RESPOND",
    "PERMISSION_PROJECT_READ",
    "PERMISSION_THREAD_READ",
    "PERMISSION_THREAD_WRITE",
    "REQUEST_ID_HEADER",
    "PrincipalResolver",
    "ProductionPrincipalRequired",
    "RequestPrincipal",
    "bind_principal_resolver",
    "build_chat_router",
    "build_dev_principal_resolver",
    "chat_principal_resolver",
    "chat_workspace_resolver",
    "install_chat_surface",
]
