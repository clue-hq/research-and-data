from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, StrictInt, model_validator
from clue_design.asset_context import AssetContextPatch


JsonObject = Dict[str, Any]


class ActorEnvelope(BaseModel):
    kind: str = "api"
    id: Optional[str] = None


class CreateDocumentRequest(BaseModel):
    document_id: Optional[str] = None
    title: str = "Untitled document"
    artifact_type: Optional[str] = None
    medium: Optional[Any] = None
    scene: Optional[JsonObject] = None
    brand_kit: Optional[JsonObject] = None
    # Website mode: "scene" (default, Rust engine scene) or "web" (WebDoc).
    doc_kind: str = "scene"
    # Web-only: the Brand Kit reference ({"id": str, "version": int}) the
    # helper compiles into the new WebDoc's theme. Stored verbatim; not
    # validated against the kits table in P0.
    brand_kit_ref: Optional[JsonObject] = None


class ReplaceSceneRequest(BaseModel):
    scene: JsonObject


class EditScopeEnvelope(BaseModel):
    mode: Literal["strict", "advisory"] = "strict"
    allowed: List[JsonObject] = Field(default_factory=list)


class ApplyOperationsRequest(BaseModel):
    operations: List[JsonObject] = Field(default_factory=list)
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    source: Literal["editor", "agent", "api", "system"] = "api"
    snapshot_reason: Optional[str] = None
    base_version: Optional[int] = None
    intent: Optional[str] = None
    checkpoint: Optional[str] = None
    scope: Optional[EditScopeEnvelope] = None


class ApplyStructuredEditRequest(BaseModel):
    edit: JsonObject
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    source: Literal["editor", "agent", "api", "system"] = "api"
    snapshot_reason: Optional[str] = None
    base_version: Optional[int] = None
    checkpoint: Optional[str] = None
    scope: Optional[EditScopeEnvelope] = None


class CreateSnapshotRequest(BaseModel):
    snapshot_id: Optional[str] = None
    reason: str = "manual"


class PreflightRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    persist_effective_brand: bool = True


class PreflightPreviewRequest(BaseModel):
    scene: JsonObject
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    # K1.6(b): after a clean preflight, ALSO bake every Stack container to
    # Free (build_freeze_layout) on the RESOLVED, server-relaid-out scene and
    # return the raw scene + operations in a `bake` block. The editor's
    # accept path uses this so frozen geometry can never derive from an
    # unresolved (skeleton-literal) client solve.
    freeze_layout: bool = False


class ExportPreviewRequest(BaseModel):
    scene: JsonObject
    format: Literal["svg", "png", "pdf", "figma_manifest"] = "svg"
    page_ids: List[str] = Field(default_factory=list)
    profile: Optional[JsonObject] = None


class ExportDocumentRequest(BaseModel):
    format: Literal["svg", "png", "pdf", "figma_manifest"] = "svg"
    page_ids: List[str] = Field(default_factory=list)
    profile_name: Optional[str] = None
    profile: Optional[JsonObject] = None
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    persist_effective_brand: bool = True
    persist_preflight: bool = True


class AgentTurnPreviewRequest(BaseModel):
    prompt: str
    scene: JsonObject
    document_id: Optional[str] = None
    active_page_id: Optional[str] = None
    # 2c selection chips: the node ids the human chipped as edit targets.
    # (The singular selected_node_id back-compat field was dropped after its
    # one-release window; legacy senders' extra key is ignored by pydantic.)
    target_node_ids: List[str] = Field(default_factory=list)
    # RC (reference-conditioned design): the library asset ids the human
    # attached to THIS turn as visual references. Per-turn context, not
    # document state (D1) — mirrors GenerateAssetRequest.reference_asset_ids.
    # run_agent_turn_preview resolves these into config.reference_assets BY
    # VALUE (the runtime never reads the API database). Empty → no references.
    reference_asset_ids: List[str] = Field(default_factory=list)
    diagnostics: List[JsonObject] = Field(default_factory=list)
    # 2e: the document's standing agent instructions, sent by the editor with
    # every turn and folded into the prompt context.
    agent_instructions: Optional[str] = None
    max_iterations: Optional[int] = None
    # Editor model picker: a runtime model id ("openai:<openrouter-id>" /
    # "anthropic:<id>"); None = the runtime's configured default.
    model: Optional[str] = None
    # Brief clarification (one-round-per-turn guard): the honest outcome of the
    # PREVIOUS turn on this document, echoed back by the editor. When it is
    # "clarification_requested", the harness withholds the request_clarification
    # tool this turn — the agent must design from the user's answer, never ask a
    # second round. None/absent → an ordinary turn (the tool is available).
    previous_turn_outcome: Optional[str] = None


