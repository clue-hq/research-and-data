"""The chat surface's principal seam — now Lane B's real one (FI Lane D ⇄ Lane B join).

:class:`~clue_auth.RequestPrincipal` is the closed, **already authenticated and authorized**
identity `FI-lane-B-authenticated-principal-contract.md` §4 freezes. Lane D consumes it; Lane D
never authenticates.

D0 shipped a placeholder dataclass of the same shape here, because Lane B's B2 (backend
authentication) and B3 (frontend session) were still in flight and the charter explicitly permits
"a deterministic injected test ``RequestPrincipal``" while they are. **That placeholder is gone.**
The contract said Lane B's chain "replaces [it] outright at the B2 join", and B2/B3/B4 have landed,
so this module now *imports* Lane B's model and re-exports it: there is exactly one
``RequestPrincipal`` type in the platform, the one the authorizer mints, and a route cannot be
handed a principal that never passed through Lane B's shape.

Three ways a principal reaches a route, in this precedence order:

1. **Lane B's authenticated chain** (``auth_service`` at the composition root). The provider
   session is validated, mapped through ``auth_identity`` to a ``platform_user``, checked against
   an active ``workspace_membership``, and closed into a principal —
   :func:`clue_api.chat.router.bind_authenticated_principal` is the adapter, and it re-checks the
   workspace selector against the authorized workspace (ruling 6: selection is not authority).
2. **Injection.** The composition root passes a :data:`PrincipalResolver`, or a test overrides the
   dependency. This is the deterministic test principal the charter permits.
3. **The guarded development resolver.** Only when ``settings.projections_auth_mode ==
   'local_header'`` — the mode the settings file documents as "explicitly local/manual-test only".
   It derives the workspace from the surface's existing tenant seam and reads its internal
   user/membership ids from settings. Outside that mode it refuses, and
   :func:`clue_api.chat.router.install_chat_surface` refuses at *startup* rather than waiting for a
   request, which is contract §5.6's "production startup fails if the local-header resolver is
   selected".

   :func:`build_dev_principal_resolver` here is the **unprovisioned** form: pure, sync, and
   DB-free, which is what a unit test or an in-process fixture wants. Anything that will actually
   write durable rows must instead use
   :func:`clue_api.chat.dev_fixture.build_provisioned_dev_principal_resolver`, which does the async
   provisioning up front and closes this same sync resolver shape over ids read back from
   Postgres — contract §4's "must still resolve a real internal user/membership fixture from
   Postgres", and, since the B1 join migration, a hard requirement of the ownership foreign keys.
   The async factory lives in that module rather than here so this one keeps no database
   dependency at all.

Options 1 and 3 are mutually exclusive by construction — ``install_chat_surface`` refuses to start
a process that wires both, and ``projections_main`` refuses the contradictory settings pair — so
"which identity is this deployment serving under?" always has exactly one answer.

No provider (Clerk) value appears anywhere in this module, and no route ever reads a user-identity
header: the two dev ids are deployment configuration, not client input, so a browser cannot claim
to be somebody by sending a header.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from clue_auth import Permission, RequestPrincipal, RoleKey, permissions_for_role
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

#: The permission keys this surface checks, from the Lane B contract §3.5 floor. They are the
#: ``clue_auth.Permission`` literals, not strings of our own: a typo is a type error rather than a
#: check that silently never passes.
PERMISSION_PROJECT_READ: Permission = "project.read"
PERMISSION_THREAD_READ: Permission = "thread.read"
PERMISSION_THREAD_WRITE: Permission = "thread.write"
PERMISSION_GATE_RESPOND: Permission = "gate.respond"

#: The MVP role vocabulary is ``owner | admin | operator | viewer`` (contract §3.5).
DEV_ROLE_KEY: RoleKey = "owner"

#: What the development/test principal is granted: **exactly what Lane B's policy grants its role**,
#: never a hand-rolled subset. D0 enumerated a narrower set here because the surface was a thread
#: shell; D4 added gate answering and the confirm→launch receipt, and a dev principal whose
#: permission set differs from the production one for the same role stops being a fixture *of* the
#: real substrate. One policy, one source (``clue_auth.policy``).
CHAT_PERMISSIONS: frozenset[Permission] = permissions_for_role(DEV_ROLE_KEY)


class ProductionPrincipalRequired(RuntimeError):
    """The chat surface was enabled in production without a real principal resolver.

    Raised at composition, not per request: a process that would serve chat traffic under a
    development identity — or under two competing identities — must fail to start.
    """


#: How a route obtains its principal *without* Lane B's async chain: a callable over the
#: already-resolved workspace selector. This is the injected/test/development seam; the
#: authenticated path is async (it reads Postgres) and is adapted separately in the router. The
#: workspace arrives as a *selector* and the resolver proves membership, never the other way round
#: (contract ruling 6).
PrincipalResolver = Callable[[str], RequestPrincipal]


def build_dev_principal_resolver(settings: Settings) -> PrincipalResolver:
    """The guarded development resolver — valid only in ``local_header`` auth mode.

    It fabricates no *authorization*: it hands back the deployment-configured internal ids for the
    workspace the surface's tenant seam already resolved. It also touches no database, so the ids
    it carries are only as real as the configuration — use
    :func:`clue_api.chat.dev_fixture.build_provisioned_dev_principal_resolver` for anything that
    writes durable rows.
    """

    if settings.projections_auth_mode != "local_header":
        raise ProductionPrincipalRequired(
            "the chat surface requires an authenticated principal service or an injected "
            "RequestPrincipal resolver outside local_header auth mode; the development principal "
            "is refused in production"
        )

    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=settings.chat_dev_principal_user_id,
            membership_id=settings.chat_dev_principal_membership_id,
            workspace_id=workspace_id,
            role_key=DEV_ROLE_KEY,
            permissions=CHAT_PERMISSIONS,
            authenticated_at=datetime.now(UTC),
        )

    return resolve
