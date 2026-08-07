#!/usr/bin/env python
"""Vet a Lumen DSL block: compile + preflight against the platform-default Brand Kit.

Usage:
    python .context/p02-validate.py <file.lumen>      # validate a full page+artboard+block doc
    cat doc.lumen | python .context/p02-validate.py    # or via stdin

Prints JSON: {"ok": bool, "stage": "compile"|"preflight", "errors": [...], "warnings": [...]}.
A block is VETTED iff ok == true. LUMB0613/LUMB0614 (platform font not embeddable/
subsettable) are warnings and never fail a block — they are environmental.
Requires env: PYTHONPATH=apps/api:apps/agent_runtime and (recommended)
LUMEN_CORE_HELPER=target/debug/lumen-api-helper to bypass cargo.
"""
import json
import sys

from lumen_api.core import CoreClient


def validate(dsl: str) -> dict:
    c = CoreClient()
    scene = c.new_scene("validate", "vet")
    res = c.compile_dsl_into_scene(scene, dsl)
    co = (res.get("dsl") or {}).get("compile_output") or {}
    cdiags = co.get("diagnostics") or []
    halted = co.get("halted_at")
    cerrs = [d for d in cdiags if d and d.get("severity") in ("error", "blocker")]
    if halted or cerrs:
        return {
            "ok": False,
            "stage": "compile",
            "halted_at": halted,
            "errors": [
                {"code": d.get("code"), "message": d.get("message"), "line": d.get("line")}
                for d in cerrs
            ],
        }
    pf = c.preflight_scene(res["scene"], c.platform_default_brand_kit())
    diags = pf.get("diagnostics") or []
    perrs = [d for d in diags if d.get("severity") in ("error", "blocker")]
    warns = [d.get("code") for d in diags if d.get("severity") == "warning"]
    return {
        "ok": len(perrs) == 0,
        "stage": "preflight",
        "errors": [
            {
                "code": d.get("code"),
                "message": d.get("message"),
                "node": d.get("target_node_id"),
                "slot": d.get("target_slot_id"),
            }
            for d in perrs
        ],
        "warnings": warns,
    }


if __name__ == "__main__":
    dsl = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    print(json.dumps(validate(dsl), indent=2))
