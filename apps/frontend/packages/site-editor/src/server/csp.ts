/**
 * The editor domain's content security policy (D2 + plan Global Constraints). The only inline
 * script is the import map, allowed by a per-response nonce; there is no 'unsafe-eval' (zod
 * runs jitless), no 'strict-dynamic' (an agent module may not import anything the policy does
 * not name) and no blob:. Images, fonts and media come only from this origin's /asset-store
 * proxy (or data:). Puck's in-frame canvas iframe is disabled, so no frames at all.
 */
export function contentSecurityPolicy({ appOrigin, nonce }: { appOrigin: string; nonce: string | null }): string {
  return [
    "default-src 'none'",
    nonce ? `script-src 'self' 'nonce-${nonce}'` : "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "media-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
    "worker-src 'none'",
    "object-src 'none'",
    "manifest-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    `frame-ancestors ${appOrigin}`,
  ].join("; ");
}

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};
