import { useEffect, useMemo, useState } from "react";
import type { BrandTypeface } from "../model/brand-context";
import { cssFontString, TYPEFACE_SAMPLE, typefacePreviewSpec } from "../model/typeface-preview";

/** A font sample is shown only after its actual face has loaded successfully. */
export function useTypefacePreview(typeface: BrandTypeface) {
  const { family, sources, weight, style, registeredFamily } = useMemo(() => typefacePreviewSpec(typeface), [typeface]);
  const identity = JSON.stringify([family, sources, weight, style, registeredFamily]);
  const [result, setResult] = useState<{ identity: string; family: string; status: "ready" | "unavailable" } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let ownedFaces: FontFace[] = [];
    async function load() {
      // Reuse an already registered application/library font, but an empty result
      // does not prove an unknown family exists: browsers silently fall back for it.
      if (registeredFamily) {
        const registered = await document.fonts.load(`400 18px ${registeredFamily}`, TYPEFACE_SAMPLE);
        if (registered.length) {
          if (!cancelled) setResult({ identity, family: registeredFamily, status: "ready" });
          return;
        }
      }
      if (cancelled) return;
      ownedFaces = sources.map((source) => new FontFace(family, source, { weight: String(weight), style }));
      await Promise.all(ownedFaces.map((face) => face.load()));
      if (cancelled) return;
      ownedFaces.forEach((face) => document.fonts.add(face));
      setResult({ identity, family: cssFontString(family), status: "ready" });
    }
    void load().catch(() => {
      if (!cancelled) setResult({ identity, family, status: "unavailable" });
    });
    return () => {
      cancelled = true;
      ownedFaces.forEach((face) => document.fonts.delete(face));
    };
  }, [family, identity, registeredFamily, sources, style, weight]);

  return {
    status: result?.identity === identity ? result.status : "loading",
    fontFamily: result?.identity === identity ? result.family : cssFontString(family),
    fontWeight: weight,
    fontStyle: style,
  };
}
