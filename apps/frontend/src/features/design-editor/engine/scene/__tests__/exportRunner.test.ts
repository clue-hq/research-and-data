import { afterEach, describe, expect, it, vi } from "../../__tests__/vitest-shim";
import { minimalScene } from "./__fixtures__/minimalScene";
import type { Scene } from "../contracts";
import { createApiExportRunner, defaultEditorExportProfile, exportProfilesForScene } from "../exportRunner";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("export runner profiles", () => {
  it("uses document export profiles as canonical overrides for built-ins", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    scene.export_profiles = [
      {
        name: "preview_svg",
        format: "svg",
        pdf_intent: "preview",
        raster: null,
        include_bleed: true,
        include_marks: false,
        embed_fonts: true
      },
      {
        name: "client_print_pdf",
        format: "pdf",
        pdf_intent: "print",
        raster: null,
        include_bleed: true,
        include_marks: true,
        embed_fonts: true
      }
    ];

    const profiles = exportProfilesForScene(scene);

    expect(profiles.find((profile) => profile.name === "preview_svg")).toMatchObject({
      include_bleed: true,
      embed_fonts: true
    });
    expect(profiles.find((profile) => profile.name === "client_print_pdf")).toMatchObject({
      format: "pdf",
      pdf_intent: "print"
    });
  });

  it("preserves failed export-preview diagnostics from the API", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          status: "failed",
          diagnostics: [
            {
              severity: "error",
              phase: "export",
              code: "LUME0101",
              message: "export request references missing page missing_page",
              subject: { page_id: "missing_page" },
              hint: "Choose a page that exists in the current scene."
            }
          ],
          export: {
            artifacts: []
          }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["missing_page"]
    });

    expect(result.status).toBe("failed");
    expect(result.artifacts).toEqual([]);
    expect(result.diagnostics).toMatchObject([
      {
        severity: "error",
        phase: "export",
        code: "LUME0101",
        message: "export request references missing page missing_page",
        hint: "Choose a page that exists in the current scene."
      }
    ]);
    expect(fetchMock).toHaveBeenCalledWith(new URL("/export-preview", "http://localhost:8000"), expect.any(Object));
  });

  it("normalizes export artifact filenames from API and legacy payloads", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          status: "ok",
          diagnostics: [],
          export: {
            artifacts: [
              {
                format: "svg",
                page_id: "page_a4",
                asset_id: null,
                filename: "page_a4.preview_svg.svg",
                sidecar_filename: "page_a4.preview_svg.sidecar.json",
                mime_type: "image/svg+xml",
                byte_length: 120,
                dimensions: {
                  width: 1080,
                  height: 1080,
                  unit: "scene",
                  source: "svg_view_box"
                },
                data_url: "data:image/svg+xml;base64,PHN2Zy8+",
                text: "<svg />",
                sidecar_json: "{}",
                sidecar_summary: {
                  profile_name: "preview_svg",
                  page_count: 1,
                  node_count: 0,
                  slot_count: 0,
                  page_ids: ["page_a4"],
                  slot_keys: []
                }
              },
              {
                format: "png",
                page_id: "page_second",
                asset_id: null,
                mime_type: "image/png",
                byte_length: 8,
                dimensions: {
                  width: 1080,
                  height: 1080,
                  unit: "px",
                  source: "png_ihdr"
                },
                data_url: "data:image/png;base64,AAAA",
                text: null,
                sidecar_json: "{}",
                sidecar_summary: null
              },
              {
                format: "pdf",
                page_id: null,
                asset_id: null,
                mime_type: "application/pdf",
                byte_length: 8,
                dimensions: {
                  width: 1080,
                  height: 1080,
                  unit: "pt",
                  source: "pdf_media_box"
                },
                data_url: "data:application/pdf;base64,AAAA",
                text: null,
                sidecar_json: "{}",
                sidecar_summary: {
                  profile_name: "print_pdf",
                  page_count: 1,
                  node_count: 0,
                  slot_count: 0,
                  page_ids: ["page_a4"],
                  slot_keys: []
                }
              }
            ]
          }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["page_a4"]
    });

    expect(result.status).toBe("ok");
    expect(result.artifacts[0]).toMatchObject({
      filename: "page_a4.preview_svg.svg",
      sidecar_filename: "page_a4.preview_svg.sidecar.json"
    });
    expect(result.artifacts[1]).toMatchObject({
      filename: "page_second.png",
      sidecar_filename: "page_second.sidecar.json"
    });
    expect(result.artifacts[2]).toMatchObject({
      filename: "page_a4.pdf",
      sidecar_filename: "page_a4.sidecar.json"
    });
  });

  it("parses the print_ready report on a print-intent PDF export", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          status: "ok",
          diagnostics: [],
          export: {
            artifacts: [
              {
                format: "pdf",
                page_id: "page_a4",
                mime_type: "application/pdf",
                byte_length: 8,
                data_url: "data:application/pdf;base64,AAAA"
              }
            ],
            print_ready: {
              ruleset: "commercial-print-v1",
              status: "warn",
              rules: [
                { id: "bleed_present", status: "pass", detail: "3mm bleed present" },
                { id: "min_dpi", status: "warn", detail: "Image below 300dpi" }
              ]
            }
          }
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["page_a4"]
    });

    expect(result.printReady).not.toBeNull();
    expect(result.printReady).toMatchObject({
      ruleset: "commercial-print-v1",
      status: "warn"
    });
    expect(result.printReady?.rules).toHaveLength(2);
    expect(result.printReady?.rules[1]).toMatchObject({ id: "min_dpi", status: "warn", detail: "Image below 300dpi" });
  });

  it("leaves printReady null when the export payload omits it", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({ schema_version: 1, status: "ok", diagnostics: [], export: { artifacts: [] } }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["page_a4"]
    });

    expect(result.printReady).toBeNull();
  });

  it("reads the codes of the response's warnings as the errors this export let through", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          status: "ok",
          diagnostics: [],
          warnings: [{ code: "LUMV0903", message: "text node separator exceeds available height" }, { message: "no code" }],
          export: { artifacts: [] }
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({ apiBaseUrl: "http://localhost:8000" });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["page_a4"]
    });

    expect(result.advisoryCodes).toEqual(["LUMV0903"]);
  });

  it("uses the persisted document export route when a document id is configured", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          schema_version: 1,
          status: "failed",
          diagnostics: {
            current: [
              {
                severity: "error",
                phase: "export",
                code: "LUME0101",
                message: "export request references missing page missing_page",
                subject: { kind: "page", id: "missing_page" },
                hint: "Choose a page that exists in the current document."
              }
            ]
          },
          export: {
            artifacts: []
          }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const runner = createApiExportRunner({
      apiBaseUrl: "http://localhost:8000",
      documentId: "doc_saved"
    });

    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["missing_page"]
    });

    expect(result.status).toBe("failed");
    expect(result.diagnostics).toMatchObject([
      {
        severity: "error",
        phase: "export",
        code: "LUME0101",
        message: "export request references missing page missing_page",
        subject: { kind: "page", id: "missing_page" },
        hint: "Choose a page that exists in the current document."
      }
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("/documents/doc_saved/export", "http://localhost:8000"),
      expect.objectContaining({
        method: "POST"
      })
    );
    const [, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      format: "svg",
      page_ids: ["missing_page"],
      profile: defaultEditorExportProfile()
    });
    expect(body.scene).toBeUndefined();
    // The editor's export is a PREVIEW: the endpoint's persist_preflight
    // default (true) would write the token-baked preflight scene + ops into
    // the document behind the edit queue's back — stale base_version (next
    // edit rejected as concurrent) and server-side token baking. The
    // 2d browser e2e caught exactly this as a 409 after Accept.
    expect(body.persist_preflight).toBe(false);
  });

  // Added at AD1 final review (not upstream): the runner's transport must be
  // INJECTABLE, not the module-global fetch. AD3/AD4 consumers reach the design
  // API only through the BFF, and the same-origin re-mount lives inside
  // designBffConfig()'s fetchImpl — a module-global call would bypass it.
  it("routes the request through an injected fetchImpl, never the global", async () => {
    const injected = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ schema_version: 1, status: "ok", diagnostics: [], export: { artifacts: [] } }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
    );
    // The global is stubbed to a hard failure: if the module ever reaches for
    // it instead of the injected transport, this test fails loudly.
    const globalFetch = vi.fn(async () => {
      throw new Error("the export runner must not call the module-global fetch");
    });
    vi.stubGlobal("fetch", globalFetch);

    const runner = createApiExportRunner({
      apiBaseUrl: "http://localhost:8000",
      fetchImpl: injected as unknown as typeof fetch
    });
    const result = await runner({
      scene: minimalScene,
      profile: defaultEditorExportProfile(),
      pageIds: ["page_a4"]
    });

    expect(result.status).toBe("ok");
    expect(injected.mock.calls).toHaveLength(1);
    expect(globalFetch.mock.calls).toHaveLength(0);
    expect(String(injected.mock.calls[0][0])).toBe("http://localhost:8000/export-preview");
  });
});
