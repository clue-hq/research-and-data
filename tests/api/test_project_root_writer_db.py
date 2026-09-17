"""The project mount's writer against the real tables: a file write becomes a document version.

The model writes a path; the writer turns it into the act that path names. These tests exercise
that translation the way the backend does — **synchronously**, through
:class:`~clue_api.project_root_writer.ProjectRootWriter`, over a real bridge and real rows — so the
whole sync→async→Postgres chain is what is proven, not a coroutine called directly.

Four properties carry the seam:

* **Any markdown path is a document** (founder ruling 2026-09-14). ``plan.md``, a persona for a key
  this project never pinned, a brief under ``notes/`` — each lands as a version at its own path,
  under the kind and title the *document* claims. Nothing is refused for its shape.
* **The version the model read is the version it must declare.** A second write against a version
  the project has moved past comes back as ``revision_conflict`` naming the version at rest.
* **Two refusals, both about the file and never about its content.** A compiled file is read-only;
  a path that is not markdown is not something the library can serve back.
* **What was written is readable back.** After every accepted write the library is re-materialized:
  ``refresh()`` reports the version this write minted, and the bytes in the tree are byte-identical
  to the version's stored artifact.

Everything runs on one bridge loop — the connection, the seeding and the writers alike — because a
database connection belongs to the loop that created it, and the bridge loop is the one the
production writer's engine lives on. The transaction is rolled back at the end, so the lane
database keeps no rows.
"""

from __future__ import annotations

from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from clue_agents import AgentWorkspaceFactory, VersionedWriteRefused
from clue_agents.bridge import AsyncBridge, process_bridge
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.project_root_writer import (
    ProjectRootWriter,
    _bridge_engine,
    bridge_transaction,
)
from clue_auth.store import create_platform_user
from clue_db import create_engine, database_url
from clue_spine import Project
from clue_storage import artifact_key, content_address, read_verified_artifact, record_artifact
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.agents.workspace_helpers import make_factory
from tests.arv2.icp_fixture import pin_icp, seed_icp_document
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_profiling_db")

USER_ID = "usr_project_root_writer"
#: The brand's ICP this project pins. Its key is the only key a persona may be written for here.
PINNED_KEY = "gi"
#: The variant key the ICP test authors — a *different* key, because a project variant may not take
#: the name the brand's profile already owns (``icp_key_taken_by_brand``).
VARIANT_KEY = "gi-dac"

BRAND_ICP = """---
kind: icp-definition
icp_key: gi
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: GI-focused ASC, test: the site lists GI procedures}
status: confirmed
---

# GI-focused ambulatory surgery centres

The profile the human said yes to.
"""

VARIANT_ICP = f"""---
kind: icp-definition
icp_key: {VARIANT_KEY}
product_ids: [prd_aura]
hard_gates:
  - {{key: specialty, rule: GI-focused ASC, test: the site lists GI procedures}}
  - {{key: anesthesia, rule: owns its anesthesia service line, test: the site names it}}
derived_from: {PINNED_KEY}
---

# GI-focused ASCs that own anesthesia

The narrower reading this project qualifies against.
"""

PERSONA = f"""---
kind: audience-persona
icp_key: {PINNED_KEY}
personas:
  - role: champion
    title: Director of Clinical Operations
  - role: economic_buyer
    title: Chief Financial Officer
---

# Who decides

The director owns the throughput problem; the CFO signs.
"""

PLAN_BODY = """# Q4 expansion plan

## Outcome
Twenty qualified conversations with GI-focused ASCs by the end of the quarter.
"""


# =================================================================================================
# the lane: one bridge, one connection, one project
# =================================================================================================


