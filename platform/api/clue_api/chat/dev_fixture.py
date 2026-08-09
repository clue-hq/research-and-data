"""Real Postgres rows behind the development chat principal (FI Lane D — the B1 join).

`FI-lane-B-authenticated-principal-contract.md` §4 permits a development authentication adapter
"only under an explicit local/test environment guard", and requires that it "must still resolve a
real internal user/membership fixture from Postgres". D0 could not honour the second half: Lane B's
tables did not exist yet, so ``settings.chat_dev_principal_user_id`` / ``…_membership_id`` were
free-floating strings that named nothing. B1 has since landed ``platform_user`` / ``auth_identity``
/ ``workspace_membership``, so this module makes those settings *point at rows* — and the join
migration ``c4ccc7b11810`` makes a thread or turn citing a non-existent identity a database error
rather than a convention breach.

Three rules shape what is here:

* **Never a raw INSERT into Lane B's tables.** Every write goes through ``clue_auth``'s own CRUD
  (:func:`clue_auth.create_platform_user`, :func:`clue_auth.link_auth_identity`,
  :func:`clue_auth.create_workspace_membership`), so Lane B keeps sole authority over the shape and
  lifecycle of its rows. This module decides *which* fixture exists, never *how* an identity is
  built.
* **Idempotent.** Startup runs it on every boot: a second boot must find its rows, not fail on them
  and not duplicate them.
* **Fail loud, never fabricate.** A missing workspace, a suspended user, a revoked membership, or a
  settings/DB id disagreement refuses with :class:`DevPrincipalUnavailable`. Provisioning runs at
  *startup*, so a process that cannot resolve its development identity never serves chat traffic
  under a fictional one.

The provider mapping written here uses the deliberately non-production provider key
``clue_local_dev``. It is not Clerk and it authenticates nobody — no session, token, or cookie is
ever validated against it. It exists so the fixture has the *same shape* B2's real adapter will
resolve (``auth_identity`` → ``platform_user`` → ``workspace_membership``), which is what keeps
this a fixture *of* the real substrate rather than a parallel one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.chat.principal import (
    DEV_ROLE_KEY,
    PrincipalResolver,
    ProductionPrincipalRequired,
    RequestPrincipal,
)
from clue_auth import (
    AuthIdentityError,
    PlatformUser,
    RoleKey,
    WorkspaceMembership,
    create_platform_user,
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    link_auth_identity,
    permissions_for_role,
)

# The unguarded membership primitive, imported from the module rather than the package root. Lane
# B's public API exposes only ``create_workspace_member``, which requires an *acting* membership
# already holding ``workspace.manage_members``; provisioning a workspace's development owner has no
# such actor. That is the same bootstrap case Lane B's own ``provision_workspace_owner`` and
# ``accept_workspace_invitation`` solve with this very primitive, so the fixture borrows it rather
# than inventing a second way to write the row.
from clue_auth.store import create_workspace_membership
from clue_config import Settings
from clue_db import ConnFactory, transaction
from clue_spine import get_workspace

__all__ = [
    "DEV_PROVIDER_KEY",
    "DevPrincipalIds",
    "DevPrincipalUnavailable",
    "StartupDevPrincipalResolver",
    "build_provisioned_dev_principal_resolver",
    "dev_provider_subject",
    "provision_dev_principal",
]

#: The provider key the development identity mapping is filed under. Never a real provider.
DEV_PROVIDER_KEY = "clue_local_dev"


class DevPrincipalUnavailable(RuntimeError):
    """The configured development principal cannot be backed by real Postgres rows.

    Raised at startup, never per request. Every message names the setting or the row that is wrong,
    so an operator fixes configuration instead of meeting a half-identity at first request.
    """


@dataclass(frozen=True, slots=True)
class DevPrincipalIds:
    """The verified internal ids a provisioned development principal carries."""

    user_id: str
    membership_id: str
    workspace_id: str
    role_key: RoleKey


def dev_provider_subject(user_id: str) -> str:
    """The opaque subject the fixture is filed under within :data:`DEV_PROVIDER_KEY`.

    Derived from the Clue user id rather than an email or a person's name: this value is a *lookup
    attribute*, and the fixture must not put a personal identifier where production holds an opaque
    provider subject.
    """

    return f"local-dev:{user_id}"


async def provision_dev_principal(conn: AsyncConnection, *, settings: Settings) -> DevPrincipalIds:
    """Idempotently ensure the configured development user + membership exist; return their ids.

    The caller owns the transaction (the repo's raw-SQL convention). Every returned id is read back
    from Postgres, so a resolver closing over them cites rows that provably exist and provably
    belong together — which is exactly what the new composite ownership foreign keys require.
    """

    user_id = settings.chat_dev_principal_user_id.strip()
    membership_id = settings.chat_dev_principal_membership_id.strip()
    workspace_id = settings.chat_dev_principal_workspace_id.strip()
    if not user_id or not membership_id:
        raise DevPrincipalUnavailable(
            "CLUE_CHAT_DEV_PRINCIPAL_USER_ID and CLUE_CHAT_DEV_PRINCIPAL_MEMBERSHIP_ID must both "
            "be set to provision the development chat principal"
        )
    if not workspace_id:
        raise DevPrincipalUnavailable(
            "CLUE_CHAT_DEV_PRINCIPAL_WORKSPACE_ID is unset: the development principal is a "
            "membership of exactly one workspace and cannot be provisioned without naming it"
        )
    if await get_workspace(conn, workspace_id) is None:
        raise DevPrincipalUnavailable(
            f"workspace {workspace_id!r} does not exist; create the workspace this development "
            "principal belongs to before enabling the chat surface"
        )

    user = await _ensure_user(conn, user_id=user_id)
    membership = await _ensure_membership(
        conn, user_id=user.user_id, membership_id=membership_id, workspace_id=workspace_id
    )
    return DevPrincipalIds(
        user_id=user.user_id,
        membership_id=membership.membership_id,
        workspace_id=membership.workspace_id,
        role_key=membership.role_key,
    )


async def build_provisioned_dev_principal_resolver(
    settings: Settings, *, conn_factory: ConnFactory = transaction
) -> PrincipalResolver:
    """Provision the development identity, then close a **sync** resolver over the verified ids.

    This is where the async work lives, which is what lets :data:`PrincipalResolver` stay a plain
    ``(workspace_id) -> RequestPrincipal`` callable and leaves the router untouched. Call it from a
    composition root/startup hook: a failure here must stop the process, not surface as a 500 on
    the first chat request.

    The principal is pinned to the *provisioned* workspace. A request selecting any other workspace
    is refused by the router's existing workspace re-check (403 ``WORKSPACE_FORBIDDEN``), because
    the membership this principal carries is a membership of one workspace and of no other — Lane B
    ruling 6, now also enforced by the composite ownership foreign keys.
    """

    if settings.projections_auth_mode != "local_header":
        raise ProductionPrincipalRequired(
            "the chat surface requires an injected RequestPrincipal resolver outside "
            "local_header auth mode; the development principal is refused in production"
        )
    async with conn_factory() as conn:
        ids = await provision_dev_principal(conn, settings=settings)

    def resolve(workspace_id: str) -> RequestPrincipal:
        del workspace_id  # the router re-checks it against the principal below
        return RequestPrincipal(
            user_id=ids.user_id,
            membership_id=ids.membership_id,
            workspace_id=ids.workspace_id,
            role_key=ids.role_key,
            # The provisioned membership's *own* role decides what this principal may do — the
            # same ``permissions_for_role`` the real authorizer applies. A fixture that granted
            # itself a different set would stop testing production's authorization.
            permissions=permissions_for_role(ids.role_key),
            authenticated_at=datetime.now(UTC),
        )

    return resolve


class StartupDevPrincipalResolver:
    """A :data:`PrincipalResolver` that must be bound by an async startup hook before it answers.

    The chat router is mounted while the application object is *built* (synchronously), but real
    rows can only be provisioned once the process has a database — i.e. inside the lifespan. This
    object bridges those two moments without changing the sync resolver seam: the composition root
    passes it to ``create_projections_app`` at build time and awaits :meth:`bind` from its startup
    check, where a failure aborts startup.

    Unbound, it refuses. That branch should be unreachable — :meth:`bind` raising is what stops the
    process — but a resolver that would rather serve *nobody* than an unverified identity is the
    only safe default for this seam.
    """

    __slots__ = ("_delegate",)

    def __init__(self) -> None:
        self._delegate: PrincipalResolver | None = None

    async def bind(
        self, settings: Settings, *, conn_factory: ConnFactory = transaction
    ) -> DevPrincipalIds:
        """Provision the fixture and start answering. Raises rather than degrading."""

        resolver = await build_provisioned_dev_principal_resolver(
            settings, conn_factory=conn_factory
        )
        self._delegate = resolver
        principal = resolver("")
        return DevPrincipalIds(
            user_id=principal.user_id,
            membership_id=principal.membership_id,
            workspace_id=principal.workspace_id,
            role_key=principal.role_key,
        )

    def __call__(self, workspace_id: str) -> RequestPrincipal:
        if self._delegate is None:
            raise DevPrincipalUnavailable(
                "the development chat principal was never provisioned; the process must bind it "
                "at startup before serving chat traffic"
            )
        return self._delegate(workspace_id)


async def _ensure_user(conn: AsyncConnection, *, user_id: str) -> PlatformUser:
    existing = await get_platform_user(conn, user_id)
    if existing is not None:
        if existing.status != "active":
            raise DevPrincipalUnavailable(
                f"platform_user {user_id!r} exists but is {existing.status}; a suspended or "
                "disabled identity is never silently reactivated"
            )
        user = existing
    else:
        try:
            user = await create_platform_user(
                conn, user_id=user_id, display_name="Local development principal"
            )
        except (IntegrityError, AuthIdentityError) as exc:
            raise DevPrincipalUnavailable(
                f"platform_user {user_id!r} could not be provisioned: {exc}"
            ) from exc
    subject = dev_provider_subject(user_id)
    identity = await get_auth_identity(
        conn, provider_key=DEV_PROVIDER_KEY, provider_subject=subject
    )
    if identity is None:
        await link_auth_identity(
            conn, user_id=user.user_id, provider_key=DEV_PROVIDER_KEY, provider_subject=subject
        )
    return user


async def _ensure_membership(
    conn: AsyncConnection, *, user_id: str, membership_id: str, workspace_id: str
) -> WorkspaceMembership:
    existing = await get_workspace_membership(conn, workspace_id=workspace_id, user_id=user_id)
    if existing is not None:
        # ``unique (workspace_id, user_id)`` means this pair holds exactly one membership, so a
        # settings id naming a different one is a configuration error rather than a second
        # membership to create. Refusing — instead of silently preferring either side — keeps the
        # durable ownership columns and the deployment configuration in agreement.
        if existing.membership_id != membership_id:
            raise DevPrincipalUnavailable(
                f"user {user_id!r} already holds membership {existing.membership_id!r} in "
                f"workspace {workspace_id!r}; set CLUE_CHAT_DEV_PRINCIPAL_MEMBERSHIP_ID to that "
                "value"
            )
        if existing.status != "active":
            raise DevPrincipalUnavailable(
                f"workspace_membership {membership_id!r} is {existing.status}; a suspended or "
                "revoked membership is never silently reactivated"
            )
        return existing
    try:
        return await create_workspace_membership(
            conn,
            workspace_id=workspace_id,
            user_id=user_id,
            role_key=DEV_ROLE_KEY,
            status="active",
            membership_id=membership_id,
        )
    except (IntegrityError, AuthIdentityError, ValueError) as exc:
        raise DevPrincipalUnavailable(
            f"workspace_membership {membership_id!r} could not be provisioned in workspace "
            f"{workspace_id!r}: {exc}"
        ) from exc
