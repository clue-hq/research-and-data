import { describe, expect, it, vi } from "../../__tests__/vitest-shim";
import { emptyScene } from "./__fixtures__/emptyScene";
import type { Scene } from "../contracts";
import {
  createDocument,
  fetchBrandKitDetail,
  fetchBrandKits,
  fetchDocument,
  revertDocument,
  saveLayoutManagedEditing
} from "../documentStore";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

describe("documentStore", () => {
  it("createDocument strips the local placeholder id so the server mints one", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { status: "created", document: { id: "doc_abc123" } }));

    const created = await createDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      emptyScene
    );

    expect(created).toEqual({ documentId: "doc_abc123" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://localhost:8002/documents");
    const body = JSON.parse(String(init?.body)) as { scene: Scene };
    expect(body.scene.meta).not.toHaveProperty("id");
    expect(body.scene.meta.title).toBe("Untitled design");
  });

  it("createDocument rejects on HTTP errors and missing ids", async () => {
    const failing = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(422, {}));
    await expect(
      createDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: failing }, emptyScene)
    ).rejects.toThrow("HTTP 422");

    const idless = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { status: "created", document: {} }));
    await expect(
      createDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: idless }, emptyScene)
    ).rejects.toThrow("no document id");
  });

  it("fetchDocument returns the document scene and id", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        id: "doc_abc123",
        title: "GTM poster",
        scene: { ...emptyScene, meta: { ...emptyScene.meta, id: "doc_abc123" } }
      })
    );

    const loaded = await fetchDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123"
    );

    expect(loaded.documentId).toBe("doc_abc123");
    expect(loaded.title).toBe("GTM poster");
    expect(loaded.scene.meta.id).toBe("doc_abc123");
    // Absent layout_managed_editing (legacy payload) defaults to false.
    expect(loaded.layoutManagedEditing).toBe(false);
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/documents/doc_abc123"
    );
  });

  it("fetchDocument round-trips layout_managed_editing (strictly-true only)", async () => {
    const withFlag = (value: unknown) =>
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(200, {
          id: "doc_abc123",
          title: "GTM poster",
          scene: emptyScene,
          layout_managed_editing: value
        })
      );

    const enabled = await fetchDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl: withFlag(true) },
      "doc_abc123"
    );
    expect(enabled.layoutManagedEditing).toBe(true);

    const disabled = await fetchDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl: withFlag(false) },
      "doc_abc123"
    );
    expect(disabled.layoutManagedEditing).toBe(false);

    // Anything not literally true (defensive) reads as off.
    const malformed = await fetchDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl: withFlag("yes") },
      "doc_abc123"
    );
    expect(malformed.layoutManagedEditing).toBe(false);
  });

  it("saveLayoutManagedEditing PUTs the flag and returns the persisted value", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse(200, {
          schema_version: 1,
          document_id: "doc_abc123",
          layout_managed_editing: true
        })
      );

    const persisted = await saveLayoutManagedEditing(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      true
    );

    expect(persisted).toBe(true);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:8002/documents/doc_abc123/layout-managed-editing"
    );
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: true });

    const failing = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(
      saveLayoutManagedEditing(
        { apiBaseUrl: "http://localhost:8002", fetchImpl: failing },
        "doc_abc123",
        false
      )
    ).rejects.toThrow("HTTP 500");
  });

  it("fetchDocument reports not-found and missing-scene errors clearly", async () => {
    const notFound = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(404, {}));
    await expect(
      fetchDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: notFound }, "doc_missing")
    ).rejects.toThrow("doc_missing was not found");

    const sceneless = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { id: "doc_abc123" }));
    await expect(
      fetchDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: sceneless }, "doc_abc123")
    ).rejects.toThrow("no scene");
  });

  it("revertDocument applies: POSTs the checkpoint then fetches the reverted scene (2d)", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse(200, {
          status: "applied",
          checkpoint: "agent-turn-run_1",
          reverted_batch_ids: ["batch_a", "batch_b"],
          document: { id: "doc_abc123", current_version: 12 }
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { id: "doc_abc123", title: "Poster", scene: emptyScene })
      );

    const outcome = await revertDocument(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "doc_abc123",
      "agent-turn-run_1"
    );

    expect(outcome).toEqual({
      status: "applied",
      revertedBatchIds: ["batch_a", "batch_b"],
      currentVersion: 12,
      scene: emptyScene
    });
    const [revertUrl, revertInit] = fetchImpl.mock.calls[0];
    expect(String(revertUrl)).toBe(
      "http://localhost:8002/documents/doc_abc123/revert?checkpoint=agent-turn-run_1"
    );
    expect(revertInit?.method).toBe("POST");
  });

  it("revertDocument returns an honest refusal on 409/404, throws on 5xx (2d)", async () => {
    const refusing = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(409, {
        detail: {
          code: "history.checkpoint_not_active",
          message: "checkpoint is not on the active undo path"
        }
      })
    );
    await expect(
      revertDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: refusing }, "doc_x", "cp")
    ).resolves.toEqual({
      status: "refused",
      code: "history.checkpoint_not_active",
      message: "checkpoint is not on the active undo path"
    });

    const failing = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(
      revertDocument({ apiBaseUrl: "http://localhost:8002", fetchImpl: failing }, "doc_x", "cp")
    ).rejects.toThrow("HTTP 500");
  });

  it("fetchBrandKits returns the stored brand kit summaries", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, [
        { id: "brand_acme", version: 3, name: "Acme" },
        { id: "brand_globex", version: 1, name: "Globex" }
      ])
    );

    const brandKits = await fetchBrandKits({ apiBaseUrl: "http://localhost:8002", fetchImpl });

    expect(brandKits).toEqual([
      { id: "brand_acme", version: 3, name: "Acme" },
      { id: "brand_globex", version: 1, name: "Globex" }
    ]);
    expect(String(fetchImpl.mock.calls[0][0])).toBe("http://localhost:8002/brand-kits");
  });

  it("fetchBrandKits throws on HTTP errors and tolerates a non-array payload", async () => {
    const failing = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(
      fetchBrandKits({ apiBaseUrl: "http://localhost:8002", fetchImpl: failing })
    ).rejects.toThrow("HTTP 500");

    const malformed = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, { oops: true }));
    await expect(
      fetchBrandKits({ apiBaseUrl: "http://localhost:8002", fetchImpl: malformed })
    ).resolves.toEqual([]);
  });

  it("fetchBrandKitDetail resolves the document's exact pinned version", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, {
        schema_version: 1,
        brand_kit: { id: "brand_acme", version: 6, name: "Acme" },
        brand_kit_json: {
          tokens: {
            colors: {
              "surface.page": { value: { default: { kind: "hex", value: "#FFFFFF" } } }
            }
          }
        }
      })
    );

    const detail = await fetchBrandKitDetail(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "brand_acme",
      6
    );

    expect(detail).toEqual({
      tokens: {
        colors: {
          "surface.page": { value: { default: { kind: "hex", value: "#FFFFFF" } } }
        }
      }
    });
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/brand-kits/brand_acme/versions/6"
    );
  });

  it("fetchBrandKitDetail uses the latest route only for the unversioned builtin fallback", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { brand_kit_json: { tokens: {} } })
    );

    await fetchBrandKitDetail(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "brand_kit_platform_default",
      null
    );

    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/brand-kits/brand_kit_platform_default"
    );
  });

  it("fetchBrandKitDetail routes a VERSION-PINNED builtin to the latest route too", async () => {
    // Preflight stamps kit-less scenes with the builtin's fixture version
    // (brand_kit_platform_default@1), but the builtin has no registry row —
    // the versioned endpoint 404s for it and only `/brand-kits/{id}`
    // synthesizes it. Without this rerouting, every default-branded document
    // raised "Pinned Brand Kit unavailable" and dropped to fallback tokens.
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(200, { brand_kit_json: { tokens: {} } })
    );

    await fetchBrandKitDetail(
      { apiBaseUrl: "http://localhost:8002", fetchImpl },
      "brand_kit_platform_default",
      1
    );

    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/brand-kits/brand_kit_platform_default"
    );
  });

  it("fetchBrandKitDetail throws on HTTP errors and tolerates a missing brand_kit_json", async () => {
    const failing = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(404, {}));
    await expect(
      fetchBrandKitDetail({ apiBaseUrl: "http://localhost:8002", fetchImpl: failing }, "brand_kit_x")
    ).rejects.toThrow("HTTP 404");

    const empty = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, {}));
    await expect(
      fetchBrandKitDetail({ apiBaseUrl: "http://localhost:8002", fetchImpl: empty }, "brand_kit_x")
    ).resolves.toBeNull();
  });
});

it("validates the fresh render context identity and preserves selected inline JSON", async () => {
  const context = { context_key:"exact-inline", document_id:"doc_ctx", document_version:4,
    scene_brand_ref:{id:"kit",version:3}, scene_medium:"digital", source:"document",
    brand_kit:{id:"kit",version:3,tokens:{spacing:{alias:{value:{default:32}}}}},
    mode:{values:{theme:"dark"}}, diagnostics:[] };
  const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, {
    id:"doc_ctx", current_version:4, scene:emptyScene, render_context:context,
  }));
  const loaded = await fetchDocument({apiBaseUrl:"http://localhost:8002",fetchImpl},"doc_ctx");
  expect(loaded.renderContext).toEqual(context);
  fetchImpl.mockResolvedValue(jsonResponse(200, {id:"doc_ctx", current_version:5, scene:emptyScene, render_context:context}));
  await expect(fetchDocument({apiBaseUrl:"http://localhost:8002",fetchImpl},"doc_ctx")).rejects.toThrow("another document or version");
});
