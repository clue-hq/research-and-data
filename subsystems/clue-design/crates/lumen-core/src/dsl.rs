#![allow(clippy::result_large_err)]

use crate::editing::{ExportProfileEditPatch, StackEntryEdit};
use crate::scene::{BrandKitRef, ColorStop, Medium};
use crate::{
    build_archive_asset, build_clone_subtree, build_delete_export_profile, build_hard_delete_asset,
    build_modify_operations, build_move_after, build_move_before, build_move_to_parent,
    build_replace_node, build_safe_delete, build_safe_delete_page, build_safe_delete_slot,
    build_ungroup, normalize_page_size, page_size_for_preset, resolve_edit_target, AssetEditPatch,
    AssetId, AutoLayoutDirection, AutoLayoutNode, AutoLayoutProps, CloneSlotPolicy,
    CloneSubtreeRequest, Color, ComputedClonePolicy, Diagnostic, DiagnosticSeverity, DocumentPatch,
    EditError, EditPatch, EditTargetRef, Effect, EffectId, EffectKind, ExportFormat, FieldPatch,
    Fill, ImageNode, LayoutAnchor, LineNode, Node, NodeEditPatch, NodeId, NodeKind, Operation,
    OperationError, OperationReport, OptionalFieldPatch, Orientation, Page, PageEditPatch, PageId,
    PagePreset, PageSizeInput, Paint, PaintId, ParentRef, PdfIntent, Phase, RasterScale, Rect,
    RelativePlacement, ReplaceNodeRequest, ReplaceSlotPolicy, Scene, SizeSpec, Slot, SlotEditPatch,
    SlotId, SlotKey, Stroke, StrokeAlign, StrokeCap, StrokeJoin, TextAlign, TextDirection,
    TextEditPatch, TextNode, TextWrap, Unit, VectorNode,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub fn normalize_dsl(source: &str) -> String {
    normalized_lines(source)
        .into_iter()
        .map(|line| line.text)
        .collect::<Vec<_>>()
        .join("\n")
}

pub fn parse_dsl(source: &str) -> DslParseOutput {
    DslParser::new(source).parse()
}

/// Operation source for history-aware `undo(...)`/`redo(...)` lowering.
/// The API's append-only envelope log is the canonical product
/// implementation (POST /undo, /redo, /revert); this trait lets session
/// hosts lower the DSL forms against the same history. Pure `compile_dsl`
/// has no history and keeps rejecting undo/redo with a precise diagnostic.
pub trait DslHistoryAdapter {
    /// Inverse operations that revert the batch addressed by `label`
    /// (or the latest undoable batch when `None`).
    fn undo_operations(&self, label: Option<&str>) -> Option<Vec<Operation>>;
    /// Original operations that re-apply the batch addressed by `label`
    /// (or the latest redoable batch when `None`).
    fn redo_operations(&self, label: Option<&str>) -> Option<Vec<Operation>>;
}

pub fn compile_dsl(source: &str) -> DslCompileOutput {
    let mut session = DslCompileSession::empty();
    session.compile_block(source)
}

pub fn compile_dsl_into_scene(source: &str, scene: &mut Scene) -> DslSceneCompileOutput {
    compile_dsl_into_scene_with_session(source, scene, None)
}

pub fn compile_dsl_into_scene_with_session(
    source: &str,
    scene: &mut Scene,
    session_snapshot: Option<DslCompileSessionSnapshot>,
) -> DslSceneCompileOutput {
    let mut session = session_snapshot
        .map(|snapshot| DslCompileSession::from_snapshot(scene.clone(), snapshot))
        .unwrap_or_else(|| DslCompileSession::new(scene.clone()));
    let previous_snapshot = session.snapshot();
    let compile_output = session.compile_block(source);

    if compile_output.has_errors() {
        return DslSceneCompileOutput {
            compile_output,
            operation_report: None,
            operation_error: None,
            session_snapshot: previous_snapshot,
        };
    }

    match scene.apply_operations_checked(compile_output.operations.clone()) {
        Ok(report) => {
            session.sync_scene_preserving_context(scene.clone());
            DslSceneCompileOutput {
                compile_output,
                operation_report: Some(report),
                operation_error: None,
                session_snapshot: session.snapshot(),
            }
        }
        Err(error) => DslSceneCompileOutput {
            compile_output,
            operation_report: None,
            operation_error: Some(error),
            session_snapshot: previous_snapshot,
        },
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslCompileSession {
    scene: Scene,
    parser_context: DslParserContext,
    parent_stack: Vec<ParentFrame>,
    emitted_slots: BTreeMap<SlotKey, SlotId>,
}

impl DslCompileSession {
    pub fn empty() -> Self {
        Self::new(Scene::new(
            crate::DocumentId::from("doc_dsl_compile"),
            "DSL Compile",
        ))
    }

    pub fn new(scene: Scene) -> Self {
        let emitted_slots = scene
            .slots
            .values()
            .map(|slot| (slot.key.clone(), slot.id.clone()))
            .collect();
        Self {
            parser_context: DslParserContext::from_scene(&scene),
            scene,
            parent_stack: Vec::new(),
            emitted_slots,
        }
    }

    pub fn from_snapshot(scene: Scene, snapshot: DslCompileSessionSnapshot) -> Self {
        let mut emitted_slots: BTreeMap<SlotKey, SlotId> = scene
            .slots
            .values()
            .map(|slot| (slot.key.clone(), slot.id.clone()))
            .collect();
        emitted_slots.extend(snapshot.emitted_slots);
        let mut session = Self {
            parser_context: DslParserContext {
                seen_node_ids: snapshot.seen_node_ids,
                previous_structural_depth: snapshot.previous_structural_depth,
                previous_can_have_children: snapshot.previous_can_have_children,
            },
            scene,
            parent_stack: snapshot
                .parent_stack
                .into_iter()
                .map(|frame| ParentFrame {
                    indent: frame.indent,
                    parent: frame.parent,
                })
                .collect(),
            emitted_slots,
        };
        let scene = &session.scene;
        session
            .parent_stack
            .retain(|frame| parent_can_receive_children(scene, &frame.parent));
        session
    }

    pub fn compile_block(&mut self, source: &str) -> DslCompileOutput {
        self.compile_block_with_history(source, None)
    }

    pub fn compile_block_with_history(
        &mut self,
        source: &str,
        history: Option<&dyn DslHistoryAdapter>,
    ) -> DslCompileOutput {
        let starting_context = self.parser_context.clone();
        let (parse, parsed_context) =
            DslParser::new_with_context(source, starting_context.clone()).parse_with_context();
        let mut compiler = DslCompiler::new(
            parse.document.clone(),
            parse.diagnostics.clone(),
            &mut self.scene,
            &mut self.parent_stack,
            &mut self.emitted_slots,
            history,
        );
        let output = compiler.compile(parse.halted_at.clone());

        self.parser_context = if let Some(halt) =
            lower_halt_before_parse_halt(output.halted_at.as_ref(), parse.halted_at.as_ref())
        {
            parser_context_after_lines(&starting_context, &parse.document.lines, halt.line)
        } else {
            parsed_context
        };

        output
    }

    pub fn snapshot(&self) -> DslCompileSessionSnapshot {
        DslCompileSessionSnapshot {
            seen_node_ids: self.parser_context.seen_node_ids.clone(),
            previous_structural_depth: self.parser_context.previous_structural_depth,
            previous_can_have_children: self.parser_context.previous_can_have_children,
            parent_stack: self
                .parent_stack
                .iter()
                .map(|frame| DslParentFrameSnapshot {
                    indent: frame.indent,
                    parent: frame.parent.clone(),
                })
                .collect(),
            emitted_slots: self.emitted_slots.clone(),
        }
    }

    pub fn sync_scene_preserving_context(&mut self, scene: Scene) {
        self.emitted_slots = scene
            .slots
            .values()
            .map(|slot| (slot.key.clone(), slot.id.clone()))
            .collect();
        self.scene = scene;
        self.parent_stack
            .retain(|frame| parent_can_receive_children(&self.scene, &frame.parent));
    }

    pub fn scene(&self) -> &Scene {
        &self.scene
    }

    pub fn into_scene(self) -> Scene {
        self.scene
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslSceneCompileOutput {
    pub compile_output: DslCompileOutput,
    pub operation_report: Option<OperationReport>,
    pub operation_error: Option<OperationError>,
    pub session_snapshot: DslCompileSessionSnapshot,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DslCompileSessionSnapshot {
    pub seen_node_ids: BTreeSet<NodeId>,
    pub previous_structural_depth: Option<usize>,
    pub previous_can_have_children: bool,
    pub parent_stack: Vec<DslParentFrameSnapshot>,
    pub emitted_slots: BTreeMap<SlotKey, SlotId>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DslParentFrameSnapshot {
    pub indent: usize,
    pub parent: ParentRef,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslCompileOutput {
    pub document: DslDocument,
    pub operations: Vec<Operation>,
    pub diagnostics: Vec<DslDiagnostic>,
    pub halted_at: Option<DslHalt>,
    /// Last `// label` checkpoint comment successfully lowered in this
    /// block. Callers attach it to the persisted edit envelope so narration,
    /// undo anchor, and trace label stay one artifact.
    pub checkpoint_label: Option<String>,
}

impl DslCompileOutput {
    pub fn has_errors(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslParseOutput {
    pub document: DslDocument,
    pub diagnostics: Vec<DslDiagnostic>,
    pub halted_at: Option<DslHalt>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DslDocument {
    pub lines: Vec<DslLine>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslLine {
    pub line_number: usize,
    pub indent: usize,
    pub raw: String,
    pub kind: DslLineKind,
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslLineKind {
    Comment(String),
    Checkpoint(String),
    Page(DslPage),
    Element(DslElement),
    Directive(DslDirective),
    Modification(DslModification),
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslPage {
    pub id: PageId,
    pub preset: Option<DslPagePreset>,
    pub size: Option<DslPageSize>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslPagePreset {
    pub preset: PagePreset,
    pub orientation: Orientation,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslPageSize {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslElement {
    pub id: NodeId,
    pub kind: DslElementKind,
    pub properties: Vec<DslProperty>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslElementKind {
    Frame,
    Group,
    Rect,
    Ellipse,
    Line { x2: f64, y2: f64 },
    Text { content: String },
    Image { asset_id: Option<AssetId> },
    Vector { path_data: Option<String> },
    SvgIcon { icon: String },
    AutoLayout { direction: AutoLayoutDirection },
    Instance { source_node_id: Option<NodeId> },
}

impl DslElementKind {
    fn can_have_children(&self) -> bool {
        matches!(self, Self::Frame | Self::Group | Self::AutoLayout { .. })
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslProperty {
    Position(f64, f64),
    Size(DslDimension, DslDimension),
    PageSize(DslPageSize),
    TextContent(String),
    Fill(DslFill),
    PageBackground(DslFill),
    Stroke(DslStroke),
    Shadow(DslShadow),
    RemoveEffect(EffectId),
    Font(DslFont),
    FontSize(DslScalar),
    FontWeight(u16),
    Slot(SlotKey),
    Asset(AssetId),
    Path(String),
    Source(NodeId),
    Radius(DslScalar),
    Opacity(DslScalar),
    Rotation(f64),
    Skew(f64, f64),
    Flip {
        x: bool,
        y: bool,
    },
    Clip(bool),
    Gap(DslScalar),
    Padding([DslScalar; 4]),
    Wrap(bool),
    TextWrap(bool),
    LineHeight(DslScalar),
    LetterSpacing(DslScalar),
    Tracking(DslScalar),
    MaxLines(u16),
    TextDirection(TextDirection),
    Grow(DslScalar),
    TextStyleToken(String),
    LayoutAnchor {
        axis: DslLayoutAxis,
        anchor: DslLayoutAnchor,
    },
    SafeArea(Rect),
    Bleed(Rect),
    SlotLabel(String),
    SlotRequired(bool),
    SlotPlaceholder(String),
    SlotSample(String),
    SlotWorstCase(String),
    SlotBind(NodeId),
    SlotUnbind(NodeId),
    LineTo(f64, f64),
    Name(String),
    Token(String),
    TextAppend(String),
    TextPrepend(String),
    ArtifactType(String),
    DocumentMedium(Medium),
    DocumentBrandKit(String, u32),
    ExportFormatValue(ExportFormat),
    ExportPdfIntent(PdfIntent),
    ExportRasterScale {
        scale: f64,
        dpi: Option<u16>,
    },
    ExportIncludeBleed(bool),
    ExportEmbedFonts(bool),
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslScalar {
    Number(f64),
    Token(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DslLayoutAxis {
    X,
    Y,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DslLayoutAnchor {
    Start,
    Center,
    End,
    SpaceBetween,
    Stretch,
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslDimension {
    Fixed(f64),
    Hug,
    Fill(Option<f64>),
    Token(String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslFill {
    pub id: Option<PaintId>,
    pub paint: Paint,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslStroke {
    pub id: Option<PaintId>,
    pub paint: Paint,
    pub width: DslScalar,
    pub dash: Option<Vec<f64>>,
    pub cap: Option<StrokeCap>,
    pub join: Option<StrokeJoin>,
    pub align: Option<StrokeAlign>,
}

impl DslStroke {
    fn basic(id: Option<PaintId>, paint: Paint, width: DslScalar) -> Self {
        Self {
            id,
            paint,
            width,
            dash: None,
            cap: None,
            join: None,
            align: None,
        }
    }
}

/// Drop-shadow surface of the modify/creation grammar:
/// `shadow(id?,#color,o(0.18),x(0),y(8),blur(24),spread(0))`.
#[derive(Clone, Debug, PartialEq)]
pub struct DslShadow {
    pub id: Option<EffectId>,
    pub color: Color,
    pub opacity: f64,
    pub x: f64,
    pub y: f64,
    pub blur: f64,
    pub spread: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslFont {
    pub family: String,
    pub size: DslScalar,
    pub weight: u16,
    pub align: TextAlign,
}

#[derive(Clone, Debug, PartialEq)]
pub enum DslDirective {
    Delete {
        target: EditTargetRef,
        /// Assets archive by default; `hard` requests an unreferenced hard
        /// delete. Ignored for non-asset targets.
        hard: bool,
        /// Export-profile deletes may name the surviving profile.
        replace_with: Option<String>,
        /// `if_exists` turns a missing target into an info diagnostic
        /// instead of a halt.
        if_exists: bool,
    },
    Parent {
        target: NodeId,
        new_parent: ParentRef,
        placement: DslParentPlacement,
    },
    Before {
        target: NodeId,
        before: NodeId,
    },
    After {
        target: NodeId,
        after: NodeId,
    },
    Clone {
        source: NodeId,
        new_root_id: NodeId,
        placement: RelativePlacement,
        slot_policy: CloneSlotPolicy,
        computed_policy: ComputedClonePolicy,
    },
    Replace {
        target: NodeId,
        replacement: NodeId,
        slot_policy: ReplaceSlotPolicy,
    },
    /// Block form: `replace(target)` followed by an indented, inline-authored
    /// replacement subtree with exactly one root. The subtree stages as a
    /// sibling of the target and swaps in atomically when the block closes.
    ReplaceBlock {
        target: NodeId,
        slot_policy: ReplaceSlotPolicy,
    },
    Ungroup {
        target: NodeId,
        allow_layout: bool,
    },
    Undo {
        label: Option<String>,
    },
    Redo {
        label: Option<String>,
    },
    Override {
        target: NodeId,
    },
    DesignSystem {
        id: String,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslModification {
    pub target_ref: String,
    pub properties: Vec<DslProperty>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DslDiagnostic {
    pub diagnostic: Diagnostic,
    pub span: SourceSpan,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceSpan {
    pub line: usize,
    pub column: usize,
    pub length: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DslHalt {
    pub line: usize,
    pub code: String,
}

#[derive(Clone, Debug)]
struct NormalizedLine {
    line_number: usize,
    text: String,
}

#[derive(Clone, Debug, PartialEq)]
struct DslParserContext {
    seen_node_ids: BTreeSet<NodeId>,
    previous_structural_depth: Option<usize>,
    previous_can_have_children: bool,
}

impl Default for DslParserContext {
    fn default() -> Self {
        Self {
            seen_node_ids: BTreeSet::new(),
            previous_structural_depth: None,
            previous_can_have_children: true,
        }
    }
}

impl DslParserContext {
    fn from_scene(scene: &Scene) -> Self {
        Self {
            seen_node_ids: scene.nodes.keys().cloned().collect(),
            previous_structural_depth: None,
            previous_can_have_children: true,
        }
    }

    fn advance_with_line(&mut self, line: &DslLine) {
        match &line.kind {
            DslLineKind::Page(_) => {
                self.previous_structural_depth = Some(line.indent);
                self.previous_can_have_children = true;
            }
            DslLineKind::Element(element) => {
                self.seen_node_ids.insert(element.id.clone());
                self.previous_structural_depth = Some(line.indent);
                self.previous_can_have_children = element.kind.can_have_children();
            }
            _ => {}
        }
    }
}

struct DslParser {
    lines: Vec<NormalizedLine>,
    diagnostics: Vec<DslDiagnostic>,
    halted_at: Option<DslHalt>,
    context: DslParserContext,
}

impl DslParser {
    fn new(source: &str) -> Self {
        Self::new_with_context(source, DslParserContext::default())
    }

    fn new_with_context(source: &str, context: DslParserContext) -> Self {
        Self {
            lines: normalized_lines(source),
            diagnostics: Vec::new(),
            halted_at: None,
            context,
        }
    }

    fn parse(self) -> DslParseOutput {
        self.parse_with_context().0
    }

    fn parse_with_context(mut self) -> (DslParseOutput, DslParserContext) {
        let mut document = DslDocument::default();

        for line in self.lines.clone() {
            let Some((indent, trimmed)) = self.parse_indent(&line) else {
                break;
            };

            let parsed = match self.parse_line(line.line_number, indent, trimmed) {
                Ok(kind) => kind,
                Err(diagnostic) => {
                    self.halt(diagnostic);
                    break;
                }
            };

            let is_structural = matches!(parsed, DslLineKind::Page(_) | DslLineKind::Element(_));
            if is_structural {
                if let Some(previous_depth) = self.context.previous_structural_depth {
                    if indent > previous_depth + 1 {
                        self.halt(error_diag(
                            line.line_number,
                            1,
                            trimmed.len().max(1),
                            "LUMD0302",
                            "cannot indent by more than one level",
                            "Add the missing parent line or reduce indentation to two spaces.",
                        ));
                        break;
                    }
                    if indent > previous_depth && !self.context.previous_can_have_children {
                        self.halt(error_diag(
                            line.line_number,
                            1,
                            trimmed.len().max(1),
                            "LUMD0304",
                            "leaf elements cannot contain children",
                            "Use frame, group, or autolayout as the parent container.",
                        ));
                        break;
                    }
                }

                if let DslLineKind::Element(element) = &parsed {
                    if self.context.seen_node_ids.contains(&element.id) {
                        self.halt(error_diag(
                            line.line_number,
                            1,
                            element.id.as_str().len(),
                            "LUMD0401",
                            format!("duplicate node id {}", element.id),
                            "Every DSL element must have a stable unique id.",
                        ));
                        break;
                    }
                }
            }

            let parsed_line = DslLine {
                line_number: line.line_number,
                indent,
                raw: line.text,
                kind: parsed,
            };
            self.context.advance_with_line(&parsed_line);
            document.lines.push(parsed_line);
        }

        (
            DslParseOutput {
                document,
                diagnostics: self.diagnostics,
                halted_at: self.halted_at,
            },
            self.context,
        )
    }

    fn parse_indent<'a>(&mut self, line: &'a NormalizedLine) -> Option<(usize, &'a str)> {
        let spaces = line.text.chars().take_while(|ch| *ch == ' ').count();
        if spaces % 2 != 0 {
            self.halt(error_diag(
                line.line_number,
                spaces + 1,
                1,
                "LUMD0301",
                "indentation must use two spaces per level",
                "Replace odd indentation with a multiple of two spaces.",
            ));
            return None;
        }

        Some((spaces / 2, line.text.trim_start()))
    }

    fn parse_line(
        &mut self,
        line_number: usize,
        indent: usize,
        trimmed: &str,
    ) -> Result<DslLineKind, DslDiagnostic> {
        if let Some(label) = trimmed.strip_prefix("//") {
            return Ok(DslLineKind::Checkpoint(label.trim().to_owned()));
        }
        if trimmed.starts_with('#') && is_modification_line(trimmed) {
            return self.parse_modification(line_number, trimmed);
        }
        if let Some(comment) = trimmed.strip_prefix('#') {
            return Ok(DslLineKind::Comment(comment.trim().to_owned()));
        }
        if trimmed.starts_with("page(") || trimmed == "page" || trimmed.starts_with("page ") {
            return self.parse_page(line_number, trimmed).map(DslLineKind::Page);
        }
        if let Some(directive) = self.parse_directive(line_number, trimmed)? {
            return Ok(DslLineKind::Directive(directive));
        }

        self.parse_element(line_number, indent, trimmed)
            .map(DslLineKind::Element)
    }

    fn parse_page(&mut self, line_number: usize, trimmed: &str) -> Result<DslPage, DslDiagnostic> {
        let tokens = split_top_level_whitespace(trimmed);
        let (id_token, property_tokens): (String, Vec<String>) = if tokens.len() == 1 {
            let call = parse_call(&tokens[0]).ok_or_else(|| {
                error_diag(
                    line_number,
                    1,
                    trimmed.len(),
                    "LUMD0201",
                    "page line must include a page id",
                    "Use page(page_a4) or page page_a4.",
                )
            })?;
            if call.name != "page" || call.args.len() != 1 {
                return Err(error_diag(
                    line_number,
                    1,
                    trimmed.len(),
                    "LUMD0202",
                    "page(...) expects exactly one id",
                    "Use page(page_a4).",
                ));
            }
            (call.args[0].clone(), Vec::new())
        } else {
            (tokens[1].clone(), tokens[2..].to_vec())
        };

        let id = parse_page_id(&id_token, line_number, 1)?;
        let mut preset = None;
        let mut size = None;
        for token in property_tokens {
            let call = parse_call(&token).ok_or_else(|| {
                error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0203",
                    format!("unsupported page property {token}"),
                    "Use preset(name,orientation), size(width,height,unit), or keep richer page config in scene metadata.",
                )
            })?;
            match call.name.as_str() {
                "preset" if !call.args.is_empty() => {
                    preset = Some(parse_page_preset(&call, line_number)?);
                }
                "size" => {
                    size = Some(parse_page_size(&call, line_number)?);
                }
                _ => {
                    return Err(error_diag(
                        line_number,
                        1,
                        token.len(),
                        "LUMD0204",
                        format!("unsupported page property {}", call.name),
                        "Use preset(a4,portrait), size(1080,1080,px), or omit page metadata from DSL.",
                    ));
                }
            }
        }

        Ok(DslPage { id, preset, size })
    }

    fn parse_element(
        &mut self,
        line_number: usize,
        _indent: usize,
        trimmed: &str,
    ) -> Result<DslElement, DslDiagnostic> {
        let tokens = split_top_level_whitespace(trimmed);
        if tokens.len() < 2 {
            return Err(error_diag(
                line_number,
                1,
                trimmed.len().max(1),
                "LUMD0205",
                "element line must include a kind and id",
                "Use either frame hero ... or hero fr ...",
            ));
        }

        let first_kind = element_kind_name(&tokens[0]);
        let (kind_token, id_token, mut rest): (&str, &str, Vec<String>) = if first_kind.is_some() {
            (&tokens[0], &tokens[1], tokens[2..].to_vec())
        } else if tokens.len() >= 2 && element_kind_name(&tokens[1]).is_some() {
            (&tokens[1], &tokens[0], tokens[2..].to_vec())
        } else {
            return Err(error_diag(
                line_number,
                1,
                tokens[0].len(),
                "LUMD0206",
                format!("unknown element kind in line: {trimmed}"),
                "Use frame/fr, group/gr, autolayout/al, rect/r, ellipse/e, line/l, text/t, image/img, vector/v, or instance.",
            ));
        };

        let id = parse_node_id(id_token, line_number, 1)?;
        let mut properties = parse_kind_call_properties(kind_token, line_number)?;
        let mut kind = parse_element_kind(kind_token, line_number)?;

        if matches!(kind, DslElementKind::Text { .. }) && !rest.is_empty() && is_quoted(&rest[0]) {
            kind = DslElementKind::Text {
                content: unquote(&rest.remove(0), line_number, 1)?,
            };
        }

        if matches!(kind, DslElementKind::AutoLayout { .. })
            && !rest.is_empty()
            && parse_direction(&rest[0]).is_some()
        {
            kind = DslElementKind::AutoLayout {
                direction: parse_direction(&rest.remove(0)).expect("checked direction"),
            };
        }

        for token in rest {
            let parsed = parse_property_token(&token, line_number, 1)?;
            properties.extend(parsed);
        }

        Ok(DslElement {
            id,
            kind,
            properties,
        })
    }

    fn parse_directive(
        &mut self,
        line_number: usize,
        trimmed: &str,
    ) -> Result<Option<DslDirective>, DslDiagnostic> {
        let Some(call) = parse_call(trimmed) else {
            return Ok(None);
        };

        let directive = match call.name.as_str() {
            "delete" => {
                if call.args.is_empty() || call.args.len() > 3 {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        "delete(...) expects a target and optional flags",
                        "Use delete(node_id), delete(page:id), delete(slot:key), delete(asset:id[, hard]), delete(export:name[, replace_with:other]), with optional if_exists.",
                    ));
                }
                let target = parse_directive_target(&call.args[0], line_number)?;
                let mut hard = false;
                let mut replace_with = None;
                let mut if_exists = false;
                for flag in call.args.iter().skip(1) {
                    let flag = flag.trim();
                    if flag == "hard" {
                        hard = true;
                    } else if flag == "if_exists" {
                        if_exists = true;
                    } else if let Some(name) = flag.strip_prefix("replace_with:") {
                        replace_with = Some(name.trim().to_owned());
                    } else {
                        return Err(error_diag(
                            line_number,
                            1,
                            trimmed.len(),
                            "LUMD0207",
                            format!("unknown delete flag {flag}"),
                            "Supported flags: hard, if_exists, replace_with:profile_name.",
                        ));
                    }
                }
                DslDirective::Delete {
                    target,
                    hard,
                    replace_with,
                    if_exists,
                }
            }
            "parent" => {
                if !(2..=3).contains(&call.args.len()) {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        "parent(...) expects target, parent, and optional index",
                        "Use parent(node_id,parent_id) or parent(node_id,page:page_a4,0).",
                    ));
                }
                let placement = if call.args.len() == 3 {
                    let arg = call.args[2].trim();
                    if let Some(anchor) = arg.strip_prefix("before:") {
                        DslParentPlacement::Before(parse_node_id(anchor, line_number, 1)?)
                    } else if let Some(anchor) = arg.strip_prefix("after:") {
                        DslParentPlacement::After(parse_node_id(anchor, line_number, 1)?)
                    } else if let Some(index) = arg.strip_prefix("index:") {
                        DslParentPlacement::Index(parse_usize(index, line_number, 1)?)
                    } else {
                        DslParentPlacement::Index(parse_usize(arg, line_number, 1)?)
                    }
                } else {
                    DslParentPlacement::Index(0)
                };
                DslDirective::Parent {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    new_parent: parse_parent_ref(&call.args[1], line_number)?,
                    placement,
                }
            }
            "before" => {
                expect_arg_count(&call, 2, line_number)?;
                DslDirective::Before {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    before: parse_node_id(&call.args[1], line_number, 1)?,
                }
            }
            "after" => {
                expect_arg_count(&call, 2, line_number)?;
                DslDirective::After {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    after: parse_node_id(&call.args[1], line_number, 1)?,
                }
            }
            "clone" => {
                if call.args.len() < 3 {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        "clone(...) expects source, new root id, and placement",
                        "Use clone(source_node,new_node,after:anchor), clone(source_node,new_node,before:anchor), or clone(source_node,new_node,parent:page_id,index:0).",
                    ));
                }
                let placement = parse_relative_placement(&call.args[2], line_number)?;
                let mut slot_policy = CloneSlotPolicy::Detach;
                let mut computed_policy = ComputedClonePolicy::Clear;
                let mut placement = placement;
                for arg in call.args.iter().skip(3) {
                    if let Some(index) = arg.strip_prefix("index:") {
                        let RelativePlacement::ParentIndex { parent, index: _ } = placement else {
                            return Err(error_diag(
                                line_number,
                                1,
                                arg.len(),
                                "LUMD0207",
                                "index:... can only be used with parent clone placement",
                                "Use clone(source,new_id,parent:page_id,index:1).",
                            ));
                        };
                        placement = RelativePlacement::ParentIndex {
                            parent,
                            index: parse_usize(index, line_number, 1)?,
                        };
                    } else if let Some(policy) = arg.strip_prefix("slots:") {
                        slot_policy = parse_clone_slot_policy(policy, line_number)?;
                    } else if let Some(policy) = arg.strip_prefix("computed:") {
                        computed_policy = parse_computed_clone_policy(policy, line_number)?;
                    } else {
                        return Err(error_diag(
                            line_number,
                            1,
                            arg.len(),
                            "LUMD0207",
                            "clone(...) received an unsupported option",
                            "Use slots:detach, slots:copy, slots:suffix:_variant, computed:clear, computed:preserve, or index:N.",
                        ));
                    }
                }
                DslDirective::Clone {
                    source: parse_node_id(&call.args[0], line_number, 1)?,
                    new_root_id: parse_node_id(&call.args[1], line_number, 1)?,
                    placement,
                    slot_policy,
                    computed_policy,
                }
            }
            "replace" => {
                if call.args.is_empty() || call.args.len() > 3 {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        "replace(...) expects a target and optional replacement",
                        "Use replace(old_node,new_node[,slots:preserve]) or replace(old_node[,slots:...]) followed by an indented replacement subtree.",
                    ));
                }
                // Single-target form (optionally with slots:) opens a block
                // whose indented elements author the replacement inline.
                let block_form = call.args.len() == 1
                    || (call.args.len() == 2 && call.args[1].trim().starts_with("slots:"));
                if block_form {
                    let slot_policy = call
                        .args
                        .get(1)
                        .map(|arg| {
                            parse_replace_slot_policy(
                                arg.trim().strip_prefix("slots:").unwrap_or(""),
                                line_number,
                            )
                        })
                        .transpose()?
                        .unwrap_or(ReplaceSlotPolicy::Detach);
                    return Ok(Some(DslDirective::ReplaceBlock {
                        target: parse_node_id(&call.args[0], line_number, 1)?,
                        slot_policy,
                    }));
                }
                let slot_policy = call
                    .args
                    .get(2)
                    .map(|arg| {
                        let Some(policy) = arg.strip_prefix("slots:") else {
                            return Err(error_diag(
                                line_number,
                                1,
                                arg.len(),
                                "LUMD0207",
                                "replace(...) option must be a slot policy",
                                "Use slots:detach or slots:preserve.",
                            ));
                        };
                        parse_replace_slot_policy(policy, line_number)
                    })
                    .transpose()?
                    .unwrap_or(ReplaceSlotPolicy::Detach);
                DslDirective::Replace {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    replacement: parse_node_id(&call.args[1], line_number, 1)?,
                    slot_policy,
                }
            }
            "ungroup" => {
                if call.args.is_empty() || call.args.len() > 2 {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        "ungroup(...) expects a group id and optional allow_layout",
                        "Use ungroup(group_id) or ungroup(stack, allow_layout).",
                    ));
                }
                let allow_layout = call
                    .args
                    .get(1)
                    .map(|flag| flag.trim() == "allow_layout")
                    .unwrap_or(false);
                if call.args.len() == 2 && !allow_layout {
                    return Err(error_diag(
                        line_number,
                        1,
                        trimmed.len(),
                        "LUMD0207",
                        format!("unknown ungroup flag {}", call.args[1].trim()),
                        "The only supported flag is allow_layout.",
                    ));
                }
                DslDirective::Ungroup {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    allow_layout,
                }
            }
            "undo" => DslDirective::Undo {
                label: call.args.first().map(|arg| unquote_lossy(arg)),
            },
            "redo" => DslDirective::Redo {
                label: call.args.first().map(|arg| unquote_lossy(arg)),
            },
            "override" => {
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::Override {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                }
            }
            "ds" => {
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::DesignSystem {
                    id: unquote_lossy(&call.args[0]),
                }
            }
            _ => return Ok(None),
        };

        Ok(Some(directive))
    }

    fn parse_modification(
        &mut self,
        line_number: usize,
        trimmed: &str,
    ) -> Result<DslLineKind, DslDiagnostic> {
        let tokens = split_top_level_whitespace(trimmed);
        if tokens.is_empty() {
            return Err(error_diag(
                line_number,
                1,
                1,
                "LUMD0208",
                "empty modification line",
                "Use #ref p(x,y), or use structured operations for complex patching.",
            ));
        }

        let mut properties = Vec::new();
        for token in tokens.iter().skip(1) {
            properties.extend(parse_property_token(token, line_number, 1)?);
        }

        Ok(DslLineKind::Modification(DslModification {
            target_ref: tokens[0].clone(),
            properties,
        }))
    }

    fn halt(&mut self, diagnostic: DslDiagnostic) {
        self.halted_at = Some(DslHalt {
            line: diagnostic.span.line,
            code: diagnostic.diagnostic.code.clone(),
        });
        self.diagnostics.push(diagnostic);
    }
}

/// Active inline block replace: the staged subtree authors as a sibling of
/// the target and swaps in atomically when the block closes. The snapshot
/// makes the whole directive atomic — any failure inside the block rolls
/// the draft scene and emitted operations back to the block start.
struct ReplaceBlockState {
    target: NodeId,
    slot_policy: ReplaceSlotPolicy,
    root: Option<NodeId>,
    scene_snapshot: Scene,
    ops_checkpoint: usize,
    stack_depth: usize,
}

struct DslCompiler<'a> {
    document: DslDocument,
    operations: Vec<Operation>,
    diagnostics: Vec<DslDiagnostic>,
    halted_at: Option<DslHalt>,
    checkpoint_label: Option<String>,
    /// Active `override(root)` patch group: indented modify lines must
    /// target the root or its descendants until a flat line ends the group.
    override_root: Option<NodeId>,
    replace_block: Option<ReplaceBlockState>,
    history: Option<&'a dyn DslHistoryAdapter>,
    scene: &'a mut Scene,
    parent_stack: &'a mut Vec<ParentFrame>,
    emitted_slots: &'a mut BTreeMap<SlotKey, SlotId>,
}

impl<'a> DslCompiler<'a> {
    fn new(
        document: DslDocument,
        diagnostics: Vec<DslDiagnostic>,
        scene: &'a mut Scene,
        parent_stack: &'a mut Vec<ParentFrame>,
        emitted_slots: &'a mut BTreeMap<SlotKey, SlotId>,
        history: Option<&'a dyn DslHistoryAdapter>,
    ) -> Self {
        Self {
            document,
            operations: Vec::new(),
            diagnostics,
            halted_at: None,
            checkpoint_label: None,
            override_root: None,
            replace_block: None,
            history,
            scene,
            parent_stack,
            emitted_slots,
        }
    }

    fn compile(&mut self, parse_halt: Option<DslHalt>) -> DslCompileOutput {
        let mut last_line_number = 1;
        for line in self.document.lines.clone() {
            if parse_halt
                .as_ref()
                .is_some_and(|halt| line.line_number >= halt.line)
            {
                break;
            }
            last_line_number = line.line_number;

            if let Err(diagnostic) = self.lower_line(&line) {
                self.rollback_replace_block();
                self.halted_at = Some(DslHalt {
                    line: diagnostic.span.line,
                    code: diagnostic.diagnostic.code.clone(),
                });
                self.diagnostics.push(diagnostic);
                break;
            }
        }

        if self.halted_at.is_none() && parse_halt.is_none() {
            if let Err(diagnostic) = self.finalize_replace_block(last_line_number, 1) {
                self.halted_at = Some(DslHalt {
                    line: diagnostic.span.line,
                    code: diagnostic.diagnostic.code.clone(),
                });
                self.diagnostics.push(diagnostic);
            }
        }

        DslCompileOutput {
            document: self.document.clone(),
            operations: self.operations.clone(),
            diagnostics: self.diagnostics.clone(),
            halted_at: self.halted_at.clone().or(parse_halt),
            checkpoint_label: self.checkpoint_label.clone(),
        }
    }

    fn lower_line(&mut self, line: &DslLine) -> Result<(), DslDiagnostic> {
        // A flat (unindented) line ends any active override patch group or
        // replace block; the directives themselves re-open them below.
        if line.indent == 0 {
            self.override_root = None;
            self.finalize_replace_block(line.line_number, line.raw.len().max(1))?;
        }
        match &line.kind {
            DslLineKind::Comment(_) => Ok(()),
            DslLineKind::Checkpoint(label) => {
                if !label.is_empty() {
                    self.checkpoint_label = Some(label.clone());
                }
                Ok(())
            }
            DslLineKind::Page(page) => self.lower_page(line, page),
            DslLineKind::Element(element) => self.lower_element(line, element),
            DslLineKind::Directive(directive) => self.lower_directive(line, directive),
            DslLineKind::Modification(modification) => self.lower_modification(line, modification),
        }
    }

    fn lower_page(&mut self, line: &DslLine, page: &DslPage) -> Result<(), DslDiagnostic> {
        if line.indent != 0 {
            return Err(error_diag(
                line.line_number,
                1,
                line.raw.len().max(1),
                "LUMD0305",
                "page lines must be top-level",
                "Move page(...) to indentation level 0.",
            ));
        }

        let fallback_preset = page.preset.clone().unwrap_or_else(|| DslPagePreset {
            preset: PagePreset::A4,
            orientation: default_orientation_for_preset(&PagePreset::A4),
        });

        let size = if let Some(size) = &page.size {
            normalize_page_size(PageSizeInput::new(
                size.width,
                size.height,
                size.unit.clone(),
                page.preset
                    .as_ref()
                    .map(|preset| preset.preset.clone())
                    .or(Some(PagePreset::Custom)),
                orientation_for_dimensions(size.width, size.height),
            ))
        } else {
            page_size_for_preset(&fallback_preset.preset, &fallback_preset.orientation)
        };

        let page_model = Page {
            id: page.id.clone(),
            name: page.id.to_string(),
            size,
            children: Vec::new(),
            bleed: None,
            safe_area: None,
            background: Vec::new(),
        };

        self.emit_operation(line, Operation::AddPage { page: page_model })?;
        self.parent_stack.clear();
        self.parent_stack.push(ParentFrame {
            indent: line.indent,
            parent: ParentRef::Page(page.id.clone()),
        });
        Ok(())
    }

    fn lower_element(&mut self, line: &DslLine, element: &DslElement) -> Result<(), DslDiagnostic> {
        if let Some(state) = &self.replace_block {
            // Only one root may stage inside a replace block: a second
            // element at the root's indentation level is rejected.
            if let Some(root) = &state.root {
                let root_indent = self
                    .parent_stack
                    .iter()
                    .find(|frame| matches!(&frame.parent, ParentRef::Node(id) if id == root))
                    .map(|frame| frame.indent);
                if Some(line.indent) <= root_indent || root_indent.is_none() {
                    return Err(error_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0914",
                        "block replace requires exactly one replacement root",
                        "Nest additional elements under the single replacement root.",
                    ));
                }
            }
        }
        while self
            .parent_stack
            .last()
            .is_some_and(|frame| frame.indent >= line.indent)
        {
            self.parent_stack.pop();
        }

        let parent = self
            .parent_stack
            .last()
            .map(|frame| frame.parent.clone())
            .ok_or_else(|| {
                error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0402",
                    "node appears before or outside a page/container",
                    "Create a top-level page(...) and indent nodes under it.",
                )
            })?;

        let mut node = node_from_element(element, line.line_number)?;
        let mut property_diagnostics = Vec::new();
        apply_properties(
            &mut node,
            &element.properties,
            line.line_number,
            &mut property_diagnostics,
        );

        let index = children_len_for_parent(self.scene, &parent, line)?;

        self.emit_operation(
            line,
            Operation::InsertNode {
                parent,
                index,
                node: node.clone(),
            },
        )?;

        let mut seen_slot_keys = BTreeSet::new();
        for property in &element.properties {
            if let DslProperty::Slot(slot_key) = property {
                if seen_slot_keys.insert(slot_key.clone()) {
                    self.emit_slot_binding(line, slot_key, &node)?;
                }
            }
        }

        self.diagnostics.extend(property_diagnostics);

        if element.kind.can_have_children() {
            self.parent_stack.push(ParentFrame {
                indent: line.indent,
                parent: ParentRef::Node(element.id.clone()),
            });
        }

        if let Some(state) = &mut self.replace_block {
            if state.root.is_none() {
                state.root = Some(element.id.clone());
            }
        }

        Ok(())
    }

    fn lower_directive(
        &mut self,
        line: &DslLine,
        directive: &DslDirective,
    ) -> Result<(), DslDiagnostic> {
        match directive {
            DslDirective::Delete {
                target,
                hard,
                replace_with,
                if_exists,
            } => {
                if *if_exists && resolve_edit_target(self.scene, target).is_err() {
                    self.diagnostics.push(warning_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0915",
                        format!(
                            "delete target {:?} does not exist; skipped (if_exists)",
                            target
                        ),
                        "Remove if_exists to make a missing target a hard error.",
                    ));
                    return Ok(());
                }
                let batch = match target {
                    EditTargetRef::Node(node_id) => build_safe_delete(self.scene, node_id.clone()),
                    EditTargetRef::Page(page_id) => {
                        build_safe_delete_page(self.scene, page_id.clone())
                    }
                    EditTargetRef::Slot(_) | EditTargetRef::SlotKey(_) => {
                        build_safe_delete_slot(self.scene, target.clone())
                    }
                    EditTargetRef::Asset(asset_id) => {
                        if *hard {
                            build_hard_delete_asset(self.scene, asset_id.clone())
                        } else {
                            build_archive_asset(self.scene, asset_id.clone())
                        }
                    }
                    EditTargetRef::ExportProfile(name) => {
                        build_delete_export_profile(self.scene, name.clone(), replace_with.clone())
                    }
                    EditTargetRef::Document => Err(EditError::new(
                        crate::EditErrorKind::UnsupportedTarget,
                        "the document itself cannot be deleted through DSL",
                    )),
                }
                .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Parent {
                target,
                new_parent,
                placement,
            } => {
                let index = match placement {
                    DslParentPlacement::Index(index) => *index,
                    DslParentPlacement::Before(anchor) | DslParentPlacement::After(anchor) => {
                        // Resolve the anchor inside the destination parent
                        // with detach-aware math: the target leaves its slot
                        // before reinsertion, so it is excluded first.
                        let mut siblings = children_ids_for_parent(self.scene, new_parent, line)?;
                        siblings.retain(|id| id != target);
                        let anchor_index = siblings
                            .iter()
                            .position(|id| id == anchor)
                            .ok_or_else(|| {
                                error_diag(
                                    line.line_number,
                                    1,
                                    line.raw.len().max(1),
                                    "LUMD0900",
                                    format!(
                                        "anchor {} is not a child of the destination parent",
                                        anchor
                                    ),
                                    "Use before:/after: anchors that already live inside the destination parent.",
                                )
                            })?;
                        if matches!(placement, DslParentPlacement::After(_)) {
                            anchor_index + 1
                        } else {
                            anchor_index
                        }
                    }
                };
                let batch =
                    build_move_to_parent(self.scene, target.clone(), new_parent.clone(), index)
                        .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Before { target, before } => {
                let batch = build_move_before(self.scene, target.clone(), before.clone())
                    .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::After { target, after } => {
                let batch = build_move_after(self.scene, target.clone(), after.clone())
                    .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Clone {
                source,
                new_root_id,
                placement,
                slot_policy,
                computed_policy,
            } => {
                let batch = build_clone_subtree(
                    self.scene,
                    CloneSubtreeRequest {
                        source: source.clone(),
                        new_root_id: new_root_id.clone(),
                        placement: placement.clone(),
                        slot_policy: slot_policy.clone(),
                        computed_policy: computed_policy.clone(),
                    },
                )
                .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Replace {
                target,
                replacement,
                slot_policy,
            } => {
                let batch = build_replace_node(
                    self.scene,
                    ReplaceNodeRequest {
                        target: target.clone(),
                        replacement: replacement.clone(),
                        slot_policy: slot_policy.clone(),
                    },
                )
                .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::ReplaceBlock {
                target,
                slot_policy,
            } => {
                let parent = self.scene.parent_of(target).ok_or_else(|| {
                    error_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0901",
                        format!("replace target {} does not exist or has no parent", target),
                        "Use replace(target) with an existing node inside a page.",
                    )
                })?;
                self.replace_block = Some(ReplaceBlockState {
                    target: target.clone(),
                    slot_policy: slot_policy.clone(),
                    root: None,
                    scene_snapshot: self.scene.clone(),
                    ops_checkpoint: self.operations.len(),
                    stack_depth: self.parent_stack.len(),
                });
                // The staged subtree authors as a sibling inside the
                // target's parent; the swap happens when the block closes.
                self.parent_stack.push(ParentFrame { indent: 0, parent });
                Ok(())
            }
            DslDirective::Ungroup {
                target,
                allow_layout,
            } => {
                let batch = build_ungroup(self.scene, target.clone(), *allow_layout)
                    .map_err(|error| edit_error_diag(line, &error))?;
                self.emit_edit_batch(line, batch.operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Override { target } => {
                if !self.scene.nodes.contains_key(target) {
                    return Err(error_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0901",
                        format!("override root {} does not exist", target),
                        "Use override(root_id) with an existing node, typically a fresh clone root.",
                    ));
                }
                self.override_root = Some(target.clone());
                Ok(())
            }
            DslDirective::Undo { label } | DslDirective::Redo { label } => {
                let Some(history) = self.history else {
                    return Err(error_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0916",
                        "undo/redo require a history context",
                        "Use the document history API (POST /undo, /redo, /revert) or compile through a session with a history adapter.",
                    ));
                };
                let is_undo = matches!(
                    &line.kind,
                    DslLineKind::Directive(DslDirective::Undo { .. })
                );
                let operations = if is_undo {
                    history.undo_operations(label.as_deref())
                } else {
                    history.redo_operations(label.as_deref())
                };
                let Some(operations) = operations else {
                    return Err(error_diag(
                        line.line_number,
                        1,
                        line.raw.len().max(1),
                        "LUMD0917",
                        format!(
                            "no {} history entry matches {:?}",
                            if is_undo { "undoable" } else { "redoable" },
                            label
                        ),
                        "Check checkpoint labels with the history API before undoing.",
                    ));
                };
                self.emit_edit_batch(line, operations)?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::DesignSystem { .. } => Err(error_diag(
                line.line_number,
                1,
                line.raw.len().max(1),
                "LUMD0700",
                "directive is parsed but not lowered by this workstream",
                "Design-system switching belongs to the brand-kit workstream.",
            )),
        }
    }

    fn lower_modification(
        &mut self,
        line: &DslLine,
        modification: &DslModification,
    ) -> Result<(), DslDiagnostic> {
        let target = parse_edit_target_ref(&modification.target_ref, line)?;
        if let (Some(root), true) = (self.override_root.clone(), line.indent > 0) {
            let in_root = match &target {
                EditTargetRef::Node(node_id) => {
                    node_id == &root || self.scene.descendants_of(&root).contains(node_id)
                }
                _ => false,
            };
            if !in_root {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0913",
                    format!(
                        "override group for {} cannot modify target {:?}",
                        root, target
                    ),
                    "Inside override(root), only the root and its descendants may be modified.",
                ));
            }
        }
        let patch =
            edit_patch_from_properties(self.scene, &target, &modification.properties, line)?;
        let batch = build_modify_operations(self.scene, target, patch)
            .map_err(|error| edit_error_diag(line, &error))?;
        self.emit_edit_batch(line, batch.operations)
    }

    fn emit_slot_binding(
        &mut self,
        line: &DslLine,
        slot_key: &SlotKey,
        node: &Node,
    ) -> Result<(), DslDiagnostic> {
        let slot_id = if let Some(slot_id) = self.emitted_slots.get(slot_key) {
            slot_id.clone()
        } else {
            let slot_id = slot_id_for_key(slot_key);
            let mut slot =
                Slot::text_short(slot_id.clone(), slot_key.clone(), slot_key.to_string());
            slot.content_type = match node.kind {
                NodeKind::Image(_) => crate::ContentType::Image,
                NodeKind::Text(_) => crate::ContentType::TextShort,
                _ => crate::ContentType::TextShort,
            };
            if let NodeKind::Text(text) = &node.kind {
                slot.placeholder = Some(text.content.clone());
            }
            self.emit_operation(line, Operation::UpsertSlot { slot })?;
            self.emitted_slots.insert(slot_key.clone(), slot_id.clone());
            slot_id
        };

        self.emit_operation(
            line,
            Operation::BindNodeToSlot {
                slot_id,
                node_id: node.id.clone(),
            },
        )
    }

    fn emit_operation(
        &mut self,
        line: &DslLine,
        operation: Operation,
    ) -> Result<(), DslDiagnostic> {
        self.scene
            .apply_operation(operation.clone())
            .map_err(|error| operation_error_diag(line, &error))?;
        self.operations.push(operation);
        Ok(())
    }

    fn emit_edit_batch(
        &mut self,
        line: &DslLine,
        operations: Vec<Operation>,
    ) -> Result<(), DslDiagnostic> {
        for operation in operations {
            self.emit_operation(line, operation)?;
        }
        Ok(())
    }

    /// Close an active inline replace block: validate exactly one staged
    /// root, swap it into the target's parent/index, and remove the target.
    /// Any failure rolls the whole block back so the directive is atomic.
    fn finalize_replace_block(
        &mut self,
        line_number: usize,
        length: usize,
    ) -> Result<(), DslDiagnostic> {
        let Some(state) = self.replace_block.take() else {
            return Ok(());
        };
        let Some(root) = state.root.clone() else {
            self.restore_replace_snapshot(state);
            return Err(error_diag(
                line_number,
                1,
                length,
                "LUMD0914",
                "block replace requires exactly one replacement root",
                "Indent one root element (with children) under replace(target).",
            ));
        };
        self.parent_stack.truncate(state.stack_depth);
        let swap = build_replace_node(
            self.scene,
            ReplaceNodeRequest {
                target: state.target.clone(),
                replacement: root,
                slot_policy: state.slot_policy.clone(),
            },
        );
        let swap = match swap {
            Ok(batch) => batch,
            Err(error) => {
                let diagnostic = error_diag(
                    line_number,
                    1,
                    length,
                    "LUMD0914",
                    format!(
                        "block replace of {} failed: {} {}",
                        state.target,
                        error.kind.code(),
                        error.message
                    ),
                    "Repair the replacement subtree; the whole block was rolled back.",
                );
                self.restore_replace_snapshot(state);
                return Err(diagnostic);
            }
        };
        for operation in swap.operations {
            if let Err(error) = self.scene.apply_operation(operation.clone()) {
                let diagnostic = operation_error_diag_at(line_number, length, &error);
                self.restore_replace_snapshot(state);
                return Err(diagnostic);
            }
            self.operations.push(operation);
        }
        self.prune_parent_stack();
        Ok(())
    }

    fn restore_replace_snapshot(&mut self, state: ReplaceBlockState) {
        *self.scene = state.scene_snapshot;
        self.operations.truncate(state.ops_checkpoint);
        self.parent_stack.truncate(state.stack_depth);
    }

    fn rollback_replace_block(&mut self) {
        if let Some(state) = self.replace_block.take() {
            self.restore_replace_snapshot(state);
        }
    }

    fn prune_parent_stack(&mut self) {
        let scene = &*self.scene;
        self.parent_stack
            .retain(|frame| parent_can_receive_children(scene, &frame.parent));
    }
}

#[derive(Clone, Debug, PartialEq)]
struct ParentFrame {
    indent: usize,
    parent: ParentRef,
}

fn lower_halt_before_parse_halt<'a>(
    output_halt: Option<&'a DslHalt>,
    parse_halt: Option<&DslHalt>,
) -> Option<&'a DslHalt> {
    output_halt.filter(|halt| {
        parse_halt
            .map(|parse_halt| halt.line < parse_halt.line || halt.code != parse_halt.code)
            .unwrap_or(true)
    })
}

fn parser_context_after_lines(
    starting_context: &DslParserContext,
    lines: &[DslLine],
    halt_line: usize,
) -> DslParserContext {
    let mut context = starting_context.clone();
    for line in lines {
        if line.line_number >= halt_line {
            break;
        }
        context.advance_with_line(line);
    }
    context
}

fn children_ids_for_parent(
    scene: &Scene,
    parent: &ParentRef,
    line: &DslLine,
) -> Result<Vec<NodeId>, DslDiagnostic> {
    match parent {
        ParentRef::Page(page_id) => scene
            .pages
            .get(page_id)
            .map(|page| page.children.clone())
            .ok_or_else(|| {
                operation_error_diag(
                    line,
                    &OperationError::new(
                        "op.page_missing",
                        format!("parent page {} does not exist", page_id),
                    ),
                )
            }),
        ParentRef::Node(node_id) => scene
            .nodes
            .get(node_id)
            .map(|node| node.children.clone())
            .ok_or_else(|| {
                operation_error_diag(
                    line,
                    &OperationError::new(
                        "op.node_missing",
                        format!("parent node {} does not exist", node_id),
                    ),
                )
            }),
    }
}

fn children_len_for_parent(
    scene: &Scene,
    parent: &ParentRef,
    line: &DslLine,
) -> Result<usize, DslDiagnostic> {
    match parent {
        ParentRef::Page(page_id) => scene
            .pages
            .get(page_id)
            .map(|page| page.children.len())
            .ok_or_else(|| {
                operation_error_diag(
                    line,
                    &OperationError::new(
                        "op.page_missing",
                        format!("parent page {} does not exist", page_id),
                    ),
                )
            }),
        ParentRef::Node(node_id) => {
            let node = scene.nodes.get(node_id).ok_or_else(|| {
                operation_error_diag(
                    line,
                    &OperationError::new(
                        "op.node_missing",
                        format!("parent node {} does not exist", node_id),
                    ),
                )
            })?;
            if !node.kind.can_have_children() {
                return Err(operation_error_diag(
                    line,
                    &OperationError::new(
                        "op.leaf_parent",
                        format!("node {} cannot have children", node_id),
                    ),
                ));
            }
            Ok(node.children.len())
        }
    }
}

fn parent_can_receive_children(scene: &Scene, parent: &ParentRef) -> bool {
    match parent {
        ParentRef::Page(page_id) => scene.pages.contains_key(page_id),
        ParentRef::Node(node_id) => scene
            .nodes
            .get(node_id)
            .map(|node| node.kind.can_have_children())
            .unwrap_or(false),
    }
}

fn operation_error_diag(line: &DslLine, error: &OperationError) -> DslDiagnostic {
    operation_error_diag_at(line.line_number, line.raw.len().max(1), error)
}

fn operation_error_diag_at(
    line_number: usize,
    length: usize,
    error: &OperationError,
) -> DslDiagnostic {
    error_diag(
        line_number,
        1,
        length,
        "LUMD0800",
        format!("operation {} failed during DSL lowering: {}", error.code, error.message),
        "The DSL line parsed, but applying the corresponding structured operation failed against the current draft scene.",
    )
}

fn edit_error_diag(line: &DslLine, error: &EditError) -> DslDiagnostic {
    error_diag(
        line.line_number,
        1,
        line.raw.len().max(1),
        "LUMD0900",
        format!(
            "targeted edit {} failed: {}",
            error.kind.code(),
            error.message
        ),
        "Repair the target reference or use properties compatible with the target kind.",
    )
}

fn parse_edit_target_ref(source: &str, line: &DslLine) -> Result<EditTargetRef, DslDiagnostic> {
    let Some(target) = source.strip_prefix('#') else {
        return Err(error_diag(
            line.line_number,
            1,
            source.len().max(1),
            "LUMD0901",
            "modify target must start with #",
            "Use #node_id, #page:page_id, #slot:key, #slot_id:id, #asset:id, or #document.",
        ));
    };
    if target == "document" {
        return Ok(EditTargetRef::Document);
    }
    if let Some(page_id) = target.strip_prefix("page:") {
        return Ok(EditTargetRef::Page(parse_page_id(
            page_id,
            line.line_number,
            1,
        )?));
    }
    if let Some(slot_key) = target.strip_prefix("slot:") {
        return Ok(EditTargetRef::SlotKey(parse_slot_key(
            slot_key,
            line.line_number,
            1,
        )?));
    }
    if let Some(slot_id) = target.strip_prefix("slot_id:") {
        return Ok(EditTargetRef::Slot(parse_slot_id(
            slot_id,
            line.line_number,
            1,
        )?));
    }
    if let Some(asset_id) = target.strip_prefix("asset:") {
        return Ok(EditTargetRef::Asset(parse_asset_id(
            asset_id,
            line.line_number,
            1,
        )?));
    }
    if let Some(name) = target.strip_prefix("export:") {
        return Ok(EditTargetRef::ExportProfile(name.to_owned()));
    }
    Ok(EditTargetRef::Node(parse_node_id(
        target,
        line.line_number,
        1,
    )?))
}

fn edit_patch_from_properties(
    scene: &Scene,
    target: &EditTargetRef,
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<EditPatch, DslDiagnostic> {
    match target {
        EditTargetRef::Node(node_id) => {
            let patch = node_edit_patch_from_properties(scene, node_id, properties, line)?;
            Ok(EditPatch::Node(patch))
        }
        EditTargetRef::Page(_) => {
            let patch = page_edit_patch_from_properties(properties, line)?;
            Ok(EditPatch::Page(patch))
        }
        EditTargetRef::Slot(_) | EditTargetRef::SlotKey(_) => {
            let patch = slot_edit_patch_from_properties(properties, line)?;
            Ok(EditPatch::Slot(patch))
        }
        EditTargetRef::Asset(_) => {
            let patch = asset_edit_patch_from_properties(properties, line)?;
            Ok(EditPatch::Asset(patch))
        }
        EditTargetRef::Document => {
            let patch = document_edit_patch_from_properties(properties, line)?;
            Ok(EditPatch::Document(patch))
        }
        EditTargetRef::ExportProfile(_) => {
            let patch = export_profile_edit_patch_from_properties(properties, line)?;
            Ok(EditPatch::ExportProfile(patch))
        }
    }
}

fn document_edit_patch_from_properties(
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<DocumentPatch, DslDiagnostic> {
    let mut patch = DocumentPatch::default();
    for property in properties {
        match property {
            DslProperty::Name(name) => patch.title = FieldPatch::Set(name.clone()),
            DslProperty::ArtifactType(artifact_type) => {
                patch.artifact_type = OptionalFieldPatch::Set(artifact_type.clone())
            }
            DslProperty::DocumentMedium(medium) => {
                patch.medium = OptionalFieldPatch::Set(medium.clone())
            }
            DslProperty::DocumentBrandKit(brand_kit_id, version) => {
                patch.brand_kit = OptionalFieldPatch::Set(BrandKitRef {
                    id: brand_kit_id.clone().into(),
                    version: *version,
                })
            }
            _ => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for #document modify targets",
                    "Use name(...), artifact_type(...), medium(...), or brand_kit(id, version).",
                ));
            }
        }
    }
    Ok(patch)
}

fn export_profile_edit_patch_from_properties(
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<ExportProfileEditPatch, DslDiagnostic> {
    let mut patch = ExportProfileEditPatch::default();
    for property in properties {
        match property {
            DslProperty::ExportFormatValue(format) => {
                patch.format = FieldPatch::Set(format.clone())
            }
            DslProperty::ExportPdfIntent(intent) => {
                patch.pdf_intent = OptionalFieldPatch::Set(intent.clone())
            }
            DslProperty::ExportRasterScale { scale, dpi } => {
                patch.raster = OptionalFieldPatch::Set(RasterScale {
                    scale: *scale,
                    dpi: *dpi,
                })
            }
            DslProperty::ExportIncludeBleed(include_bleed) => {
                patch.include_bleed = FieldPatch::Set(*include_bleed)
            }
            DslProperty::ExportEmbedFonts(embed_fonts) => {
                patch.embed_fonts = FieldPatch::Set(*embed_fonts)
            }
            _ => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for #export:name modify targets",
                    "Use format(...), pdf_intent(...), raster_scale(...), include_bleed(...), or embed_fonts(...).",
                ));
            }
        }
    }
    Ok(patch)
}

/// Placement inside a `parent(...)` destination: a fixed index or a
/// position relative to an anchor child of the destination.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DslParentPlacement {
    Index(usize),
    Before(NodeId),
    After(NodeId),
}

/// Parse a directive target argument: bare ids are nodes; prefixed forms
/// mirror the `#`-target grammar of modify lines (page:, slot:, slot_id:,
/// asset:, export:).
fn parse_directive_target(
    source: &str,
    line_number: usize,
) -> Result<EditTargetRef, DslDiagnostic> {
    let target = source.trim();
    if let Some(page_id) = target.strip_prefix("page:") {
        return Ok(EditTargetRef::Page(parse_page_id(page_id, line_number, 1)?));
    }
    if let Some(slot_key) = target.strip_prefix("slot:") {
        return Ok(EditTargetRef::SlotKey(parse_slot_key(
            slot_key,
            line_number,
            1,
        )?));
    }
    if let Some(slot_id) = target.strip_prefix("slot_id:") {
        return Ok(EditTargetRef::Slot(parse_slot_id(slot_id, line_number, 1)?));
    }
    if let Some(asset_id) = target.strip_prefix("asset:") {
        return Ok(EditTargetRef::Asset(parse_asset_id(
            asset_id,
            line_number,
            1,
        )?));
    }
    if let Some(name) = target.strip_prefix("export:") {
        return Ok(EditTargetRef::ExportProfile(name.to_owned()));
    }
    Ok(EditTargetRef::Node(parse_node_id(target, line_number, 1)?))
}

fn parse_medium(source: &str, line_number: usize, column: usize) -> Result<Medium, DslDiagnostic> {
    match source.trim() {
        "print" => Ok(Medium::Print),
        "digital" => Ok(Medium::Digital),
        "email" => Ok(Medium::Email),
        "direct_mail" => Ok(Medium::DirectMail),
        "ad" => Ok(Medium::Ad),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0211",
            format!("unknown medium {other}"),
            "Use medium(print|digital|email|direct_mail|ad).",
        )),
    }
}

fn parse_export_format(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<ExportFormat, DslDiagnostic> {
    match source.trim() {
        "svg" => Ok(ExportFormat::Svg),
        "png" => Ok(ExportFormat::Png),
        "pdf" => Ok(ExportFormat::Pdf),
        "figma_manifest" => Ok(ExportFormat::FigmaManifest),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0211",
            format!("unknown export format {other}"),
            "Use format(svg|png|pdf|figma_manifest).",
        )),
    }
}

fn parse_pdf_intent(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<PdfIntent, DslDiagnostic> {
    match source.trim() {
        "preview" => Ok(PdfIntent::Preview),
        "print" => Ok(PdfIntent::Print),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0211",
            format!("unknown pdf intent {other}"),
            "Use pdf_intent(preview|print).",
        )),
    }
}

fn node_edit_patch_from_properties(
    scene: &Scene,
    node_id: &NodeId,
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<NodeEditPatch, DslDiagnostic> {
    let current = scene.nodes.get(node_id).ok_or_else(|| {
        error_diag(
            line.line_number,
            1,
            node_id.as_str().len(),
            "LUMD0901",
            format!("target node {} does not exist", node_id),
            "Use a node id from the current scene.",
        )
    })?;
    let mut patch = NodeEditPatch::default();
    let mut next_transform = current.transform.clone();
    let mut transform_changed = false;
    let mut next_corner = current.corner.clone();
    let mut corner_changed = false;
    let mut next_layout = current.layout.clone().unwrap_or_default();
    let mut layout_changed = false;
    let mut fills = Vec::new();
    let mut strokes = Vec::new();
    let mut effect_edits = Vec::new();
    let mut fill_index = 0;
    let mut stroke_index = 0;
    let mut shadow_index = 0;
    let mut text_patch = TextEditPatch::default();
    let mut has_text_patch = false;

    for property in properties {
        match property {
            DslProperty::Position(x, y) => {
                next_transform.x = *x;
                next_transform.y = *y;
                transform_changed = true;
            }
            DslProperty::Rotation(rotation) => {
                next_transform.rotation = *rotation;
                transform_changed = true;
            }
            DslProperty::Skew(skew_x, skew_y) => {
                next_transform.skew_x = *skew_x;
                next_transform.skew_y = *skew_y;
                transform_changed = true;
            }
            DslProperty::Flip { x, y } => {
                next_transform.flip_x = *x;
                next_transform.flip_y = *y;
                transform_changed = true;
            }
            DslProperty::Size(width, height) => {
                patch.size = FieldPatch::Set(SizeSpec {
                    width: dimension_to_scene(width),
                    height: dimension_to_scene(height),
                });
            }
            DslProperty::TextContent(content) => {
                text_patch.content = FieldPatch::Set(content.clone());
                has_text_patch = true;
            }
            DslProperty::TextAppend(suffix) | DslProperty::TextPrepend(suffix) => {
                let base = match &text_patch.content {
                    FieldPatch::Set(value) => value.clone(),
                    FieldPatch::Unchanged => match &current.kind {
                        NodeKind::Text(text) => text.content.clone(),
                        _ => {
                            return Err(error_diag(
                                line.line_number,
                                1,
                                line.raw.len().max(1),
                                "LUMD0903",
                                "append/prepend only apply to text nodes",
                                "Target a text node, or use text(...) to replace content.",
                            ));
                        }
                    },
                };
                let next = if matches!(property, DslProperty::TextAppend(_)) {
                    format!("{base}{suffix}")
                } else {
                    format!("{suffix}{base}")
                };
                text_patch.content = FieldPatch::Set(next);
                has_text_patch = true;
            }
            DslProperty::Name(name) => {
                patch.name = OptionalFieldPatch::Set(name.clone());
            }
            DslProperty::Fill(fill) => {
                let id = fill.id.clone().unwrap_or_else(|| {
                    fill_index += 1;
                    PaintId::from(format!("paint_{}_fill_{}", node_id, fill_index))
                });
                fills.push(Fill {
                    id,
                    paint: fill.paint.clone(),
                });
            }
            DslProperty::Stroke(stroke) => {
                let id = stroke.id.clone().unwrap_or_else(|| {
                    stroke_index += 1;
                    PaintId::from(format!("paint_{}_stroke_{}", node_id, stroke_index))
                });
                strokes.push(stroke_from_dsl(id, stroke));
            }
            DslProperty::Shadow(shadow) => {
                let id = shadow.id.clone().unwrap_or_else(|| {
                    shadow_index += 1;
                    EffectId::from(format!("effect_{}_shadow_{}", node_id, shadow_index))
                });
                let effect = effect_from_dsl_shadow(id.clone(), shadow);
                // Upsert semantics: an existing effect id updates in place,
                // a new id appends to the top of the stack.
                if current.effects.iter().any(|existing| existing.id == id) {
                    effect_edits.push(StackEntryEdit::Set { id, value: effect });
                } else {
                    effect_edits.push(StackEntryEdit::Add {
                        entry: effect,
                        index: None,
                    });
                }
            }
            DslProperty::RemoveEffect(effect_id) => {
                effect_edits.push(StackEntryEdit::Remove {
                    id: effect_id.clone(),
                });
            }
            DslProperty::Font(font) => {
                text_patch.font_family = FieldPatch::Set(font.family.clone());
                match &font.size {
                    DslScalar::Number(size) => text_patch.font_size = FieldPatch::Set(*size),
                    DslScalar::Token(token) => {
                        text_patch.style_token = OptionalFieldPatch::Set(token.clone())
                    }
                }
                text_patch.font_weight = FieldPatch::Set(font.weight);
                text_patch.align = FieldPatch::Set(font.align.clone());
                has_text_patch = true;
            }
            DslProperty::FontSize(size) => {
                if let DslScalar::Number(size) = size {
                    text_patch.font_size = FieldPatch::Set(*size);
                    has_text_patch = true;
                }
            }
            DslProperty::FontWeight(weight) => {
                text_patch.font_weight = FieldPatch::Set(*weight);
                has_text_patch = true;
            }
            DslProperty::TextStyleToken(token) => {
                text_patch.style_token = OptionalFieldPatch::Set(token.clone());
                has_text_patch = true;
            }
            DslProperty::LineHeight(line_height) => {
                match line_height {
                    DslScalar::Number(line_height) => {
                        text_patch.line_height = FieldPatch::Set(*line_height)
                    }
                    DslScalar::Token(token) => {
                        text_patch.line_height_token = OptionalFieldPatch::Set(token.clone())
                    }
                }
                has_text_patch = true;
            }
            DslProperty::LetterSpacing(letter_spacing) => {
                match letter_spacing {
                    DslScalar::Number(letter_spacing) => {
                        text_patch.letter_spacing = FieldPatch::Set(*letter_spacing)
                    }
                    DslScalar::Token(token) => {
                        text_patch.letter_spacing_token = OptionalFieldPatch::Set(token.clone())
                    }
                }
                has_text_patch = true;
            }
            DslProperty::Tracking(tracking) => {
                if let DslScalar::Number(tracking) = tracking {
                    let font_size = match &current.kind {
                        NodeKind::Text(text) => text.font_size,
                        _ => 16.0,
                    };
                    text_patch.letter_spacing =
                        FieldPatch::Set(design_tracking_to_letter_spacing(*tracking, font_size));
                    has_text_patch = true;
                }
            }
            DslProperty::MaxLines(max_lines) => {
                text_patch.max_lines = OptionalFieldPatch::Set(*max_lines);
                has_text_patch = true;
            }
            DslProperty::TextWrap(wrap) => {
                text_patch.wrap = FieldPatch::Set(if *wrap {
                    TextWrap::Wrap
                } else {
                    TextWrap::NoWrap
                });
                has_text_patch = true;
            }
            DslProperty::TextDirection(direction) => {
                text_patch.direction = FieldPatch::Set(direction.clone());
                has_text_patch = true;
            }
            DslProperty::Asset(asset_id) => {
                patch.image_asset_id = OptionalFieldPatch::Set(asset_id.clone());
            }
            DslProperty::Radius(radius) => {
                match radius {
                    DslScalar::Number(radius) => {
                        next_corner.top_left = *radius;
                        next_corner.top_right = *radius;
                        next_corner.bottom_right = *radius;
                        next_corner.bottom_left = *radius;
                        next_corner.token = None;
                    }
                    DslScalar::Token(token) => next_corner.token = Some(token.clone()),
                }
                corner_changed = true;
            }
            DslProperty::Opacity(opacity) => match opacity {
                DslScalar::Number(opacity) => {
                    patch.opacity = FieldPatch::Set(*opacity);
                    patch.opacity_token = OptionalFieldPatch::Clear;
                }
                DslScalar::Token(token) => {
                    patch.opacity_token = OptionalFieldPatch::Set(token.clone());
                }
            },
            DslProperty::Clip(clip) => patch.clip = FieldPatch::Set(*clip),
            DslProperty::Gap(gap) => {
                match gap {
                    DslScalar::Number(gap) => {
                        next_layout.gap = *gap;
                        next_layout.gap_token = None;
                    }
                    DslScalar::Token(token) => next_layout.gap_token = Some(token.clone()),
                }
                layout_changed = true;
            }
            DslProperty::Padding(padding) => {
                if let Some(token) = uniform_scalar_token(padding) {
                    next_layout.padding_token = Some(token);
                    layout_changed = true;
                } else if let Some(padding) = scalar_quad_to_numbers(
                    padding,
                    line.line_number,
                    node_id.as_str().len(),
                    "padding",
                    &mut Vec::new(),
                ) {
                    next_layout.padding = padding;
                    next_layout.padding_token = None;
                    layout_changed = true;
                }
            }
            DslProperty::Wrap(wrap) => {
                let _ = wrap;
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "wrap(...) modify lowering for auto-layout kind is not supported yet",
                    "Use structured operations for auto-layout kind changes until Phase D adds a kind patch.",
                ));
            }
            DslProperty::Grow(grow) => {
                if let DslScalar::Number(grow) = grow {
                    next_layout.grow = *grow;
                    layout_changed = true;
                }
            }
            DslProperty::LayoutAnchor { axis, anchor } => {
                let anchor = layout_anchor_to_scene(anchor);
                match axis {
                    DslLayoutAxis::X => next_layout.align_x = anchor,
                    DslLayoutAxis::Y => next_layout.align_y = anchor,
                }
                layout_changed = true;
            }
            DslProperty::PageSize(_)
            | DslProperty::PageBackground(_)
            | DslProperty::SafeArea(_)
            | DslProperty::Bleed(_)
            | DslProperty::Slot(_)
            | DslProperty::SlotLabel(_)
            | DslProperty::SlotRequired(_)
            | DslProperty::SlotPlaceholder(_)
            | DslProperty::SlotSample(_)
            | DslProperty::SlotWorstCase(_)
            | DslProperty::SlotBind(_)
            | DslProperty::SlotUnbind(_)
            | DslProperty::Path(_)
            | DslProperty::Source(_)
            | DslProperty::LineTo(_, _)
            | DslProperty::Token(_)
            | DslProperty::ArtifactType(_)
            | DslProperty::DocumentMedium(_)
            | DslProperty::DocumentBrandKit(_, _)
            | DslProperty::ExportFormatValue(_)
            | DslProperty::ExportPdfIntent(_)
            | DslProperty::ExportRasterScale { .. }
            | DslProperty::ExportIncludeBleed(_)
            | DslProperty::ExportEmbedFonts(_) => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for node modify targets",
                    "Use properties compatible with node targets, or use a page/slot/asset target prefix.",
                ));
            }
        }
    }

    if transform_changed {
        patch.transform = FieldPatch::Set(next_transform);
    }
    if corner_changed {
        patch.corner = FieldPatch::Set(next_corner);
    }
    if layout_changed {
        patch.layout = OptionalFieldPatch::Set(next_layout);
    }
    if !fills.is_empty() {
        patch.fills = FieldPatch::Set(fills);
    }
    if !strokes.is_empty() {
        patch.strokes = FieldPatch::Set(strokes);
    }
    if !effect_edits.is_empty() {
        patch.effect_edits = effect_edits;
    }
    if has_text_patch {
        patch.text = Some(text_patch);
    }
    Ok(patch)
}

fn stroke_from_dsl(id: PaintId, stroke: &DslStroke) -> Stroke {
    let (width, width_token) = match &stroke.width {
        DslScalar::Number(width) => (*width, None),
        DslScalar::Token(token) => (0.0, Some(token.clone())),
    };
    Stroke {
        id,
        paint: stroke.paint.clone(),
        width,
        width_token,
        dash: stroke.dash.clone(),
        cap: stroke.cap.unwrap_or_default(),
        join: stroke.join.unwrap_or_default(),
        align: stroke.align.unwrap_or_default(),
    }
}

fn effect_from_dsl_shadow(id: EffectId, shadow: &DslShadow) -> Effect {
    let color_token = match &shadow.color {
        Color::Token { token } => Some(token.clone()),
        _ => None,
    };
    Effect {
        id,
        kind: EffectKind::DropShadow {
            color: shadow.color.clone(),
            opacity: shadow.opacity,
            x: shadow.x,
            y: shadow.y,
            blur: shadow.blur,
            spread: shadow.spread,
            color_token,
        },
    }
}

fn page_edit_patch_from_properties(
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<PageEditPatch, DslDiagnostic> {
    let mut patch = PageEditPatch::default();
    let mut backgrounds = Vec::new();
    for property in properties {
        match property {
            DslProperty::Name(name) => patch.name = FieldPatch::Set(name.clone()),
            DslProperty::PageSize(size) => {
                patch.size = FieldPatch::Set(normalize_page_size(PageSizeInput::new(
                    size.width,
                    size.height,
                    size.unit.clone(),
                    Some(PagePreset::Custom),
                    orientation_for_dimensions(size.width, size.height),
                )));
            }
            DslProperty::PageBackground(fill) => {
                let id = fill
                    .id
                    .clone()
                    .unwrap_or_else(|| PaintId::from("paint_page_background"));
                backgrounds.push(Fill {
                    id,
                    paint: fill.paint.clone(),
                });
            }
            DslProperty::SafeArea(rect) => patch.safe_area = OptionalFieldPatch::Set(rect.clone()),
            DslProperty::Bleed(rect) => patch.bleed = OptionalFieldPatch::Set(rect.clone()),
            _ => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for page modify targets",
                    "Use name(...), size(width,height,unit), background(...), safe_area(...), or bleed(...).",
                ));
            }
        }
    }
    if !backgrounds.is_empty() {
        patch.background = FieldPatch::Set(backgrounds);
    }
    Ok(patch)
}

fn slot_edit_patch_from_properties(
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<SlotEditPatch, DslDiagnostic> {
    let mut patch = SlotEditPatch::default();
    for property in properties {
        match property {
            DslProperty::SlotLabel(label) | DslProperty::Name(label) => {
                patch.label = FieldPatch::Set(label.clone())
            }
            DslProperty::SlotRequired(required) => {
                patch.required = FieldPatch::Set(*required);
            }
            DslProperty::SlotPlaceholder(placeholder) => {
                patch.placeholder = OptionalFieldPatch::Set(placeholder.clone());
            }
            DslProperty::SlotSample(sample) => {
                patch.sample = OptionalFieldPatch::Set(sample.clone());
            }
            DslProperty::SlotWorstCase(worst_case) => {
                patch.worst_case = OptionalFieldPatch::Set(worst_case.clone());
            }
            DslProperty::SlotBind(node_id) => {
                patch.bind_nodes.push(node_id.clone());
            }
            DslProperty::SlotUnbind(node_id) => {
                patch.unbind_nodes.push(node_id.clone());
            }
            _ => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for slot modify targets",
                    "Use label(...), required(...), placeholder(...), sample(...), worst_case(...), bind(...), or unbind(...).",
                ));
            }
        }
    }
    Ok(patch)
}

fn asset_edit_patch_from_properties(
    properties: &[DslProperty],
    line: &DslLine,
) -> Result<AssetEditPatch, DslDiagnostic> {
    let mut patch = AssetEditPatch::default();
    for property in properties {
        match property {
            DslProperty::Name(name) | DslProperty::SlotLabel(name) => {
                patch.label = FieldPatch::Set(name.clone())
            }
            _ => {
                return Err(error_diag(
                    line.line_number,
                    1,
                    line.raw.len().max(1),
                    "LUMD0903",
                    "property is not supported for asset modify targets",
                    "Use name(...) for metadata-only asset edits in Phase D.",
                ));
            }
        }
    }
    Ok(patch)
}

fn normalized_lines(source: &str) -> Vec<NormalizedLine> {
    source
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            let text = line.trim_end().to_owned();
            if text.trim().is_empty() {
                None
            } else {
                Some(NormalizedLine {
                    line_number: index + 1,
                    text,
                })
            }
        })
        .collect()
}

fn parse_element_kind(token: &str, line_number: usize) -> Result<DslElementKind, DslDiagnostic> {
    let (name, args) = if let Some(call) = parse_call(token) {
        (call.name, call.args)
    } else {
        (token.to_owned(), Vec::new())
    };

    match name.as_str() {
        "fr" | "frame" => {
            expect_no_kind_args(&name, &args, token, line_number)?;
            Ok(DslElementKind::Frame)
        }
        "gr" | "group" => {
            expect_no_kind_args(&name, &args, token, line_number)?;
            Ok(DslElementKind::Group)
        }
        "r" | "rect" => {
            expect_no_kind_args(&name, &args, token, line_number)?;
            Ok(DslElementKind::Rect)
        }
        "c" | "e" | "ellipse" => {
            expect_no_kind_args(&name, &args, token, line_number)?;
            Ok(DslElementKind::Ellipse)
        }
        "l" | "line" => {
            if args.is_empty() {
                Ok(DslElementKind::Line { x2: 0.0, y2: 0.0 })
            } else if args.len() == 2 {
                Ok(DslElementKind::Line {
                    x2: parse_f64(&args[0], line_number, 1)?,
                    y2: parse_f64(&args[1], line_number, 1)?,
                })
            } else {
                Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0232",
                    "line(...) expects either no args or x2,y2",
                    "Use line divider to(x,y) or l(x2,y2).",
                ))
            }
        }
        "t" | "text" => {
            if args.len() > 1 && args.len() != 5 {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0233",
                    "text(...) expects content or content,family,size,weight,align",
                    "Use t(\"Copy\") or t(\"Copy\",\"Inter\",18,700,left).",
                ));
            }
            Ok(DslElementKind::Text {
                content: args
                    .first()
                    .map(|arg| unquote(arg, line_number, 1))
                    .transpose()?
                    .unwrap_or_default(),
            })
        }
        "img" | "image" => {
            if args.len() > 1 {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0234",
                    "image(...) expects at most one asset id",
                    "Use image logo asset(account_logo) or img(account_logo).",
                ));
            }
            let asset_id = args
                .first()
                .map(|arg| {
                    if let Some(call) = parse_call(arg) {
                        if call.name == "asset" && call.args.len() == 1 {
                            parse_asset_id(&call.args[0], line_number, 1)
                        } else {
                            parse_asset_id(arg, line_number, 1)
                        }
                    } else {
                        parse_asset_id(arg, line_number, 1)
                    }
                })
                .transpose()?;
            Ok(DslElementKind::Image { asset_id })
        }
        "v" | "vector" => {
            if args.len() > 1 {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0235",
                    "vector(...) expects at most one path string",
                    "Use vector icon path(\"M0 0L10 10\") or v(\"M0 0L10 10\").",
                ));
            }
            Ok(DslElementKind::Vector {
                path_data: args
                    .first()
                    .map(|arg| unquote(arg, line_number, 1))
                    .transpose()?,
            })
        }
        "svg" => {
            if args.len() != 1 {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0236",
                    "svg(...) expects one icon reference",
                    "Use svg(icon:calendar).",
                ));
            }
            Ok(DslElementKind::SvgIcon {
                icon: args[0].clone(),
            })
        }
        "al" | "autolayout" => {
            let direction = args
                .first()
                .map(|arg| {
                    parse_direction(arg).ok_or_else(|| {
                        error_diag(
                            line_number,
                            1,
                            arg.len(),
                            "LUMD0244",
                            format!("unknown autolayout direction {arg}"),
                            "Use h/row/horizontal or v/column/vertical.",
                        )
                    })
                })
                .transpose()?
                .unwrap_or(AutoLayoutDirection::Column);
            Ok(DslElementKind::AutoLayout { direction })
        }
        "inst" | "instance" => {
            if args.len() > 1 {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0237",
                    "instance(...) expects at most one source node id",
                    "Use instance copy source(card) or inst(card).",
                ));
            }
            Ok(DslElementKind::Instance {
                source_node_id: args
                    .first()
                    .map(|arg| parse_node_id(arg, line_number, 1))
                    .transpose()?,
            })
        }
        _ => Err(error_diag(
            line_number,
            1,
            token.len(),
            "LUMD0209",
            format!("unknown element kind {name}"),
            "Use frame/fr, group/gr, autolayout/al, rect/r, ellipse/e, line/l, text/t, image/img, vector/v, or instance.",
        )),
    }
}

