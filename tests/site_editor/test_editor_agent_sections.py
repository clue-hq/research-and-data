"""S2a-2: agent-written sections in the editor's Edit mode (option B, founder 2026-10-16).

A prop the agent marks `.meta({ edit: "inline" })` edits in place on the canvas; every other text
prop is edited in the dock and reaches the section as plain text; surfaces and styles are pick-lists
from the brand; a section that still fails in Edit mode is drawn with its stored props. The sections
here go through the real write path: site-kit's compile-section (the check and the bundle) and the
design API's record path (`lumen_api.site_render.read_section_schema`, the hardened render page),
and are served to the built editor through its token route. A save is checked by the validator the
design API runs (site-kit's dist/validate-site.mjs).

    CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        tests/site_editor/test_editor_agent_sections.py

Adopted from the S2a review's probe (.superpowers/review/2026-10-13-wave2/reports/
S2a-site-editor-package-probes/test_s2a_agent_props.py), which asserted the failure.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
from typing import Any

import pytest

from .conftest import BROWSER_OPT_IN, FRONTEND, REPO, TOKEN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
SITE_KIT = FRONTEND / "packages/site-kit"
DESIGN = REPO / "subsystems/clue-design"

# The writing-a-section skill's own example (its S2a-2 wording, founder-approved 2026-10-16).
SKILL = DESIGN / "apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md"
SKILL_QUOTE = re.search(r"```tsx\n(.*?)```", SKILL.read_text(), re.S).group(1)  # type: ignore[union-attr]

# Choices and text the agent did not mark: what the section receives must be text in every mode.
CHOICE_PROBE = """import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  headline: z.string().meta({ edit: "inline" }),
  cta: z.string().meta({ edit: "inline" }),
  ctaHref: z.string(),
  ctaLook: z.string(),
  alt: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <h2 className="font-title text-title">{props.headline}</h2>
      <p data-probe="types" className="font-body text-body">
        {[typeof props.surface, typeof props.ctaLook, typeof props.alt].join(" ")}
      </p>
      <kit.Button
        label={props.cta} href={props.ctaHref} surface={props.surface} look={props.ctaLook}
      />
    </kit.Shell>
  );
}
"""

# A section that marks nothing and handles its text as text: it never breaks in Edit mode.
PLAIN_PROBE = """import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  eyebrow: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <p data-probe="plain" className="font-body text-body">{props.eyebrow.toUpperCase()}</p>
    </kit.Shell>
  );
}
"""

# What the checks cannot see: props typed by hand, so the type check never learns `eyebrow` is
# marked, and the section capitalises it. In Edit mode it is drawn with its stored props (§2.5).
HAND_TYPED = """import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.string(),
  eyebrow: z.string().meta({ edit: "inline" }),
}).strict();

export function render(props: { id: string; surface: string; eyebrow: string }, kit: Kit) {
  return (
    <kit.Shell surface={props.surface}>
      <p data-probe="hand-typed" className="font-body text-body">{props.eyebrow.toUpperCase()}</p>
    </kit.Shell>
  );
}
"""

SECTIONS = {
    "SkillQuote": (
        SKILL_QUOTE,
        {
            "id": "quote",
            "surface": "brand",
            "quote": "Garner cut our spend.",
            "attribution": "A CFO",
        },
    ),
    "ChoiceProbe": (
        CHOICE_PROBE,
        {
            "id": "choice",
            "surface": "inverse",
            "headline": "Probe",
            "cta": "Talk to us",
            "ctaHref": "/analysis",
            "ctaLook": "",
            "alt": "Team photo",
        },
    ),
    "PlainProbe": (PLAIN_PROBE, {"id": "plain", "surface": "page", "eyebrow": "new for 2026"}),
    "HandTyped": (HAND_TYPED, {"id": "typed", "surface": "page", "eyebrow": "by hand"}),
}


def compile_section(name: str, source: str, brand: dict[str, Any]) -> str:
    """site-kit's own compile-section: the lint, the type check and the bundle."""
    out = subprocess.run(
        ["node", "--import", "tsx", "bin/compile-section.ts"],
        input=json.dumps({"name": name, "source": source, "brand": brand}),
        capture_output=True,
        check=True,
        cwd=SITE_KIT,
        text=True,
    ).stdout
    result = json.loads(out)
    assert result["ok"], f"{name} was refused: {result.get('errors')}"
    return str(result["moduleJs"])


