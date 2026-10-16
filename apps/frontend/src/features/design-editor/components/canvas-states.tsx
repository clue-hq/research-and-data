import styles from "./web-artifact-canvas.module.css";

/** The website canvases' three designed states (W2.1), shared by the web and the site canvas. */
export function CanvasLoadingState() {
  return (
    <div className={styles.stateFrame} role="status">
      <p className={styles.stateHint}>Loading preview…</p>
    </div>
  );
}

export function CanvasErrorState({ message }: { message: string }) {
  return (
    <div className={styles.stateFrame} role="alert">
      <p className={styles.stateTitle}>Preview failed</p>
      <p className={styles.stateHint}>{message}</p>
    </div>
  );
}

export function CanvasEmptyState() {
  return (
    <div className={styles.stateFrame}>
      <p className={styles.stateTitle}>Your website will render here</p>
      <p className={styles.stateHint}>Describe what you want in the chat and the agent will build it.</p>
    </div>
  );
}