fn element_kind_name(token: &str) -> Option<&str> {
    let name = parse_call(token)
        .map(|call| call.name)
        .unwrap_or_else(|| token.to_owned());
    match name.as_str() {
        "fr" | "frame" | "gr" | "group" | "al" | "autolayout" | "r" | "rect" | "c" | "e"
        | "ellipse" | "l" | "line" | "t" | "text" | "img" | "image" | "v" | "vector" | "svg"
        | "inst" | "instance" => Some(token),
        _ => None,
    }
}

fn parse_kind_call_properties(
    token: &str,
    line_number: usize,
) -> Result<Vec<DslProperty>, DslDiagnostic> {
    let Some(call) = parse_call(token) else {
        return Ok(Vec::new());
    };

    match call.name.as_str() {
        "t" | "text" if call.args.len() == 5 => Ok(vec![DslProperty::Font(DslFont {
            family: unquote(&call.args[1], line_number, 1)?,
            size: parse_scalar(&call.args[2], line_number, 1)?,
            weight: parse_u16(&call.args[3], line_number, 1)?,
            align: parse_text_align(&call.args[4], line_number, 1)?,
        })]),
        "al" | "autolayout" => call
            .args
            .iter()
            .skip(1)
            .map(|arg| parse_property_token(arg, line_number, 1))
            .collect::<Result<Vec<_>, _>>()
            .map(|groups| groups.into_iter().flatten().collect()),
        _ => Ok(Vec::new()),
    }
}

