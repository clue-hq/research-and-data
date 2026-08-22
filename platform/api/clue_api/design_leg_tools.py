"""The governed delegation entry onto the design leg (Part III P3.4, PD-part3 §1-D1/§2.3).

One tool, ``open_design_leg@3``, granted to the Head of ABM. It is the materialization of the
master plan's "attach as subagent" wrapper under ruling D1: delegating to Design is not a
LangGraph edge but a durable act — validate the D5 pins, build the §2.3 delegation bundle as one
immutable canonical-JSON artifact, and open the ``design_leg`` row whose existence *is* the
routing rule ("an open leg on the thread receives the user's message").

The authority discipline is the ``open_directive_confirmation_gate`` precedent, applied verbatim:

* **The leg's anchor is not the agent's choice.** The leg is derived from the turn the agent is
  answering (``source_turn_ref``, served through the PC-C8 ``TRUSTED_TURN_FIELD`` seam and
  stripped from the model-visible schema): its thread, its project, its execution. One presenting
  turn derives one leg id, so a replayed delegation converges on the same leg instead of racing
  the partial-unique index.
* **The pins are verified, never trusted.** A document pin's CAS guard is read from the durable
  ``design_document`` row (an ``expected_document_version`` that is not current is refused —
  D5's "mismatch = honest refusal"); a brand pin must name an existing ``(brand_kit_id,
  version)`` row — the fail-closed rule that makes the design entrypoint's silent default
  fallback an *error* once a bundle pin exists.
* **The bundle is bounded at build.** §2.3's day-one size policy: refs-only content and a hard
  byte cap (:data:`DESIGN_DELEGATION_BUNDLE_MAX_BYTES`), enforced here so an oversized bundle
  fails the delegation loudly rather than failing some later design turn confusingly. The cap is
  half of the 48k L3 layer (utf8-bytes token counter), because the C8 project card legitimately
  occupies the other half.

Claim refs ride the :class:`~clue_core.ContactHandoffClaimRef` vocabulary (ids + governance
stamps, never values) — validated structurally at the input model. Their existence/governance
provenance is the research-view surface's job: the only way a head-of-abm holds claim ids at all
is by having read them through ``get_research_view``.

What this tool does **not** do: dispatch anything. Opening a leg spends nothing and runs no
design turn; the agent's next act is to tell the user the design session is open and end its
turn. The user's next message on the thread is what becomes the first design turn (the P3.4
routing rule in ``agent_turn_fleet_wiring``).

**@2 — document birth at leg-open (genweb slice 2, plan §4.1).** A leg may now *create* the
document its docstring always promised (§2.1). ``doc_kind="web"`` on a document-less open
births one empty website-mode document and pins the leg to it at birth
(``document_version_guard=0``), so "make me a landing page" finally has somewhere to land and
the rail's gallery derivation — legs joined to ``design_document`` where ``doc_kind='web'`` —
picks the card up the moment the leg opens. Two disciplines make the birth safe:

* **One invocation, one document.** The document id is derived from the leg id, which is
  itself derived from the presenting turn — so a retried delegation converges on the same
  document row instead of minting twins, exactly as it already converges on the same leg. The
  create and the leg insert share ONE transaction: neither can survive the other.
* **The birth is where the brand identity is decided, and the leg only reads it back.** The
  create routes through ``clue_design.documents.create_document`` — the frozen creation
  contract that stamps the workspace's latest APPROVED brand kit onto a new web document (and
  fails closed in a multi-brand workspace). The leg's D5 brand pin is then read back off the
  STORED row, never re-derived: a kit approved later in the conversation cannot re-theme the
  document nor move the pin, so every generation turn on this leg designs against exactly the
  kit version the document was born with. No approved kit ⇒ an all-null theme and a leg with
  no pin — un-branded, honestly, and generation still works.

``doc_kind="scene"`` creation was refused in v1 (@2): the ad flow stayed editor-first, and a
scene leg kept requiring an existing document. **Superseded 2026-08-23 (genad ruling 1), @3.**
"Make me a LinkedIn ad" must land the way "make me a landing page" does, so a document-less
``doc_kind="scene"`` open now BIRTHS an empty ad document — under one added precondition, the
ad's **format** (genad ruling 2): one of the ratified presets, or ``custom`` with explicit
``ad_width``/``ad_height`` in px. An ad has a size, so a birth that names none is refused
(``design_leg_ad_format_required``) rather than silently guessing one; a preset carries its own
pixels, so dimensions alongside one are refused too (``design_leg_ad_format_invalid``) instead
of being dropped on the floor, and an ``ad_format`` on a ``web`` open is the same refusal — a
malformed agent belief is worth surfacing. Everything else about the birth is the web path's,
seam for seam: one document per leg (twin-proof under replay), the create and the leg insert in
ONE transaction, and the brand identity decided by the DAL's creation contract at birth and
only READ BACK into the leg's D5 pin.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, JsonValue, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_api.turn_action import (
    TurnActionUnresolvable,
    TurnIdentity,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import ContactHandoffClaimRef
from clue_db import ConnFactory, transaction
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from clue_design.errors import DesignNotFoundError
from clue_storage import StorageBackend
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "DESIGN_DELEGATION_BUNDLE_MAX_BYTES",
    "DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE",
    "DESIGN_LEG_REF_PREFIX",
    "DESIGN_LEG_TITLE_WORD_BUDGET",
    "derive_leg_document_id",
    "FinishDesignLegInput",
    "FinishDesignLegOutput",
    "FinishDesignLegTool",
    "OpenDesignLegInput",
    "OpenDesignLegOutput",
    "OpenDesignLegTool",
    "build_design_leg_tools",
    "design_leg_ref",
]

#: The §2.3 bundle's own media type — one artifact kind, one name.
DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE = "application/vnd.clue.design-delegation-bundle+json"

#: §2.3's day-one hard size policy. The bundle lands in the 48k-token L3 layer
#: (``utf8-bytes-v1`` counter: tokens are bytes) that the C8 project card can half-fill,
#: so the bundle's budget is the other half. An oversized bundle is refused at build.
DESIGN_DELEGATION_BUNDLE_MAX_BYTES = 24_000

#: The opaque reference shape carried in tool results and finalization refs.
DESIGN_LEG_REF_PREFIX = "design-leg:"

#: F5's fallback title: the brief's first words when the agent supplies no ``title``.
DESIGN_LEG_TITLE_WORD_BUDGET = 8

#: The title a whitespace-only brief with no supplied title falls back to (``design_document.title``
#: is NOT NULL, and an empty string is not a title).
_FALLBACK_DOCUMENT_TITLE = "Untitled page"

_LEG_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg")
_LEG_DOCUMENT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-document")


def design_leg_ref(leg_id: str | UUID) -> str:
    return f"{DESIGN_LEG_REF_PREFIX}{leg_id}"


def derive_design_leg_id(*, workspace_id: str, turn_id: UUID) -> str:
    """One presenting turn ⇒ one leg id — the replay identity of the delegation."""

    framed = f"{len(workspace_id)}:{workspace_id}{len(str(turn_id))}:{turn_id}"
    return str(uuid5(_LEG_NAMESPACE, framed))


def derive_leg_document_id(*, leg_id: str) -> str:
    """One leg ⇒ one born document — the A9 replay identity of the birth (§6 trap 3).

    Derived from the leg id (itself derived from the presenting turn) rather than minted
    randomly like the design API's ``new_id("doc")``, so a retried delegation addresses the
    SAME document row. It carries the design subsystem's ``doc_<32 hex>`` id shape so nothing
    downstream can tell a leg-born document from a route-born one.
    """

    return f"doc_{uuid5(_LEG_DOCUMENT_NAMESPACE, leg_id).hex}"


def _document_title(*, title: str | None, brief: str) -> str:
    """F5: the agent's title when it supplied one, else the brief's first ~8 words."""

    if title is not None and title.strip():
        return title.strip()
    words = brief.split()[:DESIGN_LEG_TITLE_WORD_BUDGET]
    return " ".join(words) or _FALLBACK_DOCUMENT_TITLE


async def _emit_leg_lifecycle(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn: TurnIdentity,
    event_type: TurnEventType,
    leg_id: str,
    reason: str | None = None,
) -> None:
    """Delta 8 (P3.7): announce one leg transition on the chat turn stream.

    Emitted in the SAME transaction as the durable transition, on the turn that performed it —
    so a crash can never leave a frame without its row, and a replayed invocation (which
    performs no transition) emits nothing.
    """

    payload: dict[str, JsonValue] = {"leg_id": leg_id}
    if reason is not None:
        payload["reason"] = reason
    await emit_turn_event(
        conn,
        workspace_id=workspace_id,
        project_id=turn.project_id,
        thread_id=turn.thread_id,
        turn_id=turn.turn_id,
        event_type=event_type,
        payload=payload,
    )


class OpenDesignLegInput(ToolInput):
    """What the agent proposes; every authority value is derived by the engine, not accepted."""

    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    #: The design brief — what the user wants made. Free text (D5: no fabricated content plane).
    brief: str = Field(min_length=1, max_length=16_000)
    #: Target document (nullable — a leg may create its document, §2.1).
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    #: What to create when there is no ``document_id`` — REQUIRED on a document-less open.
    #: ``web`` births one empty website-mode document; ``scene`` births one empty ad document
    #: at ``ad_format`` (genad ruling 1, 2026-08-23 — @2 refused scene creation outright).
    #: With a ``document_id`` present the durable row's own kind is the truth and this field
    #: is ignored.
    doc_kind: Literal["web", "scene"] | None = Field(default=None)
    #: The born document's title (F5). Absent ⇒ the brief's first ~8 words. Ignored when the
    #: leg pins an existing document — a delegation never renames someone else's artifact.
    title: str | None = Field(default=None, min_length=1, max_length=200)
    #: genad ruling 2 (2026-08-23): the ad's format, REQUIRED on a document-less
    #: ``doc_kind="scene"`` open. A preset resolves its own dimensions; ``custom`` requires
    #: ``ad_width``/``ad_height`` (px). Ignored when ``document_id`` pins an existing artifact.
    ad_format: Literal["square", "portrait", "story", "landscape", "custom"] | None = Field(
        default=None
    )
    ad_width: int | None = Field(default=None, ge=16, le=8192)
    ad_height: int | None = Field(default=None, ge=16, le=8192)
    #: The document version the agent believes is current. When present it must match the durable
    #: ``current_version`` exactly (the D5 CAS guard); when absent the current version is pinned.
    expected_document_version: int | None = Field(default=None, ge=0)
    #: The D5 fail-closed brand pin — both fields or neither.
    brand_kit_id: str | None = Field(default=None, min_length=1, max_length=200)
    brand_kit_version: int | None = Field(default=None, ge=1)
    #: Governed claim edges (ids + stamps, never values) — the C8 §2.3 vocabulary.
    claim_refs: tuple[ContactHandoffClaimRef, ...] = Field(default=(), max_length=200)
    #: Design's real content vocabulary, both nullable (ruling D5a).
    binding_set_ref: str | None = Field(default=None, min_length=1, max_length=500)
    template_revision_ref: str | None = Field(default=None, min_length=1, max_length=500)
    #: The §2.2 mis-exit recovery: re-delegation NAMES the closed leg to reopen it. The same
    #: leg returns ``open_awaiting_user`` with its original bundle and history — context
    #: resumes, and the exit journal record survives. When present, the pin/bundle fields
    #: above are ignored: a reopen is a resumption, not a fresh delegation.
    reopen_leg_id: str | None = Field(default=None, min_length=1, max_length=64)


class OpenDesignLegOutput(ToolOutput):
    leg_id: str
    leg_ref: str
    thread_id: str
    bundle_artifact_key: str
    bundle_sha256: str
    document_id: str | None
    document_version_guard: int | None
    brand_kit_id: str | None
    brand_kit_version: int | None
    created: bool
    #: ``True`` when this call BIRTHED the pinned document (@2). A replay of the same
    #: delegation returns the same ``document_id`` with ``False`` — the birth already
    #: happened, and nothing is created twice.
    document_created: bool = False
    #: ``True`` when this call reopened a closed leg (the mis-exit recovery path).
    reopened: bool = False


class _LegRefused(ValueError):
    """One typed refusal, raised by the shared resolution and rendered by both entry points."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _ResolvedDelegation:
    turn: TurnIdentity
    parent_execution_id: UUID
    leg_id: str
    document_id: str | None
    document_version_guard: int | None
    brand_kit_id: str | None
    brand_kit_version: int | None
    existing_leg: dict[str, Any] | None
    bundle_bytes: bytes
    #: The validated CLOSED leg a re-delegation names (§2.2 mis-exit reopen); ``None`` on the
    #: fresh-delegation path.
    reopen_leg: dict[str, Any] | None = None
    #: @2's document birth: the title to mint under ``document_id`` when this open must create
    #: its own document. ``None`` on every path that pins (or reopens onto) an existing one.
    birth_title: str | None = None
    #: What kind of document that birth mints (``"web"`` | ``"scene"``) — set together with
    #: ``birth_title``, which stays the single "this open births" flag.
    birth_doc_kind: str | None = None
    #: @3's ad geometry: ``(format_key, width_px, height_px)`` on a scene birth, ``None`` on a
    #: web birth. The preset lookup happens once, in ``_resolve``, so the minter is handed
    #: resolved pixels rather than a key it would have to interpret.
    birth_format: tuple[str, int, int] | None = None
    #: The §2.3 payload behind ``bundle_bytes``, kept so the birth path can re-freeze the bundle
    #: with the brand pin the DOCUMENT was actually born with (which does not exist until the
    #: create runs, inside ``invoke``).
    bundle_payload: dict[str, JsonValue] | None = None


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _require_bundle_within_cap(bundle_bytes: bytes) -> None:
    if len(bundle_bytes) > DESIGN_DELEGATION_BUNDLE_MAX_BYTES:
        raise _LegRefused(
            f"the delegation bundle is {len(bundle_bytes)} bytes; the hard cap is "
            f"{DESIGN_DELEGATION_BUNDLE_MAX_BYTES} (PD-part3 §2.3 — refs only, trim the "
            "brief or the claim set)",
            reason_code="design_bundle_too_large",
        )


