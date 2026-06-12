use lumen_core::validation::validate_scene;
use lumen_core::{
    platform_default_brand_kit, validate_brand_asset_references, validate_scene_assets, AssetId,
    AssetKind, AssetLicense, AssetMediaMetadata, AssetPlacement, AssetProvenance, AssetRecord,
    AssetSource, AssetStatus, AssetValidationOptions, AssetVectorizationResult, ContentType,
    Diagnostic, DocumentId, ExportFormat, ExportProfile, FocalPoint, ImageFitMode, ImageNode,
    ImagePolicy, LogoAsset, LogoAssetMetadata, LogoColorMode, LogoUsage, LogoVariant, Node, NodeId,
    NodeKind, Operation, Orientation, OverflowPolicy, Page, PageId, PagePreset, PageSize,
    ParentRef, PdfIntent, RasterAssetMetadata, Scene, SizeSpec, Slot, SlotId, SlotKey, TextAlign,
    TextNode, Unit,
};

const UPLOADED_LOGO: &str = include_str!("../fixtures/assets/uploaded_logo_asset.json");
const GENERATED_RASTER: &str = include_str!("../fixtures/assets/generated_raster_asset.json");
const VECTORIZED_SVG: &str = include_str!("../fixtures/assets/vectorized_svg_asset.json");
const FONT_ASSET: &str = include_str!("../fixtures/assets/font_asset.json");
const INVALID_REFERENCE_SCENE: &str =
    include_str!("../fixtures/assets/invalid_missing_asset_scene.json");

fn decode_asset(source: &str) -> AssetRecord {
    serde_json::from_str(source).unwrap()
}

fn page() -> Page {
    Page {
        id: PageId::from("page"),
        name: "Page".to_owned(),
        size: PageSize {
            width: 400.0,
            height: 300.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: None,
        background: Vec::new(),
    }
}

fn export_profile() -> ExportProfile {
    ExportProfile {
        name: "print_pdf".to_owned(),
        format: ExportFormat::Pdf,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: true,
        embed_fonts: true,
    }
}

fn scene_with_page() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_assets"), "Assets");
    scene
        .apply_operation(Operation::AddPage { page: page() })
        .unwrap();
    scene
        .apply_operation(Operation::UpsertExportProfile {
            profile: export_profile(),
        })
        .unwrap();
    scene
}

fn image_policy() -> ImagePolicy {
    ImagePolicy {
        fit: ImageFitMode::Contain,
        focal_point: Some(FocalPoint { x: 0.5, y: 0.5 }),
        min_dpi: Some(144),
        preserve_transparency: true,
        aspect_ratio: Some(1.0),
    }
}

fn text_node(id: &str, content: &str) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 600,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec::fixed(180.0, 24.0);
    node
}

fn logo_slot() -> Slot {
    let mut slot = Slot::text_short(
        SlotId::from("slot_logo"),
        SlotKey::from("account.logo"),
        "Account logo",
    );
    slot.content_type = ContentType::Logo;
    slot.placeholder = Some("Logo".to_owned());
    slot.overflow = OverflowPolicy::Error;
    slot.image_policy = Some(image_policy());
    slot
}

fn insert(scene: &mut Scene, node: Node) {
    let index = scene.pages[&PageId::from("page")].children.len();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page")),
            index,
            node,
        })
        .unwrap();
}

fn has_code(diagnostics: &[Diagnostic], code: &str) -> bool {
    diagnostics.iter().any(|diagnostic| diagnostic.code == code)
}

#[test]
fn asset_record_fixtures_round_trip_deterministically() {
    for source in [UPLOADED_LOGO, GENERATED_RASTER, VECTORIZED_SVG, FONT_ASSET] {
        let asset = decode_asset(source);
        let first = serde_json::to_string_pretty(&asset).unwrap();
        let decoded: AssetRecord = serde_json::from_str(&first).unwrap();
        let second = serde_json::to_string_pretty(&decoded).unwrap();

        assert_eq!(asset, decoded);
        assert_eq!(first, second);
    }
}

