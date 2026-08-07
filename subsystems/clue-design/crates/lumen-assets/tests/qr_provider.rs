use lumen_assets::{
    generate_qr, ingest, sha256_hex, IngestRequest, QrEcLevel, QrRequest, QR_QUIET_ZONE_MODULES,
};

fn request(data: &str) -> QrRequest {
    QrRequest {
        data: data.to_owned(),
        ec_level: None,
        print: false,
        target_width_mm: None,
    }
}

#[test]
fn same_input_yields_identical_bytes_and_digest() {
    let first = generate_qr(&request("https://lumen.example/a/acme-health")).expect("first");
    let second = generate_qr(&request("https://lumen.example/a/acme-health")).expect("second");

    assert_eq!(first.svg, second.svg);
    assert_eq!(
        sha256_hex(first.svg.as_bytes()),
        sha256_hex(second.svg.as_bytes())
    );

    // The digest is pinned: a change here means generated QR assets stop
    // deduplicating against previously stored bytes (an intentional,
    // reviewed break only).
    insta_like_pin(&first.svg);
}

fn insta_like_pin(svg: &str) {
    let digest = sha256_hex(svg.as_bytes());
    assert_eq!(
        digest,
        "477180f1bfcb5bc529c3a8876d6b7c0a2355369b34c169f5d372965c57eabe35",
        "pinned QR svg digest changed; svg head: {}",
        &svg[..svg.len().min(160)]
    );
}

#[test]
fn ec_level_changes_output_and_defaults_are_applied() {
    let medium = generate_qr(&request("https://lumen.example/a/acme-health")).expect("m");
    assert_eq!(medium.ec_level, QrEcLevel::M);

    let high = generate_qr(&QrRequest {
        ec_level: Some(QrEcLevel::H),
        ..request("https://lumen.example/a/acme-health")
    })
    .expect("h");
    assert_eq!(high.ec_level, QrEcLevel::H);
    assert_ne!(medium.svg, high.svg);
    assert!(high.module_count >= medium.module_count);

    // Print media defaults to H without an explicit level (Decision 1).
    let print = generate_qr(&QrRequest {
        print: true,
        ..request("https://lumen.example/a/acme-health")
    })
    .expect("print");
    assert_eq!(print.ec_level, QrEcLevel::H);
    assert_eq!(print.svg, high.svg);
}

#[test]
fn quiet_zone_surrounds_the_code() {
    let output = generate_qr(&request("https://lumen.example/a/acme-health")).expect("qr");

    assert_eq!(output.quiet_zone_modules, QR_QUIET_ZONE_MODULES);
    let total = output.module_count + 2 * QR_QUIET_ZONE_MODULES;
    assert!(output
        .svg
        .contains(&format!("viewBox=\"0 0 {total} {total}\"")));
    // No dark cell may start inside the quiet zone: every path cell is
    // offset by at least the quiet zone width.
    for command in output.svg.split('M').skip(1) {
        let Some((x, rest)) = command.split_once(',') else {
            continue;
        };
        let Some((y, _)) = rest.split_once('h') else {
            continue;
        };
        let x: u32 = x.parse().expect("x");
        let y: u32 = y.parse().expect("y");
        assert!(x >= QR_QUIET_ZONE_MODULES && x < total - QR_QUIET_ZONE_MODULES);
        assert!(y >= QR_QUIET_ZONE_MODULES && y < total - QR_QUIET_ZONE_MODULES);
    }
}

#[test]
fn print_size_diagnostic_fires_below_threshold() {
    let small = generate_qr(&QrRequest {
        print: true,
        target_width_mm: Some(14.0),
        ..request("https://lumen.example/a/acme-health")
    })
    .expect("qr");
    assert!(small
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0700"));

    let large = generate_qr(&QrRequest {
        print: true,
        target_width_mm: Some(28.0),
        ..request("https://lumen.example/a/acme-health")
    })
    .expect("qr");
    assert!(large.diagnostics.is_empty());
}

#[test]
fn empty_data_and_oversized_data_reject() {
    let empty = generate_qr(&request("   ")).expect_err("empty rejects");
    assert_eq!(empty.code, "qr.empty_data");
    assert_eq!(empty.diagnostic.code, "LUMA0702");

    let oversized = generate_qr(&QrRequest {
        ec_level: Some(QrEcLevel::H),
        ..request(&"x".repeat(8000))
    })
    .expect_err("oversized rejects");
    assert_eq!(oversized.code, "qr.encode_failed");
    assert_eq!(oversized.diagnostic.code, "LUMA0701");
}

#[test]
fn generated_svg_survives_ingest_sanitization_deterministically() {
    let output = generate_qr(&request("https://lumen.example/a/acme-health")).expect("qr");

    let first = ingest(&IngestRequest {
        declared_mime: Some("image/svg+xml"),
        ..IngestRequest::new(output.svg.as_bytes())
    })
    .expect("ingest");
    let second = ingest(&IngestRequest {
        declared_mime: Some("image/svg+xml"),
        ..IngestRequest::new(output.svg.as_bytes())
    })
    .expect("ingest again");

    assert_eq!(first.bytes, second.bytes);
    assert!(first
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.code != "LUMA0603"));
    let vector = first.vector.expect("vector metadata");
    let total = f64::from(output.module_count + 2 * QR_QUIET_ZONE_MODULES);
    assert_eq!(vector.width, Some(total));
    assert_eq!(vector.view_box, Some([0.0, 0.0, total, total]));
}