@dataclass
class _Lane:
    """Everything one test needs, all of it living on the bridge's loop."""

    bridge: AsyncBridge
    conn: AsyncConnection
    storage: FsStorage
    artifacts: DurableAgentArtifactStore
    factory: AgentWorkspaceFactory
    root: Path
    project: Project
    turn_id: UUID
    brand_icp_id: UUID

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        # Generous: the first call builds a tree and reads blobs, and a slow lane database must
        # fail as a failure, not as a bridge timeout that hides it.
        return self.bridge.run(coro, timeout_s=120.0)

    def writer(self, *, turn_id: UUID | None = None) -> ProjectRootWriter:
        """A writer bound to this project — and to *this test's* transaction, so nothing commits."""

        return ProjectRootWriter(
            bridge=self.bridge,
            storage=self.storage,
            artifacts=self.artifacts,
            workspaces=self.factory,
            workspace_id=self.project.workspace_id,
            brand_id=str(self.project.brand_id),
            project_id=self.project.project_id,
            turn_id=self.turn_id if turn_id is None else turn_id,
            user_id=USER_ID,
            conn_factory=conn_session_factory(self.conn),
        )

    @property
    def tree(self) -> Path:
        """Where the mount's read-only generation is installed."""

        projects = self.root / self.project.workspace_id / "projects"
        return projects / self.project.project_id / "library"

    def stored_bytes(self, document_id: UUID) -> bytes:
        """The bytes of one document version, read back through its verified artifact row."""

        return self.run(_stored_bytes(self.conn, self.storage, self.project, document_id))


async def _stored_bytes(
    conn: AsyncConnection, storage: FsStorage, project: Project, document_id: UUID
) -> bytes:
    key = await conn.scalar(
        text("SELECT artifact_key FROM brand_knowledge_document WHERE document_id = :d"),
        {"d": document_id},
    )
    _record, raw = await read_verified_artifact(
        conn, storage, storage_key=str(key), workspace_id=project.workspace_id
    )
    return raw


async def _row(conn: AsyncConnection, document_id: UUID) -> dict[str, Any]:
    return dict(
        (
            await conn.execute(
                text(
                    "SELECT project_id, brand_id, folder, path, kind, version, status, "
                    "       derived_from_document_id, produced_by_turn_id, supersedes_document_id "
                    "FROM brand_knowledge_document WHERE document_id = :d"
                ),
                {"d": document_id},
            )
        )
        .mappings()
        .one()
    )


async def _seed_turn(conn: AsyncConnection, storage: FsStorage, project: Project) -> UUID:
    """One journaled turn of this project — the row ``produced_by_turn_id`` must name.

    A persona records the turn that wrote it, and that column is a foreign key into ``agent_turn``,
    so the writer can only be exercised as production exercises it: from inside a real turn.
    """

    thread_id = f"thr-prw-{uuid4().hex[:8]}"
    execution_id = uuid4()
    turn_id = uuid4()
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": project.workspace_id, "project": project.project_id},
    )
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, pin_manifest_hash)"
            " VALUES (:id, :ws, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    manifest = await _manifest_artifact(conn, storage, project)
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :project, :thread, :user, 'head_of_abm', "
            " :root, 'head-of-abm', 'v1', :hash, :manifest_key, :manifest_sha, :manifest_sha, "
            " 'agent-ephemeral-v1', now())"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "user": USER_ID,
            "root": f"root-{turn_id.hex[:8]}",
            "hash": "0" * 64,
            "manifest_key": manifest[0],
            "manifest_sha": manifest[1],
        },
    )
    return turn_id


async def _manifest_artifact(
    conn: AsyncConnection, storage: FsStorage, project: Project
) -> tuple[str, str]:
    """One durable artifact row the turn's resource-manifest columns can name."""

    data = b'{"schema_version": "1"}'
    sha = content_address(data)
    key = artifact_key(project.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=project.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(data),
        source_key="test:project-root-writer",
    )
    await storage.put(key, data, media_type="application/json")
    return key, sha


@contextmanager
def lane(tmp_path: Path, label: str) -> Iterator[_Lane]:
    """A bridge, a rolled-back connection on its loop, and a project with a pinned brand ICP."""

    bridge = AsyncBridge(name=f"project-root-writer-{label}")
    state: dict[str, Any] = {}
    root, factory, _sink = make_factory(tmp_path / "agents")
    storage = FsStorage(tmp_path / "blobs")
    try:
        bridge.run(_open(state, storage, label), timeout_s=120.0)
        yield _Lane(
            bridge=bridge,
            conn=state["conn"],
            storage=storage,
            artifacts=state["artifacts"],
            factory=factory,
            root=root,
            project=state["project"],
            turn_id=state["turn_id"],
            brand_icp_id=state["brand_icp_id"],
        )
    finally:
        factory.close()
        if "conn" in state:
            bridge.run(_close(state), timeout_s=120.0)
        bridge.close()


