// The agent's catalog: a bounded, plain-file map of everything a page can be built from, so the
// agent reads a short list instead of raw HTML or CSS (our version of Ploy's page-build plan).
//
//   catalog/index.md          every section available, one line each, clones in source-page order
//   catalog/clones/<id>.md    one clone: source, slots (kind + original wording), other visible
//                             text (for text replacements), links, images
//   catalog/sections.md       our own sections: purpose, fields and allowed choices (from the schemas)
//   brand/brand.md            the brand's token choices in words, the button, and the asset list
//
// Pure: buildCatalog returns the files as {relative path: markdown}; the caller writes them.
import { parse, TextNode, type HTMLElement } from "node-html-parser";
import { z } from "zod";
import type { BrandData } from "./brand";
import { colorOf, isMeasured, pxOf, tokenEntry, typographyOf } from "./brand-values";
import type { Clone } from "./clone";
import {
  buttonLooks, cardLooks, drawnButton, drawnCard, drawnLink, measuredComponents, motionEntries, motionNotes,
  partsFromSlots, type Drawn, type Look, type Part,
} from "./looks";
import { COMPONENT_SCHEMAS } from "./schemas";
import { inkRole, surfaceChoices } from "./surfaces";
import { SPACING_ROLES, TYPE_ROLES, typeVar } from "./theme";

const PURPOSE: Record<string, string> = {
  StatsBand: "Two to four numbers with what each means, under a heading. Proof or scale.",
  FeatureSplit: "One idea in words beside one image (left or right), with an optional button.",
  ProofCard: "One customer result or study: whose result, the metric, what they did, the source.",
  CtaBand: "The one next step: a heading, a line, and the button.",
  ClonedSection: "One of the seller's own sections, exactly as captured, with its words changed.",
};

