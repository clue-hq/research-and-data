// The agent's validator: the component schemas plus every check that needs the brand's data or
// the run's evidence. Each error says where it is, what is wrong and how to fix it.
//
// Usage: npx tsx scripts/validate-page.ts <workspace-dir>
// Reads <workspace>/.run.json ({brand, route}), page.json, shell.json, brief.md, research/,
// seller/ and fetched/. Prints {"valid": bool, "errors": ["where: message", ...]} as JSON.
import fs from "node:fs";
import path from "node:path";
import { parse } from "node-html-parser";
import { loadBrand, type BrandData } from "../lib/brands";
import type { Clone } from "../lib/clone";
import { PageSchema, ShellSchema, formatIssues } from "../puck/schemas";

type Item = { type: string; props: Record<string, unknown> };
type Page = { content?: Item[] };
type Shell = { header?: Record<string, unknown>; footer?: Record<string, unknown> };

const LINK = /^(https?:\/\/|\/|#|mailto:)/;
const NON_TEXT_PROPS = new Set([
  "id", "surface", "align", "headingRole", "imageSide", "image", "buttonHref", "linkHref", "fragmentId",
]);

function readTree(dir: string): string {
  if (!fs.existsSync(dir)) return "";
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(readTree(full));
    else if (/\.(md|txt|json|html?)$/i.test(entry.name)) out.push(fs.readFileSync(full, "utf-8"));
  }
  return out.join("\n");
}

const visibleText = (clone: Clone) =>
  parse(clone.html.replace(/<br\s*\/?>/gi, " ")).structuredText.replace(/\s+/g, " ").trim();

/** Every piece of visible text the agent wrote, with where it is. */
function writtenText(page: Page, shell: Shell, brand: BrandData): { where: string; text: string }[] {
  const out: { where: string; text: string }[] = [];
  (page.content ?? []).forEach((item, index) => {
    const at = `content.${index}(${String(item.props?.id ?? "?")})`;
    if (item.type === "ClonedSection") {
      const clone = brand.clones[String(item.props.fragmentId)];
      for (const [key, value] of Object.entries((item.props.slots as Record<string, unknown>) ?? {})) {
        const slot = clone?.slots[key];
        if (slot?.kind === "text" && typeof value === "string" && value !== String(slot.fallback ?? "")) {
          out.push({ where: `${at}.slots.${key}`, text: value });
        }
      }
      ((item.props.replacements as { replace?: string }[]) ?? []).forEach((r, i) => {
        if (r?.replace) out.push({ where: `${at}.replacements.${i}`, text: r.replace });
      });
      return;
    }
    for (const [key, value] of Object.entries(item.props ?? {})) {
      if (NON_TEXT_PROPS.has(key)) continue;
      if (typeof value === "string") out.push({ where: `${at}.${key}`, text: value });
      if (Array.isArray(value)) {
        value.forEach((entry, i) => {
          for (const [field, v] of Object.entries((entry as Record<string, unknown>) ?? {})) {
            if (typeof v === "string") out.push({ where: `${at}.${key}.${i}.${field}`, text: v });
          }
        });
      }
    }
  });
  for (const key of ["preparedFor", "ctaLabel"]) {
    const value = shell.header?.[key];
    if (typeof value === "string") out.push({ where: `shell.header.${key}`, text: value });
  }
  return out;
}

function notesShingles(brief: string): Map<string, string> {
  const start = brief.search(/Notes for Design/i);
  if (start < 0) return new Map();
  const notes = brief.slice(start).split("\n").slice(1);
  const shingles = new Map<string, string>();
  for (const line of notes) {
    if (/^THIS ARTIFACT/.test(line)) break;
    const words = line.toLowerCase().match(/[a-z0-9]+/g) ?? [];
    for (let i = 0; i + 4 <= words.length; i++) shingles.set(words.slice(i, i + 4).join(" "), line.trim());
  }
  return shingles;
}

