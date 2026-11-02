"use client";
import Link from "next/link";
import { useState } from "react";
import { DEMO_ID } from "../model/recording-demo-context";
import { ArrowLeft, ArrowUpRight, Check, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { money, noteFits, noteNeedsGiftUpdate, selectedGift, type GiftInsight, type Mailer } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { useMailerEditor } from "../hooks/use-mailer-editor";
import { ApprovalDialog, CostBreakdown, MailDialog, MailStatus } from "./mail-ui";
import { ProductImage } from "./product-image";
import { MailerPreview } from "./mailer-preview";
import { MailerConnections, NoteTemplates } from "./mail-context";
import { GiftResearch, GiftInsightDialog, GiftAlternatives } from "./gift-research";
import styles from "./direct-mail.module.css";

export function MailerReview({ controller: c, saved, queueHref, initialStep = 0, onBack, onOpenPage }: { controller: DirectMailController; saved: Mailer; queueHref: string; initialStep?:number; onBack?:()=>void; onOpenPage?:()=>void }) {
  const e = useMailerEditor(c, saved, initialStep), m = e.mailer;
  const recordingDemo = m.id === DEMO_ID;
  const [openInsight, setOpenInsight] = useState<GiftInsight | null>(null);
  const requestAlternatives = () => { e.setFeedback(""); e.setRequest("gifts"); };
  const card = c.data!.cards.find((item) => item.id === m.cardId), style = c.data!.styles.find((item) => item.id === m.styleId), gift = selectedGift(m);
  return <><div className={styles.heading}><div><div className={`${styles.row} mb-1`}><h1 className={styles.title}>{m.recipient.name}</h1><MailStatus stage={saved.stage} /></div><p className={`${styles.small} ${styles.subtle}`}>{m.recipient.role} · {m.recipient.company}</p></div><div className={styles.row}><span className={styles.caption}>{e.dirty ? "Unsaved changes" : "Saved"}</span><Button variant="outline" size="md" disabled={!e.dirty || c.pending || e.changedElsewhere} onClick={() => void e.save()}>{c.pending ? "Saving…" : "Save draft"}</Button></div></div>
    {e.changedElsewhere ? <div className={styles.notice} role="alert">This mailer changed in another view. Your unsaved edits are still here. <Button variant="transparent" size="sm" onClick={e.discard}>Discard edits and load latest</Button></div> : null}
    {e.recoveryError ? <div className={styles.notice} role="alert">{e.recoveryError}</div> : null}
    <nav className={styles.tabs} aria-label="Mailer review steps">{["Choose a gift", "Card & note", "Review & approve"].map((label, index) => <button key={label} className={styles.tab} aria-current={e.step === index ? "page" : undefined} disabled={c.pending || e.changedElsewhere} onClick={() => void e.go(index)}><span className={styles.caption}>{index + 1}</span> {label}</button>)}</nav>
    <div className={styles.reviewLayout}><div>
      {e.step === 0 ? <>
        {m.giftInsights?.length ? <GiftResearch name={m.recipient.name.split(" ")[0]} insights={m.giftInsights} onOpen={setOpenInsight} /> : <section className={styles.evidence} aria-label="Why these gifts"><h2 className={styles.evidenceTitle}>Why these gifts</h2><p className={styles.evidenceSummary}>{m.insight.detail}</p><details><summary>{m.insight.source}</summary><blockquote>{m.insight.excerpt}</blockquote><p className={`${styles.caption} mt-2`}>Research date: {m.insight.date}</p>{m.insight.sourceUrl ? <a className={`${styles.small} ${styles.textLink}`} href={m.insight.sourceUrl} target="_blank" rel="noreferrer">Open research source ↗</a> : null}</details></section>}
        <div className={`${styles.between} mb-4`}><h2 className="font-medium">Three gifts for {m.recipient.name.split(" ")[0]}</h2>{recordingDemo ? <span className={styles.caption}>Retailer prices checked Nov 2, 2026</span> : <button className={`${styles.small} ${styles.textLink}`} onClick={() => e.setRequest("gifts")}>Give the agent feedback</button>}</div>
        {m.proposalRequest ? <div className={styles.notice}><p className="font-medium">Recommendation changes requested</p><p className={`${styles.small} ${styles.subtle} mt-1`}>{m.proposalRequest.feedback || "Find another thoughtful direction for this recipient."} Your current gift and note are preserved.</p><div className={`${styles.row} mt-3`}>{m.giftInsights?.length ? <span className={styles.caption}>Request saved locally. Live gift search is not connected in this preview.</span> : <Button variant="outline" size="sm" disabled={c.pending} onClick={() => void e.resolveRequest(true)}>Load sample recommendations</Button>}<Button variant="transparent" size="sm" disabled={c.pending} onClick={() => void e.resolveRequest(false)}>Keep current options</Button></div></div> : null}
        <div className={styles.gifts} role="radiogroup" aria-label="Gift options">{m.gifts.map((g) => {
          const selected = m.selectedGiftId === g.id;
          const optionId = `gift-${m.id}-${g.id}`;
          const insight = m.giftInsights?.find(item => item.id === g.insightId);
          return <article key={g.id} className={styles.giftContainer} data-selected={selected} data-disabled={!g.available || c.pending}>
            <label htmlFor={optionId} className={styles.giftSelect}><span className="sr-only">Select {g.name}</span></label>
            <div className={styles.giftPhoto}><ProductImage src={g.image} alt={g.name} />{g.recommended ? <Badge className={styles.recommended}>Recommended</Badge> : null}</div>
            {g.productUrl ? <a className={styles.giftMerchant} href={g.productUrl} target="_blank" rel="noreferrer" aria-label={`View ${g.name} at ${g.merchant}`}>View at {g.merchant}<ArrowUpRight size={14} aria-hidden="true" /></a> : <span className={styles.giftMerchant}>Merchant link pending</span>}
            <div className={styles.giftBody}>
              <h3 id={`${optionId}-name`} className={styles.giftName}>{g.name}</h3>
              <p className={styles.giftVariant}>{g.variant}</p>
              {insight ? <button className={styles.giftBasis} onClick={() => setOpenInsight(insight)} aria-label={`Research behind ${g.name}`}>{insight.title}<ArrowUpRight size={12} aria-hidden="true" /></button> : null}
              <p className={styles.giftReason}>{g.rationale}</p>
              <div className={styles.giftChoice}><span className={styles.giftPrice}>{money(g.priceCents)}</span><span className={styles.giftSelection}>{!g.available ? "Unavailable" : selected ? "Selected" : "Select gift"}<input id={optionId} type="radio" name={`gift-${m.id}`} aria-labelledby={`${optionId}-name`} checked={selected} disabled={!g.available || c.pending} onChange={() => e.edit({ selectedGiftId: g.id })} /></span></div>
              <p className={styles.giftAvailability}>{g.arrival}</p>
            </div>
          </article>;
        })}</div><p className={`${styles.caption} mt-3`}>Gift prices in USD. Shipping and preparation shown at review.</p>
        {m.alternativeGifts?.length ? <GiftAlternatives mailer={m} disabled={c.pending || e.changedElsewhere} error={c.error} onSelect={e.selectAlternative} onRequest={requestAlternatives} /> : null}
      </> : null}
      {e.step === 1 ? <div className={styles.stack}><div><h2 className="font-medium mb-1">Make the note personal</h2><p className={`${styles.small} ${styles.subtle}`}>Choose the card and handwriting, then make the message your own.</p></div><div className={styles.twoColumns}>
        <div className={styles.field}><label htmlFor="mailer-card">Card</label><SelectField id="mailer-card" ariaLabel="Card design" value={m.cardId} options={c.data!.cards.map((item) => ({ value: item.id, label: `${item.name}${item.productionReady ? "" : " · Pending validation"}` }))} onValueChange={(value) => e.edit({ cardId: value })} /></div>
        <div className={styles.field}><label htmlFor="mailer-style">Handwriting</label><SelectField id="mailer-style" ariaLabel="Handwriting style" value={m.styleId} options={c.data!.styles.map((item) => ({ value: item.id, label: `${item.name}${item.productionReady ? "" : " · Pending validation"}` }))} onValueChange={(value) => e.edit({ styleId: value })} /></div></div>
        <Link className={`${styles.small} ${styles.textLink}`} href="/direct-mail/library" target="_blank">Manage cards & handwriting ↗</Link>
        {gift?.suggestedNote && m.note !== gift.suggestedNote ? <div className={styles.notice}><p className={styles.small}>{noteNeedsGiftUpdate(m) ? "You changed the gift. Update the message to match, or write your own below." : "A suggested note is available for this gift. Your edits have been kept."}</p><Button variant="outline" size="sm" className="mt-3" onClick={() => e.edit({ note: gift.suggestedNote! })}>Use note for {gift.name}</Button></div> : null}
        <NoteTemplates controller={c} mailer={m} edit={e.edit} />
        <label className={styles.field}>Your note<textarea rows={8} value={m.note} maxLength={1200} onChange={(event) => e.edit({ note: event.target.value })} aria-describedby="note-fit" /></label><p id="note-fit" className={`${styles.small} ${styles.subtle}`} aria-live="polite">{noteFits(m.note, m.signature, card, style) ? "Fits the card’s writing area." : "Adjust the message to fit the writing area and supported handwriting characters."} · {m.note.length} characters</p>
        <label className={styles.field}>Signature<textarea rows={2} value={m.signature} maxLength={100} onChange={(event) => e.edit({ signature: event.target.value })} /></label>
        <p className={styles.caption}>The note will be written in pen by Clue’s handwriting system. This preview shows the layout and handwriting style.</p>
        <MailerConnections mailer={m} onOpenPage={onOpenPage} />
      </div> : null}
      {e.step === 2 ? <><section className={styles.section}><h2>Receiving address</h2><p className={`${styles.small} ${styles.subtle} mb-4`}>{recordingDemo ? "Public Minneapolis office address from U.S. Bancorp’s website. Recipient acceptance and gifting policy have not been verified; use this address for the simulated flow only." : "The finished package goes here after preparation at Clue."}</p><div className={styles.stack}><div className={styles.twoColumns}>{([['name','Recipient'],['company','Company'],['line1','Street address'],['line2','Suite, floor or unit'],['city','City'],['region','State / region'],['postalCode','Postal code'],['country','Country']] as const).map(([key, label]) => <label className={styles.field} key={key}>{label}<input value={m.address[key]} onChange={(event) => e.edit({ address: { ...m.address, [key]: event.target.value }, addressConfirmed: false })} /></label>)}</div><label className={styles.check}><input type="checkbox" checked={m.addressConfirmed} onChange={(event) => e.edit({ addressConfirmed: event.target.checked })} /><span>{recordingDemo ? "Use this public office address." : "I’ve confirmed this recipient can receive a package at this address."}</span></label></div></section>
        <section className={styles.section}><h2>Cost estimate · USD</h2>{recordingDemo ? <p className={`${styles.caption} mt-2`}>Gift price from the retailer. Shipping, preparation and tax below are illustrative estimates, not a merchant quote.</p> : null}<div className="mt-4"><CostBreakdown mailer={m} /></div><label className={`${styles.field} mt-5`}>Maximum spend for this mailer · USD<input type="number" min={0} max={100000} step="0.01" value={m.budgetCents / 100} onChange={(event) => e.edit({ budgetCents: Math.max(0, Math.round(Number(event.target.value) * 100)) })} /></label></section>
        <section className={styles.section}><h2>Before you approve</h2>{e.issues.length ? <ul className={`${styles.small} ${styles.subtle} list-disc pl-5 space-y-1`}>{e.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p className={`${styles.small} ${styles.row}`}><Check size={16} />Gift, note, address and spending limit are ready.</p>}<p className={`${styles.small} ${styles.subtle} mt-4`}>After approval, Clue orders the gift, inspects it, adds your handwritten card and repackages it. It ships after the quality check. Package photos appear in tracking.</p></section>
      </> : null}
      <div className={styles.actions}>{e.step > 0 ? <Button variant="transparent" size="md" disabled={c.pending} onClick={() => void e.go(e.step - 1)}><ArrowLeft size={14} />Back</Button> : onBack ? <Button variant="transparent" size="sm" onClick={onBack}>Back to materials</Button> : <Link className={`${styles.small} ${styles.subtle}`} href={queueHref}>Back to all mailers</Link>}
        {e.step < 2 ? <Button variant="primary" size="md" disabled={c.pending || e.changedElsewhere || (e.step === 0 && !gift)} onClick={() => void e.go(e.step + 1)}>{e.step === 0 ? "Continue to card & note" : "Review mailer"}<ChevronRight size={14} /></Button> : <div className={styles.row}><Button variant="outline" size="md" disabled={c.pending || e.issues.length > 0 || e.changedElsewhere || (!e.dirty && saved.stage === "ready")} onClick={() => void e.review(false)}>{!e.dirty && saved.stage === "ready" ? "Marked reviewed" : "Mark reviewed"}</Button><Button variant="primary" size="md" disabled={c.pending || e.issues.length > 0 || e.changedElsewhere} onClick={() => void e.review(true)}>Approve mailer</Button></div>}
      </div>
    </div><aside className={styles.previewRail} aria-label="Mailer preview"><div className={styles.panel}><h2>Your mailer</h2>{gift ? <>
      <ProductImage src={gift.image} alt={gift.name} className={styles.previewGift} /><p>{gift.name}</p><p className={styles.caption}>{gift.variant}</p></> : <p className={`${styles.small} ${styles.subtle} py-5`}>Select a gift to complete this mailer.</p>}<div className="mt-4"><MailerPreview card={card} style={style} note={m.note} signature={m.signature} /></div></div><div className={`${styles.small} ${styles.subtle}`}><p>{m.campaign}</p><p className="mt-1">Estimated arrival: {m.deliveryEstimate}</p></div></aside></div>
    {openInsight ? <GiftInsightDialog insight={openInsight} close={() => setOpenInsight(null)} /> : null}
    {e.approval ? <ApprovalDialog mailers={[e.approval]} busy={c.pending} close={() => e.setApproval(null)} approve={() => void e.approve()} error={e.approvalError ?? c.error} /> : null}
    {e.request ? <MailDialog title="Find a different gift" description="Describe the direction, budget or product you have in mind. Your selected gift and note stay intact while you consider alternatives." close={() => e.setRequest(null)} busy={c.pending}><label className={styles.field}>What should change?<textarea autoFocus rows={4} value={e.feedback} maxLength={1000} placeholder="e.g. Keep the current gift. Find two practical alternatives linked to a different insight, under $100." onChange={(event) => e.setFeedback(event.target.value)} /></label><p className={`${styles.caption} mt-3`}>Your request is saved in this local preview. A live agent search is not connected yet.</p>{c.error ? <p role="alert">{c.error}</p> : null}<div className={styles.actions}><Button variant="transparent" size="md" onClick={() => e.setRequest(null)} disabled={c.pending}>Cancel</Button><Button variant="primary" size="md" disabled={c.pending || !e.feedback.trim()} onClick={() => void e.submitRequest()}>Save request</Button></div></MailDialog> : null}
  </>;
}
