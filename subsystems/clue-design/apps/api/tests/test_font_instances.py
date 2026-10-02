"""Plan 1 item B (2026-09-04): a harvested VARIABLE font is instanced into one static face per
named weight, so the kit (and the editor's Bold) has real faces to serve."""

from __future__ import annotations

from io import BytesIO

from fontTools.ttLib import TTFont

from lumen_ingestion.capture.font_instances import INSTANCE_WEIGHTS, plan_font_instances
from variable_font_fixture import as_woff2, build_variable_font

INTER = __import__("pathlib").Path(__file__).resolve().parents[3] / "fonts" / "Inter-Regular.ttf"


def _os2_weight(data: bytes) -> int:
    return TTFont(BytesIO(data))["OS/2"].usWeightClass


def test_a_variable_font_yields_one_static_face_per_named_weight() -> None:
    plan = plan_font_instances("Synthetic VF", build_variable_font())
    assert plan.variable is True
    assert plan.wght_range == (300.0, 900.0)
    assert plan.error is None
    assert [i.weight for i in plan.instances] == list(INSTANCE_WEIGHTS)
    assert [_os2_weight(i.data) for i in plan.instances] == [400, 500, 600, 700]
    assert all(i.italic is False for i in plan.instances)
    # Static: the instance carries no fvar, and its digest names the exact bytes.
    first = plan.instances[0]
    assert "fvar" not in TTFont(BytesIO(first.data))
    assert first.sha256 == __import__("hashlib").sha256(first.data).hexdigest()
    # The 700 instance is a real Bold: heavier advance than the 400 one (the stem grew).
    widths = {i.weight: TTFont(BytesIO(i.data))["hmtx"]["I"][0] for i in plan.instances}
    assert widths[700] > widths[400]


def test_a_woff2_wrapped_variable_font_is_decoded_before_instancing() -> None:
    plan = plan_font_instances("Synthetic VF", as_woff2(build_variable_font()))
    assert plan.variable is True and len(plan.instances) == 4
    assert plan.instances[0].data[:4] == b"\x00\x01\x00\x00"  # sfnt, never woff2


def test_weights_outside_the_axis_range_are_skipped_not_fabricated() -> None:
    plan = plan_font_instances("Narrow VF", build_variable_font(wght=(500, 700)))
    assert [i.weight for i in plan.instances] == [500, 600, 700]
    assert plan.skipped_weights == [400]
    assert plan.error is None


def test_a_static_font_is_left_alone() -> None:
    plan = plan_font_instances("Inter", INTER.read_bytes())
    assert plan.variable is False
    assert plan.instances == [] and plan.error is None


def test_garbage_bytes_report_an_error_instead_of_raising() -> None:
    plan = plan_font_instances("Junk", b"wOF2" + b"\x00" * 64)
    assert plan.variable is False and plan.instances == []
    assert plan.error  # the decode failure, in words


def test_italic_instances_carry_the_italic_bit() -> None:
    plan = plan_font_instances("Synthetic VF", build_variable_font(), italic=True)
    assert all(i.italic for i in plan.instances)
    assert TTFont(BytesIO(plan.instances[0].data))["OS/2"].fsSelection & 0x0001
