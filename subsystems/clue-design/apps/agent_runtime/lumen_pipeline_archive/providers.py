from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

from .loop import AgentDirector, DslAuthor, VisualReviewer
from .prompts import (
    DSL_AUTHOR_SYSTEM_PROMPT,
    SHARED_SURFACE_CONTRACT,
    VISUAL_REVIEWER_SYSTEM_PROMPT,
)
from .schemas import AgentDirectorDecision, AuthoringBlockRequest, VisualCritique


DIRECTOR_SYSTEM_PROMPT = f"""You are the Lumen agentic design director.

You receive a curated situation report for the CURRENT iteration: user request,
editor conversation, a compact scene summary, the scene subtree for the nodes
named by the top diagnostics, errors-first ranked diagnostics, the latest visual
critique, a short history of what was already tried and rejected, and a preview
summary. The latest rendered preview is attached as an image. This is a fresh
snapshot, not an accumulating transcript — judge the situation as it is now.

Your job is to choose the next action mode. Use your judgment. Do not blindly
follow a static diagnostic classifier. Errors outrank warnings. If the issue is
composition, visual balance, parent/artboard overflow, or repeated failed local
patches (see attempt_history), choose a structural rewrite mode instead of a tiny
targeted patch.

BRAND-ASSET THUMBNAILS: when a `brand_asset_contact_sheet` is attached, the images
after the preview ARE the kit's assets (logos first, then imagery), one per entry in
list order. Choose imagery and logo placements by LOOKING at them — the subject, the
colors, any baked-in text, and their contrast against the CURRENT draft — not by the
metadata alone. The label/usage_note is the index; the pixels are the judgment (e.g. a
dark lockup will not read on a dark draft; a dashboard screenshot and a clinician photo
serve different briefs).

SEEDED CONTINUATION TURNS: when the report says `seeded_from_initial_scene: true`,
the scene IS the user's live document — you are continuing it, not creating one.
`new_artifact`, `full_page_rewrite`, and `replace_artboard_subtree` are unavailable
(the loop coerces them to `targeted_patch`). Choose `targeted_patch` or
`layout_cluster_rewrite`. Pre-existing quality issues OUTSIDE the requested edit
are advisory — do not block or redesign for them unless the user asked.

{SHARED_SURFACE_CONTRACT}

WRITING instructions_to_author: state the GOAL and the SUBJECT, then let the
contract govern breadth. Never write scoping language that contradicts it — no
"only node X", no "keep every other node byte-identical", no forbidding new
elements. Satisfying a request routinely means INSERTING new elements placed
relative to the subject (contract rule 2: for content "inside" a leaf shape,
instruct a reconcile of the subject's PARENT with the new element overlaid) and
proportionally adjusting implicated elements (rule 3). If your previous
instruction produced repeated compile failures, change the APPROACH you
instruct, not just the wording.

Return only a structured AgentDirectorDecision.
"""


