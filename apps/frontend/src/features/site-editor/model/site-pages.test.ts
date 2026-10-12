import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import {
  EMPTY_ROUTE_HISTORY,
  filterPageRows,
  parseRouteInput,
  sitePageRows,
  stepRoute,
  visitRoute,
} from "./site-pages";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/pricing": { root: { props: { title: "Pricing for SCSD" } }, content: [] },
    "/analysis": { root: { props: { title: "The free Provider Impact Analysis" } }, content: [] },
    "/": { root: { props: { title: "Garner Health for SCSD" } }, content: [] },
    "/faq": { root: { props: {} }, content: [] },
  },
  shell: null,
  agent_sections: {},
});

test("pages list home first, then the other routes in order, titled by their page title", () => {
  assert.deepEqual(
    sitePageRows(site, "/analysis").map((row) => [row.route, row.title, row.home, row.active]),
    [
      ["/", "Garner Health for SCSD", true, false],
      ["/analysis", "The free Provider Impact Analysis", false, true],
      ["/faq", "/faq", false, false],
      ["/pricing", "Pricing for SCSD", false, false],
    ],
  );
  assert.deepEqual(sitePageRows(null, "/"), []);
});

test("search matches a title or a route, ignoring case", () => {
  const rows = sitePageRows(site, "/");
  assert.deepEqual(filterPageRows(rows, "impact").map((row) => row.route), ["/analysis"]);
  assert.deepEqual(filterPageRows(rows, "FAQ").map((row) => row.route), ["/faq"]);
  assert.equal(filterPageRows(rows, "  ").length, 4);
});

test("back and forward walk the visited pages; a new visit drops the forward history", () => {
  let history = visitRoute(EMPTY_ROUTE_HISTORY, "/");
  history = visitRoute(history, "/analysis");
  history = visitRoute(history, "/analysis");
  assert.deepEqual(history, { entries: ["/", "/analysis"], index: 1 });
  const back = stepRoute(history, -1);
  assert.equal(back.route, "/");
  assert.equal(stepRoute(back.history, -1).route, null);
  assert.equal(visitRoute(back.history, "/").index, 0, "the frame's answer to a back step adds nothing");
  const branched = visitRoute(back.history, "/faq");
  assert.deepEqual(branched, { entries: ["/", "/faq"], index: 1 });
  assert.equal(stepRoute(branched, 1).route, null);
});

test("an address typed in the bar jumps only to a page the site has", () => {
  assert.equal(parseRouteInput("/analysis", site), "/analysis");
  assert.equal(parseRouteInput("analysis", site), "/analysis");
  assert.equal(parseRouteInput(" /Pricing/ ", site), "/pricing");
  assert.equal(parseRouteInput("", site), "/");
  assert.equal(parseRouteInput("/careers", site), null);
  assert.equal(parseRouteInput("https://garnerhealth.com", site), null);
});
