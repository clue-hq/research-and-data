// The agent's validator: contracts only (founder ruling 2026-10-08). The component schemas, real
// clone ids and slots, replacement text that exists, links, kit images, and (for now) one primary
// destination. Judgement (numbers and their sources, named people, wording from the brief's notes)
// is the agent's, in its prompt and skills, never a blocking check here. Each error says where it
// is, what is wrong and how to fix it.
//
// Pure: the caller hands over the site's files, the brand and the site's agent-written sections.
// `files.pages` maps a route to its page: "/" is page.json (the home page), "/<name>" is
// pages/<name>.json (the site's other pages). `files.shell` is shell.json, or null when it does not
// exist yet. A page or shell given as a string is that file's text and is parsed here. Links the
// page writes to "/<name>" must go to a page that exists.
// Returns {valid, errors: ["where: message", ...]}.
import { parse } from "node-html-parser";
import type { BrandData } from "./brand";
import { replaceableTexts } from "./clone";
import { editsOf, editsProblems, withoutEdits } from "./edits";
import { buttonLooks, cardLooks } from "./looks";
import { isRichLink, richLinks, richProblems } from "./rich";
import { richValuesOfItem } from "./rich-props";
import { ShellSchema, formatIssues, pageSchemaWith } from "./schemas";
import { surfaceChoices } from "./surfaces";

type Item = { type: string; props: Record<string, unknown> };
type Page = { content?: Item[] };
type Shell = { header?: Record<string, unknown>; footer?: Record<string, unknown> };

/** The site's files: route -> page JSON ("/" is page.json, "/<name>" is pages/<name>.json), and shell.json. */
export type SiteFiles = { pages: Record<string, unknown>; shell: unknown | null };
/** A site's agent-written sections, as the validator needs them: only the schema (E5). The design
 * API builds each one from the section's STORED props JSON Schema (bin/validate-site.ts). */
export type AgentSectionSchemas = Record<
  string,
  {
    schema: { safeParse: (value: unknown) => { success: boolean } };
    /** The section's stored props JSON Schema: the props it marked for editing in place are rich text. */
    propsSchema?: unknown;
  }
>;
/** Images a site may use besides the brand's assets: the ones generated for it, and the account's
 * own logos (the header's accountLogo only). Every one is /asset-store/<sha256> (Contract 1). */
export type SiteImages = { siteImages: string[]; accountLogos: string[] };
const NO_IMAGES: SiteImages = { siteImages: [], accountLogos: [] };
/** A string that names stored bytes: production's /asset-store/<sha256>, or one of the spike's
 * old prefixes, which are never in the allowed set and so are refused. */
const IMAGE_PATH = /^\/(asset-store|brands|generated|accounts)\//;

const PAGE_NAME = /^[a-z0-9][a-z0-9-]*$/;
/** A file given as text is parsed (an empty file reads as {}); a parsed value is used as is. */
const fromFile = (value: unknown): unknown => (typeof value === "string" ? JSON.parse(value || "{}") : value);

