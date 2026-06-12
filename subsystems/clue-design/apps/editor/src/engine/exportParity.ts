import type { Diagnostic, NodeId, Page, PageId, Scene } from "./contracts";
import type { EditorExportArtifact, EditorExportResult } from "./exportRunner";
import { pageDescriptor } from "./renderAdapter";

export interface ExportParityReport {
  status: "match" | "mismatch" | "unavailable";
  diagnostics: Diagnostic[];
  canvas: {
    width: number;
    height: number;
  } | null;
  export: {
    width: number;
    height: number;
  } | null;
}

export function artifactForPage(
  result: EditorExportResult | null,
  pageId: PageId | null
): EditorExportArtifact | null {
  if (!result) {
    return null;
  }
  if (pageId) {
    return result.artifacts.find((artifact) => artifact.page_id === pageId && isVisualArtifact(artifact)) ?? null;
  }
  return result.artifacts.find(isVisualArtifact) ?? null;
}

export function exportParityReport(
  scene: Scene,
  pageId: PageId | null,
  result: EditorExportResult | null
): ExportParityReport {
  if (!pageId || !scene.pages[pageId]) {
    return unavailable("EDITOR_EXPORT_PARITY_PAGE_REQUIRED", "Select a page before comparing canvas and export preview.");
  }

  const artifact = artifactForPage(result, pageId);
  if (!artifact) {
    return unavailable("EDITOR_EXPORT_PARITY_ARTIFACT_REQUIRED", "Export the active page before comparing preview parity.");
  }

  const page = scene.pages[pageId];
  const descriptor = pageDescriptor(page);
  const exportSize = comparableArtifactSize(artifact, page);
  if (!exportSize) {
    return {
      status: "unavailable",
      canvas: {
        width: descriptor.width,
        height: descriptor.height
      },
      export: null,
      diagnostics: [
        exportDiagnostic(
          "EDITOR_EXPORT_PARITY_UNSUPPORTED_FORMAT",
          "Export artifact dimensions are unavailable or use an unsupported unit for parity comparison."
        )
      ]
    };
  }

  const canvas = {
    width: descriptor.width,
    height: descriptor.height
  };
  const semanticDiagnostics = semanticParityDiagnostics(scene, pageId, artifact);
  const dimensionResult = dimensionParity(canvas, exportSize, artifact, page);
  if (dimensionResult.matches) {
    const hasSemanticError = semanticDiagnostics.some((diagnostic) => diagnostic.severity === "error");
    return {
      status: hasSemanticError ? "mismatch" : "match",
      canvas,
      export: exportSize,
      diagnostics: [
        {
          severity: "advice",
          phase: "export",
          code: "EDITOR_EXPORT_PARITY_OK",
          message: dimensionResult.message,
          subject: {
            kind: "page",
            id: pageId
          },
          hint: null
        },
        ...dimensionResult.diagnostics,
        ...semanticDiagnostics
      ]
    };
  }

  return {
    status: "mismatch",
    canvas,
    export: exportSize,
    diagnostics: [
      {
        severity: "error",
        phase: "export",
        code: "EDITOR_EXPORT_PARITY_MISMATCH",
        message: dimensionResult.message,
        subject: {
          kind: "page",
          id: pageId
        },
        hint: "Fix the editor render adapter or export adapter before trusting the preview."
      },
      ...semanticDiagnostics
    ]
  };
}

function comparableArtifactSize(artifact: EditorExportArtifact, page: Page): { width: number; height: number } | null {
  if (artifact.format === "svg") {
    return svgExportSize(artifact.text);
  }

  const dimensions = artifact.dimensions;
  if (!dimensions) {
    return null;
  }

  if (artifact.format === "png" && dimensions.unit === "px") {
    return {
      width: dimensions.width,
      height: dimensions.height
    };
  }

  if (artifact.format === "pdf" && dimensions.unit === "pt") {
    const scale = pdfPointToCanvasScale(page);
    return {
      width: dimensions.width * scale,
      height: dimensions.height * scale
    };
  }

  return null;
}