async def _open(state: dict[str, Any], storage: FsStorage, label: str) -> None:
    """Open the connection and its always-rolled-back transaction, and seed the project.

    On the loop, every line of it: the connection this test hands to the writers is the connection
    the bridge's own coroutines will use, so it has to be born here.
    """

    engine: AsyncEngine = create_engine(database_url())
    conn = await engine.connect()
    trans = await conn.begin()
    state.update(engine=engine, conn=conn, trans=trans)

    workspace_id = f"prw-{label}-{uuid4().hex[:6]}"
    project = await seed_project(conn, workspace_id, name=f"Project root writer {label}")
    await create_platform_user(conn, user_id=USER_ID, display_name="Project root writer test")
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    document_id, key, sha = await seed_icp_document(
        conn,
        storage,
        workspace_id=project.workspace_id,
        brand_id=str(project.brand_id),
        body=BRAND_ICP,
        path=f"audience/icp-{PINNED_KEY}.md",
    )
    await pin_icp(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        document_id=document_id,
        artifact_key_=key,
        artifact_sha256=sha,
        icp_key=PINNED_KEY,
    )
    state.update(
        project=project,
        artifacts=artifacts,
        brand_icp_id=document_id,
        turn_id=await _seed_turn(conn, storage, project),
    )


async def _close(state: dict[str, Any]) -> None:
    await state["trans"].rollback()
    await state["conn"].close()
    await state["engine"].dispose()


# =================================================================================================
# the plan
# =================================================================================================


def test_the_plan_is_a_version_chain_and_a_stale_write_is_refused(tmp_path: Path) -> None:
    """The whole loop, twice: write, refresh, read back — then be told you are behind.

    The second write declares the version the first minted and becomes version 2. The third
    declares version 1 again, which is the shape of an agent working from a view it took before
    somebody else wrote: it is refused by the code the backend documents as "read it again", and
    the sentence names the version actually at rest.

    The plan is no longer a kind: the document says nothing about what it is, so it is a
    ``document``, and its title is the heading it gave itself.
    """

    with lane(tmp_path, "plan") as active:
        writer = active.writer()

        first = writer.write(path="plan.md", content=PLAN_BODY, expected_version=None)

        assert (first.path, first.version, first.kind, first.status, first.replayed) == (
            "plan.md",
            1,
            "document",
            "ready",
            False,
        )
        assert first.title == "Q4 expansion plan"
        assert writer.refresh()["plan.md"] == 1
        assert (active.tree / "plan.md").read_bytes() == active.stored_bytes(first.document_id)

        second = writer.write(path="plan.md", content="# The second plan\n", expected_version=1)

        assert (second.version, second.replayed, second.title) == (2, False, "The second plan")
        assert second.document_id != first.document_id
        assert writer.refresh()["plan.md"] == 2
        assert (active.tree / "plan.md").read_bytes() == active.stored_bytes(second.document_id)

        with pytest.raises(VersionedWriteRefused) as refused:
            writer.write(path="plan.md", content="# The stale plan\n", expected_version=1)

        assert refused.value.code == "revision_conflict"
        assert (
            refused.value.message == "plan.md is at version 2, you read version 1 — read it again"
        )
        assert str(refused.value).startswith("revision_conflict: ")


def test_the_model_keeps_its_front_matter_and_the_platform_stamps_over_it(tmp_path: Path) -> None:
    """The model reads a file with front matter, so it writes one back. All of it survives.

    Six keys are the platform's and are stamped last, so the version the model echoed back — always
    the one it *read*, never the one this write mints — cannot land in the bytes. Everything else
    the model wrote is kept exactly as it typed it, including the ``role`` a human agreed to pin
    this document under and the word it uses for what the document is.
    """

    with lane(tmp_path, "stamp") as active:
        header = (
            "---\nkind: project-plan\nrole: plan\ntitle: The Q4 motion\n"
            "version: 7\nstatus: superseded\nproject_id: nope\nowner: sasha\n---\n\n"
        )

        written = active.writer().write(
            path="plan.md", content=header + PLAN_BODY, expected_version=None
        )

        assert (written.kind, written.title) == ("project-plan", "The Q4 motion")
        raw = active.stored_bytes(written.document_id).decode()
        front, body = parse_front_matter(raw, preserve_body=True)
        assert body == PLAN_BODY
        assert raw.count("---\n") == 2
        assert (front["version"], front["status"]) == (1, "ready")
        assert front["project_id"] == active.project.project_id
        assert front["authored_by"] == {"turn_id": str(active.turn_id), "user_id": USER_ID}
        # The model's own words, untouched: what it calls the document, what it is for, and a key
        # the platform has never heard of.
        assert (front["kind"], front["role"], front["title"]) == (
            "project-plan",
            "plan",
            "The Q4 motion",
        )
        assert front["owner"] == "sasha"


