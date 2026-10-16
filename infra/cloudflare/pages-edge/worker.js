import { decide } from "./routing.js";

export default {
  async fetch(request, env) {
    const decision = decide(request, env);
    if (decision.kind === "passthrough") return fetch(request);
    if (decision.kind === "method_not_allowed") return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
    if (decision.kind === "redirect") return Response.redirect(decision.location, decision.status);
    // redirect: "manual" — the origin's fallback-URL 302 must reach the browser, not be followed here.
    return fetch(new Request(decision.target, { method: decision.method, headers: decision.headers, redirect: "manual" }));
  },
};
