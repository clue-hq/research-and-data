/**
 * The fragment inspector card's data layer (clone-fidelity F3.2).
 *
 * Transport-free types plus the four reads/writes the card is built from, in the shape
 * `webDocuments.ts` already uses (an options bag carrying the api base url and an injectable
 * fetch, a parse that keeps only what it recognises, and an error reader that surfaces the
 * SERVER'S sentence rather than an HTTP status).
 *
 * That last one is load-bearing here rather than a nicety. Every refusal on this surface is
 * something a human has to act on — "there is no picture of this section yet, generate one",
 * "the harvested original is evidence, retire the repair instead" — and the API is careful to
 * carry a reason code and a sentence in `detail`. A layer that collapsed those into
 * "HTTP 409" would throw away the whole point of the mapping.
 */

import { lumenFetch } from "@/engine/editorConfig";

export interface FragmentCardOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

/** One editable spot on a cloned section, and what kind of control it takes. */
export interface FragmentSlotSpec {
  key: string;
  /** `text` → a field · `image` → the asset picker · `href` → a link field · `visibility` → a
   * toggle. An href rides the node's `text` tag, so the MANIFEST is the only thing that
   * remembers it is a link target. */
  kind: "text" | "image" | "href" | "visibility" | string;
  /** What the section's own markup says today — the field's placeholder. */
  fallback: string | boolean | null;
}

/**
 * One member of the whole lineage — **ruling R18-1**: every repair in a family must be
 * retire-reachable from the card of any family member selectable on the page.
 *
 * The parent/child list cannot deliver that. A repair is on no page unless somebody pinned it, so
 * "select the repair" is not a way to reach one, and a repair-of-a-repair is nobody's direct child
 * except its own parent's — so a grandchild leaf had a retire affordance nowhere at all, and the
 * contested-lineage dead end R17-2 exists to end stayed a dead end with the button built.
 *
 * Membership and the root are the backend resolver's answers (ruling R-X1), never re-derived here.
 */
export interface FragmentFamilyEntry extends FragmentLineageEntry {
  derivedFrom: string | null;
  isRoot: boolean;
  retirement: FragmentVerdict;
}

/** One member of a repair lineage, as the card lists it. */
export interface FragmentLineageEntry {
  fragmentId: string;
  label: string | null;
  status: string;
  degraded: boolean;
  degradedReason: string | null;
  derivedReason: string | null;
  previewPath: string | null;
  createdAt: string | null;
}

export interface FragmentVerdict {
  allowed: boolean;
  reason: string | null;
  message: string | null;
}

export interface FragmentCard {
  fragmentId: string;
  label: string | null;
  sectionRole: string | null;
  status: string;
  pageUrl: string | null;
  /** A SORT KEY — where the band sat in DOCUMENT order. The visible and hidden collections are
   * numbered from one counter, so this is NOT an offset into the visible list (F3.0 M3). */
  sectionIndex: number | null;
  previewPath: string | null;
  /** How the picture was made: a crop of the source-site screenshot, or an isolation render of
   * the artifact's own bytes (P-7). Not the same evidence, so not the same word. */
  previewBasis: string | null;
  slots: FragmentSlotSpec[];
  degraded: boolean;
  degradedReason: string | null;
  degradedNote: string | null;
  derivedFrom: string | null;
  derivedReason: string | null;
  repairs: FragmentLineageEntry[];
  repairsWhat: FragmentLineageEntry | null;
  supersededBy: string | null;
  lineageAmbiguous: string[];
  lineageRoot: string | null;
  /** The whole family, from any member's card (R18-1). */
  family: FragmentFamilyEntry[];
  hiddenOnSource: { hidden: boolean; evidence: string[] } | null;
  activation: FragmentVerdict;
  retirement: FragmentVerdict;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readVerdict(value: unknown, allowedKey: string): FragmentVerdict {
  const record = (value ?? {}) as Record<string, unknown>;
  return {
    allowed: record[allowedKey] === true,
    reason: text(record.reason),
    message: text(record.message)
  };
}

function readFamilyEntry(value: unknown): FragmentFamilyEntry | null {
  const base = readLineageEntry(value);
  if (!base) {
    return null;
  }
  const record = (value ?? {}) as Record<string, unknown>;
  return {
    ...base,
    derivedFrom: text(record.derived_from),
    isRoot: record.is_root === true,
    retirement: readVerdict(record.retirement, "retirable")
  };
}

function readLineageEntry(value: unknown): FragmentLineageEntry | null {
  const record = (value ?? {}) as Record<string, unknown>;
  const fragmentId = text(record.fragment_id);
  if (!fragmentId) {
    return null;
  }
  return {
    fragmentId,
    label: text(record.label),
    status: text(record.status) ?? "draft",
    degraded: record.degraded === true,
    degradedReason: text(record.degraded_reason),
    derivedReason: text(record.derived_reason),
    previewPath: text(record.preview_path),
    createdAt: text(record.created_at)
  };
}

export function readFragmentCard(value: unknown): FragmentCard | null {
  const record = (value ?? {}) as Record<string, unknown>;
  const fragmentId = text(record.fragment_id);
  if (!fragmentId) {
    return null;
  }
  const preview = (record.preview ?? {}) as Record<string, unknown>;
  const hidden = record.hidden_on_source as Record<string, unknown> | null | undefined;
  return {
    fragmentId,
    label: text(record.label),
    sectionRole: text(record.section_role),
    status: text(record.status) ?? "draft",
    pageUrl: text(record.page_url),
    sectionIndex:
      typeof record.section_index === "number" ? record.section_index : null,
    previewPath: text(preview.path),
    previewBasis: text(preview.basis),
    slots: (Array.isArray(record.slots) ? record.slots : [])
      .map((entry) => {
        const slot = (entry ?? {}) as Record<string, unknown>;
        const key = text(slot.key);
        if (!key) {
          return null;
        }
        const fallback = slot.fallback;
        return {
          key,
          kind: text(slot.kind) ?? "text",
          fallback:
            typeof fallback === "string" || typeof fallback === "boolean" ? fallback : null
        } satisfies FragmentSlotSpec;
      })
      .filter((slot): slot is FragmentSlotSpec => slot !== null),
    degraded: record.degraded === true,
    degradedReason: text(record.degraded_reason),
    degradedNote: text(record.degraded_note),
    derivedFrom: text(record.derived_from),
    derivedReason: text(record.derived_reason),
    repairs: (Array.isArray(record.repairs) ? record.repairs : [])
      .map(readLineageEntry)
      .filter((entry): entry is FragmentLineageEntry => entry !== null),
    repairsWhat: readLineageEntry(record.repairs_what),
    supersededBy: text(record.superseded_by),
    lineageRoot: text(record.lineage_root),
    family: (Array.isArray(record.family) ? record.family : [])
      .map(readFamilyEntry)
      .filter((entry): entry is FragmentFamilyEntry => entry !== null),
    lineageAmbiguous: (Array.isArray(record.lineage_ambiguous)
      ? record.lineage_ambiguous
      : []
    ).filter((entry): entry is string => typeof entry === "string"),
    hiddenOnSource:
      hidden && typeof hidden === "object"
        ? {
            hidden: hidden.hidden === true,
            evidence: (Array.isArray(hidden.evidence) ? hidden.evidence : []).filter(
              (entry): entry is string => typeof entry === "string"
            )
          }
        : null,
    activation: readVerdict(record.activation, "activatable"),
    retirement: readVerdict(record.retirement, "retirable")
  };
}

/** The server's own sentence, or the fallback. See the module docstring. */
async function refusalMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.clone().json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) {
        return message;
      }
    }
  } catch {
    /* not JSON */
  }
  return fallback;
}

