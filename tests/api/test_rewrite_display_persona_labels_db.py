"""ARV2 D4-b: the one-shot that rewrites the personas stored inside generated display blocks.

The D4-b ruling moved every ``persona`` on contract v1 to display text. For a *live* payload that
is a read-layer change; for a display block it is not, because the block's body is written once at
generation time and served verbatim ever after — so every block written before the ruling keeps
saying ``economic_buyer`` to a marketer until something rewrites the row.

Two properties are what make the script safe to point at a real database, and both are proven here
against a hand-inserted block rather than a mocked body: it changes **only** the two persona paths
(the prose, the citations and every other key come back byte-identical), and it is **idempotent**
(a second pass finds nothing, because a persona already spelled as words maps to itself).
"""

from __future__ import annotations

import json
import uuid

import pytest
from scripts.rewrite_display_persona_labels import (
    rewrite_body,
    rewrite_display_persona_labels,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests._workspace import seed_workspace
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_d4b_rewrite"

#: A block body in the shape the D2 runner wrote before the ruling: two contact chips carrying the
#: vocabulary value, an item subject carrying it too, and one chip that is already display text.
_BODY: dict[str, object] = {
    "key": "contact-insights",
    "h1": "What the committee says",
    "empty": False,
    "intro": [{"text": "An intro sentence.", "claimIds": []}],
    "items": [
        {
            "id": "contact-insights-1",
            "h2": "Budget sits with Nick",
            "body": [{"text": "One sentence.", "claimIds": []}],
            "sendLine": None,
            "contactRefs": [
                {
                    "accountId": "a-1",
                    "contactId": "c-1",
                    "name": "Nick Fisher",
                    "title": "VP of Marketing",
                    "persona": "economic_buyer",
                },
                {
                    "accountId": "a-1",
                    "contactId": "c-2",
                    "name": "Vari Kaur",
                    "persona": "Champion",
                },
                {"accountId": "a-1", "contactId": "c-3", "name": "Tom Anthony"},
            ],
            "subject": {
                "accountId": "a-1",
                "contactId": "c-4",
                "name": "Ben Seri",
                "persona": "technical_evaluator",
            },
            "priority": 1,
            "newSinceLastVisit": False,
        }
    ],
}


async def _insert_block(conn: AsyncConnection, *, body: dict[str, object]) -> uuid.UUID:
    await seed_workspace(conn, WORKSPACE)
    block_id = uuid.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO display_block (
                display_block_id, workspace_id, subject_kind, subject_id, page, section_key,
                body_json, cited_claim_ids, model, prompt_version, recipe_version
            ) VALUES (
                :id, :ws, 'account', :subject, 'insights', 'contact-insights',
                CAST(:body AS jsonb), '{}', 'test-model', 'v0', 1
            )
            """
        ),
        {"id": block_id, "ws": WORKSPACE, "subject": uuid.uuid4(), "body": json.dumps(body)},
    )
    return block_id


def _personas(body: dict[str, object]) -> list[str]:
    item = body["items"][0]  # type: ignore[index]
    refs = [ref.get("persona") for ref in item["contactRefs"]]
    return [value for value in [*refs, item["subject"].get("persona")] if value is not None]


def test_rewrite_body_touches_the_personas_and_nothing_else() -> None:
    rewritten, changed = rewrite_body(_BODY)

    # Two vocabulary values became words; the chip that was already display text did not move,
    # and the chip with no persona at all did not grow one.
    assert changed == 2
    assert _personas(rewritten) == ["Economic buyer", "Champion", "Technical evaluator"]

    # Everything else is byte-identical: this is a display-copy correction, not a re-generation.
    def _without_personas(body: dict[str, object]) -> str:
        stripped = json.loads(json.dumps(body))
        item = stripped["items"][0]
        for ref in [*item["contactRefs"], item["subject"]]:
            ref.pop("persona", None)
        return json.dumps(stripped, sort_keys=True)

    assert _without_personas(rewritten) == _without_personas(_BODY)
    # And the input was not mutated in place.
    assert _personas(_BODY) == ["economic_buyer", "Champion", "technical_evaluator"]


def test_a_body_the_script_does_not_recognise_comes_back_unharmed() -> None:
    for body in ({"empty": True}, {"items": "not a list"}, {"items": [{"contactRefs": {}}]}):
        rewritten, changed = rewrite_body(body)
        assert changed == 0
        assert rewritten == body


def test_the_one_shot_rewrites_a_stored_block_and_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            block_id = await _insert_block(conn, body=_BODY)

            # A dry run reports the same work it would do, and writes nothing.
            preview = await rewrite_display_persona_labels(
                conn, workspace_id=WORKSPACE, dry_run=True
            )
            assert preview["blocks_rewritten"] == 1
            assert preview["personas_rewritten"] == 2
            stored = await _read(conn, block_id)
            assert _personas(stored) == ["economic_buyer", "Champion", "technical_evaluator"]

            report = await rewrite_display_persona_labels(conn, workspace_id=WORKSPACE)
            assert report["blocks_scanned"] == 1
            assert report["blocks_rewritten"] == 1
            assert report["personas_rewritten"] == 2
            assert report["blocks"][0]["section_key"] == "contact-insights"  # type: ignore[index]

            stored = await _read(conn, block_id)
            assert _personas(stored) == ["Economic buyer", "Champion", "Technical evaluator"]

            # Idempotent: nothing left to do, and the row is untouched.
            again = await rewrite_display_persona_labels(conn, workspace_id=WORKSPACE)
            assert again["blocks_rewritten"] == 0
            assert again["personas_rewritten"] == 0
            assert await _read(conn, block_id) == stored

    run_async(_run())


def test_a_superseded_block_is_history_and_is_left_alone() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            block_id = await _insert_block(conn, body=_BODY)
            await conn.execute(
                text("UPDATE display_block SET superseded_at = now() WHERE display_block_id = :id"),
                {"id": block_id},
            )
            report = await rewrite_display_persona_labels(conn, workspace_id=WORKSPACE)
            assert report["blocks_scanned"] == 0
            assert report["blocks_rewritten"] == 0
            assert _personas(await _read(conn, block_id)) == [
                "economic_buyer",
                "Champion",
                "technical_evaluator",
            ]

    run_async(_run())


async def _read(conn: AsyncConnection, block_id: uuid.UUID) -> dict[str, object]:
    row = (
        await conn.execute(
            text("SELECT body_json FROM display_block WHERE display_block_id = :id"),
            {"id": block_id},
        )
    ).scalar_one()
    return dict(row)
