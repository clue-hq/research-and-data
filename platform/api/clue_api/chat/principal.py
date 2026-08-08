"""The chat surface's principal seam (FI Lane D D0 — the placeholder Lane B replaces).

:class:`RequestPrincipal` is the closed, **already authenticated and authorized** identity
`FI-lane-B-authenticated-principal-contract.md` §4 freezes. Lane D consumes it; Lane D never
authenticates. This module exists only so D0's endpoints can be written against the final shape
while Lane B's B2 (backend authentication) and B3 (frontend session) are still in flight — the
charter explicitly permits "a deterministic injected test ``RequestPrincipal``" here, and equally
explicitly forbids "temporary user headers inside domain code" (contract §9).

So there are exactly two ways a principal reaches a route:

1. **Injection.** The composition root passes a resolver, or a test overrides the dependency. This
   is the seam Lane B's real ``Authenticator`` → ``IdentityResolver`` → ``Authorizer`` chain will
   occupy at the B2 join, with no route change.
2. **The guarded development resolver.** Only when ``settings.projections_auth_mode ==
   'local_header'`` — the mode the settings file already documents as "explicitly local/manual-test
   only". It derives the workspace from the surface's existing tenant seam and reads its internal
   user/membership ids from settings. In ``service`` mode it refuses, and
   :func:`install_chat_surface` refuses at *startup* rather than waiting for a request, which is
   contract §5.6's "production startup fails if the local-header resolver is selected".

   :func:`build_dev_principal_resolver` here is the **unprovisioned** form: pure, sync, and
   DB-free, which is what a unit test or an in-process fixture wants. Anything that will actually
   write durable rows must instead use
   :func:`clue_api.chat.dev_fixture.build_provisioned_dev_principal_resolver`, which does the async
   provisioning up front and closes this same sync resolver shape over ids read back from
   Postgres — contract §4's "must still resolve a real internal user/membership fixture from
   Postgres", and, since the B1 join migration, a hard requirement of the ownership foreign keys.
   The async factory lives in that module rather than here so this one keeps no database
   dependency at all.

No provider (Clerk) value appears anywhere in this module, and no route ever reads a user-identity
header: the two dev ids are deployment configuration, not client input, so a browser cannot claim
to be somebody by sending a header.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from clue_config import Settings

__all__ = [
    "CHAT_PERMISSIONS",
    "DEV_ROLE_KEY",
    "PERMISSION_GATE_RESPOND",
    "PERMISSION_PROJECT_READ",
    "PERMISSION_THREAD_READ",
    "PERMISSION_THREAD_WRITE",
    "PrincipalResolver",
    "ProductionPrincipalRequired",
    "RequestPrincipal",
    "build_dev_principal_resolver",
]

#: The permission keys this surface checks, from the Lane B contract §3.5 floor.
PERMISSION_PROJECT_READ = "project.read"
PERMISSION_THREAD_READ = "thread.read"
PERMISSION_THREAD_WRITE = "thread.write"
PERMISSION_GATE_RESPOND = "gate.respond"

#: What the development principal is granted: exactly the thread shell, and nothing that spends.
#: ``research.launch`` / ``research.approve_spend`` are deliberately absent — D0 has no surface for
#: them, and a dev principal must not quietly hold authority its endpoints have not earned.
CHAT_PERMISSIONS: frozenset[str] = frozenset(
    {PERMISSION_PROJECT_READ, PERMISSION_THREAD_READ, PERMISSION_THREAD_WRITE}
)

#: The MVP role vocabulary is ``owner | admin | operator | viewer`` (contract §3.5).
DEV_ROLE_KEY = "owner"


class ProductionPrincipalRequired(RuntimeError):
    """The chat surface was enabled in production without a real principal resolver.

    Raised at composition, not per request: a process that would serve chat traffic under a
    development identity must fail to start.
    """


@dataclass(frozen=True, slots=True)
class RequestPrincipal:
    """One request's authenticated, authorized, **internal** identity.

    Every field is Clue-owned: ``user_id`` is a ``platform_user.user_id``, ``membership_id`` a
    ``workspace_membership.membership_id``. No provider subject, token claim, organization, or
    email may ever be carried here — that is Lane B ruling 2, and it is why domain rows can safely
    store these values directly.
    """

    principal_kind: Literal["human"]
    user_id: str
    membership_id: str
    workspace_id: str
    role_key: str
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("user_id", "membership_id", "workspace_id", "role_key"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"request principal {name} must be non-empty")

    def allows(self, permission: str) -> bool:
        return permission in self.permissions


#: How a route obtains its principal: a callable over the already-resolved workspace selector.
#: Lane B's authorizer has exactly this shape once the session/token work lands — the workspace
#: arrives as a *selector* and the resolver proves membership, never the other way round
#: (contract ruling 6).
PrincipalResolver = Callable[[str], RequestPrincipal]


def build_dev_principal_resolver(settings: Settings) -> PrincipalResolver:
    """The guarded development resolver — valid only in ``local_header`` auth mode.

    It fabricates no *authorization*: it hands back the deployment-configured internal ids for the
    workspace the surface's tenant seam already resolved. It also touches no database, so the ids
    it carries are only as real as the configuration — use
    :func:`clue_api.chat.dev_fixture.build_provisioned_dev_principal_resolver` for anything that
    writes durable rows. When B2 lands, both are replaced outright.
    """

    if settings.projections_auth_mode != "local_header":
        raise ProductionPrincipalRequired(
            "the chat surface requires an injected RequestPrincipal resolver outside "
            "local_header auth mode; the development principal is refused in production"
        )

    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            principal_kind="human",
            user_id=settings.chat_dev_principal_user_id,
            membership_id=settings.chat_dev_principal_membership_id,
            workspace_id=workspace_id,
            role_key=DEV_ROLE_KEY,
            permissions=CHAT_PERMISSIONS,
        )

    return resolve
