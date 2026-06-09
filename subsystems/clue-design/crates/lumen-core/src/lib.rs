//! Platform-independent contract core for the ABM Design Engine.
//!
//! This crate owns design semantics. It intentionally does not know about
//! React, Konva, FastAPI, databases, object storage, browser APIs, or WebGPU.

pub mod assets;
pub mod brand;
pub mod diagnostics;
pub mod dsl;
pub mod export_contract;
pub mod ids;
pub mod layout;
pub mod operations;
pub mod preflight;
pub mod render_contract;
pub mod scene;
pub mod slots;
pub mod snapshot;
pub mod validation;

pub use assets::{
    validate_asset_manifest, validate_brand_asset_references, validate_scene_assets, AssetDigest,
    AssetGenerationConstraints, AssetGenerationRequest, AssetGenerationResult, AssetKind,
    AssetLicense, AssetLocation, AssetManifest, AssetMediaMetadata, AssetPlacement,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, AssetValidationOptions,
    AssetVectorizationRequest, AssetVectorizationResult, FontAssetMetadata, LogoAssetMetadata,
    RasterAssetMetadata, VectorAssetMetadata,
};
pub use brand::{
    collect_scene_token_references, compile_styles_brand_kit, platform_default_brand_kit,
    resolve_scene_tokens, scene_has_token_references, validate_brand_kit, validate_scene_tokens,
    AssetToken, AssetTokenValue, BrandAsset, BrandAssets, BrandConstraints, BrandKit, BrandMode,
    BrandModeSpec, BrandProvenance, BrandSource, ColorToken, ColorTokenValue, ContrastPair,
    EffectToken, EffectValue, FontAsset, FontFace, FontLicense, FontStyle, LogoAsset,
    LogoColorMode, LogoUsage, LogoVariant, ModeValue, NumberToken, NumberTokenValue, NumberUnit,
    SceneTokenReference, ShadowToken, ShadowValue, TokenAlias, TokenCatalog, TokenFallbackPolicy,
    TokenProvenance, TokenResolutionOptions, TokenResolutionReport, TokenStrictness,
    TypographyToken, TypographyTokenValue,
};
pub use diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
pub use dsl::{
    compile_dsl, compile_dsl_into_scene, compile_dsl_into_scene_with_session, normalize_dsl,
    parse_dsl, DslCompileOutput, DslCompileSession, DslCompileSessionSnapshot, DslDiagnostic,
    DslDimension, DslDirective, DslDocument, DslElement, DslElementKind, DslFill, DslFont, DslHalt,
    DslLayoutAnchor, DslLayoutAxis, DslLine, DslLineKind, DslModification, DslPage, DslPagePreset,
    DslParentFrameSnapshot, DslParseOutput, DslProperty, DslScalar, DslSceneCompileOutput,
    DslStroke, SourceSpan,
};
pub use export_contract::{
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportProfile, ExportPurpose,
    ExportRequest, ExportResult, PdfIntent, RasterScale,
};
pub use ids::{
    AssetId, BrandKitId, DocumentId, IdError, NodeId, OperationId, PageId, PaintId, SlotId,
    SlotKey, TemplateRevisionId,
};
pub use layout::{layout_operations, layout_scene, validate_layout, LayoutOptions, LayoutResult};
pub use operations::{
    DocumentPatch, FieldPatch, NodePatch, Operation, OperationError, OperationReport,
    OperationResult, OptionalFieldPatch, PagePatch,
};
pub use preflight::{preflight_scene, PreflightOptions, PreflightResult};
pub use render_contract::{
    RenderIntent, RenderManifest, RenderTarget, RendererAdapter, RendererError,
};
pub use scene::{
    AutoLayoutDirection, AutoLayoutNode, AutoLayoutProps, BrandKitRef, Color, ComputedGeometry,
    CornerRadii, Dimension, DocumentMeta, DocumentStatus, Fill, ImageNode, LineNode, Medium, Node,
    NodeKind, Orientation, Page, PagePreset, PageSize, Paint, ParentRef, Rect, Scene, SizeSpec,
    Stroke, TextAlign, TextNode, Transform, Unit, VectorNode,
};
pub use slots::{
    BindingHint, Cardinality, ConditionalRule, ContentType, Editability, EmptyBehavior, FocalPoint,
    FormattingConstraints, ImageFitMode, ImagePolicy, OverflowPolicy, ReflowPolicy, RepeaterRule,
    Slot, SlotScope, ValidationFixtures,
};
pub use snapshot::{SnapshotError, SnapshotResult};

pub const SCHEMA_VERSION: u32 = 1;
