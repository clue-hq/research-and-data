"use client";
import Link from "next/link";
import { ChevronLeft, ChevronRight, Mail, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import { estimate, isDraft, money, selectedGift } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { queueTabs, useMailerQueue } from "../hooks/use-mailer-queue";
import { useMailerCampaign } from "../hooks/use-mailer-campaign";
import { ApprovalDialog, MailDialog, MailStatus } from "./mail-ui";
import { HARVEY_PROJECT_ID, harveyAccounts } from "../model/harvey-demo-context";
import { HarveyMaterials } from "./harvey-materials";
import styles from "./direct-mail.module.css";

export function MailerQueue({ controller: c }: { controller: DirectMailController }) {
  const q = useMailerQueue(c);
  return <><div className={styles.heading}><div><h1 className={styles.title}>Direct mail</h1><p className={`${styles.small} ${styles.subtle}`}>Review gifts, approve mailers and follow every delivery.</p></div><div className={styles.row}><Link className={`${styles.small} ${styles.textLink}`} href="/direct-mail/settings">Budgets & credits</Link><Link className={`${styles.small} ${styles.textLink}`} href="/direct-mail/library">Cards, notes & handwriting</Link><Button variant="primary" size="md" onClick={() => q.setCreating(true)}><Plus size={16} />New campaign</Button></div></div>
    <nav className={styles.tabs} aria-label="Mailer status">{queueTabs.map((tab) => <button className={styles.tab} aria-current={q.tab === tab.id ? "page" : undefined} key={tab.id} onClick={() => q.filter("status", tab.id)}>{tab.label}</button>)}</nav>
    <div className={styles.toolbar}><label className={styles.search}><Search size={16} className={styles.subtle} /><input aria-label="Search mailers" placeholder="Search recipients or companies" value={q.search} onChange={(e) => q.filter("q", e.target.value)} /></label><div className={styles.row}><SelectField ariaLabel="Filter by project" value={q.project} options={[{ value: "all", label: "All projects" }, ...q.projects]} onValueChange={(value) => q.filter("project", value)} /><SelectField ariaLabel="Filter by campaign" value={q.campaign} options={[{ value: "all", label: "All campaigns" }, ...q.campaigns]} onValueChange={(value) => q.filter("campaign", value)} /><SelectField ariaLabel="Sort mailers" value={q.sort} options={[{ value: "recent", label: "Recently updated" }, { value: "name", label: "Recipient name" }]} onValueChange={(value) => q.filter("sort", value)} /></div></div>
    {q.selected.length > 0 ? <div className={`${styles.notice} ${styles.between}`}><div>{q.selected.length} selected <span className={`${styles.small} ${styles.subtle}`}>· {q.ready.length} ready to approve{q.selected.length > q.ready.length ? ` · ${q.selected.length - q.ready.length} excluded until reviewed and ready` : ""}</span></div><Button variant="primary" size="md" disabled={!q.ready.length || c.pending} onClick={() => q.setApproval(q.ready)}>Approve {q.ready.length} · {money(q.total)}</Button></div> : null}
    {q.results.length ? <div className={styles.notice} role="status">{q.results.map((result) => <p key={result.id}>{c.data?.mailers.find((m) => m.id === result.id)?.recipient.name}: {result.message}</p>)}<Button variant="transparent" size="sm" onClick={() => q.setResults([])}>Dismiss</Button></div> : null}
    {q.visible.length ? <><div className={styles.tableWrap}><table className={`${styles.table} ${styles.mailerTable}`}><colgroup><col style={{width: 28}}/><col style={{width: "22%"}}/><col style={{width: "23%"}}/><col style={{width: "14%"}}/><col style={{width: "16%"}}/><col style={{width: "11%"}}/><col style={{width: "10%"}}/></colgroup><thead><tr><th><input type="checkbox" aria-label="Select all mailers on this page" checked={q.selected.length === q.visible.length} onChange={q.toggleAll} /></th><th>Account & recipient</th><th>Gift & card</th><th>Materials</th><th>Status</th><th>Total cost</th><th><span className="sr-only">Open mailer</span></th></tr></thead><tbody>{q.visible.map((m) => {
      const gift = selectedGift(m);
      return <tr key={m.id}><td><input type="checkbox" aria-label={`Select ${m.recipient.name}`} checked={q.selected.some((item) => item.id === m.id)} onChange={() => q.toggle(m.id)} /></td><td><div className={styles.person}><span className={styles.companyLogo}>{harveyAccounts[m.accountId] ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={harveyAccounts[m.accountId].logo} alt={`${m.recipient.company} logo`} />
      ) : m.recipient.initials}</span><div><Link href={q.recordHref(m.id)}>{m.recipient.company}</Link><p className={`${styles.small} ${styles.subtle}`}>{m.recipient.name}</p></div></div></td><td><div className={styles.person}>{gift ? <>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={gift.image} alt="" className={styles.thumb} /><div>{gift.name}<p className={styles.caption}>{m.approval ? "Approved handwritten card" : "Personal handwritten card"}</p></div></> : <div><span>3 gifts to consider</span><p className={styles.caption}>{m.campaign}</p></div>}</div></td><td><HarveyMaterials accountId={m.accountId} compact /></td><td><MailStatus stage={m.stage} />{m.exception ? <p className={styles.caption}>{m.exception.title}</p> : !isDraft(m) ? <p className={styles.caption}>{m.deliveryEstimate}</p> : null}</td><td>{!gift ? <span className={styles.subtle}>Select a gift</span> : <>{money(m.approval?.estimatedCents ?? estimate(m))}<p className={styles.caption}>{m.approval ? "Approved estimate" : "Estimated"}</p></>}</td><td><Link className={styles.row} href={q.recordHref(m.id)}>{isDraft(m) ? "Review" : "Track"}</Link></td></tr>;
    })}</tbody></table></div><div className={styles.pagination}><span>{q.matching.length} {q.matching.length === 1 ? "mailer" : "mailers"}</span><div className={styles.row}><span>Page {q.currentPage} of {q.pages}</span><Button variant="transparent" size="icon-sm" aria-label="Previous page" disabled={q.currentPage <= 1} onClick={() => q.filter("page", String(q.currentPage - 1))}><ChevronLeft size={16} /></Button><Button variant="transparent" size="icon-sm" aria-label="Next page" disabled={q.currentPage >= q.pages} onClick={() => q.filter("page", String(q.currentPage + 1))}><ChevronRight size={16} /></Button></div></div></> : <div className={styles.empty}><Mail size={24} strokeWidth={1.25} /><h2>No mailers here yet</h2><p className={styles.subtle}>Try another filter or start a campaign with recipients from a project.</p><Button variant="outline" size="md" onClick={() => q.setCreating(true)}>New campaign</Button></div>}
    {q.project === HARVEY_PROJECT_ID ? <HarveyMaterials /> : null}
    {q.approval ? <ApprovalDialog mailers={q.approval} busy={c.pending} close={() => q.setApproval(null)} approve={() => void q.approve()} error={c.error} /> : null}
    {q.creating ? <CampaignDialog controller={c} close={() => q.setCreating(false)} /> : null}
  </>;
}
function CampaignDialog({ controller: c, close }: { controller: DirectMailController; close: () => void }) {
  const f = useMailerCampaign(c, close);
  return <MailDialog title="New direct mail campaign" description="Choose a project and recipients. Each person gets a separate gift and note review before approval." close={close} busy={c.pending}>
    <form onSubmit={(event) => { event.preventDefault(); void f.create(); }}><div className={styles.stack}>
      <label className={styles.field}>Campaign name<input required autoFocus maxLength={100} placeholder="e.g. Fall account outreach" value={f.name} onChange={(e) => f.setName(e.target.value)} /></label>
      <div className={styles.field}><label htmlFor="campaign-project">Project</label><SelectField id="campaign-project" ariaLabel="Campaign project" value={f.projectId} options={f.projects} onValueChange={f.changeProject} /></div>
      <fieldset><legend className={`${styles.small} mb-2`}>Recipients · {f.recipients.length} selected</legend><div className={styles.recipientList}>{f.people.map((m) => <label className={styles.check} key={m.contactId}><input type="checkbox" checked={f.recipients.includes(m.contactId)} onChange={() => f.toggle(m.contactId)} /><span>{m.recipient.name}<span className={`${styles.subtle} block`}>{m.recipient.company}</span></span></label>)}</div></fieldset>
      <div className={styles.twoColumns}><label className={styles.field}>Spending limit per recipient · USD<input required type="number" min="1" max="10000" step="0.01" value={f.budget} onChange={(e) => f.setBudget(e.target.value)} /></label><div className={styles.field}><span>Default card</span><SelectField ariaLabel="Campaign card" value={f.cardId} options={c.data!.cards.map((card) => ({ value: card.id, label: card.name }))} onValueChange={f.setCardId} /></div></div>
      <div className={styles.field}><span>Default handwriting</span><SelectField ariaLabel="Campaign handwriting" value={f.styleId} options={c.data!.styles.map((style) => ({ value: style.id, label: style.name }))} onValueChange={f.setStyleId} /></div>
      {c.error ? <p role="alert">{c.error}</p> : null}
    </div><div className={styles.actions}><Button variant="transparent" size="md" disabled={c.pending} onClick={close}>Cancel</Button><Button type="submit" variant="primary" size="md" disabled={!f.valid || c.pending}>{c.pending ? "Creating…" : "Create campaign"}</Button></div></form>
  </MailDialog>;
}
