import { describe, expect, it } from "vitest";
import phaseFManifest from "../../../../../crates/lumen-core/fixtures/conformance/phase_f_manifest.json";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Node, Orientation, Page, PagePreset, Scene, Unit } from "../contracts";
import type { EditorExportResult } from "../exportRunner";
import { artifactForPage, exportParityReport } from "../exportParity";

describe("export parity", () => {
  it("matches custom square page dimensions against SVG viewBox", () => {
    const scene = customSquareScene();
    const report = exportParityReport(scene, "page_a4", exportResult("page_a4", "0 0 1080 1080"));

    expect(report.status).toBe("match");
    expect(report.canvas).toEqual({ width: 1080, height: 1080 });
    expect(report.export).toEqual({ width: 1080, height: 1080 });
    expect(report.diagnostics[0].code).toBe("EDITOR_EXPORT_PARITY_OK");
  });

  it("matches canonical print SVG viewBox even when physical attributes are present", () => {
    const scene = canonicalA4Scene();
    const report = exportParityReport(
      scene,
      "page_a4",
      exportResult(
        "page_a4",
        "0 0 595.2755905511812 841.8897637795276",
        '<svg width="210mm" height="297mm" viewBox="0 0 595.2755905511812 841.8897637795276"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>'
      )
    );

    expect(report.status).toBe("match");
    expect(report.canvas?.width).toBeCloseTo(595.3, 1);
    expect(report.export?.width).toBeCloseTo(595.3, 1);
    expect(report.export?.height).toBeCloseTo(841.9, 1);
    expect(report.diagnostics[0].code).toBe("EDITOR_EXPORT_PARITY_OK");
  });

  it("does not reuse another page's artifact for active-page parity", () => {
    const scene = customSquareScene();
    scene.pages.page_second = {
      ...scene.pages.page_a4,
      id: "page_second",
      name: "Second Page",
      children: []
    };
    const result = exportResult("page_second", "0 0 1080 1080");

    expect(artifactForPage(result, "page_a4")).toBeNull();

    const report = exportParityReport(scene, "page_a4", result);

    expect(report.status).toBe("unavailable");
    expect(report.canvas).toBeNull();
    expect(report.export).toBeNull();
    expect(report.diagnostics[0]).toMatchObject({
      severity: "warning",
      code: "EDITOR_EXPORT_PARITY_ARTIFACT_REQUIRED",
      message: "Export the active page before comparing preview parity."
    });
  });

  it("matches non-square custom page dimensions without preset coercion", () => {
    const customCases = [
      { label: "wide leaderboard", width: 1200, height: 628 },
      { label: "portrait social", width: 1080, height: 1350 },
      { label: "email hero", width: 600, height: 800 }
    ];

    for (const customCase of customCases) {
      const scene = customPxScene(customCase.width, customCase.height);
      const report = exportParityReport(
        scene,
        "page_a4",
        exportResult("page_a4", `0 0 ${customCase.width} ${customCase.height}`)
      );

      expect(report.status, customCase.label).toBe("match");
      expect(report.canvas, customCase.label).toEqual({
        width: customCase.width,
        height: customCase.height
      });
      expect(report.export, customCase.label).toEqual({
        width: customCase.width,
        height: customCase.height
      });
      expect(report.diagnostics[0].code, customCase.label).toBe("EDITOR_EXPORT_PARITY_OK");
    }
  });

  it("matches Phase F manifest page cases against canonical SVG export dimensions", () => {
    for (const pageCase of phaseFPageCases()) {
      const scene = sceneFromPhaseFCase(pageCase);
      const report = exportParityReport(
        scene,
        pageCase.pageId,
        exportResult(pageCase.pageId, `0 0 ${pageCase.expectedCanvasWidth} ${pageCase.expectedCanvasHeight}`)
      );

      expect(report.status, pageCase.id).toBe("match");
      expect(report.canvas, pageCase.id).toEqual({
        width: pageCase.expectedCanvasWidth,
        height: pageCase.expectedCanvasHeight
      });
      expect(report.export, pageCase.id).toEqual({
        width: pageCase.expectedCanvasWidth,
        height: pageCase.expectedCanvasHeight
      });
      expect(report.diagnostics[0].code, pageCase.id).toBe("EDITOR_EXPORT_PARITY_OK");
    }
  });

  it("matches non-px SVG dimensions by converting export units into canvas pixels", () => {
    const report = exportParityReport(
      minimalScene,
      "page_a4",
      exportResult(
        "page_a4",
        "0 0 210 297",
        '<svg width="210mm" height="297mm" viewBox="0 0 210 297"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>'
      )
    );

    expect(report.status).toBe("match");
    expect(report.canvas?.width).toBeCloseTo(793.7, 1);
    expect(report.export?.width).toBeCloseTo(793.7, 1);
    expect(report.export?.height).toBeCloseTo(1122.5, 1);
  });

  it("flags canvas and exported SVG dimension mismatches", () => {
    const scene = customSquareScene();
    const report = exportParityReport(scene, "page_a4", exportResult("page_a4", "0 0 1080 1079"));

    expect(report.status).toBe("mismatch");
    expect(report.diagnostics[0]).toMatchObject({
      severity: "error",
      phase: "export",
      code: "EDITOR_EXPORT_PARITY_MISMATCH"
    });
  });

  it("flags missing exported text even when page dimensions match", () => {
    const scene = customSquareScene();
    const report = exportParityReport(
      scene,
      "page_a4",
      exportResult(
        "page_a4",
        "0 0 1080 1080",
        '<svg viewBox="0 0 1080 1080"><text data-lumen-node-id="node_contact_name">Wrong Name</text></svg>'
      )
    );

    expect(report.status).toBe("mismatch");
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_MISSING_TEXT"
        })
      ])
    );
  });

  it("flags stale exported nodes that are no longer in the canonical scene", () => {
    const scene = customSquareScene();
    const report = exportParityReport(
      scene,
      "page_a4",
      exportResult(
        "page_a4",
        "0 0 1080 1080",
        `<svg viewBox="0 0 1080 1080">
          <text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text>
          <text data-lumen-node-id="stale_node">Stale export</text>
        </svg>`
      )
    );

    expect(report.status).toBe("mismatch");
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_EXTRA_SVG_NODE"
        }),
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_EXTRA_SIDECAR_NODE"
        }),
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_SVG_NODE_COUNT_MISMATCH"
        }),
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_SIDECAR_NODE_COUNT_MISMATCH"
        })
      ])
    );
  });

  it("flags sidecar node-count mismatches for non-SVG visual artifacts", () => {
    const scene = customSquareScene();
    scene.pages.page_a4.children.push("node_hero_asset");
    scene.nodes.node_hero_asset = imageNode("node_hero_asset", "asset_missing_hero");
    const result = pngExportResult("page_a4", 1080, 1080);
    result.artifacts[0].sidecar_json = JSON.stringify({
      nodes: [{ node_id: "node_contact_name" }]
    });

    const report = exportParityReport(scene, "page_a4", result);

    expect(report.status).toBe("mismatch");
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_SIDECAR_NODE_COUNT_MISMATCH"
        }),
        expect.objectContaining({
          severity: "error",
          code: "EDITOR_EXPORT_PARITY_MISSING_SIDECAR_NODE"
        })
      ])
    );
  });

  it("warns when parity preview still contains unresolved token carriers", () => {
    const scene = customSquareScene();
    scene.nodes.node_contact_name.fills = [
      {
        id: "paint_token_text",
        paint: {
          kind: "token",
          token: "surface.brand"
        }
      }
    ];
    const report = exportParityReport(scene, "page_a4", exportResult("page_a4", "0 0 1080 1080"));

    expect(report.status).toBe("match");
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "warning",
          code: "EDITOR_EXPORT_PARITY_UNRESOLVED_TOKENS"
        })
      ])
    );
  });

  it("warns when image nodes are still exported as asset placeholders", () => {
    const scene = customSquareScene();
    scene.pages.page_a4.children.push("node_hero_asset");
    scene.nodes.node_hero_asset = imageNode("node_hero_asset", "asset_missing_hero");
    const svg = `
      <svg viewBox="0 0 1080 1080">
        <text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text>
        <g data-lumen-node-id="node_hero_asset" data-lumen-unsupported="image" data-lumen-asset-id="asset_missing_hero" />
      </svg>
    `;
    const report = exportParityReport(scene, "page_a4", exportResult("page_a4", "0 0 1080 1080", svg));

    expect(report.status).toBe("match");
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "warning",
          code: "EDITOR_EXPORT_PARITY_ASSET_PLACEHOLDER"
        }),
        expect.objectContaining({
          severity: "warning",
          code: "EDITOR_EXPORT_PARITY_UNRESOLVED_ASSETS"
        })
      ])
    );
  });

  it("treats scaled PNG dimensions as valid raster parity when aspect ratio is preserved", () => {
    const scene = customSquareScene();
    const report = exportParityReport(scene, "page_a4", pngExportResult("page_a4", 2160, 2160));

    expect(report.status).toBe("match");
    expect(report.canvas).toEqual({ width: 1080, height: 1080 });
    expect(report.export).toEqual({ width: 2160, height: 2160 });
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "advice",
          code: "EDITOR_EXPORT_PARITY_SCALED_RASTER"
        })
      ])
    );
  });

  it("flags PNG raster dimensions that change the page aspect ratio", () => {
    const scene = customSquareScene();
    const report = exportParityReport(scene, "page_a4", pngExportResult("page_a4", 1080, 900));

    expect(report.status).toBe("mismatch");
    expect(report.diagnostics[0]).toMatchObject({
      severity: "error",
      code: "EDITOR_EXPORT_PARITY_MISMATCH"
    });
  });

  it("treats PDF bleed MediaBox dimensions as valid print parity", () => {
    const scene = customSquareScene();
    scene.pages.page_a4.bleed = {
      x: -18,
      y: -18,
      width: 1116,
      height: 1116
    };

    const report = exportParityReport(scene, "page_a4", pdfExportResult("page_a4", 1116, 1116));

    expect(report.status).toBe("match");
    expect(report.canvas).toEqual({ width: 1080, height: 1080 });
    expect(report.export).toEqual({ width: 1116, height: 1116 });
    expect(report.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          severity: "advice",
          code: "EDITOR_EXPORT_PARITY_BLEED_MEDIA_BOX"
        })
      ])
    );
  });

  it("matches canonical PDF MediaBox point dimensions directly", () => {
    const scene = canonicalA4Scene();
    const report = exportParityReport(
      scene,
      "page_a4",
      pdfExportResult("page_a4", 595.2755905511812, 841.8897637795276)
    );

    expect(report.status).toBe("match");
    expect(report.canvas?.width).toBeCloseTo(595.3, 1);
    expect(report.export?.width).toBeCloseTo(595.3, 1);
    expect(report.export?.height).toBeCloseTo(841.9, 1);
  });

  it("converts non-px PDF MediaBox dimensions into canvas pixels for comparison", () => {
    const report = exportParityReport(minimalScene, "page_a4", pdfExportResult("page_a4", 595.2756, 841.8898));

    expect(report.status).toBe("match");
    expect(report.canvas?.width).toBeCloseTo(793.7, 1);
    expect(report.export?.width).toBeCloseTo(793.7, 1);
    expect(report.export?.height).toBeCloseTo(1122.5, 1);
  });
});