#[test]
fn upsert_and_remove_asset_update_scene_registry() {
    let mut scene = scene_with_page();
    let asset = decode_asset(UPLOADED_LOGO);

    scene
        .apply_operation(Operation::UpsertAsset {
            asset: asset.clone(),
        })
        .unwrap();
    assert_eq!(scene.asset(&asset.id), Some(&asset));

    scene
        .apply_operation(Operation::RemoveAsset {
            asset_id: asset.id.clone(),
        })
        .unwrap();
    assert!(scene.asset(&asset.id).is_none());
}

#[test]
fn places_uploaded_logo_asset_into_logo_slot() {
    let mut scene = scene_with_page();
    let asset = decode_asset(UPLOADED_LOGO);
    scene
        .apply_operation(Operation::UpsertAsset { asset })
        .unwrap();

    let mut placeholder = Node::new(NodeId::from("node_logo"), NodeKind::Rect);
    placeholder.size = SizeSpec::fixed(64.0, 64.0);
    insert(&mut scene, placeholder);

    scene
        .apply_operation(Operation::UpsertSlot { slot: logo_slot() })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_logo"),
            node_id: NodeId::from("node_logo"),
        })
        .unwrap();

    scene
        .apply_operation(Operation::PlaceAssetInSlot {
            slot_id: SlotId::from("slot_logo"),
            asset_id: AssetId::from("asset_uploaded_logo"),
            placement: AssetPlacement {
                fit: Some(ImageFitMode::Crop),
                focal_point: Some(FocalPoint { x: 0.25, y: 0.75 }),
                preserve_transparency: Some(true),
                alt_text: Some("Acme logo".to_owned()),
            },
        })
        .unwrap();

    let node = scene.node(&NodeId::from("node_logo")).unwrap();
    let NodeKind::Image(image) = &node.kind else {
        panic!("logo slot placement should rewrite the placeholder as an image node");
    };
    assert_eq!(image.asset_id, AssetId::from("asset_uploaded_logo"));
    assert_eq!(image.alt.as_deref(), Some("Acme logo"));
    assert_eq!(
        node.asset_placement,
        Some(AssetPlacement {
            fit: Some(ImageFitMode::Crop),
            focal_point: Some(FocalPoint { x: 0.25, y: 0.75 }),
            preserve_transparency: Some(true),
            alt_text: Some("Acme logo".to_owned()),
        })
    );

    let diagnostics = validate_scene_assets(&scene, AssetValidationOptions::strict());
    assert!(
        diagnostics.is_empty(),
        "expected strict asset validation to pass, got {diagnostics:#?}"
    );
}

#[test]
fn places_generated_raster_image_into_image_node() {
    let mut scene = scene_with_page();
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: decode_asset(GENERATED_RASTER),
        })
        .unwrap();

    let mut node = Node::new(
        NodeId::from("node_hero"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_placeholder"),
            alt: Some("Placeholder".to_owned()),
        }),
    );
    node.size = SizeSpec::fixed(320.0, 180.0);
    insert(&mut scene, node);

    scene
        .apply_operation(Operation::PlaceAssetInNode {
            node_id: NodeId::from("node_hero"),
            asset_id: AssetId::from("asset_generated_hero"),
            placement: AssetPlacement {
                fit: Some(ImageFitMode::Cover),
                focal_point: Some(FocalPoint { x: 0.5, y: 0.4 }),
                preserve_transparency: Some(false),
                alt_text: Some("Generated clinic hero".to_owned()),
            },
        })
        .unwrap();

    let node = scene.node(&NodeId::from("node_hero")).unwrap();
    let NodeKind::Image(image) = &node.kind else {
        panic!("generated raster should remain an image node");
    };
    assert_eq!(image.asset_id, AssetId::from("asset_generated_hero"));
    assert_eq!(image.alt.as_deref(), Some("Generated clinic hero"));
    assert_eq!(
        node.asset_placement,
        Some(AssetPlacement {
            fit: Some(ImageFitMode::Cover),
            focal_point: Some(FocalPoint { x: 0.5, y: 0.4 }),
            preserve_transparency: Some(false),
            alt_text: Some("Generated clinic hero".to_owned()),
        })
    );
}

