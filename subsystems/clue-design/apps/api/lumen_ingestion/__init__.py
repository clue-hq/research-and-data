"""Brand-kit ingestion — evidence IR + deterministic normalizer.

Slice 0 exposes the `BrandEvidence` intermediate representation and the
`normalize_evidence` entry point that turns a captured evidence bundle into a
validated engine Brand Kit. Nothing here imports the heavy capture dependencies
(playwright / pymupdf / fonttools / pillow); those land in requirements but stay
unimported until the capture slices.
"""

from __future__ import annotations

from .evidence import (
    BrandEvidence,
    ColorEvidence,
    DeclaredRoleEvidence,
    EvidencePointer,
    FontEvidence,
    FontFaceEvidence,
    GeometryEvidence,
    ImageEvidence,
    KeyframeStep,
    LogoEvidence,
    MeasuredAnimation,
    MeasuredReveal,
    MeasuredStyle,
    MotionEvidence,
    NarrativeEvidence,
    NumberSample,
    RuleEvidence,
    ScriptedMotion,
    SectionBackground,
    ShadowSample,
    StateStyle,
    StyleIcon,
    StyleLook,
    StyleTransition,
    SurfaceShape,
    TypeSample,
)
from .normalizer import NormalizeResult, normalize_evidence

__all__ = [
    "BrandEvidence",
    "ColorEvidence",
    "DeclaredRoleEvidence",
    "EvidencePointer",
    "FontEvidence",
    "FontFaceEvidence",
    "GeometryEvidence",
    "ImageEvidence",
    "KeyframeStep",
    "LogoEvidence",
    "MeasuredAnimation",
    "MeasuredReveal",
    "MeasuredStyle",
    "MotionEvidence",
    "NarrativeEvidence",
    "NumberSample",
    "RuleEvidence",
    "ScriptedMotion",
    "SectionBackground",
    "ShadowSample",
    "StateStyle",
    "StyleIcon",
    "StyleLook",
    "StyleTransition",
    "SurfaceShape",
    "TypeSample",
    "NormalizeResult",
    "normalize_evidence",
]
