"""D2 T6 exit gate: the page orchestrator, over a real database and a keyed provider double.

What a page *is* only becomes true here: sections written in parallel, each one persisted as a
block, the ones with nothing to say skipped rather than invented, an activity event that says the
page was written, and a second call that serves the stored page without spending a cent.

The provider is a :class:`RoutingTransport` — the lane's one permitted double (Global Constraint
3), keyed by the section the request asks for instead of by call order, because the sections of a
page are written concurrently and their order on the wire is not a fact any assertion may rely on.
Everything below the transport is real: the claims, the recipes, the blocks, the evidence read.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Collection, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.display.blocks import compose_display_block, live_blocks
from clue_api.arv2.display.gather import ClientContext, SectionInput, SubjectRef
from clue_api.arv2.display.page import (
    PageResult,
    _write_section,
    default_runner_factory,
    ensure_page,
)
from clue_api.arv2.display.recipes import read_recipes, recipes_for
from clue_api.arv2.display.render import DisplayClaim
from clue_api.arv2.display.runner import LunaSectionRunner
from clue_api.arv2.errors import Arv2Error
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2.transport import HttpRequest, HttpResponse
from clue_config import Secrets, Settings
from clue_core import EntityType, ExtractionMethod
from tests.arv2.display._seed import Seeded, seed_display_fixture, write_claim
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_page"

#: Verbatim checking on, so the page's ``checks`` carry the annotation law 6 asks for.
SETTINGS = Settings(
    _env_file=None,
    verification_enabled=False,
    evidence_verbatim_check="on",
    arv2_display_max_parallel=4,
)

#: The cost the fake provider reports per call — the page's spend is the sum of these.
CALL_COST = 0.0044

CONTACT_SECTIONS = tuple(recipe.section_key for recipe in recipes_for("contact"))
INSIGHTS_SECTIONS = tuple(recipe.section_key for recipe in recipes_for("insights"))

#: The two insights sections that own no block: they render another page's stored body.
SHARED_INSIGHTS_SECTIONS = tuple(
    recipe.section_key for recipe in recipes_for("insights") if recipe.shared_from is not None
)
#: The four insights sections the page itself writes.
OWNED_INSIGHTS_SECTIONS = tuple(
    recipe.section_key for recipe in recipes_for("insights") if recipe.shared_from is None
)

#: The two insights sections the seeded workspace holds no claim for.
EMPTY_INSIGHTS_SECTIONS = ("tools-they-already-use", "how-they-sell")

_MARKER = "# WRITE ONLY THIS SECTION NOW: "


# -- the provider double ---------------------------------------------------------------------


def _section_asked_for(request: HttpRequest) -> str:
    """The section key the request's suffix names — the only routing key the double needs."""
    body = json.loads(request.body or b"{}")
    content = body["messages"][1]["content"]
    return content.split(_MARKER)[1].split("\n")[0].strip()


def _reply(section_key: str) -> dict[str, Any]:
    """One canned section: an intro and one item, both citing ``c1``.

    ``c1`` is the first alias of every non-empty section (``alias_table`` numbers from one), so a
    single body is a valid, cited answer for whichever section the runner happens to ask about.
    """
    return {
        "section": {
            "key": section_key,
            "intro": [{"text": f"An opening line for {section_key}.", "claimIds": ["c1"]}],
            "items": [
                {
                    "h2": f"The one {section_key} card",
                    "body": [{"text": f"A cited sentence for {section_key}.", "claimIds": ["c1"]}],
                }
            ],
        }
    }


