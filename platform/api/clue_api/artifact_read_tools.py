"""``read_artifact@1`` — the Head of ABM opens one artifact from this project's gallery.

The design trio writes landing pages and ads into the rail beside the conversation, and until now
the agent that commissioned them could not read one back. It knew only what its own leg said while
the leg was open; the moment a human renamed the page, republished it, or came back a week later
to ask "what does the hero say now?", the honest answer lived in a row nobody in the conversation
could see. This is that read: the gallery's own row, plus — when asked for — the document's page
JSON as text.

Three things are deliberate here, and each one is a test:

* **Containment is the leg join, not the tenant.** A ``design_document`` carries a workspace, never
  a project, so "is this artifact this project's?" is answered by the same statement the rail's
  feed is drawn from (:func:`~clue_api.design_leg_wiring.project_design_documents`): the documents
  named by the legs of *this project's* threads. A document that join does not return is refused
  ``artifact_not_found`` — the identical code a document that never existed gets, so the read never
  tells one project that another project's artifact is out there.
* **The project is ambient.** The workspace comes from :class:`~clue_toolbelt.ToolContext` and the
  project from the turn's own ``execution`` row. Neither is a body field: a model-authored project
  id would be the containment check asking the caller to mark its own homework.
* **The body is bounded and says when it was cut.** ``section="content"`` serves the document's
  page JSON as canonical text, cut at :data:`READ_REFERENCES_BUDGET_BYTES` with
  ``body_truncated=True``. A silently truncated page is how an agent comes to describe a section
  that was never in its context; the flag is how it knows to go and get the rest.

Effect-free, like the ARV2 reads it sits beside, and composed wherever there is a database: it
reads rows that already exist and spends nothing to do it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.arv2.read_tools import READ_REFERENCES_BUDGET_BYTES
from clue_api.design_leg_wiring import head_of_abm_doc_kind, project_design_documents
from clue_db import ConnFactory, transaction
from clue_design.documents import get_document as get_design_document
from clue_design.errors import DesignNotFoundError
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "READ_REFERENCES_BUDGET_BYTES",
    "ArtifactReadRefused",
    "ArtifactView",
    "ReadArtifactInput",
    "ReadArtifactOutput",
    "ReadArtifactTool",
    "build_artifact_read_tools",
    "read_artifact",
]


class ArtifactReadRefused(Exception):
    """The read cannot be served, and the caller is told which prerequisite is missing.

    ``code`` is stable and machine-readable; the tool turns it straight into a
    :class:`~clue_toolbelt.PreconditionFailure`. Codes: ``artifact_not_found`` (no such artifact in
    *this project's* gallery — a neighbour project's document is refused the same way a
    non-existent one is), ``project_not_found`` (this turn carries no project coordinate, so there
    is no gallery to look in).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ArtifactView:
    """One gallery artifact, as this project may see it."""

    artifact_id: str
    #: ``web`` or ``ad`` — the rail's own vocabulary, mapped from the document's ``doc_kind``.
    kind: str
    title: str
    status: str
    current_version_id: str
    #: The thread whose leg this document was born on: where the conversation about it happened.
    origin_thread_id: str
    updated_at: str
    #: ``content`` only: the document's page JSON as canonical text, within the budget.
    body_text: str
    body_truncated: bool


#: The turn's project, read from the coordinate the platform stamped rather than from the model.
_EXECUTION_PROJECT = text(
    "SELECT project_id FROM execution WHERE id = :execution_id AND workspace_id = :workspace_id"
)


def _cut_to_budget(body: str) -> tuple[str, bool]:
    """``body`` within :data:`READ_REFERENCES_BUDGET_BYTES`, and whether anything was cut.

    Measured in BYTES, because the budget is a receipt budget: the runtime counts the encoded
    result, not its characters. A cut that lands mid-character drops that character rather than
    emitting a replacement, so what survives is always decodable text.
    """

    encoded = body.encode()
    if len(encoded) <= READ_REFERENCES_BUDGET_BYTES:
        return body, False
    return encoded[:READ_REFERENCES_BUDGET_BYTES].decode("utf-8", "ignore"), True


