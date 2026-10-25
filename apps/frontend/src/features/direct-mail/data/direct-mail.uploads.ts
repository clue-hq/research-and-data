import type { HandwritingStyle } from "../model/direct-mail";

export function validateAssetFile(file: Pick<File, "name" | "size" | "type">, kind: "card" | "font") {
  if (kind === "card" && (!/\.(png|jpe?g)$/i.test(file.name) || !["image/png", "image/jpeg"].includes(file.type))) throw new Error("Choose a PNG or JPEG card image.");
  if (kind === "font" && !/\.(ttf|otf|woff2?)$/i.test(file.name)) throw new Error("Choose a TTF, OTF, WOFF or WOFF2 font file.");
  if (file.size === 0) throw new Error("This file is empty.");
  if (file.size > (kind === "card" ? 3 : 2) * 1024 * 1024) throw new Error(`Choose a file under ${kind === "card" ? 3 : 2} MB.`);
}
export async function readLocalAsset(file: File, kind: "card" | "font"): Promise<string> {
  validateAssetFile(file, kind);
  const source = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(new Error("This file could not be read. Try again.")); reader.onload = () => resolve(String(reader.result)); reader.readAsDataURL(file); });
  if (kind === "card") await new Promise<void>((resolve, reject) => { const image = new Image(); image.onload = () => image.width && image.height ? resolve() : reject(new Error("The card image has no dimensions.")); image.onerror = () => reject(new Error("This image could not be opened.")); image.src = source; });
  else { try { await new FontFace("ClueUploadValidation", `url(${source})`).load(); } catch { throw new Error("This font could not be opened. Try another file."); } }
  return source;
}
const registered = new Map<string, Promise<void>>();
export function registerHandwriting(styles: HandwritingStyle[]) {
  return Promise.all(styles.map((style) => {
    if (!style.sourceUrl || typeof document === "undefined") return Promise.resolve();
    const key = `${style.id}:${style.version}`;
    if (!registered.has(key)) registered.set(key, new FontFace(style.family, `url(${style.sourceUrl})`).load().then((face) => { document.fonts.add(face); }).catch(() => { registered.delete(key); }));
    return registered.get(key)!;
  }));
}