function dimensionParity(
  canvas: { width: number; height: number },
  exportSize: { width: number; height: number },
  artifact: EditorExportArtifact,
  page: Page
): { matches: boolean; message: string; diagnostics: Diagnostic[] } {
  if (sameSize(canvas, exportSize)) {
    return {
      matches: true,
      message: `${artifact.format.toUpperCase()} export dimensions match the canvas page bounds.`,
      diagnostics: []
    };
  }

  if (artifact.format === "png" && sameAspectRatio(canvas, exportSize)) {
    const scaleX = exportSize.width / canvas.width;
    const scaleY = exportSize.height / canvas.height;
    return {
      matches: true,
      message: `PNG raster dimensions preserve the canvas page aspect ratio at ${formatScale(scaleX)}x scale.`,
      diagnostics: [
        exportDiagnostic(
          "EDITOR_EXPORT_PARITY_SCALED_RASTER",
          `PNG raster ${formatSize(exportSize)} is a scaled export of canvas page ${formatSize(canvas)}.`,
          "advice",
          nearlyEqual(scaleX, scaleY)
            ? "Scaled PNG outputs are valid when requested by the export profile."
            : "Check the raster profile if non-uniform scaling was not expected."
        )
      ]
    };
  }

  if (artifact.format === "pdf" && page.bleed) {
    const bleedSize = {
      width: page.bleed.width * pageUnitScale(page),
      height: page.bleed.height * pageUnitScale(page)
    };
    if (sameSize(bleedSize, exportSize)) {
      return {
        matches: true,
        message: "PDF MediaBox matches the bleed-expanded page bounds.",
        diagnostics: [
          exportDiagnostic(
            "EDITOR_EXPORT_PARITY_BLEED_MEDIA_BOX",
            `PDF export MediaBox ${formatSize(exportSize)} includes bleed around canvas trim ${formatSize(canvas)}.`,
            "advice",
            "This is expected when the export profile includes bleed."
          )
        ]
      };
    }
  }

  return {
    matches: false,
    message: `Canvas ${formatSize(canvas)} does not match ${artifact.format.toUpperCase()} export ${formatSize(exportSize)}.`,
    diagnostics: []
  };
}

