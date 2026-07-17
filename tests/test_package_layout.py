"""M0.1 acceptance: the package topology exists and is correctly documented.

These assert the structural facts ENG-101 promises — every milestone has its reserved package,
each names its owning milestone, the `api/` placeholder exists, and the spec backlink target
resolves — so the layout can't silently drift.

Doc R (Phase A) makes the topology two-homed: shared-base packages are progressively PROMOTED
out of ``src/clue_research`` into uv-workspace libs (``libs/clue-<name>/clue_<name>``); milestone
worker packages stay in the subsystem. ``_locate`` resolves a package's current home so the
structure facts keep holding across the moves (the legacy ``obs`` OTel skeleton folds into
``clue_obs.otel``).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "clue_research"
LIBS = REPO / "libs"

# package -> the milestone token its README must name
RESERVED: dict[str, str] = {
    "core": "M0.2",
    "config": "M0.4",
    "gateway": "M0.4",  # the LLM-gateway client (the model-egress seam; owned by M0.4)
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

# Promoted homes that don't follow the mechanical name mapping.
_SPECIAL_HOMES = {
    "obs": LIBS / "clue-obs" / "clue_obs" / "otel",  # folds into clue-obs at A2/R1
}


def _locate(name: str) -> Path:
    """A package's current home: subsystem tree first, then its promoted lib home."""
    in_subsystem = PKG / name
    if in_subsystem.is_dir():
        return in_subsystem
    special = _SPECIAL_HOMES.get(name)
    if special is not None and special.is_dir():
        return special
    return LIBS / f"clue-{name}" / f"clue_{name}"


def test_every_package_is_importable_with_readme() -> None:
    for name in (*RESERVED, "api"):
        pkg = _locate(name)
        assert (pkg / "__init__.py").is_file(), f"{name}/ missing __init__.py (at {pkg})"
        assert (pkg / "README.md").is_file(), f"{name}/ missing README.md (at {pkg})"


def test_each_readme_names_its_owning_milestone() -> None:
    for name, token in RESERVED.items():
        text = (_locate(name) / "README.md").read_text()
        assert token in text, f"{name}/README.md does not name its milestone ({token})"


def test_every_milestone_has_its_reserved_package() -> None:
    for milestone, packages in MILESTONE_PACKAGES.items():
        for pkg in packages:
            assert _locate(pkg).is_dir(), f"{milestone}: reserved package {pkg}/ missing"


def test_api_placeholder_exists() -> None:
    assert (_locate("api") / "__init__.py").is_file()


def test_umbrella_package_marks_typed() -> None:
    assert (PKG / "__init__.py").is_file()
    assert (PKG / "py.typed").is_file(), "PEP 561 marker missing — downstream loses core/ types"


def test_promoted_libs_mark_typed() -> None:
    """Each promoted lib ships its own PEP 561 marker (the umbrella one no longer covers it)."""
    for lib_dir in LIBS.iterdir():
        pkg_name = lib_dir.name.replace("-", "_")
        pkg = lib_dir / pkg_name
        if pkg.is_dir():
            assert (pkg / "py.typed").is_file(), f"{lib_dir.name} missing py.typed"


def test_specs_location_and_backlink_target_resolve() -> None:
    specs = REPO / "docs" / "specs"
    assert specs.is_dir(), "docs/specs/ missing"
    assert (specs / "M00-foundations-and-shared-contracts.md").is_file(), (
        "M0.1 spec backlink target does not resolve"
    )
