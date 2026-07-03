import { describe, expect, it, vi } from "vitest";
import { emptyScene } from "@/fixtures/emptyScene";
import type { Scene } from "../contracts";
import { createDocument, fetchDocument } from "../documentStore";

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
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      "http://localhost:8002/documents/doc_abc123"
    );
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
});