const SKIP_TEXT = /^\{\{wf/;

function cloneFile(clone: Clone): string {
  const root = parse(clone.html, { comment: false });
  const consumed = new Set<HTMLElement>();
  for (const [key, slot] of Object.entries(clone.slots)) {
    if (slot.kind !== "text") continue;
    for (const element of root.querySelectorAll(`[data-lumen-slot="${key}"]`)) consumed.add(element);
  }
  const insideTextSlot = (node: HTMLElement | null): boolean => {
    for (let current = node; current; current = current.parentNode as HTMLElement | null) {
      if (consumed.has(current)) return true;
    }
    return false;
  };

  const otherText: string[] = [];
  const walk = (node: HTMLElement) => {
    for (const child of node.childNodes) {
      if (child instanceof TextNode) {
        const value = child.rawText.replace(/\s+/g, " ").trim();
        if (value && !SKIP_TEXT.test(value) && !insideTextSlot(node) && !otherText.includes(value)) {
          otherText.push(value);
        }
      } else if ((child as HTMLElement).tagName && !["SCRIPT", "STYLE"].includes((child as HTMLElement).tagName)) {
        walk(child as HTMLElement);
      }
    }
  };
  walk(root);

  const links = root
    .querySelectorAll("a[href]")
    .map((a) => {
      // Block-aware text (structuredText puts breaks between blocks); Webflow's unrendered
      // "{{wf …}}" placeholders are not labels.
      const clean = (value: string | undefined | null) =>
        (value ?? "").replace(/\s+/g, " ").trim().replace(/^\{\{wf.*$/, "");
      const parent = a.parentNode as HTMLElement | null;
      const label = clean(a.structuredText) || clean(a.getAttribute("aria-label")) || clean(parent?.structuredText);
      return `- \`${a.getAttribute("href")}\` "${label.slice(0, 70)}"`;
    });
  const images = root.querySelectorAll("img[src]").map((img) => {
    const slot = img.getAttribute("data-lumen-slot");
    return `- ${slot ? `slot \`${slot}\`` : "no slot"}: \`${img.getAttribute("src")}\``;
  });

  // Original wording as a visitor sees it: read from the markup (line breaks become spaces); the
  // stored fallback drops <br>, which would show "results.Bottom" run together.
  const visibleText = (key: string): string | null => {
    const element = root.querySelector(`[data-lumen-slot="${key}"]`);
    if (!element) return null;
    return parse(element.innerHTML.replace(/<br\s*\/?>/gi, " ")).text.replace(/\s+/g, " ").trim();
  };
  const slotRows = Object.entries(clone.slots).map(([key, slot]) => {
    const shown = slot.kind === "text" ? visibleText(key) : null;
    const original = String(shown ?? slot.fallback ?? "").replace(/\|/g, "\\|").replace(/\s+/g, " ");
    return `| \`${key}\` | ${slot.kind} | ${original} |`;
  });

  const LIMIT = 80;
  return [
    `# Clone \`${clone.id}\`: ${clone.label}`,
    "",
    `Source page: ${clone.page_url} · role: ${clone.role} · position on the page: ${clone.section_index ?? "?"}`,
    "",
    "Use it as:",
    "```json",
    JSON.stringify(
      { type: "ClonedSection", props: { id: "<your-id>", fragmentId: clone.id, slots: {}, replacements: [], links: [] } },
    ),
    "```",
    "",
    "## Slots",
    "Set a slot in `slots` to change it; leave it out to keep the original exactly. `href` takes a",
    "link, `image` takes a brand asset file, `visibility` takes true or false.",
    "",
    "| slot | kind | original |",
    "|---|---|---|",
    ...slotRows,
    "",
    "## Other visible text (no slot)",
    "Change any of these with `replacements`, using the exact text as `find`.",
    "",
    ...otherText.slice(0, LIMIT).map((value) => `- "${value}"`),
    ...(otherText.length > LIMIT ? [`- …and ${otherText.length - LIMIT} more`] : []),
    "",
    "## Links",
    "Change with `links` (`find` is the exact current href, or `*` for every link in the section).",
    "",
    ...(links.length ? links : ["- none"]),
    "",
    "## Images",
    ...(images.length ? images : ["- none"]),
    "",
  ].join("\n");
}

function sectionsFile(brand: BrandData): string {
  const parts = [
    "# Brand sections (ours)",
    "",
    "These are built from the brand's tokens, so every choice below stays on brand. Style options",
    "are names from brand/brand.md; there are no colour, size, class or style fields.",
    "",
  ];
  for (const [type, schema] of Object.entries(COMPONENT_SCHEMAS)) {
    if (type === "ClonedSection") continue;
    const json = z.toJSONSchema(schema, { io: "input" }) as {
      properties: Record<string, { type?: string; enum?: string[]; default?: unknown; items?: unknown }>;
      required?: string[];
    };
    parts.push(`## ${type}`, "", PURPOSE[type], "", "| field | type | required | choices / default |", "|---|---|---|---|");
    for (const [field, spec] of Object.entries(json.properties)) {
      const required = json.required?.includes(field) ? "yes" : "no";
      const surfaces = surfaceChoices(brand).map((choice) => `${choice.value} (${choice.label})`).join(", ");
      const looks = buttonLooks(brand).map((look) => look.name);
      const choices =
        field === "surface"
          ? `one of this brand's surfaces (brand/brand.md, Surfaces): ${surfaces}`
          : field === "buttonLook"
            ? looks.length
              ? `default ""; empty is the standard button, or a button style from brand/brand.md (Buttons): ${looks.join(", ")}`
              : `default ""; this brand's kit records no button styles, so leave it empty`
            : spec.enum
              ? spec.enum.join(", ")
              : spec.default !== undefined
                ? `default ${JSON.stringify(spec.default)}`
                : "";
      const kind = spec.type === "array" ? "list" : spec.type ?? "text";
      parts.push(`| \`${field}\` | ${kind} | ${required} | ${choices} |`);
    }
    parts.push("");
  }
  return parts.join("\n");
}

type TypeToken = { value: { default: { font_family: string; font_size: number; font_weight: number; line_height: number } }; provenance?: { source?: string } };
type Constraint = { rule?: string; scope?: string } | string;
type LogoEntry = { title?: string; variants?: { name: string; asset_id: string }[]; allowed_backgrounds?: string[] };

const FIELD_WORDS: Record<string, string> = {
  font_family: "family", font_size: "size", font_weight: "weight", line_height: "line height", letter_spacing: "letter spacing",
};
const KIND_WORD: Record<Look["kind"], string> = { outline: "outline", ghost: "text only", solid: "filled", other: "other" };
const SPACING_CLASS: Record<string, string> = {
  section: "`py-section`", "page.margin": "`px-page-margin`", "stack.tight": "`mt-stack-tight` or `gap-stack-tight`",
  "stack.default": "`mt-stack-default`", "stack.loose": "`mt-stack-loose`", "card.padding": "`p-card-padding`",
};

/** Whether a type role was measured on the seller's site, read from its token's provenance.source
 * (lumen_ingestion/normalizer): "<source>:<locator>" is measured; "derived:type.X; measured=<fields>
 * …" is measured for those fields, or derived when the list is "none"; "default:type-scale" is derived. */
export function typeRoleBasis(source: string | undefined): string {
  if (!source || source.startsWith("default:")) return "derived";
  const derived = /^derived:[^;]*;\s*measured=([^\s@]+)/.exec(source);
  if (!derived) return source.startsWith("derived:") ? "derived" : "measured";
  if (derived[1] === "none") return "derived";
  return `measured: ${derived[1].split(",").map((field) => FIELD_WORDS[field.trim()] ?? field.trim()).join(", ")}`;
}

const cellText = (text: string) => text.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();
const uniform = (value: string | undefined) => (value && new Set(value.split(" ")).size === 1 ? value.split(" ")[0] : value);

/** One drawn part as brand.md says it: the value and its token, or what is drawn instead. */
function partCell(brand: BrandData, drawn: Drawn, part: Part, what: string): string {
  let value = uniform(drawn.parts[part]);
  const token = drawn.tokens[part];
  if (!value || value === "transparent") return "none";
  if (value === "inherit" || value === "currentColor") return "the surrounding text's colour";
  if (value.startsWith("clamp(") && token) value = pxOf(brand, token) ?? value;
  const named = token ? `${value} (${token})` : value;
  if (drawn.source[part] === "readable") return `the kit's ${drawn.replaced?.[part]} does not read on this fill; drawn: ${named}`;
  if (drawn.source[part] === "standard") return `not in the kit; drawn: ${named}, the standard ${what}`;
  if (drawn.source[part] === "fallback") return `not in the kit; drawn: ${named}, site-kit's default`;
  return named;
}

function borderCell(brand: BrandData, drawn: Drawn, what: string): string {
  const width = uniform(drawn.parts.borderWidth);
  if (!width || /^0(px)?$/.test(width) || drawn.parts.borderStyle === "none") return "none";
  const colour = drawn.parts.border;
  const tint = !colour || colour === "currentColor" ? "in the label colour" : partCell(brand, drawn, "border", `${what} colour`);
  return `${partCell(brand, drawn, "borderWidth", what)} ${tint}`;
}

function surfacesSection(brand: BrandData): string[] {
  const pairs = (brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } }).constraints?.contrast_pairs ?? [];
  const rows = surfaceChoices(brand).map((choice) => {
    const ink = inkRole(brand, choice.role);
    const paired = pairs.some((pair) => pair.background === choice.role && pair.foreground === ink);
    const how = paired ? (choice.role.startsWith("surface.band.") ? ", measured on the band" : "") : ", chosen by contrast";
    const entry = tokenEntry(brand, "colors", choice.role);
    const band = /^section background \((.*)\)$/.exec(entry?.description ?? "");
    const from = band ? `measured: a section background on the seller's site (${band[1]} tall)` : isMeasured(entry) ? "measured" : "derived";
    return `| ${choice.value} | ${choice.label} | ${choice.role} | ${colorOf(brand, choice.role) ?? "not in this kit"} | ${ink ? `${colorOf(brand, ink)} (${ink})${how}` : "chosen by contrast"} | ${from} |`;
  });
  return [
    "## Surfaces",
    "Every section stands on one of these surfaces. Choose one by its name: `\"surface\": \"brand\"` on one",
    "of our sections, or `kit.Shell surface=\"<choice>\"` (or the classes",
    "`bg-surface-<choice> text-on-surface-<choice>`) in a section you write. Text on a surface takes the",
    "colour under \"text on it\".",
    "| choice | name | kit name | colour | text on it | from |",
    "|---|---|---|---|---|---|",
    ...rows,
    "",
  ];
}

function typeSection(brand: BrandData): string[] {
  const typography = ((brand.kit as { tokens?: { typography?: Record<string, TypeToken> } }).tokens?.typography) ?? {};
  const rows = TYPE_ROLES.map((role) => {
    const classes = `\`font-${typeVar(role)} text-${typeVar(role)}\``;
    const token = typography[`type.${role}`];
    if (!token) return `| ${role} | ${classes} | not in this kit | | | | | |`;
    const style = token.value.default;
    const colourRole = typographyOf(brand, `type.${role}`)?.color;
    const colour = colourRole && colorOf(brand, colourRole) && isMeasured(tokenEntry(brand, "colors", colourRole))
      ? `${colorOf(brand, colourRole)} (${colourRole})` : "the surface's text colour";
    return `| ${role} | ${classes} | ${style.font_family} | ${style.font_size}px | ${style.font_weight} | ${style.line_height} | ${colour} | ${typeRoleBasis(token.provenance?.source)} |`;
  });
  return [
    "## Type roles",
    "Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).",
    "\"measured\" means the seller's own site showed it, for the fields listed; \"derived\" means the kit",
    "worked it out from the measured roles. On a light surface a role takes the colour shown when the kit",
    "measured that colour; otherwise, and on every dark surface, it takes the surface's text colour.",
    "| role | classes | font | size at 1440 | weight | line height | colour | from |",
    "|---|---|---|---|---|---|---|---|",
    ...rows,
    "",
    "Our sections' headings choose from display, headline and title (`headingRole`).",
    "",
  ];
}

function spacingSection(brand: BrandData): string[] {
  const items = SPACING_ROLES.flatMap((role) => {
    const px = pxOf(brand, `space.${role}`);
    return px ? [`${SPACING_CLASS[role]} (space.${role}, ${px}${role === "section" ? " at 1440" : ""})`] : [];
  });
  if (!items.length) return [];
  const list = items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0];
  return ["## Spacing", `The seller's spacing, as classes you can use: ${list}. Values above 24px shrink on smaller screens.`, ""];
}

