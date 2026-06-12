use lumen_agent::{
    AgentAssetRequest, AgentAssetResult, AgentDesignLoop, AgentEdit, AgentInstructionContext,
    AgentLoopOptions, AgentSession, AgentStopReason, AgentToolStatus, AgentTurnInput, AssetTool,
    VisualCritic, VisualCritiqueRequest, VisualCritiqueResult,
};
use lumen_core::{
    validate_scene_assets, AssetId, AssetPlacement, AssetRecord, AssetValidationOptions,
    ContentType, DiagnosticSeverity, DocumentId, FocalPoint, ImageFitMode, ImagePolicy, Node,
    NodeId, NodeKind, Operation, Orientation, OverflowPolicy, Page, PageId, PagePreset, PageSize,
    ParentRef, Rect, SizeSpec, Slot, SlotId, SlotKey, Transform, Unit,
};
use lumen_export::SvgExportAdapter;
use std::cell::RefCell;

const GENERATED_RASTER: &str =
    include_str!("../../lumen-core/fixtures/assets/generated_raster_asset.json");

struct FixedAssetTool {
    operations: Vec<Operation>,
    requests: RefCell<Vec<AgentAssetRequest>>,
}

impl AssetTool for FixedAssetTool {
    fn execute(&self, request: &AgentAssetRequest) -> AgentAssetResult {
        self.requests.borrow_mut().push(request.clone());
        AgentAssetResult {
            status: AgentToolStatus::Completed,
            asset_id: Some(AssetId::from("asset_generated_hero")),
            mime_type: Some("image/png".to_owned()),
            provenance: None,
            license: None,
            operations: self.operations.clone(),
            diagnostics: Vec::new(),
        }
    }
}

#[derive(Default)]
struct RecordingCritic {
    requests: RefCell<Vec<VisualCritiqueRequest>>,
}

impl VisualCritic for RecordingCritic {
    fn critique(&self, request: &VisualCritiqueRequest) -> VisualCritiqueResult {
        self.requests.borrow_mut().push(request.clone());
        VisualCritiqueResult::pass()
    }
}

#[test]
fn agent_asset_tool_operations_survive_preflight_export_and_dto_summary() {
    let export = SvgExportAdapter::new();
    let critic = RecordingCritic::default();
    let asset_tool = FixedAssetTool {
        operations: asset_placement_operations(),
        requests: RefCell::new(Vec::new()),
    };
    let loop_runner = AgentDesignLoop::new(&export, &critic, &asset_tool);
    let mut session = AgentSession::new(lumen_core::Scene::new(
        DocumentId::from("doc_phase4_agent_asset"),
        "Phase 4 Agent Asset",
    ));

    let result = loop_runner.run_turn(
        &mut session,
        AgentTurnInput {
            prompt: "Generate and place a hero image".to_owned(),
            instruction_context: AgentInstructionContext::from_user_request(
                "Generate and place a hero image",
            ),
            edit: AgentEdit::AssetTool {
                request: AgentAssetRequest::GenerateImage {
                    prompt: "modern neurosurgery practice reception area".to_owned(),
                    target_slot_key: Some(SlotKey::from("campaign.hero_image")),
                    suggested_asset_id: Some(AssetId::from("asset_generated_hero")),
                },
            },
            brand_kit: None,
            page_ids: Vec::new(),
            options: AgentLoopOptions {
                export_format: lumen_core::ExportFormat::Svg,
                ..AgentLoopOptions::default()
            },
        },
    );

    assert_eq!(
        result.stop_reason,
        AgentStopReason::Completed,
        "{result:#?}"
    );
    assert!(!result.has_errors(), "{result:#?}");
    assert_eq!(asset_tool.requests.borrow().len(), 1);
    assert_eq!(critic.requests.borrow().len(), 1);

    let scene = &result.final_scene;
    assert!(scene
        .assets
        .contains_key(&AssetId::from("asset_generated_hero")));
    let hero = scene.node(&NodeId::from("node_hero_image")).unwrap();
    let NodeKind::Image(image) = &hero.kind else {
        panic!("asset placement should rewrite the placeholder node to an image");
    };
    assert_eq!(image.asset_id, AssetId::from("asset_generated_hero"));
    assert_eq!(image.alt.as_deref(), Some("Generated clinic hero"));
    assert_eq!(
        hero.asset_placement
            .as_ref()
            .and_then(|placement| placement.fit.clone()),
        Some(ImageFitMode::Cover)
    );

    let asset_diagnostics = validate_scene_assets(scene, AssetValidationOptions::strict());
    assert!(
        asset_diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "strict asset validation should pass for registered placement, got {asset_diagnostics:#?}"
    );

    assert_eq!(result.preview_artifacts.len(), 1);
    assert_eq!(
        result.preview_artifacts[0].format,
        lumen_core::ExportFormat::Svg
    );
    assert!(result.preview_artifacts[0].sidecar_json.is_some());
    assert!(String::from_utf8(result.preview_artifacts[0].bytes.clone())
        .unwrap()
        .contains("data-lumen-asset-id=\"asset_generated_hero\""));

    let dto = result.to_dto();
    let operation_kinds: Vec<_> = dto
        .operations
        .iter()
        .map(|operation| operation.kind.as_str())
        .collect();
    assert!(operation_kinds.contains(&"upsert_asset"));
    assert!(operation_kinds.contains(&"place_asset_in_slot"));
    assert_eq!(
        dto.preview.as_ref().unwrap().format,
        lumen_core::ExportFormat::Svg
    );
}

