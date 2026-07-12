import type { ExportProfile, Page } from "./contracts";
import type { PrintReadyReport, PrintReadyStatus } from "./exportRunner";

/**
 * Print-readiness view + discovery policy (print workstream W3). Kept out of
 * the export panel component per the frontend-practices rule that workflow
 * policy lives in hooks/helpers, not visual components.
 */

export interface PrintReadyPill {
  label: string;
  tone: "success" | "warning" | "error";
}

const STATUS_PILL: Record<PrintReadyStatus, PrintReadyPill> = {
  pass: { label: "Print-ready", tone: "success" },
  warn: { label: "Print-ready with warnings", tone: "warning" },
  fail: { label: "Not print-ready", tone: "error" }
};

export function printReadyPill(report: PrintReadyReport): PrintReadyPill {
  return STATUS_PILL[report.status];
}

/** The rules worth surfacing under the pill: everything that is not a clean
 * pass, so a green report collapses to just the pill. */
export function printReadyNotableRules(report: PrintReadyReport) {
  return report.rules.filter((rule) => rule.status !== "pass");
}

/**
 * Whether to nudge the user toward enabling "Print & bleed". Fires only when
 * the feature is OFF and a print-intent PDF export ran against a page that has
 * no bleed — the case where enabling the feature would materially help. The
 * hint is advisory and dismissible; it never blocks the export.
 */
export function shouldShowPrintNudge({
  printFeatureEnabled,
  profile,
  activePage,
  hasExportResult
}: {
  printFeatureEnabled: boolean;
  profile: ExportProfile | null;
  activePage: Page | null;
  hasExportResult: boolean;
}): boolean {
  if (printFeatureEnabled || !hasExportResult || !profile || !activePage) {
    return false;
  }
  return profile.format === "pdf" && profile.pdf_intent === "print" && activePage.bleed === null;
}

/** Server rule id declared when bleed/crop marks are requested on an imposed
 * (booklet) sheet: imposition wins and the marks are skipped on the imposed
 * sheet. Surfaced as an advisory note beside the bleed/marks control, never a
 * block — the user's bleed/marks choice is preserved for non-imposed output. */
export const IMPOSED_MARKS_SKIPPED_RULE = "LUME0430";

/** Whether the profile requests booklet imposition. The single source of truth
 * for the booklet policy so the export panel component stays presentation-only. */
export function hasBookletImposition(profile: ExportProfile | null): boolean {
  return profile?.imposition === "booklet";
}