#[test]
fn place_asset_in_slot_rejects_image_assets_for_text_slots() {
    let mut scene = scene_with_page();
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: decode_asset(GENERATED_RASTER),
        })
        .unwrap();
    insert(&mut scene, text_node("node_name", "Apollo Neuroscience"));

    let mut slot = Slot::text_short(
        SlotId::from("slot_account_name"),
        SlotKey::from("account.name"),
        "Account name",
    );
    slot.placeholder = Some("Apollo Neuroscience".to_owned());
    slot.validation.max_length = Some(80);
    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_account_name"),
            node_id: NodeId::from("node_name"),
        })
        .unwrap();

    let error = scene
        .apply_operation(Operation::PlaceAssetInSlot {
            slot_id: SlotId::from("slot_account_name"),
            asset_id: AssetId::from("asset_generated_hero"),
            placement: AssetPlacement::default(),
        })
        .unwrap_err();

    assert_eq!(error.code, "op.asset_incompatible");
    assert!(matches!(
        scene.node(&NodeId::from("node_name")).unwrap().kind,
        NodeKind::Text(_)
    ));
}

#[test]
fn remove_asset_rejects_assets_still_referenced_by_nodes() {
    let mut scene = scene_with_page();
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: decode_asset(GENERATED_RASTER),
        })
        .unwrap();
    let mut node = Node::new(
        NodeId::from("node_hero"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_generated_hero"),
            alt: Some("Hero".to_owned()),
        }),
    );
    node.source_asset_id = Some(AssetId::from("asset_generated_hero"));
    insert(&mut scene, node);

    let error = scene
        .apply_operation(Operation::RemoveAsset {
            asset_id: AssetId::from("asset_generated_hero"),
        })
        .unwrap_err();

    assert_eq!(error.code, "op.asset_in_use");
    assert!(scene
        .assets
        .contains_key(&AssetId::from("asset_generated_hero")));
}

#[test]
fn validation_rejects_text_slots_bound_to_image_nodes() {
    let mut scene = scene_with_page();
    insert(
        &mut scene,
        Node::new(
            NodeId::from("node_bad_image"),
            NodeKind::Image(ImageNode {
                asset_id: AssetId::from("asset_missing"),
                alt: None,
            }),
        ),
    );
    let mut slot = Slot::text_short(
        SlotId::from("slot_bad_text"),
        SlotKey::from("account.name"),
        "Account name",
    );
    slot.placeholder = Some("Apollo Neuroscience".to_owned());
    slot.validation.max_length = Some(80);
    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_bad_text"),
            node_id: NodeId::from("node_bad_image"),
        })
        .unwrap();

    let diagnostics = validate_scene(&scene);
    assert!(has_code(&diagnostics, "LUMV0520"));
}

#[test]
fn vectorization_hook_result_carries_vector_asset_record() {
    let result = AssetVectorizationResult {
        request_id: "vectorize_1".to_owned(),
        source_asset_id: AssetId::from("asset_uploaded_logo"),
        asset: decode_asset(VECTORIZED_SVG),
        provider_metadata: Default::default(),
        diagnostics: Vec::new(),
    };

    assert_eq!(result.asset.kind, AssetKind::Vector);
    assert_eq!(
        result.asset.source,
        AssetSource::Vectorized {
            source_asset_id: AssetId::from("asset_uploaded_logo"),
            tool: Some("mock-vectorizer".to_owned())
        }
    );
}

#[test]
fn strict_asset_validation_reports_missing_asset_references() {
    let scene: Scene = serde_json::from_str(INVALID_REFERENCE_SCENE).unwrap();

    let diagnostics = validate_scene_assets(&scene, AssetValidationOptions::strict());

    assert!(has_code(&diagnostics, "LUMA0200"));
    assert!(has_code(&diagnostics, "LUMA0302"));
}

