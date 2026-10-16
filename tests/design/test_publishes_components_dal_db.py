"""D2.4B acceptance tests: the web-publish + custom-component DAL port (PD contract §7).

Covers the ported semantics that matter most:

* **publishes:** the republish shift — the live row's html AND ``publish_id`` move into
  ``previous_*`` in ONE statement — and the one-step rollback that swaps both back.
* **O6 in practice:** the same slug published in two workspaces coexists, and neither tenant's
  fail-closed read can see the other's.
* **append-only history:** UPDATE *and* DELETE on ``design_web_publish_revision`` are rejected
  by trigger even through a DAL-shaped write, and the content-address CHECK refuses a
  ``publish_id`` that is not ``'webpub_' || package_digest``.
* **components:** register → artifact, first source revision (CAS from 0), the identity row's
  ``current_source_revision_id`` pointer advance, a recorded compilation, and the CAS refusing a
  stale ``expected_version``.
* **cascade:** deleting the account takes its whole component family with it (the SQLite era
  orphaned it).

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import accounts as design_accounts
from clue_design import components as design_components
from clue_design import documents as design_documents
from clue_design import publishes as design_publishes
from clue_design.errors import (
    DesignArtifactConflictError,
    DesignNotFoundError,
    DesignSourceVersionConflictError,
)
from tests.design.conftest import run_async


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def _seed_ws(conn: AsyncConnection, tag: str) -> str:
    ws = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _seed_document(conn: AsyncConnection, ws: str) -> str:
    doc_id = f"doc_{uuid4().hex}"
    await design_documents.create_document(
        conn,
        workspace_id=ws,
        scene={"meta": {"id": doc_id, "title": "T", "status": {"kind": "draft"}}, "nodes": []},
    )
    return doc_id


async def _seed_account(conn: AsyncConnection, ws: str) -> str:
    account_id = f"acc_{uuid4().hex[:12]}"
    await design_accounts.create_web_account(
        conn,
        workspace_id=ws,
        account_id=account_id,
        name="Acme",
        domain=None,
        logo_asset_id=None,
        data={},
        notes=None,
    )
    return account_id


def _revision(slug: str, document_id: str, seed: str, *, doc_version: int = 1) -> dict[str, Any]:
    """One publish package. ``package_digest`` IS the content address the CHECK enforces."""
    return {
        "slug": slug,
        "document_id": document_id,
        "doc_version": doc_version,
        "html": f"<html>{seed}</html>",
        "html_digest": _sha(f"html:{seed}"),
        "manifest": {"slug": slug, "seed": seed},
        "manifest_digest": _sha(f"manifest:{seed}"),
        "package_digest": _sha(f"package:{seed}"),
        "runtime_version": 3,
    }


def _blob(payload: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "algorithm": "sha256",
        "value": digest,
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "byte_length": len(payload),
    }


def _artifact_candidate(account_id: str, slug: str, seed: str) -> dict[str, Any]:
    """The already-canonical candidate the API layer hands the DAL (validation lives there)."""
    return {
        "artifact_id": f"ccart_{_sha(f'artifact:{seed}')}",
        "account_id": account_id,
        "slug": slug,
        "source": _blob(f"source-{seed}".encode()),
        "bundle": _blob(f"bundle-{seed}".encode()),
        "css": None,
        "first_frame": None,
        "manifest": {"schema_version": 2, "props_schema": {"type": "object"}},
        "provenance": {"compiler_version": "1.0.0"},
    }


def _source_candidate(account_id: str, slug: str, seed: str) -> dict[str, Any]:
    return {
        "revision_id": f"ccsrc_{_sha(f'source:{seed}')}",
        "account_id": account_id,
        "slug": slug,
        "entry_path": "index.tsx",
        "snapshot": _blob(f"snapshot-{seed}".encode()),
        "files_manifest": {"index.tsx": _sha(f"file:{seed}")},
        "provenance": {"author": "test"},
    }


# --- publishes --------------------------------------------------------------------------------


def test_publish_upsert_shifts_current_to_previous_and_rollback_swaps_back(
    require_design_db: None,
) -> None:
    """A republish moves html AND publish_id into previous_*; rollback swaps BOTH pointers."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "pub")
            doc = await _seed_document(conn, ws)
            slug = f"slug-{uuid4().hex[:8]}"

            first = _revision(slug, doc, "v1")
            first_stored = await design_publishes.register_web_publish_revision(
                conn, workspace_id=ws, revision=first
            )
            # The content address is derived, not trusted: publish_id = webpub_<package digest>.
            assert first_stored["publish_id"] == f"webpub_{first['package_digest']}"
            published = await design_publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=1,
                html=first["html"],
                runtime_version=3,
                publish_id=first_stored["publish_id"],
            )
            assert published["html"] == "<html>v1</html>"
            assert published["status"] == "active"
            assert published["previous_html"] is None
            assert published["previous_publish_id"] is None
            assert isinstance(published["created_at"], str)  # ISO parity with the SQLite API

            second = _revision(slug, doc, "v2", doc_version=2)
            second_stored = await design_publishes.register_web_publish_revision(
                conn, workspace_id=ws, revision=second
            )
            republished = await design_publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=2,
                html=second["html"],
                runtime_version=3,
                publish_id=second_stored["publish_id"],
            )
            assert republished["html"] == "<html>v2</html>"
            assert republished["doc_version"] == 2
            assert republished["publish_id"] == second_stored["publish_id"]
            assert republished["previous_html"] == "<html>v1</html>"
            assert republished["previous_doc_version"] == 1
            assert republished["previous_publish_id"] == first_stored["publish_id"]

            rolled = await design_publishes.rollback_web_publish(conn, workspace_id=ws, slug=slug)
            assert isinstance(rolled, dict)
            assert rolled["html"] == "<html>v1</html>"
            assert rolled["doc_version"] == 1
            assert rolled["publish_id"] == first_stored["publish_id"]
            # Both sides swapped — the buffer now holds v2, so rollback is a true one-step undo.
            assert rolled["previous_html"] == "<html>v2</html>"
            assert rolled["previous_publish_id"] == second_stored["publish_id"]
            assert rolled["status"] == "active"

            # Unpublish flips status only; history and the rollback buffer survive.
            unpublished = await design_publishes.set_web_publish_status(
                conn, workspace_id=ws, slug=slug, status="unpublished"
            )
            assert unpublished is not None and unpublished["status"] == "unpublished"
            assert (
                await design_publishes.set_web_publish_status(
                    conn, workspace_id=ws, slug="no-such-slug", status="unpublished"
                )
                is None
            )
            assert (
                await design_publishes.get_web_publish_for_document(
                    conn, workspace_id=ws, document_id=doc
                )
            )["slug"] == slug
            await txn.rollback()

    run_async(_check())


