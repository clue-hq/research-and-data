import type { BrandTypeface } from "../model/brand-context";
import { TYPEFACE_SAMPLE } from "../model/typeface-preview";
import { useTypefacePreview } from "../hooks/use-typeface-preview";
import styles from "./brand-context.module.css";

export function TypefaceSample({ typeface }: { typeface: BrandTypeface }) {
  const { status, ...fontStyle } = useTypefacePreview(typeface);
  if (status !== "ready") {
    return <span className={styles.typefacePreviewStatus} role="status">{status === "loading" ? "Loading font…" : "Font preview unavailable"}</span>;
  }
  return <p style={fontStyle}>{TYPEFACE_SAMPLE}</p>;
}
