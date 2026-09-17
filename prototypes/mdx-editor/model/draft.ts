/** Compare library serialization against its initial normalization, without parsing Markdown again. */
export function bodyAfterChange(savedRaw: string, normalizedBase: string | null, next: string): string {
  return next === normalizedBase || next === savedRaw ? savedRaw : next;
}

export function canSaveDraft(savedRaw: string, body: string, readOnly: boolean, hasImportError: boolean): boolean {
  return !readOnly && !hasImportError && body !== savedRaw;
}
