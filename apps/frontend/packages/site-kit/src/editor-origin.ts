// Contract 9: the editor domain is one subdomain per workspace, `<label>.<suffix>`. The label is
// an opaque token derived from the workspace id (never the renameable handle): the first 32 hex
// characters of sha256 over a versioned prefix. Web Crypto, so it runs in Node and browsers.
export const EDITOR_LABEL_PATTERN = /^[0-9a-f]{32}$/;
const SUFFIX_PATTERN = /^[a-z0-9.-]+(?::\d{1,5})?$/;
const LOCAL_SUFFIX = /(^|\.)localhost(?::\d{1,5})?$/;

export async function editorLabelFor(workspaceId: string): Promise<string> {
  const bytes = new TextEncoder().encode(`clue-site-editor-label:v1:${workspaceId}`);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 32);
}

/** `https://<label>.<suffix>`; `http://` for a `*.localhost` dev suffix, which carries its port
 * (`editor.localhost:3129`). */
export function editorOriginFor(label: string, suffix: string): string {
  if (!EDITOR_LABEL_PATTERN.test(label)) throw new Error("not an editor label");
  const host = suffix.trim().toLowerCase();
  if (!SUFFIX_PATTERN.test(host)) throw new Error("not an editor domain suffix");
  return `${LOCAL_SUFFIX.test(host) ? "http" : "https"}://${label}.${host}`;
}

/** The label of a request's `Host`, or null when the host is not `<label>.<suffix>`. */
export function editorLabelFromHost(host: string | undefined, suffix: string): string | null {
  if (!host) return null;
  const value = host.trim().toLowerCase();
  const tail = `.${suffix.trim().toLowerCase()}`;
  if (!value.endsWith(tail)) return null;
  const label = value.slice(0, -tail.length);
  return EDITOR_LABEL_PATTERN.test(label) ? label : null;
}

/** Second-level labels that, under a two-letter country code, form a public suffix (`co.uk`,
 * `com.au`): the registrable domain is then the last THREE labels. A conservative stand-in for the
 * Public Suffix List, mirrored in deploy/check_prod_env.py. */
const TWO_LEVEL_SECOND = new Set(["co", "com", "net", "org", "gov", "ac", "edu", "ltd", "plc"]);

/** The registrable domain of a host (`app.cluehq.ai` → `cluehq.ai`; `edit.foo.co.uk` → `foo.co.uk`),
 * port and case ignored. */
export function registrableDomainOf(host: string): string {
  const labels = host.trim().toLowerCase().replace(/:\d+$/, "").split(".").filter(Boolean);
  const twoLevel = labels.length >= 3 && labels.at(-1)!.length === 2 && TWO_LEVEL_SECOND.has(labels.at(-2)!);
  return labels.slice(twoLevel ? -3 : -2).join(".");
}

/** Review findings S2b-9 and K3-8: the editor's domain must never share a registrable domain with
 * the app (code in the editor frame could set the app's cookies) or with the published pages. */
export function sameRegistrableDomain(left: string, right: string): boolean {
  return registrableDomainOf(left) === registrableDomainOf(right);
}

