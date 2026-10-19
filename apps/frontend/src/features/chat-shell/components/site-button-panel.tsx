"use client";

import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { SiteBoxPanel } from "./site-box-panel";

/**
 * The site element inspector's button sections (plan 3, spec §2 mockup 2): the selected button's box —
 * Fill, Stroke with its corner radius, and Layout (padding and width), drawn by the shared box panel
 * (plan 4). Its words are styled by the text panel above (label mode) and its link by the Link row below.
 */
export function SiteButtonPanel({ binding }: { binding: SiteInspectorBinding }) {
  return <SiteBoxPanel binding={binding} mode="button" />;
}
