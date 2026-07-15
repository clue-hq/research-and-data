import type { Diagnostic, ExportProfile, Page } from "./contracts";
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

/**
 * The artboards in an export scope that would silently lose bleed + crop marks:
 * a print-intent PDF request against a page with no bleed rect. The server skips
 * the marks and emits LUME0412 for exactly these pages, so the topbar popover
 * warns about them BEFORE the export runs. Returns [] for any non-print or
 * non-PDF request (bleed/marks are print-PDF-only), so a non-empty result means
 * "show the nudge". Same `page.bleed === null` predicate as `shouldShowPrintNudge`
 * — kept here as the single source so the visual components stay policy-free.
 */
export function bleedlessPrintPages({
  format,
  pdfIntent,
  pages
}: {
  format: ExportProfile["format"];
  pdfIntent: "preview" | "print";
  pages: readonly Page[];
}): Page[] {
  if (format !== "pdf" || pdfIntent !== "print") {
    return [];
  }
  return pages.filter((page) => page.bleed === null);
}

/**
 * The print-readiness report's non-pass rules as editor diagnostics, so a
 * topbar export that came back warn/fail lights the always-visible diagnostics
 * alert pill instead of vanishing (the silent topbar path clears export
 * diagnostics on success). Empty for a clean/absent report. `fail` rules are
 * errors (they light the pill); `warn` rules are warnings (visible in the
 * Diagnostics panel). The server rule id is the diagnostic code.
 */
export function printReadyDiagnostics(report: PrintReadyReport | null): Diagnostic[] {
  if (!report || report.status === "pass") {
    return [];
  }
  return printReadyNotableRules(report).map((rule) => ({
    severity: rule.status === "fail" ? "error" : "warning",
    phase: "export",
    code: rule.id,
    message: rule.detail || `Print-readiness rule ${rule.id} did not pass.`,
    subject: { kind: "document" },
    hint: "Enable “Print & bleed” and add a bleed area to the artboard, then re-export for a print-ready PDF."
  }));
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
