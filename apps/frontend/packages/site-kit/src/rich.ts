// Rich text (site element inspector, plan 2; spec §4.4 as changed by plan 2's ruling R1). Text a
// marketer edits in place may hold a small, closed, INLINE-ONLY grammar of HTML:
//
//   <strong> <em> <u> <s>        bold, italic, underline, strike (<b> and <i> are read as strong / em)
//   <br>                          a line break
//   <a href="…" data-new-tab>     a link: https://, a /page of this site, a #anchor or mailto:
//   <span data-s="<key>">         highlighted words styled by hand: the key is an `_edits` entry
//
// optionally inside the ONE outer <p> the editor writes (the render drops it). No other tag, no other
// attribute, no inline style: a span's look is its `_edits` override, validated like any element's.
//
// The text is read into RUNS — stretches of characters with the same marks — so styling or linking a
// range of words is a pure function over the stored string (the app writes the result; the frame only
// reports which characters were highlighted). Pure and dependency-free: the published page's runtime
// draws rich text with `richHtml` and carries no HTML parser.
import { ElementKeySchema, type Edits, type StyleOverride } from "./edits";

export type RichLink = { href: string; newTab: boolean };
export type Run = {
  text: string;
  /** A line break: no characters (as the browser's textContent counts it). */
  br?: true;
  strong?: true;
  em?: true;
  u?: true;
  s?: true;
  link?: RichLink;
  /** The `_edits` key of the styled span the words sit in. */
  style?: string;
};

/** A link's address: http(s)://, a /page of this site (never a protocol-relative "//host"), a #anchor
 * or mailto:, with no spaces. The one rule for rich text, the editor and the inspector's Link row. */
export const RICH_LINK = /^(https?:\/\/|\/(?!\/)|#|mailto:)/;
export const isRichLink = (href: string) => RICH_LINK.test(href) && !/\s/.test(href);
const LINK_RULE = "a link must be an https:// address, a /page of this site, a #anchor or mailto:";

type Mark = "strong" | "em" | "u" | "s";
const MARK_TAGS: Record<string, Mark> = { strong: "strong", b: "strong", em: "em", i: "em", u: "u", s: "s" };
const MARK_ORDER: Mark[] = ["strong", "em", "u", "s"];

// ---------------------------------------------------------------------------------------------
// Reading

type Token =
  | { kind: "text"; text: string; raw: string }
  | { kind: "open" | "close" | "void"; tag: string; attrs: [string, string | null][]; raw: string }
  | { kind: "stray"; raw: string };

const NAMED: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

/** HTML character references to characters; an `&` that starts none stays an `&`. */
export function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]{1,6}|#[0-9]{1,7}|[a-z]{2,8});/gi, (whole, name: string) => {
    if (name[0] === "#") {
      const code = name[1] === "x" || name[1] === "X" ? Number.parseInt(name.slice(2), 16) : Number.parseInt(name.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
    }
    return NAMED[name.toLowerCase()] ?? whole;
  });
}

