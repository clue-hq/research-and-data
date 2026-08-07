import type { Color, Diagnostic, DiagnosticSubject, Dimension, Node, PageId, Paint, Scene } from "./contracts";
import type { TextMeasurementStatus } from "./canvaskit/loadCanvasKit";
import { resolveTokenNumber, tokenPaintResolves, tokenTextStyleResolves } from "./renderAdapter";
import { flattenPageNodeIds } from "./sceneQueries";

/**
 * Loud, renderer-state (not scene) diagnostic: the on-canvas text-measurement
 * path is degraded. When CanvasKit or its fonts fail to load there is no font
 * provider, so the CanvasKit measure-then-inject pass never runs and the wasm
 * engine silently keeps its heuristic measurer — text can misfit or vanish
 * with no signal. Emitted whenever the live measurement status is `heuristic`;
 * returns `null` while measurement is exact (`skia`) or not yet resolved
 * (`pending`). Unlike the advisories below this reflects the live renderer, so
 * the editor feeds it the status observed in `loadCanvasKit`.
 */
export function heuristicMeasurementDiagnostic(
  status: TextMeasurementStatus
): Diagnostic | null {
  if (status !== "heuristic") {
    return null;
  }
  return {
    severity: "error",
    phase: "validation",
    code: "EDITOR_HEURISTIC_MEASUREMENT",
    message:
      "Text measurement degraded — canvas geometry is approximate (font engine unavailable). " +
      "The CanvasKit text engine or its fonts failed to load, so on-canvas text is laid out with a " +
      "heuristic estimate and may misfit or not appear as it will on export.",
    subject: { kind: "document" },
    hint: "Reload the editor; if it persists, rebuild CanvasKit/font assets (npm run build:canvaskit && npm run build:fonts) and hard-refresh. Use export preview as the fidelity baseline meanwhile."
  };
}

/** K1.5: a number token (radius/stroke-width/opacity/size-step) that the kit
 * map resolves is genuinely previewed — no fallback to report. */
function numberTokenUnresolved(token: string | null | undefined): token is string {
  return typeof token === "string" && token.length > 0 && resolveTokenNumber(token) === null;
}

export function editorRenderDiagnostics(scene: Scene, pageId: PageId | null): Diagnostic[] {
  if (!pageId || !scene.pages[pageId]) {
    return [];
  }

  const page = scene.pages[pageId];
  const diagnostics: Diagnostic[] = [];
  for (const fill of page.background) {
    collectPaintDiagnostics(fill.paint, diagnostics, {
      kind: "page",
      id: page.id
    }, "page background");
  }

  for (const nodeId of flattenPageNodeIds(scene, pageId)) {
    const node = scene.nodes[nodeId];
    if (!node) {
      continue;
    }
    collectNodeDiagnostics(scene, node, diagnostics);
  }

  return dedupeDiagnostics(diagnostics);
}

