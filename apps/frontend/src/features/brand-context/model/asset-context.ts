import { z } from "zod";

export const CreativeTypeSchema = z.enum(["ad", "logo", "background", "product_image", "product_screenshot", "photo", "illustration", "icon", "badge_seal", "other", "unknown"]);
export const UsageRoleSchema = z.enum(["section_background", "hero_image", "card_image", "inline_image", "reference_only"]);
export const AssetSourceSchema = z.enum(["website", "linkedin_ad", "user_upload", "generated", "pdf", "unknown"]);
export const AnalysisStatusSchema = z.enum(["stale", "queued", "analyzing", "ready", "failed", "unsupported"]);
export const SourceOccurrenceSchema = z.object({
  occurrence_id: z.string(), source: AssetSourceSchema, brand_kit_id: z.string().nullish(),
  page_url: z.string().nullish(), locator: z.string().nullish(), surrounding_text: z.string().nullish(),
  alt: z.string().nullish(), placement: z.string().nullish(), creative_id: z.string().nullish(),
  ad_permalink: z.string().nullish(), advertiser: z.string().nullish(), headline: z.string().nullish(),
  commentary: z.string().nullish(), user_note: z.string().nullish(),
});
const ObservedSchema = z.object({
  subjects: z.array(z.string()), composition: z.string(), colors: z.array(z.string()),
  readable_text: z.array(z.string()), typography: z.string(), logo_placement: z.string(),
  negative_space: z.string(), transparency: z.string(),
});
const InterpretationSchema = z.object({
  occurrence_id: z.string(), observed_usage: z.string(),
  logo_relationship: z.enum(["own_brand", "customer", "partner", "third_party", "unknown"]),
  relationship_evidence: z.string(), messaging_angle: z.string(), tone: z.string(), cta: z.string(),
  visual_hierarchy: z.string(), copy_density: z.string(), product_or_use_case_hypothesis: z.string(),
  audience_hypothesis: z.string(), design_patterns: z.array(z.string()), uncertainties: z.array(z.string()),
});
export const AssetAnalysisSchema = z.object({
  creative_type: CreativeTypeSchema, usage_roles: z.array(UsageRoleSchema), classification_reason: z.string(),
  title: z.string(), description: z.string(), usage: z.string(), avoid_when: z.string(), placement: z.string(),
  tags: z.array(z.string()), observed: ObservedSchema, source_interpretations: z.array(InterpretationSchema),
  uncertainties: z.array(z.string()), reuse_boundary: z.string(),
});
export const AssetOverridesSchema = z.object({
  title: z.string().max(120).nullish(), description: z.string().max(12000).nullish(),
  usage: z.string().max(12000).nullish(), avoid_when: z.string().max(12000).nullish(), placement: z.string().max(12000).nullish(),
  tags: z.array(z.string()).nullish(), creative_type: CreativeTypeSchema.nullish(),
  usage_roles: z.array(UsageRoleSchema).nullish(), user_note: z.string().max(4000).nullish(),
});
export const AssetContextSchema = z.object({
  asset_id: z.string(), title: z.string().nullish(), description: z.string().nullish(), usage: z.string().nullish(),
  avoid_when: z.string().nullish(), placement: z.string().nullish(), tags: z.array(z.string()).default([]),
  creative_type: CreativeTypeSchema.default("unknown"), usage_roles: z.array(UsageRoleSchema).default([]),
  user_note: z.string().nullish(), classification_origin: z.string().optional(), classification_reason: z.string().optional(),
  revision: z.number().int().default(0), status: AnalysisStatusSchema.default("stale"),
  overrides: AssetOverridesSchema.default({}), source_occurrences: z.array(SourceOccurrenceSchema).default([]),
  diagnostic: z.object({ code: z.string(), message: z.string(), retryable: z.boolean().optional() }).nullish(),
  analysis: z.union([AssetAnalysisSchema, z.object({}).strict()]).optional(),
  agent_context: z.object({
    observed: ObservedSchema.nullish(), source_interpretations: z.array(InterpretationSchema).default([]),
    guidance: z.object({usage: z.string().nullish(), avoid_when: z.string().nullish(), placement: z.string().nullish()}).optional(),
    uncertainties: z.array(z.string()).default([]), reuse_boundary: z.string().nullish(),
    preview: z.record(z.string(), z.unknown()).nullish(), analysis_input: z.record(z.string(), z.unknown()).optional(),
  }).optional(),
});
export const AssetContextBatchSchema = z.object({descriptions: z.record(z.string(), AssetContextSchema)});
export type AssetContext = z.infer<typeof AssetContextSchema>;
export type AssetOverrides = z.infer<typeof AssetOverridesSchema>;
export type CreativeType = z.infer<typeof CreativeTypeSchema>;
export type UsageRole = z.infer<typeof UsageRoleSchema>;
export const assetLabel = (value: string) => value.replaceAll("_", " ").replace(/^./, (char) => char.toUpperCase());
// Deliberately only formats with an established custody, preview and placement path.
export const ASSET_UPLOAD_ACCEPT = ".png,.jpg,.jpeg,.webp,.svg,.gif";
export const ASSET_UPLOAD_TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"];
export const AssetUploadCapabilitiesSchema = z.object({max_bytes: z.number().int().positive(), formats: z.array(z.enum(["png", "jpeg", "webp", "svg", "gif"]))});
export type AssetUploadCapabilities = z.infer<typeof AssetUploadCapabilitiesSchema>;
