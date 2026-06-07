//! Platform-independent contract core for the ABM Design Engine.
//!
//! This crate owns design semantics. It intentionally does not know about
//! React, Konva, FastAPI, databases, object storage, browser APIs, or WebGPU.

pub mod diagnostics;
pub mod dsl;
pub mod export_contract;
pub mod ids;
pub mod operations;
pub mod render_contract;
pub mod scene;
pub mod slots;
pub mod snapshot;
pub mod validation;

pub use diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
pub use dsl::{
    compile_dsl, compile_dsl_into_scene, normalize_dsl, parse_dsl, DslCompileOutput,
    DslCompileSession, DslDiagnostic, DslDimension, DslDirective, DslDocument, DslElement,
    DslElementKind, DslFill, DslFont, DslHalt, DslLayoutAnchor, DslLayoutAxis, DslLine,
    DslLineKind, DslModification, DslPage, DslPagePreset, DslParseOutput, DslProperty, DslScalar,
    DslSceneCompileOutput, DslStroke, SourceSpan,
};
pub use export_contract::{
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportProfile, ExportPurpose,
    ExportRequest, ExportResult, PdfIntent, RasterScale,
};
pub use ids::{
    AssetId, BrandKitId, DocumentId, IdError, NodeId, OperationId, PageId, PaintId, SlotId,
    SlotKey, TemplateRevisionId,
};
pub use operations::{
    DocumentPatch, FieldPatch, NodePatch, Operation, OperationError, OperationReport,
    OperationResult, OptionalFieldPatch, PagePatch,
};
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
