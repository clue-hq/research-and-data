//! Platform-independent contract core for the ABM Design Engine.
//!
//! This crate owns design semantics. It intentionally does not know about
//! React, Konva, FastAPI, databases, object storage, browser APIs, or WebGPU.

pub mod assets;
pub mod binding;
pub mod brand;
pub mod diagnostics;
pub mod dsl;
pub mod editing;
pub mod export_contract;
pub mod hit_test;
pub mod icons;
pub mod ids;
pub mod instance;
pub mod layout;
pub mod operations;
pub mod page_geometry;
pub mod preflight;
pub mod reconcile;
pub mod render_contract;
pub mod render_geometry;
pub mod scene;
pub mod slots;
pub mod snapshot;
pub mod text_measure;
pub mod validation;

pub use assets::{
    validate_asset_manifest, validate_brand_asset_references, validate_scene_assets, AssetDigest,
    AssetGenerationConstraints, AssetGenerationRequest, AssetGenerationResult, AssetKind,
    AssetLicense, AssetLocation, AssetManifest, AssetMediaMetadata, AssetPlacement,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, AssetThumbnail, AssetValidationOptions,
    AssetVectorizationRequest, AssetVectorizationResult, FontAssetMetadata, LogoAssetMetadata,
    RasterAssetMetadata, VectorAssetMetadata,
};
pub use binding::{
    validate_binding_set, BindingAudience, BindingSet, BoundValue, ConditionalExpr,
    GeneratedAssetInput, GeneratedAssetSpec, InstanceLink, BINDING_SCHEMA_VERSION,
};
pub use brand::{
    collect_scene_token_references, compare_brand_kit_compatibility, compile_styles_brand_kit,
    generate_brand_kit, platform_default_brand_kit, resolve_scene_tokens,
    scene_has_token_references, summarize_brand_kit_for_authoring, validate_brand_kit,
    validate_brand_kit_product_ready, validate_scene_brand_governance, validate_scene_tokens,
    AssetToken, AssetTokenValue, BrandApprovalStatus, BrandAsset, BrandAssets,
    BrandAuthoringAssetSummary, BrandAuthoringTokenSummary, BrandCompatibilityPolicy,
    BrandCompatibilityReport, BrandCompatibilityStatus, BrandConstraints, BrandGenerationReport,
    BrandGovernanceStrictness, BrandKit, BrandKitAuthoringSummary, BrandMode, BrandModeSpec,
    BrandProvenance, BrandSeed, BrandSeedLogoRef, BrandSource, BrandValidationLevel, ColorToken,
    ColorTokenValue, ContrastPair, EffectToken, EffectValue, FontAsset, FontFace, FontLicense,
    FontStyle, LogoAsset, LogoColorMode, LogoUsage, LogoVariant, ModeValue, NumberToken,
    NumberTokenValue, NumberUnit, SceneTokenReference, ShadowToken, ShadowValue, TokenAlias,
    TokenCatalog, TokenChange, TokenChangeKind, TokenFallbackPolicy, TokenProvenance,
    TokenResolutionOptions, TokenResolutionReport, TokenStrictness, TypographyToken,
    TypographyTokenValue, REQUIRED_PRODUCT_READY_ASSET_TOKENS, REQUIRED_PRODUCT_READY_COLOR_TOKENS,
    REQUIRED_PRODUCT_READY_OPACITY_TOKENS, REQUIRED_PRODUCT_READY_RADIUS_TOKENS,
    REQUIRED_PRODUCT_READY_SPACING_TOKENS, REQUIRED_PRODUCT_READY_STROKE_WIDTH_TOKENS,
    REQUIRED_PRODUCT_READY_TYPOGRAPHY_TOKENS,
};
pub use diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
pub use dsl::{
    compile_dsl, compile_dsl_into_scene, compile_dsl_into_scene_with_session,
    compile_dsl_into_scene_with_session_and_protected, compile_dsl_into_scene_with_text_context,
    normalize_dsl, parse_dsl, slot_id_for_key, DslCompileOutput, DslCompileSession,
    DslCompileSessionSnapshot, DslDiagnostic, DslDimension, DslDirective, DslDocument, DslElement,
    DslElementKind, DslFill, DslFont, DslHalt, DslHistoryAdapter, DslLayoutAnchor, DslLayoutAxis,
    DslLine, DslLineKind, DslModification, DslPage, DslPagePreset, DslParentFrameSnapshot,
    DslParentPlacement, DslParseOutput, DslProperty, DslScalar, DslSceneCompileOutput, DslShadow,
    DslStroke, SourceSpan,
};
pub use editing::{
    batch_scope_violations, build_archive_asset, build_asset_modify, build_clone_subtree,
    build_convert_container_layout, build_delete_export_profile, build_detach_to_freehand,
    build_document_modify, build_export_profile_modify, build_freeze_layout, build_group,
    build_hard_delete_asset, build_modify_operations, build_modify_operations_with_text_context,
    build_move_after, build_move_before, build_move_to_parent, build_node_modify,
    build_page_modify, build_reattach_to_layout, build_replace_node, build_safe_delete,
    build_safe_delete_page, build_safe_delete_slot, build_slot_modify, build_structured_edit_batch,
    build_structured_edit_batch_with_text_context, build_ungroup, resolve_edit_target,
    AssetEditPatch, CloneLineage, CloneSlotPolicy, CloneSubtreeRequest, ComputedClonePolicy,
    EditBatch, EditError, EditErrorKind, EditPatch, EditScope, EditScopeMode, EditTargetRef,
    ExportProfileEditPatch, NodeEditPatch, PageEditPatch, RelativePlacement, ReplaceNodeRequest,
    ReplaceSlotPolicy, ResolvedEditTarget, ScopeViolation, SlotEditPatch, StackEntryEdit,
    StructuredEditInstruction, TextEditContext, TextEditPatch,
};
pub use export_contract::{
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportProfile, ExportPurpose,
    ExportRequest, ExportResult, PdfIntent, PrintReadyReport, PrintReadyRule, RasterScale,
};
pub use hit_test::{hit_stack, hit_test};
pub use ids::{
    AssetId, BrandKitId, DocumentId, EffectId, IdError, NodeId, OperationId, PageId, PaintId,
    SlotId, SlotKey, TemplateRevisionId,
};
pub use instance::{
    derive_instance, DerivationAssets, DeriveOptions, DerivedInstance, InstanceAuditEntry,
    InstanceAuditKind, InstanceFitReport, InstanceFitStatus, SlotFitEntry, SlotFitVerdict,
    TemplateRepairRequest,
};
pub use layout::{
    layout_operations, layout_scene, painted_text_lines, validate_layout, LayoutOptions,
    LayoutResult,
};
pub use operations::{
    DocumentPatch, FieldPatch, NodePatch, Operation, OperationError, OperationReport,
    OperationResult, OptionalFieldPatch, PagePatch,
};
pub use page_geometry::{
    is_canonical_page_size, normalize_page_size, page_geometry, page_rect_points,
    page_size_for_preset, page_size_points, physical_page_size_inches, physical_to_inches,
    points_to_physical, unit_to_inches, unit_to_points, PageGeometry, PageSizeInput, MM_PER_INCH,
    POINTS_PER_INCH,
};
pub use preflight::{preflight_scene, PreflightOptions, PreflightResult};
pub use reconcile::{reconcile_subtree, IntendedSubtree, ReconcileNote};
pub use render_contract::{
    effect_features_for_node, effect_support_diagnostics, EffectFeature, EffectSupportLevel,
    RenderIntent, RenderManifest, RenderTarget, RendererAdapter, RendererEffectSupport,
    RendererError,
};
pub use render_geometry::{
    node_render_size, paints_out_of_tree, pinned_paint_pass, render_box_for_node, RenderBox,
};
pub use scene::{
    AutoLayoutDirection, AutoLayoutNode, AutoLayoutProps, BrandKitRef, Color, ColorStop,
    ComputedGeometry,
    CornerRadii, Dimension, DocumentMeta, DocumentStatus, Effect, EffectKind, Fill, ImageNode,
    LayoutAnchor, LayoutMode, LineNode, Medium, Node, NodeKind, Orientation, Page, PageOutputSize,
    PagePreset, PageSize, PageSizeSource, Paint, ParentRef, PhysicalPageSize, PhysicalUnit,
    PositionMode, RasterPageSize, Rect, Scene, SizeSpec, SpanSegment, Stroke, StrokeAlign,
    StrokeCap, StrokeJoin, TextAlign, TextDirection, TextNode, TextSpan, TextTransform, TextWrap,
    Transform, Unit, VectorNode, VerticalAlign,
};
pub use scene::{
    normalize_content_mapped, span_validation_errors, transform_segments, valign_offset,
    SpanValidationError,
};
pub use slots::{
    BindingHint, Cardinality, ConditionalRule, ContentType, Editability, EmptyBehavior, FocalPoint,
    FormattingConstraints, ImageFitMode, ImagePolicy, OverflowPolicy, ReflowPolicy, RepeaterRule,
    Slot, SlotScope, ValidationFixtures,
};
pub use snapshot::{SnapshotError, SnapshotResult};
pub use text_measure::{
    estimate_text_width, heuristic_measurement_diagnostic, line_height_px, measure_key,
    measure_text, HeuristicTextMeasurer, ProvidedLine, ProvidedMetrics, ProvidedTextMeasurer,
    SharedTextMeasurer, TextLineBox, TextMeasureInput, TextMeasureOutput, TextMeasurer, TextRunBox,
};

pub const SCHEMA_VERSION: u32 = 1;