function collectNodeDiagnostics(scene: Scene, node: Node, diagnostics: Diagnostic[]): void {
  const subject: DiagnosticSubject = {
    kind: "node",
    id: node.id
  };

  if (!node.computed) {
    collectLayoutDiagnostics(node, diagnostics, subject);
    collectDimensionDiagnostics(node.size.width, diagnostics, subject, `${nodeDisplay(node)} width`);
    collectDimensionDiagnostics(node.size.height, diagnostics, subject, `${nodeDisplay(node)} height`);
  }
  for (const fill of node.fills) {
    collectPaintDiagnostics(fill.paint, diagnostics, subject, `${nodeDisplay(node)} fill`);
  }
  for (const stroke of node.strokes) {
    collectPaintDiagnostics(stroke.paint, diagnostics, subject, `${nodeDisplay(node)} stroke`);
    if (numberTokenUnresolved(stroke.width_token)) {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TOKEN_FALLBACK",
          `${nodeDisplay(node)} stroke width uses unresolved token ${stroke.width_token}; canvas preview cannot show the resolved width until preflight.`,
          subject,
          "Run preflight or select a Brand Kit so token-backed stroke widths resolve before approval."
        )
      );
    }
  }
  // A4 / D6 note: effect spread carries NO approximation diagnostic — the
  // CanvasKit pipeline renders outer-effect spread faithfully via
  // MakeDilate/MakeErode (gate-R upgrade; the D7 "no dilate in CanvasKit"
  // premise was wrong) and inner-shadow spread via the erode recipe.
  if (numberTokenUnresolved(node.corner.token)) {
    diagnostics.push(
      diagnostic(
        "EDITOR_RENDER_TOKEN_FALLBACK",
        `${nodeDisplay(node)} corner radius uses unresolved token ${node.corner.token}; canvas preview uses numeric fallback radii.`,
        subject,
        "Run preflight or select a Brand Kit so token-backed radius values resolve before approval."
      )
    );
  }
  if (numberTokenUnresolved(node.opacity_token)) {
    diagnostics.push(
      diagnostic(
        "EDITOR_RENDER_TOKEN_FALLBACK",
        `${nodeDisplay(node)} opacity uses unresolved token ${node.opacity_token}; canvas preview uses the current numeric opacity.`,
        subject,
        "Run preflight or select a Brand Kit so token-backed opacity resolves before approval."
      )
    );
  }
  if (node.kind.kind === "text") {
    // K1.5: a style token the kit map resolves is measured AND painted with
    // the kit's values — the preview is no longer "the current text fields".
    if (node.kind.style_token && !tokenTextStyleResolves(node.kind.style_token)) {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TOKEN_FALLBACK",
          `${nodeDisplay(node)} text style uses unresolved token ${node.kind.style_token}; canvas preview uses the current text fields.`,
          subject,
          "Run preflight or select a Brand Kit so typography tokens resolve before approval."
        )
      );
    }
    if (numberTokenUnresolved(node.kind.line_height_token)) {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TOKEN_FALLBACK",
          `${nodeDisplay(node)} line height uses unresolved token ${node.kind.line_height_token}; canvas preview uses the current numeric line height.`,
          subject,
          "Run preflight or select a Brand Kit so line-height tokens resolve before approval."
        )
      );
    }
    if (numberTokenUnresolved(node.kind.letter_spacing_token)) {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TOKEN_FALLBACK",
          `${nodeDisplay(node)} letter spacing uses unresolved token ${node.kind.letter_spacing_token}; canvas preview uses the current numeric letter spacing.`,
          subject,
          "Run preflight or select a Brand Kit so letter-spacing tokens resolve before approval."
        )
      );
    }
    if (node.kind.max_lines !== null && node.kind.max_lines !== undefined) {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TEXT_CLAMP_APPROXIMATION",
          `${nodeDisplay(node)} uses max_lines(${node.kind.max_lines}); canvas preview clamps with CanvasKit (SkParagraph) and may not match export text measurement exactly.`,
          subject,
          "Use preflight diagnostics and export preview as the fidelity baseline for final text fit."
        )
      );
    }
    if ((node.kind.direction ?? "ltr") !== "ltr") {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_TEXT_SHAPING_APPROXIMATION",
          `${nodeDisplay(node)} uses ${node.kind.direction ?? "auto"} text direction; canvas preview may not match final text shaping.`,
          subject,
          "Use export preview as the fidelity baseline for non-LTR text."
        )
      );
    }
  }
  if (node.kind.kind === "image") {
    // Ready image assets now render real pixels on the canvas (Step 2 / E0.1),
    // so no placeholder advisory is needed; only a non-ready/missing asset still
    // draws the placeholder box and warrants a warning.
    const asset = scene.assets[node.kind.asset_id];
    if (asset?.status !== "ready") {
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_IMAGE_ASSET_MISSING",
          `${nodeDisplay(node)} references missing or non-ready image asset ${node.kind.asset_id}.`,
          subject,
          "Generate or attach a ready image asset before final approval."
        )
      );
    }
  }
}

