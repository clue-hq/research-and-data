import test from "node:test";
import assert from "node:assert/strict";
import {
  addPageDecision,
  INVALID_ROUTE_MESSAGE,
  pageIdFromName,
  pageIsRemovable,
  pageWriteMessage,
  ROUTE_TAKEN_MESSAGE,
  routeFieldDecision,
} from "./inspector-page-field";

test("the refusal sentences are the agent tool's own words", () => {
  // Verbatim from `web_substrate.py`'s add_page docstring (the sentence the
  // agent already tells a marketer) — a second wording would teach two rules.
  assert.equal(
    INVALID_ROUTE_MESSAGE,
    'Routes are "/" or lowercase segments like "/pricing" — no capitals, no spaces, no trailing slash.',
  );
  assert.equal(ROUTE_TAKEN_MESSAGE, "That route is already used by another page.");
});

test("a valid, free, new route commits", () => {
  assert.deepEqual(routeFieldDecision("/plans", "/pricing", ["/", "/about"]), {
    kind: "commit",
    route: "/plans",
  });
  // Surrounding whitespace is typing, not route: it is trimmed off the commit.
  assert.deepEqual(routeFieldDecision("  /plans  ", "/pricing", ["/"]), {
    kind: "commit",
    route: "/plans",
  });
  // "/" is a legal route like any other.
  assert.deepEqual(routeFieldDecision("/", "/pricing", ["/about"]), {
    kind: "commit",
    route: "/",
  });
});

test("re-typing the page's own route is not a write", () => {
  assert.deepEqual(routeFieldDecision("/pricing", "/pricing", ["/"]), { kind: "noop" });
  assert.deepEqual(routeFieldDecision(" /pricing ", "/pricing", ["/"]), { kind: "noop" });
  // A page's own route being in the sibling list would be a caller bug, but the
  // no-op check runs first either way, so it can never self-refuse.
  assert.deepEqual(routeFieldDecision("/pricing", "/pricing", ["/pricing"]), {
    kind: "noop",
  });
});

test("an invalid route is refused with the engine's own grammar sentence", () => {
  for (const bad of ["/Pricing", "/two words", "/pricing/", "pricing", "", "/p-assets"]) {
    assert.deepEqual(
      routeFieldDecision(bad, "/pricing", ["/"]),
      { kind: "refuse", message: INVALID_ROUTE_MESSAGE },
      `expected ${JSON.stringify(bad)} to be refused`,
    );
  }
});

test("a route another page already holds is refused before the round trip", () => {
  assert.deepEqual(routeFieldDecision("/about", "/pricing", ["/", "/about"]), {
    kind: "refuse",
    message: ROUTE_TAKEN_MESSAGE,
  });
});

test("a page id is a slug of its name, and always starts with a letter", () => {
  assert.equal(pageIdFromName("Pricing Plans"), "pricing-plans");
  // The engine/agent grammar wants a leading letter, so a digit-leading slug
  // gets the `p-` prefix rather than being rejected back at the user.
  assert.equal(pageIdFromName("2026 Roadmap"), "p-2026-roadmap");
  assert.equal(pageIdFromName(""), "page");
  assert.equal(pageIdFromName("   "), "page");
  assert.equal(pageIdFromName("About / Team!"), "about-team");
  assert.equal(pageIdFromName("--Pricing--"), "pricing");
});

test("adding a page derives its route from the name, and refuses a taken one", () => {
  assert.deepEqual(addPageDecision("Pricing Plans", ["/"]), {
    kind: "commit",
    page: { id: "pricing-plans", name: "Pricing Plans", route: "/pricing-plans" },
  });
  assert.deepEqual(addPageDecision("Pricing", ["/", "/pricing"]), {
    kind: "refuse",
    message: ROUTE_TAKEN_MESSAGE,
  });
  // An unnamed page has nothing to slug — refuse rather than mint "/page".
  assert.deepEqual(addPageDecision("   ", ["/"]), {
    kind: "refuse",
    message: "Name the page first.",
  });
  // `p-assets` and `asset-store` are never a first segment (they are served
  // beside a published site), so the derived route can still be invalid.
  assert.deepEqual(addPageDecision("Asset Store", ["/"]), {
    kind: "refuse",
    message: INVALID_ROUTE_MESSAGE,
  });
});

test("the last page, and the home page, can never be removed", () => {
  assert.equal(pageIsRemovable({ route: "/pricing" }, 2), true);
  assert.equal(pageIsRemovable({ route: "/pricing" }, 1), false); // the only page
  assert.equal(pageIsRemovable({ route: "/" }, 3), false); // the home page
  assert.equal(pageIsRemovable(null, 3), false); // nothing selected
});

test("a server refusal speaks the field's words when it is one the field knows", () => {
  // The engine's own code (`detail.engine_code`) is what tells the field WHICH
  // refusal this was; `route \`/x\` is already taken` is engine prose, not a
  // sentence to show a marketer.
  assert.equal(
    pageWriteMessage("op.route_exists", "route `/pricing` is already taken"),
    ROUTE_TAKEN_MESSAGE,
  );
  assert.equal(
    pageWriteMessage("op.route_invalid", "route `/Bad` is not a valid site route"),
    INVALID_ROUTE_MESSAGE,
  );
  // Anything else keeps the server's own message — never a guess.
  assert.equal(pageWriteMessage("op.page_root_missing", "page root missing"), "page root missing");
  assert.equal(pageWriteMessage(null, "This edit could not be applied."), "This edit could not be applied.");
  assert.equal(pageWriteMessage(null, null), null);
});