class LangChainAgentDirector(AgentDirector):
    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning: str | None = None,
    ) -> None:
        raw_model = init_model(
            model, base_url=base_url, api_key=api_key, reasoning=reasoning
        )
        self.structured_model = try_structured_model(raw_model, AgentDirectorDecision)
        self.raw_model = raw_model

    def decide(self, *, full_context: dict) -> AgentDirectorDecision:
        user_content = [
            {
                "type": "text",
                "text": (
                    "Choose the next Lumen design action mode from this curated "
                    "situation report. The latest preview is attached FIRST as an "
                    "image, followed by the brand-asset thumbnails listed in "
                    "`brand_asset_contact_sheet`, in that exact order — so you can "
                    "match each attached thumbnail to its label/usage_note via the "
                    "JSON. Return AgentDirectorDecision JSON only.\n\n"
                    f"{json.dumps(full_context, indent=2)}"
                ),
            },
            *image_blocks_from_context(full_context),
        ]
        response = self.structured_model.invoke(
            [
                {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        if isinstance(response, AgentDirectorDecision):
            return response
        if isinstance(response, dict):
            return AgentDirectorDecision.model_validate(response)
        return parse_director_decision(response_content(response))


class LangChainDslAuthor(DslAuthor):
    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning: str | None = None,
    ) -> None:
        self.model = init_model(
            model, base_url=base_url, api_key=api_key, reasoning=reasoning
        )

    def write_block(self, request: AuthoringBlockRequest) -> str:
        payload = request.model_dump(mode="json")
        user_content = [
            {
                "type": "text",
                "text": (
                    "Write one Lumen DSL block for this authoring request. "
                    "Return DSL only. You are receiving the complete context; "
                    "use the director_decision to decide whether this should be "
                    "a new artifact, structural rewrite, layout-cluster rewrite, "
                    "or targeted patch.\n\n"
                    f"{json.dumps(payload, indent=2)}"
                ),
            },
            # The AUTHOR keeps the contact sheet's TEXT (labels + asset_ids it
            # references in DSL) but not its image payload — the sheet's pixels are
            # the DIRECTOR's judgment input (Slice 2 design), and the author call is
            # the longest-context one in the loop (the K1 blow-up lesson).
            *image_blocks_from_context(
                request.full_context, include_contact_sheet=False
            ),
        ]
        response = self.model.invoke(
            [
                {"role": "system", "content": DSL_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        return extract_dsl(response_content(response))


class LangChainVisualReviewer(VisualReviewer):
    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning: str | None = None,
    ) -> None:
        raw_model = init_model(
            model, base_url=base_url, api_key=api_key, reasoning=reasoning
        )
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
        full_context: dict,
    ) -> VisualCritique:
        # The real preview image is attached below as an image block. In the JSON
        # text we send the COMPACT payload (base64 stripped, SVG capped) so the
        # token-heavy raw artifacts are never duplicated into the prompt text.
        payload = {
            "user_request": user_request,
            "scene_summary": scene_summary,
            "export_summary": export_summary,
            "preview_payload": compact_preview_payload(preview_payload),
            "knowledge": knowledge,
            # `previous_feedback` is intentionally NOT dumped raw — it accumulates
            # every iteration. The curated `full_context` already carries the
            # windowed `attempt_history` and `latest_critique`.
            "full_context": full_context,
            "required_schema": VisualCritique.model_json_schema(),
        }
        user_content = [
            {
                "type": "text",
                "text": (
                    "Review this Lumen preview. Return a VisualCritique JSON "
                    "object. Reject visible clipping, wrong dimensions, weak "
                    "hierarchy, unreadable text, missing request requirements, "
                    "or poor brand fit. After the design preview, the SOURCE "
                    "thumbnails of any placed brand assets are attached in "
                    "`placed_brand_asset_previews` order — verify each placement "
                    "against its source: correct asset, a variant suited to the "
                    "background it sits on, no distortion/stretch, legible at its "
                    "placed size. A mismatch is a blocker targeting the placing "
                    "node.\n\n"
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


def create_provider_quality_loop(
    prompt: str, config, initial_scene: dict | None = None, event_sink=None
):
    from .loop import LumenQualityLoop
    from .tools import LumenDesignTools

    tools = LumenDesignTools(
        config, prompt, initial_scene=initial_scene, event_sink=event_sink
    )
    creds = {
        "base_url": getattr(config, "agent_base_url", None),
        "api_key": getattr(config, "agent_api_key", None),
        "reasoning": getattr(config, "agent_reasoning", None),
    }
    return (
        LumenQualityLoop(
            tools=tools,
            author=LangChainDslAuthor(config.model, **creds),
            reviewer=LangChainVisualReviewer(config.model, **creds),
            director=LangChainAgentDirector(config.model, **creds),
        ),
        tools,
    )


def init_model(
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning: str | None = None,
):
    """Build a deep-agent LLM bound to the OpenRouter gateway.

    OpenRouter is the SOLE gateway for every LLM call — there is no native-provider
    fallback. Callers must supply the OpenRouter `base_url` + `api_key`, and `model`
    must be an "openai:<openrouter-model-id>" string so LangChain selects the
    OpenAI-compatible client. Any other shape is a misconfiguration and raises here,
    before a request goes out, rather than failing later as an opaque transport
    error (e.g. an Anthropic client aimed at the OpenRouter base URL that 404s).

    `reasoning` ("low" | "medium" | "high") rides OpenRouter's unified
    `reasoning: {effort}` request field — the gateway translates it for whatever
    provider serves the model, so it is one mechanism for every model id, never a
    per-vendor special case. None → no reasoning field on the request (provider
    default: no extended thinking).
    """
    if not (base_url and api_key):
        raise ValueError(
            "The deep-agent routes every LLM call through OpenRouter — set both "
            "LUMEN_AGENT_BASE_URL and LUMEN_AGENT_API_KEY. There is no native "
            "provider fallback."
        )
    if not model.startswith("openai:"):
        raise ValueError(
            "LUMEN_AGENT_MODEL must be an 'openai:<openrouter-model-id>' value so "
            f"LangChain selects the OpenAI-compatible client. Got {model!r}. Prefix "
            "it with 'openai:' — e.g. 'openai:anthropic/claude-opus-4.8'. A bare "
            "'anthropic:' prefix builds the Anthropic client against the OpenRouter "
            "base URL and 404s."
        )
    if reasoning is not None and reasoning not in {"low", "medium", "high"}:
        raise ValueError(
            "LUMEN_AGENT_REASONING must be one of low|medium|high (or unset for "
            f"no reasoning field); got {reasoning!r}"
        )
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as error:
        raise RuntimeError(
            "LangChain model dependencies are missing. Install apps/api/requirements.txt "
            "or add langchain and langchain-openai to the active environment."
        ) from error
    kwargs: dict = {"base_url": base_url, "api_key": api_key}
    if reasoning is not None:
        # OpenAI-compatible clients pass unknown top-level request fields via
        # extra_body; OpenRouter reads `reasoning` from the request body.
        kwargs["extra_body"] = {"reasoning": {"effort": reasoning}}
    return init_chat_model(model, **kwargs)


# Slice 2 D4: cache of the multimodal-capability probe, keyed by (base_url, model id).
# Both outcomes are cached (passed / raised) so repeat turns in one process never
# re-hit the network — the model is fixed for the life of a run.
_IMAGE_INPUT_SUPPORT_CACHE: dict[tuple[str, str], bool] = {}


def _openrouter_model_input_modalities(model_entry: dict) -> list[str] | None:
    """Extract a model's input modalities from an OpenRouter `/models` entry,
    handling BOTH observed shapes: `architecture.input_modalities` (a list) and
    `architecture.modality` (a string like `text+image->text` or `text->text`).
    Returns None when neither is present (the caller treats that as unknown)."""
    architecture = model_entry.get("architecture") or {}
    modalities = architecture.get("input_modalities")
    if isinstance(modalities, list):
        return [str(m).lower() for m in modalities]
    modality = architecture.get("modality")
    if isinstance(modality, str) and modality:
        # `text+image+file->text` — the INPUT side is everything before `->`.
        input_side = modality.split("->", 1)[0]
        return [part.strip().lower() for part in input_side.split("+") if part.strip()]
    return None


def assert_model_supports_image_input(
    model: str, *, base_url: str, api_key: str
) -> None:
    """Slice 2 D4: fail LOUDLY, BEFORE a run starts, if LUMEN_AGENT_MODEL is a
    text-only model. The loop is structurally mandatory-multimodal (the Director and
    visual reviewer attach images every turn); a text-only model instead authors,
    then dies mid-turn at the reviewer with `404 No endpoints found that support
    image input` — burning the paid authoring call. This probe moves that failure to
    startup.

    Only a POSITIVE "text-only" finding raises. A model missing from the list, a
    non-OpenRouter gateway, or any network error must NEVER brick a run — those log a
    warning and return (unknown ≠ text-only)."""
    model_id = model[len("openai:") :] if model.startswith("openai:") else model
    cache_key = (base_url, model_id)
    if cache_key in _IMAGE_INPUT_SUPPORT_CACHE:
        if not _IMAGE_INPUT_SUPPORT_CACHE[cache_key]:
            _raise_text_only(model)
        return

    import httpx

    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json().get("data") or []
    except Exception as error:  # network down, non-OpenRouter gateway, bad JSON.
        logging.getLogger(__name__).warning(
            "Could not verify image-input support for model %r via %s/models (%s); "
            "proceeding without the check — an unknown model must not brick a run.",
            model,
            base_url,
            error,
        )
        return

    entry = next((m for m in data if m.get("id") == model_id), None)
    if entry is None:
        logging.getLogger(__name__).warning(
            "Model %r was not found in OpenRouter's model list; skipping the "
            "image-input check (unknown, not text-only).",
            model_id,
        )
        return

    modalities = _openrouter_model_input_modalities(entry)
    if modalities is None:
        # Entry found but carries neither modality shape → UNKNOWN. Do not cache:
        # caching False here would make the model pass on the first call and then
        # brick every later call from the poisoned cache (unknown ≠ text-only).
        logging.getLogger(__name__).warning(
            "Model %r has no recognizable modality metadata in OpenRouter's list; "
            "skipping the image-input check (unknown, not text-only).",
            model_id,
        )
        return
    supports_image = "image" in modalities
    _IMAGE_INPUT_SUPPORT_CACHE[cache_key] = supports_image
    if not supports_image:
        _raise_text_only(model)


def _raise_text_only(model: str) -> None:
    raise ValueError(
        f"LUMEN_AGENT_MODEL={model!r} is a TEXT-ONLY model, but the Lumen deep-agent "
        "loop is mandatory-multimodal: the Director and the visual reviewer attach "
        "images on every turn. Configured as-is, the run would author and then die "
        "mid-turn at the reviewer with `404 No endpoints found that support image "
        "input`, wasting the paid authoring call. Set LUMEN_AGENT_MODEL to a model "
        "whose OpenRouter input modalities include `image` (e.g. a vision-capable "
        "Claude/GPT/Gemini id)."
    )


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


_PREVIEW_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _mime_from_path(path: str) -> str:
    """Infer the vision mime type from a preview path's suffix (default PNG)."""
    return _PREVIEW_MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "image/png")


def _asset_preview_block(preview_path: str) -> dict | None:
    """Slice 2: read a kit-asset preview PATH into a base64 vision block at the model
    boundary. Returns None (skip, do not raise) when the file is missing/unreadable —
    the context dict only carries paths, so a stale path must never break the call."""
    if not preview_path:
        return None
    try:
        data = base64.b64encode(Path(preview_path).read_bytes()).decode("ascii")
    except OSError:
        return None
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": _mime_from_path(preview_path),
        "data": data,
    }


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
    # Slice 2 D3: after the rendered-preview blocks, append the SOURCE thumbnails of
    # the kit assets the scene placed (paths from `placed_brand_asset_previews`), so
    # the critic verifies each placement against its source. Read at the boundary; a
    # missing file is skipped, never fatal.
    for entry in preview_payload.get("placed_brand_asset_previews", []) or []:
        block = _asset_preview_block(entry.get("preview_path"))
        if block is not None:
            blocks.append(block)
    return blocks


def image_blocks_from_context(
    full_context: dict, *, include_contact_sheet: bool = True
) -> list[dict]:
    """Read the LATEST preview PNG pointed to by the curated context and return it
    as a single image block. The base64 is produced here, at the model boundary,
    and never stored in the context dict — so it is sent exactly once per call and
    cannot pile up across iterations the way the old `preview_activity` list did.

    `include_contact_sheet=False` is the AUTHOR's setting: it keeps the preview
    block but skips the brand-asset thumbnails — the sheet's pixels are the
    Director's judgment input, and the author call is the loop's longest-context
    one (Slice 2 design; the sheet's TEXT still reaches the author via the JSON).
    """
    blocks: list[dict] = []
    summary = (full_context or {}).get("preview_summary") or {}
    path = summary.get("png_path")
    if path:
        try:
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:
            data = None
        if data is not None:
            blocks.append(
                {
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": "image/png",
                    "data": data,
                }
            )
    # Slice 2 D2: after the preview, append one block per brand-asset contact-sheet
    # entry, in the exact order the sheet lists them so the model can match blocks
    # to labels via the JSON it already receives. Director-only: the author calls
    # this with include_contact_sheet=False. Bytes are read from `preview_path` here
    # at the boundary; a missing file is skipped without raising.
    if include_contact_sheet:
        for entry in (full_context or {}).get("brand_asset_contact_sheet", []) or []:
            block = _asset_preview_block(entry.get("preview_path"))
            if block is not None:
                blocks.append(block)
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


def parse_director_decision(text: str) -> AgentDirectorDecision:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    return AgentDirectorDecision.model_validate_json(candidate.strip())
