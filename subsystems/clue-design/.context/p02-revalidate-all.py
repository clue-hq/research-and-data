#!/usr/bin/env python
"""Independently re-validate every fenced ```text example in the block catalog."""
import pathlib
import re
import sys

sys.path[:0] = ["apps/api", "apps/agent_runtime"]
from lumen_api.core import CoreClient  # noqa: E402

c = CoreClient()
FENCE = re.compile(r"```text\n(.*?)```", re.S)


def validate(dsl):
    scene = c.new_scene("v", "v")
    res = c.compile_dsl_into_scene(scene, dsl)
    co = (res.get("dsl") or {}).get("compile_output") or {}
    cerrs = [d for d in (co.get("diagnostics") or []) if d and d.get("severity") in ("error", "blocker")]
    if co.get("halted_at") or cerrs:
        return ("COMPILE_FAIL", co.get("halted_at") or cerrs)
    pf = c.preflight_scene(res["scene"], c.platform_default_brand_kit())
    errs = [d.get("code") for d in pf.get("diagnostics", []) if d.get("severity") in ("error", "blocker")]
    return ("ok" if not errs else "PREFLIGHT_FAIL", errs)


blocks_dir = pathlib.Path("apps/agent_runtime/knowledge_docs/knowledge/design/blocks")
total = okc = 0
for f in sorted(blocks_dir.glob("*.md")):
    examples = FENCE.findall(f.read_text())
    for i, ex in enumerate(examples):
        total += 1
        status, info = validate(ex)
        if status == "ok":
            okc += 1
        else:
            print(f"  !! {f.name} example#{i + 1}: {status} {info}")
    print(f"{f.name}: {len(examples)} fenced examples")
print(f"\nTOTAL: {okc}/{total} examples ok==true")
