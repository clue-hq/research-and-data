export type ContactColumnKey =
  | "name"
  | "title"
  | "persona"
  | "influence"
  | "email"
  | "social";

export type ContactColumnWidths = Record<ContactColumnKey, number>;

export const contactColumnOrder: ContactColumnKey[] = [
  "name",
  "title",
  "persona",
  "influence",
  "email",
  "social",
];

export const defaultContactColumnWidths: ContactColumnWidths = {
  name: 220,
  title: 176,
  persona: 184,
  influence: 112,
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
  influence: { max: 320, min: 104 },
  email: { max: 520, min: 160 },
  social: { max: 360, min: 120 },
};