async def _stamp(conn: AsyncConnection, ws: str, slug: str, seconds_ago: int) -> None:
    """Put one publish row's ``updated_at`` at a point on an explicit timeline.

    Inside one rolled-back test transaction ``now()`` is frozen, so every DAL write stamps the
    same instant. Production runs each repository call in its own transaction, so the clock moves
    between them; this lays that production timeline out explicitly.
    """
    await conn.execute(
        text(
            "UPDATE design_web_publish SET updated_at = now() - make_interval(secs => :s)"
            " WHERE workspace_id = :w AND slug = :slug"
        ),
        {"s": seconds_ago, "w": ws, "slug": slug},
    )


async def _updated_at(conn: AsyncConnection, ws: str, slug: str) -> Any:
    return (
        await conn.execute(
            text("SELECT updated_at FROM design_web_publish WHERE workspace_id = :w AND slug = :s"),
            {"w": ws, "s": slug},
        )
    ).scalar_one()


def test_a_moved_document_reads_as_the_publish_it_now_lives_at(require_design_db: None) -> None:
    """A move (publish at A, then at B, then retire A) leaves A with the LATER ``updated_at``:
    ``unpublish_other_slugs`` re-stamps the rows it retires. The document's publish is still B,
    the live one. With nothing live, the newest row is returned, unpublished."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "move")
            doc = await _seed_document(conn, ws)
            slug_a, slug_b = f"slug-a-{uuid4().hex[:8]}", f"slug-b-{uuid4().hex[:8]}"
            for slug, seconds_ago in ((slug_a, 40), (slug_b, 30)):
                await design_publishes.upsert_web_publish(
                    conn,
                    workspace_id=ws,
                    slug=slug,
                    document_id=doc,
                    doc_version=1,
                    html=f"<html>{slug}</html>",
                    runtime_version=None,
                    publish_id=None,
                )
                await _stamp(conn, ws, slug, seconds_ago)
            assert await _updated_at(conn, ws, slug_b) > await _updated_at(conn, ws, slug_a)

            retired = await design_publishes.unpublish_other_slugs(
                conn, workspace_id=ws, document_id=doc, keep_slug=slug_b
            )
            assert retired == [slug_a]
            await _stamp(conn, ws, slug_a, 20)  # the retire statement commits after B's upsert
            assert await _updated_at(conn, ws, slug_a) > await _updated_at(conn, ws, slug_b)

            live = await design_publishes.get_web_publish_for_document(
                conn, workspace_id=ws, document_id=doc
            )
            assert live is not None
            assert (live["slug"], live["status"]) == (slug_b, "active")

            # Nothing live any more: the newest row (B, just unpublished) is the answer.
            await design_publishes.set_web_publish_status(
                conn, workspace_id=ws, slug=slug_b, status="unpublished"
            )
            assert await _updated_at(conn, ws, slug_b) > await _updated_at(conn, ws, slug_a)
            newest = await design_publishes.get_web_publish_for_document(
                conn, workspace_id=ws, document_id=doc
            )
            assert newest is not None
            assert (newest["slug"], newest["status"]) == (slug_b, "unpublished")
            await txn.rollback()

    run_async(_check())


def test_rollback_markers_and_a_publish_with_no_history(require_design_db: None) -> None:
    """The ported string markers survive the port: 'not_found' and 'no_previous'."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "roll")
            doc = await _seed_document(conn, ws)
            slug = f"slug-{uuid4().hex[:8]}"
            assert (
                await design_publishes.rollback_web_publish(conn, workspace_id=ws, slug=slug)
                == "not_found"
            )
            await design_publishes.upsert_web_publish(
                conn,
                workspace_id=ws,
                slug=slug,
                document_id=doc,
                doc_version=1,
                html="<html>only</html>",
                runtime_version=None,
                publish_id=None,
            )
            assert (
                await design_publishes.rollback_web_publish(conn, workspace_id=ws, slug=slug)
                == "no_previous"
            )
            await txn.rollback()

    run_async(_check())