function buttonsSection(brand: BrandData): string[] {
  const looks = buttonLooks(brand);
  const std = drawnButton(brand, null);
  const fill = partCell(brand, std, "fill", "button's fill");
  const label = partCell(brand, std, "label", "button's label");
  const corners = partCell(brand, std, "radius", "button's corners");
  const dark = [
    "A button whose text or fill would not stand out from its surface changes: outline and text-only",
    "styles take the surface's text colour on any surface, and on a dark surface filled styles and the",
    "standard button take their light version (the kit's page or inverse colour, whichever stands out",
    "more on that surface, with its text colour). Every other button is drawn as the seller's site draws it.",
  ];
  if (!looks.length) {
    return ["## Buttons", `This brand's kit records no button styles, so every button is the kit's standard button: ${fill}, ${label}, ${corners}.`, "", ...dark, ""];
  }
  const first = looks[0].name;
  const rows = looks.map((look) => {
    const drawn = drawnButton(brand, look);
    return `| ${look.name} | ${KIND_WORD[look.kind]} | ${partCell(brand, drawn, "fill", "button's fill")} | ${partCell(brand, drawn, "label", "button's label")} | ${borderCell(brand, drawn, "button's border")} | ${partCell(brand, drawn, "radius", "button's corners")} | ${look.recipe.confidence ?? "low"} | ${cellText((look.recipe.unmapped ?? []).join(" "))} |`;
  });
  const measuredStates = looks.some((look) => look.measured && (Object.keys(look.measured.states ?? {}).length || look.measured.motion?.length));
  return [
    "## Buttons",
    "`kit.Button` draws a button. Below are the button styles the seller's own site uses, as its brand kit",
    "recorded them, and the kit's standard button. You choose the style of each button by its name, with",
    `\`look\`: \`kit.Button look="${first}"\` in a section you write, or \`"buttonLook": "${first}"\` on`,
    "a FeatureSplit or a CtaBand. A button with no look is the standard button.",
    "| look | kind | fill | label | border | corners | confidence | notes from the brand kit |",
    "|---|---|---|---|---|---|---|---|",
    `| (none) | the kit's standard button | ${fill} | ${label} | none | ${corners} | — | Used when you name no look. |`,
    ...rows,
    ...(measuredStates ? ["Each style's hover, pressed and focus looks, and the motion between them, come from the seller's", "site; `kit.Button` draws them."] : []),
    ...(measuredComponents(brand) ? [] : ["This kit was made before button styles were measured: their values come from the kit's tokens, and", "a part the kit has no value for is drawn as the standard button's part."]),
    "",
    "How to choose:",
    "- For the page's main ask, use the style the seller's site uses for its own main call to action (the",
    "  notes and the brand's rules below say which); if none is clear, use the standard button.",
    "- For quieter actions, use an outline or text-only style the site uses.",
    "- Leave out styles the notes say are not page buttons (for example \"inside product screenshots\"), and",
    "  be careful with low-confidence styles.",
    "- Where the kit has no value for a part, the table says what is drawn instead.",
    "- Add `disabled` for a button that cannot be used yet; it takes the style's disabled look.",
    "",
    ...dark,
    "",
  ];
}

