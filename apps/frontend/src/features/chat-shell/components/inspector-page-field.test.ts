import test from "node:test";
import assert from "node:assert/strict";
import {
  addPageDecision,
  INVALID_ROUTE_MESSAGE,
  NAME_THE_PAGE_MESSAGE,
  PAGE_NAME_TAKEN_MESSAGE,
  pageIdFromName,
  pageIsRemovable,
  pageWriteMessage,
  ROUTE_TAKEN_MESSAGE,
  routeFieldDecision,
  routeTakenMessage,
  suggestedRouteForName,
} from "./inspector-page-field";

const HOME = { id: "home", name: "Home", route: "/" };
const ABOUT = { id: "about", name: "About", route: "/about" };
const PRICING = { id: "pricing", name: "Pricing", route: "/pricing" };

test("the refusal sentences are the agent tool's own words", () => {
  // Verbatim from `web_substrate.py`'s add_page docstring (the sentence the
  // agent already tells a marketer) — a second wording would teach two rules.
  assert.equal(
    INVALID_ROUTE_MESSAGE,
    'Routes are "/" or lowercase segments like "/pricing" — no capitals, no spaces, no trailing slash.',
  );
  assert.equal(ROUTE_TAKEN_MESSAGE, "That route is already used by another page.");
  // The LOCAL collision names the page (founder correction 2026-09-04: the
  // marketer had just renamed the home page to that route and could not see
  // it from "another page").
  assert.equal(routeTakenMessage("Home"), 'That route is already used by the page "Home".');
});

test("a valid, free, new route commits", () => {
  assert.deepEqual(routeFieldDecision("/plans", "/pricing", [HOME, ABOUT]), {
    kind: "commit",
    route: "/plans",
  });
  // Surrounding whitespace is typing, not route: it is trimmed off the commit.
  assert.deepEqual(routeFieldDecision("  /plans  ", "/pricing", [HOME]), {
    kind: "commit",
    route: "/plans",
  });
  // "/" is a legal route like any other.
  assert.deepEqual(routeFieldDecision("/", "/pricing", [ABOUT]), {
    kind: "commit",
    route: "/",
  });
});

test("re-typing the page's own route is not a write", () => {
  assert.deepEqual(routeFieldDecision("/pricing", "/pricing", [HOME]), { kind: "noop" });
  assert.deepEqual(routeFieldDecision(" /pricing ", "/pricing", [HOME]), { kind: "noop" });
  // A page's own route being in the sibling list would be a caller bug, but the
  // no-op check runs first either way, so it can never self-refuse.
  assert.deepEqual(routeFieldDecision("/pricing", "/pricing", [PRICING]), {
    kind: "noop",
  });
});

test("an invalid route is refused with the engine's own grammar sentence", () => {
  for (const bad of ["/Pricing", "/two words", "/pricing/", "pricing", "", "/p-assets"]) {
    assert.deepEqual(
      routeFieldDecision(bad, "/pricing", [HOME]),
      { kind: "refuse", message: INVALID_ROUTE_MESSAGE },
      `expected ${JSON.stringify(bad)} to be refused`,
    );
  }
});

test("a route another page already holds is refused before the round trip, naming that page", () => {
  assert.deepEqual(routeFieldDecision("/about", "/pricing", [HOME, ABOUT]), {
    kind: "refuse",
    message: routeTakenMessage("About"),
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

test("the suggested route is the name's slug under `/`, and nothing for no name", () => {
  assert.equal(suggestedRouteForName("Pricing Plans"), "/pricing-plans");
  assert.equal(suggestedRouteForName("  Issuing "), "/issuing");
  // An empty name suggests nothing — the box must not say "/page".
  assert.equal(suggestedRouteForName(""), "");
  assert.equal(suggestedRouteForName("   "), "");
});

test("adding a page with an empty route box takes the suggested route", () => {
  assert.deepEqual(addPageDecision("Pricing Plans", "", [HOME]), {
    kind: "commit",
    page: { id: "pricing-plans", name: "Pricing Plans", route: "/pricing-plans" },
  });
  assert.deepEqual(addPageDecision("Pricing Plans", "   ", [HOME]), {
    kind: "commit",
    page: { id: "pricing-plans", name: "Pricing Plans", route: "/pricing-plans" },
  });
});

test("adding a page with a typed route uses that route, trimmed", () => {
  assert.deepEqual(addPageDecision("Issuing for Ramp", " /issuing ", [HOME]), {
    kind: "commit",
    page: { id: "issuing-for-ramp", name: "Issuing for Ramp", route: "/issuing" },
  });
});

test("adding a page refuses, in order: unnamed, a taken name, a bad route, a taken route", () => {
  // An unnamed page has nothing to slug — refuse rather than mint "/page".
  assert.deepEqual(addPageDecision("   ", "/x", [HOME]), {
    kind: "refuse",
    message: NAME_THE_PAGE_MESSAGE,
  });
  // The id IS the name's slug, and two pages cannot share one.
  assert.deepEqual(addPageDecision("home", "/home", [HOME]), {
    kind: "refuse",
    message: PAGE_NAME_TAKEN_MESSAGE,
  });
  // `p-assets` and `asset-store` are never a first segment (they are served
  // beside a published site), so the derived route can still be invalid.
  assert.deepEqual(addPageDecision("Asset Store", "", [HOME]), {
    kind: "refuse",
    message: INVALID_ROUTE_MESSAGE,
  });
  assert.deepEqual(addPageDecision("Plans", "/Plans", [HOME]), {
    kind: "refuse",
    message: INVALID_ROUTE_MESSAGE,
  });
  // The collision names the page that holds the route.
  assert.deepEqual(addPageDecision("Plans", "/pricing", [HOME, PRICING]), {
    kind: "refuse",
    message: routeTakenMessage("Pricing"),
  });
  // The founder's own repro: the live page was renamed to the wanted route
  // first, then a new page with the same name was added.
  assert.deepEqual(
    addPageDecision("Issue", "", [{ id: "home", name: "issue", route: "/issue" }]),
    { kind: "refuse", message: routeTakenMessage("issue") },
  );
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
  assert.equal(pageWriteMessage(null, null), null);
});