function semanticParityDiagnostics(scene: Scene, pageId: PageId, artifact: EditorExportArtifact): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  const expectedNodeIds = pageNodeIds(scene, pageId);
  const expectedNodeIdSet = new Set(expectedNodeIds);
  const sidecarNodeIds = nodeIdsFromSidecar(artifact.sidecar_json);

  if (sidecarNodeIds) {
    if (sidecarNodeIds.size !== expectedNodeIds.length) {
      diagnostics.push(
        diagnosticForPage(
          "error",
          "EDITOR_EXPORT_PARITY_SIDECAR_NODE_COUNT_MISMATCH",
          `Export sidecar describes ${sidecarNodeIds.size} node${sidecarNodeIds.size === 1 ? "" : "s"} but the canvas page has ${expectedNodeIds.length}.`,
          pageId,
          "Regenerate export from the current canonical scene before trusting this preview."
        )
      );
    }
    for (const nodeId of expectedNodeIds) {
      if (!sidecarNodeIds.has(nodeId)) {
        diagnostics.push(
          diagnosticForNode(
            "error",
            "EDITOR_EXPORT_PARITY_MISSING_SIDECAR_NODE",
            `Export sidecar is missing scene node ${nodeId}.`,
            nodeId,
            "Regenerate export from the canonical scene or fix sidecar generation."
          )
        );
      }
    }
    for (const nodeId of sidecarNodeIds) {
      if (!expectedNodeIdSet.has(nodeId)) {
        diagnostics.push(
          diagnosticForNode(
            "error",
            "EDITOR_EXPORT_PARITY_EXTRA_SIDECAR_NODE",
            `Export sidecar contains stale node ${nodeId} that is not on the canvas page.`,
            nodeId,
            "Regenerate export from the canonical scene; stale sidecar nodes indicate preview drift."
          )
        );
      }
    }
  }

  if (artifact.text) {
    const svgNodeIds = nodeIdsFromSvg(artifact.text);
    if (svgNodeIds.size > 0 && svgNodeIds.size !== expectedNodeIds.length) {
      diagnostics.push(
        diagnosticForPage(
          "error",
          "EDITOR_EXPORT_PARITY_SVG_NODE_COUNT_MISMATCH",
          `SVG export contains ${svgNodeIds.size} node marker${svgNodeIds.size === 1 ? "" : "s"} but the canvas page has ${expectedNodeIds.length}.`,
          pageId,
          "Fix the export adapter or regenerate the preview from the current scene."
        )
      );
    }
    for (const nodeId of expectedNodeIds) {
      if (!svgNodeIds.has(nodeId)) {
        diagnostics.push(
          diagnosticForNode(
            "error",
            "EDITOR_EXPORT_PARITY_MISSING_SVG_NODE",
            `SVG export is missing scene node ${nodeId}.`,
            nodeId,
            "Fix the export adapter before trusting this preview."
          )
        );
      }
    }
    for (const nodeId of svgNodeIds) {
      if (!expectedNodeIdSet.has(nodeId)) {
        diagnostics.push(
          diagnosticForNode(
            "error",
            "EDITOR_EXPORT_PARITY_EXTRA_SVG_NODE",
            `SVG export contains stale node ${nodeId} that is not on the canvas page.`,
            nodeId,
            "Regenerate export from the canonical scene; stale SVG node markers indicate preview drift."
          )
        );
      }
    }

    for (const nodeId of expectedNodeIds) {
      const node = scene.nodes[nodeId];
      if (node?.kind.kind !== "text" || !node.kind.content.trim()) {
        continue;
      }
      if (!svgContainsText(artifact.text, node.kind.content)) {
        diagnostics.push(
          diagnosticForNode(
            "error",
            "EDITOR_EXPORT_PARITY_MISSING_TEXT",
            `SVG export is missing text content from node ${nodeId}.`,
            nodeId,
            "Compare the text renderer and export text layout path."
          )
        );
      }
    }

    if (artifact.text.includes("data-lumen-unsupported=\"image\"")) {
      diagnostics.push(
        exportDiagnostic(
          "EDITOR_EXPORT_PARITY_ASSET_PLACEHOLDER",
          "SVG export contains image placeholders because asset bytes are not resolved yet.",
          "warning",
          "Wire the asset resolver before treating image-heavy previews as final."
        )
      );
    }
  }

  const unresolvedTokens = unresolvedTokenReferencesForPage(scene, pageId);
  if (unresolvedTokens.length > 0) {
    diagnostics.push(
      exportDiagnostic(
        "EDITOR_EXPORT_PARITY_UNRESOLVED_TOKENS",
        `Scene still contains unresolved token references: ${unresolvedTokens.join(", ")}.`,
        "warning",
        "Run BrandKit preflight/token resolution before using export preview for approval."
      )
    );
  }

  const placeholderAssets = placeholderAssetIdsForPage(scene, pageId);
  if (placeholderAssets.length > 0) {
    diagnostics.push(
      exportDiagnostic(
        "EDITOR_EXPORT_PARITY_UNRESOLVED_ASSETS",
        `Scene contains image nodes with missing or non-ready assets: ${placeholderAssets.join(", ")}.`,
        "warning",
        "Resolve fixture or runtime assets before using this preview for final approval."
      )
    );
  }

  return diagnostics;
}

function pageNodeIds(scene: Scene, pageId: PageId): NodeId[] {
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }

  const ids: NodeId[] = [];
  const seen = new Set<NodeId>();
  const visit = (nodeId: NodeId) => {
    if (seen.has(nodeId)) {
      return;
    }
    seen.add(nodeId);
    ids.push(nodeId);
    for (const childId of scene.nodes[nodeId]?.children ?? []) {
      visit(childId);
    }
  };

  for (const nodeId of page.children) {
    visit(nodeId);
  }
  return ids;
}

