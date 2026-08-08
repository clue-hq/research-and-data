import type { JsonValue, ResearchStatus } from "./vocabulary";

/**
 * Display formatting for the accounts flow.
 *
 * D-5: display strings left the wire. The backend sends semantic values —
 * enums, numbers, ISO-8601 timestamps, opaque tokens — and every label,
 * band, and date rendering is decided here.
 *
 * Formatting is deterministic and UTC-pinned so a server-rendered string and
 * its client hydration cannot disagree. Nothing here invents a value: a
 * missing input formats to `null`, and the caller renders an honest absence.
 */

const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
  year: "numeric",
});

/** `2026-08-01T12:00:00Z` → `1 Aug 2026`. Returns `null` for absent or unparseable input. */
export function formatIsoDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  return dateFormatter.format(parsed);
}

/** Sentence-cases a snake_case / kebab-case backend token: `needs_review` → `Needs review`. */
export function formatToken(token: string): string {
  const words = token.replace(/[_-]+/g, " ").trim();
  if (!words) return token;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Turns a field-registry key into a human label without enumerating anything:
 * `core.employee_count` → `Employee count`, `dental.chair_count` → `Chair count`.
 *
 * This is the generic prettifier that lets an industry pack's custom fields
 * render dynamically (FI-1 D-7) — a new pack field needs no frontend change.
 */
export function formatFieldKeyLabel(fieldKey: string): string {
  const segments = fieldKey.split(".");
  return formatToken(segments[segments.length - 1] ?? fieldKey);
}

/** The namespace a field key lives in, for a subtle provenance affordance. `null` when unqualified. */
export function fieldKeyNamespace(fieldKey: string): string | null {
  const segments = fieldKey.split(".");
  return segments.length > 1 ? segments.slice(0, -1).join(".") : null;
}

const researchStatusLabels: Record<ResearchStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  needs_review: "Needs review",
  completed: "Completed",
  suspended: "Suspended",
  not_launchable: "Not launchable",
};

export function formatResearchStatus(status: ResearchStatus): string {
  return researchStatusLabels[status] ?? formatToken(status);
}

/**
 * Revenue bands.
 *
 * The wire token is whatever the field's writer produced, so this is a lookup
 * with a fallback, never an exhaustive map. An unknown token renders
 * sentence-cased rather than as a wrong label or a blank cell.
 */
const revenueBandLabels: Record<string, string> = {
  under_1m: "Under $1M",
  "1m_10m": "$1M – $10M",
  "10m_50m": "$10M – $50M",
  "50m_100m": "$50M – $100M",
  "100m_500m": "$100M – $500M",
  "500m_1b": "$500M – $1B",
  "1b_plus": "$1B+",
};

export function formatRevenueBand(band: string | null): string | null {
  if (!band) return null;
  return revenueBandLabels[band] ?? formatToken(band);
}

const employeeCountFormatter = new Intl.NumberFormat("en-US");

export function formatEmployeeCount(count: number | null): string | null {
  return count === null ? null : employeeCountFormatter.format(count);
}

/**
 * A unit-interval score (0–1) rendered on the 0–100 scale the accounts table
 * has always shown. Not a percentage of anything — it is a normalized score.
 */
export function formatScore(score: number | null): string | null {
  return score === null ? null : String(Math.round(score * 100));
}

export function formatConfidence(confidence: number | null): string | null {
  return confidence === null ? null : `${Math.round(confidence * 100)}%`;
}

/**
 * Renders an opaque claim payload as a single line when it is scalar.
 *
 * Objects and arrays return `null` so the caller can lay them out structurally
 * instead of dumping JSON at the user.
 */
export function formatJsonScalar(value: JsonValue): string | null {
  if (value === null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number") return employeeCountFormatter.format(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return null;
}

/** `{ persona: "economic_buyer" }` → `[["Persona", "economic_buyer"], …]`, keys prettified. */
export function jsonEntries(value: JsonValue): Array<[string, JsonValue]> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }
  return Object.entries(value);
}
