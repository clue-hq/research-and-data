"""The prerequisite set every ARV2 launch test needs: a spine, a confirmed ICP, and its pin.

Both launches — R2's account/person research and R4's discovery — start at the same door: a
project that has pinned one confirmed ``icp-definition`` document version. Seeding that is fifty
lines of spine writes, and two test modules writing them twice is two chances for the fixtures to
drift apart and stop proving the same thing. So the seed lives here once, and each test module
imports it.

:data:`ICP_BODY` is the **real** confirmed Clue ICP document, ``hard_gates`` and all, rather than a
stub: the discovery launch compiles a brief out of those gates before it writes a row, so a body
without them could not be launched against at all. The account launch never reads the gates, so
using the real document costs it nothing.
"""

# ruff: noqa: E501 — ``ICP_BODY`` is the confirmed document copied verbatim from
# ``.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md``; rewrapping its YAML would make the
# fixture something other than the document the lane is pinned to.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth.store import create_platform_user
from clue_config import Settings
from clue_core import EntityId
from clue_fleet import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_research.identity import insert_account_entity
from clue_spine import confirm_project_product_set, create_product
from clue_storage import artifact_key, content_address
from clue_storage.artifacts import record_artifact
from clue_storage.fs import FsStorage
from tests._workspace import seed_project

WORKSPACE = "ws_r2_launch"
USER_ID = "usr_r2_launch"
ICP_KEY = "clue-abm-buyers"

#: The confirmed Clue ICP document. Its front matter is the program R4 compiles a discovery brief
#: from (the four hard gates, the exclusions), and its body's first paragraph is the buyer sentence
#: the long-list query is built out of.
ICP_BODY = """---
kind: icp-definition
icp_key: clue-abm-buyers
version: 1
status: confirmed
hard_gates:
  - key: geography
    rule: "US-headquartered"
    test: "The HQ city and state on the company's own site, its LinkedIn page, or its funding announcement dateline is in the United States."
  - key: stage
    rule: "A named, priced round of Series A or later, announced within the last 36 months"
    test: "A dated announcement (press release, lead investor's post, or the company's own newsroom) that names the round and at least one investor. A seed-only, bootstrapped, public or PE-owned company is recorded as outside the stated stage — a verdict for the human, never a reason to stop researching. A self-funded operator is recorded as unclear pending master plan D9's equivalence clause."
  - key: hiring
    rule: "Actively hiring now, with at least one open go-to-market role"
    test: "At least one requisition listed today on the company's own careers page or ATS board with a GTM title: sales, marketing, growth, ABM, demand generation, SDR or BDR, partnerships, revenue operations."
  - key: intent
    rule: "At least one citable, dated buying-intent signal"
    test: "One Tier-1 signal (Q1 to Q4 below) or two Tier-2 signals (Q5 to Q10 below), each with a verbatim quote and the URL it came from."
exclusions:
  - "Sells to consumers (B2C)"
  - "Pure self-serve product-led growth: public signup, published low-tier pricing, no talk-to-sales path"
  - "An enterprise ABM or personalization platform already installed: 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic"
  - "A direct competitor: sells ABM orchestration, AI SDR or GTM agents, personalized-microsite or intent tooling"
  - "Public, PE-owned, or more than 800 employees"
  - "Non-US headquarters"
  - "Below Series A: pre-seed, seed, bootstrapped, grant-funded"
  - "Clue itself and any Clue-affiliated entity"
---

# Who we sell to

US B2B vertical SaaS companies with a priced round behind them, thirty to three hundred people,
selling to a named list of accounts rather than a funnel, whose go-to-market team is hiring
humans to solve throughput.

## How they buy

A small team runs the motion: the marketer who owns the list is the champion, and the round that
was earmarked for expansion is why the economic buyer signs.
"""


@dataclass
class FakeQueue:
    """Records every offer, and dedups by key the way the real queue does.

    A launch itself never touches this: it is handed to the lane's ``enqueue_*`` function, which
    the caller runs *after* the launch transaction commits.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    trace: list[str] | None = None

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        work_id: WorkId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, Any] | None = None,
        reopen_terminal: bool = False,
        only_if_work_idle: bool = False,
    ) -> bool:
        if self.trace is not None:
            self.trace.append("enqueue")
        seen = any(call["dedup_key"] == dedup_key for call in self.calls)
        self.calls.append(
            {
                "kind": kind,
                "work_id": work_id,
                "dedup_key": dedup_key,
                "priority": priority,
                "payload": payload,
                "reopen_terminal": reopen_terminal,
                "only_if_work_idle": only_if_work_idle,
            }
        )
        # A duplicate dedup key is a pure no-op at the real queue (``reopen_terminal=False``),
        # which is what makes re-offering a replayed run's jobs safe.
        return not seen


@dataclass(frozen=True)
class IcpFixture:
    workspace_id: str
    project_id: str
    brand_id: str
    accounts: tuple[EntityId, ...]
    icp_document_id: UUID
    icp_artifact_key: str
    icp_artifact_sha256: str
    selection_version: int


def settings_for(**overrides: Any) -> Settings:
    """Settings with no ``.env`` underneath it — a test's flags are the test's own, never a box's."""
    return Settings(_env_file=None, **overrides)


