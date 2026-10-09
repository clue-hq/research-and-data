"""Design-substrate lifecycle enums (Part II slice D1).

Deliberately package-local, not in ``core.enums`` (the fleet/durable precedent): these are the
design subsystem's private vocabularies, mirrored one-to-one by Postgres ENUM types created in
the D1 ``design_*`` migrations. The parity tests in ``tests/design/`` assert the Python members
and DB labels stay in lock-step (member value == DB label, definition order == DB order).

Scope rule (PD contract §4): only vocabularies that were CLOSED in the merged design subsystem —
a SQLite CHECK constraint or a code-enforced closed set — become enums. Engine-owned free-text
vocabularies (document/asset/binding/instance/batch/repair statuses, event types, actor kinds)
stay ``text``; inventing members for them here would fork the engine's vocabulary.
"""

from __future__ import annotations

from enum import StrEnum


class DesignDocKind(StrEnum):
    """``design_doc_kind`` — the document families (scene engine, WebDoc, Puck site)."""

    SCENE = "scene"
    WEB = "web"
    SITE = "site"


class DesignEffectiveBrandSource(StrEnum):
    """``design_effective_brand_source`` — where a document's effective brand kit came from.

    ``PLATFORM_DEFAULT`` postdates the D1a CREATE TYPE (the D1 inventory under-read the closed
    set; the runtime assigns it in four places) — added by migration ``7a9881f9717a`` via
    ``ALTER TYPE … ADD VALUE``, hence last in definition order (parity-locked).
    """

    REQUEST = "request"
    DOCUMENT = "document"
    GENERATED_DEFAULT = "generated_default"
    BRAND_KIT_LIBRARY = "brand_kit_library"
    SCENE_REF = "scene_ref"
    PLATFORM_DEFAULT = "platform_default"


class DesignOpSource(StrEnum):
    """``design_op_source`` — who authored an operation batch (op log + edit envelopes)."""

    EDITOR = "editor"
    AGENT = "agent"
    API = "api"
    SYSTEM = "system"


class DesignBrandApprovalStatus(StrEnum):
    """``design_brand_approval_status`` — brand-kit review lifecycle."""

    DRAFT = "draft"
    GENERATED_UNREVIEWED = "generated_unreviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class DesignBrandKitSource(StrEnum):
    """``design_brand_kit_source`` — how a brand-kit version was produced."""

    MANUAL = "manual"
    UPLOADED = "uploaded"
    GENERATED = "generated"
    STYLES = "styles"
    PLATFORM_DEFAULT = "platform_default"
    API = "api"
    WEBSITE = "website"
    PDF = "pdf"
    ASSET_UPLOAD = "asset_upload"


class DesignDescriptionOrigin(StrEnum):
    """``design_description_origin`` — asset-description authorship (human curation wins)."""

    AI = "ai"
    HUMAN = "human"


class DesignPublishStatus(StrEnum):
    """``design_publish_status`` — web-publish serving state."""

    ACTIVE = "active"
    UNPUBLISHED = "unpublished"


class DesignRunKind(StrEnum):
    """``design_run_kind`` — which design runtime executes a run (PD D5).

    The fleet sees ONE mechanical kind (``FleetTaskKind.DESIGN_JOB``); this column plus the
    by-value ``design_agent_run.payload`` envelope carry the real discriminant, the same shape
    the two M8D research subject types share under ``entity_research_job``.
    """

    AGENT_TURN = "agent_turn"
    WEB_TURN = "web_turn"
    SITE_TURN = "site_turn"


class DesignRunStatus(StrEnum):
    """``design_run_status`` — design-run lifecycle (PD D5).

    ``QUEUED`` is first in definition order because the D5 migration REBUILDS the type rather
    than appending with ``ALTER TYPE … ADD VALUE`` — the lifecycle reads in order, and rebuilding
    is what makes the widening reversible (PostgreSQL cannot drop an enum label). A run is born
    ``QUEUED`` by the API and stamped ``RUNNING`` by the worker that claims it.

    Suspension / HITL states are deliberately absent: D5 keeps the status vocabulary minimal.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DesignIngestionKind(StrEnum):
    """``design_ingestion_kind`` — brand-onboarding job input kinds.

    ``AD_ASSETS`` (Brand Ad Assets v1, W2) is the fourth: harvest → filter/dedupe → custody →
    distill → pre-generate for one brand's own published ads. It rides ``design_ingestion_job``
    rather than a private job table because everything that made ingestion durable — fleet
    dispatch, the generation fence, stage reporting, the stranded-work reaper — is the same
    machinery this lane needs, and a second copy of it would be a second thing to keep right.
    The member is APPENDED: ``tests/design/test_design_schema_db`` asserts label ORDER against
    the Postgres type lock-step, so its position here is the migration's position too.
    """

    WEBSITE = "website"
    PDF = "pdf"
    ASSET_UPLOAD = "asset_upload"
    AD_ASSETS = "ad_assets"
    ASSET_ENRICHMENT = "asset_enrichment"


class DesignIngestionStatus(StrEnum):
    """``design_ingestion_status`` — ingestion-job lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DesignCompilationStatus(StrEnum):
    """``design_compilation_status`` — custom-component compiler outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TRANSIENT_ERROR = "transient_error"


#: enum-type name -> Python enum, exactly as created in the D1 migrations (parity-test surface).
DESIGN_PG_ENUMS: dict[str, type[StrEnum]] = {
    "design_doc_kind": DesignDocKind,
    "design_effective_brand_source": DesignEffectiveBrandSource,
    "design_op_source": DesignOpSource,
    "design_brand_approval_status": DesignBrandApprovalStatus,
    "design_brand_kit_source": DesignBrandKitSource,
    "design_description_origin": DesignDescriptionOrigin,
    "design_publish_status": DesignPublishStatus,
    "design_run_kind": DesignRunKind,
    "design_run_status": DesignRunStatus,
    "design_ingestion_kind": DesignIngestionKind,
    "design_ingestion_status": DesignIngestionStatus,
    "design_compilation_status": DesignCompilationStatus,
}
