import type { ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { estimate, money, stageLabels, type Mailer, type Stage } from "../model/direct-mail";
import styles from "./direct-mail.module.css";

export function MailStatus({ stage }: { stage: Stage }) { return <span className={styles.status} data-stage={stage}><span className={styles.dot} />{stageLabels[stage]}</span>; }
export function MailDialog({ title, description, close, children, wide = false, busy = false }: { title: string; description: string; close: () => void; children: ReactNode; wide?: boolean; busy?: boolean }) {
  return <Dialog.Root open onOpenChange={(open) => { if (!open && !busy) close(); }}><Dialog.Portal><Dialog.Backdrop className={styles.backdrop} /><Dialog.Popup className={`${styles.dialog} ${wide ? styles.dialogWide : ""}`}>
    <div className={styles.dialogHeader}><Dialog.Title className={styles.dialogTitle}>{title}</Dialog.Title><Button variant="transparent" size="icon-sm" aria-label="Close dialog" onClick={close} disabled={busy}><X size={16} /></Button></div>
    <Dialog.Description className={styles.dialogDescription}>{description}</Dialog.Description>{children}
  </Dialog.Popup></Dialog.Portal></Dialog.Root>;
}
/** Reused for individual review, bulk approval and the approved shipment. */
export function CostBreakdown({ mailer, mailers, totalLabel = "Total estimated cost · USD" }: { mailer?: Mailer; mailers?: Mailer[]; totalLabel?: string }) {
  const records = mailers ?? (mailer ? [mailer] : []);
  const sum = (read: (m: Mailer) => number | null) => {
    const amounts = records.map(read);
    return amounts.some(a => a === null) ? null : amounts.reduce<number>((total, a) => total + (a ?? 0), 0);
  };
  const lines: [string, number | null][] = [
    ["Gift cost", sum(m => m.gifts.find(g => g.id === m.selectedGiftId)?.priceCents ?? null)],
    ["Delivery to Clue", sum(m => m.inboundCents)],
    ["Card, packaging & preparation", sum(m => m.preparationCents)],
    ["Delivery to recipient", sum(m => m.outboundCents)],
    ["Estimated tax", sum(m => m.taxCents)],
  ];
  return <dl className={styles.costs}>{lines.map(([label, amount]) => <div className={styles.costLine} key={label}><dt>{label}</dt><dd>{money(amount)}</dd></div>)}<dt className={styles.total}>{totalLabel}</dt><dd className={styles.total}>{money(sum(estimate))}</dd></dl>;
}
export function ApprovalDialog({ mailers, busy, close, approve, error }: { mailers: Mailer[]; busy: boolean; close: () => void; approve: () => void; error?: string | null }) {
  return <MailDialog title={mailers.length === 1 ? "Approve this mailer?" : `Approve ${mailers.length} mailers?`} description="Confirm the selected gifts, notes and receiving addresses. Clue will prepare each package and dispatch it after its quality check." close={close} busy={busy}>
    <div className={styles.stack}>{mailers.map((m) => <div className={styles.between} key={m.id}><div>{m.recipient.name}<p className={`${styles.small} ${styles.subtle}`}>{m.gifts.find((g) => g.id === m.selectedGiftId)?.name}</p></div>{mailers.length > 1 ? <span>{money(estimate(m))}</span> : null}</div>)}
      <CostBreakdown mailers={mailers} />
      <p className={`${styles.small} ${styles.subtle}`}>A replacement or cost above the approved limit will come back to you for review.</p>
      <p className={`${styles.small} ${styles.subtle}`}>The estimate is deducted from gifting credits when you approve. Your project search budget reserves no credits.</p>
      <p className={styles.caption}>This local preview updates demo credits only. It does not place orders or charge a payment method.</p>
      {error ? <p role="alert">{error}</p> : null}
    </div><div className={styles.actions}><Button variant="transparent" size="md" disabled={busy} onClick={close}>Back to review</Button><Button variant="primary" size="md" disabled={busy} onClick={approve}>{busy ? "Approving…" : "Confirm approval"}</Button></div>
  </MailDialog>;
}