// No "<" inside an attribute name, so a "<" that starts no tag fails at the next "<" (linear time).
const TAG = /<(\/?)([A-Za-z][A-Za-z0-9-]*)((?:\s+[^\s=>/"'<]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*(\/?)>/y;
const ATTR = /([^\s=>/"']+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
const DROP_WHOLE = new Set(["script", "style", "template", "noscript", "svg", "iframe", "object", "textarea", "title"]);

/** The string as tags and text. A "<" that starts no tag is `stray` (text in a lenient read, an error
 * in a strict one). Comments are dropped. */
function tokenize(html: string): Token[] {
  const tokens: Token[] = [];
  let text = "";
  const flush = () => {
    if (text) tokens.push({ kind: "text", raw: text, text: decodeEntities(text) });
    text = "";
  };
  let i = 0;
  while (i < html.length) {
    const lt = html.indexOf("<", i);
    if (lt === -1) {
      text += html.slice(i);
      break;
    }
    text += html.slice(i, lt);
    if (html.startsWith("<!--", lt)) {
      const end = html.indexOf("-->", lt + 4);
      i = end === -1 ? html.length : end + 3;
      continue;
    }
    TAG.lastIndex = lt;
    const match = TAG.exec(html);
    if (!match) {
      flush();
      tokens.push({ kind: "stray", raw: "<" });
      i = lt + 1;
      continue;
    }
    flush();
    const tag = match[2].toLowerCase();
    const attrs: [string, string | null][] = [];
    for (const attr of match[3].matchAll(ATTR)) {
      const value = attr[2] ?? attr[3] ?? attr[4];
      attrs.push([attr[1].toLowerCase(), value === undefined ? null : decodeEntities(value)]);
    }
    const kind = match[1] ? "close" : match[4] || tag === "br" ? "void" : "open";
    tokens.push({ kind, tag, attrs, raw: match[0] });
    i = lt + match[0].length;
  }
  flush();
  return tokens;
}

type Frame = { tag: string; mark?: Mark; link?: RichLink; style?: string };

/** Read tokens into runs. `strict`: the first thing outside the grammar is the result's error.
 * Otherwise every unknown tag is dropped with its text kept (script and style with their text), bad
 * attributes are dropped, and paragraph breaks become line breaks. */
/** What a text may hold beyond the base marks: `links: false` for a button's words (a link may not
 * hold a link; plan 3). */
export type RichOptions = { links?: boolean };

function read(html: string, strict: boolean, options: RichOptions = {}): { runs: Run[] } | { error: string } {
  const links = options.links !== false;
  const tokens = tokenize(html);
  const runs: Run[] = [];
  const stack: Frame[] = [];
  let dropping: string | null = null;
  // One outer <p> is the editor's own wrapper: in a strict read it is allowed only around everything.
  let paragraphs = 0;
  const firstTag = tokens.find((token) => token.kind !== "text" || token.text.trim() !== "");
  const lastTag = [...tokens].reverse().find((token) => token.kind !== "text" || token.text.trim() !== "");
  const outerP = firstTag?.kind === "open" && firstTag.tag === "p" && lastTag?.kind === "close" && lastTag.tag === "p";

  const marksNow = (): Omit<Run, "text"> => {
    const run: Omit<Run, "text"> = {};
    for (const frame of stack) {
      if (frame.mark) run[frame.mark] = true;
      if (frame.link) run.link = frame.link;
      if (frame.style) run.style = frame.style;
    }
    return run;
  };
  const fail = (error: string) => ({ error });

  for (const token of tokens) {
    if (dropping) {
      if (token.kind === "close" && token.tag === dropping) dropping = null;
      continue;
    }
    if (token.kind === "text") {
      // A named reference the grammar does not decode would show literally on the page but decoded
      // in the editor and to the agent; the writer writes the character itself.
      const unknown = strict ? /&([a-z][a-z0-9]{1,30});/i.exec(token.raw) : null;
      if (unknown && !(unknown[1].toLowerCase() in NAMED)) return fail(`write the character itself instead of "&${unknown[1]};"`);
      if (token.text) runs.push({ ...marksNow(), text: token.text });
      continue;
    }
    if (token.kind === "stray") {
      if (strict) return fail('write &lt; for a "<" in text');
      runs.push({ ...marksNow(), text: "<" });
      continue;
    }
    const { tag } = token;
    if (token.kind === "void") {
      if (tag === "br") {
        if (strict && token.attrs.length) return fail(`attribute "${token.attrs[0][0]}" is not allowed on <br>`);
        runs.push({ ...marksNow(), text: "", br: true });
        continue;
      }
      if (strict) return fail(`<${tag}> is not allowed in text`);
      continue;
    }
    if (token.kind === "open") {
      if (tag === "p") {
        paragraphs += 1;
        if (strict && token.attrs.length) return fail(`attribute "${token.attrs[0][0]}" is not allowed on <p>`);
        if (strict && (!outerP || paragraphs > 1 || stack.length)) return fail("one paragraph only: use <br> for a new line");
        if (!strict && paragraphs > 1 && runs.length) runs.push({ ...marksNow(), text: "", br: true });
        stack.push({ tag });
        continue;
      }
      const mark = MARK_TAGS[tag];
      if (mark) {
        if (strict && token.attrs.length) return fail(`attribute "${token.attrs[0][0]}" is not allowed on <${tag}>`);
        stack.push({ tag, mark });
        continue;
      }
      if (tag === "a" && !links) {
        if (strict) return fail("a button's words may not hold a link");
        stack.push({ tag });
        continue;
      }
      if (tag === "a") {
        let href: string | null = null;
        let newTab = false;
        for (const [name, value] of token.attrs) {
          if (name === "href") href = (value ?? "").trim();
          else if (name === "data-new-tab") newTab = value === null || value === "" || value === "true";
          else if (strict) {
            return fail(name === "target" || name === "rel"
              ? `attribute "${name}" is not allowed on <a>; write data-new-tab for a link that opens in a new tab`
              : `attribute "${name}" is not allowed on <a>`);
          }
        }
        if (strict && stack.some((frame) => frame.link)) return fail("a link may not hold another link");
        if (href === null || !isRichLink(href)) {
          if (strict) return fail(href === null ? "<a> needs an href" : LINK_RULE);
          stack.push({ tag });
          continue;
        }
        stack.push({ tag, link: { href, newTab } });
        continue;
      }
      if (tag === "span") {
        const key = token.attrs.find(([name]) => name === "data-s")?.[1] ?? null;
        if (strict) {
          const other = token.attrs.find(([name]) => name !== "data-s");
          if (other) return fail(`attribute "${other[0]}" is not allowed on <span>`);
          if (key === null) return fail("<span> needs data-s naming its _edits entry");
          if (!ElementKeySchema.safeParse(key).success) return fail(`data-s must be an element key; "${key}" is not one`);
          if (stack.some((frame) => frame.style)) return fail("a styled span may not hold another");
        }
        const valid = key !== null && ElementKeySchema.safeParse(key).success && !stack.some((frame) => frame.style);
        stack.push(valid ? { tag, style: key! } : { tag });
        continue;
      }
      if (strict) return fail(`<${tag}> is not allowed in text`);
      if (DROP_WHOLE.has(tag)) dropping = tag;
      else stack.push({ tag });
      continue;
    }
    // A closing tag: it must close the innermost open element.
    const at = stack.map((frame) => frame.tag).lastIndexOf(tag);
    if (strict) {
      if (at === -1) return fail(`</${tag}> closes nothing`);
      if (at !== stack.length - 1) return fail(`<${stack[stack.length - 1].tag}> is not closed before </${tag}>`);
    }
    if (at !== -1) stack.splice(at);
  }
  if (strict && stack.length) return fail(`<${stack[stack.length - 1].tag}> is not closed`);
  return { runs };
}

/** The text as runs, or the first thing it holds outside the grammar, as a sentence. */
export function parseRich(html: string): Run[] | { error: string } {
  const result = read(html, true);
  return "error" in result ? result : merged(result.runs);
}

/** Every reason the text is not in the grammar (none, or the first one), each saying what to write. */
export function richProblems(html: string, options: RichOptions = {}): string[] {
  const result = read(html, true, options);
  return "error" in result ? [result.error] : [];
}

/** Any text as the grammar's canonical markup: tags outside it dropped (their words kept; script and
 * style with their words), attributes outside it dropped, paragraphs joined by line breaks. Canonical
 * text comes back unchanged; normalizing twice changes nothing more. */
export function normalizeRich(html: string, options: RichOptions = {}): string {
  const result = read(html, false, options);
  return "runs" in result ? serializeRich(result.runs) : "";
}

/** Runs of a text the caller already holds as stored: strictly read, else leniently. */
function runsOf(html: string): Run[] {
  const strict = read(html, true);
  if ("runs" in strict) return merged(strict.runs);
  const lenient = read(html, false);
  return "runs" in lenient ? merged(lenient.runs) : [];
}

/** The visible characters, as the browser's textContent counts them (a line break is none). */
export function richText(html: string): string {
  return runsOf(html).map((run) => run.text).join("");
}

// ---------------------------------------------------------------------------------------------
// Writing

const escapeText = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttr = (text: string) => escapeText(text).replace(/"/g, "&quot;");

type Open = { key: string; open: string; close: string };

function opens(run: Run, link: (link: RichLink) => string): Open[] {
  const out: Open[] = [];
  if (run.link) out.push({ key: `a ${run.link.href} ${run.link.newTab}`, open: link(run.link), close: "</a>" });
  if (run.style) out.push({ key: `s ${run.style}`, open: `<span data-s="${escapeAttr(run.style)}">`, close: "</span>" });
  for (const mark of MARK_ORDER) if (run[mark]) out.push({ key: mark, open: `<${mark}>`, close: `</${mark}>` });
  return out;
}

const sameMarks = (a: Run, b: Run) =>
  !a.br && !b.br && a.style === b.style && a.link?.href === b.link?.href && a.link?.newTab === b.link?.newTab &&
  MARK_ORDER.every((mark) => a[mark] === b[mark]);

/** Neighbouring text runs with the same marks joined; empty text runs dropped. */
function merged(runs: Run[]): Run[] {
  const out: Run[] = [];
  for (const run of runs) {
    if (!run.br && !run.text) continue;
    const last = out[out.length - 1];
    if (last && sameMarks(last, run)) last.text += run.text;
    else out.push({ ...run });
  }
  return out;
}

function write(runs: Run[], link: (link: RichLink) => string): string {
  let html = "";
  let stack: Open[] = [];
  for (const run of merged(runs)) {
    const want = opens(run, link);
    let common = 0;
    while (common < stack.length && common < want.length && stack[common].key === want[common].key) common += 1;
    for (let i = stack.length - 1; i >= common; i -= 1) html += stack[i].close;
    for (let i = common; i < want.length; i += 1) html += want[i].open;
    stack = want;
    html += run.br ? "<br>" : escapeText(run.text);
  }
  for (let i = stack.length - 1; i >= 0; i -= 1) html += stack[i].close;
  return html;
}

/** Runs as the grammar's canonical markup: marks nest link > styled span > strong > em > u > s. */
export function serializeRich(runs: Run[]): string {
  return write(runs, (link) => `<a href="${escapeAttr(link.href)}"${link.newTab ? ' data-new-tab=""' : ""}>`);
}

/** The text as the published page draws it: the outer paragraph dropped, a new-tab link opening in a
 * new tab, this site's own pages through `href` (its base path). Whatever is outside the grammar is
 * dropped with its words kept, so raw markup never reaches the page. */
export function richHtml(html: string, href: (value: string) => string): string {
  return write(runsOf(html), (link) =>
    `<a href="${escapeAttr(href(link.href))}"${link.newTab ? ' target="_blank" rel="noopener"' : ""}>`,
  );
}

/** The text with each link's address passed through `href` (a clone slot's links resolved under the
 * site's base path before the clone filler draws them), still in the grammar. */
export function mapRichLinks(html: string, href: (value: string) => string): string {
  return serializeRich(runsOf(html).map((run) => (run.link ? { ...run, link: { ...run.link, href: href(run.link.href) } } : run)));
}

/** The addresses of the links in the text, in order (the save check sends each one to its page check). */
export function richLinks(html: string): string[] {
  return runsOf(html).flatMap((run, i, runs) => (run.link && runs[i - 1]?.link?.href !== run.link.href ? [run.link.href] : []));
}

/** Whether a string holds markup or a character reference (and so must be drawn as rich text). */
export const hasMarkup = (value: string) => /[<&]/.test(value);

// ---------------------------------------------------------------------------------------------
// Changing a range of words

/** The runs split so that `start` and `end` fall between runs; `inside` says which runs are in the range. */
function splitAt(runs: Run[], start: number, end: number): { runs: Run[]; inside: boolean[] } {
  const out: Run[] = [];
  const inside: boolean[] = [];
  let at = 0;
  for (const run of runs) {
    if (run.br) {
      out.push(run);
      inside.push(at > start && at < end);
      continue;
    }
    const from = at;
    const to = at + run.text.length;
    at = to;
    const cuts = [from, Math.max(from, Math.min(start, to)), Math.max(from, Math.min(end, to)), to];
    for (let i = 0; i < 3; i += 1) {
      if (cuts[i + 1] <= cuts[i]) continue;
      out.push({ ...run, text: run.text.slice(cuts[i] - from, cuts[i + 1] - from) });
      inside.push(i === 1);
    }
  }
  return { runs: out, inside };
}

const SPAN_KEY = (elementKey: string) => new RegExp(`^${elementKey.replace(/[.]/g, "\\.")}~(\\d+)$`);

/** Style the words in `[start, end)`: each stretch gets `apply(its current override)`. A styled span
 * wholly inside the range keeps its key (its entry is updated); words outside a span, or a span cut by
 * the range's edge, get a new key `<elementKey>~<n>`; an override that ends up empty unwraps its
 * words. Entries of this element's spans that no longer appear in the text are dropped. */
export function styleWords(
  html: string,
  start: number,
  end: number,
  apply: (old: StyleOverride) => StyleOverride,
  edits: Edits,
  elementKey: string,
): { html: string; edits: Edits } {
  const { runs, inside } = splitAt(runsOf(html), start, end);
  const next: Edits = { ...edits };
  const pattern = SPAN_KEY(elementKey);
  let free = 1 + Math.max(0, ...[...Object.keys(edits), ...runs.map((run) => run.style ?? "")].map((key) => Number(pattern.exec(key)?.[1] ?? 0)));
  const assigned = new Map<string, string | null>();
  runs.forEach((run, i) => {
    if (!inside[i] || run.br) return;
    const old = run.style ?? "";
    if (!assigned.has(old)) {
      const whollyInside = old !== "" && runs.every((other, j) => other.style !== old || inside[j]);
      const override = Object.fromEntries(
        Object.entries(apply(old ? (edits[old] ?? {}) : {})).filter(([, value]) => value !== undefined),
      ) as StyleOverride;
      if (!Object.keys(override).length) {
        if (whollyInside) delete next[old];
        assigned.set(old, null);
      } else {
        const key = whollyInside ? old : `${elementKey}~${free++}`;
        next[key] = override;
        assigned.set(old, key);
      }
    }
    const key = assigned.get(old);
    if (key) run.style = key;
    else delete run.style;
  });
  const used = new Set(runs.map((run) => run.style).filter(Boolean));
  for (const key of Object.keys(next)) if (pattern.test(key) && !used.has(key)) delete next[key];
  return { html: serializeRich(runs), edits: next };
}

/** The styled span key every highlighted word in `[start, end)` shares, or null (none, or several). */
export function styleAt(html: string, start: number, end: number): string | null {
  const { runs, inside } = splitAt(runsOf(html), start, end);
  const keys = new Set(runs.filter((run, i) => inside[i] && !run.br).map((run) => run.style ?? ""));
  return keys.size === 1 ? [...keys][0] || null : null;
}

/** The link the range is in — all of the range's words in one link, or a caret inside one — with
 * that link's whole extent; null otherwise. */
export function linkAt(html: string, start: number, end: number): (RichLink & { start: number; end: number }) | null {
  const runs = runsOf(html);
  let at = 0;
  const spans = runs.map((run) => {
    const from = at;
    at += run.text.length;
    return { run, from, to: at };
  });
  const touched = spans.filter(({ run, from, to }) =>
    !run.br && (start === end ? from < start && start < to || (from <= start && start < to) : from < end && to > start),
  );
  if (!touched.length) return null;
  const link = touched[0].run.link;
  if (!link || touched.some(({ run }) => run.link?.href !== link.href || run.link?.newTab !== link.newTab)) return null;
  // The link's whole extent: neighbouring runs carrying the same link.
  let first = spans.indexOf(touched[0]);
  let last = spans.indexOf(touched[touched.length - 1]);
  const same = (i: number) => spans[i] && (spans[i].run.br || (spans[i].run.link?.href === link.href && spans[i].run.link?.newTab === link.newTab));
  while (first > 0 && same(first - 1)) first -= 1;
  while (last < spans.length - 1 && same(last + 1)) last += 1;
  return { href: link.href, newTab: link.newTab, start: spans[first].from, end: spans[last].to };
}

/** Link the words in `[start, end)` (or remove their link, with null). A range inside one link acts on
 * that whole link. */
export function linkWords(html: string, start: number, end: number, link: RichLink | null): string {
  const current = linkAt(html, start, end);
  const [from, to] = current ? [current.start, current.end] : [start, end];
  const { runs, inside } = splitAt(runsOf(html), from, to);
  runs.forEach((run, i) => {
    if (!inside[i]) return;
    if (link) run.link = { ...link };
    else delete run.link;
  });
  return serializeRich(runs);
}

/** The text with its words changed to `text` as typed in a box (plan 3: a button's Text row): the
 * words before and after the change keep their marks and styled spans, the changed words are plain
 * text; this element's span entries whose words are gone are dropped from `edits`. */
export function retypeRich(html: string, text: string, edits: Edits, elementKey: string): { html: string; edits: Edits } {
  const old = richText(html);
  if (old === text) return { html, edits };
  let start = 0;
  while (start < old.length && start < text.length && old[start] === text[start]) start += 1;
  let tail = 0;
  while (tail < old.length - start && tail < text.length - start && old[old.length - 1 - tail] === text[text.length - 1 - tail]) tail += 1;
  const { runs, inside } = splitAt(runsOf(html), start, old.length - tail);
  const kept: Run[] = [];
  let placed = false;
  const typed = text.slice(start, text.length - tail);
  runs.forEach((run, i) => {
    if (inside[i]) {
      if (!placed && typed) kept.push({ text: typed });
      placed = true;
      return;
    }
    if (!placed && typed && sumBefore(runs, i) >= start) {
      kept.push({ text: typed });
      placed = true;
    }
    kept.push(run);
  });
  if (!placed && typed) kept.push({ text: typed });
  const next = serializeRich(kept);
  const pattern = SPAN_KEY(elementKey);
  const used = new Set(runsOf(next).map((run) => run.style).filter(Boolean));
  const nextEdits: Edits = { ...edits };
  for (const key of Object.keys(nextEdits)) if (pattern.test(key) && !used.has(key)) delete nextEdits[key];
  return { html: next, edits: nextEdits };
}

function sumBefore(runs: Run[], index: number): number {
  return runs.slice(0, index).reduce((total, run) => total + run.text.length, 0);
}
