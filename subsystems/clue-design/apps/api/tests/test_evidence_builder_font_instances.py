"""Plan 1 item B: the evidence builder turns a harvested variable font into static kit faces,
ingests each as its own asset, and keeps the variable file rehosted. Also pins that an italic
@font-face declared by the site passes through parse → evidence unchanged (no new harvest code:
the Apollo site simply declares none)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.ttLib import TTFont
from io import BytesIO

from lumen_ingestion.capture.evidence_builder import build_evidence
from lumen_ingestion.capture.snapshot import Download, Stylesheet, load_snapshot
from variable_font_fixture import as_woff2, build_variable_font

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"
VF_URL = "https://units.example/fonts/synthetic-vf.woff2"
ITALIC_URL = "https://units.example/fonts/synthetic-italic.woff2"


class _RecordingCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "asset": {"record": {"asset_id": kwargs["asset_id"]}}}


@dataclass
class _Outcome:
    snapshot: object
    tier: str = "static"
    escalated: bool = False
    escalation_reason: str | None = None
    diagnostics: list[dict] = field(default_factory=list)


def _snapshot(css: str, downloads: list[Download]):
    base = load_snapshot(FIXTURES / "insight_static.json")
    return base.model_copy(
        update={
            "stylesheets": [Stylesheet(url="https://units.example/site.css", text=css)],
            "downloads": downloads,
            "computed_samples": None,
        }
    )


def _download(url: str, data: bytes) -> Download:
    return Download(
        url=url, kind="font", content_type="font/woff2",
        bytes_b64=base64.b64encode(data).decode("ascii"),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _weights_ingested(core: _RecordingCore) -> dict[str, int]:
    out = {}
    for call in core.calls:
        if call.get("kind") != "font":
            continue
        data = base64.b64decode(call["bytes_base64"])
        font = TTFont(BytesIO(data))
        if "fvar" in font:
            continue
        out[call["asset_id"]] = font["OS/2"].usWeightClass
    return out


def test_a_variable_face_becomes_four_static_kit_faces(tmp_path: Path) -> None:
    vf = as_woff2(build_variable_font("Synthetic VF"))
    css = f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL}) format("woff2");font-weight:100 900;}}'
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, vf)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)

    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    assert [face.weight for face in font.faces] == [400, 500, 600, 700]
    assert all(face.asset_id and face.asset_id.startswith("asset_ing_") for face in font.faces)
    assert all(face.format == "ttf" and face.style == "normal" for face in font.faces)
    # The declared (400) instance keeps the variable url so the kit's `source.url` survives.
    assert font.faces[0].source_url == VF_URL
    assert all(face.source_url is None for face in font.faces[1:])
    # Each instance was ingested as sfnt at its own weight, and the variable file still was.
    assert sorted(_weights_ingested(core).values()) == [400, 500, 600, 700]
    assert any(
        base64.b64decode(c["bytes_base64"]) == vf for c in core.calls if c.get("kind") == "font"
    )
    instance_calls = [c for c in core.calls if c["asset_id"] in {f.asset_id for f in font.faces}]
    assert all(c["provenance"]["notes"] and "instance" in c["provenance"]["notes"][0] for c in instance_calls)
    assert all(c["filename"].endswith(".ttf") for c in instance_calls)
    assert [d["code"] for d in outcome.diagnostics if d["code"].startswith("LUMI023")] == ["LUMI0234"]


def test_an_instancing_failure_keeps_the_single_face_and_says_so(tmp_path: Path, monkeypatch) -> None:
    import lumen_ingestion.capture.evidence_builder as eb
    from lumen_ingestion.capture.font_instances import FontInstancePlan

    monkeypatch.setattr(
        eb, "plan_font_instances",
        lambda family, data, **kw: FontInstancePlan(family, True, (300.0, 900.0), error="boom"),
    )
    vf = as_woff2(build_variable_font("Synthetic VF"))
    css = f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL}) format("woff2");}}'
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, vf)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)
    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    assert [face.weight for face in font.faces] == [400]
    assert font.faces[0].asset_id and font.faces[0].source_url == VF_URL
    assert [d["code"] for d in outcome.diagnostics if d["code"].startswith("LUMI023")] == ["LUMI0235"]


def test_a_declared_italic_face_passes_through_to_evidence(tmp_path: Path) -> None:
    upright = as_woff2(build_variable_font("Synthetic VF"))
    italic = as_woff2(build_variable_font("Synthetic VF", wght=(400, 700)))
    css = (
        f'@font-face{{font-family:"Synthetic VF";src:url({VF_URL});font-style:normal;}}'
        f'@font-face{{font-family:"Synthetic VF";src:url({ITALIC_URL});font-style:italic;}}'
    )
    core = _RecordingCore()
    outcome = _Outcome(snapshot=_snapshot(css, [_download(VF_URL, upright), _download(ITALIC_URL, italic)]))
    evidence = build_evidence(outcome, core=core, store_root=str(tmp_path), reporter=lambda s, p: None)
    font = next(f for f in evidence.fonts if f.family == "Synthetic VF")
    italics = [face for face in font.faces if face.style == "italic"]
    uprights = [face for face in font.faces if face.style == "normal"]
    assert [f.weight for f in uprights] == [400, 500, 600, 700]
    assert [f.weight for f in italics] == [400, 500, 600, 700]
    italic_ids = {f.asset_id for f in italics}
    italic_calls = [c for c in core.calls if c["asset_id"] in italic_ids]
    assert all(TTFont(BytesIO(base64.b64decode(c["bytes_base64"])))["OS/2"].fsSelection & 1 for c in italic_calls)