async def read_artifact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    artifact_id: str,
    section: str,
) -> ArtifactView:
    """One design document of ``project_id``'s gallery, by id.

    The membership statement runs first and is the whole security argument: the document must be
    one the rail would list for this project, or nothing is read at all.
    """

    documents = await project_design_documents(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    listed = _find(documents, artifact_id)
    if listed is None:
        raise ArtifactReadRefused(
            "artifact_not_found",
            f"no artifact {artifact_id!r} in this project's gallery",
        )
    try:
        document = await get_design_document(
            conn, workspace_id=workspace_id, document_id=artifact_id
        )
    except DesignNotFoundError as missing:
        # Unreachable through the join above (it read the document row itself), and refused by the
        # same name anyway: a caller is never told the difference between absent and not-ours.
        raise ArtifactReadRefused(
            "artifact_not_found",
            f"no artifact {artifact_id!r} in this project's gallery",
        ) from missing

    body_text, body_truncated = "", False
    if section == "content":
        # The canonical encoding the receipt is measured in, so the cap the caller is promised is
        # the cap the runtime enforces.
        body_text, body_truncated = _cut_to_budget(
            json.dumps(document.get("scene"), sort_keys=True, separators=(",", ":"))
        )
    return ArtifactView(
        artifact_id=artifact_id,
        kind="web" if head_of_abm_doc_kind(str(document["doc_kind"])) == "web" else "ad",
        title=str(document["title"]),
        status=str(document["status"]),
        current_version_id=str(document["current_version"]),
        origin_thread_id=str(listed["origin_thread_id"]),
        updated_at=str(document["updated_at"]),
        body_text=body_text,
        body_truncated=body_truncated,
    )


def _find(documents: Sequence[Mapping[str, Any]], artifact_id: str) -> Mapping[str, Any] | None:
    return next((row for row in documents if str(row["id"]) == artifact_id), None)


async def _ambient_project_id(conn: AsyncConnection, ctx: ToolContext) -> str:
    """The project this turn runs in, from the ``execution`` row the platform stamped.

    The same coordinate the ``project`` pin resolves from (``clue_api.stage0_recipe``), for the
    same reason: a body field is model-authored and an execution's project is not.
    """

    if ctx.execution_id is None:
        raise ArtifactReadRefused(
            "project_not_found", "this turn is not bound to a project in this workspace"
        )
    project_id = (
        await conn.execute(
            _EXECUTION_PROJECT,
            {"execution_id": ctx.execution_id, "workspace_id": ctx.workspace_id},
        )
    ).scalar_one_or_none()
    if not isinstance(project_id, str) or not project_id:
        raise ArtifactReadRefused(
            "project_not_found", "this turn is not bound to a project in this workspace"
        )
    return project_id


class ReadArtifactInput(ToolInput):
    #: The design-document id the gallery lists — what ``project/artifacts/index.json`` records.
    artifact_id: str
    #: ``summary`` is the card: what it is, what it is called, where it came from. ``content`` adds
    #: the page JSON itself, which is what a question about the words on the page needs.
    section: Literal["summary", "content"] = "summary"


class ReadArtifactOutput(ToolOutput):
    artifact_id: str
    #: ``web`` (a page) or ``ad``.
    kind: str
    title: str
    status: str
    current_version_id: str
    #: The thread the artifact was made on, so the agent can point the human at the conversation.
    origin_thread_id: str
    updated_at: str
    #: ``content`` only: the document's page JSON as text, capped at
    #: :data:`READ_REFERENCES_BUDGET_BYTES`. ``summary`` leaves it empty.
    body_text: str
    #: The page was larger than the cap and what came back is its beginning, not the whole of it.
    body_truncated: bool


class ReadArtifactTool(Tool):
    """Read one artifact from this project's gallery."""

    name = "read_artifact"
    version = "1"
    model_description = (
        "Read one artifact from this project's gallery (a landing page or an ad) by its id: "
        "section=summary gives what it is, what it is called, its status, its version and the "
        "thread it was made on; section=content adds the document's page JSON as text, capped, "
        "with body_truncated saying whether there is more. Read this before describing an "
        "artifact or what it says. Effect-free. " + tool_manual_link("read_artifact")
    )
    input_model: ClassVar[type[ToolInput]] = ReadArtifactInput
    output_model: ClassVar[type[ToolOutput]] = ReadArtifactOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="the design document behind this project's gallery row",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("artifact_id", "section"))
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5). It is also the gallery this read looks in.
    pin_requirements = ("project",)

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadArtifactInput)
        try:
            async with self._conn_factory() as conn:
                # Both statements in one transaction: the membership answer and the document it
                # admits are one consistent read, never two that raced each other.
                project_id = await _ambient_project_id(conn, ctx)
                view = await read_artifact(
                    conn,
                    # The tenant is AMBIENT authority, never model-authored.
                    workspace_id=ctx.workspace_id,
                    project_id=project_id,
                    artifact_id=inputs.artifact_id,
                    section=inputs.section,
                )
        except ArtifactReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadArtifactOutput(
            artifact_id=view.artifact_id,
            kind=view.kind,
            title=view.title,
            status=view.status,
            current_version_id=view.current_version_id,
            origin_thread_id=view.origin_thread_id,
            updated_at=view.updated_at,
            body_text=view.body_text,
            body_truncated=view.body_truncated,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


def build_artifact_read_tools(*, conn_factory: ConnFactory = transaction) -> tuple[Tool, ...]:
    """The gallery read. Registered everywhere, and composed everywhere there is a database.

    It has no capability of its own to be absent — no storage, no gateway, no flag: it reads the
    ``design_document`` and ``design_leg`` rows the rail already draws from, and reading them
    spends nothing. It is granted at `head-of-abm@v56` — the reviewed bump that pins its contract,
    mints the manual chapter that teaches it and admits it to the conversation's interaction slot.
    """

    return (ReadArtifactTool(conn_factory=conn_factory),)
