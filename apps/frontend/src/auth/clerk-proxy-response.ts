/**
 * Normalize Clerk's pass-through response for Next 16's `proxy.ts` runtime.
 *
 * Clerk 7 may express "continue this exact request" as a rewrite to the request's own URL. In the
 * local Next 16 proxy runtime that response re-enters the proxy indefinitely. Preserve every
 * Clerk-injected request header, but translate only that exact self-rewrite back to Next's native
 * continue marker. Real redirects and rewrites to a different URL remain untouched.
 */
export function normalizeClerkProxyResponse(
  requestUrl: string,
  response: Response | null | void,
): Response | null | void {
  if (response == null) return response;
  if (response.headers.get("x-middleware-rewrite") !== requestUrl) {
    return response;
  }
  response.headers.delete("x-middleware-rewrite");
  response.headers.set("x-middleware-next", "1");
  return response;
}
