// The brand reading the app's Brand page shares with published sites (Wave 2 A9, Task X6): the
// functions that draw a site's buttons, surfaces and motion also describe them on the Brand page, so
// the two never disagree. Pure TypeScript — no React, no Puck — so a Server Component may import it.
export { brandData, type BrandData } from "./brand";
export {
  colorOf, contrast, durationOf, easingOf, hexOf, isComponentToken, isMeasured, pxOf, styleOf, tokenEntry,
  tokenGroups, trim, typographyOf,
} from "./brand-values";
export {
  STATES, kindOf, measuredComponents, motionEntries, motionNotes, partsFromSlots,
  type MeasuredRecipe, type MotionEntry, type Part, type Parts, type State,
} from "./looks";
export { inkRole, otherSurfaceRoles, surfaceLabels } from "./surfaces";
