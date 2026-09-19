#!/usr/bin/env python3
"""Probe: can the Head-of-ABM model see an image sent as an `image_url` content part?

Spends money (one small model call). Run with the lane's `.env` sourced:
    set -a; source .env; set +a
    uv run python scripts/probe_chat_image_input.py [--model x-ai/grok-4.6] [--image PATH]

Two modes:

* **Default (synthetic PNG).** Sends a generated half-red/half-blue square and asks for the left
  then the right colour. The script judges: exit 0 = it named them in order, exit 1 = it did not.
  A machine-checkable test, but a guessable one — a blind model naming "red and blue" passes, and
  a sighted model that mirrors left/right fails. Round 1 hit exactly that.
* **`--image PATH` (a real file).** Sends the file and asks an OPEN question — describe the image
  and read any words in it. Nothing here is guessable, so no heuristic can judge it: the script
  prints the reply verbatim and exits 0 with `RESULT: SEE REPLY`. **The human judges.**

Two deliberate choices, so the probe answers the question the platform actually asks:

* It builds the provider from ``default_gateway_config()``, not a bare ``GatewayConfig()``.
  That is the config the production Head-of-ABM model is built from, and the difference is
  load-bearing here: it sets ``openrouter_chat_completions_fallback=True``, which routes a
  non-OpenAI model off OpenRouter's ``/responses`` translation — the translation that 400s
  ``invalid_union: expected string, received array`` on exactly the array-shaped message
  content this probe sends (``agent_model.py`` documents that live failure). On a bare
  ``GatewayConfig()`` a grok probe would fail on the wire shape and tell us nothing about
  whether the model can see.
* It allows a roomy output budget. This lane runs the dev reasoning lens
  (``CLUE_CHAT_REASONING_TRACE_MODE=raw`` -> ``reasoning.effort=medium``), so a tight
  ``max_output_tokens`` can be spent on reasoning and truncate the visible answer to
  nothing — a false "IMAGE NOT SEEN". The verdict logic below is unchanged.
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import zlib
from pathlib import Path

from langchain_core.messages import HumanMessage

from clue_config import Secrets
from clue_config.gateway import default_gateway_config
from clue_gateway import OpenRouterAgentModelProvider


def _png(width: int, height: int) -> bytes:
    """A PNG whose left half is pure red and right half pure blue; no Pillow needed."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    rows = b""
    for _ in range(height):
        row = b"\x00"
        for x in range(width):
            row += b"\xff\x00\x00" if x < width // 2 else b"\x00\x00\xff"
        rows += row
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


# Extensions this probe will send. Deliberately a closed map rather than `mimetypes.guess_type`:
# an unknown extension should stop the run before it spends, not send a guessed media type.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_COLOUR_QUESTION = (
    "This image has two solid color halves. Name the left color and the right color, in that "
    "order, in one short sentence."
)

# Open, unguessable, and answerable only by looking: a blind model cannot invent the company names
# printed in a real screenshot.
_OPEN_QUESTION = (
    "Describe what this image shows in two sentences. Name any words you can read in it."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="x-ai/grok-4.6")
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Send this image file and ask the open question instead of the synthetic colour test.",
    )
    args = parser.parse_args()

    if args.image is not None:
        media_type = _MEDIA_TYPES.get(args.image.suffix.lower())
        if media_type is None:
            print(
                f"unsupported image extension {args.image.suffix!r}; "
                f"expected one of {sorted(_MEDIA_TYPES)}",
                file=sys.stderr,
            )
            return 2
        payload = args.image.read_bytes()
        question = _OPEN_QUESTION
    else:
        media_type = "image/png"
        payload = _png(64, 64)
        question = _COLOUR_QUESTION

    api_key = Secrets().openrouter_api_key
    if api_key is None:
        print("CLUE_OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    config = default_gateway_config()
    provider = OpenRouterAgentModelProvider(config, api_key)
    # Free pre-spend signal from OpenRouter's own catalog; None = the catalog does not say.
    print(f"catalog_supports_image_input={provider.supports_image_input(args.model)}")
    model = provider.build(
        model_id=args.model,
        timeout_s=min(60.0, config.timeout_s),
        max_retries=0,
        max_output_tokens=1000,
        temperature=0,
        role="head_of_abm",
    )
    data_url = f"data:{media_type};base64," + base64.b64encode(payload).decode("ascii")
    message = HumanMessage(
        content=[
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )
    reply = model.invoke([message])
    # ``.text`` is a property on current LangChain; older builds expose a method. Take the property
    # when it is the string it claims to be, else fall back to the raw content.
    raw_text = getattr(reply, "text", None)
    text = raw_text if isinstance(raw_text, str) else str(reply.content)
    print(f"model={args.model}")

    if args.image is not None:
        print(f"image={args.image} ({len(payload)} bytes, {media_type})")
        print("--- reply (verbatim) ---")
        print(text)
        print("--- end reply ---")
        # No heuristic can grade an open answer, and a wrong one would be worse than none.
        print("RESULT: SEE REPLY")
        return 0

    print(f"reply={text!r}")
    lowered = text.lower()
    ok = "red" in lowered and "blue" in lowered and lowered.index("red") < lowered.index("blue")
    print("RESULT:", "IMAGE SEEN" if ok else "IMAGE NOT SEEN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