class RoutingTransport:
    """A provider double keyed by the section asked for, not by call order.

    Concurrency is the reason it exists: the page writes its sections under a semaphore, so the
    order requests reach a transport is a scheduling detail. Its own bookkeeping is taken under a
    lock so a count asserted afterwards is the count that actually happened.
    """

    def __init__(
        self,
        *,
        allowed: bool = True,
        scripted: Mapping[str, list[dict[str, Any]]] | None = None,
        broken: Collection[str] = (),
    ) -> None:
        self._allowed = allowed
        self._scripted = {key: list(value) for key, value in (scripted or {}).items()}
        self._broken = frozenset(broken)
        self._lock = threading.Lock()
        self.sections: list[str] = []
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        section_key = _section_asked_for(request)
        with self._lock:
            if not self._allowed:
                raise AssertionError(f"the provider was called for {section_key!r}")
            self.sections.append(section_key)
            self.requests.append(request)
            queue = self._scripted.get(section_key)
            reply = queue.pop(0) if queue else _reply(section_key)
        # A "broken" section answers in prose: a real, paid-for call whose reply is unusable.
        content = (
            "I am sorry, I cannot write that section."
            if section_key in self._broken
            else json.dumps(reply)
        )
        body = {
            "id": f"gen-{section_key}",
            "choices": [{"message": {"content": content}}],
            "usage": {"cost": CALL_COST},
        }
        return HttpResponse(status=200, headers={}, body=json.dumps(body).encode())


