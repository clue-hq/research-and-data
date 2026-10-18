// Site element inspector, plan 5 (rulings R1, R2, R5): where a selected image's file and its alt text
// are written, by the kind of section it sits in. One rule for the frame (which reports them) and the
// tests. Notes are said in the panel when the marketer cannot change one.
import { cloneImageAt, type Clone } from "./clone";
import type { AltSource, ComputedImage, ImageSource } from "./editor-protocol";

export const SELLER_LOGO = "The seller's logo comes from the brand kit.";
export const CLONE_IMAGE = "This image is copied from the seller's page and has no slot; ask the agent to change it.";
export const AGENT_IMAGE = "The agent's section sets this image; ask the agent to change it.";
export const AGENT_ALT = "The agent's section sets this image's alt text; ask the agent to change it.";
export const VIDEO_REPLACE = "Ask the agent to change a video.";
export const VIDEO_ALT = "Videos have no alt text; the agent can describe one in the words beside it.";
export const ICON_NOTE = "This is an icon drawn in code; ask the agent to change it.";

/** An image file a site may hold: a stored asset or a brand asset. */
const IMAGE_FILE = /^\/(asset-store|brands)\//;

const fixed = (reason: string) => ({ kind: "fixed" as const, reason });

/** Where an image's file and alt text are written: our image prop (FeatureSplit `image` / `imageAlt`),
 * the header's account logo, the seller's logo (its file is the brand kit's), a copied image's slot
 * (and its alt by element key), or an agent's image named after the prop holding its file. */
export function imageSourcesOf(input: {
  type: string;
  key: string;
  props: Record<string, unknown>;
  clone: Clone | null;
  media: ComputedImage["media"];
  /** The file the image draws: an agent's named prop is its source only when it holds this file
   * (review I3: `el` may name a prop that is not this image's). */
  src: string;
}): { image: ImageSource; alt: AltSource } {
  const { clone, key, media, props, src, type } = input;
  if (media === "svg") return { alt: fixed(ICON_NOTE), image: fixed(ICON_NOTE) };
  if (media === "video") return { alt: fixed(VIDEO_ALT), image: fixed(VIDEO_REPLACE) };
  if (type === "SiteHeader" && key === "accountLogo") {
    return { alt: { kind: "prop", prop: "accountLogoAlt" }, image: { kind: "prop", prop: "accountLogo", uses: 1 } };
  }
  if ((type === "SiteHeader" || type === "SiteFooter") && key === "logo") return { alt: { kind: "prop", prop: "logoAlt" }, image: fixed(SELLER_LOGO) };
  if (type === "FeatureSplit" && key === "image") return { alt: { kind: "prop", prop: "imageAlt" }, image: { kind: "prop", prop: "image", uses: 1 } };
  if (type === "ClonedSection") {
    const found = clone ? cloneImageAt(clone, key) : null;
    return {
      alt: { key, kind: "clone" },
      image: found?.slot ? { kind: "slot", slot: found.slot, uses: found.uses } : fixed(CLONE_IMAGE),
    };
  }
  const named = props[key];
  return {
    alt: fixed(AGENT_ALT),
    image: typeof named === "string" && IMAGE_FILE.test(named) && named === src ? { kind: "prop", prop: key, uses: 1 } : fixed(AGENT_IMAGE),
  };
}
