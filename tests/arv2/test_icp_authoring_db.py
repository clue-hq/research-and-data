"""Authoring an ICP against the real tables: one proposed version, scoped, with honest lineage.

``author_icp_document`` is the write behind the Head of ABM's ``author_icp_document@1``. What is
worth pinning here is exactly what the model may *not* decide: the document is born ``proposed``
(nothing is confirmed by writing a file), its scope is the caller's — brand-level or project-local
— rather than the front matter's, its lineage names a real brand document or nothing at all, and
the version chain it joins is the one inside its own scope, so a project's variant and the brand's
profile at the same path never interleave or retire each other.

The refusals are the other half: a key that is not a key, front matter that is not an ICP, a key
another scope already owns, and a lineage that names nothing. Each one is typed and named, so the
agent is told what to fix instead of being handed a stack trace or a half-written file.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.icp_authoring import (
    AuthoredIcp,
    IcpAuthoringRefused,
    IcpAuthoringRequest,
    author_icp_document,
    authored_document_id,
)
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import pin_icp, seed_icp_document

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_icp_authoring"
USER_ID = "usr_icp_authoring"

#: A complete ICP the model could plausibly have written: the front matter the contract requires,
#: then a body. Everything the platform owns (status, scope, lineage, authorship) is absent from
#: it — the point being that the platform, not the model, puts those there.
DOCUMENT = """---
kind: icp-definition
icp_key: gi-dac
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: GI-focused ambulatory surgery centre, test: website lists GI procedures}
exclusions: [academic medical centres]
persona_map:
  economic_buyer: {titles: [Administrator]}
qualifier_fields:
  - {field_key: account.gi_case_volume, description: annual GI case volume, display: rail}
---

# GI-focused ASCs

Body.
"""


async def _seed(conn: AsyncConnection) -> tuple[str, str, str]:
    project = await seed_project(conn, WORKSPACE)
    return project.workspace_id, project.project_id, str(project.brand_id)


def _request(
    workspace_id: str,
    brand_id: str,
    project_id: str,
    **overrides: Any,
) -> IcpAuthoringRequest:
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "brand_id": brand_id,
        "project_id": project_id,
        "turn_id": uuid4(),
        "user_id": USER_ID,
        "icp_key": "gi-dac",
        "document_text": DOCUMENT,
        "scope": "project",
        "derived_from_icp_key": None,
    }
    payload.update(overrides)
    return IcpAuthoringRequest(**payload)


async def _row(conn: AsyncConnection, document_id: UUID) -> dict[str, Any]:
    return dict(
        (
            await conn.execute(
                text(
                    "SELECT project_id, derived_from_document_id, status, folder, kind, path, "
                    "       version, artifact_key, supersedes_document_id "
                    "FROM brand_knowledge_document WHERE document_id = :d"
                ),
                {"d": document_id},
            )
        )
        .mappings()
        .one()
    )


async def _front(
    conn: AsyncConnection, storage: FsStorage, authored: AuthoredIcp
) -> dict[str, Any]:
    row = await _row(conn, authored.document_id)
    body = await storage.get(str(row["artifact_key"]))
    front, _ = parse_front_matter(body.decode(), preserve_body=True)
    return front


def test_a_project_local_variant_is_stored_proposed_with_scope_and_lineage(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            brand_icp, _, _ = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi.md",
            )
            request = _request(
                workspace_id, brand_id, project_id, derived_from_icp_key="clue-abm-buyers"
            )

            first = await author_icp_document(conn, storage, request)

            assert (first.version, first.status, first.replayed) == (1, "proposed", False)
            assert first.icp_key == "gi-dac"
            assert first.path == "audience/icp-gi-dac.md"
            assert first.workspace_path == "project/audience/icp-gi-dac.md"
            assert first.document_id == authored_document_id(
                turn_id=request.turn_id, scope="project", icp_key="gi-dac"
            )

            row = await _row(conn, first.document_id)
            assert row["project_id"] == project_id
            assert row["derived_from_document_id"] == brand_icp
            assert (row["status"], row["folder"], row["kind"]) == (
                "proposed",
                "audience",
                "icp-definition",
            )
            assert row["supersedes_document_id"] is None

            front = await _front(conn, storage, first)
            assert front["status"] == "proposed"
            assert front["brand_id"] == brand_id
            assert front["project_id"] == project_id
            assert front["derived_from"] == str(brand_icp)
            assert front["authored_by"] == {
                "turn_id": str(request.turn_id),
                "user_id": USER_ID,
            }
            assert isinstance(front["authored_at"], str) and front["authored_at"]
            # The model's own content survives verbatim beside the platform's stamp.
            assert front["product_ids"] == ["prd_aura"]
            assert front["qualifier_fields"][0]["field_key"] == "account.gi_case_volume"

            again = await author_icp_document(conn, storage, request)
            assert again.replayed is True
            assert again.document_id == first.document_id
            assert again.version == first.version
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM brand_knowledge_document "
                        "WHERE workspace_id = :w AND path = 'audience/icp-gi-dac.md'"
                    ),
                    {"w": workspace_id},
                )
            ).scalar_one() == 1

    run_async(scenario())


def test_a_brand_level_profile_is_stored_unscoped_with_no_lineage(tmp_path: Any) -> None:
    """A brand profile belongs to the brand: no ``project_id``, no ``derived_from``, and it
    materializes under the brand's knowledge prefix rather than the project's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            authored = await author_icp_document(
                conn, storage, _request(workspace_id, brand_id, project_id, scope="brand")
            )

            assert authored.workspace_path == "brand/knowledge/audience/icp-gi-dac.md"
            row = await _row(conn, authored.document_id)
            assert row["project_id"] is None
            assert row["derived_from_document_id"] is None
            front = await _front(conn, storage, authored)
            assert front["status"] == "proposed"
            assert "project_id" not in front
            assert "derived_from" not in front

    run_async(scenario())


