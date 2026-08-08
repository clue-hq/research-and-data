/**
 * Contacts-table view configuration (presentation only).
 *
 * `influence` is gone (D-7: a fixture-only band). Its honest replacement is
 * `role` — the governed committee role plus the confidence behind it — and
 * `signals`, the count of signal TYPES. The `email` column keeps its local
 * lookup affordance: it has never read a backend field, and slice 1 serves no
 * email data at all (G3).
 */
export type ContactColumnKey =
  | "name"
  | "title"
  | "persona"
  | "role"
  | "signals"
  | "email"
  | "social";

export type ContactColumnWidths = Record<ContactColumnKey, number>;

export const contactColumnOrder: ContactColumnKey[] = [
  "name",
  "title",
  "persona",
  "role",
  "signals",
  "email",
  "social",
];

export const defaultContactColumnWidths: ContactColumnWidths = {
  name: 220,
  title: 176,
  persona: 184,
  role: 180,
  signals: 140,
  email: 196,
  social: 136,
};

export const contactColumnWidthConstraints: Record<
  ContactColumnKey,
  { max: number; min: number }
> = {
  name: { max: 640, min: 180 },
  title: { max: 480, min: 128 },
  persona: { max: 480, min: 136 },
  role: { max: 400, min: 128 },
  signals: { max: 320, min: 112 },
  email: { max: 520, min: 160 },
  social: { max: 360, min: 120 },
};
