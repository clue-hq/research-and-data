/**
 * An incremental Markdown reader for streamed assistant prose.
 *
 * Charter §3.1 maps the `text` part to `MessageResponse`/`MessageMarkdown`:
 * "incremental Markdown", and slice D5's AC adds "streamed Markdown renders
 * without raw syntax/flicker". Those two together are the whole problem. A
 * naive renderer that re-parses the accumulated string on every delta shows the
 * user `**bo` for one frame and then bold "bold" on the next — the raw-syntax
 * flash — and re-mounts its subtree, which is the flicker.
 *
 * The fix has two halves and both live here, as pure functions, so they can be
 * tested against every awkward split without a browser:
 *
 * 1. **Suppress the incomplete tail.** While the text is still streaming, an
 *    inline construct whose closing delimiter has not arrived is not rendered
 *    at all — neither as markup nor as its raw characters. The visible text
 *    lags the stream by at most one unfinished token, and never lies about it.
 * 2. **Stable block identity.** Blocks are keyed by their ordinal, so a
 *    growing document appends and updates rather than re-mounting, which is
 *    what keeps scroll position and open disclosures intact.
 *
 * The dialect is deliberately small and closed — headings, fenced code,
 * blockquotes, ordered/unordered lists, paragraphs, and the four inline
 * constructs. It is a renderer for model prose, not a CommonMark
 * implementation, and it renders no raw HTML at all: every leaf below is
 * escaped text placed by React, so a model cannot emit markup into the page.
 */

export type MarkdownInline =
  | { type: "text"; value: string }
  | { type: "strong"; value: string }
  | { type: "em"; value: string }
  | { type: "code"; value: string }
  | { type: "link"; value: string; href: string };

export type MarkdownBlock =
  | { type: "paragraph"; key: string; inline: MarkdownInline[] }
  | { type: "heading"; key: string; level: number; inline: MarkdownInline[] }
  | { type: "quote"; key: string; inline: MarkdownInline[] }
  | { type: "code"; key: string; language: string | null; value: string }
  | {
      type: "list";
      key: string;
      ordered: boolean;
      items: { key: string; inline: MarkdownInline[] }[];
    };

/**
 * The prefix of `text` that is safe to render right now.
 *
 * Only called while streaming. It finds the earliest position at which an
 * inline construct is still open and cuts there, so a half-typed `**bold` or
 * `[label](htt` never reaches the page as literal characters.
 */
export function safeStreamingPrefix(text: string): string {
  // Fenced code is scanned as a block, not as inline markup: its body may hold
  // any number of backticks or asterisks, and an *unclosed* fence is a
  // legitimate streaming state that renders as code rather than as ``` on the
  // page. Masking the fenced regions keeps both facts out of the parity counts
  // below and out of the cut.
  const scan = maskFences(text);
  let cut = text.length;

  const consider = (index: number) => {
    if (index !== -1 && index < cut) cut = index;
  };

  // An odd number of inline-code ticks means the last one is still open.
  const ticks = positionsOf(scan, "`");
  if (ticks.length % 2 === 1) consider(ticks[ticks.length - 1]);

  const doubles = positionsOf(scan, "**");
  if (doubles.length % 2 === 1) consider(doubles[doubles.length - 1]);

  // Single `*` emphasis, counting only asterisks that are not part of a `**`.
  const singles = positionsOf(scan, "*").filter(
    (index) => scan[index - 1] !== "*" && scan[index + 1] !== "*",
  );
  if (singles.length % 2 === 1) consider(singles[singles.length - 1]);

  const underscores = positionsOf(scan, "_");
  if (underscores.length % 2 === 1) consider(underscores[underscores.length - 1]);

  // A link is open until its `)` lands, and the whole `[label](href)` is one
  // unit — a rendered `[label]` followed a frame later by a link is a flicker.
  const openBracket = scan.lastIndexOf("[");
  if (openBracket !== -1) {
    const rest = scan.slice(openBracket);
    if (!/^\[[^\]]*\]\([^)]*\)/.test(rest)) consider(openBracket);
  }

  return text.slice(0, cut);
}

