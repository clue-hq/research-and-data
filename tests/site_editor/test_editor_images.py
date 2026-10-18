"""Site element inspector, plan 5: images in the real editor frame.

A click on our Feature split's image posts `selected` with an image: how it is drawn, and where its
file and alt text are written; a copied <picture>'s <img> is the image; a fixed-height copied photo's
Fill and Fit differ, a full-width one's do not; a `set_props` carrying fit, corners and alt text
redraws the image.

    cd apps/frontend && npm run build -w @clue/site-kit && npm run build -w @clue/site-editor
    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \\
        tests/site_editor/test_editor_images.py
"""

from __future__ import annotations

import base64
import copy
import struct
import zlib
from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received
from .test_editor_element_styling import computed, wait_selected

pytestmark = BROWSER_OPT_IN
WHAT = '[data-puck-component="what"]'


def png(width: int, height: int) -> str:
    """A plain PNG of this size, as a data: URL (a known natural shape for the frame to read)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + b"\x80\x80\x80" * width
    raw = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + raw).decode()


PHOTO = png(40, 30)
GALLERY_ID = "frag_00000000000000c5"
GALLERY = {
    "id": GALLERY_ID,
    "role": "section",
    "label": "Gallery",
    "page_url": "https://garnerhealth.com/",
    "section_index": 0,
    "wrapper_class": "lumen-frag-gallery",
    "html": (
        f'<div class="g"><img class="tall" data-lumen-slot="photo" src="{PHOTO}" alt="Captured">'
        f'<picture><source srcset="{PHOTO}"><img class="pic" src="{PHOTO}" alt="In a picture"></picture></div>'
    ),
    "css": ".g{padding:24px}.g .tall{display:block;width:100%;height:120px}.g .pic{display:block;width:200px}",
    "slots": {"photo": {"kind": "image", "fallback": PHOTO}},
}


def images_init() -> dict[str, Any]:
    init = garner_init(mode="edit")
    init["route"] = "/analysis"
    init["brand"]["clones"][GALLERY_ID] = GALLERY
    content = init["site"]["pages"]["/analysis"]["content"]
    next(item for item in content if item["props"]["id"] == "what")["props"]["image"] = PHOTO
    content.insert(1, {"type": "ClonedSection", "props": {"id": "gallery", "fragmentId": GALLERY_ID, "slots": {}, "replacements": [], "links": []}})
    return init


def open_images(app: Any, browser_page: Any, editor_origin: str, init: dict[str, Any]) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.locator(f'{WHAT} [data-clue-el="image"]').first.wait_for(timeout=20000)
    page.wait_for_timeout(1000)
    return page, frame


def click(page: Any, frame: Any, selector: str) -> None:
    frame.locator(selector).first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = frame.locator(selector).first.bounding_box()
    assert box, selector
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def test_a_click_on_our_image_selects_it_with_how_it_is_drawn_and_where_it_is_written(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_images(app, browser_page, editor_origin, images_init())
    mark = len(received(page))
    click(page, frame, f'{WHAT} [data-clue-el="image"]')
    element = wait_selected(page, mark, "image", "what")["element"]
    assert element["kind"] == "image", element
    assert element["image"]["media"] == "img" and element["image"]["fitMatters"] is False, element["image"]
    assert element["imageSource"] == {"kind": "prop", "prop": "image", "uses": 1}
    assert element["altSource"] == {"kind": "prop", "prop": "imageAlt"}


def test_a_fixed_height_copied_photo_has_fit_a_pictures_img_is_the_image(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, frame = open_images(app, browser_page, editor_origin, images_init())
    tall = '[data-puck-component="gallery"] img.tall'
    key = frame.locator(tall).first.get_attribute("data-clue-el")
    mark = len(received(page))
    click(page, frame, tall)
    element = wait_selected(page, mark, key, "gallery")["element"]
    assert element["image"]["fitMatters"] is True, element["image"]
    assert element["imageSource"] == {"kind": "slot", "slot": "photo", "uses": 1}
    assert element["altSource"] == {"kind": "clone", "key": key}

    inner = '[data-puck-component="gallery"] img.pic'
    inner_key = frame.locator(inner).first.get_attribute("data-clue-el")
    picture_key = frame.locator('[data-puck-component="gallery"] picture').first.get_attribute("data-clue-el")
    assert inner_key and inner_key.startswith(f"{picture_key}."), (inner_key, picture_key)
    mark = len(received(page))
    click(page, frame, inner)
    assert wait_selected(page, mark, inner_key, "gallery")["element"]["kind"] == "image"


def test_fit_corners_and_alt_text_redraw_the_image(app: Any, browser_page: Any, editor_origin: str) -> None:
    init = images_init()
    page, frame = open_images(app, browser_page, editor_origin, init)
    props = copy.deepcopy(next(item["props"] for item in init["site"]["pages"]["/analysis"]["content"] if item["props"]["id"] == "what"))
    props["imageAlt"] = 'Dr. "Smith" & the clinic'
    props["_edits"] = {"image": {"imageFit": "fit", "radius": 24}}
    page.evaluate("(props) => window.__send('set_props', { route: '/analysis', componentId: 'what', props, rev: 2 })", props)
    image = f'{WHAT} [data-clue-el="image"]'
    frame.wait_for_function("(sel) => getComputedStyle(document.querySelector(sel)).objectFit === 'contain'", arg=image, timeout=10000)
    assert computed(frame, image, "borderTopLeftRadius") == "24px"
    assert frame.locator(image).first.get_attribute("alt") == 'Dr. "Smith" & the clinic'
