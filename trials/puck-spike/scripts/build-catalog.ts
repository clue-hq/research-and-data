// The agent's catalog: a bounded, plain-file map of everything a page can be built from, so the
// agent reads a short list instead of raw HTML or CSS (our version of Ploy's page-build plan).
//
//   catalog/index.md          every section available, one line each, clones in source-page order
//   catalog/clones/<id>.md    one clone: source, slots (kind + original wording), other visible
//                             text (for text replacements), links, images
//   catalog/sections.md       our own sections: purpose, fields and allowed choices (from the schemas)
//   brand/brand.md            the brand's token choices in words, the button, and the asset list
//
// Usage: npx tsx scripts/build-catalog.ts <brand> <out-dir>
import fs from "node:fs";
import path from "node:path";
import { parse, TextNode, type HTMLElement } from "node-html-parser";
import { z } from "zod";
import { loadBrand, type BrandData } from "../lib/brands";
import type { Clone } from "../lib/clone";
import { COMPONENT_SCHEMAS, SURFACES, SURFACE_LABELS } from "../puck/schemas";

/** What each surface choice maps to in the brand kit. */
const SURFACE_ROLE: Record<(typeof SURFACES)[number], string> = {
  page: "surface.page",
  card: "surface.card",
  muted: "surface.muted",
  brandSubtle: "surface.brand.subtle",
  brand: "surface.brand",
  inverse: "surface.inverse",
};

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

function sectionsFile(): string {
  const parts = [
    "# Brand sections (ours)",
    "",
    "These are built from the brand's tokens, so every choice below stays on brand. Style options",
    "are fixed choices; there are no colour, size, class or style fields.",
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
      const choices = spec.enum
        ? spec.enum.map((value) => (field === "surface" ? `${value} (${SURFACE_LABELS[value as keyof typeof SURFACE_LABELS]})` : value)).join(", ")
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

type Token = { value: { default: Record<string, unknown> } };

function brandFile(brand: BrandData): string {
  const kit = brand.kit as {
    name?: string;
    tokens: { colors: Record<string, Token>; typography: Record<string, Token> };
    constraints?: { contrast_pairs?: { background: string; foreground: string }[] };
  };
  const color = (role: string) => String(kit.tokens.colors[role]?.value.default.value ?? "");
  const pairs = kit.constraints?.contrast_pairs ?? [];
  const surfaces = SURFACES.map((choice) => {
    const role = SURFACE_ROLE[choice];
    const ink = pairs.find((pair) => pair.background === role)?.foreground ?? "chosen by contrast";
    return `| ${choice} | ${SURFACE_LABELS[choice]} | ${color(role)} | ${ink}${ink.startsWith("text.") ? ` ${color(ink)}` : ""} |`;
  });
  const typeRow = (role: string) => {
    const style = kit.tokens.typography[`type.${role}`]?.value.default as
      | { font_family: string; font_size: number; font_weight: number }
      | undefined;
    return style ? `| ${role} | ${style.font_family} | ${style.font_size}px | ${style.font_weight} |` : "";
  };
  const button = brand.measured?.primary_button;
  const heading = brand.measured?.heading_on_light;
  const assets = Object.entries(brand.assets).map(
    ([key, asset]) => `- \`${asset.file}\` (${asset.kind}${key.startsWith("asset_") ? `, ${key}` : ""}): ${(asset.description ?? asset.label ?? "").replace(/\s+/g, " ").slice(0, 220)}`,
  );
  return [
    `# Brand: ${kit.name ?? brand.slug}`,
    "",
    "Every brand section takes its colours, type and buttons from these values. You choose by name",
    "(for example `surface: \"brand\"`); you never write a colour or a size.",
    "",
    "## Surfaces",
    "| choice | name | colour | text on it |",
    "|---|---|---|---|",
    ...surfaces,
    "",
    "## Heading sizes and body text",
    "| role | font | size at 1440 | weight |",
    "|---|---|---|---|",
    typeRow("display"),
    typeRow("headline"),
    typeRow("title"),
    typeRow("body"),
    "",
    heading ? `Headings on light surfaces use the brand's heading ink ${heading.color}.` : "",
    "",
    "## Button",
    button
      ? `The brand's primary button, measured from its own hero: background ${button.background}, text ${button.color}, radius ${button.borderRadius}, ${button.fontWeight} weight. On dark surfaces it switches to its light version automatically.`
      : "No measured button; the brand surface colour is used.",
    "",
    "## Assets (the only images and logos a page may use)",
    ...assets,
    "",
  ].join("\n");
}

export function buildCatalog(slug: string, outDir: string): void {
  const brand = loadBrand(slug);
  const clones = Object.values(brand.clones);
  fs.mkdirSync(path.join(outDir, "catalog", "clones"), { recursive: true });
  fs.mkdirSync(path.join(outDir, "brand"), { recursive: true });

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
      fs.writeFileSync(path.join(outDir, "catalog", "clones", `${clone.id}.md`), cloneFile(clone));
    }
  }
  index.push("", "## Brand sections (ours), see catalog/sections.md");
  for (const type of Object.keys(COMPONENT_SCHEMAS).filter((t) => t !== "ClonedSection")) {
    index.push(`- \`${type}\`: ${PURPOSE[type]}`);
  }
  fs.writeFileSync(path.join(outDir, "catalog", "index.md"), index.join("\n") + "\n");
  fs.writeFileSync(path.join(outDir, "catalog", "sections.md"), sectionsFile());
  fs.writeFileSync(path.join(outDir, "brand", "brand.md"), brandFile(brand));
}

if (process.argv[1]?.endsWith("build-catalog.ts") && process.argv[2]) {
  buildCatalog(process.argv[2], process.argv[3] ?? path.join("agent-runs", "catalog", process.argv[2]));
  console.log("catalog written");
}
