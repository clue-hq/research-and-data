"""Verify frozen delivery manifests and every viewer asset without provider calls."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / "deliverables/brand-context-pilot"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (DEST / "v1").exists(), "V1 must not be included in this delivery"
    for version, counts in [("v2", (25, 56, 103))]:
        root = DEST / version
        manifest = json.loads((root / "snapshot-manifest.json").read_text())
        original = ROOT / manifest["source_path"]
        actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name != "snapshot-manifest.json"}
        assert actual == set(manifest["files"]), "Missing or extra snapshot files"
        for name, digest in manifest["files"].items():
            assert sha(root / name) == digest, "Snapshot changed: " + name
            if original.exists():
                assert sha(original / name) == digest, "Original and copy differ: " + name
        public = root / "public"
        viewer_manifest = json.loads((public / "manifest.json").read_text())
        for name, digest in viewer_manifest.items():
            assert sha(public / name) == digest, "Viewer integrity mismatch: " + name
        data = json.loads((public / "data.json").read_text())
        assert tuple(len(data[k]) for k in ["documents", "assets", "sources"]) == counts
        for asset in data["assets"]:
            for key in ["path", "preview"]:
                if asset.get(key):
                    target = (public / asset[key]).resolve()
                    assert target.is_relative_to(public.resolve()) and target.is_file()
        for document in data["documents"]:
            assert document.get("markdown") and document.get("html")
        print(version, "PASS", len(actual), "files;", counts, "documents/assets/sources; local original comparison:", original.exists())


if __name__ == "__main__":
    main()
