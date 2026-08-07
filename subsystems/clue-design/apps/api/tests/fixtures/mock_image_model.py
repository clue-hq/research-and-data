#!/usr/bin/env python3
"""Mock OpenRouter-shaped image model for Phase 3b browser e2e.

Stdlib-only (no PIL). Answers POST /chat/completions with the OpenRouter
chat-completions image shape:

    {"choices":[{"message":{"images":[{"image_url":{"url":"data:image/png;base64,<b64>"}}]}}]}

Determinism + visible distinctness rules (so a browser can *see* the difference):

- Plain GENERATION (request `content` is a bare string): return an opaque solid
  PNG. Colour is derived from the instruction/prompt hash, so two different
  prompts render two visibly different solids; an identical prompt renders the
  identical image (the model is deterministic, and the API's generation cache
  keys on the request, so a repeat is a cache hit and never reaches us).

- Image EDIT (`content` is a LIST of parts: image_url part(s) then a text part):
  colour is derived from the *edit instruction text* hash, so Before != After
  visibly. If the text part mentions "background"/"transparent"/"remove bg" OR
  the body hints transparency, return an RGBA PNG with a genuine alpha hole
  (a transparent centre disc) so remove-background is distinguishable from a
  plain colour swap.

Every response also carries a small opaque header stripe keyed to the hash so
even same-hued results differ, but the dominant field colour is the primary
signal. The server logs each request (kind + hash + colour) to stderr.

Usage:
    python3 mock_image_model.py [--port N] [--host H]
Prints the chosen port as the last line of stdout as `PORT=<n>` for capture.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SIZE = 512


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode_png(pixels: bytes, width: int, height: int, *, alpha: bool) -> bytes:
    """Encode raw pixel rows to a PNG. `pixels` is width*height*channels bytes,
    top-to-bottom, no filter bytes (we add filter 0 per scanline here)."""
    channels = 4 if alpha else 3
    color_type = 6 if alpha else 2
    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        raw.extend(pixels[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    sig = b"\x89PNG\r\n\x1a\n"
    return (
        sig
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _solid_png(rgb: tuple[int, int, int], stripe: tuple[int, int, int]) -> bytes:
    """Opaque solid field with a distinguishing top stripe (32px)."""
    r, g, b = rgb
    sr, sg, sb = stripe
    field_row = bytes((r, g, b)) * SIZE
    stripe_row = bytes((sr, sg, sb)) * SIZE
    pixels = bytearray()
    for y in range(SIZE):
        pixels.extend(stripe_row if y < 32 else field_row)
    return _encode_png(bytes(pixels), SIZE, SIZE, alpha=False)


def _transparent_png(rgb: tuple[int, int, int]) -> bytes:
    """RGBA field with a transparent centre disc — a genuine alpha hole so a
    remove-background edit is visibly distinct from an opaque colour swap."""
    r, g, b = rgb
    cx = cy = SIZE / 2.0
    radius = SIZE * 0.32
    r2 = radius * radius
    pixels = bytearray()
    for y in range(SIZE):
        dy = y - cy
        for x in range(SIZE):
            dx = x - cx
            if dx * dx + dy * dy <= r2:
                pixels.extend((0, 0, 0, 0))  # transparent hole
            else:
                pixels.extend((r, g, b, 255))
    return _encode_png(bytes(pixels), SIZE, SIZE, alpha=True)


def _hash_color(seed: str) -> tuple[int, int, int]:
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    # Keep it saturated + mid-bright so it reads clearly on canvas.
    return (64 + h[0] % 160, 64 + h[1] % 160, 64 + h[2] % 160)


def _extract(content: object) -> tuple[str, str, bool]:
    """Return (kind, hash_seed, wants_transparent).

    kind is 'generate' for a bare-string content, 'edit' for a list content.
    hash_seed is the text that drives the colour (prompt for generate, the last
    text part for edit). wants_transparent is True when the text hints bg removal.
    """
    if isinstance(content, str):
        # Plain generation stays opaque. The word "background" is common in a
        # generation prompt ("clean studio background") and must NOT force alpha —
        # only an explicit body-level transparency flag does (handled by caller).
        return "generate", content, False
    if isinstance(content, list):
        text = ""
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "")
        return "edit", text, _hints_transparent(text)
    return "generate", str(content), False


def _hints_transparent(text: str) -> bool:
    t = (text or "").lower()
    return any(
        kw in t
        for kw in ("background", "transparent", "remove bg", "remove-bg", "alpha")
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence default noisy logging
        return

    def _reply_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._reply_json(404, {"error": {"message": f"no route {self.path}"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError) as exc:
            self._reply_json(400, {"error": {"message": f"bad json: {exc}"}})
            return

        content: object = ""
        try:
            content = payload["messages"][0]["content"]
        except (KeyError, IndexError, TypeError):
            content = ""

        # Body-level transparency hint (some callers set it outside the text).
        body_hint = bool(
            payload.get("transparent_background")
            or payload.get("transparent")
            or "transparent" in json.dumps(payload).lower()[:0]  # noop guard
        )

        kind, seed, wants_transparent = _extract(content)
        wants_transparent = wants_transparent or body_hint
        color = _hash_color(seed or "empty")
        stripe = _hash_color("stripe:" + (seed or "empty"))

        if wants_transparent:
            png = _transparent_png(color)
            mode = "rgba-transparent"
        else:
            png = _solid_png(color, stripe)
            mode = "rgb-solid"

        print(
            f"[mock_image_model] kind={kind} mode={mode} color={color} "
            f"seed={seed[:60]!r}",
            file=sys.stderr,
            flush=True,
        )

        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        self._reply_json(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "images": [{"image_url": {"url": data_url}}],
                        }
                    }
                ]
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        # Simple health endpoint.
        if self.path.rstrip("/").endswith("/health") or self.path == "/":
            self._reply_json(200, {"ok": True})
            return
        self._reply_json(404, {"error": {"message": f"no route {self.path}"}})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    port = server.server_address[1]
    print(f"[mock_image_model] listening on http://{args.host}:{port}", file=sys.stderr, flush=True)
    print(f"PORT={port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