fn generated_asset() -> AssetRecord {
    serde_json::from_str(GENERATED_RASTER).unwrap()
}

fn asset_placement_operations() -> Vec<Operation> {
    let page_id = PageId::from("page_asset");
    let node_id = NodeId::from("node_hero_image");
    let slot_id = SlotId::from("slot_campaign_hero_image");
    let asset_id = AssetId::from("asset_generated_hero");

    let mut placeholder = Node::new(node_id.clone(), NodeKind::Rect);
    placeholder.name = Some("Hero image".to_owned());
    placeholder.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    placeholder.size = SizeSpec::fixed(240.0, 135.0);

    let mut slot = Slot::text_short(
        slot_id.clone(),
        SlotKey::from("campaign.hero_image"),
        "Hero image",
    );
    slot.content_type = ContentType::Image;
    slot.bound_nodes = vec![node_id.clone()];
    slot.required = false;
    slot.placeholder = Some("Generated clinic hero".to_owned());
    slot.overflow = OverflowPolicy::Error;
    slot.image_policy = Some(ImagePolicy {
        fit: ImageFitMode::Cover,
        focal_point: Some(FocalPoint { x: 0.5, y: 0.42 }),
        min_dpi: Some(72),
        preserve_transparency: false,
        aspect_ratio: Some(16.0 / 9.0),
    });

    vec![
        Operation::AddPage {
            page: Page {
                id: page_id.clone(),
                name: "Asset Preview".to_owned(),
                size: PageSize {
                    width: 320.0,
                    height: 180.0,
                    unit: Unit::Px,
                    preset: Some(PagePreset::Custom),
                    orientation: Orientation::Landscape,
                },
                children: Vec::new(),
                bleed: None,
                safe_area: Some(Rect {
                    x: 16.0,
                    y: 16.0,
                    width: 288.0,
                    height: 148.0,
                }),
                background: Vec::new(),
            },
        },
        Operation::InsertNode {
            parent: ParentRef::Page(page_id),
            index: 0,
            node: placeholder,
        },
        Operation::UpsertSlot { slot },
        Operation::UpsertAsset {
            asset: generated_asset(),
        },
        Operation::PlaceAssetInSlot {
            slot_id,
            asset_id,
            placement: AssetPlacement {
                fit: Some(ImageFitMode::Cover),
                focal_point: Some(FocalPoint { x: 0.5, y: 0.42 }),
                preserve_transparency: Some(false),
                alt_text: Some("Generated clinic hero".to_owned()),
            },
        },
    ]
}