fn expect_no_kind_args(
    name: &str,
    args: &[String],
    token: &str,
    line_number: usize,
) -> Result<(), DslDiagnostic> {
    if args.is_empty() {
        Ok(())
    } else {
        Err(error_diag(
            line_number,
            1,
            token.len(),
            "LUMD0243",
            format!("{name} does not accept call arguments"),
            "Use properties such as p(...), s(...), f[...], and st[...] after the element id.",
        ))
    }
}

fn parse_property_token(
    token: &str,
    line_number: usize,
    column: usize,
) -> Result<Vec<DslProperty>, DslDiagnostic> {
    let Some(call) = parse_call(token) else {
        return Err(error_diag(
            line_number,
            column,
            token.len(),
            "LUMD0210",
            format!("unsupported property syntax {token}"),
            "Use property calls such as p(x,y), s(w,h), fill(#hex), font(...), or slot(key).",
        ));
    };

    let properties = match call.name.as_str() {
        "p" | "pos" => {
            expect_arg_count(&call, 2, line_number)?;
            vec![DslProperty::Position(
                parse_f64(&call.args[0], line_number, column)?,
                parse_f64(&call.args[1], line_number, column)?,
            )]
        }
        "s" | "size" => {
            if call.args.len() == 3 {
                vec![DslProperty::PageSize(parse_page_size(&call, line_number)?)]
            } else {
                expect_arg_count(&call, 2, line_number)?;
                vec![DslProperty::Size(
                    parse_dimension(&call.args[0], line_number, column)?,
                    parse_dimension(&call.args[1], line_number, column)?,
                )]
            }
        }
        "text" | "content" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextContent(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "fill" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Fill(DslFill {
                id: None,
                paint: parse_paint(&call.args[0], line_number, column)?,
            })]
        }
        "background" | "bg" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::PageBackground(DslFill {
                id: None,
                paint: parse_paint(&call.args[0], line_number, column)?,
            })]
        }
        "f" => parse_fill_list(&call.args.join(","), line_number, column)?
            .into_iter()
            .map(DslProperty::Fill)
            .collect(),
        "stroke" => {
            vec![DslProperty::Stroke(parse_stroke_property(
                &call,
                token,
                line_number,
                column,
            )?)]
        }
        "shadow" => {
            vec![DslProperty::Shadow(parse_shadow_property(
                &call,
                token,
                line_number,
                column,
            )?)]
        }
        "remove_effect" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::RemoveEffect(parse_effect_id(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "st" => parse_stroke_list(&call.args.join(","), line_number, column)?
            .into_iter()
            .map(DslProperty::Stroke)
            .collect(),
        "font" => parse_font_property(&call, line_number, column)?,
        "font_size" | "font-size" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::FontSize(parse_positive_scalar(
                &call.args[0],
                line_number,
                column,
                "font size",
            )?)]
        }
        "font_weight" | "font-weight" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::FontWeight(parse_u16(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "style" | "text_style" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextStyleToken(parse_token_ref(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "lh" | "line_height" | "line-height" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::LineHeight(parse_positive_scalar(
                &call.args[0],
                line_number,
                column,
                "line height",
            )?)]
        }
        "ls" | "letter_spacing" | "letter-spacing" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::LetterSpacing(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "tracking" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Tracking(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "max_lines" | "max" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::MaxLines(parse_positive_u16(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "wrap_text" | "text_wrap" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextWrap(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "dir" | "direction" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextDirection(parse_text_direction(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "slot" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Slot(parse_slot_key(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "meta" => vec![DslProperty::Slot(parse_meta_slot(
            &call,
            line_number,
            column,
        )?)],
        "label" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotLabel(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "required" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotRequired(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "placeholder" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotPlaceholder(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "sample" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotSample(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "worst_case" | "worst-case" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotWorstCase(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "bind" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotBind(parse_node_id(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "unbind" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::SlotUnbind(parse_node_id(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "asset" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Asset(parse_asset_id(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "path" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Path(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "source" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Source(parse_node_id(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "rd" | "radius" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Radius(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "o" | "opacity" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Opacity(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "rot" | "rotation" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Rotation(parse_f64(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "sk" | "skew" => {
            expect_arg_count(&call, 2, line_number)?;
            vec![DslProperty::Skew(
                parse_f64(&call.args[0], line_number, column)?,
                parse_f64(&call.args[1], line_number, column)?,
            )]
        }
        "flip" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![parse_flip(&call.args[0], line_number, column)?]
        }
        "clip" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Clip(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "safe_area" | "safe-area" => {
            expect_arg_count(&call, 4, line_number)?;
            vec![DslProperty::SafeArea(Rect {
                x: parse_f64(&call.args[0], line_number, column)?,
                y: parse_f64(&call.args[1], line_number, column)?,
                width: parse_positive_f64(&call.args[2], line_number, column)?,
                height: parse_positive_f64(&call.args[3], line_number, column)?,
            })]
        }
        "bleed" => {
            expect_arg_count(&call, 4, line_number)?;
            vec![DslProperty::Bleed(Rect {
                x: parse_f64(&call.args[0], line_number, column)?,
                y: parse_f64(&call.args[1], line_number, column)?,
                width: parse_positive_f64(&call.args[2], line_number, column)?,
                height: parse_positive_f64(&call.args[3], line_number, column)?,
            })]
        }
        "g" | "gap" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Gap(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "pad" | "padding" => vec![DslProperty::Padding(parse_padding(
            &call,
            line_number,
            column,
        )?)],
        "wrap" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Wrap(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "grow" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Grow(parse_scalar(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "x" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::LayoutAnchor {
                axis: DslLayoutAxis::X,
                anchor: parse_layout_anchor(&call.args[0], line_number, column)?,
            }]
        }
        "y" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::LayoutAnchor {
                axis: DslLayoutAxis::Y,
                anchor: parse_layout_anchor(&call.args[0], line_number, column)?,
            }]
        }
        "to" => {
            expect_arg_count(&call, 2, line_number)?;
            vec![DslProperty::LineTo(
                parse_f64(&call.args[0], line_number, column)?,
                parse_f64(&call.args[1], line_number, column)?,
            )]
        }
        "name" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Name(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "append" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextAppend(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "prepend" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextPrepend(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "artifact_type" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::ArtifactType(unquote(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "medium" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::DocumentMedium(parse_medium(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "brand_kit" => {
            expect_arg_count(&call, 2, line_number)?;
            let version = parse_f64(&call.args[1], line_number, column)?;
            if version < 0.0 || version.fract() != 0.0 {
                return Err(error_diag(
                    line_number,
                    column,
                    token.len(),
                    "LUMD0211",
                    "brand_kit(...) expects a non-negative integer version",
                    "Use brand_kit(brand_id, 3).",
                ));
            }
            vec![DslProperty::DocumentBrandKit(
                call.args[0].trim().to_owned(),
                version as u32,
            )]
        }
        "format" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::ExportFormatValue(parse_export_format(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "pdf_intent" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::ExportPdfIntent(parse_pdf_intent(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "raster_scale" => {
            if call.args.is_empty() || call.args.len() > 2 {
                return Err(error_diag(
                    line_number,
                    column,
                    token.len(),
                    "LUMD0211",
                    "raster_scale(...) expects scale and optional dpi",
                    "Use raster_scale(2) or raster_scale(2, 300).",
                ));
            }
            let scale = parse_f64(&call.args[0], line_number, column)?;
            let dpi = if call.args.len() == 2 {
                Some(parse_f64(&call.args[1], line_number, column)? as u16)
            } else {
                None
            };
            vec![DslProperty::ExportRasterScale { scale, dpi }]
        }
        "include_bleed" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::ExportIncludeBleed(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "embed_fonts" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::ExportEmbedFonts(parse_bool(
                &call.args[0],
                line_number,
                column,
            )?)]
        }
        "token" | "ds" | "color" => vec![DslProperty::Token(token.to_owned())],
        _ => {
            return Err(error_diag(
                line_number,
                column,
                token.len(),
                "LUMD0212",
                format!("unknown property {}", call.name),
                "Unsupported constructs are errors in the DSL compiler, not silently ignored.",
            ));
        }
    };

    Ok(properties)
}

fn node_from_element(element: &DslElement, line_number: usize) -> Result<Node, DslDiagnostic> {
    let kind = match &element.kind {
        DslElementKind::Frame => NodeKind::Frame,
        DslElementKind::Group => NodeKind::Group,
        DslElementKind::Rect => NodeKind::Rect,
        DslElementKind::Ellipse => NodeKind::Ellipse,
        DslElementKind::Line { x2, y2 } => NodeKind::Line(LineNode { x2: *x2, y2: *y2 }),
        DslElementKind::Text { content } => NodeKind::Text(TextNode {
            content: content.clone(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 400,
            align: TextAlign::Left,
            line_height: 1.2,
            letter_spacing: 0.0,
            max_lines: None,
            wrap: TextWrap::NoWrap,
            direction: TextDirection::Ltr,
            style_token: None,
            line_height_token: None,
            letter_spacing_token: None,
        }),
        DslElementKind::Image { asset_id } => NodeKind::Image(ImageNode {
            asset_id: asset_id
                .clone()
                .or_else(|| property_asset_id(&element.properties))
                .ok_or_else(|| {
                    error_diag(
                        line_number,
                        1,
                        element.id.as_str().len(),
                        "LUMD0403",
                        "image elements require asset(asset_id)",
                        "Use image logo asset(account_logo) ...",
                    )
                })?,
            alt: None,
        }),
        DslElementKind::Vector { path_data } => NodeKind::Vector(VectorNode {
            path_data: path_data
                .clone()
                .or_else(|| property_path_data(&element.properties))
                .ok_or_else(|| {
                    error_diag(
                        line_number,
                        1,
                        element.id.as_str().len(),
                        "LUMD0404",
                        "vector elements require path(\"...\")",
                        "Use vector icon path(\"M0 0L10 10\") ...",
                    )
                })?,
        }),
        DslElementKind::SvgIcon { .. } => {
            return Err(error_diag(
                line_number,
                1,
                element.id.as_str().len(),
                "LUMD0703",
                "svg icon elements are parsed but not lowered by this workstream",
                "Use vector path(...) for now; SVG/icon acquisition belongs to assets/pipeline-v0.",
            ));
        }
        DslElementKind::AutoLayout { direction } => NodeKind::AutoLayout(AutoLayoutNode {
            direction: direction.clone(),
            wrap: false,
        }),
        DslElementKind::Instance { source_node_id } => NodeKind::Instance {
            source_node_id: source_node_id
                .clone()
                .or_else(|| property_source_node_id(&element.properties))
                .ok_or_else(|| {
                    error_diag(
                        line_number,
                        1,
                        element.id.as_str().len(),
                        "LUMD0405",
                        "instance elements require source(node_id)",
                        "Use instance card_copy source(card_template).",
                    )
                })?,
        },
    };

    Ok(Node::new(element.id.clone(), kind))
}

fn property_asset_id(properties: &[DslProperty]) -> Option<AssetId> {
    properties.iter().find_map(|property| {
        if let DslProperty::Asset(asset_id) = property {
            Some(asset_id.clone())
        } else {
            None
        }
    })
}

fn property_path_data(properties: &[DslProperty]) -> Option<String> {
    properties.iter().find_map(|property| {
        if let DslProperty::Path(path_data) = property {
            Some(path_data.clone())
        } else {
            None
        }
    })
}

fn property_source_node_id(properties: &[DslProperty]) -> Option<NodeId> {
    properties.iter().find_map(|property| {
        if let DslProperty::Source(node_id) = property {
            Some(node_id.clone())
        } else {
            None
        }
    })
}

fn apply_properties(
    node: &mut Node,
    properties: &[DslProperty],
    line_number: usize,
    diagnostics: &mut Vec<DslDiagnostic>,
) {
    let mut fill_index = 0;
    let mut stroke_index = 0;
    let mut shadow_index = 0;

    for property in properties {
        match property {
            DslProperty::Position(x, y) => {
                node.transform.x = *x;
                node.transform.y = *y;
            }
            DslProperty::Size(width, height) => {
                node.size = SizeSpec {
                    width: dimension_to_scene(width),
                    height: dimension_to_scene(height),
                };
            }
            DslProperty::PageSize(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0610",
                    "size(width,height,unit) only applies to page modify targets",
                    "Use size(width,height) on nodes, or use size(width,height,unit) on #page:page_id modify lines.",
                ));
            }
            DslProperty::TextContent(content) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.content = content.clone();
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0608",
                        "text(...)/content(...) only applies to text nodes",
                        "Move text(\"...\") to a text/t element or #text_node modify line.",
                    ));
                }
            }
            DslProperty::Fill(fill) => {
                let id = fill.id.clone().unwrap_or_else(|| {
                    fill_index += 1;
                    PaintId::from(format!("paint_{}_fill_{}", node.id, fill_index))
                });
                node.fills.push(Fill {
                    id,
                    paint: fill.paint.clone(),
                });
            }
            DslProperty::PageBackground(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0611",
                    "background(...) only applies to page modify targets",
                    "Use background(...) on #page:page_id modify lines.",
                ));
            }
            DslProperty::Stroke(stroke) => {
                let id = stroke.id.clone().unwrap_or_else(|| {
                    stroke_index += 1;
                    PaintId::from(format!("paint_{}_stroke_{}", node.id, stroke_index))
                });
                node.strokes.push(stroke_from_dsl(id, stroke));
            }
            DslProperty::Shadow(shadow) => {
                let id = shadow.id.clone().unwrap_or_else(|| {
                    shadow_index += 1;
                    EffectId::from(format!("effect_{}_shadow_{}", node.id, shadow_index))
                });
                node.effects.push(effect_from_dsl_shadow(id, shadow));
            }
            DslProperty::RemoveEffect(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0616",
                    "remove_effect(...) only applies to modify lines targeting existing nodes",
                    "Author the effect stack directly when creating elements; remove effects with #node remove_effect(id).",
                ));
            }
            DslProperty::Font(font) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.font_family = font.family.clone();
                    if let Some(size) = scalar_to_number(
                        &font.size,
                        line_number,
                        node.id.as_str().len(),
                        "font size",
                        diagnostics,
                    ) {
                        text.font_size = size;
                    }
                    text.font_weight = font.weight;
                    text.align = font.align.clone();
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0601",
                        "font(...) only applies to text nodes",
                        "Move font(...) to a text/t element.",
                    ));
                }
            }
            DslProperty::FontSize(font_size) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    if let Some(size) = scalar_to_number(
                        font_size,
                        line_number,
                        node.id.as_str().len(),
                        "font size",
                        diagnostics,
                    ) {
                        text.font_size = size;
                    }
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0605",
                        "font_size(...) only applies to text nodes",
                        "Move font_size(...) to a text/t element.",
                    ));
                }
            }
            DslProperty::FontWeight(font_weight) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.font_weight = *font_weight;
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0606",
                        "font_weight(...) only applies to text nodes",
                        "Move font_weight(...) to a text/t element.",
                    ));
                }
            }
            DslProperty::TextStyleToken(token) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.style_token = Some(token.clone());
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0602",
                        "style(...) only applies to text nodes",
                        "Move style($typography.token) to a text/t element.",
                    ));
                }
            }
            DslProperty::Asset(asset_id) => {
                if let NodeKind::Image(image) = &mut node.kind {
                    image.asset_id = asset_id.clone();
                }
            }
            DslProperty::Path(path) => {
                if let NodeKind::Vector(vector) = &mut node.kind {
                    vector.path_data = path.clone();
                }
            }
            DslProperty::Source(source) => {
                if let NodeKind::Instance { source_node_id } = &mut node.kind {
                    *source_node_id = source.clone();
                }
            }
            DslProperty::Radius(radius) => match radius {
                DslScalar::Number(radius) => {
                    node.corner.top_left = *radius;
                    node.corner.top_right = *radius;
                    node.corner.bottom_right = *radius;
                    node.corner.bottom_left = *radius;
                    node.corner.token = None;
                }
                DslScalar::Token(token) => {
                    node.corner.token = Some(token.clone());
                }
            },
            DslProperty::Opacity(opacity) => match opacity {
                DslScalar::Number(opacity) => {
                    node.opacity = *opacity;
                    node.opacity_token = None;
                }
                DslScalar::Token(token) => {
                    node.opacity_token = Some(token.clone());
                }
            },
            DslProperty::Rotation(rotation) => node.transform.rotation = *rotation,
            DslProperty::Skew(skew_x, skew_y) => {
                node.transform.skew_x = *skew_x;
                node.transform.skew_y = *skew_y;
            }
            DslProperty::Flip { x, y } => {
                node.transform.flip_x = *x;
                node.transform.flip_y = *y;
            }
            DslProperty::Clip(clip) => node.clip = *clip,
            DslProperty::SafeArea(_) | DslProperty::Bleed(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0612",
                    "safe_area(...)/bleed(...) only apply to page modify targets",
                    "Use these properties on #page:page_id modify lines.",
                ));
            }
            DslProperty::Gap(gap) => match gap {
                DslScalar::Number(gap) => {
                    let layout = ensure_layout(node);
                    layout.gap = *gap;
                    layout.gap_token = None;
                }
                DslScalar::Token(token) => {
                    ensure_layout(node).gap_token = Some(token.clone());
                }
            },
            DslProperty::Padding(padding) => {
                if let Some(token) = uniform_scalar_token(padding) {
                    ensure_layout(node).padding_token = Some(token);
                } else if padding
                    .iter()
                    .any(|scalar| matches!(scalar, DslScalar::Token(_)))
                {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0705",
                        "mixed padding token syntax is parsed but not lowered by this workstream",
                        "Use pad($spacing.token) for now; per-edge padding token carriers belong to a later scene contract update.",
                    ));
                } else if let Some(padding) = scalar_quad_to_numbers(
                    padding,
                    line_number,
                    node.id.as_str().len(),
                    "padding",
                    diagnostics,
                ) {
                    let layout = ensure_layout(node);
                    layout.padding = padding;
                    layout.padding_token = None;
                }
            }
            DslProperty::Wrap(wrap) => {
                if let NodeKind::AutoLayout(auto_layout) = &mut node.kind {
                    auto_layout.wrap = *wrap;
                }
            }
            DslProperty::TextWrap(wrap) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.wrap = if *wrap {
                        TextWrap::Wrap
                    } else {
                        TextWrap::NoWrap
                    };
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0604",
                        "wrap_text(...) only applies to text nodes",
                        "Use wrap_text(true) on text nodes, or wrap(true) on auto-layout nodes.",
                    ));
                }
            }
            DslProperty::LineHeight(line_height) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    match line_height {
                        DslScalar::Number(line_height) => {
                            text.line_height = *line_height;
                            text.line_height_token = None;
                        }
                        DslScalar::Token(token) => {
                            text.line_height_token = Some(token.clone());
                        }
                    }
                }
            }
            DslProperty::LetterSpacing(letter_spacing) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    match letter_spacing {
                        DslScalar::Number(letter_spacing) => {
                            text.letter_spacing = *letter_spacing;
                            text.letter_spacing_token = None;
                        }
                        DslScalar::Token(token) => {
                            text.letter_spacing_token = Some(token.clone());
                        }
                    }
                }
            }
            DslProperty::Tracking(tracking) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    match tracking {
                        DslScalar::Number(tracking) => {
                            text.letter_spacing =
                                design_tracking_to_letter_spacing(*tracking, text.font_size);
                            text.letter_spacing_token = None;
                        }
                        DslScalar::Token(token) => {
                            text.letter_spacing_token = Some(token.clone());
                        }
                    }
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0607",
                        "tracking(...) only applies to text nodes",
                        "Move tracking(...) to a text/t element, or use ls(...) for explicit letter spacing.",
                    ));
                }
            }
            DslProperty::MaxLines(max_lines) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.max_lines = Some(*max_lines);
                }
            }
            DslProperty::TextDirection(direction) => {
                if let NodeKind::Text(text) = &mut node.kind {
                    text.direction = direction.clone();
                }
            }
            DslProperty::Grow(grow) => {
                if let Some(grow) = scalar_to_number(
                    grow,
                    line_number,
                    node.id.as_str().len(),
                    "grow",
                    diagnostics,
                ) {
                    ensure_layout(node).grow = grow;
                }
            }
            DslProperty::LayoutAnchor { .. } => {
                if matches!(node.kind, NodeKind::AutoLayout(_)) {
                    let DslProperty::LayoutAnchor { axis, anchor } = property else {
                        unreachable!("matched layout anchor");
                    };
                    let anchor = layout_anchor_to_scene(anchor);
                    let layout = ensure_layout(node);
                    match axis {
                        DslLayoutAxis::X => layout.align_x = anchor,
                        DslLayoutAxis::Y => layout.align_y = anchor,
                    }
                } else {
                    diagnostics.push(warning_diag(
                        line_number,
                        1,
                        node.id.as_str().len(),
                        "LUMD0603",
                        "x(...)/y(...) only apply to auto-layout nodes",
                        "Move layout anchors to an autolayout/al element.",
                    ));
                }
            }
            DslProperty::LineTo(x, y) => {
                if let NodeKind::Line(line) = &mut node.kind {
                    line.x2 = *x;
                    line.y2 = *y;
                }
            }
            DslProperty::SlotLabel(_)
            | DslProperty::SlotRequired(_)
            | DslProperty::SlotPlaceholder(_)
            | DslProperty::SlotSample(_)
            | DslProperty::SlotWorstCase(_)
            | DslProperty::SlotBind(_)
            | DslProperty::SlotUnbind(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0613",
                    "slot metadata properties only apply to slot modify targets",
                    "Use these properties on #slot:key or #slot_id:id modify lines.",
                ));
            }
            DslProperty::Name(name) => node.name = Some(name.clone()),
            DslProperty::Token(token) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0702",
                    "design-system token syntax is parsed but not resolved in this workstream",
                    "Token model and resolution belong to brand-kit/tokens-v0.",
                ));
            }
            DslProperty::Slot(_) => {}
            DslProperty::TextAppend(_) | DslProperty::TextPrepend(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0615",
                    "append/prepend only apply to modify lines targeting existing text nodes",
                    "Author full text(...) content when creating elements.",
                ));
            }
            DslProperty::ArtifactType(_)
            | DslProperty::DocumentMedium(_)
            | DslProperty::DocumentBrandKit(_, _)
            | DslProperty::ExportFormatValue(_)
            | DslProperty::ExportPdfIntent(_)
            | DslProperty::ExportRasterScale { .. }
            | DslProperty::ExportIncludeBleed(_)
            | DslProperty::ExportEmbedFonts(_) => {
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0614",
                    "document/export-profile properties only apply to #document or #export:name modify targets",
                    "Use these properties on #document or #export:name modify lines.",
                ));
            }
        }
    }
}