#: The engine round-trip a web-document birth needs: ``(document_id, title, brand_kit_ref)`` in,
#: one empty ``WebDoc`` out. Injected so tests do not need the Rust helper binary; production
#: passes ``clue_api.design_tools.mint_empty_web_document``.
WebDocumentMinter = Callable[..., dict[str, Any]]


def _default_web_document_minter(
    *, document_id: str, title: str, brand_kit_ref: dict[str, Any] | None
) -> dict[str, Any]:
    # Imported lazily: `design_tools` reaches into `lumen_api`, and the leg tools are imported
    # by processes (the C6 authority audit, the trial surface) that must not pay for it.
    from clue_api.design_tools import mint_empty_web_document

    return mint_empty_web_document(
        document_id=document_id, title=title, brand_kit_ref=brand_kit_ref
    )


#: The engine round-trip a scene (ad) birth needs: an id, a title, the resolved format and its
#: pixels in, one empty single-artboard scene out. Injected like its web sibling; production
#: passes ``clue_api.design_tools.mint_empty_ad_document``.
SceneDocumentMinter = Callable[..., dict[str, Any]]


def _default_scene_document_minter(
    *,
    document_id: str,
    title: str,
    format_key: str,
    width: int,
    height: int,
    brand_kit_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    # Lazily imported for the same reason as the web minter: `design_tools` reaches into
    # `lumen_api`, and the leg tools are imported by processes that must not pay for it.
    from clue_api.design_tools import mint_empty_ad_document

    return mint_empty_ad_document(
        document_id=document_id,
        title=title,
        format_key=format_key,
        width=width,
        height=height,
        brand_kit_ref=brand_kit_ref,
    )


def _resolve_ad_format(inputs: OpenDesignLegInput) -> tuple[str, int, int]:
    """The @3 format contract for a scene birth: one ratified size, stated loudly.

    Every violation is a refusal rather than a repair, because each one is a *malformed
    belief* the agent should see: no format at all would make the tool guess an ad's size;
    a preset carrying dimensions means the agent believes it can override pixels it cannot;
    ``custom`` without them names no size to build.
    """

    from clue_api.design_tools import AD_FORMAT_PRESETS

    presets = ", ".join(f"{key} ({w}x{h})" for key, (w, h) in sorted(AD_FORMAT_PRESETS.items()))
    if inputs.ad_format is None:
        raise _LegRefused(
            "an ad has a size, and this delegation names none: pass ad_format — one of "
            f"{presets} — or ad_format='custom' with ad_width and ad_height in px",
            reason_code="design_leg_ad_format_required",
        )
    if inputs.ad_format == "custom":
        if inputs.ad_width is None or inputs.ad_height is None:
            raise _LegRefused(
                "ad_format='custom' names no size by itself; pass BOTH ad_width and "
                f"ad_height in px, or use a preset ({presets})",
                reason_code="design_leg_ad_format_invalid",
            )
        return "custom", inputs.ad_width, inputs.ad_height
    if inputs.ad_width is not None or inputs.ad_height is not None:
        raise _LegRefused(
            f"the ad_format preset '{inputs.ad_format}' carries its own dimensions, so "
            "ad_width/ad_height cannot be supplied with it; drop them, or pass "
            "ad_format='custom' with both to choose the size yourself",
            reason_code="design_leg_ad_format_invalid",
        )
    width, height = AD_FORMAT_PRESETS[inputs.ad_format]
    return inputs.ad_format, width, height


def _refuse_ad_format_on_web(inputs: OpenDesignLegInput) -> None:
    """No cross-kind leakage: a website has no ad format (@3)."""

    if inputs.ad_format is None and inputs.ad_width is None and inputs.ad_height is None:
        return
    raise _LegRefused(
        "ad_format/ad_width/ad_height describe an ad, and this delegation is creating a "
        "website (doc_kind='web'); drop them, or pass doc_kind='scene' to make an ad",
        reason_code="design_leg_ad_format_invalid",
    )


class OpenDesignLegTool(Tool):
    name = "open_design_leg"
    version = "3"
    model_description = (
        "Hand this conversation to the design deepagent — the only way to get a website (or any "
        "design artifact) made. Use it the moment the user asks for a landing page, microsite, "
        "or page to be built or changed. For a NEW website pass doc_kind='web' and no "
        "document_id: an empty web document is created and the leg is pinned to it, so the "
        "artifact appears in the project's gallery immediately. Pass title as the name the user "
        'would recognise ("Insight Health landing page"); omitted, it is taken from the brief. '
        "Put the user's actual ask in brief — what the page is for, who it is for, what it must "
        "say — because Design sees the brief, not this conversation. To keep working on an "
        "EXISTING artifact pass its document_id instead (doc_kind is then ignored). "
        "For a NEW ad pass doc_kind='scene', no document_id, and ad_format — one of square "
        "(1200x1200), portrait (1080x1350), story (1080x1920), landscape (1200x628), or custom "
        "with ad_width/ad_height in px. Infer the format from what the user asked for and STATE "
        "your choice in your reply (they can correct it); do not block on a confirmation. "
        "To resume a design session you closed by "
        "mistake, pass reopen_leg_id — a reopen ignores every other field. While the leg is "
        "open, every user message on this thread goes directly to Design — you will not see the "
        "thread again until the leg closes. Opening a leg spends nothing and runs no design "
        "turn: the user's NEXT message is what starts generation, and generating a page takes "
        "minutes, not seconds. Tell the user the design session is open and end your turn."
    )
    input_model: ClassVar[type[ToolInput]] = OpenDesignLegInput
    output_model: ClassVar[type[ToolOutput]] = OpenDesignLegOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one design leg per delegating turn (leg id derived from the turn), and one born "
            "document per leg (document id derived from the leg) — both in one transaction"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "document_id",
            "doc_kind",
            "ad_format",
            "ad_width",
            "ad_height",
            "expected_document_version",
            "brand_kit_id",
            "brand_kit_version",
        )
    )
    #: The leg is anchored to one project (through its thread); the C5 step pins that project so
    #: a replayed delegation is judged against the same project revision it was opened under. The
    #: design-side pins (document CAS guard, brand-kit version) are validated by the tool itself
    #: against durable design rows — they have no platform pin kind, and inventing one here would
    #: fork the design substrate's own versioning.
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
        enabled: bool = True,
        web_document_minter: WebDocumentMinter | None = None,
        scene_document_minter: SceneDocumentMinter | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage
        # The deployment thread-wedge guard (adversarial-review fix): on a worker without the
        # design runtime, an opened leg is a thread NOTHING can serve — the routing rule is
        # unconditional, the lane is the fail-loud stub, finish_design_leg has no design turns
        # to run on, and the reaper rides the same switch. So the tools stay REGISTERED (the
        # C6 audit is exact set equality) but refuse before any durable write, exactly like
        # the sibling design_* set's `design_runtime_not_configured`.
        self._enabled = enabled
        self._mint_web_document = web_document_minter or _default_web_document_minter
        self._mint_scene_document = scene_document_minter or _default_scene_document_minter

    def _require_runtime(self) -> None:
        """The thread-wedge guard: refuse BEFORE any database touch on a design-disabled
        deployment — a leg opened where no runtime is composed is a thread nothing can
        serve (unconditional routing, fail-loud lane, no reaper on the same switch)."""

        if not self._enabled:
            raise _LegRefused(
                "the design runtime is not composed on this deployment "
                "(CLUE_DESIGN_RUNTIME_ENABLED is off), so a design leg opened here could "
                "never run a design turn; delegation is refused rather than wedging the "
                "thread",
                reason_code="design_leg_runtime_not_configured",
            )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenDesignLegInput)
        try:
            # Before the connection opens: a design-disabled deployment refuses without
            # touching the database at all (the thread-wedge guard).
            self._require_runtime()
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _LegRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """Opening a leg is free — the spend happens inside governed design turns, later."""

        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenDesignLegInput)
        self._require_runtime()
        reopened = False
        document_created = False
        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            if resolved.reopen_leg is not None:
                await design_legs.reopen_leg(
                    conn,
                    workspace_id=ctx.workspace_id,
                    leg_id=resolved.leg_id,
                )
                leg = await design_legs.get_leg(
                    conn, workspace_id=ctx.workspace_id, leg_id=resolved.leg_id
                )
                created = False
                reopened = True
                await _emit_leg_lifecycle(
                    conn,
                    workspace_id=ctx.workspace_id,
                    turn=resolved.turn,
                    event_type=TurnEventType.LEG_REOPENED,
                    leg_id=resolved.leg_id,
                )
            elif resolved.existing_leg is not None:
                leg = resolved.existing_leg
                created = False
            else:
                brand_kit_id = resolved.brand_kit_id
                brand_kit_version = resolved.brand_kit_version
                bundle_bytes = resolved.bundle_bytes
                if resolved.birth_title is not None:
                    assert resolved.document_id is not None  # set together in _resolve
                    if resolved.birth_doc_kind == "scene":
                        assert resolved.birth_format is not None  # @3: set with the kind
                        format_key, width, height = resolved.birth_format
                        brand_kit_id, brand_kit_version = await self._birth_scene_document(
                            conn,
                            workspace_id=ctx.workspace_id,
                            document_id=resolved.document_id,
                            title=resolved.birth_title,
                            format_key=format_key,
                            width=width,
                            height=height,
                            requested_brand_kit_id=resolved.brand_kit_id,
                            requested_brand_kit_version=resolved.brand_kit_version,
                        )
                    else:
                        brand_kit_id, brand_kit_version = await self._birth_web_document(
                            conn,
                            workspace_id=ctx.workspace_id,
                            document_id=resolved.document_id,
                            title=resolved.birth_title,
                            requested_brand_kit_id=resolved.brand_kit_id,
                            requested_brand_kit_version=resolved.brand_kit_version,
                        )
                    document_created = True
                    # The bundle records what was actually born, not what was asked for: the
                    # kit is chosen BY the creation contract, so it cannot be known until now.
                    assert resolved.bundle_payload is not None
                    bundle_bytes = _canonical_json(
                        {
                            **resolved.bundle_payload,
                            "brand_kit": _brand_kit_ref(brand_kit_id, brand_kit_version),
                        }
                    )
                    _require_bundle_within_cap(bundle_bytes)
                bundle_ref = await self._artifacts().persist_body(
                    workspace_id=ctx.workspace_id,
                    data=bundle_bytes,
                    media_type=DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE,
                    project_bindings=((resolved.turn.project_id, "design_delegation_context"),),
                )
                leg = await design_legs.open_leg(
                    conn,
                    workspace_id=ctx.workspace_id,
                    thread_id=resolved.turn.thread_id,
                    parent_execution_id=resolved.parent_execution_id,
                    opened_by_turn_id=resolved.turn.turn_id,
                    bundle_artifact_ref=bundle_ref.artifact_key,
                    document_id=resolved.document_id,
                    document_version_guard=resolved.document_version_guard,
                    brand_kit_id=brand_kit_id,
                    brand_kit_version=brand_kit_version,
                    leg_id=resolved.leg_id,
                )
                created = True
                await _emit_leg_lifecycle(
                    conn,
                    workspace_id=ctx.workspace_id,
                    turn=resolved.turn,
                    event_type=TurnEventType.LEG_OPENED,
                    leg_id=resolved.leg_id,
                )
        bundle_sha = (
            (await self._bundle_sha(leg["bundle_artifact_ref"], ctx.workspace_id))
            if leg.get("bundle_artifact_ref")
            else ""
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": leg["id"],
                "leg_ref": design_leg_ref(leg["id"]),
                "thread_id": leg["thread_id"],
                "bundle_artifact_key": leg.get("bundle_artifact_ref") or "",
                "bundle_sha256": bundle_sha,
                "document_id": leg.get("document_id"),
                "document_version_guard": leg.get("document_version_guard"),
                "brand_kit_id": leg.get("brand_kit_id"),
                "brand_kit_version": leg.get("brand_kit_version"),
                "created": created,
                "document_created": document_created,
                "reopened": reopened,
            },
        )

    async def _birth_web_document(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        document_id: str,
        title: str,
        requested_brand_kit_id: str | None,
        requested_brand_kit_version: int | None,
    ) -> tuple[str | None, int | None]:
        """Create the leg's empty web document and return the pin READ BACK off the stored row.

        Two seams, in the order the design API's own ``POST /documents`` uses them: the engine
        mints the ``WebDoc`` (it is the only author of that shape), then the DAL's
        ``create_document`` performs the governed write — and that DAL call is the whole point,
        because it carries the frozen creation contract that stamps the workspace's latest
        APPROVED brand kit onto a new web document. Both run inside the CALLER's transaction,
        the same one that inserts the leg, so a failed delegation leaves no orphan document.

        The returned pin is read off the stored row, never re-derived: whatever birth decided
        is what the leg carries for the rest of the conversation (a kit approved later cannot
        move it). An explicit agent-supplied pin is honoured by handing it to the engine as the
        document's own ``theme.brand_kit``, which the creation contract treats as authoritative
        — so even then the pin is a read-back of the durable truth, not a parallel decision.
        """

        requested_ref = (
            None
            if requested_brand_kit_id is None or requested_brand_kit_version is None
            else {"id": requested_brand_kit_id, "version": requested_brand_kit_version}
        )
        # The engine round-trip is a blocking subprocess call; keep it off the event loop.
        web_doc = await asyncio.to_thread(
            self._mint_web_document,
            document_id=document_id,
            title=title,
            brand_kit_ref=requested_ref,
        )
        document = await create_document(
            conn, workspace_id=workspace_id, scene=web_doc, doc_kind="web"
        )
        stamped_id = document.get("effective_brand_kit_id")
        stamped_version = document.get("effective_brand_kit_version")
        if stamped_id is None or stamped_version is None:
            # No approved kit in this workspace (or a multi-brand workspace, which the contract
            # fails closed): an all-null theme and a leg with NO pin — un-branded, honestly.
            return None, None
        return str(stamped_id), int(stamped_version)

    async def _birth_scene_document(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        document_id: str,
        title: str,
        format_key: str,
        width: int,
        height: int,
        requested_brand_kit_id: str | None,
        requested_brand_kit_version: int | None,
    ) -> tuple[str | None, int | None]:
        """Create the leg's empty ad document and return the pin READ BACK off the stored row.

        The scene sibling of :meth:`_birth_web_document`, using the same two seams in the same
        order and for the same reasons: the engine mints the scene (it is the only author of
        that shape — here one ``new_scene`` plus one ``add_page`` at the resolved format), then
        the DAL's ``create_document`` performs the governed write carrying the frozen creation
        contract, which stamps the workspace's latest APPROVED brand kit onto a new scene
        document. Both run inside the CALLER's transaction — the one that inserts the leg — so
        a failed delegation leaves no orphan ad.

        The dimensions arrive already resolved (``_resolve_ad_format`` did the preset lookup),
        so this method never interprets a format key; it only threads it through as the page's
        name/artifact type. The returned pin is read off the stored row, never re-derived.
        """

        requested_ref = (
            None
            if requested_brand_kit_id is None or requested_brand_kit_version is None
            else {"id": requested_brand_kit_id, "version": requested_brand_kit_version}
        )
        # The engine round-trip is a blocking subprocess call; keep it off the event loop.
        scene = await asyncio.to_thread(
            self._mint_scene_document,
            document_id=document_id,
            title=title,
            format_key=format_key,
            width=width,
            height=height,
            brand_kit_ref=requested_ref,
        )
        document = await create_document(
            conn, workspace_id=workspace_id, scene=scene, doc_kind="scene"
        )
        stamped_id = document.get("effective_brand_kit_id")
        stamped_version = document.get("effective_brand_kit_version")
        if stamped_id is None or stamped_version is None:
            # No approved kit in this workspace (or the fail-closed multi-brand case): an
            # un-branded ad and a leg with NO pin — honestly, and generation still works.
            return None, None
        return str(stamped_id), int(stamped_version)

    def _artifacts(self) -> DurableAgentArtifactStore:
        if self._storage is None:  # pragma: no cover - guarded by _resolve
            raise RuntimeError("design leg storage is not configured")
        return DurableAgentArtifactStore(
            storage=self._storage,
            conn_factory=self._conn_factory,
        )

    async def _bundle_sha(self, artifact_key: str, workspace_id: str) -> str:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT content_sha256 FROM artifact "
                        "WHERE storage_key = :key AND workspace_id = :ws"
                    ),
                    {"key": artifact_key, "ws": workspace_id},
                )
            ).first()
        return "" if row is None else str(row[0])

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: OpenDesignLegInput,
        ctx: ToolContext,
    ) -> _ResolvedDelegation:
        """Every check the delegation depends on, run identically by preconditions and invoke."""

        self._require_runtime()
        if self._storage is None:
            raise _LegRefused(
                "this deployment has no artifact storage, so no delegation bundle can be "
                "frozen; the design leg cannot open",
                reason_code="design_leg_storage_not_configured",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _LegRefused(str(exc), reason_code="design_leg_turn_ref_malformed") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            raise _LegRefused(
                "no such turn in this workspace",
                reason_code="design_leg_turn_not_found",
            )
        execution_row = (
            await conn.execute(
                text("SELECT execution_id FROM agent_turn WHERE id = :turn AND workspace_id = :ws"),
                {"turn": turn.turn_id, "ws": ctx.workspace_id},
            )
        ).first()
        if execution_row is None:
            raise _LegRefused(
                "the presenting turn has no execution row yet, so the leg has no platform "
                "parent to attach to",
                reason_code="design_leg_turn_execution_missing",
            )
        parent_execution_id = UUID(str(execution_row[0]))

        if inputs.reopen_leg_id is not None:
            return await self._resolve_reopen(
                conn,
                inputs,
                ctx,
                turn=turn,
                parent_execution_id=parent_execution_id,
            )

        leg_id = derive_design_leg_id(workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        try:
            existing = await design_legs.get_leg(conn, workspace_id=ctx.workspace_id, leg_id=leg_id)
        except DesignNotFoundError:
            existing = None
        if existing is not None:
            if existing["state"] == "closed":
                # Practically unreachable (head-of-abm does not run while its own leg is open,
                # and a closed leg means a *later* turn re-delegates) — refused rather than
                # silently reopened; the mis-exit reopen names the leg via ``reopen_leg_id``.
                raise _LegRefused(
                    "this turn's design leg was already closed; a re-delegation reopens it by "
                    "naming it in reopen_leg_id, not by opening it again",
                    reason_code="design_leg_replay_closed",
                )
            return _ResolvedDelegation(
                turn=turn,
                parent_execution_id=parent_execution_id,
                leg_id=leg_id,
                document_id=existing.get("document_id"),
                document_version_guard=existing.get("document_version_guard"),
                brand_kit_id=existing.get("brand_kit_id"),
                brand_kit_version=existing.get("brand_kit_version"),
                existing_leg=existing,
                bundle_bytes=b"",
            )

        open_leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if open_leg is not None:
            raise _LegRefused(
                "this thread already has an open design leg; finish it (or let the user keep "
                "talking to Design) before delegating again",
                reason_code="design_leg_already_open",
            )

        document_version_guard: int | None = None
        document_id = inputs.document_id
        birth_title: str | None = None
        birth_doc_kind: str | None = None
        birth_format: tuple[str, int, int] | None = None
        if inputs.document_id is not None:
            try:
                document = await get_document(
                    conn, workspace_id=ctx.workspace_id, document_id=inputs.document_id
                )
            except DesignNotFoundError as exc:
                raise _LegRefused(
                    "no such design document in this workspace",
                    reason_code="design_document_not_found",
                ) from exc
            current = int(document.get("current_version") or 0)
            if (
                inputs.expected_document_version is not None
                and inputs.expected_document_version != current
            ):
                raise _LegRefused(
                    f"the document is at version {current}, not "
                    f"{inputs.expected_document_version}; re-read it before delegating",
                    reason_code="design_document_pin_stale",
                )
            document_version_guard = current
        elif inputs.expected_document_version is not None:
            raise _LegRefused(
                "an expected document version without a document id pins nothing",
                reason_code="design_document_pin_incomplete",
            )
        else:
            # @2's document birth (plan §4.1), widened to ads by @3 (genad ruling 1). No
            # document to pin ⇒ the delegation must say what to make — and, for an ad, at
            # what size.
            if inputs.doc_kind is None:
                raise _LegRefused(
                    "this delegation names no document, so it must say what to create: pass "
                    "doc_kind='web' to start a new website, doc_kind='scene' (with an "
                    "ad_format) to start a new ad, or document_id to work on an existing "
                    "artifact",
                    reason_code="design_leg_doc_kind_required",
                )
            if inputs.doc_kind == "scene":
                birth_format = _resolve_ad_format(inputs)
            else:
                _refuse_ad_format_on_web(inputs)
            birth_doc_kind = inputs.doc_kind
            document_id = derive_leg_document_id(leg_id=leg_id)
            birth_title = _document_title(title=inputs.title, brief=inputs.brief)
            # A newborn document is at version 0, and that is exactly what the leg guards.
            document_version_guard = 0

        if (inputs.brand_kit_id is None) != (inputs.brand_kit_version is None):
            raise _LegRefused(
                "a brand pin is (brand_kit_id, version) together or absent entirely",
                reason_code="brand_kit_pin_incomplete",
            )
        if inputs.brand_kit_id is not None:
            kit = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM design_brand_kit "
                        "WHERE brand_kit_id = :kit AND version = :version "
                        "AND workspace_id = :ws"
                    ),
                    {
                        "kit": inputs.brand_kit_id,
                        "version": inputs.brand_kit_version,
                        "ws": ctx.workspace_id,
                    },
                )
            ).first()
            if kit is None:
                raise _LegRefused(
                    "no such brand kit version in this workspace — the pin is fail-closed "
                    "(PD-part3 D5), so a missing kit is a refusal, never a default fallback",
                    reason_code="brand_kit_pin_not_found",
                )

        bundle_payload = _bundle_payload(
            inputs=inputs,
            ctx_workspace_id=ctx.workspace_id,
            turn=turn,
            leg_id=leg_id,
            document_id=document_id,
            document_version_guard=document_version_guard,
        )
        bundle_bytes = _canonical_json(bundle_payload)
        _require_bundle_within_cap(bundle_bytes)
        return _ResolvedDelegation(
            turn=turn,
            parent_execution_id=parent_execution_id,
            leg_id=leg_id,
            document_id=document_id,
            document_version_guard=document_version_guard,
            brand_kit_id=inputs.brand_kit_id,
            brand_kit_version=inputs.brand_kit_version,
            existing_leg=None,
            bundle_bytes=bundle_bytes,
            birth_title=birth_title,
            birth_doc_kind=birth_doc_kind,
            birth_format=birth_format,
            bundle_payload=bundle_payload,
        )

    async def _resolve_reopen(
        self,
        conn: AsyncConnection,
        inputs: OpenDesignLegInput,
        ctx: ToolContext,
        *,
        turn: TurnIdentity,
        parent_execution_id: UUID,
    ) -> _ResolvedDelegation:
        """§2.2's mis-exit recovery: validate the CLOSED leg this re-delegation names.

        A reopen is a resumption, not a fresh delegation: the original bundle, pins, history
        and parent execution all survive, so the pin/bundle fields of the input are ignored
        and nothing new is frozen. The exit journal record survives by construction (the DAL
        never deletes journal rows).
        """

        assert inputs.reopen_leg_id is not None
        try:
            leg = await design_legs.get_leg(
                conn, workspace_id=ctx.workspace_id, leg_id=inputs.reopen_leg_id
            )
        except DesignNotFoundError as exc:
            raise _LegRefused(
                "no such design leg in this workspace",
                reason_code="design_leg_reopen_not_found",
            ) from exc
        if leg["thread_id"] != turn.thread_id:
            raise _LegRefused(
                "that design leg belongs to another thread; a re-delegation may only reopen "
                "a leg of its own conversation",
                reason_code="design_leg_reopen_wrong_thread",
            )
        if leg["state"] != "closed":
            raise _LegRefused(
                "that design leg is not closed — the user can simply keep talking to Design",
                reason_code="design_leg_reopen_not_closed",
            )
        open_leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if open_leg is not None:
            raise _LegRefused(
                "this thread already has an open design leg; finish it before reopening another",
                reason_code="design_leg_already_open",
            )
        return _ResolvedDelegation(
            turn=turn,
            parent_execution_id=parent_execution_id,
            leg_id=str(leg["id"]),
            document_id=leg.get("document_id"),
            document_version_guard=leg.get("document_version_guard"),
            brand_kit_id=leg.get("brand_kit_id"),
            brand_kit_version=leg.get("brand_kit_version"),
            existing_leg=None,
            bundle_bytes=b"",
            reopen_leg=leg,
        )


