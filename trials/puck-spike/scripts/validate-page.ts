// The agent's validator: contracts only (founder ruling 2026-10-08). The component schemas, real
// clone ids and slots, replacement text that exists, links, kit images, and (for now) one primary
// destination. Judgement (numbers and their sources, named people, wording from the brief's notes)
// is the agent's, in its prompt and skills, never a blocking check here. Each error says where it
// is, what is wrong and how to fix it.
//
// Usage: npx tsx scripts/validate-page.ts <workspace-dir>
// Reads <workspace>/.run.json ({brand}), page.json (the home page, "/"), pages/<name>.json (the
// site's other pages, "/<name>") and shell.json. Links the page writes to "/<name>" must go to a
// page that exists.
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
const PAGE_NAME = /^[a-z0-9][a-z0-9-]*$/;
const visibleText = (clone: Clone) =>
  parse(clone.html.replace(/<br\s*\/?>/gi, " ")).structuredText.replace(/\s+/g, " ").trim();

export function validate(workspace: string): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  const run = JSON.parse(fs.readFileSync(path.join(workspace, ".run.json"), "utf-8")) as { brand: string };
  const brand = loadBrand(run.brand);

  const missing = ["page.json", "shell.json"].filter((file) => !fs.existsSync(path.join(workspace, file)));
  if (missing.length) {
    return {
      valid: false,
      errors: missing.map((file) => `${file}: does not exist yet; create it with write_file (its shape is in the building-with-puck skill)`),
    };
  }

  // The site's pages: page.json is "/", pages/<name>.json is "/<name>". Errors name the file the
  // way the agent wrote it: "page.content.3(proof)…" or "pages/analysis.content.0(hero)…".
  const files: { route: string; file: string; where: string }[] = [{ route: "/", file: "page.json", where: "page" }];
  const pagesDir = path.join(workspace, "pages");
  if (fs.existsSync(pagesDir)) {
    for (const name of fs.readdirSync(pagesDir).filter((n) => n.endsWith(".json")).sort()) {
      const stem = name.replace(/\.json$/, "");
      if (!PAGE_NAME.test(stem)) {
        errors.push(`pages/${name}: a page name uses lowercase letters, digits and dashes (for example pages/analysis.json)`);
        continue;
      }
      files.push({ route: `/${stem}`, file: `pages/${name}`, where: `pages/${stem}` });
    }
  }
  const pages: { route: string; where: string; page: Page }[] = [];
  for (const entry of files) {
    try {
      pages.push({ ...entry, page: JSON.parse(fs.readFileSync(path.join(workspace, entry.file), "utf-8") || "{}") });
    } catch (error) {
      errors.push(`${entry.file}: not valid JSON (${(error as Error).message})`);
    }
  }
  let shell: Shell = {};
  try {
    shell = JSON.parse(fs.readFileSync(path.join(workspace, "shell.json"), "utf-8") || "{}");
  } catch (error) {
    return { valid: false, errors: [...errors, `shell.json: not valid JSON (${(error as Error).message})`] };
  }
  if (errors.length && !pages.length) return { valid: false, errors };

  const shellResult = ShellSchema.safeParse(shell);
  if (!shellResult.success) errors.push(...formatIssues(shellResult.error).split("\n").map((e) => `shell.${e}`));

  const assetFiles = new Set(Object.values(brand.assets).map((asset) => asset.file));
  const imageAllowed = (value: unknown) =>
    value === "" || value === undefined || (typeof value === "string" && assetFiles.has(value));

  // Links the page writes (not the clones' own captured links, which keep pointing at the seller).
  const written: { where: string; href: string }[] = [];
  const addWritten = (href: unknown, where: string) => {
    if (typeof href === "string" && href) written.push({ where, href });
  };
  // One primary destination: every button that leaves the site goes to the same place.
  const destinations = new Map<string, string[]>();
  const addDestination = (href: unknown, where: string) => {
    if (typeof href !== "string" || !/^https?:\/\//.test(href)) return;
    destinations.set(href, [...(destinations.get(href) ?? []), where]);
  };

  for (const { where: file, page } of pages) {
    // Name sections by position and id everywhere, e.g. content.3(proof), so every error reads alike.
    const withIds = (line: string) =>
      line.replace(/^content\.(\d+)\.(?:props\.)?/, (_, n) => {
        const id = (page.content ?? [])[Number(n)]?.props?.id;
        return `content.${n}${id ? `(${String(id)})` : ""}.`;
      });
    const pageResult = PageSchema.safeParse(page);
    if (!pageResult.success) errors.push(...formatIssues(pageResult.error).split("\n").map((e) => `${file}.${withIds(e)}`));

    // Clones: real ids, real slots, matching replacements and links.
    (page.content ?? []).forEach((item, index) => {
      const at = `${file}.content.${index}(${String(item.props?.id ?? "?")})`;
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
          if (slot.kind === "href" && value !== String(slot.fallback ?? "")) addWritten(value, `${at}.slots.${key}`);
          if (slot.kind === "href" && key.startsWith("cta")) addDestination(value, `${at}.slots.${key}`);
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
        ((item.props.links as { find?: string; replace?: string }[]) ?? []).forEach((l, i) => {
          if (l?.find && l.find !== "*" && !hrefs.has(l.find)) {
            errors.push(`${at}.links.${i}: no link "${l.find}" in ${id}; use an href from ${card}, or "*" for every link`);
          }
          addWritten(l?.replace, `${at}.links.${i}`);
        });
      }
      if (item.type === "FeatureSplit" && !imageAllowed(item.props.image)) {
        errors.push(`${at}.image: "${String(item.props.image)}" is not in the brand's assets; pick a file from brand/brand.md`);
      }
      if ((item.type === "FeatureSplit" && item.props.buttonLabel) || item.type === "CtaBand") {
        addDestination(item.props.buttonHref, `${at}.buttonHref`);
        addWritten(item.props.buttonHref, `${at}.buttonHref`);
      }
      if (item.type === "ProofCard") addWritten(item.props.linkHref, `${at}.linkHref`);
    });
  }

  const accountLogo = shell.header?.accountLogo;
  if (accountLogo && !imageAllowed(accountLogo) && !String(accountLogo).startsWith("/accounts/")) {
    errors.push(`shell.header.accountLogo: "${String(accountLogo)}" is neither a brand asset nor an account asset`);
  }
  addDestination(shell.header?.ctaHref, "shell.header.ctaHref");
  addWritten(shell.header?.ctaHref, "shell.header.ctaHref");
  ((shell.header?.nav as { href?: string }[] | undefined) ?? []).forEach((item, i) => addWritten(item?.href, `shell.header.nav.${i}.href`));
  addWritten(shell.footer?.privacyHref, "shell.footer.privacyHref");
  addWritten(shell.footer?.termsHref, "shell.footer.termsHref");

  if (destinations.size > 1) {
    const list = [...destinations].map(([href, where]) => `${href} (${where.join(", ")})`).join("; ");
    errors.push(`site: a 1:1 page has one primary destination, but buttons go to ${destinations.size}: ${list}`);
  }

  // A link to another page of this site must go to a page that exists.
  const routes = new Set(pages.map((p) => p.route));
  for (const { where, href } of written) {
    if (!href.startsWith("/") || href.startsWith("//")) continue;
    const route = href.split(/[?#]/)[0].replace(/(.)\/$/, "$1") || "/";
    if (!routes.has(route)) {
      errors.push(
        `${where}: links to ${route}, which is not a page of this site; its pages are ${[...routes].join(", ")} (a new page is pages/<name>.json)`,
      );
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