fn ensure_layout(node: &mut Node) -> &mut AutoLayoutProps {
    node.layout.get_or_insert_with(AutoLayoutProps::default)
}

fn layout_anchor_to_scene(anchor: &DslLayoutAnchor) -> LayoutAnchor {
    match anchor {
        DslLayoutAnchor::Start => LayoutAnchor::Start,
        DslLayoutAnchor::Center => LayoutAnchor::Center,
        DslLayoutAnchor::End => LayoutAnchor::End,
        DslLayoutAnchor::SpaceBetween => LayoutAnchor::SpaceBetween,
        DslLayoutAnchor::Stretch => LayoutAnchor::Stretch,
    }
}

fn design_tracking_to_letter_spacing(tracking: f64, font_size: f64) -> f64 {
    if tracking.abs() > 20.0 {
        font_size * tracking / 1000.0
    } else {
        tracking
    }
}

fn scalar_to_number(
    scalar: &DslScalar,
    line_number: usize,
    length: usize,
    field_name: &str,
    diagnostics: &mut Vec<DslDiagnostic>,
) -> Option<f64> {
    match scalar {
        DslScalar::Number(value) => Some(*value),
        DslScalar::Token(token) => {
            diagnostics.push(unresolved_scalar_token_warning(
                line_number,
                length,
                field_name,
                token,
            ));
            None
        }
    }
}

