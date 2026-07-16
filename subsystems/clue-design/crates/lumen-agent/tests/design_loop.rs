use lumen_agent::{
    query_geometry, query_slot_bindings, recommend_edit_surface, summarize_document,
    summarize_node_tree, summarize_page, AgentAssetRequest, AgentAssetResult, AgentDesignLoop,
    AgentEdit, AgentEditIntent, AgentInstructionContext, AgentLoopOptions, AgentSession,
    AgentStopReason, AgentToolStatus, AgentTurnInput, AssetTool, EditSurfaceRecommendation,
    UnavailableAssetTool, VisualCritic, VisualCritiqueRequest, VisualCritiqueResult, VisualIssue,
    VisualIssueCategory,
};
use lumen_core::{
    scene_has_token_references, AssetId, BrandKitId, BrandKitRef, Color, Diagnostic,
    DiagnosticSeverity, DocumentId, ExportAdapter, ExportArtifact, ExportError, ExportFormat,
    ExportRequest, ExportResult, FieldPatch, Fill, ImageNode, Node, NodeId, NodeKind, NodePatch,
    Operation, Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Rect,
    SizeSpec, SlotKey, Transform, Unit,
};
use std::cell::RefCell;
use std::collections::VecDeque;

#[derive(Default)]
struct MockExportAdapter {
    requests: RefCell<Vec<ExportRequest>>,
    diagnostics: Vec<Diagnostic>,
    artifacts: Option<Vec<ExportArtifact>>,
    error: Option<ExportError>,
}

impl ExportAdapter for MockExportAdapter {
    fn export(
        &self,
        _scene: &lumen_core::Scene,
        request: &ExportRequest,
    ) -> Result<ExportResult, ExportError> {
        self.requests.borrow_mut().push(request.clone());

        if let Some(error) = &self.error {
            return Err(error.clone());
        }

        Ok(ExportResult {
            artifacts: self.artifacts.clone().unwrap_or_else(|| {
                vec![ExportArtifact {
                    format: request.profile.format.clone(),
                    page_id: request.page_ids.first().cloned(),
                    asset_id: None,
                    mime_type: match request.profile.format {
                        ExportFormat::Png => "image/png",
                        ExportFormat::Svg => "image/svg+xml",
                        ExportFormat::Pdf => "application/pdf",
                        ExportFormat::FigmaManifest => "application/json",
                    }
                    .to_owned(),
                    bytes: vec![1, 2, 3],
                    sidecar_json: None,
                }]
            }),
            diagnostics: self.diagnostics.clone(),
            print_ready: None,
        })
    }
}

struct QueueCritic {
    requests: RefCell<Vec<VisualCritiqueRequest>>,
    responses: RefCell<VecDeque<VisualCritiqueResult>>,
}

impl QueueCritic {
    fn new(responses: Vec<VisualCritiqueResult>) -> Self {
        Self {
            requests: RefCell::new(Vec::new()),
            responses: RefCell::new(VecDeque::from(responses)),
        }
    }
}

impl VisualCritic for QueueCritic {
    fn critique(&self, request: &VisualCritiqueRequest) -> VisualCritiqueResult {
        self.requests.borrow_mut().push(request.clone());
        self.responses
            .borrow_mut()
            .pop_front()
            .unwrap_or_else(VisualCritiqueResult::pass)
    }
}

struct MockAssetTool {
    result: AgentAssetResult,
    requests: RefCell<Vec<AgentAssetRequest>>,
}

impl AssetTool for MockAssetTool {
    fn execute(&self, request: &AgentAssetRequest) -> AgentAssetResult {
        self.requests.borrow_mut().push(request.clone());
        self.result.clone()
    }
}

fn empty_session(id: &str) -> AgentSession {
    AgentSession::new(lumen_core::Scene::new(DocumentId::from(id), "Agent Test"))
}

fn turn(edit: AgentEdit) -> AgentTurnInput {
    AgentTurnInput {
        prompt: "Create an ABM artifact".to_owned(),
        instruction_context: AgentInstructionContext::from_user_request("Create an ABM artifact"),
        edit,
        brand_kit: None,
        page_ids: Vec::new(),
        options: AgentLoopOptions::default(),
    }
}

fn concrete_dsl() -> &'static str {
    r##"
