"""Optional LLM role-assist seam (§5).

`RoleAssist` is a protocol the normalizer may consult to refine the deterministic
role assignment. `NullRoleAssist` (the default, used in all tests) returns None.
`OpenRouterRoleAssist` mirrors `lumen_api.image_provider`'s pattern: lazy httpx
import, env-driven config, strict JSON response. It never touches the network in
tests and is never constructed by the normalizer unless explicitly passed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from py_lumen_config import settings

DEFAULT_TIMEOUT_S = 30.0


@dataclass
class AssistDraft:
    clusters: list[dict]                 # [{hex, weight, hints, name}]
    color_roles: dict[str, str]          # deterministic token -> hex
    type_anchors: dict[str, object]
    narrative: dict
    rules: list[str]


@dataclass
class AssistResult:
    color_roles: dict[str, str] = field(default_factory=dict)
    heading_family: str | None = None
    body_family: str | None = None
    description: str | None = None
    tagline: str | None = None
    values: list[str] = field(default_factory=list)
    tone: list[str] = field(default_factory=list)
    dark_overrides: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class RoleAssist(Protocol):
    def refine(self, draft: AssistDraft) -> AssistResult | None: ...


class NullRoleAssist:
    """Deterministic no-op. The default everywhere; tests use this."""

    def refine(self, draft: AssistDraft) -> AssistResult | None:
        return None


class OpenRouterRoleAssist:
    """LLM-backed refinement over OpenRouter. Enabled only when
    LUMEN_INGESTION_ASSIST=1. Never call the network in tests."""

    def __init__(self) -> None:
        self.enabled = settings.lumen_ingestion_assist
        self.model = settings.lumen_ingestion_assist_model
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key
        self.diagnostics: list[dict] = []

    def refine(self, draft: AssistDraft) -> AssistResult | None:
        if not self.enabled or not self.api_key:
            self.diagnostics.append(
                {"code": "LUMI0301", "severity": "warning", "message": "assist unavailable — deterministic fallback"}
            )
            return None
        payload = self._invoke(draft)
        if payload is None:
            self.diagnostics.append(
                {"code": "LUMI0301", "severity": "warning", "message": "assist unavailable — deterministic fallback"}
            )
            return None
        return AssistResult(
            color_roles={str(k): str(v) for k, v in (payload.get("color_roles") or {}).items()},
            heading_family=payload.get("heading_family"),
            body_family=payload.get("body_family"),
            description=payload.get("description"),
            tagline=payload.get("tagline"),
            values=[str(v) for v in (payload.get("values") or [])],
            tone=[str(v) for v in (payload.get("tone") or [])],
            dark_overrides={str(k): str(v) for k, v in (payload.get("dark_overrides") or {}).items()},
        )

    def _invoke(self, draft: AssistDraft) -> dict | None:
        from clue_spend import ProviderHalted
        from lumen_api import spend  # lazy: only the real network path needs it

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_draft_payload(draft))},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "role_assist", "strict": True, "schema": _RESPONSE_SCHEMA},
            },
        }
        # The two attempts are the provider caller's now (same count, same swallow-on-failure
        # contract). A ``ProviderHalted`` propagates: an out-of-credit key must fail the job, not
        # quietly drop the lane to its deterministic fallback.
        try:
            response = spend.openrouter_call(
                operation="design.ingestion.assist",
                body=body,
                label="assist:role refinement",
                timeout_s=DEFAULT_TIMEOUT_S,
                api_key=self.api_key,
                base_url=self.base_url,
                max_attempts=2,
            )
            if response.status >= 400:
                return None
            content = json.loads(response.body)["choices"][0]["message"]["content"]
            return json.loads(content)
        except ProviderHalted:
            raise
        except Exception:
            return None


def _draft_payload(draft: AssistDraft) -> dict:
    return {
        "clusters": draft.clusters,
        "deterministic_roles": draft.color_roles,
        "type_anchors": draft.type_anchors,
        "narrative": draft.narrative,
        "rules": draft.rules,
    }


_SYSTEM_PROMPT = (
    "You refine a deterministic brand color/type role assignment. Only override "
    "where evidence clearly supports a better choice. Return valid JSON matching "
    "the schema. Colors are #RRGGBB. Do not invent families not present in the "
    "evidence."
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "color_roles": {"type": "object"},
        "heading_family": {"type": ["string", "null"]},
        "body_family": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "tagline": {"type": ["string", "null"]},
        "values": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "array", "items": {"type": "string"}},
        "dark_overrides": {"type": "object"},
    },
    "additionalProperties": False,
}