function customSquareScene(): Scene {
  return customPxScene(1080, 1080);
}

function canonicalA4Scene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4.size = {
    width: 595.2755905511812,
    height: 841.8897637795276,
    unit: "pt",
    preset: "a4",
    orientation: "portrait",
    source: {
      width: 210,
      height: 297,
      unit: "mm"
    },
    output: {
      physical: {
        width: 210,
        height: 297,
        unit: "mm"
      }
    }
  };
  return scene;
}

function customPxScene(width: number, height: number): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4.size = {
    width,
    height,
    unit: "px",
    preset: "custom",
    orientation: width >= height ? "landscape" : "portrait"
  };
  return scene;
}

function exportResult(pageId: string, viewBox: string, text?: string): EditorExportResult {
  const svg =
    text ??
    `<svg viewBox="${viewBox}"><text data-lumen-node-id="node_contact_name">Dr. Priya Sharma</text></svg>`;
  return {
    status: "ok",
    diagnostics: [],
    artifacts: [
      {
        format: "svg",
        page_id: pageId,
        asset_id: null,
        filename: `${pageId}.preview_svg.svg`,
        sidecar_filename: `${pageId}.preview_svg.sidecar.json`,
        mime_type: "image/svg+xml",
        byte_length: 80,
        dimensions: {
          width: 1080,
          height: 1080,
          unit: "scene",
          source: "svg_view_box"
        },
        data_url: "data:image/svg+xml;base64,PHN2Zy8+",
        text: svg,
        sidecar_json: JSON.stringify({
          nodes: nodeIdsFromSvg(svg).map((node_id) => ({ node_id }))
        }),
        sidecar_summary: {
          profile_name: "preview_svg",
          page_count: 1,
          node_count: nodeIdsFromSvg(svg).length,
          slot_count: 0,
          page_ids: [pageId],
          slot_keys: []
        }
      }
    ]
  };
}

