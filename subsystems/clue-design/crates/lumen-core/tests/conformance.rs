use lumen_core::validation::validate_scene;
use lumen_core::{
    AssetId, BindingHint, BrandKitId, Color, CornerRadii, Diagnostic, DiagnosticSeverity,
    DiagnosticSubject, DocumentId, DocumentPatch, ExportAdapter, ExportArtifact, ExportError,
    ExportFormat, ExportProfile, ExportPurpose, ExportRequest, ExportResult, FieldPatch, Fill,
    FocalPoint, ImageFitMode, ImageNode, ImagePolicy, Medium, Node, NodeId, NodeKind, NodePatch,
    Operation, OptionalFieldPatch, Orientation, OverflowPolicy, Page, PageId, PagePreset, PageSize,
    Paint, PaintId, ParentRef, PdfIntent, Phase, RasterScale, RenderIntent, RenderManifest,
    RenderTarget, RendererAdapter, RendererError, Scene, SizeSpec, Slot, SlotId, SlotKey,
    SlotScope, Stroke, TextAlign, TextNode, Transform, Unit, ValidationFixtures,
};

const MINIMAL_SCENE: &str = include_str!("../fixtures/minimal_scene.json");
const VALID_MULTI_PAGE_SLOTS: &str =
    include_str!("../fixtures/conformance/valid_multi_page_slots.json");
const INVALID_TREE_REFERENCE: &str =
    include_str!("../fixtures/conformance/invalid_tree_reference.json");
const INVALID_SLOT_EXPORT: &str = include_str!("../fixtures/conformance/invalid_slot_export.json");

#[test]
fn valid_conformance_fixtures_have_no_diagnostic_errors() {
    for (name, json) in valid_fixtures() {
        let scene = decode_scene(name, json);
        assert_no_diagnostic_errors(name, &scene);
    }
}

#[test]
fn invalid_tree_fixture_exposes_expected_contract_diagnostics() {
    let scene = decode_scene("invalid_tree_reference", INVALID_TREE_REFERENCE);
    let signatures = diagnostic_signatures(&scene);
    let expected = sorted_signatures(vec![
        signature("error", "validation", "LUMV0300"),
        signature("error", "validation", "LUMV0301"),
    ]);

    assert_eq!(signatures, expected);
    assert_has_error(&scene);
}

#[test]
fn invalid_slot_export_fixture_exposes_expected_contract_diagnostics() {
    let scene = decode_scene("invalid_slot_export", INVALID_SLOT_EXPORT);
    let signatures = diagnostic_signatures(&scene);
    let expected = sorted_signatures(vec![
        signature("error", "validation", "LUMV0500"),
        signature("warning", "validation", "LUMV0501"),
        signature("error", "validation", "LUMV0502"),
        signature("error", "validation", "LUMV0510"),
        signature("error", "validation", "LUMV0600"),
        signature("error", "validation", "LUMV0601"),
        signature("error", "validation", "LUMV0602"),
    ]);

    assert_eq!(signatures, expected);
    assert_has_error(&scene);
}

#[test]
fn valid_fixture_snapshots_round_trip_canonically() {
    for (name, json) in valid_fixtures() {
        let scene = decode_scene(name, json);
        let first = stable_scene_json(&scene);
        let decoded: Scene = serde_json::from_str(&first).expect("canonical JSON decodes");
        let second = stable_scene_json(&decoded);

        assert_eq!(scene, decoded, "{name} changed during canonical decode");
        assert_eq!(first, second, "{name} serialization is not deterministic");
    }
}

#[test]
fn operation_replay_matches_the_shared_multi_page_slot_fixture() {
    let fixture = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);
    let replayed = replay_multi_page_slot_scene();

    assert_eq!(replayed, fixture);
    assert_no_diagnostic_errors("replayed_multi_page_slots", &replayed);
}

#[test]
fn finalization_remains_validation_gated_and_blocks_later_mutation() {
    let mut scene = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);

    scene
        .apply_operation(Operation::FinalizeTemplate {
            template_revision_id: lumen_core::TemplateRevisionId::from(
                "template_rev_conformance_1",
            ),
        })
        .expect("valid fixture finalizes");

    let error = scene
        .apply_operation(Operation::UpdateDocument {
            patch: DocumentPatch {
                title: lumen_core::FieldPatch::Set("Illegal edit".to_owned()),
                ..DocumentPatch::default()
            },
        })
        .expect_err("finalized scenes reject mutation");

    assert_eq!(error.code, "op.finalized_scene");
}