class WebTurnTargetNote(BaseModel):
    """One annotation a human made in the editor (R-A2): the node they pointed at, the
    optional element INSIDE it, and their own words about it.

    ``path`` is the closed structural grammar of spec §3.1 — ``:nth-child(n)`` steps joined
    by `` > `` and nothing else — enforced here so a value that reached the brief could
    never widen into a selector. It is measured from the clone's rendered wrapper, which is
    what makes it resolvable against the artifact's stored HTML.

    The same pattern is written twice more and cannot be shared across the seam: the
    platform's acceptance gate (``clue_api.design_turn_targets._WEB_TARGET_PATH``) and this
    subsystem's resolver (``lumen_api.fragments.paths.PATH_RE``). Change one, change all
    three.

    ``note`` may be absent: the platform sends one entry per selected node whether or not
    the human wrote about it, and a note-less entry simply leaves that node with its
    ordinary TURN TARGET line.
    """

    target: str
    path: Optional[str] = Field(
        default=None, max_length=256, pattern=r"^(:nth-child\(\d+\)( > )?)+$"
    )
    note: Optional[str] = Field(default=None, max_length=2000)


class WebTurnRequest(BaseModel):
    """A website-mode agent turn against one exact stored WebDoc revision.

    ``base_version`` is mandatory because the async worker may run for minutes:
    the result must never replace human edits committed after the turn began.
    """

    prompt: str
    base_version: int
    model: Optional[str] = None
    # Scoped edit turns: the node ids the user selected in the editor. When
    # present, the turn is scoped to the enclosing section(s) of those nodes
    # (the orchestrator reacts to a "TURN TARGET" line appended to the brief).
    # Absent/None → an ordinary whole-page turn.
    target_node_ids: Optional[List[str]] = None
    # R-A2: what the human WROTE about those targets, one entry per submitted
    # reference in submission order (the order is part of what they said — they
    # number their own annotations "1.", "2.", …). Absent/None → a selection-only
    # scoped turn, whose brief is byte-identical to the pre-annotation one.
    target_notes: Optional[List[WebTurnTargetNote]] = None
    # P5 (D6): the target account this turn personalizes for. Unknown id → 404
    # before the run starts. Absent → the document row's own account_id (a
    # derived doc) is used when present, else an un-personalized turn.
    account_id: Optional[str] = None


class WebOperationsRequest(BaseModel):
    """A manual website-mode edit: a batch of typed WebOperations applied to the
    stored WebDoc through the checked-apply helper. `base_version` gates on the
    optimistic-concurrency contract the scene /operations endpoint uses; `intent`
    labels the resulting edit envelope."""

    operations: List[JsonObject] = Field(default_factory=list)
    base_version: Optional[int] = None
    intent: Optional[str] = None


class SiteWriteRequest(BaseModel):
    """A save of a whole Puck site document (Wave 2 Contract 2): the site JSON, the version it was
    edited from (required — a stale tab must never overwrite a newer save), and a history label."""

    site: JsonObject
    base_version: int
    intent: Optional[str] = None


class SiteHistoryRequest(BaseModel):
    """An undo, a redo or a restore of a Puck site, from the version the caller is looking at."""

    base_version: int


class CreateWebAccountRequest(BaseModel):
    """A personalization account (P5 D3). `account_id` is minted (`acc_…`) when
    absent; an explicit duplicate id is a 409. `data` is the string→string custom
    var map (each key becomes `account.<key>`); `notes` is agent-only context,
    never a substitution value. A provided `logo_asset_id` must resolve in the
    assets table (422 otherwise)."""

    account_id: Optional[str] = None
    name: str
    domain: Optional[str] = None
    logo_asset_id: Optional[str] = None
    data: Dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class UpdateWebAccountRequest(BaseModel):
    """Partial account update (P5 D3). Only the fields present in the request
    body are written; `data`, when present, replaces the whole map. Same
    logo_asset_id resolution check as create."""

    name: Optional[str] = None
    domain: Optional[str] = None
    logo_asset_id: Optional[str] = None
    data: Optional[Dict[str, str]] = None
    notes: Optional[str] = None


