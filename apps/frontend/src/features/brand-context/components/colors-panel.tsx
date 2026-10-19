import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandContextWorkspace } from "../model/brand-context";
import styles from "./brand-context.module.css";

export function ColorsPanel({
  controller,
  emptyMessage,
  measuredGroups = [],
  workspace,
}: {
  controller: BrandContextController;
  emptyMessage: string;
  /** Section backgrounds and each measured style's colours (Task X6), after the kit's own groups. */
  measuredGroups?: BrandContextWorkspace["colorGroups"];
  workspace: BrandContextWorkspace;
}) {
  const groups = [...workspace.colorGroups, ...measuredGroups];
  return (
    <div className={styles.colorsPanel}>
      {!groups.length ? (
        <div className={styles.emptyState}>{emptyMessage}</div>
      ) : null}
      {groups.map((group) => (
        <section className={styles.colorSection} key={group.id}>
          <h2>{group.label}</h2>
          <div className={styles.swatchGrid}>
            {group.swatches.map((swatch) => {
              const value = controller.colorMode === "light" ? swatch.lightValue : swatch.darkValue;
              return (
                <article className={styles.swatchCard} key={swatch.id}>
                  <div className={styles.swatchPreview} style={{ background: value }} />
                  <div className={styles.swatchMeta}>
                    <span className={styles.swatchLabel}>{swatch.label}</span>
                    <code>{value}</code>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
