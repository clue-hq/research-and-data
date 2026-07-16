//! Print W2b gates: exact box geometry (L3) — TrimBox inside the
//! bleed-expanded MediaBox/BleedBox, with the layout→PDF y-flip.

use lopdf::{dictionary, Document, Object};
use lumen_core::{Fill, Orientation, Page, PageId, PagePreset, PageSize, Rect, Unit};
use lumen_export::{apply_print_boxes, page_boxes_for, PageBoxes};

fn print_page(bleed: Option<Rect>) -> Page {
    Page {
        id: PageId::from("page_boxes"),
        name: "Boxes".to_owned(),
        size: PageSize {
            width: 200.0,
            height: 150.0,
            unit: Unit::Pt,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
            source: None,
            output: None,
        },
        children: Vec::new(),
        bleed,
        safe_area: None,
        background: Vec::<Fill>::new(),
    }
}

fn minimal_pdf(page_count: usize) -> Vec<u8> {
    let mut document = Document::with_version("1.4");
    let pages_id = document.new_object_id();
    let kids: Vec<Object> = (0..page_count)
        .map(|_| {
            let page_id = document.add_object(dictionary! {
                "Type" => "Page",
                "Parent" => Object::Reference(pages_id),
                "MediaBox" => vec![0.into(), 0.into(), 10.into(), 10.into()],
            });
            Object::Reference(page_id)
        })
        .collect();
    document.objects.insert(
        pages_id,
        Object::Dictionary(dictionary! {
            "Type" => "Pages",
            "Kids" => kids,
            "Count" => page_count as i64,
        }),
    );
    let catalog_id = document.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => Object::Reference(pages_id),
    });
    document.trailer.set("Root", Object::Reference(catalog_id));
    let mut bytes = Vec::new();
    document.save_to(&mut bytes).unwrap();
    bytes
}

#[test]
fn bleed_boxes_put_trim_inside_with_y_flip() {
    // 9pt symmetric bleed: layout bleed rect (-9,-9,218,168) around a
    // 200x150 page. PDF is y-up: trim x0=y0=9, x1=209, y1=159.
    let page = print_page(Some(Rect {
        x: -9.0,
        y: -9.0,
        width: 218.0,
        height: 168.0,
    }));
    let boxes = page_boxes_for(&page, true);
    assert_eq!(boxes.media, [0.0, 0.0, 218.0, 168.0]);
    assert_eq!(boxes.bleed, boxes.media);
    assert_eq!(boxes.trim, [9.0, 9.0, 209.0, 159.0]);

    // Asymmetric bleed (e.g. no bleed on the bound edge): trim offsets
    // follow each side independently. Layout: 3pt left/top, 0 right, 6pt
    // bottom → PDF y-up: y0 = 6 (bottom gap), y1 = 156.
    let page = print_page(Some(Rect {
        x: -3.0,
        y: -3.0,
        width: 203.0,
        height: 159.0,
    }));
    let boxes = page_boxes_for(&page, true);
    assert_eq!(boxes.trim, [3.0, 6.0, 203.0, 156.0]);
}

#[test]
fn no_bleed_collapses_all_boxes_to_trim() {
    let page = print_page(None);
    let boxes = page_boxes_for(&page, true);
    assert_eq!(boxes.media, [0.0, 0.0, 200.0, 150.0]);
    assert_eq!(boxes.trim, boxes.media);
    let boxes = page_boxes_for(&print_page(None), false);
    assert_eq!(boxes.trim, [0.0, 0.0, 200.0, 150.0]);
}

#[test]
fn apply_rewrites_boxes_and_is_deterministic() {
    let bytes = minimal_pdf(2);
    let boxes = vec![
        PageBoxes {
            media: [0.0, 0.0, 218.0, 168.0],
            trim: [9.0, 9.0, 209.0, 159.0],
            bleed: [0.0, 0.0, 218.0, 168.0],
        };
        2
    ];

    let first = apply_print_boxes(&bytes, &boxes).expect("boxes applied");
    let second = apply_print_boxes(&bytes, &boxes).expect("boxes applied twice");
    assert_eq!(first, second, "post-process must be deterministic");

    let document = Document::load_mem(&first).unwrap();
    for (_, page_id) in document.get_pages() {
        let page_dict = document.get_object(page_id).unwrap().as_dict().unwrap();
        let trim: Vec<f32> = page_dict
            .get(b"TrimBox")
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_float().unwrap())
            .collect();
        assert_eq!(trim, vec![9.0, 9.0, 209.0, 159.0]);
        assert!(page_dict.get(b"BleedBox").is_ok());
    }
}

#[test]
fn page_count_mismatch_fails_loudly() {
    let bytes = minimal_pdf(2);
    let boxes = vec![PageBoxes {
        media: [0.0, 0.0, 100.0, 100.0],
        trim: [0.0, 0.0, 100.0, 100.0],
        bleed: [0.0, 0.0, 100.0, 100.0],
    }];
    let error = apply_print_boxes(&bytes, &boxes).unwrap_err();
    assert!(error.contains("does not match"), "{error}");
}