export function validateSite(
  files: SiteFiles,
  brand: BrandData,
  agentSections: AgentSectionSchemas,
  images: SiteImages = NO_IMAGES,
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  // This site's agent-written sections (E5) are valid section types here, and only here.
  const PageSchema = pageSchemaWith(
    Object.fromEntries(Object.entries(agentSections).map(([name, module]) => [name, module.schema as never])),
  );

  const missing = [
    ...(files.pages["/"] === undefined ? ["page.json"] : []),
    ...(files.shell === null || files.shell === undefined ? ["shell.json"] : []),
  ];
  if (missing.length) {
    return {
      valid: false,
      errors: missing.map((file) => `${file}: does not exist yet; create it with write_file (its shape is in the building-with-puck skill)`),
    };
  }

  // The site's pages: page.json is "/", pages/<name>.json is "/<name>". Errors name the file the
  // way the agent wrote it: "page.content.3(proof)…" or "pages/analysis.content.0(hero)…".
  const entries: { route: string; file: string; where: string }[] = [{ route: "/", file: "page.json", where: "page" }];
  const others = Object.keys(files.pages)
    .filter((route) => route !== "/")
    .map((route) => ({ route, name: `${route.replace(/^\//, "")}.json` }))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const { route, name } of others) {
    const stem = name.replace(/\.json$/, "");
    if (!PAGE_NAME.test(stem)) {
      errors.push(`pages/${name}: a page name uses lowercase letters, digits and dashes (for example pages/analysis.json)`);
      continue;
    }
    entries.push({ route, file: `pages/${name}`, where: `pages/${stem}` });
  }
  const pages: { route: string; where: string; page: Page }[] = [];
  for (const entry of entries) {
    try {
      pages.push({ route: entry.route, where: entry.where, page: fromFile(files.pages[entry.route]) as Page });
    } catch (error) {
      errors.push(`${entry.file}: not valid JSON (${(error as Error).message})`);
    }
  }
  let shell: Shell = {};
  try {
    shell = fromFile(files.shell) as Shell;
  } catch (error) {
    return { valid: false, errors: [...errors, `shell.json: not valid JSON (${(error as Error).message})`] };
  }
  if (errors.length && !pages.length) return { valid: false, errors };

  const shellResult = ShellSchema.safeParse(shell);
  if (!shellResult.success) errors.push(...formatIssues(shellResult.error).split("\n").map((e) => `shell.${e}`));

  const allowedImages = new Set([...Object.values(brand.assets).map((asset) => asset.file), ...images.siteImages]);
  const accountLogos = new Set(images.accountLogos);
  const imageAllowed = (value: unknown) =>
    value === "" || value === undefined || (typeof value === "string" && allowedImages.has(value));
  // One wording for every refused image (the spike's R3 text, founder-approved 2026-10-09).
  const imageError = (where: string, value: unknown) =>
    `${where}: image "${String(value)}" is not in the brand's assets; pick a file from brand/brand.md`;
  // Surfaces and button styles are the brand's (founder rulings 4 and Q4 = (b)): a contract, like
  // clone ids. The refusals name what this brand has.
  const surfaceNames = surfaceChoices(brand).map((choice) => choice.value);
  const lookNames = buttonLooks(brand).map((look) => look.name);
  const cardNames = cardLooks(brand).map((look) => look.name);
  const surfaceError = (where: string, value: string) =>
    `${where}: "${value}" is not one of this brand's surfaces; its surfaces are ${surfaceNames.join(", ")} (brand/brand.md, Surfaces)`;
  const lookError = (where: string, value: string) =>
    lookNames.length
      ? `${where}: "${value}" is not one of this brand's button styles; its styles are ${lookNames.join(", ")}, or leave it empty for the standard button (brand/brand.md, Buttons)`
      : `${where}: this brand's kit records no button styles; leave it empty for the standard button (brand/brand.md, Buttons)`;
  const OURS = new Set(["StatsBand", "FeatureSplit", "ProofCard", "CtaBand"]);
  // Manual styling (`_edits`) names the brand's colour tokens and font families: a contract, like
  // surfaces. Its shape is the schema's; a malformed `_edits` is reported there, not again here.
  const addEditsProblems = (props: Record<string, unknown> | undefined, where: string) => {
    for (const line of editsProblems(editsOf(props ?? {}), brand)) errors.push(`${where}._edits.${line}`);
  };

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

  // Rich text (plan 2): the grammar, and each of its links to a real page like any other link.
  const checkRich = (value: unknown, where: string) => {
    if (typeof value !== "string" || value === "") return;
    const problems = richProblems(value);
    for (const problem of problems) errors.push(`${where}: ${problem}`);
    if (!problems.length) for (const href of richLinks(value)) addWritten(href, where);
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
      addEditsProblems(item.props, at);
      for (const { path, value } of richValuesOfItem(item, brand, (type) => agentSections[type]?.propsSchema)) checkRich(value, `${at}.${path}`);
      if (OURS.has(item.type)) {
        const surface = item.props.surface;
        if (typeof surface === "string" && !surfaceNames.includes(surface)) errors.push(surfaceError(`${at}.surface`, surface));
        const look = item.props.buttonLook;
        if (typeof look === "string" && look && !lookNames.includes(look)) errors.push(lookError(`${at}.buttonLook`, look));
      }
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
          if (slot.kind === "href" && (typeof value !== "string" || (value !== "" && !isRichLink(value)))) {
            errors.push(`${at}.slots.${key}: a link slot takes an https:// URL, a /route or a #anchor`);
          }
          if (slot.kind === "href" && value !== String(slot.fallback ?? "")) addWritten(value, `${at}.slots.${key}`);
          if (slot.kind === "href" && key.startsWith("cta")) addDestination(value, `${at}.slots.${key}`);
          if (slot.kind === "image" && !imageAllowed(value)) {
            errors.push(imageError(`${at}.slots.${key}`, value));
          }
          if (slot.kind === "visibility" && typeof value !== "boolean") errors.push(`${at}.slots.${key}: a visibility slot takes true or false`);
        }
        // Only whole text nodes, as the renderer replaces them (review finding S1-3).
        const replaceable = replaceableTexts(clone);
        ((item.props.replacements as { find?: string }[]) ?? []).forEach((r, i) => {
          const find = (r?.find ?? "").replace(/\s+/g, " ").trim();
          if (find && !replaceable.includes(find)) {
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
        errors.push(imageError(`${at}.image`, item.props.image));
      }
      if ((item.type === "FeatureSplit" && item.props.buttonLabel) || item.type === "CtaBand") {
        addDestination(item.props.buttonHref, `${at}.buttonHref`);
        addWritten(item.props.buttonHref, `${at}.buttonHref`);
      }
      if (item.type === "ProofCard") addWritten(item.props.linkHref, `${at}.linkHref`);
      if (item.type in agentSections) {
        // An agent section's images must be the brand's (or this site's). Its links — props named
        // …Href — must reach real pages, and a link prop named for a cta or a button is a primary
        // destination like any other button's (Wave 2 Lane A, Task 6).
        const walk = (value: unknown, where: string, key: string) => {
          if (typeof value === "string") {
            if (/^surface$|Surface$/.test(key) && !surfaceNames.includes(value)) {
              errors.push(surfaceError(where, value));
              return;
            }
            if (/^cardLook$|CardLook$/.test(key)) {
              if (value && !cardNames.includes(value)) {
                errors.push(`${where}: "${value}" is not one of this brand's card styles; its styles are ${cardNames.join(", ")}, or leave it out for the standard card (brand/brand.md, Cards)`);
              }
              return;
            }
            if (/^look$|Look$/.test(key)) {
              if (value && !lookNames.includes(value)) errors.push(lookError(where, value));
              return;
            }
            if (IMAGE_PATH.test(value)) {
              if (!imageAllowed(value)) errors.push(imageError(where, value));
            } else if (/href$/i.test(key)) {
              addWritten(value, where);
              if (/cta|button/i.test(key)) addDestination(value, where);
            }
          } else if (Array.isArray(value)) value.forEach((v, i) => walk(v, `${where}.${i}`, key));
          else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) walk(v, `${where}.${k}`, k);
        };
        walk(withoutEdits(item.props), at, "");
      }
    });
  }

  addEditsProblems(shell.header, "shell.header");
  addEditsProblems(shell.footer, "shell.footer");
  const accountLogo = shell.header?.accountLogo;
  if (accountLogo && !imageAllowed(accountLogo) && !accountLogos.has(String(accountLogo))) {
    errors.push(`shell.header.accountLogo: "${String(accountLogo)}" is not this account's logo; use a file from "The account's logo" in brand/brand.md, or leave it empty`);
  }
  const ctaLook = shell.header?.ctaLook;
  if (typeof ctaLook === "string" && ctaLook && !lookNames.includes(ctaLook)) errors.push(lookError("shell.header.ctaLook", ctaLook));
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
