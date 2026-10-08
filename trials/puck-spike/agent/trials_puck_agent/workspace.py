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


def build_catalog(spike_root: Path, brand: str, dest: Path, seller: str) -> None:
    subprocess.run(
        ["npx", "tsx", "scripts/build-catalog.ts", brand, str(dest), seller],
        cwd=spike_root, check=True, capture_output=True, text=True, timeout=180,
    )


def assemble(
    workspace: Path,
    *,
    spike_root: Path,
    brand: str,
    seller: str,
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
    build_catalog(spike_root, brand, workspace, seller)
    shutil.copytree(SKILLS_DIR, workspace / "skills")
    (workspace / "fetched").mkdir()
    (workspace / ".run.json").write_text(json.dumps({"brand": brand, "site": site, "route": "/"}))
    return {
        "research_blocks": len(overview) + len(insights),
        "people_in_research": len(research_people(overview + insights)),
        "seller_files": seller_files,
        "clones": len(list((workspace / "catalog" / "clones").glob("*.md"))),
    }


# --- memory for a fresh session: written by code, read by the agent ---------------------------------

def _site_pages(workspace: Path) -> dict[str, dict]:
    pages = {"/": json.loads((workspace / "page.json").read_text())} if (workspace / "page.json").exists() else {}
    for file in sorted((workspace / "pages").glob("*.json")) if (workspace / "pages").exists() else []:
        pages[f"/{file.stem}"] = json.loads(file.read_text())
    return pages


def _short(text: object, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def site_summary(workspace: Path, spike_root: Path) -> str:
    """site.md: what is on every page now, in a few lines per section."""
    brand = json.loads((workspace / ".run.json").read_text())["brand"]
    data = spike_root / "data" / "brands" / brand
    clones = {c["id"]: c for c in json.loads((data / "clones.json").read_text())}
    described = {a["file"]: a.get("description") or "" for a in json.loads((data / "assets.json").read_text()).values()}

    def image(file: object) -> str:
        return f"{file}" + (f" ({_short(described.get(str(file), ''), 120)})" if described.get(str(file)) else "")

    out = ["# The site as it is now", "",
           "Written for you at the start of this request. The page files are the truth; this is a summary.", ""]
    if (workspace / "shell.json").exists():
        shell = json.loads((workspace / "shell.json").read_text())
        header = shell.get("header", {})
        nav = ", ".join(f"{n.get('label')} → {n.get('href')}" for n in header.get("nav") or []) or "none"
        out += ["## Header and footer",
                f"- Prepared for: {header.get('preparedFor')}; button \"{header.get('ctaLabel')}\" → {header.get('ctaHref')}",
                f"- Nav links: {nav}", f"- Footer: {_short(shell.get('footer', {}).get('legal', ''))}", ""]
    for route, page in _site_pages(workspace).items():
        file = "page.json" if route == "/" else f"pages/{route[1:]}.json"
        out += [f"## {route} ({file})"]
        for n, item in enumerate(page.get("content") or [], 1):
            props = item.get("props", {})
            if item.get("type") == "ClonedSection":
                clone = clones.get(props.get("fragmentId"), {})
                out.append(f"{n}. {props.get('id')}: the seller's section \"{_short(clone.get('label', ''), 70)}\" ({props.get('fragmentId')})")
                slots = props.get("slots") or {}
                for key, slot in (clone.get("slots") or {}).items():
                    value = slots.get(key)
                    if slot.get("kind") == "text" and value not in (None, "", slot.get("fallback")):
                        out.append(f"   - {key}: \"{_short(value)}\"")
                    elif slot.get("kind") == "image" and value:
                        out.append(f"   - {key}: {image(value)}")
                    elif slot.get("kind") == "href" and value:
                        out.append(f"   - {key} → {value}")
                    elif slot.get("kind") == "visibility" and value is False:
                        out.append("   - hidden")
                for r in props.get("replacements") or []:
                    out.append(f"   - \"{_short(r.get('find'), 60)}\" now reads \"{_short(r.get('replace'), 80)}\"")
                for link in props.get("links") or []:
                    out.append(f"   - link {link.get('find')} → {link.get('replace')}")
            else:
                out.append(f"{n}. {props.get('id')}: {item.get('type')} on the {props.get('surface')} surface")
                for key in ("eyebrow", "kicker", "heading", "metric", "metricLabel", "intro", "body", "source"):
                    if props.get(key):
                        out.append(f"   - {key}: \"{_short(props[key])}\"")
                for stat in props.get("stats") or []:
                    out.append(f"   - stat: {stat.get('value')} {_short(stat.get('label', ''), 80)}")
                if props.get("image"):
                    out.append(f"   - image: {image(props['image'])}")
                if props.get("buttonLabel"):
                    out.append(f"   - button \"{props['buttonLabel']}\" → {props.get('buttonHref')}")
                if props.get("linkLabel"):
                    out.append(f"   - link \"{props['linkLabel']}\" → {props.get('linkHref')}")
        out.append("")
    return "\n".join(out)


def site_changes(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """What changed between two snapshots of the pages, in plain words."""
    notes = []
    for route in after:
        if route not in before:
            notes.append(f"added the page {route}")
            continue
        old = {i["props"].get("id"): i for i in before[route].get("content") or []}
        new = {i["props"].get("id"): i for i in after[route].get("content") or []}
        for sid in new:
            if sid not in old:
                notes.append(f"{route}: added the section {sid} ({new[sid].get('type')})")
            elif old[sid] != new[sid]:
                fields = sorted(k for k in set(old[sid]["props"]) | set(new[sid]["props"])
                                if old[sid]["props"].get(k) != new[sid]["props"].get(k))
                notes.append(f"{route}: changed {sid} ({', '.join(fields)})")
        notes += [f"{route}: removed the section {sid}" for sid in old if sid not in new]
        kept_old = [s for s in old if s in new]
        kept_new = [s for s in new if s in old]
        if kept_old != kept_new:
            notes.append(f"{route}: new order {', '.join(new)}")
    notes += [f"removed the page {route}" for route in before if route not in after]
    return notes


def append_history(workspace: Path, number: int, request: str, changes: list[str], shell_changed: bool, reply: str | None) -> None:
    path = workspace / "history.md"
    text = path.read_text() if path.exists() else "# Earlier requests in this project\n\nOldest first. Written after each request.\n"
    what = "; ".join(changes + (["changed the header or footer"] if shell_changed else [])) or "nothing changed"
    text += f"\n## {number}. {request}\n- What changed: {what}\n- The reply: {_short(reply or '', 500)}\n"
    path.write_text(text)


# --- references for writing a new section (E5, option C) -------------------------------------------

THEME_HEADER = """/* The brand's classes: the real mapping from the app's theme (app/globals.css, @theme).
   Each variable below is a class you can use; the brand decides its value at runtime.
   --color-ink-secondary   -> text-ink-secondary, bg-ink-secondary, border-ink-secondary
   --color-surface-muted   -> bg-surface-muted (and text-, border-)
   --color-line-subtle     -> border-line-subtle (and text-, bg-)
   --font-title            -> font-title (the role's font family)
   --text-title            -> text-title (the role's size, line height, weight and tracking)
   --radius-card           -> rounded-card
*/
"""


def write_section_references(workspace: Path, spike_root: Path) -> None:
    """brand/theme.css (the theme's class-to-token mapping) and brand/agent-kit.tsx (the kit's source)."""
    css = (spike_root / "app" / "globals.css").read_text()
    start = css.index("@theme inline")
    depth, end = 0, start
    for index in range(css.index("{", start), len(css)):
        depth += {"{": 1, "}": -1}.get(css[index], 0)
        if depth == 0:
            end = index + 1
            break
    (workspace / "brand").mkdir(exist_ok=True)
    (workspace / "brand" / "theme.css").write_text(THEME_HEADER + css[start:end] + "\n")
    shutil.copy2(spike_root / "puck" / "agent-kit.tsx", workspace / "brand" / "agent-kit.tsx")