function pngExportResult(pageId: string, width: number, height: number): EditorExportResult {
  return nonSvgExportResult(pageId, "png", "image/png", width, height, "px", "png_ihdr");
}

function pdfExportResult(pageId: string, width: number, height: number): EditorExportResult {
  return nonSvgExportResult(pageId, "pdf", "application/pdf", width, height, "pt", "pdf_media_box");
}

function nonSvgExportResult(
  pageId: string,
  format: "png" | "pdf",
  mimeType: string,
  width: number,
  height: number,
  unit: string,
  source: string
): EditorExportResult {
  return {
    status: "ok",
    diagnostics: [],
    artifacts: [
      {
        format,
        page_id: pageId,
        asset_id: null,
        filename: `${pageId}.preview_${format}.${format}`,
        sidecar_filename: `${pageId}.preview_${format}.sidecar.json`,
        mime_type: mimeType,
        byte_length: 120,
        dimensions: {
          width,
          height,
          unit,
          source
        },
        data_url: `data:${mimeType};base64,AAAA`,
        text: null,
        sidecar_json: JSON.stringify({
          nodes: [{ node_id: "node_contact_name" }]
        }),
        sidecar_summary: {
          profile_name: `preview_${format}`,
          page_count: 1,
          node_count: 1,
          slot_count: 0,
          page_ids: [pageId],
          slot_keys: []
        }
      }
    ]
  };
}