function cardsSection(brand: BrandData): string[] {
  const looks = cardLooks(brand);
  const std = drawnCard(brand, null);
  const fill = partCell(brand, std, "fill", "card's fill");
  const text = partCell(brand, std, "label", "card's text");
  const corners = partCell(brand, std, "radius", "card's corners");
  const padding = partCell(brand, std, "padding", "card's padding");
  if (!looks.length) {
    return ["## Cards", `This brand's kit records no card styles; \`kit.Card\` draws the kit's standard card: ${fill}, ${corners}, ${padding}.`, ""];
  }
  const rows = looks.map((look) => {
    const drawn = drawnCard(brand, look);
    return `| ${look.name} | ${KIND_WORD[look.kind]} | ${partCell(brand, drawn, "fill", "card's fill")} | ${partCell(brand, drawn, "label", "card's text")} | ${borderCell(brand, drawn, "card's border")} | ${partCell(brand, drawn, "radius", "card's corners")} | ${partCell(brand, drawn, "padding", "card's padding")} | ${look.recipe.confidence ?? "low"} | ${cellText((look.recipe.unmapped ?? []).join(" "))} |`;
  });
  return [
    "## Cards",
    "`kit.Card` draws a card on a section's surface. Below are the card styles the seller's site uses, as",
    `its brand kit recorded them, and the kit's standard card. Choose one with \`look\``,
    `(\`kit.Card look="${looks[0].name}"\`), or leave it out for the standard card. Give it \`href\` to make`,
    "the whole card a link; it then takes the style's hover and focus looks from the seller's site.",
    "A text-only or outline card's text takes the surface's text colour on any surface where its own",
    "would not stand out.",
    "| look | kind | fill | text | border | corners | padding | confidence | notes from the brand kit |",
    "|---|---|---|---|---|---|---|---|---|",
    `| (none) | the kit's standard card | ${fill} | ${text} | none | ${corners} | ${padding} | — | Used when you name no look. |`,
    ...rows,
    "",
  ];
}

