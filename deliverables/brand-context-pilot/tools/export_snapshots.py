"""Export the saved V2 pilot without changing its original run directory."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / "deliverables/brand-context-pilot"
SOURCE = ROOT / "experiments/brand-context-agent-v1/runs"
VERSIONS = {"v2": "conduit-rework-20260919"}
EXCLUDED_DIRS = {"cache", "raw", "baseline", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"run.lock", "model-catalog.json", ".DS_Store"}
SECRET_PATTERNS = [
    rb"\bsk-[A-Za-z0-9_-]{20,}\b", rb"\bsk_[A-Za-z0-9_-]{20,}\b",
    rb"\bAKIA[0-9A-Z]{16}\b", rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def excluded(relative):
    if relative.parts[0] in EXCLUDED_DIRS:
        return "provider/page cache or private database baseline"
    if relative.name in EXCLUDED_FILES or relative.suffix in {".log", ".pyc"}:
        return "process log, lock, compiled cache or provider catalog"
    if relative.name == ".env" or relative.name.startswith(".env."):
        return "environment configuration"
    return None


def main():
    # Inspect every selected file before creating any exports. Never print matched secrets.
    selections = {}
    for version, run in VERSIONS.items():
        source = SOURCE / run
        selected, omitted = [], []
        for file in sorted(source.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(source)
            reason = excluded(relative)
            if reason:
                omitted.append({"path": str(relative), "reason": reason})
                continue
            if any(re.search(pattern, file.read_bytes()) for pattern in SECRET_PATTERNS):
                raise SystemExit("Credential-like content found in selected export; stop for private review: " + str(relative))
            selected.append((file, relative))
        selections[version] = (run, selected, omitted)
    summaries = []
    for version, (run, selected, omitted) in selections.items():
        target = DEST / version
        hashes = {}
        for file, relative in selected:
            out = target / relative
            if out.exists() and out.read_bytes() != file.read_bytes():
                raise SystemExit("Existing frozen snapshot differs; create a new version instead: " + str(out))
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                shutil.copy2(file, out)
            hashes[str(relative)] = sha(file)
        payload = json.loads((target / "public/data.json").read_text())
        manifest = {"version": version, "source_run": run, "source_path": str((SOURCE / run).relative_to(ROOT)),
                    "files": hashes, "excluded": omitted,
                    "documents": len(payload["documents"]), "assets": len(payload["assets"]),
                    "sources": len(payload["sources"]), "status": "Preserved supervised research draft; not production-approved."}
        (target / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        summaries.append({k: manifest[k] for k in ["version", "source_run", "documents", "assets", "sources"]})
        print(version, "exported", len(hashes), "files; omitted", len(omitted), "local runtime/cache files")
    (DEST / "snapshots.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    main()
