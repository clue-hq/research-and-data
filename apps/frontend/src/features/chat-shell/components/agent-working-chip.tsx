import styles from "./chat-shell.module.css";

/**
 * "Designing. Please wait to edit." — the persistent chip pinned to the top-left edge
 * of the scene stage while the design agent holds the editor lock.
 *
 * Purely presentational: the caller decides visibility (`shouldShowAgentWorkingChip`).
 * The nine-dot grid pulses and the label shimmers, both in CSS (see the
 * `agentWorking*` rules in the module); under `prefers-reduced-motion` both are
 * static. `pointer-events: none` in the CSS keeps it out of the canvas's way.
 */
export function AgentWorkingChip({ label }: { label: string }) {
  return (
    <div aria-live="polite" className={styles.agentWorkingChip} role="status">
      <span aria-hidden="true" className={styles.agentWorkingGrid}>
        {Array.from({ length: 9 }, (_, index) => (
          <span className={styles.agentWorkingDot} data-dot="" key={index} />
        ))}
      </span>
      <span className={styles.agentWorkingLabel}>{label}</span>
    </div>
  );
}
