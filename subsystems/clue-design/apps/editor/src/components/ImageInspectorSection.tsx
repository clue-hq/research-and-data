"use client";

import { useState } from "react";
import { ImageIcon, RefreshCw, Sparkles } from "lucide-react";

import type {
  AssetPlacement,
  AssetRecord,
  ImageFitMode,
  Node,
  Operation
} from "@/engine/contracts";
import { nodePatch, set } from "@/engine/operations";
import { buildNodePlacementOperations, generateAsset } from "@/engine/assetLibrary";

/**
 * Step 5 (E0.2–E0.5): the image node's controls — Fit, focal point, alt text, and
 * generate / regenerate — plus pending/ready/failed status. Placement edits emit an
 * `update_node` `asset_placement` patch (the same op every other inspector field
 * uses); generate posts to `/assets/generate` and then places the returned asset into
 * the SAME node, carrying the existing placement forward (fit/focal preserved).
 *
 * The draggable focal-point dot on the canvas is a separate overlay; these number
 * fields are the keyboard-accessible equivalent and the test surface.
 */

const FIT_MODES: ImageFitMode[] = ["cover", "contain", "crop"];
const IMAGE_LONG_EDGE = 1536;

export interface ImageInspectorSectionProps {
  node: Node;
  asset: AssetRecord | null;
  apiBaseUrl: string;
  disabled?: boolean;
  onOperations: (operations: Operation[]) => void;
}

export function ImageInspectorSection({
  node,
  asset,
  apiBaseUrl,
  disabled = false,
  onOperations
}: ImageInspectorSectionProps) {
  const placement = node.asset_placement ?? {};
  const fit: ImageFitMode = placement.fit ?? "cover";
  const focalX = placement.focal_point?.x ?? 0.5;
  const focalY = placement.focal_point?.y ?? 0.5;
  const altText = placement.alt_text ?? (node.kind.kind === "image" ? node.kind.alt ?? "" : "");

  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const emitPlacement = (next: AssetPlacement) => {
    onOperations([
      { kind: "update_node", node_id: node.id, patch: nodePatch({ asset_placement: set(next) }) }
    ]);
  };

  const setFit = (value: ImageFitMode) =>
    emitPlacement({ ...placement, fit: value });
  const setFocal = (axis: "x" | "y", value: number) => {
    const clamped = Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0.5));
    const focal = { x: focalX, y: focalY, [axis]: clamped };
    emitPlacement({ ...placement, focal_point: focal });
  };
  const setAlt = (value: string) =>
    emitPlacement({ ...placement, alt_text: value });

  const runGenerate = async () => {
    const trimmed = prompt.trim();
    if (!trimmed) {
      setError("Enter a prompt to generate an image.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const resolution = frameResolution(node);
      const result = await generateAsset(apiBaseUrl, {
        prompt: trimmed,
        width: resolution?.width,
        height: resolution?.height,
        label: trimmed.slice(0, 60)
      });
      // Place into the SAME node, preserving the existing placement (fit/focal/alt).
      onOperations(buildNodePlacementOperations(result.asset, node.id, currentPlacement(placement)));
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : String(generateError));
    } finally {
      setGenerating(false);
    }
  };

  const hasImage = node.kind.kind === "image" && Boolean(node.kind.asset_id);
  const status = generating
    ? "pending"
    : error
      ? "failed"
      : asset?.status ?? (hasImage ? "ready" : "empty");

  return (
    <section className="inspector-section" data-testid="image-inspector">
      <div className="section-heading">
        <ImageIcon aria-hidden size={15} />
        Image
      </div>

      <div className="field-row">
        <label className="field">
          <span>Fit</span>
          <select
            aria-label="Image fit"
            value={fit}
            disabled={disabled}
            onChange={(event) => setFit(event.target.value as ImageFitMode)}
          >
            {FIT_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="field-row">
        <FocalField label="Focal X" value={focalX} disabled={disabled} onCommit={(v) => setFocal("x", v)} />
        <FocalField label="Focal Y" value={focalY} disabled={disabled} onCommit={(v) => setFocal("y", v)} />
      </div>

      <label className="field">
        <span>Alt text</span>
        <input
          type="text"
          aria-label="Image alt text"
          value={altText}
          placeholder="Describe the image"
          disabled={disabled}
          onChange={(event) => setAlt(event.target.value)}
        />
      </label>

      <div className="field">
        <span>{hasImage ? "Regenerate" : "Generate image"}</span>
        <textarea
          aria-label="Image prompt"
          rows={2}
          value={prompt}
          placeholder="e.g. editorial photo of a calm clinic reception, soft light, no text"
          disabled={disabled || generating}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </div>
      <div className="field-row">
        <button
          type="button"
          data-testid="image-generate"
          disabled={disabled || generating || !prompt.trim()}
          onClick={() => void runGenerate()}
        >
          {hasImage ? <RefreshCw aria-hidden size={14} /> : <Sparkles aria-hidden size={14} />}
          {generating ? "Generating…" : hasImage ? "Regenerate" : "Generate"}
        </button>
      </div>

      <p className="muted" data-testid="image-status" data-status={status}>
        {generating
          ? "Generating image…"
          : error
            ? `Generation failed: ${error}`
            : hasImage
              ? `Asset ${node.kind.kind === "image" ? node.kind.asset_id : ""} · ${asset?.status ?? "ready"}`
              : "No image yet — generate or place one from the asset library."}
      </p>
    </section>
  );
}

function FocalField({
  label,
  value,
  disabled,
  onCommit
}: {
  label: string;
  value: number;
  disabled?: boolean;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        aria-label={label}
        value={Number.isFinite(value) ? value : 0.5}
        min={0}
        max={1}
        step={0.05}
        disabled={disabled}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(next);
          }
        }}
      />
    </label>
  );
}

/** The placement to carry forward on (re)generate: default cover + centered focal. */
function currentPlacement(placement: AssetPlacement): AssetPlacement {
  return {
    fit: placement.fit ?? "cover",
    focal_point: placement.focal_point ?? { x: 0.5, y: 0.5 },
    preserve_transparency: placement.preserve_transparency ?? undefined,
    alt_text: placement.alt_text ?? undefined
  };
}

/** A role-appropriate generation resolution at the frame's aspect (long edge 1536). */
function frameResolution(node: Node): { width: number; height: number } | undefined {
  const bounds = node.computed?.layout_bounds;
  let width = bounds?.width;
  let height = bounds?.height;
  if (!width || !height) {
    if (node.size.width.kind === "fixed") {
      width = node.size.width.value;
    }
    if (node.size.height.kind === "fixed") {
      height = node.size.height.value;
    }
  }
  if (!width || !height || width <= 0 || height <= 0) {
    return undefined;
  }
  return width >= height
    ? { width: IMAGE_LONG_EDGE, height: Math.max(1, Math.round((IMAGE_LONG_EDGE * height) / width)) }
    : { width: Math.max(1, Math.round((IMAGE_LONG_EDGE * width) / height)), height: IMAGE_LONG_EDGE };
}