#[test]
fn image_slot_policy_metadata_and_license_are_validated() {
    let mut scene = scene_with_page();
    let restricted_asset = AssetRecord {
        id: AssetId::from("asset_restricted_logo"),
        label: "Restricted logo".to_owned(),
        kind: AssetKind::Logo,
        status: AssetStatus::Ready,
        source: AssetSource::Uploaded {
            asset_id: None,
            filename: Some("restricted-logo.png".to_owned()),
            uploaded_by: Some("tester".to_owned()),
        },
        media: AssetMediaMetadata {
            mime_type: Some("image/png".to_owned()),
            filename: Some("restricted-logo.png".to_owned()),
            byte_length: Some(128),
            digest: None,
            location: None,
            thumbnail: None,
        },
        raster: Some(RasterAssetMetadata {
            pixel_width: 320,
            pixel_height: 160,
            dpi_x: Some(72.0),
            dpi_y: Some(72.0),
            has_alpha: Some(false),
            color_profile: None,
            aspect_ratio: Some(2.0),
        }),
        vector: None,
        font: None,
        logo: Some(LogoAssetMetadata {
            pixel_width: Some(320),
            pixel_height: Some(160),
            width: None,
            height: None,
            dpi_x: Some(72.0),
            dpi_y: Some(72.0),
            has_transparency: Some(false),
            color_mode: Some("full_color".to_owned()),
            clearspace: None,
        }),
        license: Some(AssetLicense {
            name: "restricted".to_owned(),
            allow_export: false,
            allow_modification: false,
            allow_embedding: false,
            allow_subsetting: false,
            source_url: None,
            restrictions: vec!["internal preview only".to_owned()],
        }),
        provenance: AssetProvenance::default(),
        tags: Vec::new(),
    };
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: restricted_asset,
        })
        .unwrap();

    let mut node = Node::new(
        NodeId::from("node_logo"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_restricted_logo"),
            alt: Some("Restricted logo".to_owned()),
        }),
    );
    node.source_asset_id = Some(AssetId::from("asset_restricted_logo"));
    node.size = SizeSpec::fixed(64.0, 64.0);
    insert(&mut scene, node);

    let mut slot = logo_slot();
    slot.image_policy = Some(ImagePolicy {
        fit: ImageFitMode::Crop,
        focal_point: Some(FocalPoint { x: 0.5, y: 0.5 }),
        min_dpi: Some(144),
        preserve_transparency: true,
        aspect_ratio: Some(1.0),
    });
    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_logo"),
            node_id: NodeId::from("node_logo"),
        })
        .unwrap();

    let diagnostics = validate_scene_assets(&scene, AssetValidationOptions::strict());
    assert!(has_code(&diagnostics, "LUMA0310"));
    assert!(has_code(&diagnostics, "LUMA0311"));
    assert!(has_code(&diagnostics, "LUMA0313"));
    assert!(has_code(&diagnostics, "LUMA0400"));
    assert!(has_code(&diagnostics, "LUMA0401"));
}

#[test]
fn brand_kit_font_and_logo_refs_can_match_scene_assets() {
    let mut scene = scene_with_page();
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: decode_asset(UPLOADED_LOGO),
        })
        .unwrap();
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: decode_asset(FONT_ASSET),
        })
        .unwrap();

    let mut brand_kit = platform_default_brand_kit().unwrap();
    let font = brand_kit.assets.fonts.get_mut("brand").unwrap();
    font.faces[0].asset_id = Some(AssetId::from("asset_font_inter"));
    brand_kit.assets.logos.insert(
        "primary".to_owned(),
        LogoAsset {
            variants: vec![LogoVariant {
                name: "full_color".to_owned(),
                asset_id: AssetId::from("asset_uploaded_logo"),
                color_mode: LogoColorMode::FullColor,
                width: Some(120.0),
                height: Some(120.0),
            }],
            usage: LogoUsage::Primary,
            min_size: Some(32.0),
            clearspace: Some(8.0),
            allowed_backgrounds: Vec::new(),
            license: None,
            provenance: None,
        },
    );

    let diagnostics = validate_brand_asset_references(&scene, &brand_kit);
    assert!(
        diagnostics.is_empty(),
        "expected brand asset refs to match scene assets, got {diagnostics:#?}"
    );
}