async function cardCall(
  { apiBaseUrl, fetchImpl = lumenFetch }: FragmentCardOptions,
  path: string,
  init: RequestInit | undefined,
  fallback: string
): Promise<FragmentCard> {
  const response = await fetchImpl(new URL(path, apiBaseUrl), init);
  if (!response.ok) {
    throw new Error(await refusalMessage(response, `${fallback} (HTTP ${response.status}).`));
  }
  const card = readFragmentCard(await response.json());
  if (!card) {
    throw new Error("The cloned section's card came back in a shape this build cannot read.");
  }
  return card;
}

export function fetchFragmentCard(
  options: FragmentCardOptions,
  fragmentId: string
): Promise<FragmentCard> {
  return cardCall(
    options,
    `/web/fragments/${encodeURIComponent(fragmentId)}`,
    undefined,
    "The cloned section could not be loaded"
  );
}

/** Photograph the section's own bytes in isolation, and keep the picture (P-7). */
export function generateFragmentPreview(
  options: FragmentCardOptions,
  fragmentId: string
): Promise<FragmentCard> {
  return cardCall(
    options,
    `/web/fragments/${encodeURIComponent(fragmentId)}/preview`,
    { method: "POST" },
    "The isolation render failed"
  );
}

/** Wake a section the source site hides (D-F8). Refused, with the reason, until it has a
 * preview — which is the whole point of the affordance beside this one. */
export function activateFragment(
  options: FragmentCardOptions,
  fragmentId: string
): Promise<FragmentCard> {
  return cardCall(
    options,
    `/web/fragments/${encodeURIComponent(fragmentId)}/activate`,
    { method: "POST" },
    "The section could not be activated"
  );
}

/** Retire a REPAIR (ruling R17-2). Never the harvested original (R17-3) — the server refuses
 * that, and the card's own `retirement` verdict says so before anybody presses anything. */
export function retireFragment(
  options: FragmentCardOptions,
  fragmentId: string
): Promise<FragmentCard> {
  return cardCall(
    options,
    `/web/fragments/${encodeURIComponent(fragmentId)}/retire`,
    { method: "POST" },
    "The repair could not be retired"
  );
}

/** Every section the source site HIDES. A dormant section is on no page, so nothing can select
 * one — and D-F8 makes the inspector the one place a human sees and activates them. */
export async function fetchDormantFragments({
  apiBaseUrl,
  fetchImpl = lumenFetch
}: FragmentCardOptions): Promise<FragmentCard[]> {
  const response = await fetchImpl(new URL("/web/fragments/dormant", apiBaseUrl));
  if (!response.ok) {
    throw new Error(
      await refusalMessage(
        response,
        `Hidden sections could not be loaded (HTTP ${response.status}).`
      )
    );
  }
  const payload = (await response.json()) as { sections?: unknown };
  return (Array.isArray(payload.sections) ? payload.sections : [])
    .map(readFragmentCard)
    .filter((card): card is FragmentCard => card !== null);
}
