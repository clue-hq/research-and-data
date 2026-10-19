"""Build the CLIP model directory the hybrid asset search runs on (founder ruling 2026-10-05).

Dev-machine tool: needs torch, transformers, onnx and onnxruntime, none of which the backend image
carries. The output directory is what LUMEN_ASSET_EMBEDDING_MODEL_DIR points at:

  image.onnx       fp32 image encoder  (ingestion embeds images with it; ~350 MB)
  text.onnx        int8 text encoder   (every search embeds its query with it; ~64 MB)
  tokenizer.json   CLIP's tokenizer, read by `tokenizers`
  preprocess.json  size/crop/mean/std the runtime applies
  model.json       {"space": ..., "image": "fp32", "text": "int8", "dim": 512}

Why mixed precision: an int8 image encoder drifted badly from the torch reference (cosine down
to 0.72) and lost a right answer on the T1 labels; the fp32 image encoder reproduces torch
exactly, and the int8 text encoder kept T1's result unchanged (plan doc
docs/superpowers/plans/2026-10-05-brand-imagery-findings-and-trials.md §7).

usage:
  uv venv /tmp/clipenv && VIRTUAL_ENV=/tmp/clipenv uv pip install torch transformers onnx onnxruntime onnxscript
  /tmp/clipenv/bin/python scripts/export_clip_onnx.py <output-dir>
Then copy the directory to every worker host (deploy/vm: /srv/clue/models/clip-vit-base-patch32-onnx).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

MODEL = "openai/clip-vit-base-patch32"


def main(out: Path) -> None:
    import torch
    from huggingface_hub import snapshot_download
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import CLIPModel

    out.mkdir(parents=True, exist_ok=True)
    snapshot = Path(snapshot_download(MODEL, allow_patterns=["*.json", "*.txt", "*.bin", "*.safetensors"]))
    model = CLIPModel.from_pretrained(snapshot).eval()

    # The model is registered as a submodule (not reached through a closure): the tracer must see
    # its weights as parameters, or the export fails on "a Tensor that requires grad as a constant".
    class Image(torch.nn.Module):
        def __init__(self, clip):
            super().__init__()
            self.clip = clip

        def forward(self, pixel_values):
            return self.clip.visual_projection(self.clip.vision_model(pixel_values=pixel_values).pooler_output)

    class Text(torch.nn.Module):
        def __init__(self, clip):
            super().__init__()
            self.clip = clip

        def forward(self, input_ids, attention_mask):
            return self.clip.text_projection(
                self.clip.text_model(input_ids=input_ids, attention_mask=attention_mask).pooler_output)

    with tempfile.TemporaryDirectory() as tmp, torch.no_grad():
        text_fp32 = Path(tmp) / "text.onnx"
        torch.onnx.export(Image(model), (torch.zeros(1, 3, 224, 224),), out / "image.onnx",
                          input_names=["pixel_values"], output_names=["image_embeds"],
                          dynamic_axes={"pixel_values": {0: "n"}, "image_embeds": {0: "n"}},
                          opset_version=17, dynamo=False)
        ids = torch.zeros(1, 77, dtype=torch.long)
        torch.onnx.export(Text(model), (ids, torch.ones_like(ids)), text_fp32,
                          input_names=["input_ids", "attention_mask"], output_names=["text_embeds"],
                          dynamic_axes={"input_ids": {0: "n"}, "attention_mask": {0: "n"},
                                        "text_embeds": {0: "n"}},
                          opset_version=17, dynamo=False)
        quantize_dynamic(str(text_fp32), str(out / "text.onnx"), weight_type=QuantType.QInt8)

    pre = json.loads((snapshot / "preprocessor_config.json").read_text())
    shutil.copy(snapshot / "tokenizer.json", out / "tokenizer.json")
    (out / "preprocess.json").write_text(json.dumps({
        "size": 224, "crop": 224, "mean": pre["image_mean"], "std": pre["image_std"],
        "resample": "bicubic", "context_length": 77}, indent=1) + "\n")
    (out / "model.json").write_text(json.dumps(
        {"space": MODEL, "image": "fp32", "text": "int8", "dim": 512}, indent=1) + "\n")
    print({p.name: f"{p.stat().st_size / 1e6:.0f} MB" for p in sorted(out.iterdir())})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]).expanduser())
