"""The ONE list of design tools (Part II slice D6, ruling R-D6-1).

Two composition roots call this, and they differ only in the host they pass:

* the **design API** (:mod:`lumen_api.toolbelt.wiring`, via ``main.create_app``) passes a real
  :class:`~lumen_api.toolbelt.base.DesignToolHost`, so the tools serve the REST routes and the
  deep agent's component registry;
* the **platform** (``clue_api.design_tools`` → ``clue_api.toolbelt_wiring.build_toolbelt``)
  passes ``None`` unless ``design_runtime_enabled`` is set, so the same envelopes are registered
  (and audited) everywhere while remaining inert where no design runtime exists.

Adding a tool to a later D6 round means adding it here and to ``DESIGN_TOOL_NAMES``; the platform
tests (`tests/api/test_toolbelt_wiring.py`, `tests/agents/test_tool_authority_audit.py`) then fail
until it has an explicit C6 authority decision and an out-of-order matrix entry — which is the
point.
"""

from __future__ import annotations

from clue_toolbelt import Tool

from .accounts import CreateWebAccountTool, DeleteWebAccountTool, UpdateWebAccountTool
from .ad_assets import (
    LinkAdPregeneratedAssetsTool,
    PublishAdDnaCardTool,
    RecordAdCreativesTool,
)
from .assets import (
    DeleteAssetTool,
    RegisterAssetRecordTool,
    RegisterAssetRecordV2Tool,
    RegisterCapturedAssetsTool,
    RegisterGeneratedAssetTool,
    RegisterQrAssetTool,
    SetAssetDescriptionTool,
    SetAssetDescriptionV2Tool,
    SetAssetStatusTool,
)
from .base import DesignToolHost
from .brand import (
    CreateBrandCompatibilityReportTool,
    CreateBrandKitTool,
    PublishBrandKitVersionTool,
    SetBrandKitApprovalTool,
)
from .components import CompileCustomComponentTool, WriteCustomComponentSourceTool
from .documents import (
    ApplyOperationsTool,
    ApplyStructuredEditTool,
    AttachBrandKitTool,
    CreateDocumentTool,
    CreateSnapshotTool,
    FinalizeDocumentTool,
    PersistPreflightTool,
    RecordDiagnosticsTool,
    RedoDocumentTool,
    RenameDocumentTool,
    ReplaceSceneTool,
    SetAgentInstructionsTool,
    SetDocumentArchivedTool,
    SetLayoutManagedEditingTool,
    SetWebNoindexTool,
    UndoDocumentTool,
)
from .ingestion import (
    EnrichAssetsTool,
    IngestAdAssetsTool,
    IngestAssetsTool,
    IngestPdfTool,
    IngestWebsiteTool,
)
from .personalization import (
    AdvanceInstanceBatchTool,
    AdvanceWebBatchTool,
    CreateInstanceBatchTool,
    CreateWebBatchTool,
    DeleteBindingSetTool,
    DeriveInstanceTool,
    UpsertBindingSetTool,
)
from .publishes import (
    PublishWebDocumentTool,
    RollbackWebPublishTool,
    UnpublishWebDocumentTool,
)
from .site_documents import RedoSiteTool, UndoSiteTool, WriteSiteTool
from .turns import StartAgentTurnTool, StartWebTurnTool
from .web_documents import (
    ApplyWebOperationsTool,
    CreateWebTemplateTool,
    DeriveWebDocumentTool,
    RedoWebDocumentTool,
    UndoWebDocumentTool,
)

__all__ = ["DESIGN_TOOL_NAMES", "DESIGN_TOOL_TYPES", "build_design_tools"]

DESIGN_TOOL_TYPES = (
    # Round A reference domain 1 — publishes.
    PublishWebDocumentTool,
    UnpublishWebDocumentTool,
    RollbackWebPublishTool,
    # Round A reference domain 2 — personalization accounts.
    CreateWebAccountTool,
    UpdateWebAccountTool,
    DeleteWebAccountTool,
    # Round A reference domain 3 — custom components.
    WriteCustomComponentSourceTool,
    CompileCustomComponentTool,
    # Round B domain 1 — scene documents, history and diagnostics.
    CreateDocumentTool,
    SetAgentInstructionsTool,
    SetLayoutManagedEditingTool,
    SetWebNoindexTool,
    # Artifacts page (2026-09-15): the library's two curation writes.
    RenameDocumentTool,
    SetDocumentArchivedTool,
    ReplaceSceneTool,
    ApplyOperationsTool,
    ApplyStructuredEditTool,
    UndoDocumentTool,
    RedoDocumentTool,
    CreateSnapshotTool,
    PersistPreflightTool,
    AttachBrandKitTool,
    FinalizeDocumentTool,
    RecordDiagnosticsTool,
    # Round B domain 2 — website-mode documents.
    CreateWebTemplateTool,
    DeriveWebDocumentTool,
    ApplyWebOperationsTool,
    UndoWebDocumentTool,
    RedoWebDocumentTool,
    # Wave 2 Lane A — Puck site documents (Contract 2).
    WriteSiteTool,
    UndoSiteTool,
    RedoSiteTool,
    # Round B domain 3 — turn enqueues.
    StartAgentTurnTool,
    StartWebTurnTool,
    # Round C domain 1 — brand kits.
    CreateBrandKitTool,
    PublishBrandKitVersionTool,
    SetBrandKitApprovalTool,
    CreateBrandCompatibilityReportTool,
    # Round C domain 2 — brand-kit ingestion enqueues.
    IngestWebsiteTool,
    IngestPdfTool,
    IngestAssetsTool,
    # Round C domain 3 — the asset registry.
    RegisterAssetRecordTool,
    RegisterAssetRecordV2Tool,
    RegisterQrAssetTool,
    RegisterGeneratedAssetTool,
    RegisterCapturedAssetsTool,
    SetAssetStatusTool,
    DeleteAssetTool,
    SetAssetDescriptionTool,
    SetAssetDescriptionV2Tool,
    # Round C domain 4 — personalization and both batch families.
    UpsertBindingSetTool,
    DeleteBindingSetTool,
    DeriveInstanceTool,
    CreateInstanceBatchTool,
    AdvanceInstanceBatchTool,
    CreateWebBatchTool,
    AdvanceWebBatchTool,
    # Brand Ad Assets v1 W2 — the ad-assets lane (flag-gated at its route, registered here
    # unconditionally so the platform's C6 authority audit stays a complete statement).
    IngestAdAssetsTool,
    EnrichAssetsTool,
    RecordAdCreativesTool,
    PublishAdDnaCardTool,
    LinkAdPregeneratedAssetsTool,
)

#: The registered names, in registration order. The platform's authority map and the design-side
#: no-bypass guard both assert against this tuple, so the two can never silently diverge.
DESIGN_TOOL_NAMES: tuple[str, ...] = tuple(dict.fromkeys(item.name for item in DESIGN_TOOL_TYPES))


def build_design_tools(host: DesignToolHost | None = None) -> tuple[Tool, ...]:
    """Construct every design tool against ``host`` (``None`` ⇒ registered but refusing)."""
    return tuple(item(host) for item in DESIGN_TOOL_TYPES)


def is_default_design_tool(tool: Tool) -> bool:
    return tool.descriptor.version == next(item.version for item in reversed(DESIGN_TOOL_TYPES) if item.name == tool.descriptor.name)
