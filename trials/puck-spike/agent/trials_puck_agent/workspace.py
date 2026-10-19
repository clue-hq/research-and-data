"""Assemble one run's workspace: the plain files the agent works in (T3 of the phase-2 spike).

brief.md, research/ (the account's written pages as plain markdown; with claims, each statement
ends with short labels like [c4, c9] and research/claims.md gives each label its source and quote),
seller/ (the seller's files), catalog/ and brand/ (scripts/build-catalog.ts), skills/, and .run.json
for the validator. There is no page.json or shell.json yet: the agent writes both (the file tools refuse to
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
    title: str,
    sections: list[dict],
    labels: dict[str, str] | None = None,
    held: set[str] | None = None,
) -> str:
    """One research page (overview or insights) as markdown: headings and statements, each statement
    with its type and notes, and ending with the short labels of its claims when `labels` is given
    (never the claim ids). Sections held back from outreach (Watch-outs, Context only) are kept and
    marked as background, never words for the page. A statement citing a claim in `held` is left out."""
    out = [f"# {title}"]
    for section in sections:
        body = _section_body(section)
        if body is None:
            out += [
                "",
                f"## {section.get('section_key', 'Section')}",
                str(section.get("body_text", "")),
            ]
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
        lines += [
            f"{label}: {_plain(value[key])}"
            for key, label in (("persona", "For"), ("angle_label", "Angle"))
            if value.get(key)
        ]
        return lines
    return [f"Says: {_plain(value)}"]


def claims_markdown(account_name: str, labels: dict[str, str], claims: list[dict]) -> str:
    """research/claims.md: each label's claim with what it says, its source link and any notes."""
    by_id = {str(c.get("claim_id")): c for c in claims}
    out = [
        f"# {account_name}: the claims behind the research",
        "",
        "Each label in the research files (like [c4]) is one claim below: what it says, its source link,",
        "and any notes. A shortened quote is only the opening of the source's words.",
    ]
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


def write_seller_files(knowledge: Any, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    index = ["# The seller's files", ""]
    for doc in knowledge.documents:
        target = dest / doc.path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.body_text)
        mark = (
            " (the confirmed ICP)"
            if doc.path == getattr(knowledge, "confirmed_icp_path", None)
            else ""
        )
        index.append(
            f"- seller/{doc.path.lstrip('/')} ({doc.kind}, {len(doc.body_text)} characters){mark}"
        )
    (dest / "index.md").write_text("\n".join(index) + "\n")
    return len(knowledge.documents)


def build_catalog(spike_root: Path, brand: str, dest: Path, seller: str) -> None:
    subprocess.run(
        ["npx", "tsx", "scripts/build-catalog.ts", brand, str(dest), seller],
        cwd=spike_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )


