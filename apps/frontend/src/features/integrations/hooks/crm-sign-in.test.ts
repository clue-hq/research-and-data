import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { CrmConnectError } from "../model/crm";
import type { CrmConnectFlowEvent } from "../model/crm-connect-flow";
import { CrmWorkspaceChangedError } from "../data/crm-settings.repository";
import { crmSettingsConnectHandlers, openSignInWindow, settingsSignIn } from "./crm-sign-in";

const REQUEST = "5b7e1f7a-2c3d-4e5f-8a9b-0c1d2e3f4a5b";
const URL_ = "https://connect.example.test/link";

/** A fake `window.open`: records what was opened, and the blank tab's fate. */
function fakeOpener({ blocked = false } = {}) {
  const tab = { location: { href: "about:blank" }, closed: false, close() { this.closed = true; } };
  const opened: { url: string | undefined; features: string | undefined }[] = [];
  const open = ((url?: string | URL, _target?: string, features?: string) => {
    opened.push({ url: url === undefined ? undefined : String(url), features });
    return blocked ? null : tab;
  }) as unknown as typeof window.open;
  return { tab, opened, open };
}

test("openSignInWindow opens the blank tab before waiting, then navigates it", async () => {
  const { tab, opened, open } = fakeOpener();
  let resolve!: (url: string) => void;
  const pending = openSignInWindow(() => new Promise((r) => (resolve = r)), { open });
  assert.deepEqual(opened, [{ url: "about:blank", features: undefined }]); // inside the click
  resolve(URL_);
  assert.equal(await pending, "opened");
  assert.equal(tab.location.href, URL_);
});

test("openSignInWindow falls back to a new window when the blank tab was blocked", async () => {
  const { opened, open } = fakeOpener({ blocked: true });
  assert.equal(await openSignInWindow(async () => URL_, { open }), "opened");
  assert.deepEqual(opened[1], { url: URL_, features: "noopener" });
});

test("openSignInWindow closes the tab when the link fails, and rethrows", async () => {
  const { tab, open } = fakeOpener();
  await assert.rejects(openSignInWindow(async () => { throw new Error("no"); }, { open }), { message: "no" });
  assert.equal(tab.closed, true);
});

test("openSignInWindow closes the tab and navigates nowhere when cancelled while loading", async () => {
  const { tab, open } = fakeOpener();
  assert.equal(await openSignInWindow(async () => URL_, { open, cancelled: () => true }), "cancelled");
  assert.equal(tab.closed, true);
  assert.equal(tab.location.href, "about:blank");
});

function deps(overrides: Partial<Parameters<typeof settingsSignIn>[0]> = {}) {
  const events: CrmConnectFlowEvent[] = [];
  const calls = { reloads: 0, requests: 0, links: [] as string[] };
  const { tab, open } = fakeOpener();
  const value: Parameters<typeof settingsSignIn>[0] = {
    requestConnect: async () => {
      calls.requests += 1;
      return REQUEST;
    },
    requestLink: async (requestId) => {
      calls.links.push(requestId);
      return URL_;
    },
    open,
    cancelled: () => false,
    dispatch: (event) => events.push(event),
    reload: () => {
      calls.reloads += 1;
    },
    ...overrides,
  };
  return { value, events, calls, tab };
}

test("a sign-in opens a Settings request, its link, and waits on that request", async () => {
  const { value, events, calls, tab } = deps();
  await settingsSignIn(value, "connect", "hubspot", null);
  assert.equal(calls.requests, 1);
  assert.deepEqual(calls.links, [REQUEST]);
  assert.equal(tab.location.href, URL_);
  assert.deepEqual(events, [{ type: "opened", mode: "connect", provider: "hubspot", requestId: REQUEST }]);
});

test("Open sign-in again and Try again reuse the request", async () => {
  const { value, calls } = deps();
  await settingsSignIn(value, "reconnect", "salesforce", "existing");
  assert.equal(calls.requests, 0);
  assert.deepEqual(calls.links, ["existing"]);
});

test("a workspace switched in another tab reloads the page and changes nothing", async () => {
  for (const error of [
    new CrmWorkspaceChangedError(new ClueApiError("x", { code: "WORKSPACE_CHANGED", status: 409, requestId: null })),
    new CrmConnectError("x", "WORKSPACE_CHANGED"),
  ]) {
    const { value, events, calls, tab } = deps({ requestConnect: async () => { throw error; } });
    await settingsSignIn(value, "connect", "hubspot", null);
    assert.equal(calls.reloads, 1);
    assert.deepEqual(events, []);
    assert.equal(tab.closed, true);
  }
});

test("refusals become the failed dialog, in Settings' own words", async () => {
  const cases: [unknown, string][] = [
    [new ClueApiError("x", { code: "PERMISSION_REQUIRED", status: 403, requestId: null }), "Only a workspace owner or admin can connect the CRM."],
    [
      new CrmConnectError("This connect card is no longer open — the CRM may already be connected.", "connect_request_closed"),
      "This connection attempt has ended — the CRM may already be connected. Reload the page to check.",
    ],
    [new CrmConnectError("Only a workspace owner or admin can connect the CRM.", "PERMISSION_REQUIRED"), "Only a workspace owner or admin can connect the CRM."],
    [new Error("boom"), "Could not start the HubSpot connection. Please try again."],
  ];
  for (const [error, message] of cases) {
    const { value, events, calls } = deps({ requestLink: async () => { throw error; } });
    await settingsSignIn(value, "connect", "hubspot", null);
    assert.equal(calls.reloads, 0);
    assert.deepEqual(events, [{ type: "failed", mode: "connect", provider: "hubspot", message }]);
  }
});

test("cancelled while the link loads: the tab closes and nothing starts", async () => {
  const { value, events, tab } = deps({ cancelled: () => true });
  await settingsSignIn(value, "connect", "hubspot", null);
  assert.deepEqual(events, []);
  assert.equal(tab.closed, true);
});

test("connected closes the flow and refreshes the server data; a failed sign-in names the CRM", () => {
  const events: CrmConnectFlowEvent[] = [];
  let refreshes = 0;
  const handlers = crmSettingsConnectHandlers((event) => events.push(event), () => (refreshes += 1));
  handlers.onConnected();
  handlers.onFailed("switch", "salesforce");
  assert.equal(refreshes, 1);
  assert.deepEqual(events, [
    { type: "connected" },
    { type: "failed", mode: "switch", provider: "salesforce", message: "Salesforce didn’t connect. Try again." },
  ]);
});
