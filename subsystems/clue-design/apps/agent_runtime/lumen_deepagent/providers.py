from __future__ import annotations

import json
import re
from typing import Any

from .loop import DslAuthor, VisualReviewer
from .prompts import DSL_AUTHOR_SYSTEM_PROMPT, VISUAL_REVIEWER_SYSTEM_PROMPT
from .schemas import AuthoringBlockRequest, VisualCritique


class LangChainDslAuthor(DslAuthor):
    def __init__(self, model: str) -> None:
        self.model = init_model(model)

    def write_block(self, request: AuthoringBlockRequest) -> str:
        response = self.model.invoke(
            [
                {"role": "system", "content": DSL_AUTHOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Write one Lumen DSL block for this authoring request. "
                        "Return DSL only.\n\n"
                        f"{json.dumps(request.model_dump(mode='json'), indent=2)}"
                    ),
                },
            ]
        )
        return extract_dsl(response_content(response))


class LangChainVisualReviewer(VisualReviewer):
    def __init__(self, model: str) -> None:
        raw_model = init_model(model)
        self.structured_model = try_structured_model(raw_model, VisualCritique)
        self.raw_model = raw_model

    def review(
        self,
        *,
        user_request: str,
        scene_summary: dict,
        export_summary: dict,
        knowledge: list[dict],
        previous_feedback: list[dict],
        preview_payload: dict,
    ) -> VisualCritique:
        payload = {
            "user_request": user_request,
            "scene_summary": scene_summary,
            "export_summary": export_summary,
            "preview_payload": compact_preview_payload(preview_payload),
            "knowledge": knowledge,
            "previous_feedback": previous_feedback,
            "required_schema": VisualCritique.model_json_schema(),
        }
        user_content = [
            {
                "type": "text",
                "text": (
                    "Review this Lumen preview. Return a VisualCritique JSON "
                    "object. Reject visible clipping, wrong dimensions, weak "
                    "hierarchy, unreadable text, missing request requirements, "
                    "or poor brand fit.\n\n"
                    f"{json.dumps(payload, indent=2)}"
                ),
            },
            *preview_image_blocks(preview_payload),
        ]
        messages = [
            {"role": "system", "content": VISUAL_REVIEWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        response = self.structured_model.invoke(messages)
        if isinstance(response, VisualCritique):
            return response
        if isinstance(response, dict):
            return VisualCritique.model_validate(response)
        return parse_visual_critique(response_content(response))


def create_provider_quality_loop(prompt: str, config):
    from .loop import LumenQualityLoop
    from .tools import LumenDesignTools

    tools = LumenDesignTools(config, prompt)
    return (
        LumenQualityLoop(
            tools=tools,
            author=LangChainDslAuthor(config.model),
            reviewer=LangChainVisualReviewer(config.model),
        ),
        tools,
    )


def init_model(model: str):
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as error:
        raise RuntimeError(
            "LangChain model dependencies are missing. Install apps/api/requirements.txt "
            "or add langchain and langchain-anthropic to the active environment."
        ) from error
    return init_chat_model(model)


def try_structured_model(model: Any, schema: type[VisualCritique]):
    try:
        return model.with_structured_output(schema)
    except Exception:
        return model


def response_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def compact_preview_payload(preview_payload: dict) -> dict:
    compact = dict(preview_payload)
    artifacts = []
    for artifact in preview_payload.get("artifacts", []):
        item = {
            key: value
            for key, value in artifact.items()
            if key not in {"base64", "svg_text"}
        }
        if "svg_text" in artifact:
            item["svg_text"] = artifact["svg_text"][:20000]
            item["truncated_for_prompt"] = len(artifact["svg_text"]) > 20000
        if "base64" in artifact:
            item["base64_omitted_from_text_prompt"] = True
        artifacts.append(item)
    compact["artifacts"] = artifacts
    return compact


def preview_image_blocks(preview_payload: dict) -> list[dict]:
    blocks: list[dict] = []
    for artifact in preview_payload.get("artifacts", []):
        if artifact.get("format") != "png" or not artifact.get("base64"):
            continue
        blocks.append(
            {
                "type": "image",
                "source_type": "base64",
                "mime_type": artifact.get("mime_type") or "image/png",
                "data": artifact["base64"],
            }
        )
    return blocks


def extract_dsl(text: str) -> str:
    fenced = re.search(r"```[^\n\r]*[\n\r]+(.*?)```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def parse_visual_critique(text: str) -> VisualCritique:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    return VisualCritique.model_validate_json(candidate.strip())