fn scalar_quad_to_numbers(
    scalars: &[DslScalar; 4],
    line_number: usize,
    length: usize,
    field_name: &str,
    diagnostics: &mut Vec<DslDiagnostic>,
) -> Option<[f64; 4]> {
    let mut values = [0.0; 4];
    for (index, scalar) in scalars.iter().enumerate() {
        match scalar {
            DslScalar::Number(value) => values[index] = *value,
            DslScalar::Token(token) => {
                diagnostics.push(unresolved_scalar_token_warning(
                    line_number,
                    length,
                    field_name,
                    token,
                ));
                return None;
            }
        }
    }
    Some(values)
}

fn uniform_scalar_token(scalars: &[DslScalar; 4]) -> Option<String> {
    let DslScalar::Token(first) = &scalars[0] else {
        return None;
    };
    if scalars
        .iter()
        .all(|scalar| matches!(scalar, DslScalar::Token(token) if token == first))
    {
        Some(first.clone())
    } else {
        None
    }
}

fn unresolved_scalar_token_warning(
    line_number: usize,
    length: usize,
    field_name: &str,
    token: &str,
) -> DslDiagnostic {
    warning_diag(
        line_number,
        1,
        length.max(1),
        "LUMD0705",
        format!("{field_name} token ${token} is parsed but not resolved in this workstream"),
        "Token model and numeric/style resolution belong to brand-kit/tokens-v0.",
    )
}