def _brand_kit_ref(brand_kit_id: str | None, brand_kit_version: int | None) -> JsonValue:
    """The §2.3 bundle's brand stamp — both halves or nothing (the D5 fail-closed pin)."""

    if brand_kit_id is None or brand_kit_version is None:
        return None
    return {"brand_kit_id": brand_kit_id, "version": brand_kit_version}


def _bundle_payload(
    *,
    inputs: OpenDesignLegInput,
    ctx_workspace_id: str,
    turn: TurnIdentity,
    leg_id: str,
    document_id: str | None,
    document_version_guard: int | None,
) -> dict[str, JsonValue]:
    """The §2.3 delegation-bundle schema v1 — refs and stamps, never claim values.

    ``document_id`` is the RESOLVED target, which on @2's birth path is the document this
    delegation is about to create (identical to ``inputs.document_id`` on every other path,
    so the frozen bundle bytes are byte-stable for legs that pin an existing document).
    """

    return {
        "schema_version": "1",
        "bundle_kind": "design_delegation",
        "workspace_id": ctx_workspace_id,
        "project_id": turn.project_id,
        "thread_id": turn.thread_id,
        "leg_id": leg_id,
        "opened_by_turn_id": str(turn.turn_id),
        "brief": inputs.brief,
        "brand_kit": _brand_kit_ref(inputs.brand_kit_id, inputs.brand_kit_version),
        "target_document": (
            None
            if document_id is None
            else {
                "document_id": document_id,
                "version_guard": document_version_guard,
            }
        ),
        "claim_refs": [ref.model_dump(mode="json") for ref in inputs.claim_refs],
        "binding_set_ref": inputs.binding_set_ref,
        "template_revision_ref": inputs.template_revision_ref,
        "turn_contract": {
            "proposal_flow": "propose_accept_reject",
            "clarification_rounds": 1,
        },
    }


