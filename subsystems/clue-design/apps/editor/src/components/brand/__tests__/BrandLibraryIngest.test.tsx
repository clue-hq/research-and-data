import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssetRecord } from "@/engine/contracts";
import { AssetLibrary } from "../AssetLibrary";
import { IngestConsole } from "../IngestConsole";

const API_BASE = "http://localhost:8000";

function assetRecord(
  id: string,
  label: string,
  kind: AssetRecord["kind"],
  tags: string[],
  created: string
): AssetRecord {
  return {
    id,
    label,
    kind,
    status: "ready",
    source: { kind: "manual", label },
    media: {
      mime_type: "image/png",
      filename: `${id}.png`,
      byte_length: 2048,
      digest: { algorithm: "sha256", value: "f".repeat(64) },
      location: { provider: "local-store", opaque_ref: `sha256/ff/${id}`, url: null }
    },
    provenance: { created_at: created } as AssetRecord["provenance"],
    tags
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// --------------------------------------------------------------------------
// Library
// --------------------------------------------------------------------------

function mockLibraryFetch(
  records: AssetRecord[],
  descriptions: Record<string, unknown> = {}
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "PUT" && url.includes("/description")) {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      return new Response(
        JSON.stringify({ ...body, origin: "human", updated_at: "2026-07-06T10:00:00Z" }),
        { status: 200 }
      );
    }
    if (url.includes("/assets/descriptions")) {
      return new Response(JSON.stringify({ schema_version: 1, descriptions }), {
        status: 200
      });
    }
    if (url.includes("/assets")) {
      return new Response(
        JSON.stringify({ schema_version: 1, assets: records, count: records.length }),
        { status: 200 }
      );
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("AssetLibrary", () => {
  it("renders assets, narrows by tag facet, and filters by search", async () => {
    mockLibraryFetch([
      assetRecord("a_logo", "Acme logo", "logo", ["logo", "upload"], "2026-07-06T09:00:00Z"),
      assetRecord("a_photo", "Team photo", "raster_image", ["photo", "website"], "2026-07-06T08:00:00Z")
    ]);

    render(<AssetLibrary apiBaseUrl={API_BASE} />);

    await waitFor(() => {
      expect(screen.getByTestId("lib-asset-a_logo")).toBeTruthy();
    });
    expect(screen.getByTestId("lib-asset-a_photo")).toBeTruthy();

    // Facet counts include an "All assets" total plus per-tag chips.
    const logoFacet = screen.getByRole("button", { name: /^logo\s*1$/ });
    fireEvent.click(logoFacet);
    expect(screen.getByTestId("lib-asset-a_logo")).toBeTruthy();
    expect(screen.queryByTestId("lib-asset-a_photo")).toBeNull();

    // Reset to all, then search narrows by title substring.
    fireEvent.click(screen.getByRole("button", { name: /^All assets/ }));
    fireEvent.change(screen.getByLabelText("Search") ?? screen.getByRole("searchbox"), {
      target: { value: "team" }
    });
    expect(screen.queryByTestId("lib-asset-a_logo")).toBeNull();
    expect(screen.getByTestId("lib-asset-a_photo")).toBeTruthy();
  });

  it("opens the lightbox and saves an edited description via PUT", async () => {
    const fetchMock = mockLibraryFetch(
      [assetRecord("a_logo", "Acme logo", "logo", ["logo"], "2026-07-06T09:00:00Z")],
      { a_logo: { title: "Acme logo", description: "Old text", origin: "engine" } }
    );

    render(<AssetLibrary apiBaseUrl={API_BASE} />);

    await waitFor(() => {
      expect(screen.getByTestId("lib-asset-a_logo")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("lib-asset-a_logo"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Old text")).toBeTruthy();

    // Edit the Description field.
    const editButtons = within(dialog).getAllByRole("button", { name: "Edit" });
    // Description is the second editable row (title, description, usage).
    fireEvent.click(editButtons[1]);
    const textarea = within(dialog).getByLabelText("Description value");
    fireEvent.change(textarea, { target: { value: "Primary lockup" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(within(dialog).getByText("Primary lockup")).toBeTruthy();
    });

    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(putCall).toBeTruthy();
    expect(String(putCall?.[0])).toContain("/assets/a_logo/description");
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({ description: "Primary lockup" });
    // Origin flipped to human → "edited" marker shows.
    expect(within(dialog).getByText("edited")).toBeTruthy();
  });

  it("closes the lightbox on Escape", async () => {
    mockLibraryFetch([
      assetRecord("a_logo", "Acme logo", "logo", ["logo"], "2026-07-06T09:00:00Z")
    ]);
    render(<AssetLibrary apiBaseUrl={API_BASE} />);
    await waitFor(() => expect(screen.getByTestId("lib-asset-a_logo")).toBeTruthy());
    fireEvent.click(screen.getByTestId("lib-asset-a_logo"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

// --------------------------------------------------------------------------
// Ingest
// --------------------------------------------------------------------------

function queuedJob(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "job_1",
    kind: "website",
    status: "queued",
    stage: "queued",
    progress: 0,
    brand_kit_id: null,
    brand_kit_version: null,
    error: null,
    created_at: "2026-07-06T10:00:00Z",
    updated_at: "2026-07-06T10:00:00Z",
    ...overrides
  };
}

describe("IngestConsole", () => {
  it("submits a website scan and polls until succeeded with a review link", async () => {
    vi.useFakeTimers();
    const poll = [
      queuedJob({ status: "running", stage: "capturing", progress: 0.4 }),
      queuedJob({
        status: "succeeded",
        stage: "done",
        progress: 1,
        brand_kit_id: "kit_42"
      })
    ];
    let pollIndex = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/ingest/website")) {
        return new Response(JSON.stringify({ schema_version: 1, job: queuedJob() }), {
          status: 200
        });
      }
      if (url.includes("/brand-kits/ingest/job_1")) {
        const job = poll[Math.min(pollIndex, poll.length - 1)];
        pollIndex += 1;
        return new Response(JSON.stringify({ schema_version: 1, job }), { status: 200 });
      }
      if (url.endsWith("/brand-kits/ingest")) {
        return new Response(JSON.stringify({ jobs: [] }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<IngestConsole apiBaseUrl={API_BASE} />);

    fireEvent.change(screen.getByLabelText("Site URL"), {
      target: { value: "https://acme.com" }
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Scan site" }));
    });

    // Progress panel appears after the POST resolves.
    expect(screen.getByTestId("ingest-progress-fill")).toBeTruthy();

    // Advance two poll intervals → running, then succeeded.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    const reviewLink = screen.getByRole("link", { name: "Review kit" });
    expect(reviewLink.getAttribute("href")).toBe("/brand/kits/kit_42");

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) => init?.method === "POST" && String(url).includes("/ingest/website")
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({ url: "https://acme.com" });
  });

  it("shows an error pill when the job fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/ingest/website")) {
        return new Response(JSON.stringify({ schema_version: 1, job: queuedJob() }), {
          status: 200
        });
      }
      if (url.includes("/brand-kits/ingest/job_1")) {
        return new Response(
          JSON.stringify({
            schema_version: 1,
            job: queuedJob({
              status: "failed",
              error: { message: "site unreachable" }
            })
          }),
          { status: 200 }
        );
      }
      if (url.endsWith("/brand-kits/ingest")) {
        return new Response(JSON.stringify({ jobs: [] }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<IngestConsole apiBaseUrl={API_BASE} />);
    fireEvent.change(screen.getByLabelText("Site URL"), {
      target: { value: "https://acme.com" }
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Scan site" }));
    });
    expect(screen.getByTestId("ingest-progress-fill")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(screen.getByText("site unreachable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
