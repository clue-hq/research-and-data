"use client";

import { useState } from "react";
import { estimate, readiness, type Mailer, type MailerPatch } from "../model/direct-mail";
import type { DirectMailController } from "./use-direct-mail";
import { readPendingDraft, writePendingDraft } from "../data/direct-mail.drafts";

export function useMailerEditor(c: DirectMailController, saved: Mailer) {
  const [draft, setDraft] = useState(() => readPendingDraft(saved.id));
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [approval, setApproval] = useState<Mailer | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [request, setRequest] = useState<"gifts" | "insight" | null>(null);
  const [feedback, setFeedback] = useState("");
  const mailer = { ...saved, ...draft?.patch };
  const changedElsewhere = draft !== null && draft.revision !== saved.revision;
  const issues = c.data ? readiness(mailer, c.data) : [];
  function edit(patch: MailerPatch) {
    const next = { revision: draft?.revision ?? saved.revision, patch: { ...draft?.patch, ...patch } };
    setDraft(next);
    setRecoveryError(writePendingDraft(saved.id, next) ? null : "Draft recovery is unavailable. Use Save draft before leaving this page.");
  }
  async function save() {
    if (!draft) return saved;
    const result = await c.run(() => c.repository.patch(saved.id, draft.revision, draft.patch));
    if (!result) return null;
    setDraft(null);
    writePendingDraft(saved.id, null);
    return result.mailers.find((item) => item.id === saved.id)!;
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
  return { mailer, step, go, edit, save, dirty: !!draft, changedElsewhere, recoveryError, discard: () => { setDraft(null); writePendingDraft(saved.id, null); }, issues,
    estimate: estimate(mailer), approval, setApproval, approvalError, review, approve, request, setRequest, feedback, setFeedback, submitRequest, resolveRequest };
}