/** Replace every fenced-code region (closed or still open) with blanks. */
function maskFences(text: string): string {
  const fences = positionsOf(text, "```");
  if (fences.length === 0) return text;
  const characters = [...text];
  for (let index = 0; index < fences.length; index += 2) {
    const start = fences[index];
    const end = index + 1 < fences.length ? fences[index + 1] + 3 : characters.length;
    for (let position = start; position < end; position += 1) {
      characters[position] = " ";
    }
  }
  return characters.join("");
}

function positionsOf(text: string, token: string): number[] {
  const found: number[] = [];
  let index = text.indexOf(token);
  while (index !== -1) {
    found.push(index);
    index = text.indexOf(token, index + token.length);
  }
  return found;
}

const INLINE_PATTERN =
  /(`[^`]+`)|(\[[^\]]*\]\([^)\s]*\))|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(_[^_\n]+_)/;

/** Parse one line of already-safe text into inline tokens. */
export function parseInline(text: string): MarkdownInline[] {
  const tokens: MarkdownInline[] = [];
  let rest = text;
  while (rest.length > 0) {
    const match = INLINE_PATTERN.exec(rest);
    if (!match || match.index === undefined) break;
    if (match.index > 0) {
      tokens.push({ type: "text", value: rest.slice(0, match.index) });
    }
    const token = match[0];
    if (token.startsWith("`")) {
      tokens.push({ type: "code", value: token.slice(1, -1) });
    } else if (token.startsWith("[")) {
      const split = token.indexOf("](");
      tokens.push({
        type: "link",
        value: token.slice(1, split),
        href: token.slice(split + 2, -1),
      });
    } else if (token.startsWith("**")) {
      tokens.push({ type: "strong", value: token.slice(2, -2) });
    } else {
      tokens.push({ type: "em", value: token.slice(1, -1) });
    }
    rest = rest.slice(match.index + token.length);
  }
  if (rest.length > 0) tokens.push({ type: "text", value: rest });
  return tokens;
}

/**
 * Parse streamed assistant prose into stable, renderable blocks.
 *
 * `streaming` is derived from the part's own lifecycle (`text.start` seen,
 * `text.end` not yet) — never from a wire value and never from a timer.
 */
export function parseStreamingMarkdown(
  raw: string,
  { streaming = false }: { streaming?: boolean } = {},
): MarkdownBlock[] {
  const text = streaming ? safeStreamingPrefix(raw) : raw;
  const lines = text.split("\n");
  const blocks: MarkdownBlock[] = [];
  let ordinal = 0;
  const key = () => `b${ordinal++}`;

  let index = 0;
  while (index < lines.length) {
    const line = lines[index];

    if (line.trim().length === 0) {
      index += 1;
      continue;
    }

    const fence = /^```(\w*)\s*$/.exec(line.trim());
    if (fence) {
      const language = fence[1] ? fence[1] : null;
      const body: string[] = [];
      index += 1;
      while (index < lines.length && lines[index].trim() !== "```") {
        body.push(lines[index]);
        index += 1;
      }
      // A missing closing fence is the streaming case: render what exists.
      if (index < lines.length) index += 1;
      blocks.push({ type: "code", key: key(), language, value: body.join("\n") });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({
        type: "heading",
        key: key(),
        level: heading[1].length,
        inline: parseInline(heading[2]),
      });
      index += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const body: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", key: key(), inline: parseInline(body.join(" ")) });
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const ordered = numbered !== null;
      const blockKey = key();
      const items: { key: string; inline: MarkdownInline[] }[] = [];
      while (index < lines.length) {
        const candidate = ordered
          ? /^\s*\d+[.)]\s+(.*)$/.exec(lines[index])
          : /^\s*[-*+]\s+(.*)$/.exec(lines[index]);
        if (!candidate) break;
        items.push({
          key: `${blockKey}i${items.length}`,
          inline: parseInline(candidate[1]),
        });
        index += 1;
      }
      blocks.push({ type: "list", key: blockKey, ordered, items });
      continue;
    }

    const body: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim().length > 0 &&
      !/^```/.test(lines[index].trim()) &&
      !/^#{1,6}\s/.test(lines[index]) &&
      !/^>\s?/.test(lines[index]) &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index])
    ) {
      body.push(lines[index]);
      index += 1;
    }
    blocks.push({
      type: "paragraph",
      key: key(),
      inline: parseInline(body.join(" ")),
    });
  }

  return blocks;
}
