"""Lossless, bounded overview reads without changing the historical read contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import build_agent_profile_registry, c6_roles_for_tool
from clue_api.arv2 import read_tools as reads
from clue_api.arv2.display.blocks import LiveBlock
from clue_api.arv2.display.recipes import SectionRecipe
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_toolbelt import PreconditionFailed
from tests.api.test_arv2_read_tools import _context, _FakeService
from tests.db.conftest import run_async

ACCOUNT = UUID("33333333-3333-5333-8333-333333333333")
WORKSPACE = "ws_overview_paging"
NOW = datetime(2026, 9, 27, tzinfo=UTC)


def _stored_blocks(monkeypatch: pytest.MonkeyPatch, *, large: bool = False) -> list[LiveBlock]:
    blocks = [
        LiveBlock(
            display_block_id=str(uuid4()),
            section_key=f"section-{index}",
            body_json={
                "intro": [f"Section {index}: " + ('文😀\\"\n' * 5000 if large else "text " * 400)],
                "status": "imported_unverified",
                "source_scope": "workspace_private",
                "source_url": f"https://source.example/{index}",
            },
            cited_claim_ids=tuple(str(uuid4()) for _ in range(400 if large else 1)),
            model="import",
            prompt_version="v1",
            recipe_version=1,
            generated_at=NOW,
        )
        for index in range(6)
    ]

    async def account(_conn: Any, *, workspace_id: str, account_entity_id: str) -> tuple[UUID, str]:
        if workspace_id != WORKSPACE or account_entity_id != str(ACCOUNT):
            raise reads.Arv2ReadRefused("account_not_found", "absent")
        return ACCOUNT, "An account"

    async def live(_conn: Any, **kwargs: Any) -> dict[str, LiveBlock]:
        assert kwargs == {
            "workspace_id": WORKSPACE,
            "subject_kind": "account",
            "subject_id": str(ACCOUNT),
            "page": "overview",
        }
        return {block.section_key: block for block in reversed(blocks)}

    async def recipes(_conn: Any, page: str, *, workspace_id: str) -> tuple[SectionRecipe, ...]:
        assert (page, workspace_id) == ("overview", WORKSPACE)
        # Deliberately non-lexical order, plus an orphaned stored section.
        return tuple(
            SectionRecipe("overview", f"section-{i}", "Heading", n, ())
            for n, i in enumerate([3, 1, 4, 0, 2])
        )

    monkeypatch.setattr(reads, "_account_in_workspace", account)
    monkeypatch.setattr(reads, "live_blocks", live)
    monkeypatch.setattr(reads, "read_recipes", recipes)
    return blocks


@pytest.mark.parametrize("large", [False, True])
@pytest.mark.parametrize("limit", [1, 3, 120])
def test_every_stored_section_is_reconstructible_under_the_full_receipt_budget(
    monkeypatch: pytest.MonkeyPatch, large: bool, limit: int
) -> None:
    blocks = _stored_blocks(monkeypatch, large=large)
    assert hasattr(reads, "read_account_overview"), "@3 needs a lossless overview read"

    async def scenario() -> None:
        collected: list[Any] = []
        offset = 0
        for _ in range(1000):
            page = await reads.read_account_overview(
                None,
                workspace_id=WORKSPACE,
                account_entity_id=str(ACCOUNT),
                offset=offset,
                limit=limit,
            )
            assert page.offset == offset
            assert 1 <= len(page.overview) <= limit
            assert reads.receipt_bytes(page.model_dump()) <= reads.READ_REFERENCES_BUDGET_BYTES
            assert page.claims == () and page.excluded == {}
            collected.extend(page.overview)
            if page.next_offset is None:
                assert page.truncated is False
                break
            assert page.truncated is True
            assert page.next_offset == offset + len(page.overview)
            offset = page.next_offset
        else:
            pytest.fail("overview pagination did not terminate")

        assert list(dict.fromkeys(chunk.section_key for chunk in collected)) == [
            "section-3",
            "section-1",
            "section-4",
            "section-0",
            "section-2",
            "section-5",
        ]
        for block in blocks:
            chunks = [
                chunk for chunk in collected if chunk.display_block_id == block.display_block_id
            ]
            assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
            assert {chunk.chunk_count for chunk in chunks} == {len(chunks)}
            combined = "".join(chunk.section_json for chunk in chunks)
            assert {chunk.section_sha256 for chunk in chunks} == {
                hashlib.sha256(combined.encode()).hexdigest()
            }
            assert json.loads(combined) == {
                "body_json": block.body_json,
                "cited_claim_ids": list(block.cited_claim_ids),
                "generated_at": NOW.isoformat(),
            }
            if not large:
                assert len(chunks) == 1

        empty = await reads.read_account_overview(
            None,
            workspace_id=WORKSPACE,
            account_entity_id=str(ACCOUNT),
            offset=len(collected),
            limit=1,
        )
        assert empty.overview == () and empty.next_offset is None and not empty.truncated

    run_async(scenario())


def test_legacy_versions_keep_their_exact_descriptors_and_overview_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stored_blocks(monkeypatch)
    for cls, digest in (
        (
            reads.ReadAccountResearchTool,
            "3c24d0caeca2a1ec1a7458fbe950e15ad2d174dfc4b30d1872f215a29162bc79",
        ),
        (
            reads.ReadAccountResearchV2Tool,
            "97e3f1dc122d321fa0d6165d65bfaf09f09b2de83cdf84d2e2331725e04bedd0",
        ),
    ):
        descriptor = cls(None).descriptor
        assert descriptor.input_schema_sha256 == digest
        assert (
            descriptor.output_schema_sha256
            == "1697e1587da18c201a767fbe1bea67fda72a31b7280d1f422182127434af44fe"
        )

    async def scenario() -> None:
        with pytest.raises(reads.Arv2ReadRefused) as exc:
            await reads.read_account_research(
                None,
                workspace_id=WORKSPACE,
                account_entity_id=str(ACCOUNT),
                section="overview",
                settings=Settings(_env_file=None),
                offset=1,
            )
        assert exc.value.code == "offset_not_paged"

    run_async(scenario())


def test_overview_checks_ambient_workspace_before_reading_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stored_blocks(monkeypatch)
    assert hasattr(reads, "read_account_overview"), "@3 needs a scoped overview read"

    async def scenario() -> None:
        for workspace, account in [("foreign", str(ACCOUNT)), (WORKSPACE, str(uuid4()))]:
            with pytest.raises(reads.Arv2ReadRefused) as exc:
                await reads.read_account_overview(
                    None, workspace_id=workspace, account_entity_id=account, offset=1, limit=1
                )
            assert exc.value.code == "account_not_found"

    run_async(scenario())


def test_only_design_pins_v3_and_the_default_and_head_remain_v2() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    assert registry.has("read_account_research", "3")
    assert registry.descriptor("read_account_research").version == "2"
    profiles = build_agent_profile_registry(registry)
    design = profiles.resolve(AgentRole.DESIGN)
    assert design.profile.version == "v3"
    assert c6_roles_for_tool("read_account_research@3") == (AgentRole.DESIGN,)
    assert c6_roles_for_tool("read_account_research@2") == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("read_account_research@1") == ()
    assert "read_account_research@3" in {pin.address for pin in design.profile.tools}
    assert "read_account_research@2" in {
        pin.address for pin in profiles.resolve(AgentRole.HEAD_OF_ABM).profile.tools
    }


def test_v3_tool_uses_ambient_scope_and_preserves_claim_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stored_blocks(monkeypatch)
    assert hasattr(reads, "ReadAccountResearchV3Tool"), "design needs an explicitly versioned tool"

    class Service(_FakeService):
        async def read_account_overview(self, **kwargs: Any) -> Any:
            # The tool's ambient workspace is authoritative, not the model input.
            assert kwargs["workspace_id"] == _context().workspace_id
            return await reads.read_account_overview(None, **{**kwargs, "workspace_id": WORKSPACE})

    async def scenario() -> None:
        tool = reads.ReadAccountResearchV3Tool(
            Service(refusal=reads.Arv2ReadRefused("account_not_researched", "absent"))
        )
        result = await tool.invoke(
            reads.ReadAccountResearchV3Input(account_entity_id=str(ACCOUNT), limit=1), _context()
        )
        assert result.version == "3"
        assert result.references["next_offset"] == 1
        assert result.references["overview"][0]["chunk_count"] == 1
        with pytest.raises(PreconditionFailed) as exc:
            await tool.invoke(
                reads.ReadAccountResearchV3Input(account_entity_id=str(ACCOUNT), section="claims"),
                _context(),
            )
        assert exc.value.reason_codes == ("account_not_researched",)

    run_async(scenario())
