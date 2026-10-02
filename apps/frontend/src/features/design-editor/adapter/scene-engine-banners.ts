import type { SceneEngineStatus } from "../hooks/use-scene-document";
import type { Diagnostic } from "../engine/scene/contracts";
import type { Derivation } from "../engine/scene/wasmEngine";

/**
 * Gate G-D (founder, 2026-08-21): what the two engine-forced failure states
 * SAY.
 *
 * The ruling was "as is from the MVP editor, no separate banner" — so this file
 * is not authored copy. Every string below is lifted verbatim from the design
 * subsystem's own banners
 * (`subsystems/clue-design/apps/editor/src/components/EditorChrome.tsx:200-288`,
 * `EngineDisabledBanner` + `HeuristicMeasurementBanner`), and the read-only
 * state deliberately gets the SAME treatment as the degraded-text one rather
 * than a canvas-specific variant (the second half of the same ruling).
 *
 * Two deliberate deviations, both disclosed at the founder preview:
 *
 *  1. **The command chip names THIS repo's command.** The source banners tell a
 *     design-subsystem developer to run `npm run build:wasm` /
 *     `npm run build:canvaskit`, which do not exist in `apps/frontend`. The
 *     platform's real remedies are the ones our own vendor script already
 *     prints (`scripts/copy-design-vendor.mjs:96`), so those are what the chip
 *     says. Copy that instructs is worth nothing if the instruction is false.
 *  2. **Multiple diagnostics share one disclosure.** The platform presents them
 *     with Clue product tokens and a dismiss control (founder, 2026-09-15),
 *     preserving the diagnostic copy while leaving the artboard unobstructed.
 *
 * The third state in the gate — the CAS conflict — needs nothing here: it stays
 * the web lane's existing inspector note ("Document moved on — reloaded."),
 * which is already ratified (D10) and already implemented.
 *
 * The copy lives in this pure module, not in the component, so the wording is
 * asserted by a plain unit test against the upstream source.
 */

/** The engine's own text-measurement store value (`loadCanvasKit`). */
export type SceneTextMeasurementStatus = string;

export interface SceneEngineBanner {
  /** Stable key + test hook; mirrors the source's `data-testid` names. */
  kind: "engine-disabled" | "heuristic-measurement" | "font-fallback" | "render-context";
  /** Controls the status accent and whether the explanation starts expanded. */
  severity: "warning" | "error";
  /** The bold first line. */
  title: string;
  /** The sentence under it. */
  body: string;
  /** Recovery guidance, with a separate machine detail when available. */
  command: string;
  detail: string | null;
}

/** Reason-specific copy for the server-only-mode canvas banner (verbatim). */
function engineDisabledCopy(reason: SceneEngineStatus["reason"]): {
  headline: string;
  fix: string;
} {
  switch (reason) {
    case "version_mismatch":
      return {
        headline: "The in-browser engine is a different build than the API.",
        fix: "Rebuild it to match, then hard-refresh (⌘⇧R):",
      };
    case "handshake_failed":
      return {
        headline: "Couldn’t verify the in-browser engine against the API.",
        fix: "Start the API, rebuild the engine, then hard-refresh (⌘⇧R):",
      };
    case "load_failed":
    default:
      return {
        headline: "The in-browser engine failed to load.",
        fix: "Build it, then hard-refresh (⌘⇧R):",
      };
  }
}

/** The platform's own wasm remedy — the string `copy-design-vendor.mjs` prints. */
const REBUILD_ENGINE_COMMAND =
  "npm --prefix ../../subsystems/clue-design/apps/editor run build:wasm";

/** The platform's own canvaskit/font remedy: the vendor copy produces both. */
const REVENDOR_ASSETS_COMMAND = "node scripts/copy-design-vendor.mjs";

/**
 * Every banner the current engine state earns, in paint order.
 *
 * Empty is the overwhelmingly common answer (a live engine measuring with
 * Skia), and empty means NO element at all — never an empty container holding
 * space above the artboard.
 */