function linksSection(brand: BrandData): string[] {
  const lines = [
    "## Links",
    "Write every link with `kit.Link` (a text link) or `kit.Button`, never a bare `<a>`. A link to another",
    "page of this site is written `/` or `/<page>`; the kit points it at the right address wherever the",
    "site is published.",
  ];
  const link = drawnLink(brand, "link");
  if (!link.style) return [...lines, "The kit recorded no text-link style, so text links are underlined in the surrounding text's", "colour.", ""];
  const colour = link.parts.label ? partCell(brand, link, "label", "link colour") : "the surrounding text's colour";
  const hover = partsFromSlots(brand, link.style.states?.hover);
  const underline = link.parts.decoration === "underline" ? "underlined" : hover.parts.decoration === "underline" ? "underlined on hover" : "not underlined";
  const hoverColour = hover.parts.label ? `, ${hover.parts.label}${hover.tokens.label ? ` (${hover.tokens.label})` : ""} on hover` : "";
  return [...lines, `Text links look like the seller's own: ${colour}, ${underline}${hoverColour}.`, ""];
}

function motionSection(brand: BrandData): string[] {
  const entries = motionEntries(brand);
  const notes = motionNotes(brand);
  const lines = ["## Motion"];
  if (!entries.length) {
    lines.push("The seller's site shows no motion a page can reuse; nothing moves except the kit's buttons,", "links and cards.");
  } else {
    lines.push(
      "`kit.Button`, `kit.Link` and `kit.Card` already move the way the seller's site does on hover and",
      "press. Nothing else moves unless you add one of these classes to an element; write no transition or",
      "animation of your own.",
      "| class | what it does | timing | where the seller's site uses it |",
      "|---|---|---|---|",
      ...entries.map((entry) => `| \`${entry.className}\` | ${cellText(entry.describe)} | ${entry.timing} | ${cellText(entry.where)} |`),
      "Visitors who ask their device for less motion see every element still, in its final place.",
    );
  }
  if (notes.length) {
    const words: Record<string, string> = { canvas: "a canvas animation", video: "a video", scripted: "a scripted animation" };
    const list = notes.map((note) => `${words[note.kind] ?? note.kind} (${note.where})`).join("; ");
    lines.push(`The seller's site also moves in ways a published page cannot, because they need a script: ${list}. Do not imitate them.`);
  }
  return [...lines, ""];
}