#[test]
fn mock_renderer_adapter_consumes_the_scene_contract_without_redefining_it() {
    let scene = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);
    let renderer = MockRenderer;

    let manifest = renderer
        .render(
            &scene,
            RenderTarget::KonvaScene,
            RenderIntent::EditorPreview,
            &[PageId::from("page_a4")],
        )
        .expect("mock renderer accepts valid scene");

    assert_eq!(manifest.target, RenderTarget::KonvaScene);
    assert_eq!(manifest.page_ids, vec![PageId::from("page_a4")]);
    assert_eq!(manifest.mime_type, "application/vnd.abm-design.konva+json");
    assert!(manifest
        .sidecar_json
        .as_deref()
        .is_some_and(|sidecar| sidecar.contains("\"scene_schema_version\":1")));
}

#[test]
fn mock_editor_boundary_consumes_scene_and_emits_structured_operations() {
    let scene = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);
    let editor = MockEditor;

    let operation = editor
        .move_node_operation(&scene, &NodeId::from("node_cta"), 32.0, 248.0)
        .expect("editor emits operation for existing node");

    match &operation {
        Operation::UpdateNode { node_id, patch } => {
            assert_eq!(node_id, &NodeId::from("node_cta"));
            assert!(matches!(patch.transform, FieldPatch::Set(_)));
        }
        other => panic!("editor must emit a structured update operation, got {other:?}"),
    }

    let mut next = scene.clone();
    next.apply_operation(operation)
        .expect("core accepts editor operation");

    assert_eq!(next.nodes[&NodeId::from("node_cta")].transform.x, 32.0);
    assert_eq!(next.nodes[&NodeId::from("node_cta")].transform.y, 248.0);
    assert_eq!(scene.nodes[&NodeId::from("node_cta")].transform.x, 24.0);
    assert_no_diagnostic_errors("mock_editor_result", &next);

    let missing = editor
        .move_node_operation(&scene, &NodeId::from("node_missing"), 0.0, 0.0)
        .expect_err("missing editor target returns diagnostic");
    assert_eq!(missing.severity, DiagnosticSeverity::Error);
    assert_eq!(missing.phase, Phase::Operation);
    assert_eq!(missing.code, "mock_editor.node_missing");
}

#[test]
fn mock_export_adapter_consumes_export_request_contract() {
    let scene = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);
    let adapter = MockExportAdapter;
    let request = ExportRequest {
        profile: scene
            .export_profiles
            .iter()
            .find(|profile| profile.name == "agent_png")
            .expect("agent PNG profile exists")
            .clone(),
        page_ids: vec![PageId::from("page_linkedin_ad")],
        purpose: ExportPurpose::AgentCritique,
    };

    let result = adapter
        .export(&scene, &request)
        .expect("mock export succeeds");

    assert!(result
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].format, ExportFormat::Png);
    assert_eq!(
        result.artifacts[0].page_id,
        Some(PageId::from("page_linkedin_ad"))
    );
    assert_eq!(result.artifacts[0].mime_type, "image/png");
}

#[test]
fn mock_agent_boundary_consumes_scene_operations_and_diagnostics() {
    let scene = decode_scene("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS);
    let agent = MockAgent;

    let accepted = agent.apply_and_validate(
        &scene,
        vec![Operation::UpdateNode {
            node_id: NodeId::from("node_ad_headline"),
            patch: NodePatch {
                kind: FieldPatch::Set(NodeKind::Text(TextNode {
                    content: "A better path to higher-fit demand".to_owned(),
                    font_family: "Inter".to_owned(),
                    font_size: 54.0,
                    font_weight: 800,
                    align: TextAlign::Left,
                })),
                ..NodePatch::default()
            },
        }],
    );

    assert!(accepted.accepted);
    assert_eq!(accepted.applied_operations, 1);
    assert!(accepted
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
    assert_eq!(
        text_content(&accepted.scene, "node_ad_headline"),
        "A better path to higher-fit demand"
    );
    assert_eq!(
        text_content(&scene, "node_ad_headline"),
        "A sharper plan for patient acquisition"
    );

    let rejected = agent.apply_and_validate(
        &scene,
        vec![Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_account_name"),
            node_id: NodeId::from("node_missing"),
        }],
    );

    assert!(!rejected.accepted);
    assert_eq!(rejected.applied_operations, 0);
    assert!(rejected
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "op.node_missing"));
    assert_eq!(rejected.scene, scene);
}

