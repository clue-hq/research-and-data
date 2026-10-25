"use client";
import { useState } from "react";
import Link from "next/link";
import { Check, ExternalLink, LockKeyhole, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { money, type Mailer } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { useGiftBudget, useNoteTemplates } from "../hooks/use-mail-context";
import { MailDialog } from "./mail-ui";
import styles from "./direct-mail.module.css";

export function MailBadge({ children }: { children: React.ReactNode }) { return <span className={styles.badge}>{children}</span>; }

export function NoteTemplates({ controller: c, mailer, edit }: { controller: DirectMailController; mailer: Mailer; edit: (patch: { note: string; signature: string }) => void }) {
  const t = useNoteTemplates(c, mailer, edit);
  return <><div className={styles.between}><div className={styles.row}>{t.templates.length ? <SelectField ariaLabel="Use a saved note template" value="none" options={[{ value: "none", label: "Use a saved note" }, ...t.templates.map((item) => ({ value: item.id, label: item.name }))]} onValueChange={t.apply} /> : <span className={styles.caption}>Save a note to reuse its structure.</span>}</div><Button variant="transparent" size="sm" disabled={!mailer.note.trim() || c.pending} onClick={() => t.setSaving(true)}>Save as template</Button></div>{t.error ? <p role="alert">{t.error}</p> : null}
    {t.saving ? <MailDialog title="Save note template" description="Reuse this wording in another mailer. Review the research, gift reference and final recipient message each time." close={() => t.setSaving(false)} busy={c.pending}><label className={styles.field}>Template name<input autoFocus maxLength={80} value={t.name} onChange={(e) => t.setName(e.target.value)} placeholder="e.g. A gift from their story" /></label><p className={`${styles.small} ${styles.subtle} mt-3`}>The current recipient name becomes a template field. Other account-specific wording stays unchanged for you to review.</p>{c.error ? <p role="alert">{c.error}</p> : null}<div className={styles.actions}><Button variant="transparent" size="md" onClick={() => t.setSaving(false)}>Cancel</Button><Button variant="primary" size="md" disabled={!t.name.trim() || c.pending} onClick={() => void t.save()}>Save template</Button></div></MailDialog> : null}</>;
}

export function MailerConnections({ mailer: m }: { mailer: Mailer }) {
  const site = m.assets?.find((asset) => asset.kind === "microsite");
  const destination = m.qr?.destinationUrl ?? site?.url;
  return <section className={styles.section}><div className={styles.between}><h2>Microsite & printed card</h2><MailBadge>{m.qr?.verifiedAt ? "QR verified" : m.qr?.printedUrl ? "QR assigned · Check pending" : "Assign during preparation"}</MailBadge></div>
    {destination ? <a className={`${styles.small} ${styles.textLink}`} href={destination} target="_blank" rel="noreferrer">{site?.title ?? "Recipient microsite"}<ExternalLink size={13} /></a> : <p className={`${styles.small} ${styles.subtle}`}>The agent will link the recipient’s microsite from this project.</p>}
    {destination ? <p className={`${styles.caption} mt-2`}>{m.qr?.destinationStatus === "published" ? "Microsite published" : m.qr?.destinationStatus === "draft" ? "Microsite draft · Publish before dispatch" : "Microsite publication not verified"}</p> : null}
    <p className={`${styles.small} ${styles.subtle} mt-2`}>Clue pairs a preprinted QR card with this recipient during preparation, then checks the destination before dispatch.</p>
    {m.qr?.printedUrl ? <a className={`${styles.caption} ${styles.textLink} mt-2`} href={m.qr.printedUrl} target="_blank" rel="noreferrer">Open printed QR link <ExternalLink size={12} /></a> : null}
    {m.qr?.verifiedAt ? <p className={styles.caption}>Verified {new Date(m.qr.verifiedAt).toLocaleString()}</p> : null}
  </section>;
}

function BudgetForm({ controller: c, projectId }: { controller: DirectMailController; projectId: string }) {
  const b = useGiftBudget(c, projectId);
  return <section className={styles.panel}><div className={styles.between}><h2>Gift recommendation budget</h2>{!b.editing ? <Button variant="transparent" size="sm" onClick={() => b.setEditing(true)}><Pencil size={13} />Edit budget</Button> : null}</div><p className={`${styles.small} ${styles.subtle} mt-2 mb-5`}>A preferred range gives the agent room to find a thoughtful gift. The upper limit is for the gift itself; delivery and preparation appear in each send approval.</p><div className={styles.budgetFields}>{([{ label: "Preferred from · USD", value: b.minimum, set: b.setMinimum }, { label: "Preferred to · USD", value: b.preferred, set: b.setPreferred }, { label: "Upper gift-price limit · USD", value: b.ceiling, set: b.setCeiling }]).map((field) => <label className={styles.field} key={field.label}>{field.label}<input type="number" min="0" step="0.01" disabled={!b.editing || c.pending} value={field.value} onChange={(e) => field.set(e.target.value)} /></label>)}</div><div className={`${styles.between} mt-4`}><span className={`${styles.small} ${styles.subtle} ${styles.row}`}><LockKeyhole size={14} />{b.saved?.locked && !b.editing ? "Budget locked · Can be edited" : "Save to confirm this guidance"}</span>{b.editing ? <Button variant="primary" size="md" disabled={!b.valid || c.pending} onClick={() => void b.save()}>Save & lock budget</Button> : null}</div><p className={`${styles.caption} mt-4`}>No credits are reserved. Every send still needs your approval of its full cost.</p></section>;
}

export function DirectMailSettings({ controller: c }: { controller: DirectMailController }) {
  const projects = Array.from(new Map(c.data!.mailers.map((m) => [m.projectId, { value: m.projectId, label: m.projectName }])).values());
  const [projectId, setProjectId] = useState(projects[0]?.value ?? "");
  const [topUp, setTopUp] = useState(false);
  return <><div className={styles.heading}><div><h1 className={styles.title}>Budgets & gifting credits</h1><p className={`${styles.small} ${styles.subtle}`}>Set the search range. Approve the spend when the mailer is ready.</p></div></div><div className={styles.settingsLayout}><div className={styles.stack}><SelectField ariaLabel="Budget project" value={projectId} options={projects} onValueChange={setProjectId} /><BudgetForm key={`${projectId}:${c.data!.giftBudgets?.find((b) => b.projectId === projectId)?.revision ?? 0}`} controller={c} projectId={projectId} /><section className={styles.section}><h2>Recent gifting activity</h2>{c.data!.creditEntries?.length ? <div className={styles.stack}>{c.data!.creditEntries.slice().reverse().slice(0, 12).map((entry) => <div className={styles.between} key={entry.id}><div><p>{entry.description}</p><time className={styles.caption}>{new Date(entry.at).toLocaleDateString()}</time></div><span>{entry.amountCents > 0 ? "+" : ""}{money(entry.amountCents)}</span></div>)}</div> : <p className={styles.subtle}>Approved mailers and credit top-ups will appear here.</p>}</section></div><aside className={styles.panel}><h2>Gifting credits</h2><p className={`${styles.creditBalance} mt-4`}>{money(c.data!.creditBalanceCents ?? 200000)}</p><p className={`${styles.small} ${styles.subtle} mt-1`}>Available · USD</p><Button variant="outline" size="md" className="mt-5" onClick={() => setTopUp(true)}>Add credits</Button><p className={`${styles.caption} mt-4`}>Separate from your platform subscription credits. A send approval deducts its estimate once.</p><p className={`${styles.caption} mt-3`}>Final preparation costs remain itemized. An amount above your approved limit comes back for approval.</p><Link href="/settings" className={`${styles.small} ${styles.textLink} mt-4`}>Workspace settings<ExternalLink size={13} /></Link></aside></div>
    {topUp ? <MailDialog title="Add gifting credits" description="This preview updates the local demo balance only. No payment method is charged." close={() => setTopUp(false)} busy={c.pending}><div className={styles.twoColumns}>{[100000, 200000].map((amount) => <Button key={amount} variant="outline" size="md" disabled={c.pending} onClick={async () => { if (await c.run(() => c.repository.topUp(amount))) setTopUp(false); }}><Check size={14} />Add {money(amount)}</Button>)}</div>{c.error ? <p role="alert">{c.error}</p> : null}</MailDialog> : null}</>;
}
