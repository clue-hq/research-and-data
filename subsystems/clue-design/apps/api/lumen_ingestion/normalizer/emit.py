"""Kit JSON assembly (§4).

Assembles the full engine Brand Kit serde shape from the assigned roles, ramps,
type styles, number scales, and asset evidence, plus the evidence-pointer
`ingestion_report`. Provenance strings are compact evidence pointers. Missing
asset tokens emit LUMI0220 info diagnostics. Output ordering is deterministic
(dicts sorted by the caller when dumping; we never rely on insertion order for
correctness).
"""

from __future__ import annotations

import re

from ..colorspace import hex_alpha
from ..evidence import BrandEvidence, FontEvidence, LogoEvidence
from .required import (
    REQUIRED_ASSET_TOKENS,
    REQUIRED_COLOR_TOKENS,
)
from .roles import DarkColorway, LightRoles, RoleAssignment

_COLOR_ROLE_MAP = {
    "surface": "surface",
    "text": "text",
    "border": "border",
    "focus": "focus",
    "palette": "palette",
    "accent": "accent",
}

_PRINT_FONT_CAUTION = (
    "Font licensing was not verified at ingestion; confirm embeddability before print export."
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _color_role(path: str) -> str:
    head = path.split(".", 1)[0]
    if path.startswith("palette."):
        return "palette"
    if path.startswith("focus."):
        return "focus"
    return _COLOR_ROLE_MAP.get(head, "surface")


def _color_value(hex_value: str) -> dict:
    if hex_alpha(hex_value) < 1.0:
        return {"kind": "hex", "value": hex_value}
    return {"kind": "hex", "value": hex_value[:7]}


def _provenance(source: str, confidence: float) -> dict:
    return {"source": source[:160], "confidence": round(confidence, 4)}


def _mode_value(default: dict, modes: dict | None = None) -> dict:
    return {"default": default, "modes": modes or {}}


class KitBuilder:
    def __init__(
        self,
        evidence: BrandEvidence,
        *,
        brand_kit_id: str,
        version: int,
        name: str,
        created_at: str,
    ) -> None:
        self.evidence = evidence
        self.brand_kit_id = brand_kit_id
        self.version = version
        self.name = name
        self.created_at = created_at
        self.colors: dict[str, dict] = {}
        self.typography: dict[str, dict] = {}
        self.spacing: dict[str, dict] = {}
        self.radii: dict[str, dict] = {}
        self.stroke_widths: dict[str, dict] = {}
        self.opacity: dict[str, dict] = {}
        self.asset_tokens: dict[str, dict] = {}
        self.aliases: dict[str, dict] = {}
        self.fonts: dict[str, dict] = {}
        self.logos: dict[str, dict] = {}
        self.images: dict[str, dict] = {}
        self.diagnostics: list[dict] = []
        self.confidence_samples: list[float] = []
        self.role_assignments: list[dict] = []

    # --- colors ---------------------------------------------------------

    def add_color(
        self,
        path: str,
        assignment: RoleAssignment,
        dark_hex: str | None,
        *,
        record_report: bool = True,
    ) -> None:
        confidence = _confidence_for(assignment.basis)
        self.confidence_samples.append(confidence)
        modes = {"theme.dark": _color_value(dark_hex)} if dark_hex else {}
        self.colors[path] = {
            "value": _mode_value(_color_value(assignment.hex), modes),
            "role": _color_role(path),
            "description": None,
            "provenance": _provenance(assignment.provenance, confidence),
        }
        if record_report:
            self.role_assignments.append(
                {
                    "token": path,
                    "value": assignment.hex,
                    "basis": assignment.basis,
                    "pointer": assignment.provenance,
                }
            )

    def add_ramp(self, prefix: str, ramp: dict[str, str], basis_source: str) -> None:
        confidence = _confidence_for("derived")
        for stop, hex_value in ramp.items():
            path = f"{prefix}.{stop}"
            self.confidence_samples.append(confidence)
            self.colors[path] = {
                "value": _mode_value(_color_value(hex_value), {}),
                "role": "palette",
                "description": None,
                "provenance": _provenance(f"derived:ramp({path})", confidence),
            }

    def add_extra_color(self, cluster) -> str:
        slug = _slug(cluster.name or "extra")
        path = f"palette.extra.{slug}"
        confidence = _confidence_for("evidence")
        self.confidence_samples.append(confidence)
        self.colors[path] = {
            "value": _mode_value(_color_value(cluster.representative), {}),
            "role": "palette",
            "description": cluster.name,
            "provenance": _provenance(
                f"{cluster.pointer_source}:{cluster.pointer_locator}", confidence
            ),
        }
        return path

    # --- typography -----------------------------------------------------

    def add_typography(self, path: str, style: dict, basis: str, pointer: str) -> None:
        confidence = _confidence_for(basis)
        self.confidence_samples.append(confidence)
        self.typography[path] = {
            "value": _mode_value(style, {}),
            "role": path.split(".", 1)[1],
            "description": None,
            "provenance": _provenance(pointer, confidence),
        }
        self.role_assignments.append(
            {"token": path, "value": f"{style['font_family']} {style['font_size']}", "basis": basis, "pointer": pointer}
        )

    # --- numbers --------------------------------------------------------

    def add_numbers(self, target: dict, values: dict[str, dict], role: str, source: str) -> None:
        confidence = _confidence_for("derived")
        for path, number in values.items():
            target[path] = {
                "value": _mode_value(number, {}),
                "role": role,
                "description": None,
                "provenance": _provenance(source, confidence),
            }

    # --- assets ---------------------------------------------------------

    def add_font(self, key: str, font: FontEvidence, fallback: list[str]) -> None:
        has_webfont = any(face.source_url for face in font.faces)
        source = (
            {"kind": "url", "url": next(f.source_url for f in font.faces if f.source_url)}
            if has_webfont
            else {"kind": "system", "family": font.family}
        )
        faces = [
            {
                "weight": face.weight or 400,
                "style": face.style if face.style in ("normal", "italic") else "normal",
                "asset_id": face.asset_id,
                "source_url": face.source_url,
            }
            for face in font.faces
        ]
        if not faces:
            self.diagnostics.append(
                {
                    "code": "LUMI0230",
                    "severity": "warning",
                    "message": f"font files not sourced for {font.family} — upload or pick an alternative",
                }
            )
        self.fonts[key] = {
            "family": font.family,
            "source": source,
            "faces": faces,
            "fallback_stack": font.fallback_stack or fallback,
            "scripts": ["latin"],
            "license": {
                "name": font.license_hint or "unknown",
                "embeddable": False,
                "subsettable": False,
                "source_url": None,
                "restrictions": [
                    "License not verified at ingestion; do not embed in print exports without confirmation."
                ],
            },
            "provenance": _provenance(f"{font.pointer.source}:{font.pointer.locator}", 0.7),
        }

    def add_logos(self, logos: list[LogoEvidence]) -> None:
        groups: dict[str, list[LogoEvidence]] = {}
        for logo in logos:
            key = logo.usage_hint or "primary"
            groups.setdefault(key, []).append(logo)

        clearspace_rule = _rule_numeric(self.evidence, "clearspace")
        min_size_rule = _rule_numeric(self.evidence, "min_size")

        for key, group in groups.items():
            has_reversed = any(g.color_mode_hint == "reversed" for g in group)
            allowed = ["surface.page", "surface.card"]
            if has_reversed:
                allowed.append("surface.inverse")
            self.logos[key] = {
                "variants": [
                    {
                        "name": logo.color_mode_hint or "full_color",
                        "asset_id": logo.asset_id,
                        "color_mode": logo.color_mode_hint or "full_color",
                        "width": logo.width,
                        "height": logo.height,
                    }
                    for logo in group
                ],
                "usage": key,
                "min_size": min_size_rule,
                "clearspace": clearspace_rule,
                "allowed_backgrounds": allowed,
                "license": None,
                "provenance": _provenance(f"{group[0].pointer.source}:{group[0].pointer.locator}", 0.7),
            }

        # asset tokens
        primary = groups.get("primary")
        if primary:
            self._asset_token("logo.primary", primary[0].asset_id, 0.7)
            reversed_variant = next((g for g in primary if g.color_mode_hint == "reversed"), None)
            if reversed_variant:
                self._asset_token("logo.reversed", reversed_variant.asset_id, 0.7)
        if groups.get("mark"):
            self._asset_token("logo.mark", groups["mark"][0].asset_id, 0.7)
        if groups.get("wordmark"):
            self._asset_token("logo.wordmark", groups["wordmark"][0].asset_id, 0.7)
        # a reversed logo may live only under primary already handled; also check any group
        for group in groups.values():
            reversed_variant = next((g for g in group if g.color_mode_hint == "reversed"), None)
            if reversed_variant and "logo.reversed" not in self.asset_tokens:
                self._asset_token("logo.reversed", reversed_variant.asset_id, 0.7)

    def _asset_token(self, path: str, asset_id: str, confidence: float) -> None:
        self.asset_tokens[path] = {
            "value": _mode_value({"kind": "asset", "asset_id": asset_id}, {}),
            "description": f"Ingested {path} asset",
            "provenance": _provenance("upload:asset", confidence),
        }

    def add_images(self) -> None:
        for index, image in enumerate(self.evidence.images, start=1):
            key = f"img.{index}"
            self.images[key] = {
                "asset_id": image.asset_id,
                "role": image.kind_hint or "photo",
                "mime_type": None,
                "license": None,
                "provenance": _provenance(f"{image.pointer.source}:{image.pointer.locator}", 0.6),
                "style_tags": [],
                "allowed_contexts": [],
                "preferred_color_tokens": [],
                "recolor_allowed": False,
                "crop_allowed": True,
            }

    # --- aliases --------------------------------------------------------

    def add_alias(self, alias: str, token: str, description: str) -> None:
        self.aliases[alias] = {"token": token, "description": description}

    # --- diagnostics / gaps --------------------------------------------

    def report_missing_asset_tokens(self) -> list[str]:
        gaps: list[str] = []
        for path in REQUIRED_ASSET_TOKENS:
            if path not in self.asset_tokens:
                gaps.append(path)
                self.diagnostics.append(
                    {
                        "code": "LUMI0220",
                        "severity": "info",
                        "message": f"asset token {path} not populated",
                    }
                )
        return gaps

    # --- assembly -------------------------------------------------------

    def overall_confidence(self) -> float:
        if not self.confidence_samples:
            return 0.3
        return round(sum(self.confidence_samples) / len(self.confidence_samples), 4)

    def build(self, notes: list[str], constraints: dict) -> dict:
        return {
            "id": self.brand_kit_id,
            "version": self.version,
            "name": self.name,
            "description": None,
            "sources": [self.evidence.source],
            "provenance": {
                "created_by": "lumen_ingestion",
                "created_at": self.created_at,
                "updated_at": None,
                "confidence": self.overall_confidence(),
                "notes": notes,
            },
            "approval_status": "draft",
            "modes": {
                "axes": {
                    "theme": ["light", "dark"],
                    "density": ["comfortable", "compact"],
                    "accessibility": ["standard", "high_contrast", "large_text"],
                },
                "defaults": {"theme": "light", "density": "comfortable", "accessibility": "standard"},
            },
            "tokens": {
                "colors": self.colors,
                "typography": self.typography,
                "numbers": {},
                "spacing": self.spacing,
                "radii": self.radii,
                "stroke_widths": self.stroke_widths,
                "opacity": self.opacity,
                "shadows": {},
                "effects": {},
                "assets": self.asset_tokens,
                "aliases": self.aliases,
            },
            "assets": {
                "fonts": self.fonts,
                "logos": self.logos,
                "images": self.images,
            },
            "constraints": constraints,
        }


def _confidence_for(basis: str) -> float:
    if basis == "evidence":
        return 0.9
    if basis == "derived":
        return 0.6
    return 0.3


def _rule_numeric(evidence: BrandEvidence, kind: str) -> float | None:
    for rule in evidence.rules:
        if rule.kind == kind and rule.numeric_value is not None:
            return rule.numeric_value
    return None


def build_constraints(
    evidence: BrandEvidence,
    tone_override: list[str] | None = None,
    cta_color: str = "text.inverse",
) -> dict:
    def texts(kind: str) -> list[str]:
        return [rule.text for rule in evidence.rules if rule.kind == kind]

    tone = tone_override or texts("tone") or ["clear", "professional"]
    print_constraints = texts("print") + [_PRINT_FONT_CAUTION]
    # Combination rules ("text in Off White on 100% color backgrounds…") are
    # contrast-usage guidance — accessibility_notes is their closest home.
    return {
        "allow_gradients": True,
        "tone": tone,
        "imagery": texts("imagery"),
        "iconography": texts("iconography"),
        "accessibility_notes": texts("accessibility") + texts("combination"),
        "print_constraints": print_constraints,
        "contrast_pairs": [
            {"foreground": "text.primary", "background": "surface.page", "min_ratio": 4.5},
            {"foreground": cta_color, "background": "surface.brand", "min_ratio": 4.5},
            {"foreground": "text.inverse", "background": "surface.inverse", "min_ratio": 4.5},
        ],
    }