struct MockRenderer;

impl RendererAdapter for MockRenderer {
    fn render(
        &self,
        scene: &Scene,
        target: RenderTarget,
        intent: RenderIntent,
        page_ids: &[PageId],
    ) -> Result<RenderManifest, RendererError> {
        for page_id in page_ids {
            if !scene.pages.contains_key(page_id) {
                return Err(RendererError::new(
                    "mock_render.page_missing",
                    format!("missing page {page_id}"),
                ));
            }
        }

        Ok(RenderManifest {
            mime_type: render_mime_type(&target).to_owned(),
            target,
            page_ids: page_ids.to_vec(),
            bytes: None,
            sidecar_json: Some(
                serde_json::json!({
                    "intent": intent,
                    "scene_schema_version": scene.schema_version
                })
                .to_string(),
            ),
        })
    }
}

struct MockEditor;

impl MockEditor {
    fn move_node_operation(
        &self,
        scene: &Scene,
        node_id: &NodeId,
        x: f64,
        y: f64,
    ) -> Result<Operation, Diagnostic> {
        let current = scene.nodes.get(node_id).ok_or_else(|| {
            Diagnostic::error(
                Phase::Operation,
                "mock_editor.node_missing",
                format!("cannot edit missing node {node_id}"),
                Some(DiagnosticSubject::Node(node_id.clone())),
            )
        })?;
        let mut transform = current.transform.clone();
        transform.x = x;
        transform.y = y;

        Ok(Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: NodePatch {
                transform: FieldPatch::Set(transform),
                ..NodePatch::default()
            },
        })
    }
}

struct MockExportAdapter;

impl ExportAdapter for MockExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError> {
        for page_id in &request.page_ids {
            if !scene.pages.contains_key(page_id) {
                return Err(ExportError::new(
                    "mock_export.page_missing",
                    format!("missing page {page_id}"),
                ));
            }
        }

        let diagnostics = validate_scene(scene);
        let artifacts = request
            .page_ids
            .iter()
            .cloned()
            .map(|page_id| ExportArtifact {
                format: request.profile.format.clone(),
                page_id: Some(page_id),
                asset_id: None,
                mime_type: export_mime_type(&request.profile.format).to_owned(),
                bytes: Vec::new(),
                sidecar_json: Some(
                    serde_json::json!({
                        "profile": request.profile.name,
                        "purpose": request.purpose
                    })
                    .to_string(),
                ),
            })
            .collect();

        Ok(ExportResult {
            artifacts,
            diagnostics,
        })
    }
}

struct MockAgent;

#[derive(Debug)]
struct AgentApplyResult {
    scene: Scene,
    accepted: bool,
    applied_operations: usize,
    diagnostics: Vec<Diagnostic>,
}

impl MockAgent {
    fn apply_and_validate(&self, scene: &Scene, operations: Vec<Operation>) -> AgentApplyResult {
        let mut next = scene.clone();
        let mut applied_operations = 0;
        let mut diagnostics = Vec::new();

        for operation in operations {
            match next.apply_operation(operation) {
                Ok(()) => applied_operations += 1,
                Err(error) => {
                    diagnostics.push(Diagnostic::error(
                        Phase::Operation,
                        error.code,
                        error.message,
                        Some(DiagnosticSubject::Document),
                    ));
                    return AgentApplyResult {
                        scene: next,
                        accepted: false,
                        applied_operations,
                        diagnostics,
                    };
                }
            }
        }

        diagnostics.extend(validate_scene(&next));
        let accepted = diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error);

        AgentApplyResult {
            scene: next,
            accepted,
            applied_operations,
            diagnostics,
        }
    }
}

fn valid_fixtures() -> [(&'static str, &'static str); 2] {
    [
        ("minimal_scene", MINIMAL_SCENE),
        ("valid_multi_page_slots", VALID_MULTI_PAGE_SLOTS),
    ]
}

fn decode_scene(name: &str, json: &str) -> Scene {
    serde_json::from_str(json).unwrap_or_else(|error| panic!("{name} failed to decode: {error}"))
}

fn stable_scene_json(scene: &Scene) -> String {
    serde_json::to_string_pretty(scene).expect("scene serializes")
}

#[derive(Debug, Eq, PartialEq, Ord, PartialOrd)]
struct DiagnosticSignature {
    severity: &'static str,
    phase: &'static str,
    code: String,
}