fn dimension_to_scene(dimension: &DslDimension) -> crate::Dimension {
    match dimension {
        DslDimension::Fixed(value) => crate::Dimension::Fixed(*value),
        DslDimension::Hug => crate::Dimension::Hug,
        DslDimension::Fill(weight) => crate::Dimension::Fill {
            weight: weight.unwrap_or(1.0),
        },
        DslDimension::Token(token) => crate::Dimension::Token {
            token: token.clone(),
        },
    }
}

fn parse_fill_list(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<Vec<DslFill>, DslDiagnostic> {
    parse_tuple_groups(source, line_number, column)?
        .into_iter()
        .map(|group| {
            let args = split_top_level_commas(&group);
            if args.len() == 1 {
                Ok(DslFill {
                    id: None,
                    paint: parse_paint(&args[0], line_number, column)?,
                })
            } else if args.len() == 2 {
                Ok(DslFill {
                    id: Some(parse_paint_id(&args[0], line_number, column)?),
                    paint: parse_paint(&args[1], line_number, column)?,
                })
            } else if args.len() > 2 {
                Err(error_diag(
                    line_number,
                    column,
                    source.len(),
                    "LUMD0238",
                    "fill tuple expects paint or id,paint",
                    "Use f[(fill_id,#ffffff)] and keep effects in later renderer/asset workstreams.",
                ))
            } else {
                Err(error_diag(
                    line_number,
                    column,
                    source.len(),
                    "LUMD0213",
                    "empty fill tuple",
                    "Use f[(fill_id,#ffffff)].",
                ))
            }
        })
        .collect()
}

fn parse_stroke_list(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<Vec<DslStroke>, DslDiagnostic> {
    parse_tuple_groups(source, line_number, column)?
        .into_iter()
        .map(|group| {
            let args = split_top_level_commas(&group);
            if args.len() != 3 {
                return Err(error_diag(
                    line_number,
                    column,
                    source.len(),
                    "LUMD0214",
                    "stroke tuple expects exactly id, color, and width",
                    "Use st[(stroke_id,#111827,w(2))]; cap/position semantics belong to a later stroke-model update.",
                ));
            }
            let width = if let Some(call) = parse_call(&args[2]) {
                if call.name == "w" && call.args.len() == 1 {
                    parse_scalar(&call.args[0], line_number, column)?
                } else {
                    parse_scalar(&args[2], line_number, column)?
                }
            } else {
                parse_scalar(&args[2], line_number, column)?
            };
            Ok(DslStroke::basic(
                Some(parse_paint_id(&args[0], line_number, column)?),
                parse_paint(&args[1], line_number, column)?,
                width,
            ))
        })
        .collect()
}

fn parse_tuple_groups(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<Vec<String>, DslDiagnostic> {
    let trimmed = source.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }

    if !trimmed.starts_with('(') {
        if trimmed.contains('(') || trimmed.contains(')') {
            return Err(error_diag(
                line_number,
                column,
                source.len().max(1),
                "LUMD0247",
                "malformed paint tuple list",
                "Use f[(fill_id,#ffffff)] or st[(stroke_id,#111827,w(2))]; tuple lists must consume the full source.",
            ));
        }
        return Ok(split_top_level_commas(trimmed));
    }

    let mut groups = Vec::new();
    let mut cursor = 0usize;

    while cursor < trimmed.len() {
        cursor = skip_ascii_whitespace(trimmed, cursor);
        if cursor >= trimmed.len() {
            break;
        }

        if trimmed.as_bytes()[cursor] != b'(' {
            return Err(error_diag(
                line_number,
                column + cursor,
                source.len().saturating_sub(cursor).max(1),
                "LUMD0247",
                "malformed paint tuple list",
                "Only commas and complete tuple groups are allowed after the first paint tuple.",
            ));
        }

        let group_start = cursor + 1;
        let mut depth = 0usize;
        let mut in_string = false;
        let mut escape = false;
        let mut end = None;

        for (relative_index, ch) in trimmed[cursor..].char_indices() {
            let index = cursor + relative_index;
            if escape {
                escape = false;
                continue;
            }
            if ch == '\\' && in_string {
                escape = true;
                continue;
            }
            if ch == '"' {
                in_string = !in_string;
                continue;
            }
            if in_string {
                continue;
            }
            match ch {
                '(' => depth += 1,
                ')' => {
                    if depth == 0 {
                        return Err(error_diag(
                            line_number,
                            column + index,
                            1,
                            "LUMD0247",
                            "malformed paint tuple list",
                            "Check tuple parentheses.",
                        ));
                    }
                    depth -= 1;
                    if depth == 0 {
                        end = Some(index);
                        break;
                    }
                }
                _ => {}
            }
        }

        let Some(group_end) = end else {
            return Err(error_diag(
                line_number,
                column + cursor,
                source.len().saturating_sub(cursor).max(1),
                "LUMD0247",
                "malformed paint tuple list",
                "Close every paint tuple and avoid trailing malformed text.",
            ));
        };

        groups.push(trimmed[group_start..group_end].trim().to_owned());
        cursor = skip_ascii_whitespace(trimmed, group_end + 1);

        if cursor >= trimmed.len() {
            break;
        }

        if trimmed.as_bytes()[cursor] != b',' {
            return Err(error_diag(
                line_number,
                column + cursor,
                1,
                "LUMD0247",
                "malformed paint tuple list",
                "Separate paint tuples with commas and remove trailing junk.",
            ));
        }
        cursor += 1;
        cursor = skip_ascii_whitespace(trimmed, cursor);
        if cursor >= trimmed.len() {
            return Err(error_diag(
                line_number,
                column + cursor.saturating_sub(1),
                1,
                "LUMD0247",
                "malformed paint tuple list",
                "Remove the trailing comma or add the next tuple.",
            ));
        }
    }

    Ok(groups)
}

fn parse_paint(source: &str, line_number: usize, column: usize) -> Result<Paint, DslDiagnostic> {
    let source = source.trim();
    if let Some(token) = source.strip_prefix('$') {
        return Ok(Paint::Token {
            token: token.to_owned(),
        });
    }
    if source.starts_with("linear(") {
        let call = parse_required_call(source, "linear", line_number, column)?;
        let angle = call
            .args
            .first()
            .map(|arg| parse_f64(arg, line_number, column))
            .transpose()?
            .unwrap_or(0.0);
        let stops = call
            .args
            .iter()
            .skip(1)
            .map(|arg| parse_color_stop(arg, line_number, column))
            .collect::<Result<Vec<_>, _>>()?;
        if stops.is_empty() {
            return Err(error_diag(
                line_number,
                column,
                source.len(),
                "LUMD0239",
                "linear(...) expects at least one stop",
                "Use linear(90,stop(#ffffff,0),stop(#000000,1)).",
            ));
        }
        return Ok(Paint::LinearGradient { angle, stops });
    }
    if source.starts_with("radial(") {
        let call = parse_required_call(source, "radial", line_number, column)?;
        let stops = call
            .args
            .iter()
            .map(|arg| parse_color_stop(arg, line_number, column))
            .collect::<Result<Vec<_>, _>>()?;
        if stops.is_empty() {
            return Err(error_diag(
                line_number,
                column,
                source.len(),
                "LUMD0240",
                "radial(...) expects at least one stop",
                "Use radial(stop(#ffffff,0),stop(#000000,1)).",
            ));
        }
        return Ok(Paint::RadialGradient { stops });
    }
    if source.starts_with("solid(") {
        let call = parse_required_call(source, "solid", line_number, column)?;
        if call.args.is_empty() {
            return Err(error_diag(
                line_number,
                column,
                source.len(),
                "LUMD0215",
                "solid(...) expects a color",
                "Use solid(#ffffff).",
            ));
        }
        if call.args.len() > 1 {
            return Err(error_diag(
                line_number,
                column,
                source.len(),
                "LUMD0241",
                "solid(...) opacity arguments are parsed but not lowered by this workstream",
                "Use #RRGGBBAA/#AARRGGBB-compatible assets after color semantics are finalized, or use node opacity o(...).",
            ));
        }
        return Ok(Paint::Solid {
            color: parse_color(&call.args[0], line_number, column)?,
        });
    }

    Ok(Paint::Solid {
        color: parse_color(source, line_number, column)?,
    })
}

fn is_modification_line(trimmed: &str) -> bool {
    let tokens = split_top_level_whitespace(trimmed);
    if tokens.len() < 2 {
        return false;
    }

    let Some(reference) = tokens[0].strip_prefix('#') else {
        return false;
    };
    if reference.is_empty() {
        return false;
    }

    reference
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' || ch == '.' || ch == ':')
}

fn parse_color_stop(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<ColorStop, DslDiagnostic> {
    let call = parse_call(source).ok_or_else(|| {
        error_diag(
            line_number,
            column,
            source.len(),
            "LUMD0216",
            "gradient stops must use stop(color,position)",
            "Use linear(90,stop(#ffffff,0),stop(#000000,1)).",
        )
    })?;
    if call.name != "stop" || call.args.len() != 2 {
        return Err(error_diag(
            line_number,
            column,
            source.len(),
            "LUMD0217",
            "gradient stops must use stop(color,position)",
            "Use stop(#ffffff,0).",
        ));
    }
    Ok(ColorStop {
        color: parse_color(&call.args[0], line_number, column)?,
        position: parse_f64(&call.args[1], line_number, column)?,
    })
}

fn parse_color(source: &str, line_number: usize, column: usize) -> Result<Color, DslDiagnostic> {
    let source = source.trim();
    if let Some(token) = source.strip_prefix('$') {
        return Ok(Color::Token {
            token: token.to_owned(),
        });
    }
    if source.starts_with("oklch(") {
        let call = parse_required_call(source, "oklch", line_number, column)?;
        if !(3..=4).contains(&call.args.len()) {
            return Err(error_diag(
                line_number,
                column,
                source.len(),
                "LUMD0218",
                "oklch(...) expects l,c,h and optional alpha",
                "Use oklch(0.72,0.14,250,1).",
            ));
        }
        return Ok(Color::Oklch {
            l: parse_f64(&call.args[0], line_number, column)?,
            c: parse_f64(&call.args[1], line_number, column)?,
            h: parse_f64(&call.args[2], line_number, column)?,
            alpha: if call.args.len() == 4 {
                parse_f64(&call.args[3], line_number, column)?
            } else {
                1.0
            },
        });
    }
    if source.starts_with('#') {
        return Ok(Color::Hex {
            value: normalize_dsl_hex_color(source, line_number, column)?,
        });
    }
    if source.starts_with("rgb(") || source.starts_with("rgba(") {
        return parse_rgb_color(source, line_number, column);
    }
    Err(error_diag(
        line_number,
        column,
        source.len(),
        "LUMD0219",
        format!("invalid color {source}"),
        "Use #RRGGBB, #AARRGGBB, $token, or oklch(l,c,h,a).",
    ))
}

/// CSS `rgb(r,g,b)` / `rgba(r,g,b,a)` compatibility alias. Models reach for it
/// out of CSS habit; we lower it to the canonical hex color instead of failing
/// with `LUMD0219`. Channels are 0-255 (or `NN%`); alpha is 0-1 (or `NN%`). The
/// result is `#RRGGBB`, or `#RRGGBBAA` when alpha is below 1.
fn parse_rgb_color(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<Color, DslDiagnostic> {
    let name = if source.starts_with("rgba(") {
        "rgba"
    } else {
        "rgb"
    };
    let call = parse_required_call(source, name, line_number, column)?;
    let expected = if name == "rgba" { 4 } else { 3 };
    if call.args.len() != expected {
        return Err(invalid_color_diag(source, line_number, column));
    }
    let channel = |raw: &str| -> Result<u8, DslDiagnostic> {
        let trimmed = raw.trim();
        let value = match trimmed.strip_suffix('%') {
            Some(pct) => parse_f64(pct, line_number, column)? / 100.0 * 255.0,
            None => parse_f64(trimmed, line_number, column)?,
        };
        Ok(value.round().clamp(0.0, 255.0) as u8)
    };
    let r = channel(&call.args[0])?;
    let g = channel(&call.args[1])?;
    let b = channel(&call.args[2])?;
    let alpha = if expected == 4 {
        let trimmed = call.args[3].trim();
        let a = match trimmed.strip_suffix('%') {
            Some(pct) => parse_f64(pct, line_number, column)? / 100.0,
            None => parse_f64(trimmed, line_number, column)?,
        };
        (a.clamp(0.0, 1.0) * 255.0).round() as u8
    } else {
        255
    };
    let value = if alpha == 255 {
        format!("#{r:02x}{g:02x}{b:02x}")
    } else {
        format!("#{r:02x}{g:02x}{b:02x}{alpha:02x}")
    };
    Ok(Color::Hex { value })
}

fn parse_font_property(
    call: &Call,
    line_number: usize,
    column: usize,
) -> Result<Vec<DslProperty>, DslDiagnostic> {
    if call.args.len() == 1 && call.args[0].trim().starts_with('$') {
        return Ok(vec![DslProperty::TextStyleToken(parse_token_ref(
            &call.args[0],
            line_number,
            column,
        )?)]);
    }

    Ok(vec![DslProperty::Font(parse_font(
        call,
        line_number,
        column,
    )?)])
}

fn parse_font(call: &Call, line_number: usize, column: usize) -> Result<DslFont, DslDiagnostic> {
    if call.args.len() != 4 {
        return Err(error_diag(
            line_number,
            column,
            call.name.len(),
            "LUMD0220",
            "font(...) expects family,size,weight,align or one typography token",
            "Use font(\"Inter\",16,700,left) or font($type.headline).",
        ));
    }

    Ok(DslFont {
        family: unquote(&call.args[0], line_number, column)?,
        size: parse_scalar(&call.args[1], line_number, column)?,
        weight: parse_u16(&call.args[2], line_number, column)?,
        align: parse_text_align(&call.args[3], line_number, column)?,
    })
}

fn parse_meta_slot(
    call: &Call,
    line_number: usize,
    column: usize,
) -> Result<SlotKey, DslDiagnostic> {
    for arg in &call.args {
        if let Some(value) = arg.strip_prefix("slot=") {
            return parse_slot_key(&unquote_lossy(value), line_number, column);
        }
    }
    Err(error_diag(
        line_number,
        column,
        call.name.len(),
        "LUMD0221",
        "meta(...) currently supports only slot=\"key\"",
        "Use slot(contact.full_name) for compact slot annotations.",
    ))
}

fn parse_padding(
    call: &Call,
    line_number: usize,
    column: usize,
) -> Result<[DslScalar; 4], DslDiagnostic> {
    match call.args.len() {
        1 => {
            let value = parse_scalar(&call.args[0], line_number, column)?;
            Ok([value.clone(), value.clone(), value.clone(), value])
        }
        2 => {
            let vertical = parse_scalar(&call.args[0], line_number, column)?;
            let horizontal = parse_scalar(&call.args[1], line_number, column)?;
            Ok([vertical.clone(), horizontal.clone(), vertical, horizontal])
        }
        4 => Ok([
            parse_scalar(&call.args[0], line_number, column)?,
            parse_scalar(&call.args[1], line_number, column)?,
            parse_scalar(&call.args[2], line_number, column)?,
            parse_scalar(&call.args[3], line_number, column)?,
        ]),
        _ => Err(error_diag(
            line_number,
            column,
            call.name.len(),
            "LUMD0222",
            "padding expects 1, 2, or 4 numeric values",
            "Use pad(12), pad(8,12), or pad(8,12,8,12).",
        )),
    }
}

fn parse_layout_anchor(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<DslLayoutAnchor, DslDiagnostic> {
    match source.trim() {
        "s" | "start" => Ok(DslLayoutAnchor::Start),
        "c" | "center" => Ok(DslLayoutAnchor::Center),
        "e" | "end" => Ok(DslLayoutAnchor::End),
        "sb" | "space_between" | "space-between" => Ok(DslLayoutAnchor::SpaceBetween),
        "stretch" | "st" => Ok(DslLayoutAnchor::Stretch),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0248",
            format!("unknown layout anchor {other}"),
            "Use s/start, c/center, e/end, sb/space_between, or stretch.",
        )),
    }
}

fn parse_page_size(call: &Call, line_number: usize) -> Result<DslPageSize, DslDiagnostic> {
    if call.args.len() != 3 {
        return Err(error_diag(
            line_number,
            1,
            call.name.len(),
            "LUMD0250",
            "size(...) expects width, height, and unit",
            "Use size(1080,1080,px), size(595,842,pt), size(210,297,mm), or size(8.5,11,in).",
        ));
    }

    let width = parse_f64(&call.args[0], line_number, 1)?;
    let height = parse_f64(&call.args[1], line_number, 1)?;
    if width <= 0.0 || height <= 0.0 {
        return Err(error_diag(
            line_number,
            1,
            call.name.len(),
            "LUMD0251",
            "page size dimensions must be positive",
            "Use positive width and height values, for example size(1080,1080,px).",
        ));
    }

    Ok(DslPageSize {
        width,
        height,
        unit: parse_unit(&call.args[2], line_number)?,
    })
}

fn parse_unit(source: &str, line_number: usize) -> Result<Unit, DslDiagnostic> {
    match source.trim() {
        "pt" => Ok(Unit::Pt),
        "px" => Ok(Unit::Px),
        "mm" => Ok(Unit::Mm),
        "in" | "inch" | "inches" => Ok(Unit::In),
        other => Err(error_diag(
            line_number,
            1,
            other.len().max(1),
            "LUMD0252",
            format!("unknown page size unit {other}"),
            "Use pt, px, mm, or in.",
        )),
    }
}

fn parse_page_preset(call: &Call, line_number: usize) -> Result<DslPagePreset, DslDiagnostic> {
    let preset = match call.args[0].as_str() {
        "a4" | "A4" => PagePreset::A4,
        "us_letter" | "letter" => PagePreset::UsLetter,
        "linkedin_ad" => PagePreset::LinkedinAd,
        "envelope_dl" => PagePreset::EnvelopeDl,
        "custom" => PagePreset::Custom,
        other => {
            return Err(error_diag(
                line_number,
                1,
                other.len(),
                "LUMD0223",
                format!("unknown page preset {other}"),
                "Use a4, us_letter, linkedin_ad, envelope_dl, or custom.",
            ));
        }
    };
    let orientation = call
        .args
        .get(1)
        .map(|orientation| match orientation.as_str() {
            "portrait" => Ok(Orientation::Portrait),
            "landscape" => Ok(Orientation::Landscape),
            other => Err(error_diag(
                line_number,
                1,
                other.len(),
                "LUMD0224",
                format!("unknown page orientation {other}"),
                "Use portrait or landscape.",
            )),
        })
        .transpose()?
        .unwrap_or_else(|| default_orientation_for_preset(&preset));

    Ok(DslPagePreset {
        preset,
        orientation,
    })
}

fn default_orientation_for_preset(preset: &PagePreset) -> Orientation {
    match preset {
        PagePreset::LinkedinAd | PagePreset::EnvelopeDl => Orientation::Landscape,
        PagePreset::A4 | PagePreset::UsLetter | PagePreset::Custom => Orientation::Portrait,
    }
}

fn orientation_for_dimensions(width: f64, height: f64) -> Orientation {
    if width >= height {
        Orientation::Landscape
    } else {
        Orientation::Portrait
    }
}

fn parse_dimension(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<DslDimension, DslDiagnostic> {
    let source = source.trim();
    if source.starts_with('$') {
        return Ok(DslDimension::Token(parse_token_ref(
            source,
            line_number,
            column,
        )?));
    }

    match source {
        "hug" => Ok(DslDimension::Hug),
        "fill" => Ok(DslDimension::Fill(None)),
        other if other.starts_with("fill(") => {
            let call = parse_required_call(other, "fill", line_number, column)?;
            expect_arg_count(&call, 1, line_number)?;
            Ok(DslDimension::Fill(Some(parse_f64(
                &call.args[0],
                line_number,
                column,
            )?)))
        }
        other if other.starts_with("fill:") => Ok(DslDimension::Fill(Some(parse_f64(
            other.trim_start_matches("fill:"),
            line_number,
            column,
        )?))),
        other => Ok(DslDimension::Fixed(parse_f64(other, line_number, column)?)),
    }
}

fn parse_parent_ref(source: &str, line_number: usize) -> Result<ParentRef, DslDiagnostic> {
    if let Some(page_id) = source.strip_prefix("page:") {
        Ok(ParentRef::Page(parse_page_id(page_id, line_number, 1)?))
    } else {
        Ok(ParentRef::Node(parse_node_id(source, line_number, 1)?))
    }
}

fn parse_relative_placement(
    source: &str,
    line_number: usize,
) -> Result<RelativePlacement, DslDiagnostic> {
    let trimmed = source.trim();
    if let Some(anchor) = trimmed.strip_prefix("before:") {
        return Ok(RelativePlacement::Before {
            anchor: parse_node_id(anchor, line_number, 1)?,
        });
    }
    if let Some(anchor) = trimmed.strip_prefix("after:") {
        return Ok(RelativePlacement::After {
            anchor: parse_node_id(anchor, line_number, 1)?,
        });
    }
    if let Some(parent) = trimmed.strip_prefix("parent:") {
        return Ok(RelativePlacement::ParentIndex {
            parent: parse_parent_ref(parent, line_number)?,
            index: 0,
        });
    }
    Err(error_diag(
        line_number,
        1,
        trimmed.len().max(1),
        "LUMD0207",
        "clone placement must be before:node, after:node, or parent:node/page:page_id",
        "Use clone(source,new_id,after:anchor), clone(source,new_id,before:anchor), or clone(source,new_id,parent:page:page_a4,index:0).",
    ))
}

fn parse_clone_slot_policy(
    source: &str,
    line_number: usize,
) -> Result<CloneSlotPolicy, DslDiagnostic> {
    match source.trim() {
        "detach" => Ok(CloneSlotPolicy::Detach),
        "copy" => Ok(CloneSlotPolicy::Copy),
        suffix if suffix.starts_with("suffix:") => Ok(CloneSlotPolicy::Suffix(
            suffix.trim_start_matches("suffix:").to_owned(),
        )),
        other => Err(error_diag(
            line_number,
            1,
            other.len().max(1),
            "LUMD0207",
            format!("unknown clone slot policy {other}"),
            "Use slots:detach, slots:copy, or slots:suffix:_variant.",
        )),
    }
}

fn parse_computed_clone_policy(
    source: &str,
    line_number: usize,
) -> Result<ComputedClonePolicy, DslDiagnostic> {
    match source.trim() {
        "clear" => Ok(ComputedClonePolicy::Clear),
        "preserve" => Ok(ComputedClonePolicy::Preserve),
        other => Err(error_diag(
            line_number,
            1,
            other.len().max(1),
            "LUMD0207",
            format!("unknown clone computed policy {other}"),
            "Use computed:clear or computed:preserve.",
        )),
    }
}

fn parse_replace_slot_policy(
    source: &str,
    line_number: usize,
) -> Result<ReplaceSlotPolicy, DslDiagnostic> {
    match source.trim() {
        "detach" => Ok(ReplaceSlotPolicy::Detach),
        "preserve" | "preserve_compatible" => Ok(ReplaceSlotPolicy::PreserveCompatible),
        other => Err(error_diag(
            line_number,
            1,
            other.len().max(1),
            "LUMD0207",
            format!("unknown replace slot policy {other}"),
            "Use slots:detach or slots:preserve.",
        )),
    }
}

fn parse_direction(source: &str) -> Option<AutoLayoutDirection> {
    match source {
        "row" | "h" | "horizontal" => Some(AutoLayoutDirection::Row),
        "column" | "v" | "vertical" => Some(AutoLayoutDirection::Column),
        _ => None,
    }
}

fn parse_text_align(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<TextAlign, DslDiagnostic> {
    match source {
        "left" => Ok(TextAlign::Left),
        "center" => Ok(TextAlign::Center),
        "right" => Ok(TextAlign::Right),
        "justify" => Ok(TextAlign::Justify),
        other => Err(error_diag(
            line_number,
            column,
            other.len(),
            "LUMD0225",
            format!("unknown text alignment {other}"),
            "Use left, center, right, or justify.",
        )),
    }
}

fn parse_text_direction(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<TextDirection, DslDiagnostic> {
    match source.trim() {
        "ltr" => Ok(TextDirection::Ltr),
        "rtl" => Ok(TextDirection::Rtl),
        "auto" => Ok(TextDirection::Auto),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0253",
            format!("unknown text direction {other}"),
            "Use ltr, rtl, or auto.",
        )),
    }
}

#[derive(Clone, Debug)]
struct Call {
    name: String,
    args: Vec<String>,
}

fn parse_call(token: &str) -> Option<Call> {
    let token = token.trim();
    let open = match (token.find('('), token.find('[')) {
        (Some(paren), Some(bracket)) => paren.min(bracket),
        (Some(paren), None) => paren,
        (None, Some(bracket)) => bracket,
        (None, None) => return None,
    };
    let close = token.chars().last()?;
    let opener = token.as_bytes()[open] as char;
    let expected_close = if opener == '(' { ')' } else { ']' };
    if close != expected_close {
        return None;
    }
    let name = token[..open].trim().to_owned();
    let inner = &token[open + 1..token.len() - 1];
    Some(Call {
        name,
        args: split_top_level_commas(inner),
    })
}

fn parse_required_call(
    token: &str,
    expected_name: &str,
    line_number: usize,
    column: usize,
) -> Result<Call, DslDiagnostic> {
    let call = parse_call(token).ok_or_else(|| {
        error_diag(
            line_number,
            column,
            token.len().max(1),
            "LUMD0245",
            format!("malformed {expected_name}(...) call"),
            "Check that the call has balanced parentheses and valid comma-separated arguments.",
        )
    })?;

    if call.name == expected_name {
        Ok(call)
    } else {
        Err(error_diag(
            line_number,
            column,
            token.len().max(1),
            "LUMD0246",
            format!("expected {expected_name}(...), got {}(...)", call.name),
            "Use the expected property function name.",
        ))
    }
}

fn split_top_level_whitespace(source: &str) -> Vec<String> {
    split_top_level(source, char::is_whitespace)
}

fn split_top_level_commas(source: &str) -> Vec<String> {
    split_top_level(source, |ch| ch == ',')
}

fn split_top_level(source: &str, split: impl Fn(char) -> bool) -> Vec<String> {
    let mut result = Vec::new();
    let mut start = 0usize;
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escape = false;

    for (index, ch) in source.char_indices() {
        if escape {
            escape = false;
            continue;
        }
        if ch == '\\' && in_string {
            escape = true;
            continue;
        }
        if ch == '"' {
            in_string = !in_string;
            continue;
        }
        if in_string {
            continue;
        }
        match ch {
            '(' | '[' => depth += 1,
            ')' | ']' => depth -= 1,
            _ => {}
        }
        if depth == 0 && split(ch) {
            let part = source[start..index].trim();
            if !part.is_empty() {
                result.push(part.to_owned());
            }
            start = index + ch.len_utf8();
        }
    }

    let part = source[start..].trim();
    if !part.is_empty() {
        result.push(part.to_owned());
    }
    result
}

fn parse_page_id(source: &str, line_number: usize, column: usize) -> Result<PageId, DslDiagnostic> {
    PageId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0406",
            format!("invalid page id {}", source.trim()),
            "Use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

fn parse_node_id(source: &str, line_number: usize, column: usize) -> Result<NodeId, DslDiagnostic> {
    NodeId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0407",
            format!("invalid node id {}", source.trim()),
            "Use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

fn parse_slot_key(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<SlotKey, DslDiagnostic> {
    SlotKey::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0408",
            format!("invalid slot key {}", source.trim()),
            "Slot keys may use ASCII letters, numbers, dashes, underscores, and dots.",
        )
    })
}

fn parse_slot_id(source: &str, line_number: usize, column: usize) -> Result<SlotId, DslDiagnostic> {
    SlotId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0408",
            format!("invalid slot id {}", source.trim()),
            "Slot IDs may use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

fn parse_paint_id(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<PaintId, DslDiagnostic> {
    PaintId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0409",
            format!("invalid paint id {}", source.trim()),
            "Paint IDs may use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

fn parse_effect_id(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<EffectId, DslDiagnostic> {
    EffectId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0258",
            format!("invalid effect id {}", source.trim()),
            "Effect IDs may use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

/// `true` when the argument can only be a paint/color literal, which
/// disambiguates the optional leading stable id in `stroke(...)` and
/// `shadow(...)` forms.
fn paint_like(source: &str) -> bool {
    let trimmed = source.trim();
    trimmed.starts_with('#')
        || trimmed.starts_with('$')
        || trimmed.starts_with("oklch(")
        || trimmed.starts_with("rgb(")
        || trimmed.starts_with("rgba(")
        || trimmed.starts_with("linear(")
        || trimmed.starts_with("radial(")
        || trimmed.starts_with("solid(")
}

/// Extended stroke grammar (Effects Contract V0):
/// `stroke(id?,paint,w(1)|1,dash(6,4),cap(round),join(round),align(inside))`.
/// The pre-effects `stroke(#111827,2)` form keeps working unchanged.
fn parse_stroke_property(
    call: &Call,
    token: &str,
    line_number: usize,
    column: usize,
) -> Result<DslStroke, DslDiagnostic> {
    let stroke_error = |code: &'static str, message: String| {
        error_diag(
            line_number,
            column,
            token.len(),
            code,
            message,
            "Use stroke(#111827,2) or stroke(stroke_border,#111827,w(1),dash(6,4),cap(round),join(round),align(inside)).",
        )
    };
    if call.args.len() < 2 {
        return Err(stroke_error(
            "LUMD0211",
            "stroke(...) expects color and width".to_owned(),
        ));
    }

    let mut args = call.args.iter();
    let first = args.next().expect("len checked above");
    let (id, paint) = if paint_like(first) {
        (None, parse_paint(first, line_number, column)?)
    } else {
        let id = parse_paint_id(first, line_number, column)?;
        let color = args.next().ok_or_else(|| {
            stroke_error(
                "LUMD0211",
                "stroke(...) with an id still expects color and width".to_owned(),
            )
        })?;
        (Some(id), parse_paint(color, line_number, column)?)
    };

    let mut width: Option<DslScalar> = None;
    let mut stroke = DslStroke::basic(id, paint, DslScalar::Number(0.0));
    for arg in args {
        let trimmed = arg.trim();
        match parse_call(trimmed) {
            Some(option) => match option.name.as_str() {
                "w" | "width" => {
                    if option.args.len() != 1 {
                        return Err(stroke_error(
                            "LUMD0256",
                            "w(...) expects exactly one width value".to_owned(),
                        ));
                    }
                    width = Some(parse_scalar(&option.args[0], line_number, column)?);
                }
                "dash" => {
                    if option.args.is_empty() {
                        return Err(stroke_error(
                            "LUMD0256",
                            "dash(...) expects at least one segment length".to_owned(),
                        ));
                    }
                    let mut pattern = Vec::with_capacity(option.args.len());
                    for value in &option.args {
                        let value = parse_f64(value, line_number, column)?;
                        if value < 0.0 {
                            return Err(stroke_error(
                                "LUMD0256",
                                "dash(...) segment lengths must be non-negative".to_owned(),
                            ));
                        }
                        pattern.push(value);
                    }
                    stroke.dash = Some(pattern);
                }
                "cap" => {
                    if option.args.len() != 1 {
                        return Err(stroke_error(
                            "LUMD0256",
                            "cap(...) expects butt, round, or square".to_owned(),
                        ));
                    }
                    stroke.cap = Some(parse_stroke_cap(&option.args[0], line_number, column)?);
                }
                "join" => {
                    if option.args.len() != 1 {
                        return Err(stroke_error(
                            "LUMD0256",
                            "join(...) expects miter, round, or bevel".to_owned(),
                        ));
                    }
                    stroke.join = Some(parse_stroke_join(&option.args[0], line_number, column)?);
                }
                "align" => {
                    if option.args.len() != 1 {
                        return Err(stroke_error(
                            "LUMD0256",
                            "align(...) expects center, inside, or outside".to_owned(),
                        ));
                    }
                    stroke.align = Some(parse_stroke_align(&option.args[0], line_number, column)?);
                }
                other => {
                    return Err(stroke_error(
                        "LUMD0256",
                        format!("unknown stroke option {other}(...)"),
                    ));
                }
            },
            None => {
                width = Some(parse_scalar(trimmed, line_number, column)?);
            }
        }
    }

    let Some(width) = width else {
        return Err(stroke_error(
            "LUMD0211",
            "stroke(...) requires a width: a bare number or w(...)".to_owned(),
        ));
    };
    stroke.width = width;
    Ok(stroke)
}

fn parse_stroke_cap(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<StrokeCap, DslDiagnostic> {
    match source.trim() {
        "butt" => Ok(StrokeCap::Butt),
        "round" => Ok(StrokeCap::Round),
        "square" => Ok(StrokeCap::Square),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0256",
            format!("unknown stroke cap {other}"),
            "Use cap(butt|round|square).",
        )),
    }
}

fn parse_stroke_join(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<StrokeJoin, DslDiagnostic> {
    match source.trim() {
        "miter" => Ok(StrokeJoin::Miter),
        "round" => Ok(StrokeJoin::Round),
        "bevel" => Ok(StrokeJoin::Bevel),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0256",
            format!("unknown stroke join {other}"),
            "Use join(miter|round|bevel).",
        )),
    }
}

fn parse_stroke_align(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<StrokeAlign, DslDiagnostic> {
    match source.trim() {
        "center" => Ok(StrokeAlign::Center),
        "inside" => Ok(StrokeAlign::Inside),
        "outside" => Ok(StrokeAlign::Outside),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0256",
            format!("unknown stroke alignment {other}"),
            "Use align(center|inside|outside).",
        )),
    }
}

/// `shadow(id?,#color,o(0.18),x(0),y(8),blur(24),spread(0))`. Omitted
/// channels keep their defaults (opacity 1, offsets/blur/spread 0).
fn parse_shadow_property(
    call: &Call,
    token: &str,
    line_number: usize,
    column: usize,
) -> Result<DslShadow, DslDiagnostic> {
    let shadow_error = |message: String| {
        error_diag(
            line_number,
            column,
            token.len(),
            "LUMD0257",
            message,
            "Use shadow(shadow_soft,#000000,o(0.18),x(0),y(8),blur(24),spread(0)).",
        )
    };
    if call.args.is_empty() {
        return Err(shadow_error("shadow(...) expects a color".to_owned()));
    }

    // Compatibility alias for the CSS `box-shadow` ordering models reach for out
    // of habit: `shadow(x, y[, blur[, spread]], color)` with the color LAST and
    // every preceding argument a bare number. We accept it rather than reject it
    // because the model emits it persistently and the intent is unambiguous; the
    // canonical `shadow(color, o(), x(), y(), blur(), spread())` form is still
    // preferred. Detection is conservative — it never fires when the first arg is
    // a color (canonical form) or when a leading non-numeric id is present
    // (`shadow(shadow_soft, #000000, ...)`), so existing grammars are untouched.
    let n = call.args.len();
    let positional = n >= 2
        && !paint_like(&call.args[0])
        && paint_like(&call.args[n - 1])
        && call.args[..n - 1]
            .iter()
            .all(|arg| parse_call(arg.trim()).is_none() && parse_f64(arg, 0, 0).is_ok());
    if positional {
        let color = parse_color(&call.args[n - 1], line_number, column)?;
        let mut shadow = DslShadow {
            id: None,
            color,
            opacity: 1.0,
            x: 0.0,
            y: 0.0,
            blur: 0.0,
            spread: 0.0,
        };
        let offsets = &call.args[..n - 1];
        if let Some(v) = offsets.first() {
            shadow.x = parse_f64(v, line_number, column)?;
        }
        if let Some(v) = offsets.get(1) {
            shadow.y = parse_f64(v, line_number, column)?;
        }
        if let Some(v) = offsets.get(2) {
            shadow.blur = parse_f64(v, line_number, column)?;
        }
        if let Some(v) = offsets.get(3) {
            shadow.spread = parse_f64(v, line_number, column)?;
        }
        return Ok(shadow);
    }

    let mut args = call.args.iter();
    let first = args.next().expect("non-empty checked above");
    let (id, color) = if paint_like(first) {
        (None, parse_color(first, line_number, column)?)
    } else {
        let id = parse_effect_id(first, line_number, column)?;
        let color = args.next().ok_or_else(|| {
            shadow_error("shadow(...) with an id still expects a color".to_owned())
        })?;
        (Some(id), parse_color(color, line_number, column)?)
    };

    let mut shadow = DslShadow {
        id,
        color,
        opacity: 1.0,
        x: 0.0,
        y: 0.0,
        blur: 0.0,
        spread: 0.0,
    };
    for arg in args {
        let Some(option) = parse_call(arg.trim()) else {
            return Err(shadow_error(format!("unknown shadow argument {arg}")));
        };
        if option.args.len() != 1 {
            return Err(shadow_error(format!(
                "{}(...) expects exactly one numeric value",
                option.name
            )));
        }
        let value = parse_f64(&option.args[0], line_number, column)?;
        match option.name.as_str() {
            "o" | "opacity" => shadow.opacity = value,
            "x" => shadow.x = value,
            "y" => shadow.y = value,
            "blur" => shadow.blur = value,
            "spread" => shadow.spread = value,
            other => {
                return Err(shadow_error(format!("unknown shadow option {other}(...)")));
            }
        }
    }
    Ok(shadow)
}

fn parse_asset_id(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<AssetId, DslDiagnostic> {
    AssetId::new(source.trim()).map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0410",
            format!("invalid asset id {}", source.trim()),
            "Asset IDs may use ASCII letters, numbers, dashes, or underscores.",
        )
    })
}

fn parse_f64(source: &str, line_number: usize, column: usize) -> Result<f64, DslDiagnostic> {
    let value = source.trim().parse::<f64>().map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0226",
            format!("expected numeric value, got {source}"),
            "Use decimal numerics such as 24 or 24.5.",
        )
    })?;
    if !value.is_finite() {
        return Err(error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0249",
            format!("numeric value must be finite, got {source}"),
            "Use finite decimal numerics; NaN and infinity are not valid design geometry.",
        ));
    }
    Ok(value)
}

