"""Phase 2 of the imagery-quality eval set: the LLM JUDGE ceiling + DET combination.

The deterministic gates (``imagery_checks.score_scene``) catch the ugly, taste-free
failures; this judge looks at the rendered PNG against the SAME shared rubric
(``prompts.IMAGERY_RUBRIC`` — the one the in-loop visual reviewer uses, Step 9) and
sets the ceiling for the taste axes (composition reads, role choice, theme / cliché,
relevance, soft DPI, in-image text).

Two check families per the fixture-set spec:
- **DET** (deterministic gates) — authoritative on the hard, taste-free axes; a gate
  failure caps that axis at 1 and blocks acceptance.
- **JUDGE** (the LLM ceiling) — sets the score within what the gates allow.

Final per-axis score = ``min(DET cap, JUDGE)``. Everything here is pure functions with
an injectable ``model`` so it is unit-testable offline with a fake (no network).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

from .imagery_checks import score_scene
from .prompts import IMAGERY_RUBRIC

# Rubric axes, in IMAGERY_RUBRIC order. Each is scored 0–3.
RUBRIC_AXES = (
    "relevance",
    "placeholder_real",
    "aspect_fit",
    "placement",
    "legibility",
    "resolution_dpi",
    "no_in_image_text",
    "theme_coherence",
)

# Weights from the fixture-set spec scoring table.
AXIS_WEIGHTS: Dict[str, float] = {
    "relevance": 1.0,
    "placeholder_real": 1.0,
    "aspect_fit": 1.0,
    "placement": 1.0,
    "legibility": 1.2,
    "resolution_dpi": 0.8,
    "no_in_image_text": 0.8,
    "theme_coherence": 1.0,
}

# A hard DET gate failure on one of these axes is an automatic redo (caps it at 1).
HARD_GATE_AXES = {"aspect_fit", "placement", "legibility"}

# Which deterministic ``score_scene`` dimension caps each rubric axis (None = JUDGE-only).
DET_DIM_FOR_AXIS: Dict[str, Optional[str]] = {
    "relevance": "decision",
    "placeholder_real": "placeholder_real",
    "aspect_fit": "aspect_fit",
    "placement": "hero_count",
    "legibility": "legibility",
    "resolution_dpi": None,
    "no_in_image_text": None,
    "theme_coherence": None,
}

ACCEPT_MEAN = 2.3   # weighted-mean floor for "Ship"
TWEAK_MEAN = 2.0    # weighted-mean floor for "Tweak"


class ImageryJudgeVerdict(BaseModel):
    """The LLM judge's 0–3 score on each shared-rubric axis (the JUDGE ceiling)."""

    # No ge/le bounds on the axis ints: they emit JSON-schema minimum/maximum,
    # which the Anthropic structured-output path rejects with a 400 (same failure
    # class as the VisualCritique confidence fix, d8eb4e7). Clamp in a validator;
    # validators never surface in the emitted schema.
    relevance: int = Field(description="Axis 1 (0-3) — does the imagery earn its place for THIS brief; gratuitous/cliché = low.")
    placeholder_real: int = Field(description="Axis 2 (0-3) — a real credible picture, not a gray/solid placeholder.")
    aspect_fit: int = Field(description="Axis 3 (0-3) — fills the frame, no stretch, no letterbox dead bands, subject in-frame.")
    placement: int = Field(description="Axis 4 (0-3) — one hero, coherent role, aligned, clipped/rounded if intended, alt set.")
    legibility: int = Field(description="Axis 5 (0-3) — text over image scrimmed/own-surface with adequate contrast.")
    resolution_dpi: int = Field(description="Axis 6 (0-3) — sharp at rendered size, no upscale blur.")
    no_in_image_text: int = Field(description="Axis 7 (0-3) — no words/letters/logos baked into the image.")
    theme_coherence: int = Field(description="Axis 8 (0-3) — subject/style/palette on-brief and on-brand; one element dominates.")
    reasoning: str = Field(default="", description="One or two sentences explaining the lowest scores.")

    @field_validator(
        "relevance",
        "placeholder_real",
        "aspect_fit",
        "placement",
        "legibility",
        "resolution_dpi",
        "no_in_image_text",
        "theme_coherence",
    )
    @classmethod
    def _clamp_axis(cls, value: int) -> int:
        return min(3, max(0, value))


