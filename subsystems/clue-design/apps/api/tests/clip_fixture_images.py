"""Deterministic synthetic images and phrases for the CLIP parity fixture (hybrid asset search).

`tests/fixtures/clip_reference.json` holds what the ORIGINAL torch CLIP
(openai/clip-vit-base-patch32, transformers) produced for exactly these inputs; the ONNX runtime is
checked against it. Regenerating the fixture needs torch, so it is a dev-machine step:
`<torch env>/bin/python apps/api/tests/clip_fixture_images.py --write-reference`.
No alpha here on purpose: the runtime composites transparency over white, which torch does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PHRASES = [
    "a red circle on a white background",
    "a blue square on a white background",
    "a soft green gradient background",
    "black and white vertical stripes",
    "colourful random noise",
    "a yellow star",
    # Past CLIP's 77-token window: must truncate, never fail.
    " ".join(["a very long description of a background image with soft pastel colours"] * 12),
    "Café logo — ünïcödé ✓ 日本語",
]


def fixture_images():
    """[(name, PIL.Image)] — drawn, never loaded, so the bytes are identical everywhere."""
    import numpy as np
    from PIL import Image, ImageDraw

    images = []
    red = Image.new("RGB", (320, 320), "white")
    ImageDraw.Draw(red).ellipse((60, 60, 260, 260), fill=(220, 20, 30))
    images.append(("red_circle", red))
    blue = Image.new("RGB", (400, 260), "white")  # landscape: exercises the resize/crop path
    ImageDraw.Draw(blue).rectangle((130, 40, 310, 220), fill=(20, 40, 210))
    images.append(("blue_square", blue))
    grad = np.zeros((200, 300, 3), dtype=np.uint8)
    grad[..., 1] = np.linspace(120, 250, 300, dtype=np.uint8)[None, :]
    grad[..., 0] = 200
    grad[..., 2] = 210
    images.append(("green_gradient", Image.fromarray(grad)))
    stripes = Image.new("RGB", (120, 480), "white")  # tall portrait: 1:4
    draw = ImageDraw.Draw(stripes)
    for x in range(0, 120, 20):
        draw.rectangle((x, 0, x + 9, 479), fill="black")
    images.append(("stripes", stripes))
    rng = np.random.default_rng(7)
    images.append(("noise", Image.fromarray(rng.integers(0, 256, (256, 256, 3), dtype=np.uint8))))
    star = Image.new("RGB", (300, 300), (240, 240, 240))
    ImageDraw.Draw(star).polygon([(150, 20), (185, 115), (285, 115), (205, 175), (235, 275),
                                  (150, 215), (65, 275), (95, 175), (15, 115), (115, 115)], fill=(250, 210, 0))
    images.append(("yellow_star", star))
    gray = Image.new("L", (256, 256), 90)  # grayscale mode input
    ImageDraw.Draw(gray).ellipse((40, 40, 216, 216), fill=200)
    images.append(("gray_disc", gray))
    images.append(("tiny", Image.new("RGB", (3, 2), (10, 200, 90))))  # smaller than the crop
    return images


def write_reference(path: Path) -> None:
    import torch
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").eval()
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    def norm(v):
        v = v if isinstance(v, torch.Tensor) else v.pooler_output
        return torch.nn.functional.normalize(v, dim=-1)[0].tolist()

    out = {"model": "openai/clip-vit-base-patch32", "images": {}, "phrases": {}}
    with torch.no_grad():
        for name, image in fixture_images():
            out["images"][name] = [round(x, 6) for x in norm(model.get_image_features(
                **proc(images=[image.convert("RGB")], return_tensors="pt")))]
        for phrase in PHRASES:
            tok = proc(text=[phrase], return_tensors="pt", padding=True, truncation=True, max_length=77)
            out["phrases"][phrase] = [round(x, 6) for x in norm(model.get_text_features(**tok))]
    path.write_text(json.dumps(out))
    print("wrote", path, len(out["images"]), "images,", len(out["phrases"]), "phrases")


if __name__ == "__main__" and "--write-reference" in sys.argv:
    write_reference(Path(__file__).resolve().parent / "fixtures" / "clip_reference.json")
