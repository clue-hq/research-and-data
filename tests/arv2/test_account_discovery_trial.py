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


def test_live_claim_ready_mode_keeps_acquisition_excludes_old_results_and_direct_claim_tools(
    tmp_path,
):
    source, out = tmp_path / "source", tmp_path / "trial"
    snapshot(source)
    trial.save(source / "inputs/evidence/old.json", {"finding": "OLD_TARGET_ANSWER"})
    trial.prepare(source, out, refinement="source-follow-through-v2", claim_ready=True)
    trial.verify(out)
    prompt = (out / "account-system-prompt.md").read_text()
    assert "FRESH RESEARCH AND CLAIM-READY DOSSIER" in prompt
    assert "preliminary multi-angle searches" in prompt
    assert "Delegate source processing to research_claims" not in prompt
    assert "Delegate research_narrative" not in prompt
    assert "OLD_TARGET_ANSWER" not in "".join(
        p.read_text() for p in (out / "inputs").rglob("*") if p.is_file()
    )
    guide = (out / "inputs/.deepagent/skills/claim-ready-account-dossier/SKILL.md").read_text()
    assert '"id":"F001"' in guide and "/scratch/coverage.md" in guide
    assert "Zafran" not in guide and "Nick" not in guide
    assert json.loads((out / "trial-manifest.json").read_text())["claim_ready"]


def test_saved_replay_preserves_sources_excludes_answers_and_disables_acquisition(tmp_path):
    from live_account_dossier import prepare_replay

    source, out = tmp_path / "saved", tmp_path / "replay"
    trial.save(source / "inputs/research/context.json", {"target": {"name": "Example"}})
    trial.save(source / "inputs/research/capabilities/0.json", {"operations": {"search": {}}})
    trial.save(source / "inputs/evidence/index.json", {"sources": []})
    (source / "inputs/delegation-brief.md").write_text("Seller purpose")
    (source / "source-bodies").mkdir()
    body = source / "source-bodies/source-one.txt"
    body.write_text("Original public statement")
    trial.save(
        source / "source-manifest.json",
        [
            {
                "source_id": "source-one",
                "body_sha256": trial.digest(body),
            }
        ],
    )
    trial.save(source / "dossier.json", {"sections": []})
    (source / "REVIEW.md").write_text("DO NOT SEED REVIEW ANSWERS")
    trial.save(source / "inputs/scratch/coverage.json", {"answer": "OLD_NOTES"})
    prepare_replay(source, out)
    trial.verify(out)
    assert (out / "source-bodies/source-one.txt").read_bytes() == body.read_bytes()
    assert json.loads((out / "inputs/research/capabilities/0.json").read_text()) == {
        "operations": {}
    }
    manifest = json.loads((out / "trial-manifest.json").read_text())
    assert manifest["replay_saved_research"] and manifest["claim_ready"]
    inputs = "".join(p.read_text() for p in (out / "inputs").rglob("*") if p.is_file())
    assert "DO NOT SEED" not in inputs and "OLD_NOTES" not in inputs
    assert "Decide what the finding actually establishes" in inputs
    assert "No acquisition tools are installed" in (out / "account-system-prompt.md").read_text()
    with pytest.raises(ValueError, match="fresh replay"):
        prepare_replay(source, out)
    body.write_text("Changed source")
    with pytest.raises(ValueError, match="source body changed"):
        prepare_replay(source, tmp_path / "changed")


def test_fresh_dossier_freezes_only_current_sources_and_preserves_bytes(tmp_path):
    from live_account_dossier import finish_live, save_section

    inputs = tmp_path / "inputs"
    (inputs / "scratch").mkdir(parents=True)
    (inputs / "evidence").mkdir()
    path = "/evidence/0001-example.json"
    (inputs / path.lstrip("/")).write_text("Original fresh source")
    rows = [
        {
            "source_id": "fresh-source",
            "path": path,
            "source_url": "https://example.test/source",
            "kind": "web_snapshot",
            "origin_locator": "results/0",
        }
    ]
    record = {
        "id": "F001",
        "topic": "An observation",
        "claim_type": "observation",
        "finding": "Original detail preserved.",
        "source_paths": [path],
        "review": {"status": "supported", "reason": "Fresh source"},
    }
    assert save_section(tmp_path, rows, "Business", [record])["saved"]
    dossier = inputs / "scratch/account-dossier.json"
    first = dossier.read_bytes()
    record["source_paths"] = ["/evidence/previous-run.json"]
    assert not save_section(tmp_path, rows, "Business", [record])["saved"]
    assert dossier.read_bytes() == first
    record["source_paths"] = [path]
    record["id"] = "F002"
    assert save_section(tmp_path, rows, "Voice", [record])["saved"]
    record["finding"] = "Expanded detail."
    assert save_section(tmp_path, rows, "Voice", [record])["saved"]
    saved = json.loads(dossier.read_text())
    assert len(saved["sections"]) == 2
    assert saved["sections"][0]["findings"][0]["finding"] == "Original detail preserved."
    assert saved["sections"][1]["findings"][0]["finding"] == "Expanded detail."
    assert not save_section(tmp_path, rows, "Other", [record])["saved"]
    body = dossier.read_bytes()
    result = finish_live(tmp_path, rows, "Completed", [])
    assert result["finished"] and result["entries"] == 2
    assert (tmp_path / "dossier.json").read_bytes() == body
    assert "https://example.test/source" in (tmp_path / "findings.md").read_text()
    assert not save_section(tmp_path, rows, "Voice", [record])["saved"]


@pytest.mark.parametrize(
    ("kwargs", "filename"),
    [
        ({"refined": True}, "source-follow-through.md"),
        ({"refinement": "source-follow-through-v2"}, "source-follow-through-v2.md"),
    ],
)
def test_refinement_reaches_actual_prompt_and_skill_without_changing_inputs_or_exa(
    tmp_path, kwargs, filename
):
    source, baseline, refined = tmp_path / "source", tmp_path / "baseline", tmp_path / "refined"
    snapshot(source)
    trial.prepare(source, baseline)
    trial.prepare(source, refined, **kwargs)
    trial.verify(refined)
    addition = (trial.GUIDANCE.parent / filename).read_text()
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
