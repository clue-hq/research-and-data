"""Optional vision-assist seam for the brand-guidelines PDF path (§3).

`PdfVisionAssist` is a protocol the extractor may consult to refine the
deterministic extraction: reclassify pages, add rules, name unnamed palette
colors, hint logo variants, and harvest tone/imagery notes. Every field it
returns is re-validated deterministically by the caller (`capture/pdf.py`);
vision may ADD but may never mutate an extracted hex value.

`NullPdfVision` (the default, used in every test) returns None.
`OpenRouterPdfVision` mirrors `lumen_ingestion.assist`'s pattern: lazy httpx
import, env-driven config, strict JSON response, one retry then None. It never
touches the network in tests and is never constructed by the extractor unless
explicitly passed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from py_lumen_config import settings

DEFAULT_TIMEOUT_S = 60.0


@dataclass
class PageForVision:
    page_number: int
    kind_guess: str
    png_b64: str  # 1x raster, base64 (JPEG-quality-ish scale)
    text: str


@dataclass
class PdfVisionResult:
    page_kinds: dict[int, str] = field(default_factory=dict)
    extra_rules: list[dict] = field(default_factory=list)  # {kind, text, numeric_value?}
    logo_variant_hints: dict[str, dict] = field(default_factory=dict)  # asset_id -> {color_mode, usage}
    color_names: dict[str, str] = field(default_factory=dict)  # hex -> name
    tone: list[str] = field(default_factory=list)
    imagery_notes: list[str] = field(default_factory=list)


@runtime_checkable
class PdfVisionAssist(Protocol):
    def review(self, pages: list[PageForVision]) -> PdfVisionResult | None: ...


class NullPdfVision:
    """Deterministic no-op. The default everywhere; tests use this."""

    def review(self, pages: list[PageForVision]) -> PdfVisionResult | None:
        return None


class OpenRouterPdfVision:
    """LLM vision assist over OpenRouter. Enabled only when
    LUMEN_INGESTION_VISION=1. Never call the network in tests."""

    def __init__(self) -> None:
        self.enabled = settings.lumen_ingestion_vision
        self.model = settings.lumen_ingestion_vision_model
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key
        self.diagnostics: list[dict] = []

    def review(self, pages: list[PageForVision]) -> PdfVisionResult | None:
        if not self.enabled or not self.api_key:
            self._unavailable()
            return None
        payload = self._invoke(pages)
        if payload is None:
            self._unavailable()
            return None
        return PdfVisionResult(
            page_kinds={int(k): str(v) for k, v in (payload.get("page_kinds") or {}).items()},
            extra_rules=[dict(r) for r in (payload.get("extra_rules") or [])],
            logo_variant_hints={
                str(k): dict(v) for k, v in (payload.get("logo_variant_hints") or {}).items()
            },
            color_names={str(k): str(v) for k, v in (payload.get("color_names") or {}).items()},
            tone=[str(v) for v in (payload.get("tone") or [])],
            imagery_notes=[str(v) for v in (payload.get("imagery_notes") or [])],
        )

    def _unavailable(self) -> None:
        self.diagnostics.append(
            {
                "code": "LUMI0604",
                "severity": "warning",
                "message": "vision unavailable — deterministic extraction only",
            }
        )

    def _invoke(self, pages: list[PageForVision]) -> dict | None:
        from clue_spend import ProviderHalted
        from lumen_api import spend  # lazy: only the real network path needs it

        # OpenRouter/OpenAI multimodal message uses "text"/"image_url" parts.
        parts: list[dict] = [{"type": "text", "text": _USER_PREAMBLE}]
        for page in pages:
            parts.append(
                {
                    "type": "text",
                    "text": f"page {page.page_number} (kind_guess={page.kind_guess}):\n{page.text[:1500]}",
                }
            )
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{page.png_b64}"},
                }
            )

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": parts},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "pdf_vision", "strict": True, "schema": _RESPONSE_SCHEMA},
            },
        }
        # Two attempts, now the provider caller's, with the money row and the raw body recorded
        # per attempt. ``ProviderHalted`` propagates so an out-of-credit key fails the job loud.
        try:
            response = spend.openrouter_call(
                operation="design.ingestion.vision",
                body=body,
                label=f"vision:{len(pages)} pages",
                timeout_s=DEFAULT_TIMEOUT_S,
                api_key=self.api_key,
                base_url=self.base_url,
                max_attempts=2,
            )
            if response.status >= 400:
                return None
            message = json.loads(response.body)["choices"][0]["message"]["content"]
            return json.loads(message)
        except ProviderHalted:
            raise
        except Exception:
            return None


_SYSTEM_PROMPT = (
    "You review rendered pages of a brand-guidelines PDF and refine a "
    "deterministic extraction. You may reclassify pages, add usage rules, name "
    "unnamed palette colors, hint logo variants, and note tone/imagery. Return "
    "valid JSON matching the schema. Never invent hex color values — the "
    "deterministic pass owns those; you only supply names for colors it found."
)

_USER_PREAMBLE = (
    "Here are the pages of a brand guidelines PDF. For each, the deterministic "
    "page kind guess and its extracted text precede the rendered image."
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_kinds": {"type": "object"},
        "extra_rules": {"type": "array", "items": {"type": "object"}},
        "logo_variant_hints": {"type": "object"},
        "color_names": {"type": "object"},
        "tone": {"type": "array", "items": {"type": "string"}},
        "imagery_notes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