# =================================================================================================
# any path, any document
# =================================================================================================


def test_a_persona_for_a_key_this_project_never_pinned_is_a_document_like_any_other(
    tmp_path: Path,
) -> None:
    """No pin check, no key check, no refusal (founder ruling 2026-09-14).

    Before, a persona document could only be written for the key this project had pinned, and any
    other key was refused ``icp_not_pinned``. Whether a document *is* this project's personas is
    now the human's answer to one question, recorded as a role in the document's own front matter —
    so a persona the agent drafted for another profile is a document the project has, not an error.
    Everything the model said is kept, and only the platform's six facts are stamped over it.
    """

    path = "audience/persona-dac.md"
    with lane(tmp_path, "persona") as active:
        writer = active.writer()

        written = writer.write(
            path=path,
            content=PERSONA.replace(f"icp_key: {PINNED_KEY}", "icp_key: dac"),
            expected_version=None,
        )

        assert (written.path, written.version, written.kind, written.status) == (
            path,
            1,
            "audience-persona",
            "ready",
        )
        assert written.title == "Who decides"
        row = active.run(_row(active.conn, written.document_id))
        assert (row["project_id"], row["folder"], row["path"]) == (
            active.project.project_id,
            "audience",
            path,
        )
        assert row["supersedes_document_id"] is None
        front, body = parse_front_matter(
            active.stored_bytes(written.document_id).decode(), preserve_body=True
        )
        assert (front["kind"], front["icp_key"], front["status"]) == (
            "audience-persona",
            "dac",
            "ready",
        )
        assert front["authored_by"] == {"turn_id": str(active.turn_id), "user_id": USER_ID}
        # The model's own content survives untouched; only the platform's keys are stamped over it.
        assert [entry["role"] for entry in front["personas"]] == ["champion", "economic_buyer"]
        assert body.startswith("# Who decides")

        assert writer.refresh()[path] == 1
        assert (active.tree / "audience" / "persona-dac.md").read_bytes() == (
            active.stored_bytes(written.document_id)
        )

        with pytest.raises(VersionedWriteRefused) as stale:
            writer.write(
                path=path, content=PERSONA + "\nOne more paragraph.\n", expected_version=None
            )

        assert stale.value.code == "revision_conflict"
        assert stale.value.message == (
            f"{path} is at version 1, you read version None — read it again"
        )


def test_a_document_the_platform_has_no_name_for_lands_at_its_own_path(tmp_path: Path) -> None:
    """The founder ruling, at its plainest: the agent writes what it judges useful.

    ``notes/competitive-brief.md`` is a path no version of this writer had ever heard of. It lands
    as version 1 under the kind and title the document claims for itself, it is readable back in
    the tree, and writing it again against the version it minted is version 2 — the same version
    chain every other document gets.
    """

    path = "notes/competitive-brief.md"
    brief = (
        "---\nkind: brief\ntitle: Who else is in this deal\n---\n\n"
        "# Competitive brief\n\nTwo vendors show up in every GI conversation.\n"
    )
    with lane(tmp_path, "free") as active:
        writer = active.writer()

        first = writer.write(path=path, content=brief, expected_version=None)

        assert (first.path, first.version, first.kind, first.status) == (path, 1, "brief", "ready")
        assert first.title == "Who else is in this deal"
        row = active.run(_row(active.conn, first.document_id))
        assert (row["project_id"], row["folder"], row["path"], row["kind"]) == (
            active.project.project_id,
            "notes",
            path,
            "brief",
        )
        assert writer.refresh()[path] == 1
        assert (active.tree / "notes" / "competitive-brief.md").read_bytes() == (
            active.stored_bytes(first.document_id)
        )

        second = writer.write(
            path=path, content=brief + "\nA third appeared.\n", expected_version=1
        )

        assert (second.version, second.replayed) == (2, False)
        assert writer.refresh()[path] == 2


