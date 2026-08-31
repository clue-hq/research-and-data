"""P3.2 probe (PD-part3 §4): do the design agent's multimodal + structured-output shapes
survive the platform gateway's Responses-API path?

The single highest-risk unknown of the gateway move (design-side survey §c-1): the design
runtime returns images as LangChain v0 content blocks **inside ToolMessage content**
(`view.py:97-108` — `{"type": "image", "source_type": "base64", ...}`), while
`GovernedAgentChatModel` wraps `ChatOpenAI(use_responses_api=True,
output_version="responses/v1")`. Three live sub-probes, each answering one question:

  A. Baseline — an image block in a HumanMessage: does vision work at all through the
     governed wrapper?
  B. THE risk — the exact `view`-tool shape: text+image blocks as ToolMessage content in
     a tool-call round trip. Does the model actually SEE the image (answer names the
     color), or does the translation drop/garble it?
  C. Structured output — a forced tool call with a VisualCritique-like pydantic schema
     through `bind_tools` (what langchain's ToolStrategy does under the hood), including
     the wrapper's provider_compatible_tool_schema rewriting.

Also records: usage metadata (are cached/reasoning token details present WITHOUT the
OpenRouter `usage.include` extra_body? — expected missing, motivating the GatewayConfig
passthrough) and the truthful answering-model attribution.

Run (billed — a few small vision calls):
    set -a; source ../damascus/.env; set +a
    uv run python scripts/p32_probe_responses_api_images.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field, SecretStr

from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import OpenRouterAgentModelProvider

MODEL_ID = os.environ.get("P32_PROBE_MODEL", "openai/gpt-5.6-terra")


def _probe_png_b64() -> str:
    """A 512x512 solid pure-red PNG — big enough for vision-provider floors, and with an
    unambiguous ground truth the model can only know by actually seeing it."""
    from PIL import Image

    img = Image.new("RGB", (512, 512), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_block(data_b64: str) -> dict:
    # EXACTLY the design runtime's shape — lumen_agent/tools/view.py:97-108.
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": "image/png",
        "data": data_b64,
    }


class ProbeCritique(BaseModel):
    """VisualCritique-alike: enough shape to exercise schema rewriting + parse-back."""

    verdict: str = Field(description="approve or revise")
    dominant_color: str = Field(description="the single dominant color in the image")
    issues: list[str] = Field(default_factory=list)


def _summarize(tag: str, response: AIMessage) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    details = usage.get("input_token_details") or {}
    meta = response.response_metadata or {}
    return {
        "probe": tag,
        "answering_model": meta.get("clue_answering_model") or meta.get("model_name"),
        "cost_cents": meta.get("clue_cost_cents"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": details.get("cache_read"),
        "tool_calls": [call["name"] for call in (response.tool_calls or [])],
    }


async def main() -> int:
    key = os.environ.get("CLUE_OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("NO KEY: source a workspace .env with CLUE_OPENROUTER_API_KEY first")
        return 2

    provider = OpenRouterAgentModelProvider(GatewayConfig(timeout_s=120.0), SecretStr(key))
    model = provider.build(
        model_id=MODEL_ID,
        timeout_s=110.0,
        max_retries=1,
        max_output_tokens=600,
        temperature=0.0,
    )
    png = _probe_png_b64()
    results: list[dict] = []
    verdicts: dict[str, str] = {}

    # --- A. baseline: image block in a HumanMessage --------------------------------
    a = await model.ainvoke(
        [
            SystemMessage(content="Answer in one word."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "What single color fills this image?"},
                    _image_block(png),
                ]
            ),
        ]
    )
    a_text = a.text() if callable(getattr(a, "text", None)) else str(a.content)
    verdicts["A_human_message_image"] = (
        "PASS" if "red" in a_text.lower() else f"FAIL (answer: {a_text[:120]!r})"
    )
    results.append(_summarize("A", a))

    # --- B. the risk: view-tool shape — text+image blocks as ToolMessage content ----
    view_tool_schema = {
        "name": "view",
        "description": "Render the current design preview.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    bound = model.bind_tools([view_tool_schema])
    b = await bound.ainvoke(
        [
            SystemMessage(
                content="You inspect designs. When the view tool returns a preview, "
                "answer using ONLY what the preview shows."
            ),
            HumanMessage(content="Call view, then tell me in one word the artboard's color."),
            AIMessage(
                content="",
                tool_calls=[{"name": "view", "args": {}, "id": "call_probe_view_1"}],
            ),
            ToolMessage(
                tool_call_id="call_probe_view_1",
                content=[
                    {"type": "text", "text": "preview target=preview round=1 (image follows)"},
                    _image_block(png),
                ],
            ),
        ]
    )
    b_text = b.text() if callable(getattr(b, "text", None)) else str(b.content)
    verdicts["B_tool_message_image (THE risk)"] = (
        "PASS" if "red" in b_text.lower() else f"FAIL (answer: {b_text[:200]!r})"
    )
    results.append(_summarize("B", b))

    # --- C. forced structured output through bind_tools (ToolStrategy mechanics) ----
    critique_bound = model.bind_tools([ProbeCritique], tool_choice="required")
    c = await critique_bound.ainvoke(
        [
            SystemMessage(content="Critique the design preview by calling ProbeCritique."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "The preview to critique:"},
                    _image_block(png),
                ]
            ),
        ]
    )
    try:
        call = (c.tool_calls or [])[0]
        critique = ProbeCritique.model_validate(call["args"])
        verdicts["C_structured_output"] = (
            "PASS"
            if "red" in critique.dominant_color.lower()
            else f"PARTIAL (parsed, but color={critique.dominant_color!r})"
        )
    except Exception as error:  # noqa: BLE001 - a probe reports, never raises
        verdicts["C_structured_output"] = f"FAIL ({type(error).__name__}: {error})"
    results.append(_summarize("C", c))

    print(json.dumps({"model": MODEL_ID, "verdicts": verdicts, "telemetry": results}, indent=2))
    return 0 if all(v.startswith("PASS") for v in verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
