/**
 * Face-level font style resolution for the CanvasKit canvas.
 *
 * CanvasKit's (wasm) `TypefaceFontProvider` performs NO style matching: every
 * request for a family returns the first face registered under that name,
 * whatever `fontStyle` asks for. The native Skia provider the server uses
 * does real CSS3 weight/slant matching, so relying on CanvasKit matching made
 * the canvas render single-weight typography while exports carried the real
 * weights. The editor therefore selects faces ITSELF:
 *
 *   - every face registers under a style-qualified alias (`faceAlias`) in
 *     addition to its plain family name;
 *   - paragraph builders resolve (family, weight, italic) to that alias via
 *     `selectFace`, which mirrors Skia's CSS3 matching (`matchStyleCSS3`) —
 *     the same snap the server performs (and reports as LUMS0104/0105);
 *   - a face's true weight/slant comes from its BYTES (`parseFaceMeta`, the
 *     OS/2 table — exactly what the server's Skia parser reads), with the
 *     declared manifest/kit metadata as fallback (`effectiveFaceMeta`).
 *
 * Pure functions only — the stateful registry lives in `loadCanvasKit.ts`.
 */

/** A face's style identity: the two axes our font model carries. */
export interface FaceMeta {
  weight: number;
  italic: boolean;
}

/** One face registered in the provider, addressable by its alias. */
export interface RegisteredFace extends FaceMeta {
  alias: string;
}

/** The provider alias a face registers under, unique per (family, style).
 * `::` cannot appear in a real CSS family name coming out of the scene
 * grammar, so aliases can never shadow a declared family. */
export function faceAlias(family: string, weight: number, italic: boolean): string {
  return `${family}::w${weight}${italic ? "i" : ""}`;
}

const SFNT_TTF = 0x00010000;
const SFNT_OTTO = 0x4f54544f; // 'OTTO'
const SFNT_TRUE = 0x74727565; // 'true'
const SFNT_TTC = 0x74746366; // 'ttcf'
const TAG_OS2 = 0x4f532f32; // 'OS/2'
const TAG_HEAD = 0x68656164; // 'head'

/**
 * Parse a face's weight/slant from its sfnt bytes: OS/2 `usWeightClass` and
 * the `fsSelection` ITALIC bit (with `head.macStyle` as the italic fallback).
 * This is the same source of truth Skia reads on the server, so byte-parsed
 * meta keeps the two runtimes agreeing even when declared metadata is absent
 * or wrong. Returns `null` for anything unparseable (e.g. woff2, which
 * CanvasKit cannot load anyway) — callers fall back to declared metadata.
 */
export function parseFaceMeta(bytes: ArrayBuffer): FaceMeta | null {
  try {
    const view = new DataView(bytes);
    let base = 0;
    if (view.getUint32(0) === SFNT_TTC) {
      // Font collection: read the first face's offset table.
      if (view.getUint32(8) < 1) {
        return null;
      }
      base = view.getUint32(12);
    }
    const version = view.getUint32(base);
    if (version !== SFNT_TTF && version !== SFNT_OTTO && version !== SFNT_TRUE) {
      return null;
    }
    const numTables = view.getUint16(base + 4);
    let os2Offset = -1;
    let headOffset = -1;
    for (let i = 0; i < numTables; i += 1) {
      const record = base + 12 + i * 16;
      const tag = view.getUint32(record);
      if (tag === TAG_OS2) {
        os2Offset = view.getUint32(record + 8);
      } else if (tag === TAG_HEAD) {
        headOffset = view.getUint32(record + 8);
      }
    }
    if (os2Offset < 0) {
      return null;
    }
    const weight = view.getUint16(os2Offset + 4);
    if (weight < 1 || weight > 1000) {
      return null;
    }
    let italic = (view.getUint16(os2Offset + 62) & 0x01) !== 0;
    if (!italic && headOffset >= 0) {
      italic = (view.getUint16(headOffset + 44) & 0x02) !== 0;
    }
    return { weight, italic };
  } catch {
    return null;
  }
}

/**
 * A face's effective style: byte-parsed meta when the bytes parse (server
 * truth — Skia ignores declared metadata), else the declared manifest/kit
 * fields, else the (400, upright) default.
 */
export function effectiveFaceMeta(face: {
  bytes: ArrayBuffer;
  weight?: number;
  style?: string;
}): FaceMeta {
  return (
    parseFaceMeta(face.bytes) ?? {
      weight: typeof face.weight === "number" ? face.weight : 400,
      italic: face.style === "italic"
    }
  );
}

/**
 * Select the face a (weight, italic) request resolves to, mirroring Skia's
 * CSS3 matching: slant first (faces of the requested slant when any exist,
 * otherwise the silent italic↔upright snap), then the CSS3 weight rules.
 * Deterministic: ties resolve to the first-registered face at the chosen
 * weight. `null` only for an empty face list.
 */
export function selectFace(faces: RegisteredFace[], weight: number, italic: boolean): RegisteredFace | null {
  if (faces.length === 0) {
    return null;
  }
  const slantMatched = faces.filter((face) => face.italic === italic);
  const pool = slantMatched.length > 0 ? slantMatched : faces;
  const available = [...new Set(pool.map((face) => face.weight))];
  const chosen = chooseWeight(available, weight);
  return pool.find((face) => face.weight === chosen) ?? null;
}

/** CSS3 weight selection over the available weights (non-empty). */
function chooseWeight(available: number[], target: number): number {
  if (available.includes(target)) {
    return target;
  }
  const below = available.filter((w) => w < target);
  const above = available.filter((w) => w > target);
  if (target >= 400 && target <= 500) {
    // Between target and 500 ascending, then below descending, then above.
    const between = above.filter((w) => w <= 500);
    if (between.length > 0) {
      return Math.min(...between);
    }
    return below.length > 0 ? Math.max(...below) : Math.min(...above);
  }
  if (target < 400) {
    // Thin request: nearest below, else nearest above.
    return below.length > 0 ? Math.max(...below) : Math.min(...above);
  }
  // Bold request: nearest above, else nearest below.
  return above.length > 0 ? Math.min(...above) : Math.max(...below);
}