def test_the_same_slug_in_two_workspaces_coexists(require_design_db: None) -> None:
    """O6: slugs are workspace-local. Two tenants publish 'pricing'; neither sees the other."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a, ws_b = await _seed_ws(conn, "o6a"), await _seed_ws(conn, "o6b")
            doc_a, doc_b = await _seed_document(conn, ws_a), await _seed_document(conn, ws_b)
            slug = "pricing"
            for ws, doc, body in ((ws_a, doc_a, "A"), (ws_b, doc_b, "B")):
                await design_publishes.upsert_web_publish(
                    conn,
                    workspace_id=ws,
                    slug=slug,
                    document_id=doc,
                    doc_version=1,
                    html=f"<html>{body}</html>",
                    runtime_version=None,
                    publish_id=None,
                )
            assert (await design_publishes.require_web_publish(conn, workspace_id=ws_a, slug=slug))[
                "html"
            ] == "<html>A</html>"
            assert (await design_publishes.require_web_publish(conn, workspace_id=ws_b, slug=slug))[
                "html"
            ] == "<html>B</html>"
            # Fail-closed: another tenant's slug is indistinguishable from an absent one.
            ws_c = await _seed_ws(conn, "o6c")
            assert (
                await design_publishes.get_web_publish(conn, workspace_id=ws_c, slug=slug) is None
            )
            with pytest.raises(DesignNotFoundError):
                await design_publishes.require_web_publish(conn, workspace_id=ws_c, slug=slug)
            await txn.rollback()

    run_async(_check())


def test_publish_revisions_are_append_only_and_content_addressed(
    require_design_db: None,
) -> None:
    """UPDATE and DELETE are rejected by trigger; a mis-addressed publish_id fails the CHECK."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "imm")
            doc = await _seed_document(conn, ws)
            revision = _revision("immutable-slug", doc, "only")
            stored = await design_publishes.register_web_publish_revision(
                conn, workspace_id=ws, revision=revision
            )
            publish_id = stored["publish_id"]

            # Re-registering the identical package is a no-op that returns the stored row.
            again = await design_publishes.register_web_publish_revision(
                conn, workspace_id=ws, revision=revision
            )
            assert again == stored

            # The same package digest carrying different content is a loud refusal. D6 Round C
            # made it a TYPED one: it used to be a bare ``ValueError`` nothing caught, so the API
            # answered 500; it is now the same taxonomy error the component registry raises for
            # the same species of collision, and the API answers 409.
            with pytest.raises(
                DesignArtifactConflictError, match="already exists with different content"
            ):
                await design_publishes.register_web_publish_revision(
                    conn, workspace_id=ws, revision={**revision, "html": "<html>tampered</html>"}
                )

            for mutation in (
                "UPDATE design_web_publish_revision SET html = 'x' WHERE publish_id = :p",
                "DELETE FROM design_web_publish_revision WHERE publish_id = :p",
            ):
                nested = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="immutable|append-only"):
                    await conn.execute(text(mutation), {"p": publish_id})
                await nested.rollback()

            # The content address is structural, not a naming convention.
            nested = await conn.begin_nested()
            with pytest.raises(IntegrityError, match="content_address"):
                await conn.execute(
                    text(
                        "INSERT INTO design_web_publish_revision (publish_id, workspace_id, slug,"
                        " document_id, doc_version, html, html_digest, manifest_json,"
                        " manifest_digest, package_digest)"
                        " VALUES ('webpub_not_the_digest', :w, 's', :d, 1, '<html/>', :sha,"
                        " '{}'::jsonb, :sha, :sha)"
                    ),
                    {"w": ws, "d": doc, "sha": _sha("x")},
                )
            await nested.rollback()
            await txn.rollback()

    run_async(_check())


