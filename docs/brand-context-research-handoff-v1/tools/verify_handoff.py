"""Offline acceptance for the handoff, not a live research-quality test."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

PACK = Path(__file__).resolve().parents[1]
REPO = PACK.parents[1]


def read(name):
    return json.loads((PACK / name).read_text())


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    protected = read("reference/protected-files.json")
    root = REPO / "experiments/brand-context-agent-v1"
    current = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(root.rglob("*")) if p.is_file()}
    check(protected == current, "Protected experiment changed, lost files, or acquired files.")
    docs = read("reference/document-index.json")
    catalog = read("document-catalog.json")
    keys = {d["key"] for d in docs}
    check(len(docs) == len(keys) == 25, "Reference document coverage differs.")
    check(keys == {c["reference_key"] for c in catalog}, "Catalog does not map all reference documents.")
    sources = {s["id"]: s for s in read("reference/source-index.json")}
    check(len(sources) == 103, "Source inventory differs.")
    for d in docs:
        source = REPO / d["source_document"]
        raw = json.loads(source.read_text())
        body = (PACK / d["output"]).read_text()
        check(body == raw["markdown"], "Copied reference changed: " + d["key"])
        check(hashlib.sha256(body.encode()).hexdigest() == d["body_sha256"], "Body hash differs.")
        check(hashlib.sha256(source.read_bytes()).hexdigest() == d["source_sha256"], "Source document hash differs.")
        check(set(d["source_ids"]) <= sources.keys(), "Unresolved document source IDs.")
    graph = {c["reference_key"]: c["reference_dependencies"] for c in catalog}
    visited, active = set(), set()

    def visit(key):
        check(key in graph, "Unresolved catalog dependency: " + key)
        check(key not in active, "Cyclic proposed dependency: " + key)
        if key in visited:
            return
        active.add(key)
        for dep in graph[key]:
            visit(dep)
        active.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    for c in catalog:
        check((PACK / c["prompt"]).is_file(), "Missing task prompt.")
    prompts = list((PACK / "prompts").glob("[0-9]*.md"))
    check(len(prompts) == 13, "Need shared instruction plus 12 task prompts.")
    check(all("conduit.ai" not in p.read_text().lower() for p in prompts), "Hardcoded brand domain in proposed prompt.")
    check(len(read("reference/original-document-briefs.json")) == 23, "Original brief coverage differs.")
    # Reconstruct the archived literal prompt without importing any experiment module.
    for name in ["agent", "knowledge", "rework", "rework_review"]:
        value = ""
        for n in ast.parse((root / (name + ".py")).read_text()).body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYSTEM" for t in n.targets):
                value = ast.literal_eval(n.value)
            if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id == "SYSTEM":
                value += ast.literal_eval(n.value)
        archive = (PACK / "reference/prompts" / (name + ".md")).read_text()
        check("```text\n" + value + "\n```" in archive, "Archived prompt differs: " + name)
    # Exclude copied historical bodies/prompts from relative-link lint: they intentionally
    # retain original viewer routes and literal prompt syntax. Fidelity is checked above.
    markdown = [p for p in PACK.rglob("*.md") if "reference" not in p.relative_to(PACK).parts]
    markdown.append(REPO / "docs/superpowers/plans/2026-09-20-exa-brand-context-handoff.md")
    checked_links = 0
    for path in markdown:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if target.startswith(("http:", "https:", "#", "mailto:")):
                continue
            target = unquote(target.split("#", 1)[0])
            check((path.parent / target).exists(), f"Broken local link: {path}: {target}")
            checked_links += 1
    schema = read("schemas/research-output.schema.json")
    check("agent_context" not in json.dumps(schema), "Knowledge schema includes creative context.")
    # Reuse the frontend's already installed AJV 8; do not install Python packages.
    subprocess.run(["node", str(PACK / "tools/verify_schema.cjs")], check=True, capture_output=True, text=True)
    print(json.dumps({"result": "pass", "protected_files_unchanged": len(protected),
                      "reference_bodies_exact": len(docs), "source_records": len(sources),
                      "original_briefs": 23, "archived_prompts": 4, "proposed_prompt_files": len(prompts),
                      "catalog_is_acyclic": True, "local_links_checked": checked_links,
                      "schema_valid": True, "negative_schema_cases": 3,
                      "live_research_quality": "not tested", "platform_integration": "not performed"}, indent=2))


if __name__ == "__main__":
    main()
