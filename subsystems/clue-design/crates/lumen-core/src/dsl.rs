#![allow(clippy::result_large_err)]

use crate::scene::ColorStop;
use crate::{
    AssetId, AutoLayoutDirection, AutoLayoutNode, AutoLayoutProps, Color, Diagnostic,
    DiagnosticSeverity, Fill, ImageNode, LineNode, Node, NodeId, NodeKind, Operation,
    OperationError, OperationReport, Orientation, Page, PageId, PagePreset, PageSize, Paint,
    PaintId, ParentRef, Phase, Scene, SizeSpec, Slot, SlotId, SlotKey, Stroke, TextAlign, TextNode,
    Unit, VectorNode,
};
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

pub fn compile_dsl(source: &str) -> DslCompileOutput {
    let mut session = DslCompileSession::empty();
    session.compile_block(source)
}

pub fn compile_dsl_into_scene(source: &str, scene: &mut Scene) -> DslSceneCompileOutput {
    let mut session = DslCompileSession::new(scene.clone());
    let compile_output = session.compile_block(source);

    if compile_output.has_errors() {
        return DslSceneCompileOutput {
            compile_output,
            operation_report: None,
            operation_error: None,
        };
    }

    match scene.apply_operations_checked(compile_output.operations.clone()) {
        Ok(report) => DslSceneCompileOutput {
            compile_output,
            operation_report: Some(report),
            operation_error: None,
        },
        Err(error) => DslSceneCompileOutput {
            compile_output,
            operation_report: None,
            operation_error: Some(error),
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

    pub fn compile_block(&mut self, source: &str) -> DslCompileOutput {
        let starting_context = self.parser_context.clone();
        let (parse, parsed_context) =
            DslParser::new_with_context(source, starting_context.clone()).parse_with_context();
        let mut compiler = DslCompiler::new(
            parse.document.clone(),
            parse.diagnostics.clone(),
            &mut self.scene,
            &mut self.parent_stack,
            &mut self.emitted_slots,
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
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslCompileOutput {
    pub document: DslDocument,
    pub operations: Vec<Operation>,
    pub diagnostics: Vec<DslDiagnostic>,
    pub halted_at: Option<DslHalt>,
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
}

#[derive(Clone, Debug, PartialEq)]
pub struct DslPagePreset {
    pub preset: PagePreset,
    pub orientation: Orientation,
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
    Fill(DslFill),
    Stroke(DslStroke),
    Font(DslFont),
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
    Grow(DslScalar),
    TextStyleToken(String),
    LayoutAnchor {
        axis: DslLayoutAxis,
        anchor: DslLayoutAnchor,
    },
    LineTo(f64, f64),
    Name(String),
    Token(String),
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
        target: NodeId,
    },
    Parent {
        target: NodeId,
        new_parent: ParentRef,
        index: usize,
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
        target: NodeId,
    },
    Replace {
        target: NodeId,
    },
    Ungroup {
        target: NodeId,
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
        for token in property_tokens {
            let call = parse_call(&token).ok_or_else(|| {
                error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0203",
                    format!("unsupported page property {token}"),
                    "Only preset(name,orientation) is supported in DSL; keep rich page config in scene metadata.",
                )
            })?;
            if call.name != "preset" || call.args.is_empty() {
                return Err(error_diag(
                    line_number,
                    1,
                    token.len(),
                    "LUMD0204",
                    format!("unsupported page property {}", call.name),
                    "Use preset(a4,portrait) or omit page metadata from DSL.",
                ));
            }
            preset = Some(parse_page_preset(&call, line_number)?);
        }

        Ok(DslPage { id, preset })
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
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::Delete {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
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
                DslDirective::Parent {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                    new_parent: parse_parent_ref(&call.args[1], line_number)?,
                    index: if call.args.len() == 3 {
                        parse_usize(&call.args[2], line_number, 1)?
                    } else {
                        0
                    },
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
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::Clone {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                }
            }
            "replace" => {
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::Replace {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
                }
            }
            "ungroup" => {
                expect_arg_count(&call, 1, line_number)?;
                DslDirective::Ungroup {
                    target: parse_node_id(&call.args[0], line_number, 1)?,
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

struct DslCompiler<'a> {
    document: DslDocument,
    operations: Vec<Operation>,
    diagnostics: Vec<DslDiagnostic>,
    halted_at: Option<DslHalt>,
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
    ) -> Self {
        Self {
            document,
            operations: Vec::new(),
            diagnostics,
            halted_at: None,
            scene,
            parent_stack,
            emitted_slots,
        }
    }

    fn compile(&mut self, parse_halt: Option<DslHalt>) -> DslCompileOutput {
        for line in self.document.lines.clone() {
            if parse_halt
                .as_ref()
                .is_some_and(|halt| line.line_number >= halt.line)
            {
                break;
            }

            if let Err(diagnostic) = self.lower_line(&line) {
                self.halted_at = Some(DslHalt {
                    line: diagnostic.span.line,
                    code: diagnostic.diagnostic.code.clone(),
                });
                self.diagnostics.push(diagnostic);
                break;
            }
        }

        DslCompileOutput {
            document: self.document.clone(),
            operations: self.operations.clone(),
            diagnostics: self.diagnostics.clone(),
            halted_at: self.halted_at.clone().or(parse_halt),
        }
    }

    fn lower_line(&mut self, line: &DslLine) -> Result<(), DslDiagnostic> {
        match &line.kind {
            DslLineKind::Comment(_) | DslLineKind::Checkpoint(_) => Ok(()),
            DslLineKind::Page(page) => self.lower_page(line, page),
            DslLineKind::Element(element) => self.lower_element(line, element),
            DslLineKind::Directive(directive) => self.lower_directive(line, directive),
            DslLineKind::Modification(_) => Err(error_diag(
                line.line_number,
                1,
                line.raw.len().max(1),
                "LUMD0701",
                "modify lines are parsed but not lowered in this workstream",
                "Use structured operations for complex patching until modify-line semantics are designed.",
            )),
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

        let preset = page.preset.clone().unwrap_or_else(|| DslPagePreset {
            preset: PagePreset::A4,
            orientation: default_orientation_for_preset(&PagePreset::A4),
        });

        let (width, height, unit) = page_size_for_preset(&preset.preset, &preset.orientation);

        let page_model = Page {
            id: page.id.clone(),
            name: page.id.to_string(),
            size: PageSize {
                width,
                height,
                unit,
                preset: Some(preset.preset),
                orientation: preset.orientation,
            },
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

        Ok(())
    }

    fn lower_directive(
        &mut self,
        line: &DslLine,
        directive: &DslDirective,
    ) -> Result<(), DslDiagnostic> {
        match directive {
            DslDirective::Delete { target } => {
                self.emit_operation(
                    line,
                    Operation::RemoveNode {
                        node_id: target.clone(),
                    },
                )?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Parent {
                target,
                new_parent,
                index,
            } => {
                self.emit_operation(
                    line,
                    Operation::MoveNode {
                        node_id: target.clone(),
                        new_parent: new_parent.clone(),
                        index: *index,
                    },
                )?;
                self.prune_parent_stack();
                Ok(())
            }
            DslDirective::Before { .. }
            | DslDirective::After { .. }
            | DslDirective::Clone { .. }
            | DslDirective::Replace { .. }
            | DslDirective::Ungroup { .. }
            | DslDirective::Undo { .. }
            | DslDirective::Redo { .. }
            | DslDirective::Override { .. }
            | DslDirective::DesignSystem { .. } => Err(error_diag(
                line.line_number,
                1,
                line.raw.len().max(1),
                "LUMD0700",
                "directive is parsed but not lowered by this workstream",
                "Keep this syntax for future operation-history, clone/replace, or brand-kit workstreams.",
            )),
        }
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
    error_diag(
        line.line_number,
        1,
        line.raw.len().max(1),
        "LUMD0800",
        format!("operation {} failed during DSL lowering: {}", error.code, error.message),
        "The DSL line parsed, but applying the corresponding structured operation failed against the current draft scene.",
    )
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
            expect_arg_count(&call, 2, line_number)?;
            vec![DslProperty::Size(
                parse_dimension(&call.args[0], line_number, column)?,
                parse_dimension(&call.args[1], line_number, column)?,
            )]
        }
        "fill" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::Fill(DslFill {
                id: None,
                paint: parse_paint(&call.args[0], line_number, column)?,
            })]
        }
        "f" => parse_fill_list(&call.args.join(","), line_number, column)?
            .into_iter()
            .map(DslProperty::Fill)
            .collect(),
        "stroke" => {
            if call.args.len() != 2 {
                return Err(error_diag(
                    line_number,
                    column,
                    token.len(),
                    "LUMD0211",
                    "stroke(...) expects color and width",
                    "Use stroke(#111827,2).",
                ));
            }
            vec![DslProperty::Stroke(DslStroke {
                id: None,
                paint: parse_paint(&call.args[0], line_number, column)?,
                width: parse_scalar(&call.args[1], line_number, column)?,
            })]
        }
        "st" => parse_stroke_list(&call.args.join(","), line_number, column)?
            .into_iter()
            .map(DslProperty::Stroke)
            .collect(),
        "font" => parse_font_property(&call, line_number, column)?,
        "style" | "text_style" => {
            expect_arg_count(&call, 1, line_number)?;
            vec![DslProperty::TextStyleToken(parse_token_ref(
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
            style_token: None,
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
            DslProperty::Stroke(stroke) => {
                let id = stroke.id.clone().unwrap_or_else(|| {
                    stroke_index += 1;
                    PaintId::from(format!("paint_{}_stroke_{}", node.id, stroke_index))
                });
                let (width, width_token) = match &stroke.width {
                    DslScalar::Number(width) => (*width, None),
                    DslScalar::Token(token) => (0.0, Some(token.clone())),
                };
                node.strokes.push(Stroke {
                    id,
                    paint: stroke.paint.clone(),
                    width,
                    width_token,
                });
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
                diagnostics.push(warning_diag(
                    line_number,
                    1,
                    node.id.as_str().len(),
                    "LUMD0704",
                    "layout anchors are parsed but not lowered in this workstream",
                    "Center/end/space-between alignment belongs to engine/slots-layout once the scene contract stores alignment.",
                ));
            }
            DslProperty::LineTo(x, y) => {
                if let NodeKind::Line(line) = &mut node.kind {
                    line.x2 = *x;
                    line.y2 = *y;
                }
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
        }
    }
}

fn ensure_layout(node: &mut Node) -> &mut AutoLayoutProps {
    node.layout.get_or_insert(AutoLayoutProps {
        gap: 0.0,
        gap_token: None,
        padding: [0.0; 4],
        padding_token: None,
        grow: 0.0,
    })
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
            Ok(DslStroke {
                id: Some(parse_paint_id(&args[0], line_number, column)?),
                paint: parse_paint(&args[1], line_number, column)?,
                width,
            })
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
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' || ch == '.')
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
    Err(error_diag(
        line_number,
        column,
        source.len(),
        "LUMD0219",
        format!("invalid color {source}"),
        "Use #RRGGBB, #AARRGGBB, $token, or oklch(l,c,h,a).",
    ))
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
        other => Err(error_diag(
            line_number,
            column,
            other.len().max(1),
            "LUMD0248",
            format!("unknown layout anchor {other}"),
            "Use s/start, c/center, e/end, or sb/space_between.",
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

fn page_size_for_preset(preset: &PagePreset, orientation: &Orientation) -> (f64, f64, Unit) {
    let (base_width, base_height, unit): (f64, f64, Unit) = match preset {
        PagePreset::A4 => (210.0, 297.0, Unit::Mm),
        PagePreset::UsLetter => (8.5, 11.0, Unit::In),
        PagePreset::LinkedinAd => (1200.0, 627.0, Unit::Px),
        PagePreset::EnvelopeDl => (220.0, 110.0, Unit::Mm),
        PagePreset::Custom => (210.0, 297.0, Unit::Mm),
    };
    let short_side = base_width.min(base_height);
    let long_side = base_width.max(base_height);

    match orientation {
        Orientation::Portrait => (short_side, long_side, unit),
        Orientation::Landscape => (long_side, short_side, unit),
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

fn slot_id_for_key(key: &SlotKey) -> SlotId {
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
