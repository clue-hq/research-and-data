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
export function CostBreakdown({ mailer }: { mailer: Mailer }) {
  const gift = mailer.gifts.find((item) => item.id === mailer.selectedGiftId);
  return <dl className={styles.costs}><dt>Gift</dt><dd>{money(gift?.priceCents ?? null)}</dd><dt>Delivery to Clue</dt><dd>{money(mailer.inboundCents)}</dd><dt>Card, packaging & preparation</dt><dd>{money(mailer.preparationCents)}</dd><dt>Delivery to recipient</dt><dd>{money(mailer.outboundCents)}</dd><dt>Estimated tax</dt><dd>{money(mailer.taxCents)}</dd><dt className={styles.total}>Estimated total</dt><dd className={styles.total}>{money(estimate(mailer))}</dd></dl>;
}
export function ApprovalDialog({ mailers, busy, close, approve, error }: { mailers: Mailer[]; busy: boolean; close: () => void; approve: () => void; error?: string | null }) {
  return <MailDialog title={mailers.length === 1 ? "Approve this mailer?" : `Approve ${mailers.length} mailers?`} description="Confirm the selected gifts, notes and receiving addresses. Clue will prepare each package and dispatch it after its quality check." close={close} busy={busy}>
    <div className={styles.stack}>{mailers.map((m) => <div className={styles.between} key={m.id}><div>{m.recipient.name}<p className={`${styles.small} ${styles.subtle}`}>{m.gifts.find((g) => g.id === m.selectedGiftId)?.name}</p></div><span>{money(estimate(m))}</span></div>)}
      <div className={`${styles.between} ${styles.total}`}><span>Estimated total · USD</span><strong>{money(mailers.reduce((sum, m) => sum + (estimate(m) ?? 0), 0))}</strong></div>
      <p className={`${styles.small} ${styles.subtle}`}>A replacement or cost above the approved limit will come back to you for review.</p>
      <p className={`${styles.small} ${styles.subtle}`}>The estimate is deducted from gifting credits when you approve. Your project search budget reserves no credits.</p>
      <p className={styles.caption}>This local preview updates demo credits only. It does not place orders or charge a payment method.</p>
      {error ? <p role="alert">{error}</p> : null}
    </div><div className={styles.actions}><Button variant="transparent" size="md" disabled={busy} onClick={close}>Back to review</Button><Button variant="primary" size="md" disabled={busy} onClick={approve}>{busy ? "Approving…" : "Confirm approval"}</Button></div>
  </MailDialog>;
}