function collectLayoutDiagnostics(node: Node, diagnostics: Diagnostic[], subject: DiagnosticSubject): void {
  if (node.kind.kind !== "auto_layout" && !node.layout) {
    return;
  }
  diagnostics.push(
    diagnostic(
      "EDITOR_RENDER_LAYOUT_PREFLIGHT_REQUIRED",
      `${nodeDisplay(node)} has layout fields without computed geometry; canvas preview is using fallback geometry until preflight runs.`,
      subject,
      "Run preflight after changing auto-layout direction, wrap, gap, padding, alignment, child order, or custom page size."
    )
  );
}

function collectDimensionDiagnostics(
  dimension: Dimension,
  diagnostics: Diagnostic[],
  subject: DiagnosticSubject,
  label: string
): void {
  if (dimension.kind === "token") {
    diagnostics.push(
      diagnostic(
        "EDITOR_RENDER_TOKEN_FALLBACK",
        `${label} uses unresolved token ${dimension.value.token}; canvas preview may show zero size until preflight computes geometry.`,
        subject,
        "Run preflight so token-backed dimensions resolve into computed geometry."
      )
    );
  }
}

function collectPaintDiagnostics(
  paint: Paint,
  diagnostics: Diagnostic[],
  subject: DiagnosticSubject,
  label: string
): void {
  switch (paint.kind) {
    case "token":
      // K0.5 honesty: this fired unconditionally for every token paint — even
      // when the canvas painted the real kit value from the token map — so
      // the panel reported "fallback" on a correctly-rendered document. Only
      // an actual map miss is a fallback.
      if (!tokenPaintResolves(paint.token)) {
        diagnostics.push(
          diagnostic(
            "EDITOR_RENDER_TOKEN_FALLBACK",
            `${label} uses unresolved paint token ${paint.token}; canvas preview uses a local fallback color.`,
            subject,
            "Run preflight or select a Brand Kit so paint tokens resolve before approval."
          )
        );
      }
      break;
    case "solid":
      collectColorDiagnostics(paint.color, diagnostics, subject, label);
      break;
    case "linear_gradient":
    case "radial_gradient":
      diagnostics.push(
        diagnostic(
          "EDITOR_RENDER_GRADIENT_APPROXIMATION",
          `${label} is a ${paint.kind === "linear_gradient" ? "linear" : "radial"} gradient; canvas preview currently shows its first stop as a flat color.`,
          subject,
          "Use SVG export preview as the fidelity baseline for gradients."
        )
      );
      for (const stop of paint.stops) {
        collectColorDiagnostics(stop.color, diagnostics, subject, `${label} gradient stop`);
      }
      break;
  }
}

function collectColorDiagnostics(
  color: Color,
  diagnostics: Diagnostic[],
  subject: DiagnosticSubject,
  label: string
): void {
  if (color.kind === "token" && !tokenPaintResolves(color.token)) {
    diagnostics.push(
      diagnostic(
        "EDITOR_RENDER_TOKEN_FALLBACK",
        `${label} uses unresolved color token ${color.token}; canvas preview uses a local fallback color.`,
        subject,
        "Run preflight or select a Brand Kit so color tokens resolve before approval."
      )
    );
  }
}

function diagnostic(code: string, message: string, subject: DiagnosticSubject, hint: string): Diagnostic {
  return {
    severity: "warning",
    phase: "validation",
    code,
    message,
    subject,
    hint
  };
}

function dedupeDiagnostics(diagnostics: Diagnostic[]): Diagnostic[] {
  const seen = new Set<string>();
  return diagnostics.filter((diagnostic) => {
    const key = `${diagnostic.code}:${diagnostic.message}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function nodeDisplay(node: Node): string {
  return node.name ?? node.id;
}
