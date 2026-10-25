"use client";
import { useState } from "react";
import styles from "./direct-mail.module.css";

export function ProductImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) return <div className={`${styles.imagePending} ${className ?? ""}`} role="img" aria-label={`${alt} · Image unavailable`}>Product image pending</div>;
  // Merchant imagery is source material; it is never presented as a package inspection photo.
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={className} src={src} alt={alt} referrerPolicy="no-referrer" onError={() => setFailed(src)} />;
}