fn parse_positive_f64(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<f64, DslDiagnostic> {
    let value = parse_f64(source, line_number, column)?;
    if value <= 0.0 {
        return Err(error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0255",
            "numeric value must be positive",
            "Use a positive decimal numeric value.",
        ));
    }
    Ok(value)
}

fn parse_scalar(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<DslScalar, DslDiagnostic> {
    let trimmed = source.trim();
    if trimmed.starts_with('$') {
        Ok(DslScalar::Token(parse_token_ref(
            trimmed,
            line_number,
            column,
        )?))
    } else {
        Ok(DslScalar::Number(parse_f64(source, line_number, column)?))
    }
}

fn parse_positive_scalar(
    source: &str,
    line_number: usize,
    column: usize,
    label: &str,
) -> Result<DslScalar, DslDiagnostic> {
    let scalar = parse_scalar(source, line_number, column)?;
    if let DslScalar::Number(value) = scalar {
        if value <= 0.0 {
            return Err(error_diag(
                line_number,
                column,
                source.len().max(1),
                "LUMD0254",
                format!("{label} must be positive"),
                "Use a positive numeric value or a token reference.",
            ));
        }
        Ok(DslScalar::Number(value))
    } else {
        Ok(scalar)
    }
}

fn parse_token_ref(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<String, DslDiagnostic> {
    let trimmed = source.trim();
    let Some(token) = trimmed.strip_prefix('$') else {
        return Err(error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0411",
            format!("invalid token reference {source}"),
            "Use token references like $space.md or $type.headline.",
        ));
    };
    if token.is_empty()
        || !token
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
    {
        return Err(error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0411",
            format!("invalid token reference {source}"),
            "Use token references like $space.md or $type.headline.",
        ));
    }
    Ok(token.to_owned())
}