fn diagnostic_signatures(scene: &Scene) -> Vec<DiagnosticSignature> {
    let mut signatures = validate_scene(scene)
        .into_iter()
        .map(|diagnostic| DiagnosticSignature {
            severity: severity_name(&diagnostic.severity),
            phase: phase_name(&diagnostic.phase),
            code: diagnostic.code,
        })
        .collect::<Vec<_>>();
    signatures.sort();
    signatures
}

fn signature(severity: &'static str, phase: &'static str, code: &str) -> DiagnosticSignature {
    DiagnosticSignature {
        severity,
        phase,
        code: code.to_owned(),
    }
}

fn sorted_signatures(mut signatures: Vec<DiagnosticSignature>) -> Vec<DiagnosticSignature> {
    signatures.sort();
    signatures
}

fn severity_name(severity: &DiagnosticSeverity) -> &'static str {
    match severity {
        DiagnosticSeverity::Error => "error",
        DiagnosticSeverity::Warning => "warning",
        DiagnosticSeverity::Advice => "advice",
    }
}

fn phase_name(phase: &Phase) -> &'static str {
    match phase {
        Phase::Contract => "contract",
        Phase::Operation => "operation",
        Phase::Validation => "validation",
        Phase::Dsl => "dsl",
        Phase::Layout => "layout",
        Phase::Export => "export",
    }
}

fn assert_no_diagnostic_errors(name: &str, scene: &Scene) {
    let diagnostics = validate_scene(scene);
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "{name} has validation errors: {diagnostics:#?}"
    );
}

fn assert_has_error(scene: &Scene) {
    let diagnostics = validate_scene(scene);
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error),
        "fixture should contain at least one validation error: {diagnostics:#?}"
    );
}

fn text_content<'a>(scene: &'a Scene, node_id: &str) -> &'a str {
    match &scene.nodes[&NodeId::from(node_id)].kind {
        NodeKind::Text(text) => text.content.as_str(),
        other => panic!("expected text node, got {other:?}"),
    }
}

