"""Assemble one run's workspace: the plain files the agent works in (T3 of the phase-2 spike).

brief.md, research/ (the account's written pages as plain markdown, no claim ids), seller/ (the
seller's files), catalog/ and brand/ (scripts/build-catalog.ts), skills/, and .run.json for the
validator. There is no page.json or shell.json yet: the agent writes both (the file tools refuse to
overwrite an existing file, so later changes are edits).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

AGENT_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = AGENT_DIR / "skills"


def _statements(items: Iterable[Any]) -> list[str]:
    lines = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        kind = item.get("kind")
        tag = f"({kind}) " if kind in ("inference", "quote") else ""
        lines.append(f"- {tag}{item['text']}")
    return lines


def _section_body(section: dict) -> dict | None:
    body = section.get("body_text")
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body) if isinstance(body, str) else None
    except json.JSONDecodeError:
        return None


def research_markdown(title: str, sections: list[dict]) -> str:
    """One research page (overview or insights) as markdown: headings and statements only."""
    out = [f"# {title}"]
    for section in sections:
        body = _section_body(section)
        if body is None:
            out += ["", f"## {section.get('section_key', 'Section')}", str(section.get("body_text", ""))]
            continue
        if body.get("restricted"):
            continue
        out += ["", f"## {body.get('h1') or section.get('section_key')}"]
        out += _statements(body.get("intro"))
        for item in body.get("items") or []:
            out += ["", f"### {item.get('h2', '')}".rstrip()]
            out += _statements(item.get("body"))
    return "\n".join(out).strip() + "\n"


def research_people(sections: list[dict]) -> list[str]:
    """Names of the people the research links to (its contact references)."""
    names: list[str] = []
    for section in sections:
        body = _section_body(section) or {}
        for item in body.get("items") or []:
            for ref in item.get("contactRefs") or []:
                name = (ref or {}).get("name")
                if name and name not in names:
                    names.append(name)
    return names


def read_research(reads: Any, account_entity_id: str, section: str) -> list[dict]:
    """Every block of one research page, following the paged contract."""
    blocks: list[dict] = []
    offset: int | None = 0
    while offset is not None:
        page = reads.read_account_research(
            account_entity_id=account_entity_id, section=section, offset=offset
        )
        blocks += page.get("overview") or page.get(section) or []
        offset = page.get("next_offset")
    return blocks


def write_seller_files(knowledge: Any, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    index = ["# The seller's files", ""]
    for doc in knowledge.documents:
        target = dest / doc.path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.body_text)
        mark = " (the confirmed ICP)" if doc.path == getattr(knowledge, "confirmed_icp_path", None) else ""
        index.append(f"- seller/{doc.path.lstrip('/')} ({doc.kind}, {len(doc.body_text)} characters){mark}")
    (dest / "index.md").write_text("\n".join(index) + "\n")
    return len(knowledge.documents)


def build_catalog(spike_root: Path, brand: str, dest: Path) -> None:
    subprocess.run(
        ["npx", "tsx", "scripts/build-catalog.ts", brand, str(dest)],
        cwd=spike_root, check=True, capture_output=True, text=True, timeout=180,
    )


def assemble(
    workspace: Path,
    *,
    spike_root: Path,
    brand: str,
    site: str,
    brief: str,
    account_name: str,
    overview: list[dict],
    insights: list[dict],
    knowledge: Any,
) -> dict:
    """Write the whole workspace. Returns a summary for the run record."""
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "brief.md").write_text(brief)
    research = workspace / "research"
    research.mkdir()
    if overview or insights:
        (research / "overview.md").write_text(research_markdown(f"{account_name}: overview", overview))
        (research / "insights.md").write_text(research_markdown(f"{account_name}: insights", insights))
    else:
        (research / "README.md").write_text(
            f"# {account_name}\n\nThere is no written research for this account yet.\n"
        )
    seller_files = write_seller_files(knowledge, workspace / "seller") if knowledge else 0
    build_catalog(spike_root, brand, workspace)
    shutil.copytree(SKILLS_DIR, workspace / "skills")
    (workspace / "fetched").mkdir()
    (workspace / ".run.json").write_text(json.dumps({"brand": brand, "site": site, "route": "/"}))
    return {
        "research_blocks": len(overview) + len(insights),
        "people_in_research": len(research_people(overview + insights)),
        "seller_files": seller_files,
        "clones": len(list((workspace / "catalog" / "clones").glob("*.md"))),
    }