def test_an_icp_draft_is_a_document_and_the_gate_is_what_makes_it_the_icp(tmp_path: Path) -> None:
    """An ICP write is no longer an authoring act with its own writer, its own status and a pin.

    It lands ``ready`` at the path the agent chose, saying in its own front matter that it is an
    ``icp-definition`` and which key it is about. Nothing about it is confirmed, and nothing about
    it is refused: the human's yes at the confirmation gate is the pin, and it is the only one.
    """

    path = f"audience/icp-{VARIANT_KEY}.md"
    with lane(tmp_path, "icp") as active:
        writer = active.writer()

        written = writer.write(path=path, content=VARIANT_ICP, expected_version=None)

        assert (written.path, written.version, written.kind, written.status, written.replayed) == (
            path,
            1,
            "icp-definition",
            "ready",
            False,
        )
        row = active.run(_row(active.conn, written.document_id))
        assert (row["project_id"], row["status"], row["path"]) == (
            active.project.project_id,
            "ready",
            path,
        )

        versions = writer.refresh()
        assert versions[path] == 1
        # The pinned brand profile is still served at its own name, untouched by the variant.
        assert versions[f"audience/icp-{PINNED_KEY}.md"] == 1
        assert (active.tree / "audience" / f"icp-{VARIANT_KEY}.md").read_bytes() == (
            active.stored_bytes(written.document_id)
        )


# =================================================================================================
# the paths that are not documents
# =================================================================================================


def test_a_compiled_file_is_read_only_and_a_non_markdown_path_is_not_a_document(
    tmp_path: Path,
) -> None:
    """The only two refusals left, and both are about the file rather than what it says.

    A compiled file is a *rendering* of rows the model cannot type over — telling it to re-read
    would be a lie, so it is told the file is not writable at all. A path that is not markdown is
    not something the project library can serve back, and the message says so. Every other path
    under the mount is a document.
    """

    with lane(tmp_path, "refusals") as active:
        writer = active.writer()

        for path in ("status.md", "decisions.md", "index.json", "artifacts/index.json"):
            with pytest.raises(VersionedWriteRefused) as compiled:
                writer.write(path=path, content="# mine now\n", expected_version=None)
            assert compiled.value.code == "compiled_file_read_only"
            assert compiled.value.message == (
                f"{path} is compiled from the project's rows; it cannot be written"
            )

        for path in ("notes.txt", "audience/persona.yaml"):
            with pytest.raises(VersionedWriteRefused) as unsupported:
                writer.write(path=path, content="# mine now\n", expected_version=None)
            assert unsupported.value.code == "unsupported_document_type"
            assert "markdown" in unsupported.value.message


# =================================================================================================
# the production transaction factory
# =================================================================================================


def test_the_default_transaction_factory_serves_the_bridge_loop_from_one_engine() -> None:
    """Ruling P3-1, proven rather than asserted: the engine is built *on* the loop that uses it.

    Every other test here injects its own connection so nothing commits, which leaves the one
    thing the production writer actually depends on unexercised — that an asyncpg pool created
    from a coroutine on the bridge loop can serve a query on that loop. This opens a real
    transaction on the lane database through :func:`bridge_transaction`, writes nothing, and
    checks that a second call reuses the same engine: one pool per process, not one per tool call.
    """

    bridge = process_bridge()

    async def probe() -> tuple[int, AsyncEngine]:
        async with bridge_transaction() as conn:
            answer = await conn.scalar(text("SELECT 1"))
        return int(str(answer)), await _bridge_engine()

    first_answer, first_engine = bridge.run(probe(), timeout_s=120.0)
    second_answer, second_engine = bridge.run(probe(), timeout_s=120.0)

    assert (first_answer, second_answer) == (1, 1)
    assert first_engine is second_engine
