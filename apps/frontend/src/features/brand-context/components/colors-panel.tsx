import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandContextWorkspace } from "../model/brand-context";
import styles from "./brand-context.module.css";

export function ColorsPanel({
  controller,
  workspace,
}: {
  controller: BrandContextController;
  workspace: BrandContextWorkspace;
}) {
  return (
    <div className={styles.colorsPanel}>
      {workspace.colorGroups.map((group) => (
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
