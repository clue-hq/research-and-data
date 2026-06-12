use lumen_assets::{
    generate_qr, ingest, IngestRequest, ProviderRegistry, ProviderSourceBytes, QrRequest,
};
use lumen_core::{
    AssetGenerationConstraints, AssetGenerationRequest, AssetKind, AssetVectorizationRequest,
};

const LOGO_PNG: &[u8] = include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");

fn generation_request(prompt: &str) -> AssetGenerationRequest {
    AssetGenerationRequest {
        request_id: "req_test".to_owned(),
        prompt: prompt.to_owned(),
        output_kind: AssetKind::RasterImage,
        target_node_id: None,
        target_slot_id: None,
        constraints: AssetGenerationConstraints {
            width: Some(64),
            height: Some(32),
            mime_type: None,
            transparent_background: None,
            brand_notes: Vec::new(),
        },
    }
}

#[test]
fn stub_image_provider_round_trips_through_ingest_with_license_and_provenance() {
    let registry = ProviderRegistry::with_default_providers();
    let artifact = registry
        .generate("stub-image-v0", &generation_request("teal clinic hero"))
        .expect("generate");

    assert_eq!(artifact.mime_type, "image/png");
    assert_eq!(artifact.kind, AssetKind::RasterImage);
    assert_eq!(artifact.license.name, "stub_generated");
    assert!(artifact.license.allow_export);
    assert!(!artifact.provenance_notes.is_empty());
    assert!(artifact.provider_metadata.contains_key("prompt_digest"));

    // Normalization: provider bytes run through the same ingest pipeline
    // as uploads, picking up probe metadata and a thumbnail.
    let output = ingest(&IngestRequest {
        declared_mime: Some(&artifact.mime_type),
        kind_hint: Some(artifact.kind.clone()),
        ..IngestRequest::new(&artifact.bytes)
    })
    .expect("ingest");
    let raster = output.raster.expect("probe metadata");
    assert_eq!(raster.pixel_width, 64);
    assert_eq!(raster.pixel_height, 32);
    assert!(output.thumbnail.is_some());
}

#[test]
fn stub_image_provider_is_deterministic_per_prompt() {
    let registry = ProviderRegistry::with_default_providers();
    let first = registry
        .generate("stub-image-v0", &generation_request("teal clinic hero"))
        .expect("first");
    let second = registry
        .generate("stub-image-v0", &generation_request("teal clinic hero"))
        .expect("second");
    let different = registry
        .generate("stub-image-v0", &generation_request("amber retail hero"))
        .expect("different");

    assert_eq!(first.bytes, second.bytes);
    assert_ne!(first.bytes, different.bytes);
}

#[test]
fn qr_provider_speaks_the_generation_contract() {
    let registry = ProviderRegistry::with_default_providers();
    let request = AssetGenerationRequest {
        prompt: "https://lumen.example/a/acme-health".to_owned(),
        output_kind: AssetKind::Vector,
        ..generation_request("")
    };
    let artifact = registry.generate("qr-v1", &request).expect("generate");

    // The adapter produces exactly the deterministic bytes of the
    // dedicated QR surface at default settings.
    let direct = generate_qr(&QrRequest {
        data: "https://lumen.example/a/acme-health".to_owned(),
        ec_level: None,
        print: false,
        target_width_mm: None,
    })
    .expect("direct");
    assert_eq!(artifact.bytes, direct.svg.into_bytes());
    assert_eq!(artifact.kind, AssetKind::Vector);
    assert_eq!(artifact.license.name, "generated_qr");
    assert_eq!(
        artifact.provider_metadata.get("quiet_zone_modules"),
        Some(&"4".to_owned())
    );
}

#[test]
fn vectorization_stub_round_trips_with_source_metadata() {
    let registry = ProviderRegistry::with_default_providers();
    let request = AssetVectorizationRequest {
        request_id: "req_vec".to_owned(),
        source_asset_id: lumen_core::AssetId::from("asset_logo"),
        target_node_id: None,
        target_slot_id: None,
        preserve_colors: true,
    };
    let source = ProviderSourceBytes {
        mime_type: "image/png".to_owned(),
        bytes: LOGO_PNG.to_vec(),
    };

    let artifact = registry
        .vectorize("stub-vectorize-v0", &request, &source)
        .expect("vectorize");

    assert_eq!(artifact.mime_type, "image/svg+xml");
    assert_eq!(artifact.kind, AssetKind::Vector);
    assert_eq!(artifact.license.name, "stub_vectorized");
    assert!(artifact
        .provenance_notes
        .iter()
        .any(|note| note.contains("asset_logo")));
    let digest = artifact
        .provider_metadata
        .get("source_digest")
        .expect("source digest");
    assert_eq!(digest, &lumen_assets::sha256_hex(LOGO_PNG));

    // The emitted SVG survives sanitization unchanged (no hostile
    // constructs) and parses into vector metadata.
    let output = ingest(&IngestRequest {
        declared_mime: Some("image/svg+xml"),
        ..IngestRequest::new(&artifact.bytes)
    })
    .expect("ingest");
    assert!(output.vector.is_some());
}

#[test]
fn unknown_provider_ids_are_typed_errors() {
    let registry = ProviderRegistry::with_default_providers();

    let error = registry
        .generate("imaginary-model-v9", &generation_request("anything"))
        .expect_err("unknown id rejects");
    assert_eq!(error.code, "provider.unknown");
    assert!(error.message.contains("qr-v1"));
    assert!(error.message.contains("stub-image-v0"));

    let error = registry
        .vectorize(
            "imaginary-tracer",
            &AssetVectorizationRequest {
                request_id: "req".to_owned(),
                source_asset_id: lumen_core::AssetId::from("asset_x"),
                target_node_id: None,
                target_slot_id: None,
                preserve_colors: false,
            },
            &ProviderSourceBytes {
                mime_type: "image/png".to_owned(),
                bytes: LOGO_PNG.to_vec(),
            },
        )
        .expect_err("unknown vectorizer rejects");
    assert_eq!(error.code, "provider.unknown");
}

#[test]
fn empty_prompts_and_empty_sources_reject() {
    let registry = ProviderRegistry::with_default_providers();

    let error = registry
        .generate("stub-image-v0", &generation_request("   "))
        .expect_err("empty prompt rejects");
    assert_eq!(error.code, "provider.empty_prompt");

    let error = registry
        .vectorize(
            "stub-vectorize-v0",
            &AssetVectorizationRequest {
                request_id: "req".to_owned(),
                source_asset_id: lumen_core::AssetId::from("asset_x"),
                target_node_id: None,
                target_slot_id: None,
                preserve_colors: false,
            },
            &ProviderSourceBytes {
                mime_type: "image/png".to_owned(),
                bytes: Vec::new(),
            },
        )
        .expect_err("empty source rejects");
    assert_eq!(error.code, "provider.empty_source");
}