page page_a4
  headline text "Plan" p(24,28) s(96,24) font("Inter",16,700,left) fill(#111827)
"##
}

fn tokenized_dsl() -> &'static str {
    r#"
page page_a4
  hero rect p(16,16) s(120,48) fill($surface.brand)
  headline text "Plan" p(24,28) s(180,48) style($type.headline) slot(campaign.headline)
"#
}

#[test]
fn dsl_halt_preserves_partial_ops_and_skips_preflight_export_and_critique() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_dsl_halt");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: r#"
page page_a4
  hero frame p(0,0) s(100,100)
    headline text "Plan" p(0,0) s(80,24) font("Inter",16,700,left)
      illegal rect p(0,0) s(10,10) fill(#ffffff)
"#
            .to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::DslHalted);
    assert!(result
        .dsl_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error));
    assert!(result
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::AddPage { .. })));
    assert!(session.scene().pages.contains_key(&PageId::from("page_a4")));
    assert!(export.requests.borrow().is_empty());
    assert!(critic.requests.borrow().is_empty());
}

#[test]
fn tokenized_dsl_uses_platform_default_brand_kit_before_preflight_and_export() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_default_brand");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: tokenized_dsl().to_owned(),
        }),
    );

    assert_eq!(
        result.stop_reason,
        AgentStopReason::Completed,
        "{result:#?}"
    );
    assert!(!result.has_errors(), "{result:#?}");
    assert!(!scene_has_token_references(&result.final_scene));
    assert!(result
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::SetBrandKitRef { .. })));
    assert_eq!(export.requests.borrow().len(), 1);
    assert_eq!(
        export.requests.borrow()[0].purpose,
        lumen_core::ExportPurpose::AgentCritique
    );
    assert_eq!(critic.requests.borrow().len(), 1);
    assert_eq!(
        critic.requests.borrow()[0].brand_kit.source,
        lumen_agent::AgentBrandKitSource::PlatformDefault
    );
    assert_eq!(result.preview_artifacts.len(), 1);
    assert_eq!(
        result.final_brand_kit.as_ref().unwrap().source,
        lumen_agent::AgentBrandKitSource::PlatformDefault
    );
    assert_eq!(
        result.to_dto().brand_kit.as_ref().unwrap().source,
        lumen_agent::AgentBrandKitSource::PlatformDefault
    );
}

#[test]
fn existing_scene_brand_ref_is_reported_when_no_kit_is_needed() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut scene = lumen_core::Scene::new(DocumentId::from("doc_existing_brand"), "Existing");
    scene.meta.brand_kit = Some(BrandKitRef {
        id: BrandKitId::from("brand_kit_platform_default"),
        version: 1,
    });
    let mut session = AgentSession::new(scene);

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: concrete_dsl().to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::Completed);
    assert_eq!(critic.requests.borrow().len(), 1);
    assert_eq!(
        critic.requests.borrow()[0].brand_kit.source,
        lumen_agent::AgentBrandKitSource::DocumentReference
    );
    assert_eq!(
        critic.requests.borrow()[0]
            .brand_kit
            .brand_kit_id
            .as_deref(),
        Some("brand_kit_platform_default")
    );
}