async def seed_icp_document(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    brand_id: str,
    body: str = ICP_BODY,
    kind: str = "icp-definition",
    status: str = "confirmed",
    path: str = "audience/icp-clue-abm-buyers.md",
    project_id: str | None = None,
    version: int = 1,
) -> tuple[UUID, str, str]:
    """Register one ``brand_knowledge_document`` + its artifact, the way the loader does.

    ``project_id`` seeds the row in a *project's* scope rather than the brand's — the shape ICP
    authoring writes for a project-local variant. It is part of the document's identity here, so a
    brand row and a project's variant of one path get different ids and coexist, exactly as the
    scoped unique index allows.

    ``version`` seeds a later link of one path's version chain (a pinned v2 with a superseded v1
    behind it). It joins the derived id only when it is not 1, so every existing caller's document
    id is exactly the id it was before this parameter existed.
    """
    rendered = body.encode("utf-8")
    sha = content_address(rendered)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(rendered),
        source_key="arv2:test:knowledge_document",
    )
    await storage.put(key, rendered, media_type="text/markdown")
    document_id = uuid5(
        UUID(int=0),
        f"{workspace_id}:{project_id or ''}:{path}:{status}"
        + ("" if version == 1 else f":v{version}"),
    )
    await conn.execute(
        text(
            """
            INSERT INTO brand_knowledge_document
                (document_id, workspace_id, brand_id, project_id, folder, path, kind, version,
                 status, artifact_key, artifact_sha256)
            VALUES
                (:document_id, :workspace_id, :brand_id, :project_id, :folder, :path, :kind,
                 :version, :status, :artifact_key, :artifact_sha256)
            """
        ),
        {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "project_id": project_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "version": version,
            "status": status,
            "artifact_key": key,
            "artifact_sha256": sha,
        },
    )
    return document_id, key, sha


async def pin_icp(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    document_id: UUID,
    artifact_key_: str,
    artifact_sha256: str,
    icp_key: str = ICP_KEY,
    user_id: str = USER_ID,
) -> None:
    """Append the project's ICP pin, the way the gate approval does.

    Written as a row rather than through ``pin_project_icp`` so a test can pin a document the
    approval path would never mint (a proposal, a malformed body) and prove the launch refuses it
    by name instead of researching against it.
    """
    await conn.execute(
        text(
            "INSERT INTO project_icp_pin ("
            "  workspace_id, project_id, pin_seq, brand_id, document_id, icp_key, "
            "  artifact_key, artifact_sha256, product_selection_version, pinned_by_user_id"
            ") SELECT :workspace_id, :project_id, COALESCE(MAX(pin_seq), 0) + 1, :brand_id, "
            "  :document_id, :icp_key, :artifact_key, :artifact_sha256, NULL, :user_id "
            "FROM project_icp_pin WHERE project_id = :project_id"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "brand_id": brand_id,
            "document_id": document_id,
            "icp_key": icp_key,
            "artifact_key": artifact_key_,
            "artifact_sha256": artifact_sha256,
            "user_id": user_id,
        },
    )


async def seed_icp_fixture(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str = WORKSPACE,
    user_id: str = USER_ID,
    account_records: tuple[tuple[str, str], ...] = (
        ("Probook", "probook.ai"),
        ("Zafran", "zafran.io"),
    ),
    document_path: str = "audience/icp-clue-abm-buyers.md",
) -> IcpFixture:
    """The whole launch prerequisite set: spine, a confirmed product set, accounts, a confirmed ICP.

    Deliberately NOT seeded: an ``icp_spec`` row, an ``account_research_directive``, or any Stage-0
    pin on the project run — a launch must need none of them (standing rule item 5). The one pin it
    does need is the project's own ICP pin, which is a record of a human approval, not Stage-0
    machinery.
    """
    project = await seed_project(conn, workspace_id)
    await create_platform_user(conn, user_id=user_id, display_name="R2 launch test")
    product = await create_product(
        conn, brand_id=project.brand_id, workspace_id=project.workspace_id, name="Clue"
    )
    confirmed = await confirm_project_product_set(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        product_ids=[str(product.product_id)],
        gate_id=uuid4(),
        confirmed_by_user_id=user_id,
    )
    assert confirmed is not None
    accounts: list[EntityId] = []
    for name, domain in account_records:
        accounts.append(
            await insert_account_entity(
                conn, canonical_name=name, primary_domain=domain, workspace_id=project.workspace_id
            )
        )
    document_id, key, sha = await seed_icp_document(
        conn,
        storage,
        workspace_id=project.workspace_id,
        brand_id=str(project.brand_id),
        path=document_path,
    )
    # The project pins that confirmed version, exactly as the ICP gate's approval does. Every
    # launch resolves its ICP from this row (founder rulings 2026-09-10).
    await pin_icp(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        document_id=document_id,
        artifact_key_=key,
        artifact_sha256=sha,
        user_id=user_id,
    )
    return IcpFixture(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        accounts=tuple(accounts),
        icp_document_id=document_id,
        icp_artifact_key=key,
        icp_artifact_sha256=sha,
        selection_version=confirmed.selection_version,
    )
