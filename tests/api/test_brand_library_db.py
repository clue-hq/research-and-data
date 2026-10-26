"""The brand library: one pinned knowledge version, materialized once and mounted read-only.

The turn's seeds copy every pinned document into *this thread's* workspace. The library does the
opposite: it renders one knowledge version once, beside the threads, under
``<ws>/library/brand/<brand>/<version>/``, and every thread of every project of that brand mounts
the same frozen tree at ``brand/``. Three properties are load-bearing and are asserted here against
a real filesystem, never a fake:

* **Content-addressed, written once.** The version segment is the pin's ``documents_sha256``, so a
  second turn on the same knowledge finds the tree already there and does not rewrite it — the
  directory keeps its inode and its mtime, and no superseded generation appears beside it.
* **Immutable on disk.** 0400 files in 0500 directories, and the mounted path refuses a write.
* **Shared by every project of the brand.** The library is not project-relative: the *newest*
  version of a path owns the plain name there, whatever any one project pinned. A project's own
  ICP pin still owns the plain name in that project's thread seeds — the two surfaces disagree on
  purpose, because one is shared and the other is the project's.

Postgres stays the truth: the tree is a rendering of the pinned rows, and nothing reads it to
decide anything.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from clue_agents import MountRequest
from clue_agents.worker_area import ChatScope
from clue_agents.workspace_policy import WorkspaceSecurityError
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.brand_knowledge_context import (
    BRAND_LIBRARY_PREFIX,
    SEED_PREFIX,
    compile_brand_knowledge_index_card,
    knowledge_seed_files,
    load_or_create_knowledge_pin,
    read_pinned_documents,
)
from clue_api.brand_library import brand_library_version, ensure_brand_library
from tests._workspace import seed_project
from tests.agents.workspace_helpers import (
    DEFAULT_READABLE_PREFIXES,
    EXECUTION_ID,
    make_factory,
    policy,
)
from tests.api.test_brand_knowledge_context_db import (
    CATALOG,
    OVERVIEW,
    _icp,
    _pin_icp,
    _seed_document,
    _submitted_turn,
)
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_profiling_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_the_brand_library_is_written_once_per_pinned_version_and_mounts_read_only(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-library-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 library")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            for path, kind, body in (
                ("company/overview.md", "company-overview", OVERVIEW),
                ("product/catalog.md", "product-catalog", CATALOG),
            ):
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path=path,
                    kind=kind,
                    version=1,
                    status="ready",
                    body=body,
                )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="library",
            )
            pin, created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            assert created is True
            documents = await read_pinned_documents(conn, storage, pin=pin)

            root, factory, _sink = make_factory(tmp_path)
            try:
                chat = ChatScope(workspace_id, project.project_id, "thread-1")
                version = await ensure_brand_library(
                    factory, chat=chat, pin=pin, documents=documents
                )
                assert version == brand_library_version(pin) == pin.documents_sha256[:16]

                # The chat's own copy, beside its agent root (F3, WS-37).
                tree = factory.chat_host_path(chat) / "brand"
                overview = tree / "knowledge" / "company" / "overview.md"
                assert overview.read_text() == OVERVIEW
                assert (tree / "knowledge" / "product" / "catalog.md").read_text() == CATALOG
                # Immutable on disk: 0400 files inside 0500 directories, all the way up.
                assert stat.S_IMODE(overview.stat().st_mode) == 0o400
                assert stat.S_IMODE((tree / "knowledge" / "company").stat().st_mode) == 0o500
                assert stat.S_IMODE(tree.stat().st_mode) == 0o500

                index = json.loads((tree / "index.json").read_text())
                assert index["card_kind"] == "brand_knowledge_index"
                assert index["brand_id"] == project.brand_id
                assert index["library_sha256"] == pin.documents_sha256
                # Every line of the index names the file at the path the mount serves it at.
                assert {entry["workspace_path"] for entry in index["documents"]} == {
                    f"{BRAND_LIBRARY_PREFIX}company/overview.md",
                    f"{BRAND_LIBRARY_PREFIX}product/catalog.md",
                }
                # The library is brand-wide, so it carries no per-project facts at all.
                assert index["confirmed_icp"] is None
                assert index["product_set"] is None

                # A second turn on the same knowledge version writes nothing (WS-36).
                before = overview.stat()
                assert (
                    await ensure_brand_library(factory, chat=chat, pin=pin, documents=documents)
                    == version
                )
                after = overview.stat()
                assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)

                lease = factory.acquire(
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id="thread-1",
                    execution_id=EXECUTION_ID,
                    policy=policy(readable=(*DEFAULT_READABLE_PREFIXES, "brand")),
                    mounts=MountRequest(brand=(project.brand_id, version)),
                )
                assert (
                    lease.backend.read_text_sync(f"{BRAND_LIBRARY_PREFIX}company/overview.md")
                    == OVERVIEW
                )
                with pytest.raises(WorkspaceSecurityError):
                    lease.backend.write_text_sync(
                        f"{BRAND_LIBRARY_PREFIX}company/overview.md", "nope"
                    )
                # The mount is read beside the agent root, never copied into it.
                assert not (factory.chat_host_path(chat) / "agent" / "brand").exists()
            finally:
                factory.close()

    run_async(scenario())


def test_the_mounted_brand_library_serves_its_manifest_at_brand_index_json(
    tmp_path: Path,
) -> None:
    """The manifest is at the tree ROOT, so mounted it is ``brand/index.json``.

    ``LibraryTree`` requires ``index.json`` at the root — ``current_digest()`` reads it there — so
    the writer puts it beside ``knowledge/``, not inside it. A live turn on ``head-of-abm@v52``
    read ``project/status.md`` fine and then asked for ``brand/knowledge/index.json``, because
    stage0-interview v29 §1 named it there; the workspace answered "workspace file does not
    exist". This test pins both halves of that: the manifest the skill now names resolves and
    carries the pin's digest, and the path v29 named resolves to nothing.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-libidx-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 library index")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="libidx",
            )
            pin, _created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            documents = await read_pinned_documents(conn, storage, pin=pin)

            _root, factory, _sink = make_factory(tmp_path)
            try:
                version = await ensure_brand_library(
                    factory,
                    chat=ChatScope(workspace_id, project.project_id, "thread-idx"),
                    pin=pin,
                    documents=documents,
                )
                lease = factory.acquire(
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    thread_id="thread-idx",
                    execution_id=EXECUTION_ID,
                    policy=policy(readable=(*DEFAULT_READABLE_PREFIXES, "brand")),
                    mounts=MountRequest(brand=(project.brand_id, version)),
                )

                index = json.loads(lease.backend.read_text_sync("brand/index.json"))
                assert index["library_sha256"] == pin.documents_sha256
                assert index["brand_id"] == project.brand_id
                assert {entry["workspace_path"] for entry in index["documents"]} == {
                    f"{BRAND_LIBRARY_PREFIX}company/overview.md",
                }
                # The document the manifest lists is there under the path it lists it at.
                assert (
                    lease.backend.read_text_sync(f"{BRAND_LIBRARY_PREFIX}company/overview.md")
                    == OVERVIEW
                )
                # …and the path skill v29 named is not a file. v30 names `brand/index.json`.
                with pytest.raises(WorkspaceSecurityError):
                    lease.backend.read_text_sync(f"{BRAND_LIBRARY_PREFIX}index.json")
            finally:
                factory.close()

    run_async(scenario())


