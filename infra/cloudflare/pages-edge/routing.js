// Pure routing decision for the pages-edge Worker (custom-domain publishing spec §5.1), kept
// separate from the fetch handler so it runs under `node --test` without a Workers runtime.
export function decide(request, env) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  const suffix = env.SYSTEM_SUFFIX.toLowerCase();
  const zoneApex = suffix.split(".").slice(-2).join(".");
  const ours = host === suffix || host.endsWith("." + suffix) || !host.endsWith(zoneApex);
  if (!ours) return { kind: "passthrough" };
  if (request.method !== "GET" && request.method !== "HEAD") return { kind: "method_not_allowed" };
  const headers = new Headers(request.headers);
  headers.delete("x-clue-public-host");
  headers.delete("x-clue-edge-auth");
  headers.set("x-clue-public-host", host);
  headers.set("x-clue-edge-auth", env.EDGE_SECRET);
  const target = new URL(url.pathname + url.search, "https://" + env.ORIGIN_HOST).toString();
  return { kind: "forward", host, target, headers, method: request.method };
}