def _factory(transport: RoutingTransport) -> Any:
    """One runner per section, each with its own caller over the section's sinks — the
    production factory's shape."""

    def build(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        return LunaSectionRunner(
            ProviderCaller(
                transport=transport, raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
            ),
            api_key=SecretStr("test-key"),
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-5.6-luna",
            timeout_s=30.0,
        )

    return build


# -- helpers ---------------------------------------------------------------------------------


async def _contact_page(
    conn: AsyncConnection, seeded: Seeded, transport: RoutingTransport, **kwargs: Any
) -> PageResult:
    kwargs.setdefault("artifacts", FakeArtifacts())
    kwargs.setdefault("spend_conn_factory", conn_session_factory(conn))
    return await ensure_page(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="contact",
        subject_id=str(seeded.nick),
        page="contact",
        settings=SETTINGS,
        runner_factory=_factory(transport),
        **kwargs,
    )


async def _account_page(
    conn: AsyncConnection,
    seeded: Seeded,
    transport: RoutingTransport,
    page: str,
    **kwargs: Any,
) -> PageResult:
    kwargs.setdefault("artifacts", FakeArtifacts())
    kwargs.setdefault("spend_conn_factory", conn_session_factory(conn))
    return await ensure_page(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="account",
        subject_id=str(seeded.account),
        page=page,
        settings=SETTINGS,
        runner_factory=_factory(transport),
        **kwargs,
    )


async def _overview_page(
    conn: AsyncConnection, seeded: Seeded, transport: RoutingTransport, **kwargs: Any
) -> PageResult:
    return await _account_page(conn, seeded, transport, "overview", **kwargs)


async def _insights_page(
    conn: AsyncConnection, seeded: Seeded, transport: RoutingTransport, **kwargs: Any
) -> PageResult:
    return await _account_page(conn, seeded, transport, "insights", **kwargs)


async def _stored_overview(conn: AsyncConnection, seeded: Seeded) -> dict[str, Any]:
    """The account's overview page as it is stored — the owner side of the shared section."""
    recipes = await read_recipes(conn, "overview", workspace_id=seeded.workspace_id)
    blocks = await live_blocks(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="account",
        subject_id=str(seeded.account),
        page="overview",
    )
    return compose_display_block("overview", recipes, blocks)


async def _events(conn: AsyncConnection, workspace_id: str) -> list[Mapping[str, Any]]:
    rows = (
        await conn.execute(
            text(
                """
                SELECT kind, actor_kind, actor_user_id, text, action, project_id,
                       account_entity_id, ref_json ->> 'contact_id' AS contact_id
                FROM account_activity_event
                WHERE workspace_id = :workspace_id
                ORDER BY occurred_at, event_id
                """
            ),
            {"workspace_id": workspace_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def _block_counts(conn: AsyncConnection, workspace_id: str) -> tuple[int, int]:
    """``(live, superseded)`` display-block rows in the workspace."""
    row = (
        (
            await conn.execute(
                text(
                    """
                SELECT count(*) FILTER (WHERE superseded_at IS NULL) AS live,
                       count(*) FILTER (WHERE superseded_at IS NOT NULL) AS retired
                FROM display_block WHERE workspace_id = :workspace_id
                """
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one()
    )
    return int(row["live"]), int(row["retired"])


def _cited_in(display_block: Mapping[str, Any], section_key: str) -> set[str]:
    """Every claim id the composed block cites inside one section."""
    section = next(item for item in display_block["sections"] if item["key"] == section_key)
    found: set[str] = set()
    for sentence in section.get("intro", []):
        found.update(sentence.get("claimIds", []))
    for item in section["items"]:
        for sentence in item["body"]:
            found.update(sentence.get("claimIds", []))
            for segment in sentence.get("segments", []):
                found.update(segment.get("claimIds", []))
        send_line = item.get("sendLine")
        if send_line:
            found.update(send_line.get("claimIds", []))
    return found


# -- the tests ---------------------------------------------------------------------------------


def test_a_contact_page_writes_every_section_that_has_input_and_records_one_event() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            result = await _contact_page(conn, seeded, transport)

            # Every contact section of the seeded workspace has at least one claim.
            assert result.generated == CONTACT_SECTIONS
            assert result.regenerated == ()
            assert result.skipped_empty == ()
            assert result.stale_served == ()
            assert sorted(transport.sections) == sorted(CONTACT_SECTIONS)

            # The composed page: recipe order, bare H1s, one stored block per section.
            block = result.display_block
            assert block["page"] == "contact"
            assert [section["key"] for section in block["sections"]] == list(CONTACT_SECTIONS)
            assert [section["h1"] for section in block["sections"]] == [
                recipe.h1 for recipe in recipes_for("contact")
            ]
            assert all(not section["empty"] for section in block["sections"])
            assert await _block_counts(conn, seeded.workspace_id) == (6, 0)

            # The floor: no unsafe claim is cited anywhere but the restricted section.
            unsafe = {seeded.claims["hobby_unsafe"], seeded.claims["reputation_risk"]}
            for section_key in CONTACT_SECTIONS:
                cited = _cited_in(block, section_key)
                if section_key == "do-not-mention":
                    assert cited & unsafe
                else:
                    assert not cited & unsafe
                assert result.checks[section_key]["floor_regenerated"] is False
                assert isinstance(result.checks[section_key]["verbatim"], dict)

            # The evidence drawer: one card per cited id, and never a field key.
            assert {ref["claimId"] for ref in result.evidence} == set(result.cited_claim_ids)
            assert all("fieldKey" not in ref and "field_key" not in ref for ref in result.evidence)

            assert result.cost_usd == Decimal(str(CALL_COST)) * 6

            events = await _events(conn, seeded.workspace_id)
            assert len(events) == 1
            event = events[0]
            assert event["kind"] == "summary"
            assert event["actor_kind"] == "clue" and event["actor_user_id"] is None
            assert event["text"] == "Contact page written"
            assert event["action"] == "contact generated"
            assert str(event["account_entity_id"]) == str(seeded.account)
            assert event["contact_id"] == str(seeded.nick)
            assert event["project_id"] is None

    run_async(_run())


def test_a_second_call_serves_the_stored_page_without_calling_the_provider() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            first = await _contact_page(conn, seeded, RoutingTransport())
            again = await _contact_page(conn, seeded, RoutingTransport(allowed=False))

            assert again.generated == ()
            assert again.regenerated == ()
            assert again.cost_usd == Decimal(0)
            assert again.display_block == first.display_block
            assert again.cited_claim_ids == first.cited_claim_ids
            assert await _block_counts(conn, seeded.workspace_id) == (6, 0)
            assert len(await _events(conn, seeded.workspace_id)) == 1

    run_async(_run())


def test_a_new_claim_refreshes_both_sections_that_select_it() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            await _contact_page(conn, seeded, RoutingTransport())

            # Hobby evidence is reusable in Openers and Miscellaneous; both must refresh.
            await write_claim(
                conn,
                seeded.claims,
                label="hobby_new",
                workspace_id=seeded.workspace_id,
                entity_id=seeded.nick,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.hobby",
                value_json=["Runs a weekend bread-baking club"],
                signal_priority=2,
                evidence_span="my weekend bread club",
                extraction_method=ExtractionMethod.SCRAPE,
            )

            served = await _contact_page(conn, seeded, RoutingTransport(allowed=False))
            assert served.generated == ()
            assert served.stale_served == ("openers", "miscellaneous")

            transport = RoutingTransport()
            rewritten = await _contact_page(conn, seeded, transport, regenerate_stale=True)
            assert rewritten.generated == ("openers", "miscellaneous")
            assert rewritten.regenerated == ("openers", "miscellaneous")
            assert rewritten.stale_served == ()
            assert sorted(transport.sections) == ["miscellaneous", "openers"]
            assert await _block_counts(conn, seeded.workspace_id) == (6, 2)

            events = await _events(conn, seeded.workspace_id)
            assert len(events) == 2
            assert events[1]["action"] == "contact regenerated"

    run_async(_run())


def test_force_supersedes_every_live_block_and_rewrites_the_whole_page() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            await _contact_page(conn, seeded, RoutingTransport())

            transport = RoutingTransport()
            forced = await _contact_page(conn, seeded, transport, force=True)
            assert forced.generated == CONTACT_SECTIONS
            assert forced.regenerated == CONTACT_SECTIONS
            assert sorted(transport.sections) == sorted(CONTACT_SECTIONS)
            assert await _block_counts(conn, seeded.workspace_id) == (6, 6)

            events = await _events(conn, seeded.workspace_id)
            assert [event["action"] for event in events] == [
                "contact generated",
                "contact regenerated",
            ]

    run_async(_run())


def test_an_account_page_skips_the_sections_the_research_never_filled() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            result = await ensure_page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="insights",
                settings=SETTINGS,
                runner_factory=_factory(transport),
                artifacts=FakeArtifacts(),
                spend_conn_factory=conn_session_factory(conn),
            )

            assert result.skipped_empty == EMPTY_INSIGHTS_SECTIONS
            # Only the four owned recipes are written at all — the two shared ones render their
            # owners' blocks, and no owner page has been written in this test.
            assert result.generated == tuple(
                key for key in OWNED_INSIGHTS_SECTIONS if key not in EMPTY_INSIGHTS_SECTIONS
            )
            assert sorted(transport.sections) == sorted(result.generated)

            # The page grammar is fixed: a skipped section is served, and it is honestly empty.
            block = result.display_block
            assert [section["key"] for section in block["sections"]] == list(INSIGHTS_SECTIONS)
            empty = {section["key"] for section in block["sections"] if section["empty"]}
            assert empty == set(EMPTY_INSIGHTS_SECTIONS) | set(SHARED_INSIGHTS_SECTIONS)

            events = await _events(conn, seeded.workspace_id)
            assert len(events) == 1
            assert events[0]["text"] == "Insights written"
            assert events[0]["action"] == "insights generated"
            assert events[0]["contact_id"] is None

    run_async(_run())


def test_the_default_runner_factory_refuses_to_build_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI must fail before it touches a database, so the factory raises at build time."""
    monkeypatch.delenv("CLUE_OPENROUTER_API_KEY", raising=False)
    blank = Secrets(_env_file=None, openrouter_api_key=SecretStr(""))
    with pytest.raises(Arv2Error, match="CLUE_OPENROUTER_API_KEY is unset"):
        default_runner_factory(SETTINGS, blank)

    missing = Secrets(_env_file=None, openrouter_api_key=None)
    with pytest.raises(Arv2Error, match="CLUE_OPENROUTER_API_KEY is unset"):
        default_runner_factory(SETTINGS, missing)

    present = Secrets(_env_file=None, openrouter_api_key=SecretStr("k"))
    runner = default_runner_factory(SETTINGS, present)(BufferedRawSink(), BufferedLedger())
    assert isinstance(runner, LunaSectionRunner)


def test_a_section_the_model_could_not_write_is_reported_failed_and_never_stored() -> None:
    """A transient provider failure must not become a permanently blank section.

    The runner already retries an unusable reply once and then answers honestly with
    ``reply_invalid``. Storing that empty draft would serve the section as ``empty`` on every
    later visit until something made it stale — so it is not stored at all, and the next call
    treats it as the missing section it still is.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            broken = RoutingTransport(broken={"openers"})
            result = await _contact_page(conn, seeded, broken)

            assert result.failed == ("openers",)
            assert "openers" not in result.generated
            assert result.generated == tuple(key for key in CONTACT_SECTIONS if key != "openers")
            # Two calls for the section it could not write: the runner's own single retry.
            assert broken.sections.count("openers") == 2
            # The failure is still legible to an operator.
            assert result.checks["openers"]["reply_invalid"] is True
            assert result.checks["openers"]["reply_retried"] is True

            assert await _block_counts(conn, seeded.workspace_id) == (5, 0)
            section = next(
                item for item in result.display_block["sections"] if item["key"] == "openers"
            )
            assert section["empty"] is True and section["items"] == []

            # Five sections were stored, so the page was written and the feed says so once.
            events = await _events(conn, seeded.workspace_id)
            assert [event["action"] for event in events] == ["contact generated"]

            # The next call retries it as an ordinary missing section.
            transport = RoutingTransport()
            retry = await _contact_page(conn, seeded, transport)
            assert retry.generated == ("openers",)
            assert retry.failed == ()
            assert transport.sections == ["openers"]
            assert await _block_counts(conn, seeded.workspace_id) == (6, 0)
            written = next(
                item for item in retry.display_block["sections"] if item["key"] == "openers"
            )
            assert written["empty"] is False

    run_async(_run())


# -- the floor's regenerate path ----------------------------------------------------------------

# The section input below is built by hand, and it has to be: ``gather_section_inputs`` withholds
# every ``outreach_safe=false`` row from a non-restricted section, and a restricted section has no
# unsafe rows *to* violate — so no input the real gather produces can make ``check_floor`` fail.
# The floor is the mechanical backstop for the case where that filter or the prompt was not
# enough, and this is the only honest way to drive it end to end (``test_floor.py`` builds its
# inputs the same way).

SAFE_CLAIM = DisplayClaim(
    claim_id="11111111-1111-4111-8111-111111111111",
    field_key="contact.facet.hobby",
    value="Runs a cocktail channel",
    quote="I run the Cocktail Chemistry channel",
    observed_at="2026-06-17",
    priority=1,
    outreach_safe=True,
    subject="Nick Fisher",
    media_timestamp=None,
    use_class=None,
    source_url="https://example.test/post",
    entity_id="22222222-2222-4222-8222-222222222222",
    extraction_method="llm",
    source_key="exa_search",
    collected_at=datetime(2026, 6, 18, tzinfo=UTC),
)
UNSAFE_CLAIM = replace(
    SAFE_CLAIM,
    claim_id="33333333-3333-4333-8333-333333333333",
    value="Posts about a family bereavement",
    quote="a post about a family bereavement",
    priority=3,
    outreach_safe=False,
)
FLOOR_SUBJECT = SubjectRef(
    kind="contact",
    id=SAFE_CLAIM.entity_id,
    name="Nick Fisher",
    account_id="44444444-4444-4444-8444-444444444444",
    account_name="Zafran Security",
    account_domain="zafran.io",
)


def _cited_reply(section_key: str, aliases: list[str]) -> dict[str, Any]:
    return {
        "section": {
            "key": section_key,
            "items": [
                {
                    "h2": "An opener",
                    "body": [{"text": "One cited sentence.", "claimIds": aliases}],
                }
            ],
        }
    }


def test_a_section_that_cites_an_unsafe_claim_is_rewritten_once_without_it() -> None:
    openers = next(recipe for recipe in recipes_for("contact") if recipe.section_key == "openers")
    section = SectionInput(recipe=openers, claims=(SAFE_CLAIM, UNSAFE_CLAIM), deduped={})
    # ``alias_table`` orders by priority, so c1 is the safe claim and c2 the unsafe one.
    transport = RoutingTransport(
        scripted={
            "openers": [
                _cited_reply("openers", ["c1", "c2"]),
                _cited_reply("openers", ["c1"]),
            ]
        }
    )

    async def _run() -> None:
        written = await _write_section(
            page="contact",
            subject=FLOOR_SUBJECT,
            client=ClientContext(name="Clue", what_we_sell="ABM orchestration"),
            recipes=recipes_for("contact"),
            section=section,
            people=[FLOOR_SUBJECT],
            settings=SETTINGS,
            runner_factory=_factory(transport),
            raw=BufferedRawSink(),
            ledger=BufferedLedger(),
            semaphore=asyncio.Semaphore(1),
        )
        assert written.draft.checks["floor_regenerated"] is True
        assert written.draft.cited_claim_ids == [SAFE_CLAIM.claim_id]
        assert transport.sections == ["openers", "openers"]
        # The rewrite is told which alias it may not use, in the same alias table it was given.
        second = json.loads(transport.requests[1].body or b"{}")["messages"][1]["content"]
        assert "c2" in second.split(_MARKER)[1]

    asyncio.run(_run())


def test_the_page_lands_its_provider_spend_on_the_ledger_with_the_workspace_stamp() -> None:
    """Slice 1b: one result row per section call, workspace-stamped, no project / run / job,
    each citing the artifact its raw body became; the page's cost is the rows' sum."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            artifacts = FakeArtifacts()
            result = await _contact_page(conn, seeded, transport, artifacts=artifacts)
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider, operation, project_id, project_run_id, "
                            " entity_research_job_id, cost_usd, response_artifact_key, extras_json "
                            "FROM provider_call_ledger "
                            "WHERE workspace_id = :ws AND phase = 'result' ORDER BY recorded_at"
                        ),
                        {"ws": seeded.workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == len(transport.sections)
            assert {(r["provider"], r["operation"]) for r in rows} == {
                ("openrouter", "chat/completions")
            }
            assert all(
                r["project_id"] is None
                and r["project_run_id"] is None
                and r["entity_research_job_id"] is None
                for r in rows
            )
            assert sum((r["cost_usd"] for r in rows), Decimal(0)) == result.cost_usd
            assert all(r["response_artifact_key"] for r in rows)
            assert len(artifacts.bodies) == len(rows)

    run_async(_run())


def test_the_spend_is_drained_through_the_injected_factory_not_the_page_connection() -> None:
    """D2: the script hands ``transaction`` as the spend factory so a rolled-back --dry-run page
    still records its money; the page never drains on its own connection."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            opened: list[int] = []

            @asynccontextmanager
            async def spend_factory() -> AsyncIterator[AsyncConnection]:
                opened.append(1)
                yield conn

            await _contact_page(conn, seeded, RoutingTransport(), spend_conn_factory=spend_factory)
            assert opened == [1]

    run_async(_run())


def test_a_fully_stored_read_opens_no_spend_connection_at_all() -> None:
    """Nothing buffered, nothing to drain: a page whose every section is already stored must not
    reach for a spend connection it has no row to write on."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            opened: list[int] = []

            @asynccontextmanager
            async def spend_factory() -> AsyncIterator[AsyncConnection]:
                opened.append(1)
                yield conn

            await _contact_page(conn, seeded, RoutingTransport(), spend_conn_factory=spend_factory)
            assert opened == [1]

            opened.clear()
            again = await _contact_page(
                conn,
                seeded,
                RoutingTransport(allowed=False),
                spend_conn_factory=spend_factory,
            )
            assert again.generated == ()
            assert again.regenerated == ()
            assert again.cost_usd == Decimal(0)
            assert opened == []

    run_async(_run())


# -- shared blocks ------------------------------------------------------------------------------


def test_the_insights_page_considers_five_owned_sections_and_shares_the_other_two() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            # Owners first: Nick's contact page and the account overview.
            await _contact_page(conn, seeded, transport)
            await _overview_page(conn, seeded, transport)
            written_before = len(transport.sections)

            result = await _insights_page(conn, seeded, transport)

            # Only the five OWNED recipes are candidates. Two of them match no claim in this
            # fixture (no tech-stack, no resonance rows), so they are skipped rather than
            # written — the set the page *considered* is still exactly the five.
            assert sorted(result.generated + result.skipped_empty) == sorted(
                [
                    "buying-signals",
                    "money-and-momentum",
                    "tools-they-already-use",
                    "how-they-sell",
                    "miscellaneous",
                ]
            )
            assert result.generated == ("buying-signals", "money-and-momentum", "miscellaneous")
            assert "context-only" not in transport.sections[written_before:]
            assert not any(s["key"] == "contact-insights" for s in result.display_block["sections"])
            block = result.display_block
            context = next(s for s in block["sections"] if s["key"] == "context-only")
            watch = _cited_in(await _stored_overview(conn, seeded), "watch-outs")
            assert _cited_in(block, "context-only") == watch and not context["empty"]

    run_async(_run())