fn replay_multi_page_slot_scene() -> Scene {
    let mut scene = Scene::new(
        DocumentId::from("doc_conformance_slots"),
        "Conformance Slots",
    );

    scene
        .apply_operation(Operation::UpdateDocument {
            patch: DocumentPatch {
                artifact_type: OptionalFieldPatch::Set("letter_and_ad".to_owned()),
                medium: OptionalFieldPatch::Set(Medium::Print),
                ..DocumentPatch::default()
            },
        })
        .unwrap();
    scene
        .apply_operation(Operation::SetBrandKitRef {
            brand_kit_id: BrandKitId::from("brand_kit_acme"),
            version: 1,
        })
        .unwrap();
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();
    scene
        .apply_operation(Operation::AddPage {
            page: linkedin_ad_page(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: header_frame(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("node_header_frame")),
            index: 0,
            node: account_logo_node(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("node_header_frame")),
            index: 1,
            node: account_name_node(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 1,
            node: cta_node(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_linkedin_ad")),
            index: 0,
            node: ad_headline_node(),
        })
        .unwrap();

    for slot in [
        account_logo_slot(),
        account_name_slot(),
        ad_headline_slot(),
        campaign_cta_slot(),
    ] {
        scene
            .apply_operation(Operation::UpsertSlot { slot })
            .unwrap();
    }

    for (slot_id, node_id) in [
        ("slot_account_logo", "node_account_logo"),
        ("slot_account_name", "node_account_name"),
        ("slot_ad_headline", "node_ad_headline"),
        ("slot_campaign_cta", "node_cta"),
    ] {
        scene
            .apply_operation(Operation::BindNodeToSlot {
                slot_id: SlotId::from(slot_id),
                node_id: NodeId::from(node_id),
            })
            .unwrap();
    }

    scene
        .apply_operation(Operation::UpsertExportProfile {
            profile: print_pdf_profile(),
        })
        .unwrap();
    scene
        .apply_operation(Operation::UpsertExportProfile {
            profile: agent_png_profile(),
        })
        .unwrap();

    scene
}

fn a4_page() -> Page {
    Page {
        id: PageId::from("page_a4"),
        name: "A4 Letter".to_owned(),
        size: PageSize {
            width: 210.0,
            height: 297.0,
            unit: Unit::Mm,
            preset: Some(PagePreset::A4),
            orientation: Orientation::Portrait,
        },
        children: Vec::new(),
        bleed: Some(lumen_core::Rect {
            x: 0.0,
            y: 0.0,
            width: 210.0,
            height: 297.0,
        }),
        safe_area: Some(lumen_core::Rect {
            x: 12.0,
            y: 12.0,
            width: 186.0,
            height: 273.0,
        }),
        background: vec![solid_fill("paint_page_surface", "#fffaf2")],
    }
}

fn linkedin_ad_page() -> Page {
    Page {
        id: PageId::from("page_linkedin_ad"),
        name: "LinkedIn Ad".to_owned(),
        size: PageSize {
            width: 1200.0,
            height: 627.0,
            unit: Unit::Px,
            preset: Some(PagePreset::LinkedinAd),
            orientation: Orientation::Landscape,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: Some(lumen_core::Rect {
            x: 48.0,
            y: 48.0,
            width: 1104.0,
            height: 531.0,
        }),
        background: vec![Fill {
            id: PaintId::from("paint_ad_surface"),
            paint: Paint::Token {
                token: "surface.brand".to_owned(),
            },
        }],
    }
}

fn header_frame() -> Node {
    let mut node = Node::new(NodeId::from("node_header_frame"), NodeKind::Frame);
    node.name = Some("Header Slot Group".to_owned());
    node.transform = transform(16.0, 18.0);
    node.size = SizeSpec::fixed(178.0, 44.0);
    node.fills = vec![solid_fill("paint_header_surface", "#ffffff")];
    node.strokes = vec![Stroke {
        id: PaintId::from("paint_header_stroke"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#e6ded0".to_owned(),
            },
        },
        width: 0.4,
    }];
    node.corner = corner(6.0);
    node
}

fn account_logo_node() -> Node {
    let mut node = Node::new(
        NodeId::from("node_account_logo"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_logo_demo"),
            alt: Some("Account logo".to_owned()),
        }),
    );
    node.name = Some("Account Logo".to_owned());
    node.size = SizeSpec::fixed(32.0, 32.0);
    node.corner = corner(4.0);
    node.clip = true;
    node
}

fn account_name_node() -> Node {
    let mut node = text_node(
        "node_account_name",
        "Account Name",
        "Apollo Neuroscience Center",
        40.0,
        3.0,
        126.0,
        30.0,
        14.0,
        700,
        TextAlign::Left,
    );
    node.fills = vec![Fill {
        id: PaintId::from("paint_account_text"),
        paint: Paint::Token {
            token: "text.primary".to_owned(),
        },
    }];
    node
}

fn cta_node() -> Node {
    let mut node = text_node(
        "node_cta",
        "CTA",
        "Schedule a consultation",
        24.0,
        240.0,
        88.0,
        14.0,
        12.0,
        700,
        TextAlign::Center,
    );
    node.fills = vec![Fill {
        id: PaintId::from("paint_cta_text"),
        paint: Paint::Token {
            token: "text.inverse".to_owned(),
        },
    }];
    node
}

fn ad_headline_node() -> Node {
    let mut node = text_node(
        "node_ad_headline",
        "Ad Headline",
        "A sharper plan for patient acquisition",
        64.0,
        88.0,
        720.0,
        136.0,
        54.0,
        800,
        TextAlign::Left,
    );
    node.fills = vec![solid_fill("paint_ad_headline", "#193235")];
    node
}

#[allow(clippy::too_many_arguments)]
fn text_node(
    id: &str,
    name: &str,
    content: &str,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    font_size: f64,
    font_weight: u16,
    align: TextAlign,
) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size,
            font_weight,
            align,
        }),
    );
    node.name = Some(name.to_owned());
    node.transform = transform(x, y);
    node.size = SizeSpec::fixed(width, height);
    node
}

fn account_logo_slot() -> Slot {
    let mut slot = Slot::text_short(
        SlotId::from("slot_account_logo"),
        SlotKey::from("account.logo"),
        "Account logo",
    );
    slot.content_type = lumen_core::ContentType::Logo;
    slot.scope = SlotScope::Group(NodeId::from("node_header_frame"));
    slot.placeholder = Some("Demo account logo".to_owned());
    slot.overflow = OverflowPolicy::Clip;
    slot.image_policy = Some(ImagePolicy {
        fit: ImageFitMode::Contain,
        focal_point: Some(FocalPoint { x: 0.5, y: 0.5 }),
        min_dpi: Some(144),
        preserve_transparency: true,
        aspect_ratio: Some(1.0),
    });
    slot.binding_hints = vec![BindingHint {
        source_path: "account.logo".to_owned(),
        confidence: Some(0.9),
    }];
    slot
}

