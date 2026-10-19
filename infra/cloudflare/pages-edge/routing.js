// Pure routing decision for the pages-edge Worker (custom-domain publishing spec §5.1; Wave 2
// Contract 9: published pages on their own registrable domain), kept separate from the fetch
// handler so it runs under `node --test` without a Workers runtime.
const apexOf = (suffix) => suffix.split(".").slice(-2).join(".");
const under = (host, suffix) => host === suffix || host.endsWith("." + suffix);

export function decide(request, env) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  const suffix = env.SYSTEM_SUFFIX.toLowerCase();
  const legacy = (env.LEGACY_SYSTEM_SUFFIXES || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value) => value && value !== suffix);
  // Review finding K3-8: the site editor's hosts are never ours, whatever the pages domain is — with
  // pages on the editor's registrable domain they would otherwise be forwarded to the page origin.
  const editor = (env.EDITOR_SUFFIX || "").trim().toLowerCase();
  if (editor && under(host, editor)) return { kind: "passthrough" };
  const readOnly = request.method === "GET" || request.method === "HEAD";
  // An old system hostname (<label>.pages.cluehq.ai) answers 301 with the same label, path and
  // query on the new domain. The bare old suffix is the Cloudflare for SaaS fallback origin and is
  // left as it was (custom-domain traffic arrives with the customer's own Host).
  for (const old of legacy) {
    if (host.endsWith("." + old)) {
      if (!readOnly) return { kind: "method_not_allowed" };
      const label = host.slice(0, -(old.length + 1));
      return { kind: "redirect", status: 301, location: `https://${label}.${suffix}${url.pathname}${url.search}` };
    }
  }
  const apexes = [apexOf(suffix), ...legacy.map(apexOf)];
  const ours = under(host, suffix) || legacy.includes(host) || !apexes.some((apex) => under(host, apex));
  if (!ours) return { kind: "passthrough" };
  if (!readOnly) return { kind: "method_not_allowed" };
  const headers = new Headers(request.headers);
  headers.delete("x-clue-public-host");
  headers.delete("x-clue-edge-auth");
  headers.set("x-clue-public-host", host);
  headers.set("x-clue-edge-auth", env.EDGE_SECRET);
  const target = new URL(url.pathname + url.search, "https://" + env.ORIGIN_HOST).toString();
  return { kind: "forward", host, target, headers, method: request.method };
}
