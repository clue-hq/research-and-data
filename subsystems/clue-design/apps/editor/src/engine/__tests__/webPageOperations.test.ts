/**
 * F5 task 21 — the dev shell's page-level primitives, kept in lockstep with the
 * platform shell's copy (`apps/frontend/.../engine/webDocuments.ts`).
 *
 * Three separable things are pinned here because all three are pure:
 *   - the three page ops serialize EXACTLY as the engine's serde expects
 *     (snake_case, `set_page_meta` omitting a key it was not given, `add_page`
 *     minting the conventional `root_<id>` container);
 *   - `routeIsValid` mirrors the Rust `route_is_valid` — including the two
 *     reserved first segments served beside a published site, and
 *     `manifest.json` in ANY position;
 *   - `resolveActivePageId` is the switcher's whole fallback rule, so the
 *     component owns no branching the tests cannot see.
 */
import { describe, expect, it } from "vitest";

import {
  addPageOp,
  findWebNode,
  removePageOp,
  resolveActivePageId,
  routeIsValid,
  setPageMetaOp,
  type WebDoc,
  type WebPageSummary
} from "@/engine/webDocuments";

describe("page operation builders", () => {
  it("emits only the meta keys it was given", () => {
    expect(setPageMetaOp("home", { route: "/pricing" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      route: "/pricing"
    });
    // The absence is structural, not cosmetic: the engine's fields are
    // `Option<String>` with `skip_serializing_if`, so a present `name` key
    // would be read as an intent to rename.
    expect(Object.keys(setPageMetaOp("home", { route: "/pricing" }))).not.toContain("name");
    expect(setPageMetaOp("home", { name: "Home" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      name: "Home"
    });
    expect(Object.keys(setPageMetaOp("home", { name: "Home" }))).not.toContain("route");
    expect(setPageMetaOp("home", { name: "Home", route: "/" })).toEqual({
      kind: "set_page_meta",
      page_id: "home",
      name: "Home",
      route: "/"
    });
  });

  it("adds a page as a single empty root_<id> container", () => {
    expect(addPageOp({ id: "pricing", name: "Pricing", route: "/pricing" })).toEqual({
      kind: "add_page",
      page: {
        id: "pricing",
        name: "Pricing",
        route: "/pricing",
        root: "root_pricing",
        nodes: {
          root_pricing: { id: "root_pricing", kind: "container", classes: "", children: [] }
        }
      }
    });
  });

  it("omits index unless one is given (the engine reads absence as append)", () => {
    const appended = addPageOp({ id: "a", name: "A", route: "/a" });
    expect(Object.keys(appended)).not.toContain("index");
    expect(addPageOp({ id: "a", name: "A", route: "/a" }, 2)).toMatchObject({ index: 2 });
    expect(addPageOp({ id: "a", name: "A", route: "/a" }, 0)).toMatchObject({ index: 0 });
  });

  it("removes a page by id", () => {
    expect(removePageOp("pricing")).toEqual({ kind: "remove_page", page_id: "pricing" });
  });
});

describe("routeIsValid", () => {
  const GOOD = ["/", "/pricing", "/pricing/enterprise-2026"];
  const BAD = [
    "",
    "pricing",
    "/Pricing",
    "/pricing/",
    "//a",
    "/a b",
    "/a_b",
    "/manifest.json",
    "/p-assets/x",
    "/asset-store/x",
    "/x/manifest.json",
    `/${"a".repeat(128)}`
  ];

  it.each(GOOD)("accepts %o", (route) => {
    expect(routeIsValid(route)).toBe(true);
  });

  it.each(BAD)("refuses %o", (route) => {
    expect(routeIsValid(route)).toBe(false);
  });
});

describe("resolveActivePageId", () => {
  const PAGES: WebPageSummary[] = [
    { id: "home", name: "Home", route: "/" },
    { id: "pricing", name: "Pricing", route: "/pricing" }
  ];

  it("keeps a requested page that the document still has", () => {
    expect(resolveActivePageId(PAGES, "pricing")).toBe("pricing");
  });

  it("falls back to the first page when nothing is requested", () => {
    expect(resolveActivePageId(PAGES, null)).toBe("home");
    expect(resolveActivePageId(PAGES, "")).toBe("home");
  });

  it("falls back to the first page when the requested one is gone", () => {
    // The page the user was on was removed (by an agent turn, an undo, or the
    // remove control in the platform shell) — the switcher must not point at a
    // page the document no longer has.
    expect(resolveActivePageId(PAGES, "careers")).toBe("home");
  });

  it("resolves to no page at all when the document has none", () => {
    // An empty (freshly created) web document. The empty string is what makes
    // the render fetch send NO page_id, which is the endpoint's own first-page
    // default — the exact pre-F5 behaviour.
    expect(resolveActivePageId([], "home")).toBe("");
    expect(resolveActivePageId(undefined, "home")).toBe("");
  });
});

describe("findWebNode across pages", () => {
  // The cross-page id rule (F5): node ids are NOT unique across pages — the
  // same authored id can exist on two pages with different content. A
  // first-match walk therefore hands the inspector, the move planner, and the
  // rich-text commit the WRONG page's node whenever a duplicate id exists.
  const DOC: WebDoc = {
    pages: [
      {
        id: "home",
        name: "Home",
        route: "/",
        root: "root",
        nodes: {
          root: { id: "root", kind: "container", classes: "", children: ["hero"] },
          hero: { id: "hero", kind: "text", classes: "home-hero", content: "Home hero" }
        }
      },
      {
        id: "pricing",
        name: "Pricing",
        route: "/pricing",
        root: "root",
        nodes: {
          root: { id: "root", kind: "container", classes: "", children: ["hero"] },
          hero: { id: "hero", kind: "text", classes: "pricing-hero", content: "Pricing hero" }
        }
      }
    ]
  };

  it("resolves a shared id on the ACTIVE page, not the first one that has it", () => {
    const located = findWebNode(DOC, "hero", "pricing");
    expect(located?.pageId).toBe("pricing");
    expect(located?.node.classes).toBe("pricing-hero");
  });

  it("still resolves the active page's own node when it is the first page", () => {
    const located = findWebNode(DOC, "hero", "home");
    expect(located?.pageId).toBe("home");
    expect(located?.node.classes).toBe("home-hero");
  });

  it("falls back to a first-match walk when the active page lacks the node", () => {
    const doc: WebDoc = {
      pages: [
        DOC.pages![0],
        {
          id: "about",
          name: "About",
          route: "/about",
          root: "root_about",
          nodes: { root_about: { id: "root_about", kind: "container", classes: "", children: [] } }
        }
      ]
    };
    const located = findWebNode(doc, "hero", "about");
    expect(located?.pageId).toBe("home");
  });

  it("returns null for an unknown node, an empty id, or no document", () => {
    expect(findWebNode(DOC, "nope", "home")).toBeNull();
    expect(findWebNode(DOC, null, "home")).toBeNull();
    expect(findWebNode(null, "hero", "home")).toBeNull();
  });
});
