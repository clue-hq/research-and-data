"""The footprint package holds media and social code that knows nothing about a research job."""

import ast
import importlib
from pathlib import Path

import pytest

FOOTPRINT = Path(__file__).resolve().parents[2] / "platform" / "api" / "clue_api" / "footprint"

MOVED = (
    "media_types",
    "media_recording",
    "media_feeds_client",
    "media_sources",
    "media_resolution",
    "deepgram_media_client",
    "gemini_media_client",
    "media_telemetry",
    "openrouter",
    "text",
)


def test_footprint_imports_nothing_from_arv2():
    offenders = []
    for path in FOOTPRINT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            offenders += [f"{path.name}: {n}" for n in names if n.startswith("clue_api.arv2")]
    assert offenders == []


@pytest.mark.parametrize("name", MOVED)
def test_old_paths_are_the_same_module(name):
    old = importlib.import_module(f"clue_api.arv2.{name}")
    new = importlib.import_module(f"clue_api.footprint.{name}")
    assert old is new
