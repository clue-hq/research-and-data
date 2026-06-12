//! Slice A5: the visual-regression manifest is live. Each manifest case
//! renders through the production Skia pipeline (the same composition the
//! api helper uses) and pixel-diffs against a committed PNG baseline.
//!
//! Regenerate intentionally with:
//! `UPDATE_LUMEN_VISUAL_BASELINES=1 cargo test -p lumen-skia --test visual_regression`

use lumen_core::{ExportAdapter, ExportPurpose, ExportRequest, PageId, Scene};
use lumen_export::LumenExportAdapter;
use lumen_skia::{FontManager, SkiaSceneRenderer, SkiaTextMeasurer};
use serde_json::Value;
use skia_safe::{surfaces, Data, Image};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Max per-channel delta tolerated before a pixel counts as different.
const CHANNEL_TOLERANCE: i32 = 2;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repo root resolves")
}

fn composed_adapter() -> LumenExportAdapter {
    let fonts = Arc::new(FontManager::bundled());
    LumenExportAdapter::new()
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::new(fonts)))
}

fn decode_rgba(png: &[u8]) -> (i32, i32, Vec<u8>) {
    let image = Image::from_encoded(Data::new_copy(png)).expect("png decodes");
    let info = skia_safe::ImageInfo::new(
        (image.width(), image.height()),
        skia_safe::ColorType::RGBA8888,
        skia_safe::AlphaType::Unpremul,
        None,
    );
    let mut pixels = vec![0u8; (image.width() * image.height() * 4) as usize];
    let row_bytes = (image.width() * 4) as usize;
    let mut surface =
        surfaces::raster_n32_premul((image.width(), image.height())).expect("surface");
    surface.canvas().draw_image(&image, (0, 0), None);
    assert!(surface.image_snapshot().read_pixels(
        &info,
        &mut pixels,
        row_bytes,
        (0, 0),
        skia_safe::image::CachingHint::Disallow
    ));
    (image.width(), image.height(), pixels)
}

fn assert_pixels_match(case_id: &str, actual: &[u8], baseline_path: &Path) {
    let expected = std::fs::read(baseline_path).unwrap_or_else(|_| {
        panic!(
            "missing visual baseline {baseline_path:?} for {case_id}; run with UPDATE_LUMEN_VISUAL_BASELINES=1"
        )
    });
    let (aw, ah, apx) = decode_rgba(actual);
    let (ew, eh, epx) = decode_rgba(&expected);
    assert_eq!((aw, ah), (ew, eh), "{case_id}: baseline dimensions changed");
    let differing = (0..(aw * ah) as usize)
        .filter(|index| {
            let offset = index * 4;
            (0..4).any(|channel| {
                (i32::from(apx[offset + channel]) - i32::from(epx[offset + channel])).abs()
                    > CHANNEL_TOLERANCE
            })
        })
        .count();
    assert_eq!(
        differing,
        0,
        "{case_id}: {differing}/{} pixels drifted from the baseline; regenerate intentionally with UPDATE_LUMEN_VISUAL_BASELINES=1",
        (aw * ah)
    );
}

#[test]
fn visual_regression_manifest_cases_match_baselines() {
    let root = repo_root();
    let manifest_path = root.join("crates/lumen-core/fixtures/visual_regression/manifest.json");
    let manifest: Value =
        serde_json::from_str(&std::fs::read_to_string(&manifest_path).expect("manifest reads"))
            .expect("manifest decodes");
    assert_eq!(manifest["schema_version"], 1);

    let update = std::env::var("UPDATE_LUMEN_VISUAL_BASELINES").is_ok();
    let cases = manifest["cases"].as_array().expect("cases");
    assert!(cases.len() >= 2);

    for case in cases {
        let case_id = case["id"].as_str().expect("case id");
        assert_eq!(
            case["status"], "active",
            "{case_id}: A5 activated every manifest case"
        );

        let scene_path = root.join(case["scene_fixture"].as_str().expect("fixture path"));
        let scene: Scene =
            serde_json::from_str(&std::fs::read_to_string(&scene_path).expect("scene reads"))
                .expect("scene decodes");

        let profile_name = case["profile"].as_str().expect("profile");
        let profile = scene
            .export_profiles
            .iter()
            .find(|profile| profile.name == profile_name)
            .unwrap_or_else(|| panic!("{case_id}: scene lacks profile {profile_name}"))
            .clone();

        let request = ExportRequest {
            profile,
            page_ids: vec![PageId::from(case["page_id"].as_str().expect("page id"))],
            purpose: ExportPurpose::AgentCritique,
        };
        let result = composed_adapter()
            .export(&scene, &request)
            .unwrap_or_else(|error| panic!("{case_id}: export failed: {error:?}"));
        assert_eq!(result.artifacts.len(), 1, "{case_id}");
        let png = &result.artifacts[0].bytes;

        let baseline_path = root.join(case["baseline"].as_str().expect("baseline path"));
        if update {
            std::fs::create_dir_all(baseline_path.parent().unwrap()).unwrap();
            std::fs::write(&baseline_path, png).unwrap();
        } else {
            assert_pixels_match(case_id, png, &baseline_path);
        }
    }
}
