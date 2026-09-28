"""The Head of ABM's operating manual: the generated chapters, rendered from the code.

A chapter is an ordinary catalog skill (``manual-<chapter>``), so the profile pins it like any
skill and the generated capability map already discloses it with its summary and its materialized
path. Nothing here grants anything: the profile, the recipe and the toolbelt decide what the agent
may do, and the manual only describes it.

Four chapters are generated (``tools``, ``fields``, ``errors``, ``limits``); the rest are
hand-written. The rendering lives here; the entry point that composes the live toolbelt lives at
``clue_api.manual_build``, because the agents package may not import the composition root.
"""

from clue_agents.manual.build import (
    DEFAULT_CATALOG_ROOT,
    GENERATED_CHAPTERS,
    MANUAL_VERSION,
    Chapter,
    CodeFacts,
    ManualBuildError,
    build_chapter_objects,
    build_chapters,
    build_errors_chapter,
    build_fields_chapter,
    build_limits_chapter,
    build_tools_chapter,
    chapter_path,
    load_fields,
    load_notes,
    load_profile,
    materialized_links,
    render_skill,
    run,
    tool_manual_link,
)

__all__ = [
    "DEFAULT_CATALOG_ROOT",
    "GENERATED_CHAPTERS",
    "MANUAL_VERSION",
    "Chapter",
    "CodeFacts",
    "ManualBuildError",
    "build_chapter_objects",
    "build_chapters",
    "build_errors_chapter",
    "build_fields_chapter",
    "build_limits_chapter",
    "build_tools_chapter",
    "chapter_path",
    "load_fields",
    "load_notes",
    "load_profile",
    "materialized_links",
    "render_skill",
    "run",
    "tool_manual_link",
]