# --- custom components ------------------------------------------------------------------------


def test_component_register_source_revision_and_compilation_round_trip(
    require_design_db: None,
) -> None:
    """artifact + source revision + compilation, with the identity row's pointer advance."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "cc")
            account_id = await _seed_account(conn, ws)
            slug = "book-a-call"

            artifact = await design_components.register_custom_component_artifact(
                conn, workspace_id=ws, candidate=_artifact_candidate(account_id, slug, "v1")
            )
            assert artifact["slug"] == slug
            assert artifact["css"] is None and artifact["first_frame"] is None
            assert isinstance(artifact["created_at"], str)
            # An exact retry is idempotent (INSERT-only registry; the row is immutable).
            assert (
                await design_components.register_custom_component_artifact(
                    conn, workspace_id=ws, candidate=_artifact_candidate(account_id, slug, "v1")
                )
                == artifact
            )
            # Registering the artifact minted the component identity row.
            component = await design_components.require_custom_component(
                conn, workspace_id=ws, account_id=account_id, slug=slug
            )
            assert component["source_version"] == 0
            assert component["current_source_revision_id"] is None
            assert [a["artifact_id"] for a in component["artifacts"]] == [artifact["artifact_id"]]

            # First source revision: CAS from 0 → 1, and the identity pointer advances.
            revision = await design_components.create_custom_component_source_revision(
                conn,
                workspace_id=ws,
                candidate=_source_candidate(account_id, slug, "r1"),
                expected_version=0,
            )
            assert revision["source_version"] == 1
            current = await design_components.get_current_custom_component_source(
                conn, workspace_id=ws, account_id=account_id, slug=slug
            )
            assert current is not None
            assert current["revision_id"] == revision["revision_id"]

            # A stale expected_version loses the CAS rather than skipping a version.
            with pytest.raises(DesignSourceVersionConflictError) as conflict:
                await design_components.create_custom_component_source_revision(
                    conn,
                    workspace_id=ws,
                    candidate=_source_candidate(account_id, slug, "stale"),
                    expected_version=0,
                )
            assert conflict.value.current_version == 1

            second = await design_components.create_custom_component_source_revision(
                conn,
                workspace_id=ws,
                candidate=_source_candidate(account_id, slug, "r2"),
                expected_version=1,
            )
            assert second["source_version"] == 2
            listed = await design_components.list_custom_component_source_revisions(
                conn, workspace_id=ws, account_id=account_id, slug=slug
            )
            assert [r["source_version"] for r in listed] == [2, 1]  # newest first, ported

            compilation_id = f"cccmp_{uuid4().hex}"
            compilation = await design_components.record_custom_component_compilation(
                conn,
                workspace_id=ws,
                compilation={
                    "compilation_id": compilation_id,
                    "account_id": account_id,
                    "slug": slug,
                    "source_revision_id": second["revision_id"],
                    "source_version": 2,
                    "status": "succeeded",
                    "compiler_protocol_version": 2,
                    "compiler_version": "1.2.3",
                    "diagnostics": [],
                    "artifact_id": artifact["artifact_id"],
                },
            )
            assert compilation["status"] == "succeeded"
            assert compilation["artifact_id"] == artifact["artifact_id"]
            assert [
                c["compilation_id"]
                for c in await design_components.list_custom_component_compilations(
                    conn, workspace_id=ws, account_id=account_id, slug=slug
                )
            ] == [compilation_id]

            # A successful compile must cite an artifact of the SAME component.
            other = await design_components.register_custom_component_artifact(
                conn, workspace_id=ws, candidate=_artifact_candidate(account_id, "other", "o1")
            )
            with pytest.raises(ValueError, match="artifact slug does not match"):
                await design_components.record_custom_component_compilation(
                    conn,
                    workspace_id=ws,
                    compilation={
                        "compilation_id": f"cccmp_{uuid4().hex}",
                        "account_id": account_id,
                        "slug": slug,
                        "source_revision_id": second["revision_id"],
                        "source_version": 2,
                        "status": "succeeded",
                        "compiler_protocol_version": 2,
                        "compiler_version": "1.2.3",
                        "diagnostics": [],
                        "artifact_id": other["artifact_id"],
                    },
                )

            summary = await design_components.list_custom_components(
                conn, workspace_id=ws, account_id=account_id
            )
            by_slug = {row["slug"]: row for row in summary}
            assert by_slug[slug]["artifact_count"] == 1
            assert by_slug[slug]["source_version"] == 2
            assert by_slug[slug]["latest_artifact_id"] == artifact["artifact_id"]
            await txn.rollback()

    run_async(_check())


def test_artifacts_are_workspace_and_account_scoped_and_cascade_with_the_account(
    require_design_db: None,
) -> None:
    """Fail-closed reads across tenants + the new account CASCADE (SQLite orphaned these)."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "ccscope")
            other_ws = await _seed_ws(conn, "ccother")
            account_id = await _seed_account(conn, ws)
            beta_id = await _seed_account(conn, ws)
            slug = "hero"
            artifact = await design_components.register_custom_component_artifact(
                conn, workspace_id=ws, candidate=_artifact_candidate(account_id, slug, "s1")
            )
            await design_components.create_custom_component_source_revision(
                conn,
                workspace_id=ws,
                candidate=_source_candidate(account_id, slug, "s1"),
                expected_version=0,
            )
            artifact_id = artifact["artifact_id"]

            # Another workspace cannot resolve it at all (the reference-validation read).
            assert (
                await design_components.get_custom_component_artifact(
                    conn, workspace_id=other_ws, artifact_id=artifact_id
                )
                is None
            )
            # Another ACCOUNT in the same workspace cannot either.
            assert (
                await design_components.get_custom_component_artifact_for_account(
                    conn, workspace_id=ws, account_id=beta_id, artifact_id=artifact_id
                )
                is None
            )
            with pytest.raises(DesignNotFoundError):
                await design_components.require_custom_component_artifact(
                    conn, workspace_id=ws, account_id=beta_id, artifact_id=artifact_id
                )
            # An unknown account cannot register anything (fail-closed, now also a real FK).
            with pytest.raises(DesignNotFoundError):
                await design_components.register_custom_component_artifact(
                    conn,
                    workspace_id=ws,
                    candidate=_artifact_candidate("acc_nope", slug, "s2"),
                )

            await design_accounts.delete_web_account(conn, workspace_id=ws, account_id=account_id)
            for table in (
                "design_custom_component",
                "design_custom_component_artifact",
                "design_custom_component_source_revision",
            ):
                remaining = (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE account_id = :a"),
                        {"a": account_id},
                    )
                ).scalar_one()
                assert remaining == 0, table
            await txn.rollback()

    run_async(_check())
