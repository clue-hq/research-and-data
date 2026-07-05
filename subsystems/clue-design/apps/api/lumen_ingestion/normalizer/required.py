"""Required product-ready token path lists, copied verbatim from
`crates/lumen-core/src/brand.rs` (lines 45-166). These are the token paths the
engine's product-ready validator checks for. The normalizer must emit all of the
non-asset sets; asset tokens are emitted only when we have the asset.
"""

from __future__ import annotations

REQUIRED_COLOR_TOKENS: tuple[str, ...] = (
    "palette.primary.50",
    "palette.primary.100",
    "palette.primary.200",
    "palette.primary.300",
    "palette.primary.400",
    "palette.primary.500",
    "palette.primary.600",
    "palette.primary.700",
    "palette.primary.800",
    "palette.primary.900",
    "palette.primary.950",
    "palette.neutral.50",
    "palette.neutral.100",
    "palette.neutral.200",
    "palette.neutral.300",
    "palette.neutral.400",
    "palette.neutral.500",
    "palette.neutral.600",
    "palette.neutral.700",
    "palette.neutral.800",
    "palette.neutral.900",
    "palette.neutral.950",
    "surface.canvas",
    "surface.page",
    "surface.card",
    "surface.elevated",
    "surface.brand",
    "surface.brand.subtle",
    "surface.accent",
    "surface.muted",
    "surface.inverse",
    "text.primary",
    "text.secondary",
    "text.muted",
    "text.inverse",
    "text.brand",
    "text.accent",
    "border.subtle",
    "border.default",
    "border.strong",
    "border.brand",
    "focus.ring",
)

REQUIRED_TYPOGRAPHY_TOKENS: tuple[str, ...] = (
    "type.display",
    "type.headline",
    "type.title",
    "type.subtitle",
    "type.body",
    "type.body.small",
    "type.caption",
    "type.eyebrow",
    "type.label",
    "type.cta",
    "type.stat",
    "type.legal",
)

REQUIRED_SPACING_TOKENS: tuple[str, ...] = (
    "space.0",
    "space.1",
    "space.2",
    "space.3",
    "space.4",
    "space.5",
    "space.6",
    "space.8",
    "space.10",
    "space.12",
    "space.16",
    "space.stack.tight",
    "space.stack.default",
    "space.stack.loose",
    "space.section",
    "space.page.margin",
    "space.card.padding",
)

REQUIRED_RADIUS_TOKENS: tuple[str, ...] = (
    "radius.none",
    "radius.xs",
    "radius.sm",
    "radius.md",
    "radius.lg",
    "radius.xl",
    "radius.full",
    "radius.card",
    "radius.button",
    "radius.badge",
)

REQUIRED_STROKE_WIDTH_TOKENS: tuple[str, ...] = (
    "stroke.width.hairline",
    "stroke.width.thin",
    "stroke.width.default",
    "stroke.width.firm",
    "stroke.width.bold",
    "stroke.width.divider",
    "stroke.width.card",
    "stroke.width.focus",
)

REQUIRED_OPACITY_TOKENS: tuple[str, ...] = (
    "opacity.disabled",
    "opacity.subtle",
    "opacity.muted",
    "opacity.overlay",
    "opacity.scrim",
    "opacity.emphasis",
)

REQUIRED_ASSET_TOKENS: tuple[str, ...] = (
    "logo.primary",
    "logo.reversed",
    "logo.mark",
    "logo.wordmark",
    "asset.illustration.primary",
    "asset.texture.subtle",
    "asset.icon.primary",
)

# Critical color tokens that the product-ready validator requires a theme.dark
# mode value for (brand.rs CRITICAL_MODE_COLOR_TOKENS). We emit theme.dark for
# ALL color tokens except palette.* ramps, so this is a superset guarantee.
CRITICAL_MODE_COLOR_TOKENS: tuple[str, ...] = (
    "surface.canvas",
    "surface.page",
    "surface.card",
    "surface.brand",
    "text.primary",
    "text.secondary",
    "text.inverse",
    "border.default",
    "focus.ring",
)