LOGO_CELLS = {
    "light_lockup": "the full logo, for light backgrounds",
    "dark_lockup": "the full logo, for dark backgrounds",
    "light_mark": "the symbol only, for light backgrounds",
    "dark_mark": "the symbol only, for dark backgrounds",
}
LOGO_EXTENSIONS = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def account_logo_section(spike_root: Path, site: str, logos: list[dict] | None) -> str:
    """Save the account's logo files under public/accounts/<site>/ and describe them for brand.md:
    the recommended light/dark logos first, then every other real logo the fetch found (the
    platform tool's alternatives), each with its label."""
    out = ["", "## The account's logo (header only)", ""]
    if not logos:
        return "\n".join(out + ["None was found. Leave `accountLogo` empty.", ""])
    folder = spike_root / "public" / "accounts" / site
    folder.mkdir(parents=True, exist_ok=True)
    recommended = [logo for logo in logos if not logo.get("alternative")]
    others = [logo for logo in logos if logo.get("alternative")]
    for logo in recommended:
        name = logo["cell"] + LOGO_EXTENSIONS.get(logo["content_type"], ".png")
        (folder / name).write_bytes(logo["body"])
        out.append(f"- `/accounts/{site}/{name}`: {LOGO_CELLS.get(logo['cell'], logo['cell'])}")
    if others:
        out += [
            "",
            "Other logos found for the account. Use one only when none of the above fits the header:",
        ]
        for number, logo in enumerate(others, start=1):
            name = f"other-{number}" + LOGO_EXTENSIONS.get(logo["content_type"], ".png")
            (folder / name).write_bytes(logo["body"])
            out.append(
                f"- `/accounts/{site}/{name}`: {logo.get('label') or 'another logo of the account'}"
            )
    return "\n".join(out + [""])


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
    claims: list[dict] | None = None,
    held_claim_ids: set[str] | None = None,
    account_logo: list[dict] | None = None,
) -> dict:
    """Write the whole workspace. Returns a summary for the run record. With `claims` (the account's
    served claims), the research carries short labels and research/claims.md is written. Statements
    citing a claim in `held_claim_ids` (held back by a real rule) are left out of the research."""
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "brief.md").write_text(brief)
    research = workspace / "research"
    research.mkdir()
    labels = claim_labels(overview + insights, {str(c.get("claim_id")) for c in claims or []})
    if overview or insights:
        held = held_claim_ids or set()
        (research / "overview.md").write_text(
            research_markdown(f"{account_name}: overview", overview, labels, held)
        )
        (research / "insights.md").write_text(
            research_markdown(f"{account_name}: insights", insights, labels, held)
        )
        if labels:
            (research / "claims.md").write_text(claims_markdown(account_name, labels, claims or []))
    else:
        (research / "README.md").write_text(
            f"# {account_name}\n\nThere is no written research for this account yet.\n"
        )
    seller_files = write_seller_files(knowledge, workspace / "seller") if knowledge else 0
    build_catalog(spike_root, brand, workspace, seller)
    brand_file = workspace / "brand" / "brand.md"
    brand_file.write_text(
        brand_file.read_text().rstrip()
        + "\n"
        + account_logo_section(spike_root, site, account_logo)
    )
    shutil.copytree(SKILLS_DIR, workspace / "skills")
    (workspace / "fetched").mkdir()
    (workspace / ".run.json").write_text(json.dumps({"brand": brand, "site": site, "route": "/"}))
    return {
        "research_blocks": len(overview) + len(insights),
        "claims_labelled": len(labels),
        "people_in_research": len(research_people(overview + insights)),
        "seller_files": seller_files,
        "clones": len(list((workspace / "catalog" / "clones").glob("*.md"))),
    }


# --- memory for a fresh session: written by code, read by the agent ---------------------------------