function nodeIdsFromSidecar(sidecarJson: string | null): Set<NodeId> | null {
  if (!sidecarJson) {
    return null;
  }

  try {
    const parsed = JSON.parse(sidecarJson) as unknown;
    if (!isRecord(parsed) || !Array.isArray(parsed.nodes)) {
      return null;
    }
    const ids = new Set<NodeId>();
    for (const node of parsed.nodes) {
      if (isRecord(node) && typeof node.node_id === "string") {
        ids.add(node.node_id);
      }
    }
    return ids;
  } catch {
    return null;
  }
}

function nodeIdsFromSvg(text: string): Set<NodeId> {
  const ids = new Set<NodeId>();
  for (const match of text.matchAll(/\bdata-lumen-node-id="([^"]+)"/g)) {
    ids.add(unescapeAttribute(match[1]));
  }
  return ids;
}

function unresolvedTokenReferencesForPage(scene: Scene, pageId: PageId): string[] {
  const tokens = new Set<string>();
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }

  for (const fill of page.background) {
    collectPaintTokens(fill.paint, tokens);
  }

  for (const nodeId of pageNodeIds(scene, pageId)) {
    const node = scene.nodes[nodeId];
    if (!node) {
      continue;
    }
    collectDimensionToken("size.width", node.size.width, tokens);
    collectDimensionToken("size.height", node.size.height, tokens);
    for (const fill of node.fills) {
      collectPaintTokens(fill.paint, tokens);
    }
    for (const stroke of node.strokes) {
      collectPaintTokens(stroke.paint, tokens);
      if (stroke.width_token) {
        tokens.add(`stroke.width:${stroke.width_token}`);
      }
    }
    if (node.corner.token) {
      tokens.add(`radius:${node.corner.token}`);
    }
    if (node.opacity_token) {
      tokens.add(`opacity:${node.opacity_token}`);
    }
    if (node.layout?.gap_token) {
      tokens.add(`layout.gap:${node.layout.gap_token}`);
    }
    if (node.layout?.padding_token) {
      tokens.add(`layout.padding:${node.layout.padding_token}`);
    }
    if (node.kind.kind === "text") {
      if (node.kind.style_token) {
        tokens.add(`type:${node.kind.style_token}`);
      }
      if (node.kind.line_height_token) {
        tokens.add(`line_height:${node.kind.line_height_token}`);
      }
      if (node.kind.letter_spacing_token) {
        tokens.add(`letter_spacing:${node.kind.letter_spacing_token}`);
      }
    }
  }

  return [...tokens].sort();
}

function collectDimensionToken(label: string, dimension: Scene["nodes"][NodeId]["size"]["width"], tokens: Set<string>): void {
  if (dimension.kind === "token") {
    tokens.add(`${label}:${dimension.value.token}`);
  }
}

function collectPaintTokens(paint: Scene["nodes"][NodeId]["fills"][number]["paint"], tokens: Set<string>): void {
  switch (paint.kind) {
    case "token":
      tokens.add(`paint:${paint.token}`);
      break;
    case "solid":
      if (paint.color.kind === "token") {
        tokens.add(`color:${paint.color.token}`);
      }
      break;
    case "linear_gradient":
    case "radial_gradient":
      for (const stop of paint.stops) {
        if (stop.color.kind === "token") {
          tokens.add(`color:${stop.color.token}`);
        }
      }
      break;
  }
}

function placeholderAssetIdsForPage(scene: Scene, pageId: PageId): string[] {
  const assetIds = new Set<string>();
  for (const nodeId of pageNodeIds(scene, pageId)) {
    const node = scene.nodes[nodeId];
    if (node?.kind.kind !== "image") {
      continue;
    }
    const asset = scene.assets[node.kind.asset_id];
    if (!asset || asset.status !== "ready") {
      assetIds.add(node.kind.asset_id);
    }
  }
  return [...assetIds].sort();
}

