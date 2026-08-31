// @vitest-environment node
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "../../__tests__/vitest-shim";
import { effectiveFaceMeta, faceAlias, parseFaceMeta, selectFace, type RegisteredFace } from "../canvaskit/fontFaces";

/**
 * Face-level style resolution: the pure half of the canvas font-weight fix.
 *
 * `selectFace`'s weight snaps are pinned to SKIA'S MEASURED BEHAVIOR — the
 * expected values below were probed live against the server's
 * `FontManager::match_typeface` (skia_safe matchStyleCSS3) over the bundled
 * Inter set {400, 600, 700, 800}. If these pins ever disagree with the
 * server, canvas and export weight-snap semantics have diverged.
 */

const REPO_FONTS = path.resolve(__dirname, "./__fixtures__/fonts");

function fontArrayBuffer(fileName: string): ArrayBuffer {
  const bytes = readFileSync(path.join(REPO_FONTS, fileName));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function face(weight: number, italic = false): RegisteredFace {
  return { alias: faceAlias("Fam", weight, italic), weight, italic };
}

describe("parseFaceMeta (OS/2 byte truth)", () => {
  it("reads the real OS/2 weight from the bundled Inter statics", () => {
    expect(parseFaceMeta(fontArrayBuffer("Inter-Regular.ttf"))).toEqual({ weight: 400, italic: false });
    expect(parseFaceMeta(fontArrayBuffer("Inter-SemiBold.ttf"))).toEqual({ weight: 600, italic: false });
    expect(parseFaceMeta(fontArrayBuffer("Inter-Bold.ttf"))).toEqual({ weight: 700, italic: false });
    expect(parseFaceMeta(fontArrayBuffer("Inter-ExtraBold.ttf"))).toEqual({ weight: 800, italic: false });
  });

  it("returns null for non-sfnt bytes", () => {
    expect(parseFaceMeta(new ArrayBuffer(0))).toBeNull();
    expect(parseFaceMeta(new Uint8Array([1, 2, 3, 4]).buffer)).toBeNull();
    const woff2 = new TextEncoder().encode("wOF2....").buffer as ArrayBuffer;
    expect(parseFaceMeta(woff2)).toBeNull();
  });
});

describe("effectiveFaceMeta precedence", () => {
  it("byte-parsed meta wins over declared metadata (server truth)", () => {
    const bytes = fontArrayBuffer("Inter-Bold.ttf");
    expect(effectiveFaceMeta({ bytes, weight: 100, style: "italic" })).toEqual({ weight: 700, italic: false });
  });

  it("falls back to declared metadata, then (400, upright), for unparseable bytes", () => {
    const bytes = new ArrayBuffer(4);
    expect(effectiveFaceMeta({ bytes, weight: 800, style: "italic" })).toEqual({ weight: 800, italic: true });
    expect(effectiveFaceMeta({ bytes })).toEqual({ weight: 400, italic: false });
  });
});

describe("faceAlias", () => {
  it("is style-qualified and italic-marked", () => {
    expect(faceAlias("Hanken Grotesk", 700, false)).toBe("Hanken Grotesk::w700");
    expect(faceAlias("Hanken Grotesk", 700, true)).toBe("Hanken Grotesk::w700i");
  });
});

describe("selectFace (Skia matchStyleCSS3 mirror)", () => {
  // The bundled server set — every pin below matches a live probe of the
  // server's match_typeface over these faces.
  const inter = [face(400), face(600), face(700), face(800)];
  const chosen = (weight: number, italic = false, faces = inter) =>
    selectFace(faces, weight, italic)?.weight;

  it("resolves exact weights exactly", () => {
    for (const w of [400, 600, 700, 800]) {
      expect(chosen(w)).toBe(w);
    }
  });

  it("snaps intermediate and out-of-range weights exactly like the server", () => {
    expect(chosen(100)).toBe(400);
    expect(chosen(300)).toBe(400);
    expect(chosen(350)).toBe(400);
    expect(chosen(450)).toBe(400);
    expect(chosen(500)).toBe(400);
    expect(chosen(550)).toBe(600);
    expect(chosen(650)).toBe(700);
    expect(chosen(750)).toBe(800);
    expect(chosen(900)).toBe(800);
    expect(chosen(1000)).toBe(800);
  });

  it("applies the CSS 400–500 rule: up to 500 first, then below, then above", () => {
    expect(chosen(450, false, [face(300), face(480), face(600)])).toBe(480);
    expect(chosen(450, false, [face(300), face(600)])).toBe(300);
    expect(chosen(450, false, [face(600), face(800)])).toBe(600);
  });

  it("prefers the requested slant, snapping italic↔upright only when unsatisfiable", () => {
    const faces = [face(400), face(700), face(400, true)];
    const italicPick = selectFace(faces, 700, true);
    // Slant outranks weight: the lone italic wins over the exact-weight upright.
    expect(italicPick).toMatchObject({ weight: 400, italic: true });
    // No italic faces at all → the upright snap the server reports as LUMS0105.
    expect(selectFace([face(400), face(700)], 700, true)).toMatchObject({ weight: 700, italic: false });
    // Upright request never picks an italic while an upright exists.
    expect(selectFace(faces, 400, false)).toMatchObject({ weight: 400, italic: false });
  });

  it("ties resolve to the first-registered face and empty input yields null", () => {
    const a = { alias: "Fam::w400#a", weight: 400, italic: false };
    const b = { alias: "Fam::w400#b", weight: 400, italic: false };
    expect(selectFace([a, b], 400, false)).toBe(a);
    expect(selectFace([], 400, false)).toBeNull();
  });
});