def recorded_schema(module_js: str) -> dict[str, Any]:
    """The props schema the design API stores, read inside its hardened render page."""
    out = subprocess.run(
        [
            str(REPO / ".venv/bin/python"),
            "-c",
            "import json, sys\n"
            "from lumen_api.site_render import read_section_schema\n"
            "print(json.dumps(read_section_schema(sys.stdin.read())))",
        ],
        input=module_js,
        capture_output=True,
        check=True,
        cwd=DESIGN,
        env={**os.environ, "PYTHONPATH": ".:apps/api:apps/agent_runtime"},
        text=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def validate(site: dict[str, Any], brand: dict[str, Any], schemas: dict[str, Any]) -> list[str]:
    """The validator the design API runs on a save (a refusal there is the app's 422)."""
    out = subprocess.run(
        ["node", "dist/validate-site.mjs"],
        input=json.dumps(
            {
                "files": {"pages": site["pages"], "shell": site["shell"]},
                "brand": brand,
                "agentSectionSchemas": schemas,
            }
        ),
        capture_output=True,
        check=True,
        cwd=SITE_KIT,
        text=True,
    ).stdout
    return list(json.loads(out)["errors"])


@pytest.fixture(scope="module")
def written() -> dict[str, Any]:
    brand = garner_init()["brand"]
    modules = {name: compile_section(name, source, brand) for name, (source, _) in SECTIONS.items()}
    schemas = {name: recorded_schema(module) for name, module in modules.items()}
    return {"brand": brand, "modules": modules, "schemas": schemas}


def init_payload(written: dict[str, Any], design_api: Any, mode: str) -> dict[str, Any]:
    digests = {}
    for name, module in written["modules"].items():
        code = module.encode()
        digest = hashlib.sha256(code).hexdigest()
        design_api.modules[digest] = code
        digests[name] = digest
    base = garner_init(mode=mode)
    site = copy.deepcopy(base["site"])
    site["agent_sections"] = digests
    site["pages"]["/"]["content"] += [
        {"type": name, "props": props} for name, (_, props) in SECTIONS.items()
    ]
    return {
        **base,
        "site": site,
        "sections": [
            {
                "name": name,
                "digest": digests[name],
                "token": TOKEN,
                "propsSchema": written["schemas"][name],
            }
            for name in digests
        ],
    }


STATE = """() => {
  const at = (name) => document.querySelector(`[data-agent-section="${name}"] section`);
  const look = (name) => {
    const s = at(name);
    return s ? [s.className, getComputedStyle(s).backgroundColor] : null;
  };
  return {
    quote: look("SkillQuote"),
    choice: look("ChoiceProbe"),
    types: document.querySelector('[data-probe="types"]')?.textContent ?? null,
    plain: document.querySelector('[data-probe="plain"]')?.textContent ?? null,
    typed: document.querySelector('[data-probe="hand-typed"]')?.textContent ?? null,
    failed: Array.from(document.querySelectorAll("[data-agent-section-failed]"))
      .map((e) => e.getAttribute("data-agent-section-failed")),
  };
}"""


def open_site(
    app: Any,
    browser_page: Any,
    design_api: Any,
    editor_origin: str,
    written: dict[str, Any],
    mode: str,
) -> tuple[Any, Any]:
    page, _ = browser_page
    app.init_payload = init_payload(written, design_api, mode)
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text("Garner cut our spend.").first.wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    return page, frame


def selected_fields(page: Any, frame: Any, selector: str, component_id: str) -> dict[str, Any]:
    mark = len(received(page))
    frame.locator(selector).first.click(force=True)
    page.wait_for_function(
        "([mark, id]) => window.__received.slice(mark)"
        ".some((m) => m.type === 'selected' && m.payload.componentId === id)",
        arg=[mark, component_id],
    )
    message = next(
        m
        for m in received(page)[mark:]
        if m["type"] == "selected" and m["payload"]["componentId"] == component_id
    )
    return {field["name"]: field for field in message["payload"]["fields"]}


def set_props(page: Any, frame: Any, component_id: str, props: dict[str, Any], rev: int) -> None:
    """The app's `set_props`, as after an accepted dock edit, with the section's full props."""
    page.evaluate(
        "([id, props, rev]) => "
        "window.__send('set_props', { route: '/', componentId: id, props, rev })",
        [component_id, props, rev],
    )


def test_agent_sections_in_edit_mode_draw_as_in_preview_and_save_what_the_marketer_chose(
    app: Any, browser_page: Any, design_api: Any, editor_origin: str, written: dict[str, Any]
) -> None:
    # The record path keeps the marker; unmarked props carry none.
    quote_schema = written["schemas"]["SkillQuote"]["properties"]
    assert (
        quote_schema["quote"].get("edit") == "inline"
        and quote_schema["attribution"].get("edit") == "inline"
    )
    assert "edit" not in quote_schema["surface"]

    page, frame = open_site(app, browser_page, design_api, editor_origin, written, "preview")
    preview = frame.evaluate(STATE)
    assert preview["quote"][0] == "bg-surface-brand text-on-surface-brand", preview
    assert preview["failed"] == [], preview

    page, frame = open_site(app, browser_page, design_api, editor_origin, written, "edit")
    edit = frame.evaluate(STATE)
    # The same surface class and background as in Preview, text props as text, nothing failed.
    assert edit["quote"] == preview["quote"], edit
    assert edit["choice"] == preview["choice"], edit
    assert edit["types"] == "string string string", edit
    assert edit["plain"] == "NEW FOR 2026", edit
    assert edit["typed"] == "BY HAND", (
        "a section that fails only in Edit mode is drawn with its stored props"
    )
    assert edit["failed"] == [], edit

    # Typing into marked prose on the canvas saves the new text, and the save is valid.
    quote = frame.locator('[data-agent-section="SkillQuote"] blockquote [contenteditable]').first
    quote.hover()
    quote.click(force=True)
    page.keyboard.press("Meta+a")
    page.keyboard.type("Fewer surprises.")
    mark = len(received(page))
    frame.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_function(
        "(mark) => window.__received.slice(mark).some((m) => m.type === 'changed')", arg=mark
    )
    saved = next(m for m in received(page)[mark:] if m["type"] == "changed")["payload"]["site"]
    stored = next(
        item for item in saved["pages"]["/"]["content"] if item["props"]["id"] == "quote"
    )["props"]
    assert stored["quote"] == "Fewer surprises.", stored
    assert validate(saved, written["brand"], written["schemas"]) == []

    # The dock offers the brand's surfaces and styles as lists, and any choice saves.
    fields = selected_fields(page, frame, '[data-probe="types"]', "choice")
    assert fields["surface"]["kind"] == "select" and fields["ctaLook"]["kind"] == "select", fields
    assert fields["ctaLook"]["options"][0] == {"label": "Standard", "value": ""}
    # Marked prose is rich text, edited on the canvas and shown read-only in the dock (plan 2).
    assert [fields["headline"]["kind"], fields["alt"]["kind"], fields["ctaHref"]["kind"]] == [
        "richtext",
        "text",
        "link",
    ]
    surfaces = [option["value"] for option in fields["surface"]["options"]]
    assert "canvas" in surfaces, "the brand's own surfaces follow the six"
    choice = next(
        item for item in saved["pages"]["/"]["content"] if item["props"]["id"] == "choice"
    )
    chosen = {
        **choice["props"],
        "surface": surfaces[-1],
        "ctaLook": fields["ctaLook"]["options"][-1]["value"],
    }
    choice["props"] = chosen
    assert validate(saved, written["brand"], written["schemas"]) == [], (
        "a choice from the dock's list is never a 422"
    )
    set_props(page, frame, "choice", chosen, 2)
    frame.locator(f'[data-agent-section="ChoiceProbe"] section.bg-surface-{surfaces[-1]}').wait_for(
        timeout=10000
    )

    # A section that marks nothing edits its text in the dock and never breaks.
    plain_fields = selected_fields(page, frame, '[data-probe="plain"]', "plain")
    assert plain_fields["eyebrow"]["kind"] == "text"
    plain = next(item for item in saved["pages"]["/"]["content"] if item["props"]["id"] == "plain")[
        "props"
    ]
    set_props(page, frame, "plain", {**plain, "eyebrow": "next quarter"}, 3)
    frame.get_by_text("NEXT QUARTER").first.wait_for(timeout=10000)
    assert frame.evaluate(STATE)["failed"] == []