#[test]
fn dsl_repair_block_preserves_parent_context_after_preflight_preview() {
    let export = MockExportAdapter::default();
    let repair = AgentEdit::DslBlock {
        source: r##"
  headline text "Plan" p(24,28) s(96,24) font("Inter",16,700,left) fill(#111827)
"##
        .to_owned(),
    };
    let critic = QueueCritic::new(vec![
        VisualCritiqueResult::needs_repair(
            vec![VisualIssue {
                category: VisualIssueCategory::Hierarchy,
                severity: DiagnosticSeverity::Warning,
                message: "page needs a headline".to_owned(),
                subject: Some(lumen_core::DiagnosticSubject::Page(PageId::from("page_a4"))),
                suggested_fix: Some("add headline under active page".to_owned()),
            }],
            Some(repair),
        ),
        VisualCritiqueResult::pass(),
    ]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_dsl_repair_context");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: r##"
page page_a4
"##
            .to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::Completed);
    assert_eq!(result.iterations.len(), 2);
    assert!(result
        .dsl_diagnostics
        .iter()
        .all(|diagnostic| { diagnostic.diagnostic.severity != DiagnosticSeverity::Error }));
    assert!(result
        .final_scene
        .nodes
        .contains_key(&NodeId::from("headline")));
    assert_eq!(
        result.final_scene.pages[&PageId::from("page_a4")].children,
        vec![NodeId::from("headline")]
    );
}

#[test]
fn default_brand_kit_context_stays_active_across_visual_repair_iterations() {
    let export = MockExportAdapter::default();
    let repair = AgentEdit::StructuredOps {
        operations: vec![Operation::UpdateNode {
            node_id: NodeId::from("hero"),
            patch: NodePatch {
                transform: FieldPatch::Set(Transform {
                    x: 20.0,
                    y: 16.0,
                    ..Transform::default()
                }),
                ..NodePatch::default()
            },
        }],
    };
    let critic = QueueCritic::new(vec![
        VisualCritiqueResult::needs_repair(Vec::new(), Some(repair)),
        VisualCritiqueResult::pass(),
    ]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_sticky_default_brand");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: tokenized_dsl().to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::Completed);
    assert_eq!(result.iterations.len(), 2);
    assert_eq!(
        result.iterations[0].brand_kit_source,
        Some(lumen_agent::AgentBrandKitSource::PlatformDefault)
    );
    assert_eq!(
        result.iterations[1].brand_kit_source,
        Some(lumen_agent::AgentBrandKitSource::PlatformDefault)
    );
    assert_eq!(critic.requests.borrow().len(), 2);
    assert_eq!(
        critic.requests.borrow()[0].brand_kit.source,
        lumen_agent::AgentBrandKitSource::PlatformDefault
    );
    assert_eq!(
        critic.requests.borrow()[1].brand_kit.source,
        lumen_agent::AgentBrandKitSource::PlatformDefault
    );
}

#[test]
fn preflight_errors_prevent_export_and_visual_critique() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_preflight_error");
    let mut input = turn(AgentEdit::DslBlock {
        source: tokenized_dsl().to_owned(),
    });
    input.options.use_platform_default_brand_kit = false;

    let result = loop_runner.run_turn(&mut session, input);

    assert_eq!(result.stop_reason, AgentStopReason::PreflightFailed);
    assert!(result
        .engine_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMP0300"));
    assert!(export.requests.borrow().is_empty());
    assert!(critic.requests.borrow().is_empty());
}

#[test]
fn unusable_preview_artifacts_block_visual_critic() {
    let export = MockExportAdapter {
        artifacts: Some(vec![ExportArtifact {
            format: ExportFormat::Png,
            page_id: Some(PageId::from("page_a4")),
            asset_id: None,
            mime_type: "image/png".to_owned(),
            bytes: Vec::new(),
            sidecar_json: None,
        }]),
        ..MockExportAdapter::default()
    };
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_empty_preview");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: concrete_dsl().to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::ExportFailed);
    assert!(result
        .agent_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0312"));
    assert!(critic.requests.borrow().is_empty());
}

#[test]
fn non_committed_preflight_disables_automatic_repair_by_default() {
    let export = MockExportAdapter::default();
    let repair = AgentEdit::StructuredOps {
        operations: vec![Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: NodePatch {
                transform: FieldPatch::Set(Transform {
                    x: 48.0,
                    y: 28.0,
                    ..Transform::default()
                }),
                ..NodePatch::default()
            },
        }],
    };
    let critic = QueueCritic::new(vec![VisualCritiqueResult::needs_repair(
        Vec::new(),
        Some(repair),
    )]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_preflight_read_only_repair");
    let mut input = turn(AgentEdit::DslBlock {
        source: concrete_dsl().to_owned(),
    });
    input.options.commit_preflight_operations = false;

    let result = loop_runner.run_turn(&mut session, input);

    assert_eq!(result.stop_reason, AgentStopReason::CritiqueFailed);
    assert!(result
        .agent_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0600"));
    assert_eq!(export.requests.borrow().len(), 1);
    assert_eq!(critic.requests.borrow().len(), 1);
}

#[test]
fn conservative_edit_surface_recommendation_prefers_safe_surfaces() {
    let context = AgentInstructionContext::from_user_request("revise the design");

    let asset = AgentEditIntent {
        asset_generation_or_placement: true,
        creation_or_composition: true,
        ..AgentEditIntent::default()
    };
    assert_eq!(
        recommend_edit_surface(&asset, &context),
        EditSurfaceRecommendation::AssetTool
    );

    let external = AgentEditIntent {
        asset_generation_or_placement: true,
        requires_external_planner: true,
        ..AgentEditIntent::default()
    };
    assert_eq!(
        recommend_edit_surface(&external, &context),
        EditSurfaceRecommendation::ExternalPlanner
    );

    let targeted = AgentEditIntent {
        targets: lumen_agent::AgentEditTargets {
            node_ids: vec![NodeId::from("headline")],
            ..Default::default()
        },
        ..AgentEditIntent::default()
    };
    assert_eq!(
        recommend_edit_surface(&targeted, &context),
        EditSurfaceRecommendation::StructuredOps
    );

    let create = AgentEditIntent {
        creation_or_composition: true,
        ..AgentEditIntent::default()
    };
    assert_eq!(
        recommend_edit_surface(&create, &context),
        EditSurfaceRecommendation::Dsl
    );

    assert_eq!(
        recommend_edit_surface(&AgentEditIntent::default(), &context),
        EditSurfaceRecommendation::ExternalPlanner
    );
}

#[test]
fn read_query_helpers_expose_document_nodes_slots_and_geometry() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_read_helpers");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: tokenized_dsl().to_owned(),
        }),
    );

    let scene = &result.final_scene;
    let document = summarize_document(scene);
    assert_eq!(document.page_count, 1);
    assert_eq!(document.slot_count, 1);

    let page = summarize_page(scene, &PageId::from("page_a4")).unwrap();
    assert_eq!(page.root_nodes.len(), 2);

    let tree = summarize_node_tree(scene, &PageId::from("page_a4")).unwrap();
    assert!(tree
        .nodes
        .iter()
        .any(|entry| entry.node_id == NodeId::from("headline")));

    let geometry = query_geometry(scene, &NodeId::from("headline")).unwrap();
    assert!(geometry.computed.is_some());

    let slot = query_slot_bindings(scene, &SlotKey::from("campaign.headline")).unwrap();
    assert_eq!(slot.bound_nodes.len(), 1);
}

