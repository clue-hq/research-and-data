"""Offline input-boundary checks for a new strategy using the shared research runner."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import trial_person_discovery as trial  # noqa: E402


def source_snapshot(root):
    inputs = root / "inputs"
    trial.save(inputs / "products/offering.json", {"offering": "Selected product"})
    trial.save(inputs / "audience/icp.json", {"definition": "Project variant"})
    trial.save(inputs / "audience/persona.json", {"definition": "Selected persona"})
    refs = {
        name: {"path": name, "sha256": trial.digest(inputs / name)}
        for name in ("products/offering.json", "audience/icp.json", "audience/persona.json")
    }
    trial.save(
        inputs / "research/context.json",
        {
            "person_assignment": {"name": "Dana", "linkedin_url": "https://example.test/dana"},
            "target": {"name": "Acme"},
            "seller_name": "Seller",
            "run_date": "2026-09-24",
            "icp": refs["audience/icp.json"],
            "personas": [refs["audience/persona.json"]],
            "seller_documents": [refs["products/offering.json"]],
        },
    )
    for name in ("person-brief.md", "account-findings.md", "delegation-brief.md"):
        (inputs / name).write_text(f"Original {name}\n")
    trial.save(inputs / "evidence/index/0.json", {"sources": [], "next_path": None})
    trial.save(
        root / "manifest.json",
        {
            "input_hashes": {
                str(p.relative_to(inputs)): trial.digest(p)
                for p in inputs.rglob("*")
                if p.is_file()
            }
        },
    )


def test_original_inputs_preserved_and_later_answers_excluded(tmp_path):
    source, out = tmp_path / "source", tmp_path / "trial"
    source_snapshot(source)
    trial.save(source / "baseline/answer.json", {"secret": "BASELINE_ANSWER"})
    trial.save(source / "inputs/scratch/late.json", {"secret": "LATER_RESEARCH_ANSWER"})
    trial.prepare(source, out)
    text = "".join(p.read_text() for p in (out / "inputs").rglob("*") if p.is_file())
    assert "BASELINE_ANSWER" not in text
    assert "LATER_RESEARCH_ANSWER" not in text
    manifest = json.loads((out / "manifest.json").read_text())
    for name, sha in manifest["copied_original_inputs"].items():
        assert trial.digest(out / "inputs" / name) == sha
    for name in ("charter.md", "exa-system.md"):
        assert (out / "instructions" / name).read_bytes() == (trial.DRAFT / name).read_bytes()
    assert trial.OLD_PREPARATION not in (out / "person-system.actual.md").read_text()
    assert (trial.TRIAL / "discovery-instructions.md").read_text() in text
    assert not (out / "traces").exists()
    assert not (out / "initial-response.original.json").exists()
    with pytest.raises(ValueError, match="fresh output"):
        trial.prepare(source, out)


def test_modified_source_is_not_silently_used(tmp_path):
    source = tmp_path / "source"
    source_snapshot(source)
    (source / "inputs/person-brief.md").write_text("Modified after snapshot")
    with pytest.raises(ValueError, match="Original input changed"):
        trial.prepare(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_pinned_document_mismatch_is_reported(tmp_path):
    source = tmp_path / "source"
    source_snapshot(source)
    ctx_path = source / "inputs/research/context.json"
    ctx = json.loads(ctx_path.read_text())
    ctx["personas"][0]["sha256"] = "wrong-pin"
    trial.save(ctx_path, ctx)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["input_hashes"]["research/context.json"] = trial.digest(ctx_path)
    trial.save(manifest_path, manifest)
    with pytest.raises(ValueError, match="Pinned document mismatch"):
        trial.prepare(source, tmp_path / "out")


def test_outside_snapshot_reference_rejected(tmp_path):
    with pytest.raises(ValueError, match="escapes input snapshot"):
        trial.inside(tmp_path, "../baseline/answer.json")


def test_media_follow_through_reaches_actual_trial_prompt_without_changing_exa(tmp_path):
    source, out = tmp_path / "source", tmp_path / "trial"
    source_snapshot(source)
    trial.prepare(source, out, fresh_source_review=True)
    guidance = (trial.TRIAL / "media-follow-through.md").read_text()
    assert guidance in (out / "person-system.actual.md").read_text()
    assert guidance in (out / "inputs/skills/person-dossier/SKILL.md").read_text()
    assert (out / "instructions/exa-system.md").read_bytes() == (
        trial.DRAFT / "exa-system.md"
    ).read_bytes()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["source_review_mode"] == "fresh-fields-v2"
    assert "platform/api/clue_api/arv2/media_resolution.py" in manifest["runner_hashes"]