def test_the_shared_brand_library_gives_the_plain_name_to_the_newest_version(
    tmp_path: Path,
) -> None:
    """The library is one tree per knowledge version, shared by every project of the brand.

    So a project's ICP pin cannot move a name in it: the newest version of a path owns the plain
    name, and the older version rides beside it version-qualified. The project's *thread* seeds
    still hand the plain name to the version that project pinned — the project's pin belongs in
    the project's own context, not in a tree its sibling projects read.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-libpin-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 library pin")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            confirmed_body = _icp(
                key="gi", status="confirmed", project_id=project.project_id, selection_version=3
            )
            newer_body = _icp(key="gi", status="proposed", project_id=None, selection_version=None)
            pinned_document_id = await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=2,
                status="confirmed",
                body=confirmed_body,
            )
            icp_pin = await _pin_icp(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                document_id=pinned_document_id,
                icp_key="gi",
                product_selection_version=3,
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-gi.md",
                kind="icp-definition",
                version=3,
                status="proposed",
                body=newer_body,
            )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="libpin",
            )
            pin, _created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            documents = await read_pinned_documents(conn, storage, pin=pin)
            assert [(ref.path, ref.version) for ref in pin.documents] == [
                ("audience/icp-gi.md", 2),
                ("audience/icp-gi.md", 3),
            ]

            # The thread's seeds are project-relative: the pinned v2 owns the plain name there.
            seeds = {
                seed.path: seed
                for seed in knowledge_seed_files(documents, pinned_document_id=icp_pin.document_id)
            }
            assert seeds[f"{SEED_PREFIX}audience/icp-gi.md"].content == confirmed_body.encode()
            assert seeds[f"{SEED_PREFIX}audience/icp-gi.v3.md"].content == newer_body.encode()

            root, factory, _sink = make_factory(tmp_path)
            try:
                chat = ChatScope(workspace_id, project.project_id, "thread-1")
                await ensure_brand_library(factory, chat=chat, pin=pin, documents=documents)
                knowledge = factory.chat_host_path(chat) / "brand" / "knowledge"
                # …and the shared library is not: the newest version owns the plain name.
                assert (knowledge / "audience" / "icp-gi.md").read_text() == newer_body
                assert (knowledge / "audience" / "icp-gi.v2.md").read_text() == confirmed_body
                index = json.loads(
                    (knowledge.parent / "index.json").read_text(),
                )
                assert {
                    entry["version"]: entry["workspace_path"] for entry in index["documents"]
                } == {
                    3: f"{BRAND_LIBRARY_PREFIX}audience/icp-gi.md",
                    2: f"{BRAND_LIBRARY_PREFIX}audience/icp-gi.v2.md",
                }
            finally:
                factory.close()

    run_async(scenario())


def test_the_library_index_lists_every_file_it_serves(tmp_path: Path) -> None:
    """A manifest of a tree has no context budget, so it never drops a line.

    The 8 KiB default belongs to the turn's *opening* card, where every line is spent whether or
    not the model reads it. This index is read from disk by path: an omitted entry would buy
    nothing and would leave the manifest under-listing the files sitting beside it. The control in
    this test is the default-budget card compiled over the same documents — it really does omit.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"o6-libfull-{uuid4().hex[:6]}"
            project = await seed_project(conn, workspace_id, name="O6 library full")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="company/overview.md",
                kind="company-overview",
                version=1,
                status="ready",
                body=OVERVIEW,
            )
            # A catalog this wide is what puts the default card over its budget.
            research_paths = [f"product/research-line-{index:02d}.md" for index in range(24)]
            for index, path in enumerate(research_paths):
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path=path,
                    kind="product-research",
                    version=1,
                    status="ready",
                    body=(
                        "---\nkind: product-research\n---\n\n"
                        f"Product line {index:02d} sells scheduling and anesthesia billing to "
                        "independent gastroenterology groups, and this paragraph is long enough "
                        "to fill the index summary it is truncated into.\n"
                    ),
                )
            turn_id = await _submitted_turn(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=project.brand_id,
                label="libfull",
            )
            pin, _created = await load_or_create_knowledge_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
            )
            documents = await read_pinned_documents(conn, storage, pin=pin)

            # The control: at the opening card's budget, entries really are dropped.
            bounded = compile_brand_knowledge_index_card(
                brand_id=project.brand_id,
                documents=documents,
                confirmed_icp=None,
                product_set=None,
            )
            assert bounded.omitted_count > 0

            root, factory, _sink = make_factory(tmp_path)
            try:
                chat = ChatScope(workspace_id, project.project_id, "thread-1")
                await ensure_brand_library(factory, chat=chat, pin=pin, documents=documents)
                tree = factory.chat_host_path(chat) / "brand"
                index = json.loads((tree / "index.json").read_text())
                assert index["omitted_count"] == 0
                assert {entry["path"] for entry in index["documents"]} == {
                    "company/overview.md",
                    *research_paths,
                }
                # …and every listed path is really a file in the tree it describes.
                for entry in index["documents"]:
                    served = entry["workspace_path"].removeprefix(BRAND_LIBRARY_PREFIX)
                    assert (tree / "knowledge" / served).is_file()
            finally:
                factory.close()

    run_async(scenario())