class FinishDesignLegInput(ToolInput):
    """The design orchestrator's proposed exit; the engine derives and validates everything."""

    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    #: The §2.2 closed exit vocabulary — no other reason exists.
    reason: Literal["locked", "out_of_scope", "abandoned"]
    #: The leg summary head-of-abm resumes with — what was made (or why the leg ended),
    #: in the user's terms. This is the ONE design artifact the strategy conversation's
    #: history gains; transcripts stay inside the leg.
    summary: str = Field(min_length=1, max_length=4_000)


class FinishDesignLegOutput(ToolOutput):
    leg_id: str
    leg_ref: str
    thread_id: str
    reason: str
    state: str
    journal_id: str
    summary_artifact_key: str
    summary_message_id: str
    redelivered_turn_id: str | None
    created: bool


@dataclass(frozen=True, slots=True)
class _ResolvedExit:
    turn: TurnIdentity
    leg: dict[str, Any] | None
    submission: Any
    #: The already-journaled exit this turn decided (replay); ``None`` on the fresh path.
    replay: dict[str, Any] | None


class FinishDesignLegTool(Tool):
    """The leg-level exit (PD-part3 §2.2) — the ONLY path to ``closed``.

    Reconciliation with the design harness's authorities, verbatim from the spec:
    ``final.json`` / ``finalize_run`` / ``request_clarification`` remain the TURN-level
    outcome contract and are untouched by this tool; a turn can finalize (proposal ready)
    while the leg stays open — that is the normal iteration loop. This tool is what ends the
    *leg*: it validates that the deciding turn is the leg's own, persists the summary as the
    §2.4 hand-back head-of-abm's history gains, journals the decision append-only, flips the
    leg, and — for ``out_of_scope`` — re-submits the **user's own captured message** (never
    model-authored text) as a fresh head-of-abm submission on the same thread, so the user
    never repeats themselves.
    """

    name = "finish_design_leg"
    version = "1"
    model_description = (
        "End the design leg and hand the thread back to the strategy agent. reason=locked "
        "when the user accepted the design; out_of_scope when their last message is not a "
        "design ask (it is re-delivered to the strategy agent verbatim — never rewrite it); "
        "abandoned when the user walked away. The summary is what the strategy agent resumes "
        "with — state what was made or why the leg ended, in the user's terms. Turn-level "
        "finalization (final.json) is unchanged: finishing a turn does not finish the leg; "
        "only this tool does."
    )
    input_model: ClassVar[type[ToolInput]] = FinishDesignLegInput
    output_model: ClassVar[type[ToolOutput]] = FinishDesignLegOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one journaled exit per deciding design turn (replay returns the recorded exit; "
            "a deliberately reopened leg is never re-closed by a stale retry)"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("reason",))

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
        enabled: bool = True,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage
        # The deployment thread-wedge guard (adversarial-review fix): on a worker without the
        # design runtime, an opened leg is a thread NOTHING can serve — the routing rule is
        # unconditional, the lane is the fail-loud stub, finish_design_leg has no design turns
        # to run on, and the reaper rides the same switch. So the tools stay REGISTERED (the
        # C6 audit is exact set equality) but refuse before any durable write, exactly like
        # the sibling design_* set's `design_runtime_not_configured`.
        self._enabled = enabled

    def _require_runtime(self) -> None:
        if not self._enabled:
            raise _LegRefused(
                "the design runtime is not composed on this deployment "
                "(CLUE_DESIGN_RUNTIME_ENABLED is off), so no design leg can close here",
                reason_code="design_leg_runtime_not_configured",
            )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, FinishDesignLegInput)
        try:
            # Before the connection opens: a design-disabled deployment refuses without
            # touching the database at all (the thread-wedge guard).
            self._require_runtime()
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _LegRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """Ending a leg spends nothing; it records a decision and re-delivers at most one
        already-captured message."""

        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, FinishDesignLegInput)
        self._require_runtime()
        from clue_api.agent_turn_submission import (
            dispatch_next_thread_turn,
            insert_submission,
            submission_context_refs,
            turn_id_for_submission,
        )
        from clue_api.agent_turn_wiring import DbAgentHistoryStore
        from clue_api.design_leg_wiring import design_leg_run_id

        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            if resolved.replay is not None:
                return self._replayed(resolved.replay)
            leg = resolved.leg
            assert leg is not None  # the fresh path always carries the open leg
            leg_id = str(leg["id"])
            turn = resolved.turn
            submission = resolved.submission

            summary_ref = await self._artifacts().persist_body(
                workspace_id=ctx.workspace_id,
                data=inputs.summary.encode(),
                media_type="text/plain",
                project_bindings=((turn.project_id, "design_leg_context"),),
            )
            summary_message_id = uuid5(turn.turn_id, "leg_summary")
            await DbAgentHistoryStore(conn_factory=self._conn_factory).append(
                message_id=summary_message_id,
                turn_id=turn.turn_id,
                workspace_id=ctx.workspace_id,
                thread_id=turn.thread_id,
                role="assistant",
                body_ref=summary_ref,
            )
            document_version: int | None = None
            if leg.get("document_id") is not None:
                try:
                    document = await get_document(
                        conn,
                        workspace_id=ctx.workspace_id,
                        document_id=str(leg["document_id"]),
                    )
                    document_version = int(document.get("current_version") or 0)
                except DesignNotFoundError:
                    document_version = None

            redelivered_turn_id: str | None = None
            pending_ref: str | None = None
            if inputs.reason == "out_of_scope":
                # The user's own captured bytes, re-submitted under a derived identity so a
                # retried close converges on ONE redelivered turn.
                redelivery_key = f"design-leg-redelivery:{leg_id}:{turn.turn_id}"
                redelivered = turn_id_for_submission(
                    workspace_id=ctx.workspace_id,
                    thread_id=turn.thread_id,
                    idempotency_key=redelivery_key,
                )
                context_refs = await submission_context_refs(
                    conn,
                    workspace_id=ctx.workspace_id,
                    turn_id=turn.turn_id,
                )
                await insert_submission(
                    conn,
                    turn_id=redelivered,
                    workspace_id=ctx.workspace_id,
                    project_id=submission.project_id,
                    thread_id=turn.thread_id,
                    submitted_by_user_id=submission.submitted_by_user_id,
                    submitted_via_membership_id=submission.submitted_via_membership_id,
                    onboarding_input_id=submission.onboarding_input_id,
                    message_artifact_key=submission.message_artifact_key,
                    message_sha256=submission.message_sha256,
                    idempotency_key=redelivery_key,
                    context_refs=context_refs,
                )
                redelivered_turn_id = str(redelivered)
                pending_ref = submission.message_artifact_key

            summary_refs: dict[str, JsonValue] = {
                "closing_turn_id": str(turn.turn_id),
                "summary_artifact_key": summary_ref.artifact_key,
                "summary_sha256": summary_ref.sha256,
                "summary_message_id": str(summary_message_id),
                "document_id": leg.get("document_id"),
                "document_version": document_version,
                "redelivered_turn_id": redelivered_turn_id,
            }
            journal_id = await design_legs.close_leg(
                conn,
                workspace_id=ctx.workspace_id,
                leg_id=leg_id,
                reason=inputs.reason,
                summary_refs=summary_refs,
                pending_user_message_ref=pending_ref,
                decided_by_run_id=design_leg_run_id(turn.turn_id),
            )
            await _emit_leg_lifecycle(
                conn,
                workspace_id=ctx.workspace_id,
                turn=turn,
                event_type=TurnEventType.LEG_CLOSED,
                leg_id=leg_id,
                reason=inputs.reason,
            )
            if redelivered_turn_id is not None:
                # The leg is closed in this transaction, so the redelivered turn routes to
                # head-of-abm. Offering is a no-op while this thread's own task is in flight
                # (the worker dispatches again after it finishes) — safe from either caller.
                await dispatch_next_thread_turn(
                    conn,
                    workspace_id=ctx.workspace_id,
                    thread_id=turn.thread_id,
                )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": leg_id,
                "leg_ref": design_leg_ref(leg_id),
                "thread_id": turn.thread_id,
                "reason": inputs.reason,
                "state": "closed",
                "journal_id": journal_id,
                "summary_artifact_key": summary_ref.artifact_key,
                "summary_message_id": str(summary_message_id),
                "redelivered_turn_id": redelivered_turn_id,
                "created": True,
            },
        )

    def _replayed(self, journal: dict[str, Any]) -> ToolResult:
        refs = journal["summary_refs"]
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": str(journal["leg_id"]),
                "leg_ref": design_leg_ref(str(journal["leg_id"])),
                "thread_id": str(journal["thread_id"]),
                "reason": str(journal["reason"]),
                "state": "closed",
                "journal_id": str(journal["id"]),
                "summary_artifact_key": str(refs.get("summary_artifact_key") or ""),
                "summary_message_id": str(refs.get("summary_message_id") or ""),
                "redelivered_turn_id": refs.get("redelivered_turn_id"),
                "created": False,
            },
        )

    def _artifacts(self) -> DurableAgentArtifactStore:
        if self._storage is None:  # pragma: no cover - guarded by _resolve
            raise RuntimeError("design leg storage is not configured")
        return DurableAgentArtifactStore(
            storage=self._storage,
            conn_factory=self._conn_factory,
        )

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: FinishDesignLegInput,
        ctx: ToolContext,
    ) -> _ResolvedExit:
        """Every check the exit depends on, run identically by preconditions and invoke."""

        from clue_api.agent_turn_submission import get_submission

        self._require_runtime()
        if self._storage is None:
            raise _LegRefused(
                "this deployment has no artifact storage, so no leg summary can be "
                "persisted; the design leg cannot close",
                reason_code="design_leg_storage_not_configured",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _LegRefused(str(exc), reason_code="design_leg_turn_ref_malformed") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            raise _LegRefused(
                "no such turn in this workspace",
                reason_code="design_leg_turn_not_found",
            )
        # Replay first, and deliberately BEFORE the open-leg read: a stale retry of a close
        # whose leg was since deliberately reopened must replay the original decision, never
        # close the reopened leg a second time.
        journal = (
            (
                await conn.execute(
                    text(
                        "SELECT j.id, j.leg_id, j.reason, j.summary_refs, l.thread_id "
                        "FROM design_leg_exit_journal j "
                        "JOIN design_leg l ON l.id = j.leg_id "
                        "AND l.workspace_id = j.workspace_id "
                        "WHERE j.workspace_id = :ws "
                        "AND j.summary_refs->>'closing_turn_id' = :turn"
                    ),
                    {"ws": ctx.workspace_id, "turn": str(turn.turn_id)},
                )
            )
            .mappings()
            .one_or_none()
        )
        if journal is not None:
            refs = journal["summary_refs"]
            if isinstance(refs, (str, bytes)):
                refs = json.loads(refs)
            return _ResolvedExit(
                turn=turn,
                leg=None,
                submission=None,
                replay={
                    "id": journal["id"],
                    "leg_id": journal["leg_id"],
                    "reason": journal["reason"],
                    "thread_id": journal["thread_id"],
                    "summary_refs": refs,
                },
            )

        leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if leg is None:
            raise _LegRefused(
                "this thread has no open design leg to finish",
                reason_code="design_leg_not_open",
            )
        turn_row = (
            (
                await conn.execute(
                    text(
                        "SELECT role, parent_execution_id FROM agent_turn "
                        "WHERE id = :turn AND workspace_id = :ws"
                    ),
                    {"turn": turn.turn_id, "ws": ctx.workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            turn_row is None
            or turn_row["role"] != "design"
            or str(turn_row["parent_execution_id"]) != str(leg["parent_execution_id"])
        ):
            raise _LegRefused(
                "only the leg's own design turn may finish it — this turn is not a design "
                "turn of this leg",
                reason_code="design_leg_exit_wrong_turn",
            )
        submission = await get_submission(conn, workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        if submission is None:
            raise _LegRefused(
                "the deciding design turn has no durable submission, so there is no user "
                "message to carry back",
                reason_code="design_leg_exit_no_user_message",
            )
        return _ResolvedExit(turn=turn, leg=leg, submission=submission, replay=None)


def build_design_leg_tools(
    *,
    conn_factory: ConnFactory = transaction,
    storage: StorageBackend | None = None,
    enabled: bool = True,
    web_document_minter: WebDocumentMinter | None = None,
    scene_document_minter: SceneDocumentMinter | None = None,
) -> tuple[Tool, ...]:
    """The design-leg tool set, registered unconditionally (the C6 audit is exact set equality).

    ``enabled`` is the deployment's design-runtime switch (the thread-wedge guard): where
    the runtime is not composed both tools refuse ``design_leg_runtime_not_configured``
    before any durable write, and without a storage backend they refuse
    ``design_leg_storage_not_configured``. Present-but-refusing, the same posture as the
    sibling design write tools.
    """

    return (
        OpenDesignLegTool(
            conn_factory=conn_factory,
            storage=storage,
            enabled=enabled,
            web_document_minter=web_document_minter,
            scene_document_minter=scene_document_minter,
        ),
        FinishDesignLegTool(conn_factory=conn_factory, storage=storage, enabled=enabled),
    )
