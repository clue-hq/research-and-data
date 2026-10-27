"use client";
import { useMaterialsEnabled } from "@/features/account-materials/hooks/use-materials-enabled";
import { materialGalleryHref } from "@/features/account-materials/model/materials";
import Link from "next/link";
import { selectedGift, type Mailer } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { MailStatus } from "./mail-ui";
import { MailBadge } from "./mail-context";
import styles from "./direct-mail.module.css";

function AssetCell({ mailer, kind }: { mailer: Mailer; kind: "microsite" | "linkedin-ad" | "email" }) {
  const assets = mailer.assets?.filter((a) => a.kind === kind) ?? [];
  if (!assets.length) return <span className={styles.caption}>Not linked</span>;
  return <div className={styles.stack}>{assets.map((a) => <div key={a.id}>{a.url ? <a className={styles.textLink} href={a.url} target="_blank" rel="noreferrer">{a.title} ↗</a> : <span>{a.title}</span>}<p className={`${styles.caption} mt-1`}>{a.scope === "account" ? "Account asset" : "Recipient asset"} · {a.status}</p></div>)}</div>;
}

export function ProjectMailPlan({ controller: c, projectId, compact = false }: { controller: DirectMailController; projectId?: string; compact?: boolean }) {
  const materialsEnabled=useMaterialsEnabled();
  const mailers = c.data?.mailers.filter((m) => m.projectId === projectId) ?? [];
  const visible = compact ? mailers.slice(0, 4) : mailers;
  if (!mailers.length) return <p className={styles.subtle}>No recipients are linked to this project yet.</p>;
  if(materialsEnabled) return <section className={styles.projectPlan} aria-label="Project materials"><h2 className="font-medium">Account materials</h2><p className={`${styles.small} ${styles.subtle} mt-2`}>Gifts, notes and landing pages are ready to review in Gallery.</p><div className={`${styles.stack} mt-4`}>{Array.from(new Map(mailers.map(m=>[m.accountId,m])).values()).slice(0,3).map(m=><div className={styles.between} key={m.accountId}><div><p>{m.recipient.company}</p><p className={styles.caption}>{mailers.filter(other=>other.accountId===m.accountId).length} {mailers.filter(other=>other.accountId===m.accountId).length===1?"recipient":"recipients"}</p></div><Link className={styles.textLink} href={materialGalleryHref(m.projectId,m.accountId)}>Review materials</Link></div>)}</div><Link className={`${styles.textLink} ${styles.small} mt-4`} href={materialGalleryHref(projectId!)}>Open Gallery</Link></section>;
  return <section className={compact ? styles.projectPlan : undefined} aria-label="Project campaign plan"><div className={styles.heading}><div><h2 className={compact ? "font-medium" : styles.title}>{compact ? "Campaign plan" : mailers[0].projectName}</h2><p className={`${styles.caption} mt-1`}>Gifts, messages and campaign assets for each recipient.</p></div><MailBadge>{mailers.length} mailers</MailBadge></div><div className={styles.tableWrap}><table className={`${styles.table} ${styles.planTable}`}><thead><tr><th>Recipient</th><th>Gift</th><th>Note</th><th>Microsite</th><th>LinkedIn ads</th><th>Email</th><th>Direct mail</th></tr></thead><tbody>{visible.map((m) => <tr key={m.id}><td><Link href={`/direct-mail/${m.id}`}>{m.recipient.name}</Link><p className={styles.caption}>{m.recipient.company}</p><p className={styles.caption}>{m.campaign}</p></td><td><Link href={`/direct-mail/${m.id}`}>{selectedGift(m)?.name ?? "Review 3 options"}</Link></td><td><Link href={`/direct-mail/${m.id}`}>Review note</Link><p className={styles.caption}>{m.approval ? "Approved copy" : "Prepared for review"}</p></td><td><AssetCell mailer={m} kind="microsite" /></td><td><AssetCell mailer={m} kind="linkedin-ad" /></td><td><AssetCell mailer={m} kind="email" /></td><td><Link href={`/direct-mail/${m.id}`}><MailStatus stage={m.stage} /></Link></td></tr>)}</tbody></table></div><div className={`${styles.between} mt-3`}><p className={styles.caption}>Each channel keeps its own review and approval.</p>{compact ? <Link href={`/direct-mail/project?project=${encodeURIComponent(projectId!)}`} className={`${styles.small} ${styles.textLink}`}>Open campaign table ↗</Link> : <Link className={`${styles.small} ${styles.textLink}`} href={`/direct-mail?project=${encodeURIComponent(projectId!)}`}>View mailers ↗</Link>}</div></section>;
}
