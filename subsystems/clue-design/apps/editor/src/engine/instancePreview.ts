import type { Scene, Slot } from "./contracts";

/**
 * Worst-case instance preview (Phase G slice G9).
 *
 * The editor builds a worst-case binding set from the template's own slot
 * contracts (validation worst-case fixtures, repeater max_items, the QR
 * chain) and asks the API for a stateless derived-instance render. The
 * result is read-only: instances are derived artifacts, never editable
 * documents.
 */

export interface WorstCaseBindingSet {
  schema_version: number;
  binding_set_id: string;
  template_revision_id: string;
  values: Record<string, unknown>;
  links: Record<string, { url: string }>;
  generated: Record<
    string,
    { provider: string; input: Record<string, unknown>; bind_to_slot: string }
  >;
}

export interface InstancePreviewResult {
  status: "ok" | "failed";
  fit_report: {
    status?: string;
    slots?: Array<{
      slot_key: string;
      verdict: { kind: string; policy?: string; reason?: string; adjusted_font_size?: number };
      beyond_worst_case?: boolean;
    }>;
  };
  diagnostics: Array<{ severity: string; code: string; message: string }>;
  artifact: { format: string; content?: string; content_base64?: string } | null;
}

const PREVIEW_LANDING_URL = "https://go.example.com/preview/worst-case";

function worstCaseText(slot: Slot): string | null {
  if (slot.validation.worst_case) {
    return slot.validation.worst_case;
  }
  const samples = slot.validation.samples ?? [];
  if (samples.length > 0) {
    return samples.reduce((longest, sample) =>
      sample.length > longest.length ? sample : longest
    );
  }
  return slot.placeholder ?? null;
}

function boundAssetId(scene: Scene, slot: Slot): string | null {
  for (const nodeId of slot.bound_nodes) {
    const node = scene.nodes[nodeId];
    if (!node) {
      continue;
    }
    if (node.source_asset_id) {
      return node.source_asset_id;
    }
    if (node.kind.kind === "image") {
      return node.kind.asset_id;
    }
  }
  return null;
}

/**
 * Build the worst-case binding set: every text slot at its declared
 * worst-case fixture, repeaters at max_items, image slots reusing the
 * template's own placeholder assets, and UrlQr slots chained through a
 * preview landing link.
 */
export function buildWorstCaseBindingSet(scene: Scene): WorstCaseBindingSet {
  const status = scene.meta.status as { kind: string; template_revision_id?: string };
  const revisionId =
    status.kind === "finalized" && status.template_revision_id
      ? status.template_revision_id
      : "tmpl_preview";

  const slots = Object.values(scene.slots);
  const itemSlotKeys = new Set(
    slots
      .filter((slot) => slot.repeater !== null)
      .map((slot) => slot.repeater!.item_slot_key)
  );

  const values: Record<string, unknown> = {};
  const links: WorstCaseBindingSet["links"] = {};
  const generated: WorstCaseBindingSet["generated"] = {};

  for (const slot of slots) {
    if (itemSlotKeys.has(slot.key)) {
      continue; // item slots bind through their repeater list
    }
    switch (slot.content_type) {
      case "text_short":
      case "text_long":
      case "rich_text_limited":
      case "number_stat":
      case "date": {
        const text = worstCaseText(slot);
        if (text !== null) {
          values[slot.key] = { kind: "text", value: text };
        }
        break;
      }
      case "image":
      case "logo": {
        const assetId = boundAssetId(scene, slot);
        if (assetId) {
          values[slot.key] = { kind: "asset", asset_id: assetId };
        }
        break;
      }
      case "url_qr": {
        links.landing_page = { url: PREVIEW_LANDING_URL };
        generated[`qr_${slot.key.replace(/[^A-Za-z0-9_-]/g, "_")}`] = {
          provider: "qr",
          input: { url_from: "links.landing_page.url", ec_level: "h" },
          bind_to_slot: slot.key,
        };
        break;
      }
      case "list":
      case "repeater_group": {
        const repeater = slot.repeater;
        const itemSlot = repeater
          ? slots.find((candidate) => candidate.key === repeater.item_slot_key)
          : undefined;
        const itemText =
          (itemSlot ? worstCaseText(itemSlot) : null) ?? slot.placeholder ?? "Item";
        const maxItems =
          repeater?.max_items ?? slot.cardinality.max_items ?? slot.cardinality.min_items ?? 1;
        values[slot.key] = {
          kind: "list",
          items: Array.from({ length: Math.max(1, maxItems) }, () => ({
            kind: "text",
            value: itemText,
          })),
        };
        break;
      }
      default:
        break;
    }
  }

  return {
    schema_version: 1,
    binding_set_id: "bind_worst_case_preview",
    template_revision_id: revisionId,
    values,
    links,
    generated,
  };
}

export async function fetchInstancePreview(
  apiBaseUrl: string,
  scene: Scene,
  bindingSet: WorstCaseBindingSet,
  format: "svg" | "png" = "svg"
): Promise<InstancePreviewResult> {
  const response = await fetch(new URL("/instances/preview", apiBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ scene, binding_set: bindingSet, format }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(
      `Instance preview failed with status ${response.status}: ${JSON.stringify(
        (detail as { detail?: unknown }).detail ?? detail
      )}`
    );
  }
  return (await response.json()) as InstancePreviewResult;
}
