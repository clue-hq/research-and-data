import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PagesSettingsReadSchema,
  REFUSAL_MESSAGES,
  connectionView,
  stepIndex,
} from "./pages";

const base = {
  settings: { fallbackUrl: null, pageTitle: null, pageDescription: null, faviconUrl: null, socialPreviewUrl: null },
  systemHostname: { hostname: "acme.pages.cluehq.ai", label: "acme", url: "https://acme.pages.cluehq.ai" },
  customHostname: null,
};

test("the read shape parses and a missing custom hostname is not connected", () => {
  const parsed = PagesSettingsReadSchema.parse(base);
  assert.equal(connectionView(parsed.customHostname), "not_connected");
});

test("connecting, active and error views follow the status", () => {
  const records = [
    { type: "CNAME", name: "go.acme.com", required: "pages.cluehq.ai", observed: null, ok: false },
    { type: "TXT", name: "_cf-custom-hostname.go.acme.com", required: "tok", observed: null, ok: false },
  ];
  const connecting = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "verifying_ownership", records, lastCheckedAt: null, error: null, url: null } });
  assert.equal(connectionView(connecting.customHostname), "connecting");
  assert.equal(stepIndex("verifying_ownership"), 1);
  const active = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "active", records, lastCheckedAt: "2026-09-17T12:00:00Z", error: null, url: "https://go.acme.com" } });
  assert.equal(connectionView(active.customHostname), "active");
  const errored = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "error", records, lastCheckedAt: null, error: { code: "caa_blocked", detail: "CAA" }, url: null } });
  assert.equal(connectionView(errored.customHostname), "error");
  assert.equal(stepIndex("error"), -1);
});

test("a disconnecting hostname reads as connecting, with no step marked", () => {
  // The screen relies on both halves: a failed removal is shown by marking the row
  // `disconnecting`, which must flip the view to "connecting" so the 5 s poll starts,
  // and the stepper must mark no step because `disconnecting` is not a provisioning step.
  const disconnecting = PagesSettingsReadSchema.parse({
    ...base,
    customHostname: {
      hostname: "go.acme.com",
      status: "disconnecting",
      records: [],
      lastCheckedAt: "2026-09-17T12:00:00Z",
      error: null,
      url: "https://go.acme.com",
    },
  });
  assert.equal(connectionView(disconnecting.customHostname), "connecting");
  assert.equal(stepIndex("disconnecting"), -1);
});

test("a label change refused after the first publish has its own copy", () => {
  assert.equal(typeof REFUSAL_MESSAGES.label_locked, "string");
  assert.ok(REFUSAL_MESSAGES.label_locked.length > 0);
});
