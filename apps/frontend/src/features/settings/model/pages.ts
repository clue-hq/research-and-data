import { z } from "zod";

export const HostnameStatusSchema = z.enum([
  "pending_dns",
  "verifying_ownership",
  "issuing_certificate",
  "active",
  "error",
  "disconnecting",
]);
export type HostnameStatus = z.infer<typeof HostnameStatusSchema>;

export const DnsRecordSchema = z.object({
  type: z.enum(["CNAME", "TXT"]),
  name: z.string(),
  required: z.string(),
  observed: z.string().nullable(),
  ok: z.boolean(),
});
export type DnsRecord = z.infer<typeof DnsRecordSchema>;

export const CustomHostnameSchema = z.object({
  hostname: z.string(),
  status: HostnameStatusSchema,
  records: z.array(DnsRecordSchema),
  lastCheckedAt: z.string().nullable(),
  error: z.object({ code: z.string(), detail: z.string().nullable() }).nullable(),
  url: z.string().nullable(),
});

export const PagesSettingsReadSchema = z.object({
  settings: z.object({
    fallbackUrl: z.string().nullable(),
    pageTitle: z.string().nullable(),
    pageDescription: z.string().nullable(),
    faviconUrl: z.string().nullable(),
    socialPreviewUrl: z.string().nullable(),
  }),
  systemHostname: z.object({
    hostname: z.string(),
    label: z.string(),
    url: z.string(),
  }),
  customHostname: CustomHostnameSchema.nullable(),
});
export type PagesSettingsRead = z.infer<typeof PagesSettingsReadSchema>;
export type CustomHostname = z.infer<typeof CustomHostnameSchema>;
export type CustomHostnameState = CustomHostname | null;

/** The provisioning progression a connecting hostname walks; `error` is not a step. */
export const STATUS_STEPS = [
  "pending_dns",
  "verifying_ownership",
  "issuing_certificate",
  "active",
] as const;

/** Index of `status` in {@link STATUS_STEPS}, or `-1` for a status that is not a step. */
export function stepIndex(status: HostnameStatus): number {
  return STATUS_STEPS.indexOf(status as (typeof STATUS_STEPS)[number]);
}

export type ConnectionView = "not_connected" | "connecting" | "active" | "error";

export function connectionView(custom: CustomHostname | null): ConnectionView {
  if (!custom) return "not_connected";
  if (custom.status === "active") return "active";
  if (custom.status === "error") return "error";
  return "connecting";
}

/**
 * Copy for the §7.3 refusal codes, rendered inline under the hostname input, and for the
 * label refusals (`label_locked` once the workspace has published), shown in the confirmation card.
 */
export const REFUSAL_MESSAGES: Record<string, string> = {
  hostname_invalid: "That is not a valid hostname.",
  hostname_is_apex:
    "Use a dedicated subdomain such as go.acme.com — a bare domain cannot be connected.",
  hostname_reserved: "Hostnames under Clue's own domains cannot be connected.",
  custom_hostname_exists:
    "This workspace already has a custom domain. Remove it first.",
  hostname_taken: "This hostname is already connected to a workspace.",
  provider_error:
    "The hosting provider refused this hostname. Try again or contact support.",
  PROVIDER_NOT_CONFIGURED: "Custom domains are not configured on this deployment.",
  label_locked: "This address has already published a site, so its label is fixed.",
  label_taken: "That label is already in use.",
  label_invalid:
    "Use 3–40 lowercase letters, digits or hyphens, not starting or ending with a hyphen.",
};
