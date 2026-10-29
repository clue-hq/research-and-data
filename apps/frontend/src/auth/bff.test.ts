import assert from "node:assert/strict";
import test from "node:test";
import {
  backendPath,
  backendRequestHeaders,
  browserResponseHeaders,
  hasAllowedOrigin,
} from "./bff";

test("BFF path encoding cannot escape the configured backend origin", () => {
  assert.equal(
    backendPath(["frontend", "v1", "accounts"]),
    "/frontend/v1/accounts",
  );
  assert.equal(
    backendPath(["v1", "projects", "../other"]),
    "/v1/projects/..%2Fother",
  );
  assert.throws(() => backendPath(["v1", "..", "admin"]), /dot segments/);
});

test("BFF permits only same-origin browser mutations", () => {
  assert.equal(
    hasAllowedOrigin(
      new Request("https://app.example/api/clue/tools/run", {
        method: "POST",
        headers: { Origin: "https://app.example" },
      }),
    ),
    true,
  );
  assert.equal(
    hasAllowedOrigin(
      new Request("https://app.example/api/clue/tools/run", {
        method: "POST",
        headers: { Origin: "https://attacker.example" },
      }),
    ),
    false,
  );
  assert.equal(
    hasAllowedOrigin(
      new Request("https://app.example/api/clue/tools/run", { method: "POST" }),
    ),
    false,
  );
});

test("BFF can pin mutations to the configured canonical origin across proxy rewrites", () => {
  assert.equal(
    hasAllowedOrigin(
      new Request("http://127.0.0.1:3000/api/onboarding/provision", {
        method: "POST",
        headers: { Origin: "http://localhost:3000" },
      }),
      "http://localhost:3000",
    ),
    true,
  );
  assert.equal(
    hasAllowedOrigin(
      new Request("http://localhost:3000/api/onboarding/provision", {
        method: "POST",
        headers: { Origin: "http://127.0.0.1:3000" },
      }),
      "http://localhost:3000",
    ),
    false,
  );
});

test("BFF forwards a narrow header allowlist and never browser cookies", () => {
  const incoming = new Headers({
    Cookie: "__session=secret",
    Authorization: "Bearer browser-controlled",
    "Content-Type": "application/json",
    "Idempotency-Key": "idem-1",
    "X-Workspace-Id": "browser-workspace",
  });
  const outgoing = backendRequestHeaders(incoming, {
    token: "server-session-token",
    workspaceId: "ws_internal",
  });

  assert.equal(outgoing.get("authorization"), "Bearer server-session-token");
  assert.equal(outgoing.get("x-clue-workspace-id"), "ws_internal");
  assert.equal(outgoing.get("idempotency-key"), "idem-1");
  assert.equal(outgoing.get("cookie"), null);
  assert.equal(outgoing.get("x-workspace-id"), null);
});

test("BFF response never forwards backend cookies or authentication headers", () => {
  const outgoing = browserResponseHeaders(
    new Headers({
      "Content-Type": "application/json",
      "Set-Cookie": "backend=secret",
      Authorization: "Bearer secret",
      "Content-Disposition": "inline",
      "Content-Security-Policy": "sandbox; default-src 'none'",
      "X-Content-Type-Options": "nosniff",
      "X-Request-Id": "request-1",
    }),
  );
  assert.equal(outgoing.get("content-type"), "application/json");
  assert.equal(outgoing.get("x-request-id"), "request-1");
  assert.equal(outgoing.get("content-disposition"), "inline");
  assert.equal(
    outgoing.get("content-security-policy"),
    "sandbox; default-src 'none'",
  );
  assert.equal(outgoing.get("x-content-type-options"), "nosniff");
  assert.equal(outgoing.get("set-cookie"), null);
  assert.equal(outgoing.get("authorization"), null);
});

test("BFF response forwards a thumbnail's readiness so the gallery card knows to ask again", () => {
  // Production 2026-10-28: thumbnails now render in the background; the design API says
  // whether a card is this version's (`fresh`), an older stand-in (`stale`) or not built yet
  // (`pending`), and the card retries until it is `fresh`.
  const outgoing = browserResponseHeaders(new Headers({ "X-Thumbnail-State": "stale" }));
  assert.equal(outgoing.get("x-thumbnail-state"), "stale");
});