def test_a_second_turn_supersedes_the_first_version_inside_its_own_scope(tmp_path: Any) -> None:
    """The next version of a project's variant retires the project's earlier draft — and leaves
    the brand's own row at the same path completely alone.

    The brand row is seeded ``superseded`` because that is the only way the two scopes legitimately
    share a path: a servable brand document would have refused this project's key outright
    (``icp_key_taken_by_brand``). Retired, it owns nothing — and it must still not be re-versioned
    or re-retired by a chain it is not part of.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            brand_doc, _, _ = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi-dac.md",
                status="superseded",
            )

            first = await author_icp_document(
                conn, storage, _request(workspace_id, brand_id, project_id)
            )
            second = await author_icp_document(
                conn, storage, _request(workspace_id, brand_id, project_id)
            )

            assert (first.version, second.version) == (1, 2)
            assert second.document_id != first.document_id
            assert (await _row(conn, first.document_id))["status"] == "superseded"
            second_row = await _row(conn, second.document_id)
            assert second_row["status"] == "proposed"
            assert second_row["supersedes_document_id"] == first.document_id
            # The brand's row shares the path and is in the other scope: untouched, still v1 —
            # so the project's own chain started at 1 beside it rather than continuing it.
            brand_row = await _row(conn, brand_doc)
            assert (brand_row["status"], brand_row["version"], brand_row["project_id"]) == (
                "superseded",
                1,
                None,
            )

    run_async(scenario())


def test_a_confirmed_version_in_scope_is_never_retired(tmp_path: Any) -> None:
    """A human's yes is somebody's pinned ICP. A new proposal joins the chain beside it; it does
    not retire it (the rule ``onboarding_synthesis`` already holds for re-synthesis)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            confirmed, _, _ = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="audience/icp-gi-dac.md",
                status="confirmed",
            )

            authored = await author_icp_document(
                conn, storage, _request(workspace_id, brand_id, project_id)
            )

            assert authored.version == 2
            assert (await _row(conn, confirmed))["status"] == "confirmed"
            # Nothing servable was retired, so the new proposal supersedes the row it follows.
            assert (await _row(conn, authored.document_id))["supersedes_document_id"] == confirmed

    run_async(scenario())


