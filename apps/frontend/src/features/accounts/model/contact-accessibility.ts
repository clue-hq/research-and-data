const UNNAMED_CONTACT = "Unnamed contact";

/** The one honest visible label for a committee member whose name is absent. */
export function contactDisplayName(name: string | null): string {
  return name ?? UNNAMED_CONTACT;
}

/** Grid rows and the profile links they contain must not collapse to the same name. */
export function contactRowAccessibleName(name: string | null): string {
  return `Contact ${contactDisplayName(name)}`;
}

export function contactProfileLinkAccessibleName(name: string | null): string {
  return `Open ${contactDisplayName(name)} profile`;
}
