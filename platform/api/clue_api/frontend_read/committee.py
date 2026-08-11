"""The seam every `/frontend/v1` surface shares for reading a **governed committee**.

Account detail, Contacts list and Contact detail all author links to the same people. Their
addressability rule therefore lives here rather than in three composition loops that can drift.
Five things qualify:

1. :func:`current_claims` — a member's current claim per field, the unit every gate below reasons
   over;
2. :func:`committee_member_displayable` — the fail-closed rule deciding whether a governed member
   may be listed *at all*. It must be one function: the account detail's ``committee[]`` and the
   contacts endpoints render the same people from the same resolver, and if only one of them
   consulted the workspace display policy, a workspace that has turned professional-public display
   off would see an empty contacts table beside a fully populated committee block on the account it
   belongs to — the same data, two answers. (That was live: the detail endpoint applied no display
   gate at all until this module existed.)
3. :func:`latest_project_run_context` — the one recorded latest-run-wins project scope rule;
4. :func:`request_bound_conn_factory` — the ``ConnFactory`` that hands the resolver the request's
   **already-open** connection instead of letting it take a second one from the pool.
5. :func:`read_governed_committee` — the exact member union and display-policy decision consumed by
   every linked surface. A person absent here is never linked; a person present here is resolvable
   by Contact detail, including a member whose name or professional fields are absent.

**Why (3) is a correctness fix, not a micro-optimisation.** ``ContactEligibilityResolver`` opens a
connection through the factory it is constructed with. Passing the app's pool factory means a
request that is *already holding* a pool connection asks the same pool for another one, once per
targeting project. With the default pool (size 5, max_overflow 10 → 15 usable), 15 concurrent
requests can each hold one connection and then all block waiting for a sixteenth that only they
could release: a classic self-deadlock by pool exhaustion, whose symptom is a hung request rather
than an error. Binding the resolver to the connection the request already owns removes the second
acquisition entirely — peak concurrent connections per request drops from 2 to **1**, independent of
how many projects target the account — and has the side benefit that the committee is read inside
the same transaction (one consistent snapshot) as the rest of the response.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import ContactEligibilityResolver, GovernedCommitteeContact
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.research_view_governance import display_allowed
from clue_core import Claim, EntityId, ProjectRunId
from clue_db import ConnFactory
from clue_research.compliance import WorkspacePolicy, load_workspace_policy
from clue_research.membership import ProjectMembership
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE


class ProjectRunContext(WireModel):
    """The ``(project_run, product)`` pair a project's governed reads run under."""

    project_run_id: ProjectRunId
    product_id: str | None = None


_LATEST_PROJECT_RUN = text(
    """
    SELECT id, product_id
    FROM project_run
    WHERE workspace_id = :workspace_id AND project_id = :project_id
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    """
)


async def latest_project_run_context(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectRunContext | None:
    """Return the latest run's governed ``(project_run, product)`` scope for a project.

    ``None`` means the project has never started a run. This is the only implementation of the
    latest-run-wins rule, shared by every committee consumer.
    """
    row = (
        await conn.execute(
            _LATEST_PROJECT_RUN, {"workspace_id": workspace_id, "project_id": project_id}
        )
    ).first()
    if row is None:
        return None
    return ProjectRunContext(project_run_id=ProjectRunId(row[0]), product_id=row[1])


def request_bound_conn_factory(conn: AsyncConnection) -> ConnFactory:
    """A ``ConnFactory`` that yields ``conn`` and does not close it.

    The caller (the route) owns the connection's lifecycle; this only lends it. See the module
    docstring for why the resolver must never open its own.
    """

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _factory


def current_claims(member: GovernedCommitteeContact) -> dict[str, Claim]:
    """The member's current claim per field (already merged and product-scoped by the resolver)."""
    return {str(item.claim.field_key): item.claim for item in member.display_claims}


def committee_member_displayable(member: GovernedCommitteeContact, policy: WorkspacePolicy) -> bool:
    """Whether this governed member may be shown at all, under the workspace's display policy.

    Their role and persona are what make them a committee member; if the policy will not display
    those claims, there is no honest way to render the person as one — so the member is dropped
    rather than listed with the role blanked. Fail closed, and it is the *same*
    :func:`~clue_api.research_view_governance.display_allowed` predicate C7 applies to statements,
    imported rather than copied so the two surfaces cannot drift apart on the same personal data.
    """
    claims = current_claims(member)
    return all(
        (claim := claims.get(field_key)) is not None and display_allowed(claim, policy)
        for field_key in (ROLE_ON_COMMITTEE, PERSONA)
    )


class GovernedCommitteeUnion:
    """The displayable committee and each member's targeting projects.

    The first project that reaches a contact supplies that member's governed claim view. Later
    projects add attribution only; combining their claim sets could mix two product/run scopes.
    """

    def __init__(self) -> None:
        self.members: dict[EntityId, GovernedCommitteeContact] = {}
        self.project_ids: dict[EntityId, list[str]] = defaultdict(list)

    def add(self, member: GovernedCommitteeContact, *, project_id: str) -> None:
        self.members.setdefault(member.contact_entity_id, member)
        if project_id not in self.project_ids[member.contact_entity_id]:
            self.project_ids[member.contact_entity_id].append(project_id)


async def read_governed_committee(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    workspace_id: str,
    memberships: Sequence[ProjectMembership],
) -> tuple[GovernedCommitteeUnion, WorkspacePolicy]:
    """Resolve the one committee union every linked frontend read is allowed to expose.

    Memberships are intentionally authoritative. A project with no current membership cannot
    contribute committee members to this account, even if historical run lineage exists. Members
    whose role/persona claims are not displayable are omitted from every surface together.
    """
    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    bound = request_bound_conn_factory(conn)
    union = GovernedCommitteeUnion()
    for membership in memberships:
        context = await latest_project_run_context(
            conn, workspace_id=workspace_id, project_id=membership.project_id
        )
        if context is None:
            continue
        resolver = ContactEligibilityResolver(
            project_run_id=context.project_run_id,
            product_id=context.product_id,
            conn_factory=bound,
        )
        for member in await resolver.resolve_account(
            account_entity_id=account_id, workspace_id=workspace_id
        ):
            if committee_member_displayable(member, policy):
                union.add(member, project_id=membership.project_id)
    return union, policy


__all__ = [
    "GovernedCommitteeUnion",
    "ProjectRunContext",
    "committee_member_displayable",
    "current_claims",
    "latest_project_run_context",
    "read_governed_committee",
    "request_bound_conn_factory",
]