function nodeIdsFromSvg(svg: string): string[] {
  return [...svg.matchAll(/data-lumen-node-id="([^"]+)"/g)].map((match) => match[1]);
}

function imageNode(id: string, assetId: string): Node {
  return {
    id,
    name: "Hero asset",
    kind: {
      kind: "image",
      asset_id: assetId,
      alt: null
    },
    transform: {
      x: 0,
      y: 0,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 320
      },
      height: {
        kind: "fixed",
        value: 200
      }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: {
      top_left: 0,
      top_right: 0,
      bottom_right: 0,
      bottom_left: 0
    },
    opacity: 1,
    opacity_token: null,
    source_asset_id: null,
    asset_placement: null,
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
}

interface PhaseFPageCase {
  id: string;
  pageId: string;
  page: Page;
  expectedCanvasWidth: number;
  expectedCanvasHeight: number;
}

function phaseFPageCases(): PhaseFPageCase[] {
  return phaseFManifest.artifacts.flatMap((artifact): PhaseFPageCase[] => {
    if (!("page" in artifact) || !artifact.page) {
      return [];
    }
    const page = artifact.page;
    const unit = unitFromManifest(page.unit);
    const unitScale = unitScaleForTest(unit);
    return [
      {
        id: artifact.id,
        pageId: page.id,
        page: {
          ...minimalScene.pages.page_a4,
          id: page.id,
          name: artifact.label,
          size: {
            width: page.width,
            height: page.height,
            unit,
            preset: presetFromManifest(page.preset),
            orientation: orientationFromManifest(page.orientation)
          },
          children: ["node_contact_name"]
        },
        expectedCanvasWidth: page.width * unitScale,
        expectedCanvasHeight: page.height * unitScale
      }
    ];
  });
}

function sceneFromPhaseFCase(pageCase: PhaseFPageCase): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages = {
    [pageCase.pageId]: pageCase.page
  };
  return scene;
}

function unitFromManifest(value: string): Unit {
  switch (value) {
    case "pt":
    case "px":
    case "mm":
    case "in":
      return value;
  }
  throw new Error(`Unsupported Phase F manifest unit: ${value}`);
}

function presetFromManifest(value: string): PagePreset {
  switch (value) {
    case "a4":
    case "us_letter":
    case "custom":
    case "linkedin_ad":
    case "envelope_dl":
      return value;
  }
  throw new Error(`Unsupported Phase F manifest preset: ${value}`);
}

function orientationFromManifest(value: string): Orientation {
  switch (value) {
    case "portrait":
    case "landscape":
      return value;
  }
  throw new Error(`Unsupported Phase F manifest orientation: ${value}`);
}

function unitScaleForTest(unit: Unit): number {
  switch (unit) {
    case "pt":
    case "px":
      return 1;
    case "mm":
      return 96 / 25.4;
    case "in":
      return 96;
  }
}
