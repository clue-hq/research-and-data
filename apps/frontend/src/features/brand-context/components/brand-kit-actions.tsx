import type { BrandKitActionsController } from "../hooks/use-brand-kit-actions";
import styles from "./brand-context.module.css";

const chipToneClass = {
  approved: styles.approvalChipApproved,
  draft: styles.approvalChipDraft,
  neutral: styles.approvalChipNeutral,
  unreviewed: styles.approvalChipUnreviewed,
} as const;

/** Founder-ratified Option A: kit status + actions in the page header. */
export function BrandKitActionsRow({
  controller,
}: {
  controller: BrandKitActionsController;
}) {
  return (
    <div aria-label="Brand kit actions" className={styles.brandKitActions}>
      {controller.chip ? (
        <span
          className={`${styles.approvalChip} ${chipToneClass[controller.chip.tone]}`}
          data-approval-tone={controller.chip.tone}
        >
          {controller.chip.label}
        </span>
      ) : null}
      <button
        aria-busy={controller.extracting || undefined}
        aria-label="Re-extract brand kit from website"
        className={styles.secondaryButton}
        disabled={controller.reExtractDisabled}
        onClick={controller.reExtract}
        title={controller.reExtractHint ?? undefined}
        type="button"
      >
        <span aria-hidden="true">↻</span>
        Re-extract
      </button>
      {controller.showApprove ? (
        <button
          aria-busy={controller.approving || undefined}
          className={styles.primaryButton}
          disabled={controller.approveDisabled}
          onClick={controller.approve}
          type="button"
        >
          {controller.approving ? "Approving…" : "Approve"}
        </button>
      ) : null}
    </div>
  );
}
