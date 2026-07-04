import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AssetRecord, Node, Operation } from "@/engine/contracts";
import { ImageInspectorSection } from "../ImageInspectorSection";

const API_BASE = "http://api.test";

function imageNode(overrides: Partial<Node> = {}): Node {
  return {
    id: "node_hero",
    name: "Hero",
    kind: { kind: "image", asset_id: "asset_existing", alt: "old alt" },
    transform: { x: 0, y: 0, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
    size: { width: { kind: "fixed", value: 1080 }, height: { kind: "fixed", value: 1350 } },
    children: [],
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    source_asset_id: "asset_existing",
    asset_placement: { fit: "cover", focal_point: { x: 0.5, y: 0.5 }, alt_text: "old alt" },
    clip: false,
    layout: null,
    computed: { layout_bounds: { x: 0, y: 0, width: 1080, height: 1350 } },
    locked: false,
    ...overrides
  } as Node;
}

function generatedRecord(): AssetRecord {
  return {
    id: "asset_gen_1",
    label: "generated",
    kind: "raster_image",
    status: "ready",
    source: { kind: "generated", request_id: "asset_gen_1", model: "test/image-model" } as AssetRecord["source"],
    media: { mime_type: "image/png" } as AssetRecord["media"]
  } as AssetRecord;
}

function placementPatch(call: Operation[]) {
  const op = call[0];
  if (op.kind !== "update_node") throw new Error("expected update_node");
  if (op.patch.asset_placement.kind !== "set") throw new Error("expected asset_placement set");
  return op.patch.asset_placement.value;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ImageInspectorSection", () => {
  it("emits an asset_placement update when the fit mode changes", () => {
    const onOperations = vi.fn();
    render(
      <ImageInspectorSection node={imageNode()} asset={null} apiBaseUrl={API_BASE} onOperations={onOperations} />
    );

    fireEvent.change(screen.getByLabelText("Image fit"), { target: { value: "contain" } });

    expect(onOperations).toHaveBeenCalledTimes(1);
    const placement = placementPatch(onOperations.mock.calls[0][0]);
    expect(placement.fit).toBe("contain");
    expect(placement.focal_point).toEqual({ x: 0.5, y: 0.5 });
  });

  it("emits an asset_placement update when a focal axis changes", () => {
    const onOperations = vi.fn();
    render(
      <ImageInspectorSection node={imageNode()} asset={null} apiBaseUrl={API_BASE} onOperations={onOperations} />
    );

    fireEvent.change(screen.getByLabelText("Focal X"), { target: { value: "0.2" } });

    const placement = placementPatch(onOperations.mock.calls[0][0]);
    expect(placement.focal_point).toEqual({ x: 0.2, y: 0.5 });
  });

  it("emits an asset_placement update when alt text changes", () => {
    const onOperations = vi.fn();
    render(
      <ImageInspectorSection node={imageNode()} asset={null} apiBaseUrl={API_BASE} onOperations={onOperations} />
    );

    fireEvent.change(screen.getByLabelText("Image alt text"), { target: { value: "a calm clinic" } });

    const placement = placementPatch(onOperations.mock.calls[0][0]);
    expect(placement.alt_text).toBe("a calm clinic");
  });

  it("generates into the same node and carries the existing placement forward", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/assets/generate") && init?.method === "POST") {
        return new Response(
          JSON.stringify({ schema_version: 1, asset: generatedRecord(), deduplicated: false, diagnostics: [] }),
          { status: 200 }
        );
      }
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const node = imageNode({ asset_placement: { fit: "cover", focal_point: { x: 0.3, y: 0.7 }, alt_text: "hero" } });
    const onOperations = vi.fn();
    render(<ImageInspectorSection node={node} asset={null} apiBaseUrl={API_BASE} onOperations={onOperations} />);

    fireEvent.change(screen.getByLabelText("Image prompt"), { target: { value: "editorial clinic photo" } });
    fireEvent.click(screen.getByTestId("image-generate"));

    await waitFor(() => expect(onOperations).toHaveBeenCalled());

    // POSTed to /assets/generate with the provider + a frame-derived resolution.
    const [, init] = fetchMock.mock.calls.find(([url]) => String(url).includes("/assets/generate"))!;
    const body = JSON.parse(String(init?.body));
    expect(body.provider).toBe("image-gen-v1");
    expect(body.prompt).toBe("editorial clinic photo");
    // 1080x1350 portrait → long edge 1536 on height.
    expect(body.height).toBe(1536);
    expect(body.width).toBe(Math.round((1536 * 1080) / 1350));

    const ops = onOperations.mock.calls.at(-1)![0] as Operation[];
    expect(ops.map((op) => op.kind)).toEqual(["upsert_asset", "place_asset_in_node"]);
    const place = ops[1];
    if (place.kind !== "place_asset_in_node") throw new Error("expected place_asset_in_node");
    expect(place.node_id).toBe("node_hero");
    expect(place.asset_id).toBe("asset_gen_1");
    expect(place.placement.fit).toBe("cover");
    expect(place.placement.focal_point).toEqual({ x: 0.3, y: 0.7 }); // carried forward
  });

  it("surfaces a failed generation (e.g. model not configured)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: { code: "image_model.not_configured", message: "not configured" } }), {
          status: 503
        })
      )
    );
    const onOperations = vi.fn();
    render(<ImageInspectorSection node={imageNode()} asset={null} apiBaseUrl={API_BASE} onOperations={onOperations} />);

    fireEvent.change(screen.getByLabelText("Image prompt"), { target: { value: "anything" } });
    fireEvent.click(screen.getByTestId("image-generate"));

    await waitFor(() => {
      expect(screen.getByTestId("image-status").getAttribute("data-status")).toBe("failed");
    });
    expect(screen.getByTestId("image-status").textContent).toContain("not configured");
    // No placement ops emitted on failure.
    expect(onOperations).not.toHaveBeenCalled();
  });
});