export function sceneEngineBanners(
  engineStatus: SceneEngineStatus,
  measurementStatus: SceneTextMeasurementStatus,
  fontDiagnostics: Diagnostic[] = [],
  derivation?: Pick<Derivation, "status" | "diagnostics">,
): SceneEngineBanner[] {
  const banners: SceneEngineBanner[] = [];

  if (engineStatus.engineDisabled) {
    const copy = engineDisabledCopy(engineStatus.reason);
    banners.push({
      kind: "engine-disabled",
      severity: "error",
      title: "Canvas editing is disabled",
      body: `${copy.headline} You can’t select or edit anything on the canvas until the in-browser engine is running. ${copy.fix}`,
      command: REBUILD_ENGINE_COMMAND,
      detail: engineStatus.detail,
    });
  }

  if (derivation && (derivation.status !== "ready" || derivation.diagnostics.length > 0)) {
    const first = derivation.diagnostics.find(diagnostic => diagnostic.severity === "error")
      ?? derivation.diagnostics[0];
    const blocked = derivation.status !== "ready";
    const additional = Math.max(0, derivation.diagnostics.length - 1);
    banners.push({
      kind: "render-context",
      severity: blocked || first?.severity === "error" ? "error" : "warning",
      title: blocked ? "Canvas rendering unavailable" : "Canvas rendering diagnostics",
      body: `${first?.message ?? "Waiting for a valid render context."}${additional > 0
        ? ` ${additional} additional render diagnostic${additional === 1 ? "" : "s"} reported.` : ""}`,
      command: blocked ? "Resolve the render context and reload" : "Review rendering diagnostics",
      detail: first?.hint ?? null,
    });
    // There is no painted canvas while the derivation is blocked: neither
    // approximate geometry nor an Inter fallback is being displayed.
    if (blocked) return banners;
  }

  // The dangerous one: the ad still renders, so nothing LOOKS broken while the
  // geometry it renders is approximate.
  if (measurementStatus === "heuristic") {
    banners.push({
      kind: "heuristic-measurement",
      severity: "warning",
      title: "Text measurement degraded",
      body: "Canvas geometry is approximate (font engine unavailable). On-canvas text is laid out with a heuristic estimate and may misfit or not appear as it will on export. Reload the editor; if it persists, rebuild the CanvasKit and font assets, then hard-refresh (⌘⇧R).",
      command: REVENDOR_ASSETS_COMMAND,
      detail: null,
    });
  }

  if (measurementStatus === "unsettled") {
    banners.push({
      kind: "heuristic-measurement",
      severity: "warning",
      title: "Text layout needs verification",
      body: "The editor could not confirm every text measurement. Some text may clip or differ from the export. Reload the editor and check the affected text before exporting.",
      command: "Reload editor",
      detail: null,
    });
  }

  if (fontDiagnostics.length > 0) {
    // One banner, led by the worst diagnostic: the array concatenates kit
    // before library, so without the severity sort an error-severity library
    // failure would hide behind a kit warning as "N additional diagnostics".
    const first =
      fontDiagnostics.find((diagnostic) => diagnostic.severity === "error") ??
      fontDiagnostics[0];
    const additional = fontDiagnostics.length - 1;
    banners.push({
      kind: "font-fallback",
      severity: first.severity === "error" ? "error" : "warning",
      title:
        first.code === "EDITOR_PINNED_BRAND_KIT_UNAVAILABLE"
          ? "Pinned Brand Kit unavailable"
          : "Brand font unavailable",
      body: `${first.message}${
        additional > 0
          ? ` ${additional} additional font diagnostic${additional === 1 ? "" : "s"} reported.`
          : ""
      }`,
      command: "Deterministic fallback: Inter",
      detail: first.hint ?? null,
    });
  }

  return banners;
}