function svgExportSize(text: string | null): { width: number; height: number } | null {
  if (!text) {
    return null;
  }

  const width = svgLengthAttribute(text, "width");
  const height = svgLengthAttribute(text, "height");
  if (width !== null && height !== null) {
    return { width, height };
  }

  const viewBox = text.match(/\bviewBox="([^"]+)"/);
  if (viewBox) {
    const values = viewBox[1]
      .trim()
      .split(/[,\s]+/)
      .map((value) => Number(value));
    if (values.length === 4 && values.every(Number.isFinite)) {
      return {
        width: values[2],
        height: values[3]
      };
    }
  }

  return null;
}

function svgLengthAttribute(text: string, attribute: "width" | "height"): number | null {
  const match = text.match(new RegExp(`\\b${attribute}="([0-9.]+)(px|mm|in)?`));
  if (!match) {
    return null;
  }
  const value = Number(match[1]);
  if (!Number.isFinite(value)) {
    return null;
  }
  switch (match[2] ?? "px") {
    case "px":
      return value;
    case "mm":
      return value * (96 / 25.4);
    case "in":
      return value * 96;
    default:
      return null;
  }
}

function unavailable(code: string, message: string): ExportParityReport {
  return {
    status: "unavailable",
    canvas: null,
    export: null,
    diagnostics: [exportDiagnostic(code, message)]
  };
}

function exportDiagnostic(
  code: string,
  message: string,
  severity: Diagnostic["severity"] = "warning",
  hint: string | null = null
): Diagnostic {
  return {
    severity,
    phase: "export",
    code,
    message,
    subject: null,
    hint
  };
}

function diagnosticForNode(
  severity: Diagnostic["severity"],
  code: string,
  message: string,
  nodeId: NodeId,
  hint: string | null
): Diagnostic {
  return {
    severity,
    phase: "export",
    code,
    message,
    subject: {
      kind: "node",
      id: nodeId
    },
    hint
  };
}

function diagnosticForPage(
  severity: Diagnostic["severity"],
  code: string,
  message: string,
  pageId: PageId,
  hint: string | null
): Diagnostic {
  return {
    severity,
    phase: "export",
    code,
    message,
    subject: {
      kind: "page",
      id: pageId
    },
    hint
  };
}

function isVisualArtifact(artifact: EditorExportArtifact): boolean {
  return artifact.format === "svg" || artifact.format === "png" || artifact.format === "pdf";
}

function sameSize(left: { width: number; height: number }, right: { width: number; height: number }): boolean {
  return nearlyEqual(left.width, right.width) && nearlyEqual(left.height, right.height);
}

function sameAspectRatio(left: { width: number; height: number }, right: { width: number; height: number }): boolean {
  if (left.width <= 0 || left.height <= 0 || right.width <= 0 || right.height <= 0) {
    return false;
  }
  return Math.abs(left.width / left.height - right.width / right.height) < 0.001;
}

function nearlyEqual(left: number, right: number): boolean {
  return Math.abs(left - right) < 0.01;
}

function pageUnitScale(page: Page): number {
  switch (page.size.unit) {
    case "px":
      return 1;
    case "mm":
      return 96 / 25.4;
    case "in":
      return 96;
  }
}

function pdfPointToCanvasScale(page: Page): number {
  return page.size.unit === "px" ? 1 : 96 / 72;
}

function formatSize(size: { width: number; height: number }): string {
  return `${round(size.width)}x${round(size.height)}`;
}

function formatScale(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function round(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function svgContainsText(svg: string, content: string): boolean {
  const normalized = content.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return true;
  }
  if (svg.includes(escapeText(normalized))) {
    return true;
  }

  const significantWords = normalized.split(" ").filter((word) => word.length > 1);
  return significantWords.every((word) => svg.includes(escapeText(word)));
}

function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("\"", "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function unescapeAttribute(value: string): string {
  return value
    .replaceAll("&quot;", "\"")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function escapeText(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
