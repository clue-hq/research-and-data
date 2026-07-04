#!/usr/bin/env python
"""Render a Lumen DSL doc to PNG for visual probing (A0 calibration gate).

Usage: python .context/render-probe.py <file.lumen> <out.png>
Requires: PYTHONPATH=apps/api:apps/agent_runtime, LUMEN_CORE_HELPER set (recommended).
"""
import base64
import json
import sys

from lumen_api.core import CoreClient


def main(src: str, out: str) -> None:
    dsl = open(src).read()
    c = CoreClient()
    scene = c.new_scene("probe", "probe")
    res = c.compile_dsl_into_scene(scene, dsl)
    co = (res.get("dsl") or {}).get("compile_output") or {}
    cerrs = [d for d in (co.get("diagnostics") or []) if d and d.get("severity") in ("error", "blocker")]
    if co.get("halted_at") or cerrs:
        print(json.dumps({"ok": False, "stage": "compile", "errors": cerrs, "halted": co.get("halted_at")}, indent=2))
        return
    exp = c.export_preview(res["scene"], "png")
    artifacts = (exp.get("export") or {}).get("artifacts") or []
    wrote = False
    for a in artifacts:
        b64 = a.get("bytes") or a.get("bytes_base64") or a.get("data_base64") or a.get("base64")
        if isinstance(b64, list):
            open(out, "wb").write(bytes(b64))
            wrote = True
            break
        if b64:
            open(out, "wb").write(base64.b64decode(b64))
            wrote = True
            break
        path = a.get("path") or a.get("file_path")
        if path:
            print(json.dumps({"ok": True, "artifact_path": path}))
            wrote = True
            break
    print(json.dumps({"ok": True, "wrote": wrote, "out": out, "artifact_keys": [list(a.keys()) for a in artifacts]}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
