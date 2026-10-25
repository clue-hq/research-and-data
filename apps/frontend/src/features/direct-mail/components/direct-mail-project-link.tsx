"use client";
import Link from "next/link";
import { ArrowRight, Mail } from "lucide-react";
import { useDirectMail } from "../hooks/use-direct-mail";
import { isDraft, selectedGift } from "../model/direct-mail";
import { MailStatus } from "./mail-ui";
import styles from "./direct-mail.module.css";

/** A linked mailer is a physical-send record, not a design-editor artifact. */
export function DirectMailProjectLink({ projectId, threadId }: { projectId?: string; threadId?: string | null }) {
  const c = useDirectMail();
  if (!c.enabled || !projectId || !c.data) return null;
  const mailers = c.data.mailers.filter((m) => m.projectId === projectId && (!threadId || m.threadId === threadId));
  if (!mailers.length) return null;
  const first = mailers.find(isDraft) ?? mailers[0];
  const gift = selectedGift(first);
  return <section className={styles.projectLink} aria-label="Project direct mail"><div className={styles.between}><span className={styles.row}><Mail size={16} strokeWidth={1.5} /><strong className="font-medium">Direct mail</strong></span><span className={styles.caption}>{mailers.length} mailers</span></div><Link href={`/direct-mail/${first.id}`}><div><span>{first.recipient.name}</span><p className={`${styles.small} ${styles.subtle}`}>{gift?.name ?? "Three gift recommendations ready for review"}</p></div><div className={styles.row}><MailStatus stage={first.stage} /><ArrowRight size={14} /></div></Link><Link href={`/direct-mail?project=${encodeURIComponent(projectId)}`} className={`${styles.small} ${styles.subtle}`}>View all project mailers<ArrowRight size={14} /></Link></section>;
}
