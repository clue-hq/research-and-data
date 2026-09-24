"""Keep the account experiment isolated, reproducible and free of benchmark answers."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import trial_account_discovery as trial  # noqa: E402


def snapshot(root):
    refs = []
    for name in ("seller", "icp", "persona"):
        path = root / f"inputs/documents/{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Original {name}")
        refs.append({"path": f"documents/{name}.md", "sha256": trial.digest(path)})
    trial.save(
        root / "inputs/research/context.json",
        {
            "seller_documents": refs[:1],
            "icp": refs[1],
            "personas": refs[2:],
            "target": {"name": "Acme", "domain": "acme.example"},
        },
    )
    (root / "inputs/delegation-brief.md").write_text("Original Head brief")
    trial.save(
        root / "manifest.json",
        {
            "input_hashes": {
                str(p.relative_to(root)): trial.digest(p)
                for p in (root / "inputs").rglob("*")
                if p.is_file()
            }
        },
    )


def test_preparation_preserves_context_excludes_later_answers_and_changes_only_trial(tmp_path):
    source, out = tmp_path / "source", tmp_path / "trial"
    snapshot(source)
    trial.save(source / "inputs/evidence/old.json", {"answer": "BENCHMARK_ANSWER"})
    trial.save(source / "findings.json", {"answer": "PREVIOUS_RESEARCH"})
    trial.prepare(source, out)
    trial.verify(out)
    contents = "".join(p.read_text() for p in (out / "inputs").rglob("*") if p.is_file())
    assert "BENCHMARK_ANSWER" not in contents
    assert "PREVIOUS_RESEARCH" not in contents
    assert "Original Head brief" in contents
    assert trial.GUIDANCE.read_text() in (out / "account-system-prompt.md").read_text()
    for name in ("exa-system.md", "request-config.json"):
        assert (out / "instructions" / name).read_bytes() == (
            trial.CATALOG / "provider-requests/account-deep/v1" / name
        ).read_bytes()
    skill = (out / "inputs/.deepagent/skills/account-dossier/v2/SKILL.md").read_text()
    original = (out / "instructions/account-dossier.original.md").read_text()
    assert (
        skill.split("## Research priorities and depth")[1]
        == original.split("## Research priorities and depth")[1]
    )
    assert not (out / "dispatch.json").exists()
    with pytest.raises(ValueError, match="fresh output"):
        trial.prepare(source, out)


def test_changed_context_or_prepared_inputs_are_rejected(tmp_path):
    source, out = tmp_path / "source", tmp_path / "trial"
    snapshot(source)
    trial.prepare(source, out)
    (out / "inputs/delegation-brief.md").write_text("Changed")
    with pytest.raises(ValueError, match="Prepared input changed"):
        trial.verify(out)
    (source / "inputs/documents/seller.md").write_text("Changed")
    with pytest.raises(ValueError, match="Original input changed"):
        trial.prepare(source, tmp_path / "second")


def test_pins_and_path_boundaries_checked(tmp_path):
    source = tmp_path / "source"
    snapshot(source)
    path = source / "inputs/research/context.json"
    context = json.loads(path.read_text())
    context["icp"]["sha256"] = "incorrect"
    trial.save(path, context)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["input_hashes"][str(path.relative_to(source))] = trial.digest(path)
    trial.save(manifest_path, manifest)
    with pytest.raises(ValueError, match="Pinned document mismatch"):
        trial.prepare(source, tmp_path / "out")
    with pytest.raises(ValueError, match="escapes snapshot"):
        trial.inside(source, "../other/answers.json")


def test_refinement_reaches_actual_prompt_and_skill_without_changing_inputs_or_exa(tmp_path):
    source, baseline, refined = tmp_path / "source", tmp_path / "baseline", tmp_path / "refined"
    snapshot(source)
    trial.prepare(source, baseline)
    trial.prepare(source, refined, refined=True)
    trial.verify(refined)
    addition = (trial.GUIDANCE.parent / "source-follow-through.md").read_text()
    for path in (
        "account-system-prompt.md",
        "inputs/.deepagent/skills/account-dossier/v2/SKILL.md",
    ):
        assert addition in (refined / path).read_text()
        assert addition not in (baseline / path).read_text()
    manifest = json.loads((refined / "trial-manifest.json").read_text())
    for path, sha in manifest["copied_original_inputs"].items():
        assert trial.digest(refined / path) == trial.digest(baseline / path) == sha
    for path in ("instructions/exa-system.md", "instructions/request-config.json"):
        assert (refined / path).read_bytes() == (baseline / path).read_bytes()
    (refined / "instructions/source-follow-through.md").write_text("Changed after preparation")
    with pytest.raises(ValueError, match="Prepared input changed"):
        trial.verify(refined)