function brandFile(brand: BrandData, seller?: string): string {
  const kit = brand.kit as {
    name?: string;
    brief?: { constraints?: Constraint[] };
    assets?: { logos?: Record<string, LogoEntry> };
  };
  const rules = (kit.brief?.constraints ?? [])
    .map((entry) => (typeof entry === "string" ? { rule: entry, scope: "" } : { rule: entry.rule ?? "", scope: entry.scope ?? "" }))
    .filter((entry) => entry.rule)
    .map((entry) => `- ${entry.rule.replace(/\s+/g, " ")}${entry.scope ? ` (${entry.scope})` : ""}`);
  const logos = Object.values(kit.assets?.logos ?? {}).flatMap((logo) =>
    (logo.variants ?? [])
      .map((variant) => {
        const file = brand.assets[variant.asset_id]?.file;
        const on = logo.allowed_backgrounds?.length ? `; on ${logo.allowed_backgrounds.join(", ")}` : "";
        return file ? `- \`${file}\`: ${logo.title ?? "logo"}, ${variant.name.replace(/_/g, " ")}${on}` : "";
      })
      .filter(Boolean),
  );
  const assets = Object.entries(brand.assets).map(
    ([key, asset]) => `- \`${asset.file}\` (${asset.kind}${key.startsWith("asset_") ? `, ${key}` : ""}): ${(asset.description ?? asset.label ?? "").replace(/\s+/g, " ").slice(0, 220)}`,
  );
  return [
    `# Brand: ${seller ?? kit.name ?? brand.slug}`,
    "",
    "Every brand section takes its colours, type, spacing, buttons and motion from these values. You",
    "choose by name (for example `surface: \"brand\"`); you never write a colour or a size.",
    "",
    ...surfacesSection(brand),
    ...typeSection(brand),
    ...spacingSection(brand),
    ...buttonsSection(brand),
    ...cardsSection(brand),
    ...linksSection(brand),
    ...motionSection(brand),
    ...(rules.length
      ? ["## The brand's own rules (from its brand kit)", "Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces table.", ...rules, ""]
      : []),
    "## Logos (always shown whole)",
    "`kit.Image` shows a logo whole: never cropped, never rounded.",
    ...(logos.length ? logos : ["This kit has no logo files."]),
    "",
    "## Assets (the only images and logos a page may use)",
    ...assets,
    "",
  ].join("\n");
}

/** The catalog for one brand, as {relative path: markdown}. `seller` titles brand/brand.md. */
export function buildCatalog(brand: BrandData, seller: string): Record<string, string> {
  const files: Record<string, string> = {};
  const clones = Object.values(brand.clones);

  const byPage = new Map<string, Clone[]>();
  for (const clone of clones) {
    const list = byPage.get(clone.page_url) ?? [];
    list.push(clone);
    byPage.set(clone.page_url, list);
  }
  const index = [
    "# Sections you can use",
    "",
    "Reuse comes first: start from the seller's own sections (clones), then our brand sections.",
    "",
    "## The seller's own sections (clones), by source page",
  ];
  for (const [page, list] of byPage) {
    index.push("", `### ${page}`);
    for (const clone of list.sort((a, b) => (a.section_index ?? 0) - (b.section_index ?? 0))) {
      index.push(
        `- \`${clone.id}\` · ${clone.role} · ${clone.label} · ${Object.keys(clone.slots).length} slots · catalog/clones/${clone.id}.md`,
      );
      files[`catalog/clones/${clone.id}.md`] = cloneFile(clone);
    }
  }
  index.push("", "## Brand sections (ours), see catalog/sections.md");
  for (const type of Object.keys(COMPONENT_SCHEMAS).filter((t) => t !== "ClonedSection")) {
    index.push(`- \`${type}\`: ${PURPOSE[type]}`);
  }
  files["catalog/index.md"] = index.join("\n") + "\n";
  files["catalog/sections.md"] = sectionsFile(brand);
  files["brand/brand.md"] = brandFile(brand, seller);
  return files;
}