def test_an_unparseable_key_is_refused_by_name(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            for bad in ("GI-DAC", "gi dac", "gi--dac", "-gi", "gi-", "g" * 61):
                with pytest.raises(IcpAuthoringRefused) as excinfo:
                    await author_icp_document(
                        conn, storage, _request(workspace_id, brand_id, project_id, icp_key=bad)
                    )
                assert excinfo.value.code == "icp_key_invalid"

    run_async(scenario())


def test_front_matter_that_is_not_an_icp_is_refused_by_name(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            without_gates = DOCUMENT.replace(
                "hard_gates:\n  - {key: specialty, rule: GI-focused ambulatory surgery centre, "
                "test: website lists GI procedures}\n",
                "",
            )
            cases = {
                # No front matter at all.
                "# Just a body\n": "no front matter",
                # Front matter, but not an ICP's.
                without_gates: "hard_gates",
                DOCUMENT.replace("product_ids: [prd_aura]\n", ""): "product_ids",
                DOCUMENT.replace("kind: icp-definition", "kind: audience-persona"): "kind",
                DOCUMENT.replace("icp_key: gi-dac", "icp_key: something-else"): "icp_key",
            }
            for document_text, expected in cases.items():
                with pytest.raises(IcpAuthoringRefused) as excinfo:
                    await author_icp_document(
                        conn,
                        storage,
                        _request(workspace_id, brand_id, project_id, document_text=document_text),
                    )
                assert excinfo.value.code == "icp_front_matter_invalid"
                assert expected in str(excinfo.value)

    run_async(scenario())


#: What an inline ``{key: …, rule: …}`` gate becomes when a value carries a comma: YAML splits the
#: value there, keeps the first fragment, and turns every later fragment into a key with no value.
#: The same shape a stored broken ICP has (``tests/scripts/test_trial_target_discovery.py``).
COMMA_SPLIT_GATES = """hard_gates:
- key: guest_function
  rule: There is a named plant-operations
  quality: null
  or maintenance function that owns uptime.: null
  test: Careers pages list Plant Operations
"""

#: The block form the icp-synthesis skill now asks for: every value quoted, so a comma is text.
BLOCK_DOCUMENT = """---
kind: icp-definition
icp_key: gi-dac
product_ids: [prd_aura]
hard_gates:
  - key: "guest_function"
    rule: "There is a named plant-operations, quality, or maintenance function that owns uptime."
    test: "Careers pages list Plant Operations, Quality, or Maintenance."
exclusions:
  - "Widget resellers, distributors, and marketplaces."
persona_map:
  economic_buyer:
    titles:
      - "VP, Plant Operations"
qualifier_fields:
  - field_key: "account.gi_case_volume"
    description: "Annual GI case volume, per site, from the latest public filing."
    display: "rail"
---

# GI-focused ASCs

Body.
"""


def test_a_comma_split_row_is_refused_naming_the_row_and_the_stray_key(tmp_path: Any) -> None:
    """A row with a value-less key that is not one of the row's fields is text a comma cut off.

    Storing it would keep the first fragment as the rule and lose the rest silently, so it is
    refused by name — the gate (or qualifier field) and the fragment — for the author to rewrite.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            gate_split = DOCUMENT.replace(
                "hard_gates:\n  - {key: specialty, rule: GI-focused ambulatory surgery centre, "
                "test: website lists GI procedures}\n",
                COMMA_SPLIT_GATES,
            )
            qualifier_split = DOCUMENT.replace(
                "description: annual GI case volume,",
                "description: annual GI case volume, per site,",
            )
            cases = {
                gate_split: ("guest_function", "or maintenance function that owns uptime."),
                qualifier_split: ("account.gi_case_volume", "per site"),
            }
            for document_text, (row_key, stray) in cases.items():
                with pytest.raises(IcpAuthoringRefused) as excinfo:
                    await author_icp_document(
                        conn,
                        storage,
                        _request(workspace_id, brand_id, project_id, document_text=document_text),
                    )
                assert excinfo.value.code == "icp_front_matter_invalid"
                assert row_key in str(excinfo.value)
                assert stray in str(excinfo.value)
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM brand_knowledge_document WHERE workspace_id = :ws"),
                    {"ws": workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_a_block_yaml_document_keeps_every_comma_inside_its_quoted_values(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)

            authored = await author_icp_document(
                conn,
                storage,
                _request(workspace_id, brand_id, project_id, document_text=BLOCK_DOCUMENT),
            )

            front = await _front(conn, storage, authored)
            assert front["hard_gates"] == [
                {
                    "key": "guest_function",
                    "rule": (
                        "There is a named plant-operations, quality, or maintenance function "
                        "that owns uptime."
                    ),
                    "test": "Careers pages list Plant Operations, Quality, or Maintenance.",
                }
            ]
            assert front["exclusions"] == ["Widget resellers, distributors, and marketplaces."]
            assert front["persona_map"] == {"economic_buyer": {"titles": ["VP, Plant Operations"]}}
            assert front["qualifier_fields"] == [
                {
                    "field_key": "account.gi_case_volume",
                    "description": (
                        "Annual GI case volume, per site, from the latest public filing."
                    ),
                    "display": "rail",
                }
            ]

    run_async(scenario())


def test_a_key_another_scope_already_owns_is_refused_by_name(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi-dac.md",
                status="proposed",
            )

            with pytest.raises(IcpAuthoringRefused) as excinfo:
                await author_icp_document(
                    conn, storage, _request(workspace_id, brand_id, project_id, scope="project")
                )
            assert excinfo.value.code == "icp_key_taken_by_brand"

    run_async(scenario())


def test_a_key_a_project_already_owns_is_refused_to_the_brand(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="audience/icp-gi-dac.md",
                status="proposed",
            )

            with pytest.raises(IcpAuthoringRefused) as excinfo:
                await author_icp_document(
                    conn, storage, _request(workspace_id, brand_id, project_id, scope="brand")
                )
            assert excinfo.value.code == "icp_key_taken_by_project"

    run_async(scenario())


def test_a_lineage_that_names_nothing_is_refused_by_name(tmp_path: Any) -> None:
    """``derived_from`` must name a *brand* profile that exists. A project's own variant is not
    one, so naming another project's key is the same honest absence as naming nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                project_id=project_id,
                path="audience/icp-other.md",
                body=DOCUMENT.replace("icp_key: gi-dac", "icp_key: other"),
                status="proposed",
            )

            for missing in ("no-such-icp", "other"):
                with pytest.raises(IcpAuthoringRefused) as excinfo:
                    await author_icp_document(
                        conn,
                        storage,
                        _request(workspace_id, brand_id, project_id, derived_from_icp_key=missing),
                    )
                assert excinfo.value.code == "derived_from_not_found"
            # Nothing was written on the way to the refusal.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM brand_knowledge_document "
                        "WHERE workspace_id = :w AND path = 'audience/icp-gi-dac.md'"
                    ),
                    {"w": workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_a_revision_over_a_pinned_path_is_named_at_its_version_qualified_file(
    tmp_path: Any,
) -> None:
    """The receipt names the file the *next turn* opens, not the path's plain name (review I3).

    The materializer gives the **pinned** version of a path the plain name and offers every other
    version beside it as ``…/icp-<key>.v<n>.md`` (``brand_knowledge_context.workspace_paths``). An
    authored row is always born ``proposed``, so it is never the pin — which means the moment a
    project has pinned anything at that path, a new version of it lands at the qualified name.

    Skill v23 §5b tells the model in as many words that *"the receipt names the path the file will
    have on your next turn"*. A receipt promising the plain name therefore sends the agent to
    re-read the **pinned, older** profile as though it were its own new draft: it either concludes
    the write failed and authors again, or reports the stale profile back to the human as the new
    one. Not reachable before the project has a pin, which is why the first tests did not see it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi.md",
                status="superseded",
                version=1,
                body=DOCUMENT.replace("icp_key: gi-dac", "icp_key: gi"),
            )
            pinned_id, pinned_key, pinned_sha = await seed_icp_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=brand_id,
                path="audience/icp-gi.md",
                status="confirmed",
                version=2,
                body=DOCUMENT.replace("icp_key: gi-dac", "icp_key: gi") + "\nv2\n",
            )
            await pin_icp(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                brand_id=brand_id,
                document_id=pinned_id,
                artifact_key_=pinned_key,
                artifact_sha256=pinned_sha,
                icp_key="gi",
            )

            authored = await author_icp_document(
                conn,
                storage,
                _request(
                    workspace_id,
                    brand_id,
                    project_id,
                    icp_key="gi",
                    scope="brand",
                    document_text=DOCUMENT.replace("icp_key: gi-dac", "icp_key: gi"),
                ),
            )

            assert (authored.version, authored.status) == (3, "proposed")
            assert authored.path == "audience/icp-gi.md"
            assert authored.workspace_path == "brand/knowledge/audience/icp-gi.v3.md"
            # The pin still owns the plain name, so nothing this act wrote moved the human's ICP.
            assert (
                await conn.execute(
                    text("SELECT status FROM brand_knowledge_document WHERE document_id = :d"),
                    {"d": pinned_id},
                )
            ).scalar_one() == "confirmed"

    run_async(scenario())


def test_an_unpinned_path_keeps_the_plain_name_in_the_receipt(tmp_path: Any) -> None:
    """The other half of I3: version-qualification is the pin's doing, not a new default.

    With no pin on the path, the authored version *is* what the workspace serves at the plain
    name, and a qualified receipt would send the agent to a file nothing materializes.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            workspace_id, project_id, brand_id = await _seed(conn)
            authored = await author_icp_document(
                conn,
                storage,
                _request(
                    workspace_id,
                    brand_id,
                    project_id,
                    icp_key="gi",
                    scope="brand",
                    document_text=DOCUMENT.replace("icp_key: gi-dac", "icp_key: gi"),
                ),
            )
            assert authored.workspace_path == "brand/knowledge/audience/icp-gi.md"

    run_async(scenario())
