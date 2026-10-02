import type { BrandKitActionsController } from "../hooks/use-brand-kit-actions";
import styles from "./brand-context.module.css";

export function BrandKitActionsRow({
  controller,
}: {
  controller: BrandKitActionsController;
}) {
  return (
    <div aria-label="Brand kit actions" className={styles.brandKitActions}>
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

    </div>
  );
}
