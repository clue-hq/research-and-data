"""The site agent's workspace: the plain files it works in, written by code (Lane B).

Ported from the Puck spike (`trials/puck-spike/agent/trials_puck_agent/workspace.py`). The research
markdown, claim labels, claims file, site summary, change notes and history are the spike's
functions; what changed is where the inputs come from (by value, from the design API — this module
never reads a database) and that every image is `/asset-store/<sha256>`.

Under the session folder's `workspace/`:
- brief.md, research/, seller/, project-context/, catalog/, brand/brand.md, skills/, skills-e5/,
  skills-live/ (a live workspace only): rebuilt for every request, never restored from the session
  snapshot;
- page.json, pages/<name>.json, shell.json: the stored site, written at the start of a request and
  read back at its end;
- site.md: written by code at the start of a request when the site has content;
- plan.md, history.md, fetched/: the agent's memory across requests, synced with the session.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .inputs import AccountLogo, AttachedImage, SiteSection, SiteTurnInputs

SITE_DIR = Path(__file__).resolve().parent

#: Rebuilt from the database at the start of every request.
REGENERATED = (
    "brief.md", "site.md", "research", "catalog", "brand", "project-context", "skills",
    "skills-e5", "skills-live", "page.json", "pages", "shell.json", "attachments",
)
#: Left out of the session snapshot: everything rebuilt per request, plus `seller/` (rewritten per
#: pin by `write_seller_knowledge`), `work/` (one request's compaction offloads) and
#: `large_tool_results/` (deepagents' one-request offloads of large tool results).
SESSION_REGENERATED = frozenset({*REGENERATED, "seller", "work", "large_tool_results"})
#: Left out of a running turn's working copy (site-turn durability, 2026-10-16): the inputs rebuilt
#: for every request. The site files are rebuilt too, but they are the turn's work, so they travel;
#: so do plan.md, history.md, fetched/, and the offloads the conversation may refer to later
#: (large_tool_results/, work/conversation_history/).
WORKING_COPY_EXCLUDED = frozenset({*REGENERATED, "seller"} - {"page.json", "pages", "shell.json"})
#: The working copy's budget. Over it, large_tool_results/ entries are dropped oldest first.
WORKING_COPY_MAX_BYTES = 20 * 1024 * 1024
_SITE_FILES = ("page.json", "shell.json")
#: The display gate's real rules (read_cited_claims@1). A research statement citing a claim held
#: for one of these leaves the research files; one citing an unverified finding or another
#: entity's claim stays (the spike's rule, `run_agent.py:93-94`).
REAL_HOLD_REASONS = frozenset({"sensitive", "unverified", "outreach_unsafe"})
_AUTHORS = {"agent": "the agent", "human": "a person", "system": "an undo or redo"}
_COMPONENTS_HEADER = (
    "# The seller's components on this site\n\n"
    "Written for you as each one is written. Use them like any section.\n"
)


def _claim_ids(item: dict) -> list[str]:
    return [str(i) for i in item.get("claimIds") or item.get("claim_ids") or []]


def _statements(
    items: Iterable[Any], labels: dict[str, str] | None = None, held: set[str] | None = None
) -> list[str]:
    lines = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        if held and held.intersection(_claim_ids(item)):
            continue  # it rests on a claim held back by a real rule (a reputation risk, a biography)
        kind = item.get("kind")
        tag = f"({kind}) " if kind in ("inference", "quote", "qualified", "gap") else ""
        notes = [str(n) for n in item.get("qualifications") or [] if n]
        note = f" (note: {'; '.join(notes)})" if notes else ""
        refs = [labels[i] for i in _claim_ids(item) if labels and i in labels]
        lines.append(f"- {tag}{item['text']}{note}" + (f" [{', '.join(refs)}]" if refs else ""))
    return lines


def _section_body(section: dict) -> dict | None:
    body = section.get("body_text")
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body) if isinstance(body, str) else None
    except json.JSONDecodeError:
        return None


def research_markdown(
    title: str, sections: list[dict], labels: dict[str, str] | None = None, held: set[str] | None = None
) -> str:
    """One research page (overview or insights) as markdown: headings and statements, each statement
    with its type and notes, and ending with the short labels of its claims when `labels` is given
    (never the claim ids). Sections held back from outreach (Watch-outs, Context only) are kept and
    marked as background, never words for the page. A statement citing a claim in `held` is left out."""
    out = [f"# {title}"]
    for section in sections:
        body = _section_body(section)
        if body is None:
            out += ["", f"## {section.get('section_key', 'Section')}", str(section.get("body_text", ""))]
            continue
        heading = body.get("h1") or section.get("section_key")
        if body.get("restricted"):
            heading = f"{heading} (background only, never on the page)"
        out += ["", f"## {heading}"]
        out += _statements(body.get("intro"), labels, held)
        for item in body.get("items") or []:
            out += ["", f"### {item.get('h2', '')}".rstrip()]
            out += _statements(item.get("body"), labels, held)
    return "\n".join(out).strip() + "\n"


def _section_statements(section: dict) -> list[dict]:
    body = _section_body(section)
    if body is None:
        return []
    statements = list(body.get("intro") or [])
    for item in body.get("items") or []:
        statements += item.get("body") or []
    return [s for s in statements if isinstance(s, dict)]


def cited_claim_ids(sections: list[dict]) -> list[str]:
    """Every claim the research statements cite, held-back sections included, in first-seen order."""
    ids: list[str] = []
    for section in sections:
        for statement in _section_statements(section):
            ids += [i for i in _claim_ids(statement) if i not in ids]
    return ids


def claim_labels(sections: list[dict], served: set[str]) -> dict[str, str]:
    """c1, c2, … for every claim a visible statement cites, in the order they first appear. A claim
    the read did not serve (held back by the display gate) gets no label, so no label dangles."""
    labels: dict[str, str] = {}
    for claim_id in cited_claim_ids(sections):
        if claim_id in served:
            labels[claim_id] = f"c{len(labels) + 1}"
    return labels


def _plain(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_plain(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(_plain(v) for v in value)
    return " ".join(str(value).split())


def _claim_lines(claim: dict) -> list[str]:
    """What one claim says, in plain lines. A research finding says its finding (with its topic and
    notes); a value narrative says its argument (with the persona and angle it is for)."""
    value = claim.get("value")
    if not isinstance(value, dict):
        return [f"Says: {_plain(value)}"]
    if "finding" in value:
        lines = [f"Says: {_plain(value['finding'])}"]
        if value.get("topic"):
            lines.append(f"Topic: {_plain(value['topic'])}")
        if value.get("notes"):
            lines.append(f"Notes: {_plain(value['notes'])}")
        return lines
    if "argument" in value:
        lines = [f"Says: {_plain(value['argument'])}"]
        lines += [f"{label}: {_plain(value[key])}" for key, label in (("persona", "For"), ("angle_label", "Angle"))
                  if value.get(key)]
        return lines
    return [f"Says: {_plain(value)}"]


def claims_markdown(account_name: str, labels: dict[str, str], claims: list[dict]) -> str:
    """research/claims.md: each label's claim with what it says, its source link and any notes."""
    by_id = {str(c.get("claim_id")): c for c in claims}
    out = [f"# {account_name}: the claims behind the research", "",
           "Each label in the research files (like [c4]) is one claim below: what it says, its source link,",
           "and any notes. A shortened quote is only the opening of the source's words."]
    for claim_id, label in labels.items():
        claim = by_id[claim_id]
        out += ["", f"## {label}", *_claim_lines(claim)]
        if claim.get("source_url"):
            out.append(f"Source: {claim['source_url']}")
        if claim.get("evidence"):
            mark = " (shortened)" if claim.get("evidence_truncated") else ""
            out.append(f"Quote{mark}: “{' '.join(str(claim['evidence']).split())}”")
    return "\n".join(out) + "\n"


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


