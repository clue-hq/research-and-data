import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emptyScene } from "@/fixtures/emptyScene";
import { editorWorkspaceId } from "../editorConfig";
import {
  fetchBrandKitDetailFull,
  fetchBrandKitList,
  setBrandKitApproval,
  setBrandKitLogo
} from "../brandHub";
import {
  createDocument,
  fetchBrandKitDetail,
  fetchBrandKits,
  fetchDocument,
  resolveAndFreezeScene,
  revertDocument,
  saveAgentInstructions,
  saveLayoutManagedEditing
} from "../documentStore";

/**
 * The O4 workspace seam is strict: the API refuses any request without
 * `X-Workspace-Id` (401 `workspace.header_required`), and production callers
 * reach these modules through their DEFAULT transport — no page or component
 * injects `fetchImpl`. Every other suite passes a mock `fetchImpl`, so the
 * defaults are dead code to those tests; that blind spot is exactly how
 * documentStore/brandHub shipped bare-`fetch` defaults past D2.5A and 401'd
 * only in a live browser. This suite calls each exported fetcher WITHOUT
 * `fetchImpl` and asserts the header reaches the wire.
 */

const API = "http://localhost:8002";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function workspaceHeaderOf(init: RequestInit | undefined): string | null {
  return new Headers(init?.headers).get("X-Workspace-Id");
}

const CASES: Array<[name: string, call: () => Promise<unknown>]> = [
  ["documentStore.createDocument", () => createDocument({ apiBaseUrl: API }, emptyScene)],
  ["documentStore.revertDocument", () => revertDocument({ apiBaseUrl: API }, "doc_1", "cp_1")],
  ["documentStore.fetchDocument", () => fetchDocument({ apiBaseUrl: API }, "doc_1")],
  ["documentStore.fetchBrandKits", () => fetchBrandKits({ apiBaseUrl: API })],
  ["documentStore.fetchBrandKitDetail", () => fetchBrandKitDetail({ apiBaseUrl: API }, "kit_1")],
  [
    "documentStore.resolveAndFreezeScene",
    () => resolveAndFreezeScene({ apiBaseUrl: API }, emptyScene)
  ],
  [
    "documentStore.saveAgentInstructions",
    () => saveAgentInstructions({ apiBaseUrl: API }, "doc_1", "stay on brand")
  ],
  [
    "documentStore.saveLayoutManagedEditing",
    () => saveLayoutManagedEditing({ apiBaseUrl: API }, "doc_1", true)
  ],
  ["brandHub.fetchBrandKitList", () => fetchBrandKitList({ apiBaseUrl: API })],
  ["brandHub.fetchBrandKitDetailFull", () => fetchBrandKitDetailFull({ apiBaseUrl: API }, "kit_1")],
  [
    "brandHub.setBrandKitApproval",
    () => setBrandKitApproval({ apiBaseUrl: API }, "kit_1", "approved")
  ],
  [
    "brandHub.setBrandKitLogo",
    () => setBrandKitLogo({ apiBaseUrl: API }, "kit_1", { assetId: "asset_1" })
  ]
];

describe("workspace-header defaults (O4 seam)", () => {
  const globalFetch = vi.fn<typeof fetch>();

  beforeEach(() => {
    globalFetch.mockReset();
    globalFetch.mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", globalFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(CASES)("%s attaches X-Workspace-Id by default", async (_name, call) => {
    // Only the transport is under test: an empty 200 body may make the
    // function throw while parsing, and that is fine — the request(s) it
    // already sent must each carry the workspace header.
    await call().catch(() => undefined);

    expect(globalFetch.mock.calls.length).toBeGreaterThan(0);
    for (const [, init] of globalFetch.mock.calls) {
      expect(workspaceHeaderOf(init)).toBe(editorWorkspaceId());
    }
  });
});
