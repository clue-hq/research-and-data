"""M0.1 acceptance: the package topology exists and is correctly documented.

These assert the structural facts ENG-101 promises — every milestone has its reserved package,
each names its owning milestone, the `api/` placeholder exists, and the spec backlink target
resolves — so the layout can't silently drift.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "clue_research"

# package -> the milestone token its README must name
RESERVED: dict[str, str] = {
    "core": "M0.2",
    "config": "M0.4",
    "obs": "M0.5",
    "db": "M0.3",
    "claimstore": "M1",
    "identity": "M2",
    "icp": "M3",
    "sources": "M4",
    "resolvers": "M4",
    "adapters": "M4",
    "stage0": "M5",
    "discovery_scoring": "M6",
    "durable": "M7",
    "profiling": "M8",
    "verification": "M9",
    "compliance": "M10",
    "synthesis": "M11",
    "narrative": "M12",
    "review": "M13",
}

# Every future milestone M1..M13 must have exactly its reserved layer package(s).
MILESTONE_PACKAGES: dict[str, list[str]] = {
    "M1": ["claimstore"],
    "M2": ["identity"],
    "M3": ["icp"],
    "M4": ["sources", "resolvers", "adapters"],
    "M5": ["stage0"],
    "M6": ["discovery_scoring"],
    "M7": ["durable"],
    "M8": ["profiling"],
    "M9": ["verification"],
    "M10": ["compliance"],
    "M11": ["synthesis"],
    "M12": ["narrative"],
    "M13": ["review"],
}


def test_every_package_is_importable_with_readme() -> None:
    for name in (*RESERVED, "api"):
        pkg = PKG / name
        assert (pkg / "__init__.py").is_file(), f"{name}/ missing __init__.py"
        assert (pkg / "README.md").is_file(), f"{name}/ missing README.md"


def test_each_readme_names_its_owning_milestone() -> None:
    for name, token in RESERVED.items():
        text = (PKG / name / "README.md").read_text()
        assert token in text, f"{name}/README.md does not name its milestone ({token})"


def test_every_milestone_has_its_reserved_package() -> None:
    for milestone, packages in MILESTONE_PACKAGES.items():
        for pkg in packages:
            assert (PKG / pkg).is_dir(), f"{milestone}: reserved package {pkg}/ missing"


def test_api_placeholder_exists() -> None:
    assert (PKG / "api" / "__init__.py").is_file()


def test_umbrella_package_marks_typed() -> None:
    assert (PKG / "__init__.py").is_file()
    assert (PKG / "py.typed").is_file(), "PEP 561 marker missing — downstream loses core/ types"


def test_specs_location_and_backlink_target_resolve() -> None:
    specs = REPO / "docs" / "specs"
    assert specs.is_dir(), "docs/specs/ missing"
    assert (specs / "M00-foundations-and-shared-contracts.md").is_file(), (
        "M0.1 spec backlink target does not resolve"
    )
