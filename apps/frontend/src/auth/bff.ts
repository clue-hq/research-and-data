const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "idempotency-key",
  // The @-mention directory revalidates by ETag (2026-10-05): a match is a bodiless 304.
  "if-none-match",
  "last-event-id",
  "x-quality-mode",
] as const;

const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "cache-control",
  "content-disposition",
  // Asset bytes revalidate by content digest (brand-context fix 2026-10-04).
  "etag",
  "content-security-policy",
  "x-request-id",
  "x-content-type-options",
  "x-projections-schema-version",
  // Whether a gallery thumbnail is this version's, an older stand-in, or not built yet
  // (background renders, 2026-10-29); the card retries until it is this version's.
  "x-thumbnail-state",
] as const;

export function backendPath(segments: readonly string[]): string {
  if (segments.length === 0) throw new Error("a backend path is required");
  if (segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error("backend paths cannot contain dot segments");
  }
  return `/${segments.map((segment) => encodeURIComponent(segment)).join("/")}`;
}

export function backendRequestHeaders(
  incoming: Headers,
  {
    token,
    workspaceId,
  }: Readonly<{ token: string; workspaceId: string | null }>,
): Headers {
  const outgoing = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) outgoing.set(name, value);
  }
  if (workspaceId) outgoing.set("X-Clue-Workspace-Id", workspaceId);
  return outgoing;
}

export function browserResponseHeaders(incoming: Headers): Headers {
  const outgoing = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = incoming.get(name);
    if (value) outgoing.set(name, value);
  }
  return outgoing;
}

export function hasAllowedOrigin(request: Request, expectedOrigin?: string): boolean {
  const method = request.method.toUpperCase();
  if (method === "GET" || method === "HEAD") return true;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === (expectedOrigin ?? new URL(request.url).origin);
  } catch {
    return false;
  }
}
