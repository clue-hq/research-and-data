// The agent's validator: contracts only (founder ruling 2026-10-08). The component schemas, real
// clone ids and slots, replacement text that exists, links, kit images, and (for now) one primary
// destination. Judgement (numbers and their sources, named people, wording from the brief's notes)
// is the agent's, in its prompt and skills, never a blocking check here. Each error says where it
// is, what is wrong and how to fix it.
//
// Usage: npx tsx scripts/validate-page.ts <workspace-dir>
// Reads <workspace>/.run.json ({brand, route}), page.json and shell.json.
// Prints {"valid": bool, "errors": ["where: message", ...]} as JSON.
import fs from "node:fs";
import path from "node:path";
import { parse } from "node-html-parser";
import { loadBrand } from "../lib/brands";
import type { Clone } from "../lib/clone";
import { PageSchema, ShellSchema, formatIssues } from "../puck/schemas";

type Item = { type: string; props: Record<string, unknown> };
type Page = { content?: Item[] };
type Shell = { header?: Record<string, unknown>; footer?: Record<string, unknown> };

const LINK = /^(https?:\/\/|\/|#|mailto:)/;
const visibleText = (clone: Clone) =>
  parse(clone.html.replace(/<br\s*\/?>/gi, " ")).structuredText.replace(/\s+/g, " ").trim();

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