export function validate(workspace: string): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  const run = JSON.parse(fs.readFileSync(path.join(workspace, ".run.json"), "utf-8")) as { brand: string };
  const brand = loadBrand(run.brand);
  const read = (file: string) => {
    const full = path.join(workspace, file);
    return fs.existsSync(full) ? fs.readFileSync(full, "utf-8") : "";
  };

  const missing = ["page.json", "shell.json"].filter((file) => !fs.existsSync(path.join(workspace, file)));
  if (missing.length) {
    return {
      valid: false,
      errors: missing.map((file) => `${file}: does not exist yet; create it with write_file (its shape is in the building-with-puck skill)`),
    };
  }

  let page: Page = {};
  let shell: Shell = {};
  try {
    page = JSON.parse(read("page.json") || "{}");
  } catch (error) {
    return { valid: false, errors: [`page.json: not valid JSON (${(error as Error).message})`] };
  }
  try {
    shell = JSON.parse(read("shell.json") || "{}");
  } catch (error) {
    return { valid: false, errors: [`shell.json: not valid JSON (${(error as Error).message})`] };
  }

  // Name sections by position and id everywhere, e.g. content.3(proof), so every error reads alike.
  const withIds = (line: string) =>
    line.replace(/^content\.(\d+)\.(?:props\.)?/, (_, n) => {
      const id = (page.content ?? [])[Number(n)]?.props?.id;
      return `content.${n}${id ? `(${String(id)})` : ""}.`;
    });
  const pageResult = PageSchema.safeParse(page);
  if (!pageResult.success) errors.push(...formatIssues(pageResult.error).split("\n").map((e) => `page.${withIds(e)}`));
  const shellResult = ShellSchema.safeParse(shell);
  if (!shellResult.success) errors.push(...formatIssues(shellResult.error).split("\n").map((e) => `shell.${e}`));

  const assetFiles = new Set(Object.values(brand.assets).map((asset) => asset.file));
  const imageAllowed = (value: unknown) =>
    value === "" || value === undefined || (typeof value === "string" && assetFiles.has(value));

  // Clones: real ids, real slots, matching replacements and links.
  (page.content ?? []).forEach((item, index) => {
    const at = `page.content.${index}(${String(item.props?.id ?? "?")})`;
    if (item.type === "ClonedSection") {
      const id = String(item.props.fragmentId ?? "");
      const clone = brand.clones[id];
      if (!clone) {
        if (/^frag_[0-9a-f]{16}$/.test(id)) errors.push(`${at}.fragmentId: "${id}" is not one of this brand's clones; see catalog/index.md`);
        return;
      }
      const card = `catalog/clones/${id}.md`;
      for (const [key, value] of Object.entries((item.props.slots as Record<string, unknown>) ?? {})) {
        const slot = clone.slots[key];
        if (!slot) {
          errors.push(`${at}.slots.${key}: "${key}" is not a slot of ${id}; its slots are ${Object.keys(clone.slots).join(", ")} (${card})`);
          continue;
        }
        if (slot.kind === "text" && typeof value !== "string") errors.push(`${at}.slots.${key}: a text slot takes a string`);
        if (slot.kind === "href" && (typeof value !== "string" || (value !== "" && !LINK.test(value)))) {
          errors.push(`${at}.slots.${key}: a link slot takes an https:// URL, a /route or a #anchor`);
        }
        if (slot.kind === "image" && !imageAllowed(value)) {
          errors.push(`${at}.slots.${key}: image "${String(value)}" is not in the brand's assets; pick a file from brand/brand.md`);
        }
        if (slot.kind === "visibility" && typeof value !== "boolean") errors.push(`${at}.slots.${key}: a visibility slot takes true or false`);
      }
      const text = visibleText(clone);
      ((item.props.replacements as { find?: string }[]) ?? []).forEach((r, i) => {
        const find = (r?.find ?? "").replace(/\s+/g, " ").trim();
        if (find && !text.includes(find)) {
          errors.push(`${at}.replacements.${i}: "${find}" is not text in ${id}; use exact text from "Other visible text" in ${card}`);
        }
      });
      const hrefs = new Set(parse(clone.html).querySelectorAll("a[href]").map((a) => a.getAttribute("href")));
      ((item.props.links as { find?: string }[]) ?? []).forEach((l, i) => {
        if (l?.find && l.find !== "*" && !hrefs.has(l.find)) {
          errors.push(`${at}.links.${i}: no link "${l.find}" in ${id}; use an href from ${card}, or "*" for every link`);
        }
      });
    }
    if (item.type === "FeatureSplit" && !imageAllowed(item.props.image)) {
      errors.push(`${at}.image: "${String(item.props.image)}" is not in the brand's assets; pick a file from brand/brand.md`);
    }
  });
  const accountLogo = shell.header?.accountLogo;
  if (accountLogo && !imageAllowed(accountLogo) && !String(accountLogo).startsWith("/accounts/")) {
    errors.push(`shell.header.accountLogo: "${String(accountLogo)}" is neither a brand asset nor an account asset`);
  }

  // One primary destination: every button that leaves the site goes to the same place.
  const destinations = new Map<string, string[]>();
  const addDestination = (href: unknown, where: string) => {
    if (typeof href !== "string" || !/^https?:\/\//.test(href)) return;
    destinations.set(href, [...(destinations.get(href) ?? []), where]);
  };
  addDestination(shell.header?.ctaHref, "shell.header.ctaHref");
  (page.content ?? []).forEach((item, index) => {
    const at = `content.${index}(${String(item.props?.id ?? "?")})`;
    if (item.type === "ClonedSection") {
      for (const [key, value] of Object.entries((item.props.slots as Record<string, unknown>) ?? {})) {
        if (key.startsWith("cta")) addDestination(value, `${at}.slots.${key}`);
      }
    }
    if ((item.type === "FeatureSplit" && item.props.buttonLabel) || item.type === "CtaBand") {
      addDestination(item.props.buttonHref, `${at}.buttonHref`);
    }
  });
  if (destinations.size > 1) {
    const list = [...destinations].map(([href, where]) => `${href} (${where.join(", ")})`).join("; ");
    errors.push(`page: a 1:1 page has one primary destination, but buttons go to ${destinations.size}: ${list}`);
  }

  // Numbers on the page must come from the evidence (research, seller files, fetched pages, the
  // brief, or the seller's own published wording in its clones).
  const corpus = [
    read("brief.md"),
    readTree(path.join(workspace, "research")),
    readTree(path.join(workspace, "seller")),
    readTree(path.join(workspace, "fetched")),
    ...Object.values(brand.clones).map(visibleText),
  ]
    .join("\n")
    .replace(/,(?=\d{3})/g, "");
  const written = writtenText(page, shell, brand);
  for (const { where, text } of written) {
    for (const match of text.matchAll(/[$€£]?\d[\d,]*(?:\.\d+)?%?/g)) {
      const token = match[0];
      const digits = token.replace(/[$€£%,]/g, "");
      const significant = /[%$€£.]/.test(token) || digits.replace(".", "").length >= 3;
      if (significant && !corpus.includes(digits)) {
        errors.push(`page.${where}: number "${token}" is not in the research, seller files or fetched pages; open its source with fetch_page, or remove it`);
      }
    }
  }

  // Wording from the brief's internal notes never reaches the page.
  const shingles = notesShingles(read("brief.md"));
  for (const { where, text } of written) {
    const words = text.toLowerCase().match(/[a-z0-9]+/g) ?? [];
    for (let i = 0; i + 4 <= words.length; i++) {
      const note = shingles.get(words.slice(i, i + 4).join(" "));
      if (note) {
        errors.push(`page.${where}: repeats wording from the brief's "Notes for Design" ("${words.slice(i, i + 4).join(" ")}", from: ${note}); notes are for you, never the page`);
        break;
      }
    }
  }

  // People named in the account's research are never named on the page.
  const people = (() => {
    try {
      return JSON.parse(read("research/people.json") || "[]") as string[];
    } catch {
      return [];
    }
  })();
  for (const { where, text } of written) {
    for (const name of people) {
      if (name && text.toLowerCase().includes(name.toLowerCase())) {
        errors.push(`page.${where}: names "${name}", a person at the account; account pages never name people`);
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

if (process.argv[1]?.endsWith("validate-page.ts")) {
  const workspace = process.argv[2];
  if (!workspace) {
    console.error("usage: validate-page.ts <workspace>");
    process.exit(2);
  }
  console.log(JSON.stringify(validate(workspace)));
}
