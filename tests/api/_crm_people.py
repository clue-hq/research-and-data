"""Research the people a test's CRM changes write, so the changes pass the R-8.7 targets check.

Since Phase 3 Task 5 a change that creates or updates a CRM contact must name the Clue contact it
is about, and every person value it writes must be what Clue researched and cleared. Tests about
something else (the executor, the card, the reads before it) use :func:`clear_people` to seed, for
each such change, a committee member of a project account whose claims hold exactly the values
the change writes, link it to the CRM record an update writes, and name that member on the
change.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

_PERSON_SLUGS = frozenset(
    {
        "HUBSPOT_CREATE_CONTACT",
        "HUBSPOT_UPDATE_CONTACTS",
        "SALESFORCE_CREATE_CONTACT",
        "SALESFORCE_UPDATE_CONTACT",
    }
)
_PERSONA_BY_ROLE = {
    "CHAMPION": "champion",
    "BUDGET_HOLDER": "economic_buyer",
    "INFLUENCER": "technical_evaluator",
    "BLOCKER": "blocker",
    "END_USER": "user",
}


def _fields(change: Any) -> Mapping[str, Any]:
    arguments = change.arguments
    if change.slug == "HUBSPOT_UPDATE_CONTACTS":
        inputs: Any = arguments["inputs"]
        return dict(inputs[0]["properties"])
    return dict(arguments)


def _record_ref(change: Any) -> str | None:
    if change.slug == "HUBSPOT_UPDATE_CONTACTS":
        return str(change.arguments["inputs"][0]["id"])
    if change.slug == "SALESFORCE_UPDATE_CONTACT":
        return str(change.arguments["contact_id"])
    return None


async def _world(conn: Any, seeded: Any) -> Any:
    world: Any = getattr(seeded, "_crm_people_world", None)
    if world is None:
        from clue_api.arv2.catalog_seed import load_arv2_pack
        from clue_research.profiling.committee.fields import load_committee_pack
        from tests.api.test_crm_targets_db import _World

        await load_committee_pack(conn)
        await load_arv2_pack(conn)
        world = _World(conn, seeded)
        world.people_account = await world.account("Acme People", "acme-people.example")
        seeded._crm_people_world = world
    return world


async def clear_people(conn: Any, seeded: Any, changes: Sequence[Any]) -> list[Any]:
    """``changes`` (``ProposedChange`` or the tool's ``CrmChangeInput``) with each person change
    that names no Clue contact pointed at a freshly researched one holding its values (a change
    that names one is left as it is)."""
    cleared: list[Any] = []
    for change in changes:
        if change.slug not in _PERSON_SLUGS or change.clue_entity_id is not None:
            cleared.append(change)
            continue
        world = await _world(conn, seeded)
        fields = _fields(change)

        def first(*names: str, fields: Mapping[str, Any] = fields) -> Any:
            return next((fields[n] for n in names if fields.get(n) not in (None, "")), None)

        given = first("firstname", "first_name")
        family = first("lastname", "last_name")
        name = f"{given or 'Pat'} {family or 'Person'}"
        linkedin = first("hs_linkedin_url")
        person = await world.person(world.people_account, name, linkedin=linkedin)
        label = f"person-{person}"
        title = first("jobtitle", "title")
        if title is not None:
            await world.claim(f"{label}-title", person, "contact.current_title", str(title))
        email = first("email", "work_email")
        if email is not None:
            await world.claim(
                f"{label}-email",
                person,
                "core.work_email",
                {"address": str(email).strip().lower(), "status": "verified_smtp"},
            )
        role = first("hs_buying_role")
        persona = _PERSONA_BY_ROLE.get(str(role).split(";")[-1]) if role else "user"
        await world.claim(f"{label}-persona", person, "contact.persona", persona)
        record = _record_ref(change)
        if record is not None:
            # The CRM record this change writes is the one Clue knows this person by.
            from uuid import UUID

            from clue_api.crm import writes
            from clue_api.crm.connections import latest_connection

            connection = await latest_connection(conn, workspace_id=seeded.workspace_id)
            assert connection is not None
            await writes.record_link(
                conn,
                workspace_id=seeded.workspace_id,
                connection_id=connection.connection_id,
                crm_object="contact",
                crm_id=record,
                created_by_clue=False,
                clue_entity_id=UUID(str(person)),
            )
        if dataclasses.is_dataclass(change) and not isinstance(change, type):
            cleared.append(dataclasses.replace(change, clue_entity_id=str(person)))
        else:
            cleared.append(change.model_copy(update={"clue_entity_id": str(person)}))
    return cleared
