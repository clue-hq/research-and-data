"""The seam both `/frontend/v1` surfaces share for reading a **governed committee**.

Its own module because the two consumers already point one way — ``contacts`` imports
``account_detail`` for :func:`~clue_api.frontend_read.account_detail.latest_project_run_context` —
so anything they *both* need cannot live in either without a cycle. Three things qualify:

1. :func:`current_claims` — a member's current claim per field, the unit every gate below reasons
   over;
2. :func:`committee_member_displayable` — the fail-closed rule deciding whether a governed member
   may be listed *at all*. It must be one function: the account detail's ``committee[]`` and the
   contacts endpoints render the same people from the same resolver, and if only one of them
   consulted the workspace display policy, a workspace that has turned professional-public display
   off would see an empty contacts table beside a fully populated committee block on the account it
   belongs to — the same data, two answers. (That was live: the detail endpoint applied no display
   gate at all until this module existed.)
3. :func:`request_bound_conn_factory` — the ``ConnFactory`` that hands the resolver the request's
   **already-open** connection instead of letting it take a second one from the pool.

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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import GovernedCommitteeContact
from clue_api.research_view_governance import display_allowed
from clue_core import Claim
from clue_db import ConnFactory
from clue_research.compliance import WorkspacePolicy
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE


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


__all__ = [
    "committee_member_displayable",
    "current_claims",
    "request_bound_conn_factory",
]