JUDGE_SYSTEM_PROMPT = (
    "You are the Lumen imagery JUDGE for an offline design-quality eval. You look at the "
    "RENDERED PNG of a finished design and score how well it used (or correctly declined) "
    "imagery, against a fixed rubric. Score each axis 0-3: 0 broken, 1 wrong but salvageable, "
    "2 acceptable (ships with minor tweaks), 3 deliberate and correct. Judge the PIXELS, hold a "
    "professional designer's bar, and do not inflate scores. If the design correctly used NO "
    "image for a data/type brief, score relevance 3 and the image-specific axes 3 (nothing to "
    "fault). Return an ImageryJudgeVerdict.\n\n" + IMAGERY_RUBRIC
)

PngInput = Union[str, Path, bytes, bytearray]


def _png_base64(png: PngInput) -> Optional[str]:
    if isinstance(png, (bytes, bytearray)):
        return base64.b64encode(bytes(png)).decode("ascii")
    try:
        return base64.b64encode(Path(png).read_bytes()).decode("ascii")
    except OSError:
        return None


def _scene_has_vectors(scene: Dict[str, Any]) -> bool:
    for node in (scene.get("nodes") or {}).values():
        kind = node.get("kind")
        if isinstance(kind, dict) and kind.get("kind") in ("vector", "svg"):
            return True
    return False


def _needs_judge(det: Dict[str, Any], scene: Dict[str, Any], expected: Optional[str]) -> bool:
    """A taste call is only worth a vision request when there is imagery to assess —
    a placed image, library vectors, or a brief that expected one. A correct
    image-free typographic design is scored deterministically on the decision axis."""
    return bool(det.get("image_count")) or _scene_has_vectors(scene) or expected in {"photo", "icon"}


def _build_judge_messages(b64: str, brief: Dict[str, Any], det: Dict[str, Any]) -> list:
    risks = brief.get("risks") or []
    det_notes = {
        dim: payload.get("notes")
        for dim, payload in (det.get("dimensions") or {}).items()
        if payload.get("notes")
    }
    user_text = (
        "Score this rendered design's imagery.\n"
        f"Expected decision for the brief: {brief.get('expected_decision')!r} "
        f"(role: {brief.get('role')!r}).\n"
        f"Known risks to check for: {json.dumps(risks)}.\n"
        f"Deterministic gate findings (already computed): {json.dumps(det_notes)}.\n"
        "Confirm or refine these on the pixels and score every axis 0-3."
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": b64},
            ],
        },
    ]


def _verdict_from_response(response: Any) -> Optional[ImageryJudgeVerdict]:
    if isinstance(response, ImageryJudgeVerdict):
        return response
    if isinstance(response, dict):
        try:
            return ImageryJudgeVerdict.model_validate(response)
        except Exception:
            return None
    # Fall back to parsing JSON out of a text response.
    from .llm import response_content

    text = response_content(response)
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return ImageryJudgeVerdict.model_validate(json.loads(text[start:end]))
    except Exception:
        return None


def _call_judge(
    b64: str,
    brief: Dict[str, Any],
    det: Dict[str, Any],
    *,
    model: Any = None,
    config: Any = None,
) -> Optional[ImageryJudgeVerdict]:
    if model is None:
        if config is None:
            return None
        from .llm import init_model, try_structured_model

        model = try_structured_model(
            init_model(
                config.model,
                base_url=getattr(config, "agent_base_url", None),
                api_key=getattr(config, "agent_api_key", None),
                reasoning=getattr(config, "agent_reasoning", None),
            ),
            ImageryJudgeVerdict,
        )
    response = model.invoke(_build_judge_messages(b64, brief, det))
    return _verdict_from_response(response)


