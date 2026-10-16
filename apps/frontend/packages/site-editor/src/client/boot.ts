export interface BootContext {
  appOrigin: string;
  nonce: string;
}

const NONCE = /^[A-Za-z0-9_-]{16,128}$/;

/** The frame's two boot facts: the nonce the app put in the URL fragment (`#n=<nonce>`, never sent
 * to a server) and the app origin the server wrote into the page. Anything malformed → no boot. */
export function readBootContext(hash: string, appOriginMeta: string | null): BootContext | null {
  const nonce = new URLSearchParams(hash.replace(/^#/, "")).get("n") ?? "";
  if (!NONCE.test(nonce) || !appOriginMeta) return null;
  let parsed: URL;
  try {
    parsed = new URL(appOriginMeta);
  } catch {
    return null;
  }
  if (parsed.origin !== appOriginMeta) return null;
  return { appOrigin: parsed.origin, nonce };
}
