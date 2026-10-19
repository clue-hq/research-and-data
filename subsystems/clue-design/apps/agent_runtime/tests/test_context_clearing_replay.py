"""The replay script's token estimate counts screenshots by their pixels, not as a few text
tokens (LangChain's approximate counter undercounted them on the Syracuse replay)."""

from __future__ import annotations

import base64
import importlib.util
import io
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from PIL import Image

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "context_clearing_replay.py"


def _replay():
    spec = importlib.util.spec_from_file_location("context_clearing_replay", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_a_screenshot_counts_by_its_pixels_and_text_by_its_length() -> None:
    replay = _replay()
    shot = ToolMessage(
        tool_call_id="v1",
        content=[
            {"type": "text", "text": "x" * 400},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{_png(1500, 1000)}"},
            },
        ],
    )
    assert replay.estimate_tokens([shot]) == 100 + 1500 * 1000 // 750


def test_tool_call_arguments_count_and_an_unreadable_image_gets_a_flat_estimate() -> None:
    replay = _replay()
    call = AIMessage(content="", tool_calls=[{"id": "v1", "name": "view", "args": {"target": "p"}}])
    broken = ToolMessage(
        tool_call_id="v1",
        content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,bm90"}}],
    )
    assert replay.estimate_tokens([call]) > 0
    assert replay.estimate_tokens([broken]) == replay.UNREADABLE_IMAGE_TOKENS
