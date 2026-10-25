/**
 * `/projects/{id}?prompt=<text>` opens the project Home with `<text>` already
 * in its composer (the Settings → Integrations "Ask Clue to …" links). The
 * text is only a draft: nothing is sent until the person submits it.
 *
 * Plain functions, outside the client hook, so the server page can call them.
 */

/** A pasted link can carry anything; the composer gets at most this much. */
export const MAX_PREFILLED_PROMPT_LENGTH = 2000;

/** The composer's starting text from the raw `prompt` query value — cut, never refused. */
export function prefilledPrompt(raw: string | string[] | undefined): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value || !value.trim()) return "";
  return value.slice(0, MAX_PREFILLED_PROMPT_LENGTH);
}

/**
 * The current address without its `prompt` parameter, so a reload or a shared
 * link doesn't fill the composer again. `null` when there is none to drop.
 */
export function urlWithoutPrompt(href: string): string | null {
  const url = new URL(href);
  if (!url.searchParams.has("prompt")) return null;
  url.searchParams.delete("prompt");
  return `${url.pathname}${url.search}${url.hash}`;
}
