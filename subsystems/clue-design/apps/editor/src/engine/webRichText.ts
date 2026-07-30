import type { RichTextFormat, RichTextFormatValue } from "./webBridge";

/** One source of truth for the four visual-mark controls. Both the inspector
 * and floating toolbar render from this list, so labels, glyphs, shortcuts,
 * and mixed-state semantics cannot drift into parallel implementations. */
export interface RichTextMarkControl {
  format: RichTextFormat;
  label: string;
  glyph: string;
  shortcut: string;
}

export const RICH_TEXT_MARK_CONTROLS: readonly RichTextMarkControl[] = [
  { format: "bold", label: "Bold", glyph: "B", shortcut: "⌘B" },
  { format: "italic", label: "Italic", glyph: "I", shortcut: "⌘I" },
  { format: "underline", label: "Underline", glyph: "U", shortcut: "⌘U" },
  { format: "strikethrough", label: "Strikethrough", glyph: "S", shortcut: "⇧⌘X" }
] as const;

const WEB_BINDING_KEY_RE = /^[a-z0-9_.-]{1,64}$/;

/** Shared client mirror of the engine's slot/personalization key grammar. */
export function webBindingKeyIsAllowed(key: string): boolean {
  return WEB_BINDING_KEY_RE.test(key);
}

/** Shared client mirror of the server's safe href grammar. The server still
 * performs the canonical validation when SetRichText is persisted. */
export function richTextHrefIsAllowed(href: string): boolean {
  const trimmed = href.trim();
  if (!trimmed) {
    return false;
  }
  const lower = trimmed.toLowerCase();
  return (
    lower.startsWith("https://") ||
    lower.startsWith("http://") ||
    lower.startsWith("mailto:") ||
    lower.startsWith("tel:") ||
    trimmed.startsWith("#") ||
    trimmed.startsWith("/")
  );
}

export function richTextHrefError(href: string): string | null {
  if (!href.trim()) {
    return "Enter a link URL.";
  }
  return richTextHrefIsAllowed(href)
    ? null
    : "Use http(s), mailto, tel, an anchor (#…), or a site-relative path (/…).";
}

export function richTextAriaPressed(
  value: RichTextFormatValue
): boolean | "mixed" {
  return value === "mixed" ? "mixed" : value === "on";
}