class PutCustomComponentSourceRequest(BaseModel):
    """Replace one component source tree using optimistic source versioning."""

    expected_version: StrictInt = Field(ge=0)
    files: Dict[str, str]
    actor: ActorEnvelope = Field(
        default_factory=lambda: ActorEnvelope(kind="human")
    )


class CompileCustomComponentRequest(BaseModel):
    """Compile only the exact durable source version named by the caller."""

    source_version: StrictInt = Field(ge=1)
    actor: ActorEnvelope = Field(
        default_factory=lambda: ActorEnvelope(kind="human")
    )


class SaveWebTemplateRequest(BaseModel):
    """Clone a web document into a reusable template (P5 D4). An omitted title
    defaults to ``"{source title} — template"``."""

    title: Optional[str] = None


class DeriveWebRequest(BaseModel):
    """Derive a personalized copy of a web document (P5 D4). `account_id` is
    OPTIONAL: absent → a plain marker-preserving copy with an EMPTY value map
    (default title ``"{source title} — copy"``); present → the account's value
    map is applied (default title ``"{source title} — {account name}"``). An
    unknown account is a 404; an engine rejection is a 422."""

    account_id: Optional[str] = None
    title: Optional[str] = None


class WebBatchRequest(BaseModel):
    """Bulk derive (+ optional publish) a template web document for a set of
    accounts (P5 D5). Chunked + resumable; per-account failures never kill the
    batch. Slugs are ``{slug_base or slugify(template title)}-{slugify(account
    name)}`` with collision suffixing (never a 409)."""

    account_ids: List[str] = Field(default_factory=list)
    publish: bool = True
    slug_base: Optional[str] = None
    #: CP2 (clone-fidelity F4.3, D-F5): this is an ABM run over a campaign template. It is sugar
    #: for ``slug_base="abm"`` — the PERSISTED slug base is the mode, so a resumed batch behaves
    #: identically — and it brings three things with it: ``abm-<account>`` slugs, ``noindex`` on
    #: every published account page (these are explicit-URL-only pages), and one derived document
    #: per (template, account) converged across re-runs. Passing ``slug_base`` as well is REFUSED
    #: rather than silently overridden.
    abm: bool = False


class WebPublishRequest(BaseModel):
    """Publish a website-mode document to a public slug. An omitted/None slug is
    derived from the document title; a provided slug is validated against the
    public-slug charset by the endpoint."""

    slug: Optional[str] = None
    #: F5 task 13 (ruling R-F1): ask for the robots ``noindex`` meta on this publish's pages.
    #: Defaults OFF, so an ordinary publish is byte-identical to what it produced before this
    #: field existed. It can only ADD noindex: the publish tool ORs the document's DURABLE
    #: ABM noindex, so ``false`` from a share menu can never take an ABM account page back
    #: into the index.
    noindex: bool = False


class SetAgentInstructionsRequest(BaseModel):
    instructions: Optional[str] = None


class SetLayoutManagedEditingRequest(BaseModel):
    enabled: bool = False


class SetWebNoindexRequest(BaseModel):
    """Stamp or clear a web document's durable ``noindex`` (clone-fidelity F4.3, ruling R-F1).

    ``noindex`` is REQUIRED and has NO default. That is the ruling's "removing it requires an
    explicit action", made structural: a body that merely omits the field is a 422, so no caller
    can clear the flag by forgetting to mention it — which is exactly how the publish routes
    (which carry no such field at all) lost it before this ruling.
    """

    noindex: bool


class RenameDocumentRequest(BaseModel):
    """Artifacts page (2026-09-15): the new title; blank is refused (422) by the tool gate."""

    title: str


class SetDocumentArchivedRequest(BaseModel):
    """Artifacts page (2026-09-15): REQUIRED, no default — same rule as ``SetWebNoindexRequest``."""

    archived: bool


class FinalizeTemplateRequest(BaseModel):
    template_revision_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    actor: ActorEnvelope = Field(default_factory=lambda: ActorEnvelope(kind="system"))


class GenerateQrRequest(BaseModel):
    data: str
    label: Optional[str] = None
    ec_level: Optional[str] = None
    print_media: bool = False
    target_width_mm: Optional[float] = None