def _det_cap(det_dims: Dict[str, Any], axis: str) -> Optional[int]:
    """The DET ceiling for an axis: 1 if its gate failed, else the DET sub-score
    (defaulting to 3). None when this axis has no deterministic signal."""
    dim_key = DET_DIM_FOR_AXIS.get(axis)
    if not dim_key or dim_key not in det_dims:
        return None
    dim = det_dims[dim_key]
    if dim.get("gate"):
        return 1
    score = dim.get("score")
    return int(score) if isinstance(score, (int, float)) else 3


def combine(det: Dict[str, Any], verdict: Optional[ImageryJudgeVerdict], brief: Dict[str, Any]) -> Dict[str, Any]:
    """Fold the deterministic gates and the LLM ceiling into a per-axis 0–3 score and
    the spec's accept / tier decision. ``final[axis] = min(DET cap, JUDGE)``."""
    det_dims = det.get("dimensions") or {}
    judge = verdict.model_dump() if verdict else {}

    per_axis: Dict[str, Dict[str, Any]] = {}
    for axis in RUBRIC_AXES:
        cap = _det_cap(det_dims, axis)
        judge_score = judge.get(axis)
        if judge_score is None and cap is None:
            continue  # axis not applicable (no judge, no DET signal)
        if judge_score is None:
            final = cap
        elif cap is None:
            final = int(judge_score)
        else:
            final = min(int(judge_score), cap)
        per_axis[axis] = {
            "final": final,
            "judge": None if judge_score is None else int(judge_score),
            "det_cap": cap,
            "weight": AXIS_WEIGHTS[axis],
            "hard_gate": axis in HARD_GATE_AXES,
        }

    gate_failed = bool(det.get("gate_failed"))
    scored = [a["final"] for a in per_axis.values()]
    total_w = sum(per_axis[a]["weight"] for a in per_axis) or 1.0
    weighted_mean = sum(per_axis[a]["final"] * per_axis[a]["weight"] for a in per_axis) / total_w

    all_pass = bool(scored) and all(s >= 2 for s in scored)
    accept = (not gate_failed) and all_pass and weighted_mean >= ACCEPT_MEAN
    if gate_failed or any(s <= 1 for s in scored):
        tier = "redo"
    elif accept:
        tier = "ship"
    elif all_pass and weighted_mean >= TWEAK_MEAN:
        tier = "tweak"
    else:
        tier = "redo"

    return {
        "per_axis": per_axis,
        "gate_failed": gate_failed,
        "weighted_mean": round(weighted_mean, 3),
        "accept": bool(accept),
        "tier": tier,
        "judge_ran": verdict is not None,
        "judge_reasoning": (verdict.reasoning if verdict else ""),
        "image_count": det.get("image_count", 0),
        "real_image_count": det.get("real_image_count", 0),
    }


def judge_imagery(
    scene: Dict[str, Any],
    png: Optional[PngInput],
    brief: Dict[str, Any],
    *,
    model: Any = None,
    config: Any = None,
) -> Dict[str, Any]:
    """Score one finished design's use of imagery: deterministic gates +
    (when imagery is present/expected) the LLM judge ceiling, combined per the rubric.

    Args:
        scene: the full compiled+preflighted scene dict (nodes/assets/pages).
        png: the rendered PNG (path or bytes) the judge looks at; may be None offline.
        brief: ``{id, expected_decision, role, risks, ...}`` from the fixture sidecar.
        model: an injectable LangChain-style model (already structured-output bound) —
            pass a fake in tests; if None and ``config`` is given, one is built.
        config: AgentRuntimeConfig used to build a model when ``model`` is None.

    Returns the ``scores.json`` body: per-axis finals, weighted mean, accept, tier.
    """
    expected = brief.get("expected_decision")
    det = score_scene(scene, expected_decision=expected)

    verdict: Optional[ImageryJudgeVerdict] = None
    if _needs_judge(det, scene, expected):
        b64 = _png_base64(png) if png is not None else None
        if b64 is not None:
            verdict = _call_judge(b64, brief, det, model=model, config=config)

    result = combine(det, verdict, brief)
    result["brief_id"] = brief.get("id")
    result["expected_decision"] = expected
    result["det"] = det
    return result