LOGO_CELLS = {
    "light_lockup": "the full logo, for light backgrounds",
    "dark_lockup": "the full logo, for dark backgrounds",
    "light_mark": "the symbol only, for light backgrounds",
    "dark_mark": "the symbol only, for dark backgrounds",
}


def _short(text: object, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def held_claim_ids(dispositions: Mapping[str, str]) -> set[str]:
    """The cited ids held back by a real rule, from read_cited_claims@1's dispositions."""

    return {
        claim_id
        for claim_id, disposition in dispositions.items()
        if disposition.startswith("held:") and disposition.removeprefix("held:") in REAL_HOLD_REASONS
    }


def account_logo_section(logos: Sequence[AccountLogo]) -> str:
    """brand.md's account-logo section: the recommended logos first, then the alternatives (the
    spike's text; files are now /asset-store/<sha256>)."""

    out = ["", "## The account's logo (header only)", ""]
    if not logos:
        return "\n".join(out + ["None was found. Leave `accountLogo` empty.", ""])
    recommended = [logo for logo in logos if not logo.alternative]
    others = [logo for logo in logos if logo.alternative]
    for logo in recommended:
        out.append(f"- `{logo.file}`: {LOGO_CELLS.get(logo.cell, logo.cell)}")
    if others:
        out += ["", "Other logos found for the account. Use one only when none of the above fits the header:"]
        for logo in others:
            out.append(f"- `{logo.file}`: {logo.label or 'another logo of the account'}")
    return "\n".join(out + [""])


def turn_brand(
    brand: Mapping[str, Any], logos: Sequence[AccountLogo], attached: Sequence[AttachedImage] = ()
) -> dict:
    """The brand the turn validates with: the stored brand plus this request's account logos and
    the images sent in the chat."""

    merged = copy.deepcopy(dict(brand))
    assets = merged.setdefault("assets", {})
    for number, logo in enumerate(logos):
        assets[f"account_logo_{number}"] = {
            "kind": "account_logo", "label": logo.label,
            "description": logo.label or LOGO_CELLS.get(logo.cell, logo.cell),
            "mime": logo.content_type, "file": logo.file, "logo": None,
        }
    for image in attached:
        assets[image.asset_id] = {
            "kind": "attached_image", "label": image.filename,
            "description": f"attached in chat: {image.filename}",
            "mime": image.content_type, "file": image.file, "logo": None,
        }
    return merged


def attached_images_section(images: Sequence[AttachedImage]) -> str:
    """brand/brand.md's list of the images sent in the chat, by the file a page places."""

    if not images:
        return ""
    out = ["", "## Images attached in this chat", ""]
    for image in sorted(images, key=lambda item: not item.current):
        when = "with this message" if image.current else "earlier in this chat"
        out.append(f"- `{image.file}`: {image.filename} (sent {when})")
    return "\n".join(out + [""])


def site_pages_of(site: Mapping[str, Any]) -> dict[str, dict]:
    """A stored site's pages by route ("/" is the home page)."""

    return {route: page for route, page in (site.get("pages") or {}).items() if isinstance(page, dict)}


_SHELL_PARTS = ("header", "footer")


def shell_entry(shell: Any, part: str) -> dict | None:
    """The header's or footer's entry when it is a section (plan 6: ``{"type", "props"}``); an old-shape
    part (fixed props) is no section and reads as None."""

    entry = shell.get(part) if isinstance(shell, Mapping) else None
    if isinstance(entry, dict) and isinstance(entry.get("type"), str) and isinstance(entry.get("props"), dict):
        return entry
    return None


def site_components(site: Mapping[str, Any]) -> Iterator[tuple[str, dict]]:
    """Every section of a stored site, the one walk the API and the agent use: ``(route, item)`` for
    each page item in page order, then ``("shell", entry)`` for the header and the footer."""

    for route, page in site_pages_of(site).items():
        for item in page.get("content") or []:
            if isinstance(item, dict):
                yield route, item
    for part in _SHELL_PARTS:
        entry = shell_entry(site.get("shell"), part)
        if entry is not None:
            yield "shell", entry


def site_pages(workspace: Path) -> dict[str, dict]:
    """The workspace's pages by route: page.json is "/", pages/<name>.json is "/<name>"."""

    pages = {"/": json.loads((workspace / "page.json").read_text())} if (workspace / "page.json").exists() else {}
    folder = workspace / "pages"
    for file in sorted(folder.glob("*.json")) if folder.exists() else []:
        pages[f"/{file.stem}"] = json.loads(file.read_text())
    return pages


def write_site_files(workspace: Path, site: Mapping[str, Any]) -> None:
    """Write a stored site as the agent's files, replacing whatever site files were there."""

    for name in ("page.json", "shell.json"):
        (workspace / name).unlink(missing_ok=True)
    shutil.rmtree(workspace / "pages", ignore_errors=True)
    for route, page in site_pages_of(site).items():
        if route == "/":
            target = workspace / "page.json"
        else:
            target = workspace / "pages" / f"{route.strip('/')}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(page, indent=2))
    if site.get("shell") is not None:
        (workspace / "shell.json").write_text(json.dumps(site["shell"], indent=2))


def read_site_files(
    workspace: Path, base: Mapping[str, Any], sections: Mapping[str, SiteSection]
) -> dict:
    """The site as the agent left it: ``base``'s id, title and theme, the workspace's pages and
    shell, and ``agent_sections`` = the sections its pages place (Contract 1)."""

    pages = site_pages(workspace)
    if "/" not in pages:
        pages = {**site_pages_of(base), **pages}
    shell_file = workspace / "shell.json"
    shell = json.loads(shell_file.read_text()) if shell_file.exists() else base.get("shell")
    used = {str(item.get("type")) for _route, item in site_components({"pages": pages, "shell": shell})}
    return {
        **dict(base),
        "pages": pages,
        "shell": shell,
        "agent_sections": {name: sections[name].digest for name in sorted(used) if name in sections},
    }


def collect_working_copy(workspace: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The turn's working copy: ``{relative path: text}`` for every file outside
    :data:`WORKING_COPY_EXCLUDED`, and notes ``{"skipped": [...], "dropped": [...]}``.

    Symlinks and files that are not UTF-8 text are skipped (a link names a path on this host; the
    copy is text). Over :data:`WORKING_COPY_MAX_BYTES`, ``large_tool_results/`` entries are dropped
    oldest first; whatever was dropped or skipped is named, never silently lost."""

    files: dict[str, str] = {}
    mtimes: dict[str, float] = {}
    skipped: list[str] = []
    root = Path(workspace)
    if not root.is_dir():
        return files, {"skipped": skipped, "dropped": []}
    for directory, folders, names in os.walk(root, followlinks=False):
        here = Path(directory)
        if here == root:
            folders[:] = [f for f in folders if f not in WORKING_COPY_EXCLUDED]
            names = [n for n in names if n not in WORKING_COPY_EXCLUDED]
        for folder in list(folders):
            if (here / folder).is_symlink():
                skipped.append((here / folder).relative_to(root).as_posix())
                folders.remove(folder)
        for name in sorted(names):
            path = here / name
            key = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                skipped.append(key)
                continue
            try:
                files[key] = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                skipped.append(key)
                continue
            mtimes[key] = path.stat().st_mtime
    dropped: list[str] = []
    total = sum(len(text.encode("utf-8")) for text in files.values())
    offloads = sorted((k for k in files if k.startswith("large_tool_results/")), key=lambda k: (mtimes[k], k))
    for key in offloads:
        if total <= WORKING_COPY_MAX_BYTES:
            break
        total -= len(files.pop(key).encode("utf-8"))
        dropped.append(key)
    return files, {"skipped": sorted(skipped), "dropped": dropped}


def working_copy_digest(files: Mapping[str, str]) -> str:
    """The sha256 of a working copy's files (paths and text)."""

    return hashlib.sha256(json.dumps(dict(files), sort_keys=True).encode("utf-8")).hexdigest()


def overlay_working_copy(workspace: Path, files: Mapping[str, str]) -> None:
    """Lay a working copy over a freshly materialized workspace. The site files end up exactly as
    the copy has them (a page the turn removed stays removed); every other file is written over."""

    for name in _SITE_FILES:
        (workspace / name).unlink(missing_ok=True)
    shutil.rmtree(workspace / "pages", ignore_errors=True)
    root = workspace.resolve()
    for key, text in files.items():
        target = workspace / key
        if not target.resolve().is_relative_to(root) or Path(key).parts[0] in WORKING_COPY_EXCLUDED:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def _when(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value or "")


_WEIGHT_NAMES = {100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular", 500: "Medium",
                 600: "Semi Bold", 700: "Bold", 800: "Extra Bold", 900: "Black"}
_ALIGN_WORDS = {"left": "left-aligned", "center": "centred", "right": "right-aligned",
                "justify": "justified"}
_CONTENT_TO = {"start": "to the start", "center": "centred", "end": "to the end"}
_CONTENT_ALONG = {"row": "along the row", "stack": "in the stack", "grid": "in the grid"}


class _RichReader(HTMLParser):
    """Rich text (site element inspector, plan 2) as its words, with each bold / italic / underlined
    / struck run, link and styled span noted once, in reading order."""

    _MARKS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic", "u": "underlined", "s": "struck"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.words: list[str] = []
        self.open: list[tuple[str, str, int]] = []  # (tag, note template, start in words)
        self.notes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "br":
            self.words.append(" ")
            return
        if tag == "a":
            tab = ", new tab" if "data-new-tab" in values else ""
            self.open.append((tag, f'link "{{}}" → {values.get("href") or ""}{tab}', len(self.words)))
        elif tag == "span" and values.get("data-s"):
            self.open.append((tag, f'"{{}}" styled by hand as {values["data-s"]}', len(self.words)))
        elif tag in self._MARKS:
            self.open.append((tag, f'{self._MARKS[tag]} "{{}}"', len(self.words)))
        else:
            self.open.append((tag, "", len(self.words)))

    def handle_endtag(self, tag: str) -> None:
        for at in range(len(self.open) - 1, -1, -1):
            if self.open[at][0] == tag:
                _tag, note, start = self.open.pop(at)
                text = re.sub(r"\s+", " ", "".join(self.words[start:])).strip()
                if note and text:
                    self.notes.append(note.format(_short(text, 60)))
                return

    def handle_data(self, data: str) -> None:
        self.words.append(data)


def _rich_words(value: object) -> str:
    """A text value as site.md shows it: its words in quotes, and for rich text what is bold, linked
    or styled by hand, in brackets."""
    text = str(value)
    if not re.search(r"[<&]", text):
        return f'"{_short(text)}"'
    reader = _RichReader()
    reader.feed(text)
    reader.close()
    words = re.sub(r"\s+", " ", "".join(reader.words)).strip()
    return f'"{_short(words)}"' + (f" ({'; '.join(reader.notes)})" if reader.notes else "")


def _styled_by_hand(edits: object) -> list[str]:
    """A section's (or the shell part's) `_edits` in plain words, one entry per element: what the
    person styled by hand in the editor's inspector (site element inspector, plan 1)."""
    if not isinstance(edits, Mapping):
        return []
    out = []
    for key, override in edits.items():
        if not isinstance(override, Mapping):
            continue
        words = []
        color = override.get("color")
        if isinstance(color, Mapping) and color.get("token"):
            words.append(f"colour {color['token']}")
        elif isinstance(color, Mapping) and color.get("hex"):
            words.append(f"colour {color['hex']} {color.get('opacity', 100)}%")
        if override.get("fontFamily"):
            words.append(str(override["fontFamily"]))
        if override.get("fontSize") is not None:
            words.append(f"{override['fontSize']:g} px")
        if override.get("fontWeight") is not None:
            weight = override["fontWeight"]
            words.append(_WEIGHT_NAMES.get(weight, f"weight {weight}"))
        if override.get("italic") is not None:
            words.append("italic" if override["italic"] else "not italic")
        if override.get("underline") is not None:
            words.append("underlined" if override["underline"] else "not underlined")
        if override.get("textAlign"):
            words.append(_ALIGN_WORDS.get(override["textAlign"], str(override["textAlign"])))
        # Plan 3 (buttons): the box itself.
        for prop, label in (("fill", "fill"), ("borderColor", "stroke colour")):
            value = override.get(prop)
            if isinstance(value, Mapping) and value.get("token"):
                words.append(f"{label} {value['token']}")
            elif isinstance(value, Mapping) and value.get("hex"):
                words.append(f"{label} {value['hex']} {value.get('opacity', 100)}%")
        if override.get("borderWidth") is not None:
            words.append(f"stroke {override['borderWidth']:g} px")
        radius = override.get("radius")
        if radius == "pill":
            words.append("corners pill")
        elif isinstance(radius, (int, float)):
            words.append(f"corners {radius:g} px")
        elif isinstance(radius, list):
            words.append("corners " + " / ".join(f"{corner:g}" for corner in radius) + " px")
        padding = override.get("padding")
        if isinstance(padding, (int, float)):
            words.append(f"padding {padding:g} px")
        elif isinstance(padding, Mapping):
            y, x = padding.get("y"), padding.get("x")
            if y is not None and x is not None:
                words.append(f"padding {y:g} × {x:g} px")
            elif y is not None:
                words.append(f"padding {y:g} px top and bottom")
            elif x is not None:
                words.append(f"padding {x:g} px left and right")
        width = override.get("width")
        if width == "fill":
            words.append("full width")
        elif width == "fit":
            words.append("as wide as its words")
        elif isinstance(width, (int, float)):
            words.append(f"{width:g} px wide")
        # Plan 4 (boxes): spacing, how the contents line up, the children's order, a hidden part.
        if override.get("gap") is not None:
            words.append(f"gap {override['gap']:g} px")
        align = override.get("contentAlign")
        if isinstance(align, Mapping):
            to, along = align.get("to"), align.get("along")
            if along == "text":
                words.append("text " + _ALIGN_WORDS.get({"start": "left", "end": "right"}.get(to, to), str(to)))
            else:
                words.append(f"contents {_CONTENT_TO.get(to, str(to))} {_CONTENT_ALONG.get(along, str(along))}")
        order = override.get("order")
        if isinstance(order, list) and order:
            words.append("children in the order " + ", ".join(str(child) for child in order))
        if override.get("hidden") is True:
            words.append("hidden")
        # Plan 5 (images).
        if override.get("imageFit") == "fill":
            words.append("image fills its box")
        elif override.get("imageFit") == "fit":
            words.append("image fits inside its box")
        if words:
            out.append(f"{key} — {', '.join(words)}")
    return out


def site_summary(
    workspace: Path, brand: Mapping[str, Any], versions: Sequence[Mapping[str, Any]] | None = None
) -> str:
    """site.md: what is on every page now, in a few lines per section, and the saved versions."""

    clones = brand.get("clones") or {}
    described = {
        asset["file"]: asset.get("description") or ""
        for asset in (brand.get("assets") or {}).values()
        if isinstance(asset, dict) and asset.get("file")
    }

    def image(file: object) -> str:
        return f"{file}" + (f" ({_short(described.get(str(file), ''), 120)})" if described.get(str(file)) else "")

    out = ["# The site as it is now", "",
           "Written for you at the start of this request. The page files are the truth; this is a summary.", ""]
    def item_lines(item: Mapping[str, Any]) -> list[str]:
        """A section's lines under its heading, the same on a page and in the header or footer."""
        props = item.get("props", {})
        lines: list[str] = []
        if item.get("type") == "ClonedSection":
            clone = clones.get(props.get("fragmentId"), {})
            slots = props.get("slots") or {}
            for key, slot in (clone.get("slots") or {}).items():
                value = slots.get(key)
                if slot.get("kind") == "text" and value not in (None, "", slot.get("fallback")):
                    lines.append(f"   - {key}: {_rich_words(value)}")
                elif slot.get("kind") == "image" and value:
                    lines.append(f"   - {key}: {image(value)}")
                elif slot.get("kind") == "href" and value:
                    lines.append(f"   - {key} → {value}")
                elif slot.get("kind") == "visibility" and value is False:
                    lines.append(f"   - {'hidden' if key == 'visible' else f'{key}: hidden'}")
            for r in props.get("replacements") or []:
                lines.append(f"   - \"{_short(r.get('find'), 60)}\" now reads \"{_short(r.get('replace'), 80)}\"")
            for link in props.get("links") or []:
                lines.append(f"   - link {link.get('find')} → {link.get('replace')}")
            if props.get("newTab"):
                lines.append(f"   - links opening in a new tab: {', '.join(str(key) for key in props['newTab'])}")
            for key, alt in (props.get("alts") or {}).items():
                lines.append(f'   - alt text {key}: "{_short(str(alt), 120)}"')
        else:
            for key in ("accountLine", "eyebrow", "kicker", "heading", "metric", "metricLabel", "intro", "body", "source", "legal"):
                if props.get(key):
                    lines.append(f"   - {key}: {_rich_words(props[key])}")
            for stat in props.get("stats") or []:
                lines.append(f"   - stat: {stat.get('value')} {_short(stat.get('label', ''), 80)}")
            for key in ("image", "logo", "accountLogo"):
                if props.get(key):
                    lines.append(f"   - {key}: {image(props[key])}")
            for key in ("imageAlt", "logoAlt", "accountLogoAlt"):
                if props.get(key):
                    lines.append(f'   - {key.removesuffix("Alt")} alt text: "{_short(str(props[key]), 120)}"')
            for words, href, tab in (("buttonLabel", "buttonHref", "buttonNewTab"), ("ctaLabel", "ctaHref", "ctaNewTab")):
                if props.get(words):
                    lines.append(f"   - button {_rich_words(props[words])} → {props.get(href)}{', new tab' if props.get(tab) else ''}")
            for words, href, tab in (("linkLabel", "linkHref", "linkNewTab"), ("privacyLabel", "privacyHref", "privacyNewTab"), ("termsLabel", "termsHref", "termsNewTab")):
                label = props.get(words) or {"privacyLabel": "Privacy policy", "termsLabel": "Terms"}.get(words, "")
                if props.get(href) and label:
                    lines.append(f"   - link {_rich_words(label)} → {props.get(href)}{', new tab' if props.get(tab) else ''}")
        lines += [f"   - styled by hand: {line}" for line in _styled_by_hand(props.get("_edits"))]
        return lines

    # Plan 6: the header and footer are sections, described like the page's own.
    if (workspace / "shell.json").exists():
        shell = json.loads((workspace / "shell.json").read_text())
        out += ["## Header and footer (shell.json)"]
        for part in _SHELL_PARTS:
            entry = shell_entry(shell, part)
            if entry is None:
                out.append(f"- {part.capitalize()}: not a section yet (rewrite shell.json: building-with-puck skill)")
                continue
            props = entry.get("props") or {}
            kind = str(entry.get("type"))
            if kind == "ClonedSection":
                clone = clones.get(props.get("fragmentId"), {})
                kind = f"ClonedSection {props.get('fragmentId')} \"{_short(clone.get('label', ''), 70)}\""
            elif props.get("surface"):
                kind = f"{kind} on the {props.get('surface')} surface"
            out.append(f"- {part.capitalize()}: {kind}")
            out += item_lines(entry)
            if part == "header":
                root = ((props.get("_edits") or {}).get("root") or {}) if isinstance(props.get("_edits"), dict) else {}
                placed = [words for flag, words in (("sticky", "stays at the top while scrolling"), ("overlay", "sits over the first section")) if root.get(flag)]
                if placed:
                    out.append(f"- Header {'; '.join(placed)}")
                menu = _menu_line(workspace, entry, clones)
                if menu:
                    out.append(f"- Menu: {menu}")
        out.append("")
    for route, page in site_pages(workspace).items():
        file = "page.json" if route == "/" else f"pages/{route[1:]}.json"
        out += [f"## {route} ({file})"]
        for n, item in enumerate(page.get("content") or [], 1):
            props = item.get("props", {})
            if item.get("type") == "ClonedSection":
                clone = clones.get(props.get("fragmentId"), {})
                out.append(f"{n}. {props.get('id')}: the seller's section \"{_short(clone.get('label', ''), 70)}\" ({props.get('fragmentId')})")
            else:
                out.append(f"{n}. {props.get('id')}: {item.get('type')} on the {props.get('surface')} surface")
            out += item_lines(item)
        out.append("")
    if versions:
        out += ["## Saved versions",
                "Each request and each save in the editor is one version; `restore_version` brings one back."]
        for item in versions:
            out.append(
                f'- version {item.get("version")}: "{_short(item.get("intent") or "", 80)}" '
                f'(by {_AUTHORS.get(str(item.get("actor")), "a person")}, {_when(item.get("created_at"))})'
            )
        out.append("")
    return "\n".join(out)


def _menu_line(workspace: Path, header: Mapping[str, Any], clones: Mapping[str, Any]) -> str:
    """The header's menu as the page draws it (site-kit's site-menu.ts): the site's pages, "/" first,
    renamed by ``menuLabels``, then ``menuExtra``. Empty when the header draws no menu of ours."""
    props = header.get("props") or {}
    kind = header.get("type")
    clone = clones.get(props.get("fragmentId"), {}) if kind == "ClonedSection" else {}
    if kind != "SiteHeader" and "data-clue-menu" not in str(clone.get("html") or ""):
        return ""
    routes = sorted(site_pages(workspace), key=lambda route: (route != "/", route))
    labels = props.get("menuLabels") or {}
    pages = []
    if len(routes) > 1:
        for route in routes:
            key = "_home" if route == "/" else route[1:]
            default = "Overview" if route == "/" else route[1:].replace("-", " ").capitalize()
            pages.append(f"{labels.get(key) or default} → {route}")
    extra = [f"{item.get('label')} → {item.get('href')}" + (" (new tab)" if item.get("newTab") else "") for item in props.get("menuExtra") or []]
    line = ", ".join(pages) or "no pages (a one-page site)"
    return line + (f"; extra: {', '.join(extra)}" if extra else "")


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


def history_count(workspace: Path) -> int:
    """How many requests history.md records (the spike's `run_agent.history_count`)."""

    path = workspace / "history.md"
    return path.read_text().count("\n## ") if path.exists() else 0


def append_history(
    workspace: Path,
    number: int,
    request: str,
    changes: list[str],
    shell_changed: bool,
    reply: str | None,
    saved: str | None = None,
) -> None:
    """history.md, written after each request (the spike's, plus whether it was saved — T10)."""

    path = workspace / "history.md"
    text = path.read_text() if path.exists() else "# Earlier requests in this project\n\nOldest first. Written after each request.\n"
    what = "; ".join(changes + (["changed the header or footer"] if shell_changed else [])) or "nothing changed"
    text += f"\n## {number}. {request}\n- What changed: {what}\n- The reply: {_short(reply or '', 500)}\n"
    if saved is not None:
        text += f"- Saved: {saved}\n"
    path.write_text(text)


def saved_line(
    *, status: str, stop_reason: str | None, outcome_status: str | None, version: int | None
) -> str:
    """history.md's "Saved:" text for one request (T10)."""

    if outcome_status == "saved":
        return f"as version {version}"
    if outcome_status == "conflicted":
        return "no, the site changed while this request ran"
    if outcome_status == "refused":
        return "no, the save was refused"
    if status == "applied":
        return "nothing to save"
    if status == "clarification_requested":
        return "nothing, it asked a question first"
    if stop_reason == "site_invalid":
        return "no, the page was still invalid"
    if stop_reason == "cancelled_by_request":
        return "no, it was stopped"
    return "no, the request did not finish"



#: A selected part's object id (Lane A Task 14 / Lane C Task 11): site:<route>#<id>[.<field>], where
#: <route> is "/", "/<name>" or "shell" (the header or the footer). Read the way the composer reads
#: it (`clue_api.design_turn_targets._site_target`): the whole text after "#" is one section id first
#: (ids may contain dots), and only when the site has no such section is it "<id>.<field>", split at
#: the LAST dot.
_TARGET_ROUTE = re.compile(r"/(?:[a-z0-9][a-z0-9-]*)?")


def _is_site_part(site: Mapping[str, Any] | None, route: str, part_id: str) -> bool:
    """Whether the site has a section (or, for "shell", a header or footer) with this exact id."""
    if site is None:
        return False
    if route == "shell":
        return part_id in _SHELL_PARTS and shell_entry(site.get("shell"), part_id) is not None
    content = (site_pages_of(site).get(route) or {}).get("content")
    return any(
        isinstance(item, Mapping) and isinstance(item.get("props"), Mapping) and item["props"].get("id") == part_id
        for item in (content if isinstance(content, list) else ())
    )


def _parse_target(object_id: str, site: Mapping[str, Any] | None) -> tuple[str, str, str | None] | None:
    """(route, id, field) for a well-formed target, or None for one to name as written."""
    if not object_id.startswith("site:") or "#" not in object_id:
        return None
    route, _, rest = object_id[len("site:"):].partition("#")
    if not rest or (route != "shell" and not _TARGET_ROUTE.fullmatch(route)):
        return None
    part_id, field = rest, None
    if not _is_site_part(site, route, rest):
        head, _, tail = rest.rpartition(".")
        if head and tail:
            part_id, field = head, tail
    if route == "shell" and part_id not in _SHELL_PARTS:
        return None
    return route, part_id, field


def _target_line(object_id: str, note: str | None, site: Mapping[str, Any] | None) -> str:
    parsed = _parse_target(object_id, site)
    if parsed is None:
        where = f'The part "{object_id}" of the site'
    else:
        route, part_id, field = parsed
        where = f"The {part_id}" if route == "shell" else f'Page {route}, the section with id "{part_id}"'
        if field:
            where += f', its "{field}" field'
    said = f' Their note: "{note.strip()}"' if note and note.strip() else " (No note.)"
    return f"- {where}.{said}"


def targets_block(targets: Sequence[Mapping[str, Any]], site: Mapping[str, Any] | None = None) -> str:
    """What the person pointed at (ruling R9, text T15), or "" when they pointed at nothing.

    ``site`` is the stored site the turn edits; with it, a section id that contains a dot is named
    whole rather than split into an id and a field (the composer's rule)."""
    if not targets:
        return ""
    lines = [_target_line(str(t.get("object_id") or ""), t.get("note"), site) for t in targets]
    return (
        "The person also pointed at parts of the site:\n"
        + "\n".join(lines)
        + "\nWork through these in the order listed. Change only these parts, unless their message asks "
        "for more. If a part is no longer on the site, say so in your report and use your judgement. "
        "In your report, say what you did for each part, or why you did not."
    )

#: Where a section's own code is written for the agent to read: catalog/sections/<Name>.tsx.
SECTION_CODE_DIR = "catalog/sections"


def _component_entry(name: str, props_schema: Mapping[str, Any], *, has_code: bool = False) -> str:
    entry = f"Use it with `\"type\": \"{name}\"` and these props:\n\n```json\n{json.dumps(props_schema, indent=1)}\n```\n"
    if has_code:
        entry += (f"\nIts code is in `{SECTION_CODE_DIR}/{name}.tsx`. To change this section, start from that "
                  f"code and write it again with write_section under the same name: every page that places "
                  f"it shows the new version.\n")
    return entry


def seller_components_markdown(sections: Mapping[str, SiteSection]) -> str:
    """catalog/seller-components.md for the sections the turn may place (the spike's format)."""

    return _COMPONENTS_HEADER + "".join(
        f"\n## {name}\n{_component_entry(name, s.props_schema, has_code=bool(s.source))}" for name, s in sections.items()
    )


def write_section_code(workspace: Path, name: str, source: str) -> None:
    """One section's own code at catalog/sections/<Name>.tsx (nothing when its code is unknown)."""

    if not source:
        return
    path = workspace / SECTION_CODE_DIR / f"{name}.tsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def record_component(workspace: Path, name: str, props_schema: Mapping[str, Any], source: str = "") -> None:
    """Add or replace one section in catalog/seller-components.md (the spike's `_record_component`),
    and write its code beside it when known."""

    write_section_code(workspace, name, source)
    path = workspace / "catalog" / "seller-components.md"
    entries: dict[str, str] = {}
    if path.exists():
        for chunk in path.read_text().split("\n## ")[1:]:
            entries[chunk.split("\n", 1)[0].strip()] = chunk.split("\n", 1)[1] if "\n" in chunk else ""
    entries[name] = _component_entry(name, props_schema, has_code=bool(source))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_COMPONENTS_HEADER + "".join(f"\n## {n}\n{body}" for n, body in entries.items()))


def materialize_workspace(
    workspace: Path,
    inputs: SiteTurnInputs,
    *,
    site: Mapping[str, Any],
    record: Callable[..., Any] | None = None,
) -> dict:
    """Write the whole workspace for one request (the spike's `assemble`, by value).

    Rebuilds every input folder from ``inputs`` and the site files from ``site``; keeps
    plan.md, history.md and fetched/ (the agent's memory). Returns a summary for the run record.
    """

    from lumen_agent.platform_reads import (
        read_thread_attachments,
        write_seller_knowledge,
        write_thread_attachments,
    )

    workspace.mkdir(parents=True, exist_ok=True)
    for name in REGENERATED:
        path = workspace / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    (workspace / "brief.md").write_text(inputs.brief)

    research = workspace / "research"
    research.mkdir()
    labels = claim_labels(inputs.overview + inputs.insights, {str(c.get("claim_id")) for c in inputs.claims})
    if inputs.overview or inputs.insights:
        held = set(inputs.held_claim_ids)
        (research / "overview.md").write_text(research_markdown(f"{inputs.account_name}: overview", inputs.overview, labels, held))
        (research / "insights.md").write_text(research_markdown(f"{inputs.account_name}: insights", inputs.insights, labels, held))
        if labels:
            (research / "claims.md").write_text(claims_markdown(inputs.account_name, labels, inputs.claims))
    else:
        (research / "README.md").write_text(f"# {inputs.account_name}\n\nThere is no written research for this account yet.\n")

    if inputs.platform_reads is not None:
        write_seller_knowledge(workspace, inputs.platform_reads, record=record or (lambda *a, **k: None))
    # Spec 2026-10-30 §3.3: the chat's files, rebuilt every request, read-only (READ_ONLY).
    attachments_note = write_thread_attachments(
        workspace,
        read_thread_attachments(inputs.platform_reads, record=record or (lambda *a, **k: None)),
    )
    if inputs.project_files:
        context = workspace / "project-context"
        context.mkdir()
        for item in inputs.project_files:
            name = Path(str(item.get("path") or "")).name
            if name:
                (context / name).write_text(str(item.get("body_text") or ""))

    root = workspace.resolve()
    for relative, text in inputs.catalog.items():
        target = workspace / relative
        if not target.resolve().is_relative_to(root):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    brand_file = workspace / "brand" / "brand.md"
    brand_file.parent.mkdir(parents=True, exist_ok=True)
    existing = brand_file.read_text() if brand_file.exists() else ""
    brand_file.write_text(
        existing.rstrip() + "\n" + account_logo_section(inputs.account_logos)
        + attached_images_section(inputs.attached_images)
    )
    if inputs.agent_sections:
        components = workspace / "catalog" / "seller-components.md"
        components.parent.mkdir(parents=True, exist_ok=True)
        components.write_text(seller_components_markdown(inputs.agent_sections))
        for name, section in inputs.agent_sections.items():
            write_section_code(workspace, name, section.source)

    shutil.copytree(SITE_DIR / "skills", workspace / "skills")
    shutil.copytree(SITE_DIR / "skills-e5", workspace / "skills-e5")
    if inputs.live_sites:
        shutil.copytree(SITE_DIR / "skills-live", workspace / "skills-live")
    (workspace / "fetched").mkdir(exist_ok=True)
    write_site_files(workspace, site)
    if any(page.get("content") for page in site_pages_of(site).values()):
        versions = inputs.site_versions.list_versions(10) if inputs.site_versions is not None else []
        (workspace / "site.md").write_text(site_summary(workspace, turn_brand(inputs.brand, inputs.account_logos, inputs.attached_images), versions))
    return {
        "research_blocks": len(inputs.overview) + len(inputs.insights),
        "claims_labelled": len(labels),
        "people_in_research": len(research_people(inputs.overview + inputs.insights)),
        "clones": len(list((workspace / "catalog" / "clones").glob("*.md"))),
        "attachments_note": attachments_note,
    }
