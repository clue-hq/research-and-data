"""FI-2 §6.2 — the R5 Exa first-call rule, reconciled with the borrowed set.

The R5 guard says the *first* ``research_account_deep`` call must include every field for which Exa
is the primary source; the point is to stop an agent from drip-feeding one field per paid bundle.
§6.2 makes some of those fields free — a fresh, evidence-backed, conflict-free neutral claim is
already on file, so the bundle compiler drops it. Left alone, the two rules contradict each other:
a prompt-obedient agent reads its state, sees those fields reported *complete*, omits them, and the
guard bills it a turn for obeying.

So the rule is restated **net of the borrowed set** (and only net of it):

* omitting a borrowed field passes — it is not work the agent declined, it is work that is done;
* omitting a genuinely unresearched primary field is still refused, exactly as before;
* *asking* for a borrowed field is refused outright — Exa, unlike Sumble's own preflight, has no
  provider-side freshness check, so this guard is the only layer that can stop a paid re-buy on
  the qualitative path.

Both sides read ``born_complete_account_field_keys``, the same derivation the §6.1 state read and
the bundle compiler use, so what the agent is *told* is complete and what the guard *requires* can
never diverge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_contracts import (
    EntityResearchRuntimeContext,
    EntityResearchToolCall,
)
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
)
from clue_api.account_entity_research_composition import account_research_profile_sha256
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
)
from tests.api.test_account_entity_research_fresh_skip_db import (
    _CULTURE,
    _FUNDING,
    _HIRING,
    _MOVES,
    _PAIN,
    _QUESTION,
    _Fixture,
    _NestedConnFactory,
    _p2_envelope,
    _seed_p1_research,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

#: P1 already answered these, freshly and with evidence, so §6.2 makes them free for P2.
_BORROWED = (_PAIN, _MOVES, _HIRING)
#: P1's culture claim is 200d old against a 60d TTL; nothing ever answered recent funding.
_UNRESEARCHED = (_CULTURE, _FUNDING)


def _exa_primary_authorization(
    fixture: _Fixture, *, admitted: Sequence[str]
) -> EntityResearchJobAuthorization:
    """P2's job authority with Exa Deep as the **primary** source for every admitted field.

    The shared two-project envelope makes Exa a *fallback* (structured source first), which puts
    the first-call rule's ``primary`` set at zero and would make these assertions vacuous.
    """

    authorization = (
        _p2_envelope(
            fixture=fixture,
            admitted=admitted,
            profile_sha256=account_research_profile_sha256(),
        )
        .jobs[0]
        .authorization
    )
    selection = EntityResearchSelection.model_validate(
        authorization.selection.model_copy(
            update={
                "field_source_authority": tuple(
                    FieldSourceAuthority(field_key=key, source_keys=("exa_deep", "sumble_jobs"))
                    for key in admitted
                )
            }
        ).model_dump(mode="python")
    )
    return EntityResearchJobAuthorization.model_validate(
        authorization.model_copy(update={"selection": selection}).model_dump(mode="python")
    )


class _ContextOnly:
    """The only part of a runtime context ``authorize_tool`` reads (the fixture-file pattern)."""

    def __init__(self, authorization: EntityResearchJobAuthorization) -> None:
        self.authorization = authorization


def _call(field_keys: Sequence[str]) -> EntityResearchToolCall:
    return EntityResearchToolCall(
        tool_call_id=f"fi2-62-{'-'.join(field_keys) or 'empty'}",
        tool_name="research_account_deep",
        tool_version=1,
        tool_input_sha256="a" * 64,
        arguments={
            "field_keys": list(field_keys),
            "source_keys": ["exa_deep"],
            "questions": [_QUESTION],
        },
    )


async def _authorize(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    admitted: Sequence[str],
    field_keys: Sequence[str],
) -> None:
    guard = AccountResearchExecutionGuard(conn_factory=_NestedConnFactory(conn))
    await guard.authorize_tool(
        context=cast(
            EntityResearchRuntimeContext,
            _ContextOnly(_exa_primary_authorization(fixture, admitted=admitted)),
        ),
        call=_call(field_keys),
        journal_event_ref="entity-agent-journal:fi2-62",
    )


def test_fi2_62_a_prompt_obedient_omission_of_borrowed_fields_is_authorized() -> None:
    """The agent omits exactly what its state read called complete, and is not billed a turn."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn)
            await _authorize(
                conn,
                fixture=fixture,
                admitted=(*_BORROWED, _CULTURE),
                field_keys=(_CULTURE,),
            )

    run_async(scenario())


def test_fi2_62_a_lazy_omission_of_an_unresearched_primary_field_is_still_refused() -> None:
    """The rule is narrowed by the borrowed set, not dissolved: real drip-feeding still fails."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn)
            admitted = (*_BORROWED, *_UNRESEARCHED)
            with pytest.raises(
                AccountResearchAuthorityError,
                match="first Exa account call must include every primary Exa field",
            ):
                await _authorize(conn, fixture=fixture, admitted=admitted, field_keys=(_CULTURE,))
            # …and the honest first call — every *unresearched* primary field — is authorized.
            await _authorize(conn, fixture=fixture, admitted=admitted, field_keys=_UNRESEARCHED)

    run_async(scenario())


def test_fi2_62_asking_exa_to_re_buy_a_borrowed_field_is_refused() -> None:
    """No provider is paid for a fact already on file, however the agent phrases the request."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn)
            with pytest.raises(
                AccountResearchAuthorityError,
                match=f"cannot re-buy a field an existing fresh claim already answers: {_PAIN}",
            ):
                await _authorize(
                    conn,
                    fixture=fixture,
                    admitted=(*_BORROWED, *_UNRESEARCHED),
                    field_keys=(*_UNRESEARCHED, _PAIN),
                )

    run_async(scenario())