#[test]
fn dto_and_diagnostic_views_are_stable_summaries() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_dto");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: tokenized_dsl().to_owned(),
        }),
    );

    let dto = result.to_dto();
    assert_eq!(dto.schema_version, 1);
    assert_eq!(dto.document_id, "doc_dto");
    assert_eq!(dto.operation_count, result.operations.len());
    assert_eq!(dto.iterations.len(), result.iterations.len());
    assert!(dto.preview.is_some());
    assert!(dto.brand_kit.is_some());
    assert!(!dto.diagnostics.audit.is_empty());
    assert!(!dto.diagnostics.latest.is_empty());
    assert_eq!(critic.requests.borrow().len(), 1);
    assert!(!critic.requests.borrow()[0]
        .diagnostic_views
        .current
        .is_empty());
}

#[test]
fn visual_critic_repair_edit_loops_until_pass() {
    let export = MockExportAdapter::default();
    let repair = AgentEdit::StructuredOps {
        operations: vec![Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: NodePatch {
                transform: FieldPatch::Set(Transform {
                    x: 48.0,
                    y: 28.0,
                    ..Transform::default()
                }),
                ..NodePatch::default()
            },
        }],
    };
    let critic = QueueCritic::new(vec![
        VisualCritiqueResult::needs_repair(
            vec![VisualIssue {
                category: VisualIssueCategory::Spacing,
                severity: DiagnosticSeverity::Warning,
                message: "headline needs more left margin".to_owned(),
                subject: Some(lumen_core::DiagnosticSubject::Node(NodeId::from(
                    "headline",
                ))),
                suggested_fix: Some("move headline right".to_owned()),
            }],
            Some(repair),
        ),
        VisualCritiqueResult::pass(),
    ]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_visual_repair");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::DslBlock {
            source: concrete_dsl().to_owned(),
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::Completed);
    assert_eq!(result.iterations.len(), 2);
    assert_eq!(export.requests.borrow().len(), 2);
    assert_eq!(critic.requests.borrow().len(), 2);
    assert_eq!(
        result.final_scene.nodes[&NodeId::from("headline")]
            .transform
            .x,
        48.0
    );
}

