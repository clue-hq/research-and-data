"""Agent-written Puck sections (Wave 2 Lane B, Contract 4): the one governed write.

``design_record_site_section`` stores one compiled section — its source, its compiled module and
its CSS — in this workspace's DesignBlobStore under ``SOURCE_KEY_SITE_SECTION`` (which the public
``/asset-store`` read never serves) and records its ``design_site_section`` row. The digest is the
sha256 of the module bytes, computed here, so no caller can name a digest its bytes do not have.

The props schema is read HERE, from the module itself, inside Lane A's hardened render page
(``site_render.read_section_schema``), so the stored schema is always the module's own and no agent
module is ever imported in a platform process (D2). A module that cannot be read refuses with
``SiteSectionRefused`` and nothing is stored.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import Field

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "RecordSiteSectionInput",
    "RecordSiteSectionTool",
    "SiteSectionRef",
    "SiteSectionRefused",
    "record_site_section_bytes",
]

#: The same rule the table's CHECK holds (design_site_section_name_shape).
SECTION_NAME_PATTERN = r"^[A-Z][A-Za-z0-9]{2,40}$"


class SiteSectionRefused(Exception):
    """The module cannot join a site: its props schema could not be read in the render page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RecordSiteSectionInput(ToolInput):
    name: str = Field(pattern=SECTION_NAME_PATTERN)
    #: The section's TSX source as the agent wrote it.
    source: str
    #: The esbuild output (ESM; imports only react, react/jsx-runtime and zod).
    module_js: str
    #: Tailwind's output for the section's own classes under the brand theme.
    css: str = ""


class SiteSectionRef(ToolOutput):
    digest: str
    name: str
    source_sha256: str
    css_sha256: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_site_section_bytes(
    *,
    repository: Any,
    blobs: Any,
    name: str,
    source: str,
    module_js: str,
    css: str,
    created_by_run_id: str | None,
    read_schema: Callable[[str], dict],
) -> SiteSectionRef:
    """Read the module's props schema, store the three files, record the row."""

    from clue_design.storage import SOURCE_KEY_SITE_SECTION

    try:
        props_schema = read_schema(module_js)
    except Exception as error:  # Lane A's SiteRenderError carries .code and .message
        raise SiteSectionRefused(
            str(getattr(error, "code", "render.failed")), str(getattr(error, "message", error))
        ) from error
    module_bytes, source_bytes, css_bytes = module_js.encode("utf-8"), source.encode("utf-8"), css.encode("utf-8")
    for data, media_type in (
        (module_bytes, "text/javascript"),
        (source_bytes, "text/plain"),
        (css_bytes, "text/css"),
    ):
        blobs.register(data, media_type=media_type, source_key=SOURCE_KEY_SITE_SECTION)
    row = repository.record_site_section(
        digest=_sha(module_bytes),
        name=name,
        source_sha256=_sha(source_bytes),
        css_sha256=_sha(css_bytes),
        props_schema=props_schema,
        created_by_run_id=created_by_run_id,
    )
    return SiteSectionRef(
        digest=row["digest"], name=row["name"], source_sha256=row["source_sha256"], css_sha256=row["css_sha256"]
    )


class RecordSiteSectionTool(DesignTool):
    """Record one compiled agent-written Puck section in this workspace."""

    name = "design_record_site_section"
    version = "1"
    model_description = (
        "Record one compiled agent-written website section (its source, compiled module and CSS) in "
        "this workspace, with the props schema its module declares. Returns the section's digest "
        "and file digests, never its code."
    )
    input_model: ClassVar[type[ToolInput]] = RecordSiteSectionInput
    output_model: ClassVar[type[ToolOutput]] = SiteSectionRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + sha256(module_js)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "content-addressed: the row's key is the module's sha256 and the blobs are stored by "
            "their own sha256, so a repeat of the same module converges on one row and one set of "
            "blobs; the schema read is a pure function of the module"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(safe_display_fields=("name",))

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RecordSiteSectionInput)
        from ..site_render import read_section_schema

        return record_site_section_bytes(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            name=inputs.name,
            source=inputs.source,
            module_js=inputs.module_js,
            css=inputs.css,
            created_by_run_id=ctx.actor_id,
            read_schema=lambda module_js: read_section_schema(module_js),
        )
