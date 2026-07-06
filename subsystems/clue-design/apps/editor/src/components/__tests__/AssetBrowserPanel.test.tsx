import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssetRecord, Operation } from "@/engine/contracts";
import {
  buildNodePlacementOperations,
  buildSlotPlacementOperations
} from "@/engine/assetLibrary";
import { AssetBrowserPanel } from "../AssetBrowserPanel";

const API_BASE = "http://localhost:8000";

function libraryRecord(id: string, label: string, kind: AssetRecord["kind"]): AssetRecord {
  return {
    id,
    label,
    kind,
    status: "ready",
    source: { kind: "uploaded", filename: `${id}.png`, uploaded_by: "editor" },
    media: {
      mime_type: "image/png",
      filename: `${id}.png`,
      byte_length: 96,
      digest: { algorithm: "sha256", value: "f".repeat(64) },
      location: {
        provider: "local-store",
        opaque_ref: `sha256/ff/${"f".repeat(64)}`,
        url: null
      },
      thumbnail: {
        location: {
          provider: "local-store",
          opaque_ref: `sha256/aa/${"a".repeat(64)}`,
          url: null
        },
        mime_type: "image/png"
      }
    },
    tags: []
  };
}

function mockFetch(records: AssetRecord[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          asset: libraryRecord("asset_uploaded", "uploaded.png", "raster_image"),
          deduplicated: false,
          diagnostics: []
        }),
        { status: 200 }
      );
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AssetBrowserPanel", () => {
  it("lists library assets with thumbnails", async () => {
    mockFetch([
      libraryRecord("asset_logo", "Acme logo", "logo"),
      libraryRecord("asset_qr", "Acme QR", "vector")
    ]);

    render(
      <AssetBrowserPanel apiBaseUrl={API_BASE} selectedNodeId={null} onOperations={() => {}} />
    );

    await waitFor(() => {
      expect(screen.getByTestId("asset-asset_logo")).toBeTruthy();
    });
    const thumbnail = screen.getByAltText("Acme logo") as HTMLImageElement;
    expect(thumbnail.src).toBe(`${API_BASE}/assets/asset_logo/thumbnail`);
    expect(screen.getByTestId("asset-asset_qr").textContent).toContain("vector");
  });

  it("placing an asset emits canonical upsert + place operations", async () => {
    mockFetch([libraryRecord("asset_logo", "Acme logo", "logo")]);
    const received: Operation[][] = [];

    render(
      <AssetBrowserPanel
        apiBaseUrl={API_BASE}
        selectedNodeId="node_hero_image"
        onOperations={(operations) => received.push(operations)}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("asset-asset_logo")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Place" }));

    expect(received).toHaveLength(1);
    const [operations] = received;
    expect(operations.map((operation) => operation.kind)).toEqual([
      "upsert_asset",
      "place_asset_in_node"
    ]);
    const placement = operations[1];
    if (placement.kind !== "place_asset_in_node") {
      throw new Error("expected place_asset_in_node");
    }
    expect(placement.node_id).toBe("node_hero_image");
    expect(placement.asset_id).toBe("asset_logo");
    expect(placement.placement.alt_text).toBe("Acme logo");
  });

  it("carries the selected node's placement forward when replacing an image", async () => {
    mockFetch([libraryRecord("asset_logo", "Acme logo", "logo")]);
    const received: Operation[][] = [];

    render(
      <AssetBrowserPanel
        apiBaseUrl={API_BASE}
        selectedNodeId="node_hero_image"
        selectedNodePlacement={{ fit: "cover", focal_point: { x: 0.3, y: 0.7 }, alt_text: "Existing hero" }}
        onOperations={(operations) => received.push(operations)}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("asset-asset_logo")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Place" }));

    const placement = received[0][1];
    if (placement.kind !== "place_asset_in_node") {
      throw new Error("expected place_asset_in_node");
    }
    // Replacing swaps the asset but preserves fit + focal (not reset to {}).
    expect(placement.placement.fit).toBe("cover");
    expect(placement.placement.focal_point).toEqual({ x: 0.3, y: 0.7 });
    expect(placement.placement.alt_text).toBe("Existing hero");
  });

  it("disables placement without a selected node", async () => {
    mockFetch([libraryRecord("asset_logo", "Acme logo", "logo")]);

    render(
      <AssetBrowserPanel apiBaseUrl={API_BASE} selectedNodeId={null} onOperations={() => {}} />
    );

    await waitFor(() => {
      expect(screen.getByTestId("asset-asset_logo")).toBeTruthy();
    });
    const button = screen.getByRole("button", { name: "Place" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("uploads through multipart form data and refreshes the list", async () => {
    const fetchMock = mockFetch([]);

    render(
      <AssetBrowserPanel apiBaseUrl={API_BASE} selectedNodeId={null} onOperations={() => {}} />
    );

    const input = screen.getByLabelText("Upload asset") as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], "logo.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Uploaded uploaded.png")).toBeTruthy();
    });

    const uploadCall = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(uploadCall).toBeTruthy();
    const body = uploadCall?.[1]?.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get("file") as File).name).toBe("logo.png");
    expect(body.get("label")).toBe("logo.png");
  });

  it("refetches the library when refreshToken bumps", async () => {
    const fetchMock = mockFetch([libraryRecord("asset_logo", "Acme logo", "logo")]);

    const { rerender } = render(
      <AssetBrowserPanel
        apiBaseUrl={API_BASE}
        selectedNodeId={null}
        refreshToken={0}
        onOperations={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("asset-asset_logo")).toBeTruthy();
    });
    const initialListCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/assets")).length;

    rerender(
      <AssetBrowserPanel
        apiBaseUrl={API_BASE}
        selectedNodeId={null}
        refreshToken={1}
        onOperations={() => {}}
      />
    );

    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/assets")).length;
      expect(listCalls).toBe(initialListCalls + 1);
    });
  });

  it("surfaces upload rejections from the API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(
          JSON.stringify({
            detail: {
              code: "ingest.mime_mismatch",
              message: "declared MIME type contradicts sniffed type"
            }
          }),
          { status: 400 }
        );
      }
      return new Response(JSON.stringify({ assets: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AssetBrowserPanel apiBaseUrl={API_BASE} selectedNodeId={null} onOperations={() => {}} />
    );

    const input = screen.getByLabelText("Upload asset") as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], "logo.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(
        screen.getByText("declared MIME type contradicts sniffed type")
      ).toBeTruthy();
    });
  });
});

describe("placement operation builders", () => {
  it("slot placement mirrors the node pair against the slot", () => {
    const record = libraryRecord("asset_logo", "Acme logo", "logo");
    const operations = buildSlotPlacementOperations(record, "slot_hero", {
      fit: "cover",
      focal_point: { x: 0.5, y: 0.4 }
    });
    expect(operations[0]).toEqual({ kind: "upsert_asset", asset: record });
    expect(operations[1]).toEqual({
      kind: "place_asset_in_slot",
      slot_id: "slot_hero",
      asset_id: "asset_logo",
      placement: {
        fit: "cover",
        focal_point: { x: 0.5, y: 0.4 },
        alt_text: "Acme logo"
      }
    });
  });

  it("replace keeps node identity by re-placing onto the same node", () => {
    const original = libraryRecord("asset_a", "First", "raster_image");
    const replacement = libraryRecord("asset_b", "Second", "raster_image");
    const first = buildNodePlacementOperations(original, "node_hero_image");
    const second = buildNodePlacementOperations(replacement, "node_hero_image");
    expect(first[1]).toMatchObject({ node_id: "node_hero_image", asset_id: "asset_a" });
    expect(second[1]).toMatchObject({ node_id: "node_hero_image", asset_id: "asset_b" });
  });
});