def _site_pages(workspace: Path) -> dict[str, dict]:
    pages = (
        {"/": json.loads((workspace / "page.json").read_text())}
        if (workspace / "page.json").exists()
        else {}
    )
    for file in (
        sorted((workspace / "pages").glob("*.json")) if (workspace / "pages").exists() else []
    ):
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
    described = {
        a["file"]: a.get("description") or ""
        for a in json.loads((data / "assets.json").read_text()).values()
    }
    site = json.loads((workspace / ".run.json").read_text()).get("site", "")
    generated = spike_root / "public" / "generated" / site / "index.json"
    if site and generated.exists():
        described.update(
            {
                f: f"generated: {e.get('prompt', '')}"
                for f, e in json.loads(generated.read_text()).items()
            }
        )

    def image(file: object) -> str:
        return f"{file}" + (
            f" ({_short(described.get(str(file), ''), 120)})" if described.get(str(file)) else ""
        )

    out = [
        "# The site as it is now",
        "",
        "Written for you at the start of this request. The page files are the truth; this is a summary.",
        "",
    ]
    if (workspace / "shell.json").exists():
        shell = json.loads((workspace / "shell.json").read_text())
        header = shell.get("header", {})
        nav = (
            ", ".join(f"{n.get('label')} → {n.get('href')}" for n in header.get("nav") or [])
            or "none"
        )
        out += [
            "## Header and footer",
            f'- Prepared for: {header.get("preparedFor")}; button "{header.get("ctaLabel")}" → {header.get("ctaHref")}',
            f"- Nav links: {nav}",
            f"- Footer: {_short(shell.get('footer', {}).get('legal', ''))}",
            "",
        ]
    for route, page in _site_pages(workspace).items():
        file = "page.json" if route == "/" else f"pages/{route[1:]}.json"
        out += [f"## {route} ({file})"]
        for n, item in enumerate(page.get("content") or [], 1):
            props = item.get("props", {})
            if item.get("type") == "ClonedSection":
                clone = clones.get(props.get("fragmentId"), {})
                out.append(
                    f'{n}. {props.get("id")}: the seller\'s section "{_short(clone.get("label", ""), 70)}" ({props.get("fragmentId")})'
                )
                slots = props.get("slots") or {}
                for key, slot in (clone.get("slots") or {}).items():
                    value = slots.get(key)
                    if slot.get("kind") == "text" and value not in (None, "", slot.get("fallback")):
                        out.append(f'   - {key}: "{_short(value)}"')
                    elif slot.get("kind") == "image" and value:
                        out.append(f"   - {key}: {image(value)}")
                    elif slot.get("kind") == "href" and value:
                        out.append(f"   - {key} → {value}")
                    elif slot.get("kind") == "visibility" and value is False:
                        out.append("   - hidden")
                for r in props.get("replacements") or []:
                    out.append(
                        f'   - "{_short(r.get("find"), 60)}" now reads "{_short(r.get("replace"), 80)}"'
                    )
                for link in props.get("links") or []:
                    out.append(f"   - link {link.get('find')} → {link.get('replace')}")
            else:
                out.append(
                    f"{n}. {props.get('id')}: {item.get('type')} on the {props.get('surface')} surface"
                )
                for key in (
                    "eyebrow",
                    "kicker",
                    "heading",
                    "metric",
                    "metricLabel",
                    "intro",
                    "body",
                    "source",
                ):
                    if props.get(key):
                        out.append(f'   - {key}: "{_short(props[key])}"')
                for stat in props.get("stats") or []:
                    out.append(
                        f"   - stat: {stat.get('value')} {_short(stat.get('label', ''), 80)}"
                    )
                if props.get("image"):
                    out.append(f"   - image: {image(props['image'])}")
                if props.get("buttonLabel"):
                    out.append(f'   - button "{props["buttonLabel"]}" → {props.get("buttonHref")}')
                if props.get("linkLabel"):
                    out.append(f'   - link "{props["linkLabel"]}" → {props.get("linkHref")}')
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
                fields = sorted(
                    k
                    for k in set(old[sid]["props"]) | set(new[sid]["props"])
                    if old[sid]["props"].get(k) != new[sid]["props"].get(k)
                )
                notes.append(f"{route}: changed {sid} ({', '.join(fields)})")
        notes += [f"{route}: removed the section {sid}" for sid in old if sid not in new]
        kept_old = [s for s in old if s in new]
        kept_new = [s for s in new if s in old]
        if kept_old != kept_new:
            notes.append(f"{route}: new order {', '.join(new)}")
    notes += [f"removed the page {route}" for route in before if route not in after]
    return notes


def append_history(
    workspace: Path,
    number: int,
    request: str,
    changes: list[str],
    shell_changed: bool,
    reply: str | None,
) -> None:
    path = workspace / "history.md"
    text = (
        path.read_text()
        if path.exists()
        else "# Earlier requests in this project\n\nOldest first. Written after each request.\n"
    )
    what = (
        "; ".join(changes + (["changed the header or footer"] if shell_changed else []))
        or "nothing changed"
    )
    text += f"\n## {number}. {request}\n- What changed: {what}\n- The reply: {_short(reply or '', 500)}\n"
    path.write_text(text)
