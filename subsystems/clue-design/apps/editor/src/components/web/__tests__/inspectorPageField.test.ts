/**
 * F5 task 21 — the route field's pure decision, copied from the platform
 * shell's `inspector-page-field.ts` so the two editors refuse a route in the
 * same words and in the same order.
 *
 * Order is the guarantee: an unchanged draft is a `noop` BEFORE any validation,
 * so a field can never refuse the document's own current route, and a refusal
 * carries no route at all — which is what makes "no write fires on an invalid
 * draft" structural rather than a habit of the component.
 */
import { describe, expect, it } from "vitest";

import {
  INVALID_ROUTE_MESSAGE,
  ROUTE_TAKEN_MESSAGE,
  routeFieldDecision
} from "../inspectorPageField";

describe("routeFieldDecision", () => {
  it("commits a changed, grammatical, free route (trimmed)", () => {
    expect(routeFieldDecision("/pricing", "/", ["/about"])).toEqual({
      kind: "commit",
      route: "/pricing"
    });
    expect(routeFieldDecision("  /pricing  ", "/", [])).toEqual({
      kind: "commit",
      route: "/pricing"
    });
  });

  it("is a noop when the draft is the live route", () => {
    expect(routeFieldDecision("/pricing", "/pricing", ["/about"])).toEqual({ kind: "noop" });
    // …even when the sibling list mistakenly contains this page's own route.
    expect(routeFieldDecision("/pricing", "/pricing", ["/pricing"])).toEqual({ kind: "noop" });
  });

  it("refuses an ungrammatical route without spending a round trip", () => {
    expect(routeFieldDecision("Pricing", "/", [])).toEqual({
      kind: "refuse",
      message: INVALID_ROUTE_MESSAGE
    });
    expect(routeFieldDecision("/Pricing", "/", [])).toEqual({
      kind: "refuse",
      message: INVALID_ROUTE_MESSAGE
    });
    expect(routeFieldDecision("", "/", [])).toEqual({
      kind: "refuse",
      message: INVALID_ROUTE_MESSAGE
    });
  });

  it("refuses a route another page already holds", () => {
    expect(routeFieldDecision("/about", "/", ["/about", "/pricing"])).toEqual({
      kind: "refuse",
      message: ROUTE_TAKEN_MESSAGE
    });
  });

  it("checks grammar before collision", () => {
    // A route that is both ungrammatical and taken reads as the grammar
    // refusal — the same order the engine validates in.
    expect(routeFieldDecision("/Pricing", "/", ["/Pricing"])).toEqual({
      kind: "refuse",
      message: INVALID_ROUTE_MESSAGE
    });
  });
});
