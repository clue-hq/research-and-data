"use client";

import { useRef, useState } from "react";
import { estimate, readiness, type Mailer, type MailerPatch } from "../model/direct-mail";
import type { DirectMailController } from "./use-direct-mail";
import { readPendingDraft, writePendingDraft } from "../data/direct-mail.drafts";

export function useMailerEditor(c: DirectMailController, saved: Mailer, initialStep = 0) {
  const [draft, setDraft] = useState(() => readPendingDraft(saved.id));
  const draftRef = useRef(draft);
  const saving = useRef(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [step, setStep] = useState(initialStep);
  const [approval, setApproval] = useState<Mailer | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [request, setRequest] = useState<"gifts" | "insight" | null>(null);
  const [feedback, setFeedback] = useState("");
  const mailer = { ...saved, ...draft?.patch };
  const changedElsewhere = draft !== null && draft.revision !== saved.revision;
  const issues = c.data ? readiness(mailer, c.data) : [];
  function replaceBuffer(next: typeof draft) {
    draftRef.current = next;
    setDraft(next);
    setRecoveryError(writePendingDraft(saved.id, next) ? null : "Draft recovery is unavailable. Use Save draft before leaving this page.");
  }
  function edit(patch: MailerPatch) {
    const current = draftRef.current;
    const next = { revision: current?.revision ?? saved.revision, patch: { ...current?.patch, ...patch } };
    replaceBuffer(next);
    // Invalidate a reviewed record immediately, including for other open views.
    // Further typing stays in the recovery buffer until explicitly saved.
    if (saved.stage === "ready" && next.revision === saved.revision && !saving.current) return persist(next);
  }
  async function persist(submitted: NonNullable<typeof draft>) {
    if (saving.current) return null;
    saving.current = true;
    try {
      const result = await c.run(() => c.repository.patch(saved.id, submitted.revision, submitted.patch));
      if (!result) return null;
      const record = result.mailers.find((item) => item.id === saved.id)!;
      if (draftRef.current === submitted) { replaceBuffer(null); return record; }
      // A keystroke arrived after the request started: retain it and use the
      // successful write's revision as its base. Never advance review yet.
      if (draftRef.current) replaceBuffer({ ...draftRef.current, revision: record.revision });
      return null;
    } finally { saving.current = false; }
  }
  async function save() {
    if (saving.current) return null;
    return draftRef.current ? persist(draftRef.current) : saved;
  }
  async function go(next: number) { if (await save()) setStep(next); }
  async function review(openApproval: boolean) {
    const current = await save();
    if (!current) return;
    const result = await c.run(() => c.repository.review(current.id, current.revision));
    if (result && openApproval) setApproval(result.mailers.find((item) => item.id === current.id)!);
  }
  async function approve() {
    if (!approval) return;
    setApprovalError(null);
    const result = await c.run(() => c.repository.approve([{ id: approval.id, revision: approval.revision }]));
    if (result?.results.every((item) => item.ok)) setApproval(null);
    else if (result) setApprovalError(result.results.find((item) => !item.ok)?.message ?? "Approval could not be saved.");
    return result?.results;
  }
  async function submitRequest() {
    const current = await save();
    if (!current || !request) return;
    if (await c.run(() => c.repository.requestProposal(current.id, current.revision, request, feedback))) { setRequest(null); setFeedback(""); }
  }
  async function resolveRequest(apply: boolean) {
    const current = await save();
    if (current) await c.run(() => c.repository.resolveProposal(current.id, current.revision, apply));
  }
  async function selectAlternative(id: string) {
    const current = await save();
    if (!current) return false;
    return !!await c.run(() => c.repository.patch(current.id, current.revision, { selectedGiftId: id }));
  }
  return { mailer, step, go, edit, save, dirty: !!draft, changedElsewhere, recoveryError, discard: () => replaceBuffer(null), issues,
    estimate: estimate(mailer), approval, setApproval, approvalError, review, approve, request, setRequest, feedback, setFeedback, submitRequest, resolveRequest, selectAlternative };
}
