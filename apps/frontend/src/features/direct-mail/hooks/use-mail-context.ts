"use client";
import { useState } from "react";
import { dollarsToCents, GiftBudgetSchema, noteTemplateBody, renderNoteTemplate } from "../model/direct-mail-context";
import type { DirectMailController } from "./use-direct-mail";
import type { Mailer } from "../model/direct-mail";

export function useGiftBudget(c: DirectMailController, projectId: string) {
  const saved = c.data?.giftBudgets?.find((b) => b.projectId === projectId);
  const [minimum, setMinimum] = useState(String((saved?.minimumCents ?? 5000) / 100));
  const [preferred, setPreferred] = useState(String((saved?.preferredCents ?? 10000) / 100));
  const [ceiling, setCeiling] = useState(String((saved?.ceilingCents ?? 12000) / 100));
  const [editing, setEditing] = useState(!saved?.locked);
  const parsed = GiftBudgetSchema.safeParse({ projectId, revision: (saved?.revision ?? 0) + 1, minimumCents: dollarsToCents(minimum), preferredCents: dollarsToCents(preferred), ceilingCents: dollarsToCents(ceiling), locked: true });
  async function save() { if (parsed.success && await c.run(() => c.repository.saveBudget(parsed.data, saved?.revision ?? 0))) setEditing(false); }
  return { saved, minimum, setMinimum, preferred, setPreferred, ceiling, setCeiling, editing, setEditing, valid: parsed.success && !!minimum && !!preferred && !!ceiling, save };
}

export function useNoteTemplates(c: DirectMailController, mailer: Mailer, edit: (patch: { note: string; signature: string }) => void) {
  const [saving, setSaving] = useState(false), [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const templates = c.data?.noteTemplates ?? [];
  function apply(id: string) {
    const template = templates.find((t) => t.id === id);
    if (!template) return;
    try { edit({ note: renderNoteTemplate(template.body, mailer), signature: template.signature }); setError(null); }
    catch (error) { setError(error instanceof Error ? error.message : "This template could not be applied."); }
  }
  async function save() {
    const body = noteTemplateBody(mailer);
    if (await c.run(() => c.repository.saveTemplate({ id: crypto.randomUUID(), name, body, signature: mailer.signature, version: 1 }))) { setSaving(false); setName(""); }
  }
  return { templates, saving, setSaving, name, setName, error, apply, save };
}