class GenerateAssetRequest(BaseModel):
    provider: str
    prompt: str = ""
    output_kind: str = "raster_image"
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None
    transparent_background: Optional[bool] = None
    brand_notes: List[str] = Field(default_factory=list)
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    reference_roles: Optional[List[Literal["source", "treatment", "composition"]]] = None
    reference_framing: Optional[str] = None
    operation: Optional[str] = None
    label: Optional[str] = None
    # Phase 3b image EDIT: when set, the prompt is an edit instruction applied
    # to this existing asset's pixels; the result is a NEW asset whose source
    # records the parent (kind "edited"). Remove-background = an edit with
    # transparent_background=true.
    source_asset_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_reference_semantics(self) -> "GenerateAssetRequest":
        if self.reference_roles is not None:
            if len(self.reference_roles) != len(self.reference_asset_ids):
                raise ValueError(
                    "reference_roles must match reference_asset_ids in order and length"
                )
            if any(not asset_id.strip() for asset_id in self.reference_asset_ids) or (
                len(set(self.reference_asset_ids)) != len(self.reference_asset_ids)
            ):
                raise ValueError("role-aware reference_asset_ids must be non-empty and unique")
        if self.reference_framing is not None and (
            not self.reference_framing.strip() or not any(self.reference_asset_ids)
        ):
            raise ValueError(
                "reference_framing requires reference assets and a non-empty instruction"
            )
        if self.source_asset_id and (
            self.reference_roles is not None or self.reference_framing is not None
        ):
            raise ValueError("source edits do not accept generation reference roles or framing")
        return self


class CreateBindingSetRequest(BaseModel):
    binding_set: JsonObject


class DeriveInstanceRequest(BaseModel):
    binding_set_id: Optional[str] = None
    binding_set: Optional[JsonObject] = None
    export_formats: List[str] = Field(default_factory=list)
    export_dpi: Optional[int] = None
    # Bulk print controls: a full export profile (inline) or the name of a
    # profile saved in the revision scene's export_profiles. Mutually
    # exclusive; the profile owns the artifact for its format (bleed, marks,
    # proof, imposition, CMYK, raster scale) via the same adapter pipeline
    # interactive exports use.
    export_profile: Optional[JsonObject] = None
    export_profile_name: Optional[str] = None


class CreateInstanceBatchRequest(BaseModel):
    binding_set_ids: List[str]
    export_formats: List[str] = Field(default_factory=lambda: ["svg", "png"])
    chunk_size: int = 10
    export_profile: Optional[JsonObject] = None
    export_profile_name: Optional[str] = None


class InstancePreviewRequest(BaseModel):
    scene: JsonObject
    binding_set: JsonObject
    format: str = "svg"


class AssetMetadataRequest(BaseModel):
    asset_id: Optional[str] = None
    document_id: Optional[str] = None
    kind: str
    filename: Optional[str] = None
    source_uri: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    dpi: Optional[float] = None
    provenance: JsonObject = Field(default_factory=dict)
    licensing: JsonObject = Field(default_factory=dict)


class BrandKitRefRequest(BaseModel):
    brand_kit_id: str
    version: Optional[int] = None


class CreateBrandKitRequest(BaseModel):
    brand_kit: JsonObject
    source: Literal["manual", "uploaded", "generated", "styles", "platform_default", "api"] = (
        "manual"
    )
    product_ready: bool = True


class CompileStylesBrandKitRequest(BaseModel):
    source: str
    brand_kit_id: str
    version: int = 1
    name: str
    persist: bool = True


class GenerateBrandKitRequest(BaseModel):
    seed: JsonObject
    persist: bool = True


class ValidateBrandKitRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    version: Optional[int] = None
    product_ready: bool = True


class AttachBrandKitRequest(BaseModel):
    brand_kit_id: str
    version: Optional[int] = None
    mode: Optional[JsonObject] = None
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    snapshot_reason: Optional[str] = None


class ValidateDocumentBrandGovernanceRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    version: Optional[int] = None
    strictness: Literal["advisory", "strict", "finalize"] = "strict"


class IngestWebsiteRequest(BaseModel):
    url: str
    page_urls: list[str] = Field(default_factory=list, max_length=19)
    discover_pages: bool = True
    name: Optional[str] = None
    brand_kit_id: Optional[str] = None
    #: REDUNDANT since the founder ruling of 2026-08-20, and kept only so existing callers do
    #: not 422 on a field they still send. Website ingestion now always captures at the rendered
    #: tier — the pipeline forces it (`lumen_ingestion.pipeline._ingest`), because "geometry
    #: needs a live page by definition" and a client that forgets a flag must still get
    #: geometry. Setting it True changes nothing; setting it False does NOT turn rendering off.
    force_render: bool = False