fn parse_u16(source: &str, line_number: usize, column: usize) -> Result<u16, DslDiagnostic> {
    source.trim().parse::<u16>().map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0227",
            format!("expected integer value, got {source}"),
            "Use integer font weights such as 400, 600, or 700.",
        )
    })
}

fn parse_positive_u16(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<u16, DslDiagnostic> {
    let value = parse_u16(source, line_number, column)?;
    if value == 0 {
        return Err(error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0255",
            "max_lines must be positive",
            "Use max_lines(1) or a larger integer.",
        ));
    }
    Ok(value)
}

fn parse_usize(source: &str, line_number: usize, column: usize) -> Result<usize, DslDiagnostic> {
    source.trim().parse::<usize>().map_err(|_| {
        error_diag(
            line_number,
            column,
            source.len().max(1),
            "LUMD0228",
            format!("expected non-negative integer, got {source}"),
            "Use an insertion index such as 0 or 1.",
        )
    })
}

fn parse_bool(source: &str, line_number: usize, column: usize) -> Result<bool, DslDiagnostic> {
    match source.trim() {
        "true" => Ok(true),
        "false" => Ok(false),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0229",
            format!("expected boolean value, got {other}"),
            "Use true or false.",
        )),
    }
}

fn parse_flip(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<DslProperty, DslDiagnostic> {
    match source.trim() {
        "x" | "horizontal" => Ok(DslProperty::Flip { x: true, y: false }),
        "y" | "vertical" => Ok(DslProperty::Flip { x: false, y: true }),
        "both" | "xy" => Ok(DslProperty::Flip { x: true, y: true }),
        "none" => Ok(DslProperty::Flip { x: false, y: false }),
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0242",
            format!("unknown flip axis {other}"),
            "Use flip(x), flip(y), flip(both), or flip(none).",
        )),
    }
}

fn expect_arg_count(call: &Call, expected: usize, line_number: usize) -> Result<(), DslDiagnostic> {
    if call.args.len() == expected {
        Ok(())
    } else {
        Err(error_diag(
            line_number,
            1,
            call.name.len(),
            "LUMD0230",
            format!(
                "{}(...) expects {} argument(s), got {}",
                call.name,
                expected,
                call.args.len()
            ),
            "Check the function call arity.",
        ))
    }
}

fn is_quoted(source: &str) -> bool {
    source.starts_with('"') && source.ends_with('"')
}

fn unquote(source: &str, line_number: usize, column: usize) -> Result<String, DslDiagnostic> {
    let source = source.trim();
    if !is_quoted(source) {
        return Ok(source.to_owned());
    }
    let inner = &source[1..source.len() - 1];
    let mut result = String::new();
    let mut escape = false;
    for ch in inner.chars() {
        if escape {
            result.push(match ch {
                'n' => '\n',
                't' => '\t',
                '"' => '"',
                '\\' => '\\',
                other => other,
            });
            escape = false;
        } else if ch == '\\' {
            escape = true;
        } else {
            result.push(ch);
        }
    }
    if escape {
        return Err(error_diag(
            line_number,
            column,
            source.len(),
            "LUMD0231",
            "unterminated escape sequence",
            "Remove the trailing backslash or escape it as \\\\.",
        ));
    }
    Ok(result)
}

fn unquote_lossy(source: &str) -> String {
    unquote(source, 1, 1).unwrap_or_else(|_| source.trim_matches('"').to_owned())
}

/// Deterministic slot id derivation (slug + FNV-1a 64). Public because
/// binding surfaces (lumen-wasm) expose it so editor-side mirrors can be
/// pinned against the engine instead of drifting silently.
pub fn slot_id_for_key(key: &SlotKey) -> SlotId {
    SlotId::from(format!(
        "slot_{}_{:016x}",
        stable_slug(key.as_str()),
        stable_hash64(key.as_str())
    ))
}

fn stable_slug(source: &str) -> String {
    let slug: String = source
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '_' })
        .collect();
    if slug.is_empty() {
        "slot".to_owned()
    } else {
        slug
    }
}

fn stable_hash64(source: &str) -> u64 {
    const FNV_OFFSET: u64 = 0xcbf29ce484222325;
    const FNV_PRIME: u64 = 0x100000001b3;

    let mut hash = FNV_OFFSET;
    for byte in source.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

fn normalize_dsl_hex_color(
    source: &str,
    line_number: usize,
    column: usize,
) -> Result<String, DslDiagnostic> {
    let hex = source.trim();
    let digits = hex.strip_prefix('#').unwrap_or(hex);
    if digits.len() != 6 && digits.len() != 8 {
        return Err(invalid_color_diag(hex, line_number, column));
    }
    if !digits.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(invalid_color_diag(hex, line_number, column));
    }

    let normalized = digits.to_ascii_lowercase();
    if normalized.len() == 6 {
        Ok(format!("#{normalized}"))
    } else {
        let alpha = &normalized[0..2];
        let red = &normalized[2..4];
        let green = &normalized[4..6];
        let blue = &normalized[6..8];
        Ok(format!("#{red}{green}{blue}{alpha}"))
    }
}

fn invalid_color_diag(source: &str, line_number: usize, column: usize) -> DslDiagnostic {
    error_diag(
        line_number,
        column,
        source.len().max(1),
        "LUMD0219",
        format!("invalid color {source}"),
        "Use #RRGGBB, #AARRGGBB, $token, or oklch(l,c,h,a).",
    )
}

fn skip_ascii_whitespace(source: &str, mut cursor: usize) -> usize {
    while cursor < source.len() && source.as_bytes()[cursor].is_ascii_whitespace() {
        cursor += 1;
    }
    cursor
}

fn error_diag(
    line: usize,
    column: usize,
    length: usize,
    code: impl Into<String>,
    message: impl Into<String>,
    hint: impl Into<String>,
) -> DslDiagnostic {
    DslDiagnostic {
        diagnostic: Diagnostic::error(Phase::Dsl, code, message, None).with_hint(hint),
        span: SourceSpan {
            line,
            column,
            length,
        },
    }
}

fn warning_diag(
    line: usize,
    column: usize,
    length: usize,
    code: impl Into<String>,
    message: impl Into<String>,
    hint: impl Into<String>,
) -> DslDiagnostic {
    DslDiagnostic {
        diagnostic: Diagnostic::warning(Phase::Dsl, code, message, None).with_hint(hint),
        span: SourceSpan {
            line,
            column,
            length,
        },
    }
}
