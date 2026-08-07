import type { Diagnostic } from "./contracts";

export function diagnosticsFromUnknown(payload: unknown, fallbackCode: string): Diagnostic[] {
  if (!isRecord(payload) || !Array.isArray(payload.diagnostics)) {
    return [];
  }

  return payload.diagnostics.flatMap((diagnostic) => diagnosticFromUnknown(diagnostic, fallbackCode));
}

export function diagnosticFromUnknown(value: unknown, fallbackCode: string): Diagnostic[] {
  if (!isRecord(value)) {
    return [];
  }
  const code = typeof value.code === "string" ? value.code : fallbackCode;
  const message =
    typeof value.message === "string"
      ? value.message
      : "Brand API returned a diagnostic without a message.";

  return [
    {
      severity: diagnosticSeverity(value.severity),
      phase: "brand",
      code,
      message,
      subject: diagnosticSubject(value.subject),
      hint: typeof value.hint === "string" ? value.hint : null
    }
  ];
}

export function responseStatus(payload: unknown): "ok" | "failed" | undefined {
  if (!isRecord(payload) || typeof payload.status !== "string") {
    return undefined;
  }
  return payload.status === "failed" ? "failed" : "ok";
}

export function diagnosticSeverity(value: unknown): Diagnostic["severity"] {
  return value === "error" || value === "warning" || value === "advice" ? value : "warning";
}

export function diagnosticSubject(value: unknown): Diagnostic["subject"] {
  if (!isRecord(value) || typeof value.kind !== "string") {
    return null;
  }

  switch (value.kind) {
    case "document":
      return { kind: "document" };
    case "page":
    case "node":
    case "slot":
    case "asset":
      return typeof value.id === "string" ? { kind: value.kind, id: value.id } : null;
    default:
      return null;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
