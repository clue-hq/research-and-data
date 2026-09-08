import { z } from "zod";

/**
 * The contact email-lookup contract.
 *
 * It lives beside, not inside, `account-contact.ts`: that file is the lifted
 * research/display contract from the design build, while these two schemas are
 * the platform's own mutation contract, consumed by the bulk-action and
 * email-lookup repositories.
 */
export const EmailLookupStateSchema = z.enum([
  "pending",
  "available",
  "not_found",
  "withheld",
  "unavailable",
  "failed",
]);

export const ContactEmailLookupSchema = z.object({
  lookupId: z.string(),
  state: EmailLookupStateSchema,
  // Retained machine metadata; the UI does not add verification/corroboration badges.
  resolution: z.enum([
    "pending",
    "matched",
    "single_source",
    "conflict",
    "none",
    "withheld",
    "unavailable",
    "failed",
  ]),
  emails: z
    .array(
      z.object({
        value: z.string().email(),
        sources: z.array(
          z.object({ key: z.string(), label: z.string() }),
        ),
      }),
    )
    .default([]),
  retryable: z.boolean().default(false),
});

export type EmailLookupState = z.infer<typeof EmailLookupStateSchema>;
export type ContactEmailLookup = z.infer<typeof ContactEmailLookupSchema>;