#[test]
fn visual_critic_repair_stops_at_max_iterations() {
    let export = MockExportAdapter::default();
    let repair = AgentEdit::StructuredOps {
        operations: Vec::new(),
    };
    let critic = QueueCritic::new(vec![VisualCritiqueResult::needs_repair(
        Vec::new(),
        Some(repair),
    )]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_max_iterations");
    let mut input = turn(AgentEdit::DslBlock {
        source: concrete_dsl().to_owned(),
    });
    input.options.max_iterations = 1;

    let result = loop_runner.run_turn(&mut session, input);

    assert_eq!(result.stop_reason, AgentStopReason::MaxIterations);
    assert_eq!(result.iterations.len(), 1);
}

#[test]
fn structured_operation_failure_stops_before_export() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_bad_ops");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::StructuredOps {
            operations: vec![Operation::RemoveNode {
                node_id: NodeId::from("missing"),
            }],
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::OperationFailed);
    assert!(result
        .agent_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0200"));
    assert!(export.requests.borrow().is_empty());
    assert!(critic.requests.borrow().is_empty());
}

#[test]
fn unavailable_asset_tool_stops_before_export() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = UnavailableAssetTool;
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_asset_unavailable");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::AssetTool {
            request: AgentAssetRequest::GenerateImage {
                prompt: "hospital hallway".to_owned(),
                target_slot_key: None,
                suggested_asset_id: None,
            },
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::AssetToolFailed);
    assert!(result
        .agent_diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0400"));
    assert!(export.requests.borrow().is_empty());
    assert!(critic.requests.borrow().is_empty());
}

#[test]
fn asset_tool_can_return_checked_placement_operations() {
    let export = MockExportAdapter::default();
    let critic = QueueCritic::new(vec![VisualCritiqueResult::pass()]);
    let asset_tool = MockAssetTool {
        result: AgentAssetResult {
            status: AgentToolStatus::Completed,
            asset_id: Some(AssetId::from("asset_generated")),
            mime_type: Some("image/png".to_owned()),
            provenance: None,
            license: None,
            operations: asset_scene_operations(),
            diagnostics: Vec::new(),
        },
        requests: RefCell::new(Vec::new()),
    };
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = empty_session("doc_asset_ops");

    let result = loop_runner.run_turn(
        &mut session,
        turn(AgentEdit::AssetTool {
            request: AgentAssetRequest::GenerateImage {
                prompt: "hospital hallway".to_owned(),
                target_slot_key: Some(SlotKey::from("campaign.hero_image")),
                suggested_asset_id: Some(AssetId::from("asset_generated")),
            },
        }),
    );

    assert_eq!(result.stop_reason, AgentStopReason::Completed);
    assert!(!result.has_errors(), "{result:#?}");
    assert!(result
        .final_scene
        .nodes
        .contains_key(&NodeId::from("hero_image")));
    assert_eq!(asset_tool.requests.borrow().len(), 1);
    assert_eq!(export.requests.borrow().len(), 1);
    assert_eq!(critic.requests.borrow().len(), 1);
}

fn asset_scene_operations() -> Vec<Operation> {
    let page_id = PageId::from("page_asset");
    let node_id = NodeId::from("hero_image");
    let mut node = Node::new(
        node_id.clone(),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_generated"),
            alt: Some("Generated hospital hallway".to_owned()),
        }),
    );
    node.transform = Transform {
        x: 16.0,
        y: 16.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(128.0, 72.0);
    node.fills = vec![Fill {
        id: PaintId::from("paint_asset_bg"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#f9fafb".to_owned(),
            },
        },
    }];

    vec![
        Operation::AddPage {
            page: Page {
                id: page_id.clone(),
                name: "Asset Page".to_owned(),
                size: PageSize {
                    width: 180.0,
                    height: 120.0,
                    unit: Unit::Px,
                    preset: Some(PagePreset::Custom),
                    orientation: Orientation::Landscape,
                    source: None,
                    output: None,
                },
                children: Vec::new(),
                bleed: None,
                safe_area: Some(Rect {
                    x: 8.0,
                    y: 8.0,
                    width: 164.0,
                    height: 104.0,
                }),
                background: Vec::new(),
            },
        },
        Operation::InsertNode {
            parent: ParentRef::Page(page_id),
            index: 0,
            node,
        },
    ]
}