fn account_name_slot() -> Slot {
    let mut slot = Slot::text_short(
        SlotId::from("slot_account_name"),
        SlotKey::from("account.name"),
        "Account name",
    );
    slot.scope = SlotScope::Group(NodeId::from("node_header_frame"));
    slot.placeholder = Some("Apollo Neuroscience Center".to_owned());
    slot.overflow = OverflowPolicy::Wrap { max_lines: Some(2) };
    slot.formatting.max_length = Some(96);
    slot.validation = ValidationFixtures {
        samples: vec![
            "Apollo Neuroscience Center".to_owned(),
            "Northwestern Memorial Healthcare Partners".to_owned(),
        ],
        worst_case: Some("The University of Texas MD Anderson Cancer Center".to_owned()),
        max_length: Some(96),
    };
    slot.binding_hints = vec![BindingHint {
        source_path: "account.name".to_owned(),
        confidence: Some(1.0),
    }];
    slot
}

fn ad_headline_slot() -> Slot {
    let mut slot = Slot::text_short(
        SlotId::from("slot_ad_headline"),
        SlotKey::from("campaign.headline"),
        "Campaign headline",
    );
    slot.content_type = lumen_core::ContentType::TextLong;
    slot.scope = SlotScope::Page(PageId::from("page_linkedin_ad"));
    slot.placeholder = Some("A sharper plan for patient acquisition".to_owned());
    slot.overflow = OverflowPolicy::ShrinkFont {
        min_font_size: 36.0,
        max_font_size: Some(54.0),
    };
    slot.formatting.max_length = Some(120);
    slot.validation = ValidationFixtures {
        samples: vec!["A sharper plan for patient acquisition".to_owned()],
        worst_case: Some(
            "How leading health systems identify higher-fit patient demand earlier".to_owned(),
        ),
        max_length: Some(120),
    };
    slot.binding_hints = vec![BindingHint {
        source_path: "campaign.headline".to_owned(),
        confidence: Some(0.8),
    }];
    slot
}

fn campaign_cta_slot() -> Slot {
    let mut slot = Slot::text_short(
        SlotId::from("slot_campaign_cta"),
        SlotKey::from("campaign.cta"),
        "Campaign CTA",
    );
    slot.placeholder = Some("Schedule a consultation".to_owned());
    slot.overflow = OverflowPolicy::Ellipsis;
    slot.formatting.max_length = Some(48);
    slot.validation = ValidationFixtures {
        samples: vec![
            "Schedule a consultation".to_owned(),
            "Download the care pathway".to_owned(),
        ],
        worst_case: None,
        max_length: Some(48),
    };
    slot.binding_hints = vec![BindingHint {
        source_path: "campaign.cta".to_owned(),
        confidence: Some(0.8),
    }];
    slot
}

fn print_pdf_profile() -> ExportProfile {
    ExportProfile {
        name: "print_pdf".to_owned(),
        format: ExportFormat::Pdf,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: true,
        embed_fonts: true,
    }
}

fn agent_png_profile() -> ExportProfile {
    ExportProfile {
        name: "agent_png".to_owned(),
        format: ExportFormat::Png,
        pdf_intent: None,
        raster: Some(RasterScale {
            scale: 2.0,
            dpi: Some(144),
        }),
        include_bleed: false,
        embed_fonts: false,
    }
}

fn transform(x: f64, y: f64) -> Transform {
    Transform {
        x,
        y,
        ..Transform::default()
    }
}

fn corner(value: f64) -> CornerRadii {
    CornerRadii {
        top_left: value,
        top_right: value,
        bottom_right: value,
        bottom_left: value,
    }
}

fn solid_fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.to_owned(),
            },
        },
    }
}

fn render_mime_type(target: &RenderTarget) -> &'static str {
    match target {
        RenderTarget::Svg => "image/svg+xml",
        RenderTarget::Png { .. } => "image/png",
        RenderTarget::Pdf => "application/pdf",
        RenderTarget::KonvaScene => "application/vnd.abm-design.konva+json",
        RenderTarget::FigmaManifest => "application/json",
    }
}

fn export_mime_type(format: &ExportFormat) -> &'static str {
    match format {
        ExportFormat::Svg => "image/svg+xml",
        ExportFormat::Png => "image/png",
        ExportFormat::Pdf => "application/pdf",
        ExportFormat::FigmaManifest => "application/json",
    }
}
