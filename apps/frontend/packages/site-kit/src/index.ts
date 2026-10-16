// The site kit's render surface: the brand data, the Puck config (our sections, the shell, the
// seller's cloned sections and the site's agent-written sections), the theme and the page contract.
// The validator, the catalog and the section check have their own entry points
// (@clue/site-kit/validate, /catalog, /check-section); the editor-only parts are @clue/site-kit/editor.
export { brandData, type BrandAsset, type BrandData, type FontFace } from "./brand";
export {
  fillClone,
  slotDefaults,
  type Clone,
  type CloneSlot,
  type LinkReplacement,
  type SlotKind,
  type SlotValues,
  type TextReplacement,
} from "./clone";
export { FALLBACKS, isComponentToken } from "./brand-values";
export { extraSurfaceRoles, surfaceChoices, surfaceLabels, surfaceRoles, type SurfaceChoice } from "./surfaces";
export { buttonLookOptions, buttonLooks, cardLookOptions, cardLooks, motionClassNames, motionEntries, type Look } from "./looks";
export { SPACING_ROLES, editorThemeCss, tailwindThemeCss, themeCss } from "./theme";
export * from "./schemas";
export { makeConfig, type ConfigOptions, type EditorParts } from "./config";
export { makeKit, type AgentSectionModule, type Kit } from "./agent-kit";
export { EDIT_INLINE, IMAGE_PROP, LINK_PROP, brandChoice, notInlineReason, type BrandChoice } from "./agent-props";
export { SiteFooter, SiteHeader, logoFiles, sellerLogo, type FooterProps, type HeaderProps, type ShellData } from "./shell";
export { surfaceClass, type AnySurface } from "./sections";
export { RenderRefusal, renderSitePages, sectionPropsSchema, siteRoutes, type RenderedSitePage, type StoredSite } from "./render-core";
