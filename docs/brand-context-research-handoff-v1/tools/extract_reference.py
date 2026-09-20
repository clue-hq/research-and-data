"""Offline evidence export. Reads the preserved experiment; writes only this handoff.

No experiment modules are imported, no environment is loaded, no network/DB is used.
Current source prompts are not falsely labelled as exact historical API payloads.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

PACK = Path(__file__).resolve().parents[1]
REPO = PACK.parents[1]
EXPERIMENT = REPO / "experiments/brand-context-agent-v1"
RUN = EXPERIMENT / "runs/conduit-rework-20260919"


def write(name, value):
    path = PACK / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_constant(path):
    value = ""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYSTEM" for t in node.targets):
            value = ast.literal_eval(node.value)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "SYSTEM":
            value += ast.literal_eval(node.value)
    return value


def main():
    # Capture all existing experiment bytes, including both run directories.
    # Kept as hashes only: do not export raw caches, source pages, credentials or receipts.
    inventory = {str(p.relative_to(REPO)): sha(p) for p in sorted(EXPERIMENT.rglob("*")) if p.is_file()}
    protected = PACK / "reference/protected-files.json"
    if protected.exists():
        assert json.loads(protected.read_text()) == inventory, "Protected experiment changed; stop rather than rebaseline."
    else:
        write("reference/protected-files.json", inventory)

    manifest = json.loads((RUN / "document-manifest.json").read_text())
    sources = json.loads((RUN / "sources.json").read_text())
    specs = []
    # Select only the inert specification declarations from the AST. No runtime imports.
    tree = ast.parse((EXPERIMENT / "rework.py").read_text())
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "spec":
            selected.append(node)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"PRODUCT_SECTIONS", "COMMON", "SPECS"} for t in node.targets):
            selected.append(node)
    scope = {"__builtins__": {"dict": dict, "list": list}}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "inert_rework_specs", "exec"), scope)
    specs = scope["SPECS"]
    write("reference/original-document-briefs.json", specs)
    for name in ["agent", "knowledge", "rework", "rework_review"]:
        p = EXPERIMENT / (name + ".py")
        write(f"reference/prompts/{name}.md", "# Archived source prompt: " + name + "\n\n"
              + "Extracted from `" + str(p.relative_to(REPO)) + "` (`SYSTEM` plus literal additions).\n"
              + "This is the current source text, not proof of the exact payload sent in every past call.\n\n```text\n"
              + prompt_constant(p) + "\n```\n")

    records = []
    for item in manifest["documents"]:
        key = item["key"]
        p = RUN / "documents" / (key + ".json")
        d = json.loads(p.read_text())
        output = f"reference/conduit-output/{item['folder']}/{key}.md"
        write(output, d["markdown"])
        records.append({
            "key": key, "title": d["title"], "folder": item["folder"],
            "source_document": str(p.relative_to(REPO)), "source_sha256": sha(p),
            "output": output, "body_sha256": hashlib.sha256(d["markdown"].encode()).hexdigest(),
            "word_count": len(d["markdown"].split()), "revision": d.get("revision"),
            "model_metadata": d.get("model"),
            "authorship_caution": "Model metadata does not exclude subsequent Codex editorial changes.",
            "depends_on": d.get("depends_on", []), "source_ids": d.get("source_ids", []),
            "headings": [x[3:] for x in d["markdown"].splitlines() if x.startswith("## ")],
            "open_questions": d.get("open_questions", []),
            "editorial_reviews": d.get("editorial_reviews", []),
        })
    write("reference/document-index.json", records)
    source_records = []
    for sid, s in sources.items():
        source_records.append({k: s.get(k) for k in ["id", "url", "title", "method", "retrieved_at", "published_date", "sha256", "query"]})
    write("reference/source-index.json", source_records)
    lines = ["# What was pulled for Conduit", "", "Historical inventory, not a new crawl or an endorsed set of current facts.", "",
             f"{len(sources)} source records; {len(set(s['url'] for s in sources.values()))} distinct URLs. Multiple captures of one page are not independent corroboration.", "",
             "| Recorded retrieval method | Records |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in collections.Counter(s.get("method") for s in sources.values()).items()]
    lines += ["", "Methods describe stored records, not counts of provider calls. Source text is retained in the original run and is not duplicated here.", "",
              "| Source ID | Public URL | Retrieved |", "| --- | --- | --- |"]
    lines += [f"| {s['id']} | [Source]({s['url']}) | {s.get('retrieved_at', '')} |" for s in source_records]
    write("reference/source-inventory.md", "\n".join(lines) + "\n")
    write("reference/extraction.json", {"reference_run": str(RUN.relative_to(REPO)), "documents": len(records),
          "source_records": len(sources), "original_briefs": len(specs), "protected_files": len(inventory),
          "source_methods": dict(collections.Counter(s.get("method") for s in sources.values())),
          "source_domains": dict(collections.Counter(urlsplit(s['url']).hostname for s in sources.values())),
          "source_code_sha256": {str((EXPERIMENT / f).relative_to(REPO)): sha(EXPERIMENT / f) for f in ["agent.py", "knowledge.py", "rework.py", "rework_review.py", "curation.py", "providers.py"]},
          "status": "Export only. No model calls, no integration, no autonomous quality result."})
    print(f"Exported {len(records)} document bodies, {len(specs)} original briefs, 4 prompts and {len(sources)} source records. Protected {len(inventory)} existing files.")


if __name__ == "__main__":
    main()