class OnboardAdAssetsRequest(BaseModel):
    """One Brand Ad Assets onboarding job (spec §5 W2), behind ``LUMEN_BRAND_AD_ASSETS``.

    **Own ads only** (ruling D2). The advertiser is identified by the CLIENT's own domain or
    LinkedIn page id; there is no competitor field, and adding one is a deliberate per-client
    opt-in that v1 does not build. Exactly one selector is required — the route refuses both
    and neither, because guessing which one a caller meant would spend a vendor credit on a
    question nobody asked.

    ``brand_kit_id`` / ``brand_kit_version`` name the kit this harvest is FOR. A ``full`` job
    requires them because the ad-DNA card pins the kit version it was distilled against: a card
    that cannot say which brand it describes is a card no turn can safely be conditioned on.

    ``phase`` (auto ad ingestion, 2026-09-28) splits the job so onboarding can start before any
    kit exists: ``harvest`` custodies and describes the ads with no kit, and ``card`` distils and
    pre-generates from a finished harvest's stored ads once a kit exists. ``card`` jobs are
    offered by the worker that finishes second (``ad_library.auto_card``), never by this route.
    """

    phase: Literal["full", "harvest", "card"] = "full"
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    #: The harvest a ``card`` job distils from.
    harvest_job_id: Optional[str] = None
    company_domain: Optional[str] = None
    #: THE OPERATOR'S EXPLICIT OVERRIDE (W5/R3-A), and the strongest selector there is.
    #:
    #: Supplying it SKIPS company-identity resolution entirely — a hand-verified page id is the
    #: operator saying "I looked, it is this one", so calling a resolver to second-guess them
    #: would only spend a credit to relitigate a settled question. It is an assertion rather
    #: than a verification, though, so the job still records `verified: false`, and the
    #: advertiser-name cross-check still gates custody exactly as it does on every other path.
    #:
    #: Accepted under EITHER name. `linkedin_page_id` is the spelling the R3-A design used and
    #: the one the vendor's own wire format uses; `page_id` is what this request has always
    #: called it. They are one field rather than two on purpose — a second, independent page
    #: selector would recreate precisely the "which one did the caller mean" ambiguity the
    #: route refuses `company_domain` + `page_id` together to avoid.
    page_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("page_id", "linkedin_page_id"),
        serialization_alias="page_id",
    )
    #: Overrides the inferred company name the thought-leader filter compares against. Useful
    #: when a page's own creatives are outnumbered by promoted personal posts.
    #:
    #: R3-A gave it a second job: on the two UNVERIFIED paths (an operator-supplied page id, or
    #: a fallback to the ad library's own domain resolution) this is the name the advertiser
    #: cross-check gates custody against, because no independent resolver supplied one. On the
    #: verified path the resolver's name wins — a caller-supplied name compared against itself
    #: would verify nothing.
    advertiser_name: Optional[str] = None
    #: Bounded spend: ~24–25 ads and ~1 vendor credit per page.
    max_pages: int = 3
    max_creatives: int = 15
    #: Recover source ads without spending on style analysis or generated backgrounds.
    #: Persisted with the job so a worker re-drive honors the same requested scope.
    harvest_only: bool = False
    date_filter: Optional[str] = None
    #: The card lineage to append to. Defaults to one card per brand kit.
    card_id: Optional[str] = None


class SetBrandKitApprovalRequest(BaseModel):
    approval_status: Literal["approved", "draft"]


class SetBrandKitLogoRequest(BaseModel):
    """Human logo curation: promote a library asset into a kit logo slot.
    Publishes a NEW kit version — the scraper proposes, the human disposes,
    and the version history records both."""

    asset_id: str
    slot: Literal["primary", "mark", "wordmark"] = "primary"
    color_mode: str = "full_color"



class SetAssetDescriptionRequest(AssetContextPatch):
    pass


class BrandCompatibilityRequest(BaseModel):
    from_brand_kit: Optional[JsonObject] = None
    to_brand_kit: Optional[JsonObject] = None
    from_ref: Optional[BrandKitRefRequest] = None
    to_ref: Optional[BrandKitRefRequest] = None
    persist_report: bool = True
