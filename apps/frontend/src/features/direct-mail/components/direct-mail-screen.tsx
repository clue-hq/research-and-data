"use client";
import Link from "next/link";
import { MaterialsBrowser } from "@/features/account-materials/components/materials-browser";
import { WALKTHROUGH_CAMPAIGN } from "@/features/account-materials/model/outreach";
import { useMaterialsEnabled } from "@/features/account-materials/hooks/use-materials-enabled";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { ApplicationShell } from "@/components/shell/application-shell";
import { Button } from "@/components/ui/button";
import { useDirectMail } from "../hooks/use-direct-mail";
import { isDraft } from "../model/direct-mail";
import { MailerQueue } from "./mailer-queue";
import { MailerReview } from "./mailer-review";
import { MailerTracking } from "./mailer-tracking";
import { CardLibrary } from "./card-library";
import { DirectMailSettings } from "./mail-context";
import { ProjectMailPlan } from "./project-mail-plan";
import { MailerAccountContext } from "@/features/orchestration/components/mailer-context";
import styles from "./direct-mail.module.css";

export function DirectMailScreen({ recordId }: { recordId?: string }) {
  const c = useDirectMail();
  const materialsEnabled=useMaterialsEnabled();
  const params = useSearchParams();
  const queueHref = `/direct-mail${params.size ? `?${params}` : ""}`;
  const mailer = c.data?.mailers.find((m) => m.id === recordId);
  const peers = c.data?.mailers.filter((m) => m.projectId === mailer?.projectId) ?? [];
  const index = peers.findIndex((m) => m.id === recordId);
  const previous = peers[index - 1], next = peers[index + 1];
  if(materialsEnabled && (!recordId || mailer?.campaignId===WALKTHROUGH_CAMPAIGN)) return <ApplicationShell activeHref="/direct-mail"><MaterialsBrowser initialAccount={mailer?.accountId} initialRecipient={mailer?.id} title="Direct mail"/></ApplicationShell>;
  return <ApplicationShell activeHref="/direct-mail"><main className={styles.screen}><header className={styles.header}>{recordId ? <Link className={styles.back} href={queueHref}><ArrowLeft size={14} />Direct mail</Link> : <span className={styles.headerTitle}>Direct mail</span>}{mailer ? <div className={styles.row}><Link className={`${styles.small} ${styles.subtle}`} href={`/projects/${mailer.projectId}/chats/${mailer.threadId}`}>{mailer.projectName}</Link>{previous ? <Link aria-label="Previous recipient in project" href={`/direct-mail/${previous.id}?${params}`}><ChevronLeft size={16} /></Link> : null}{next ? <Link aria-label="Next recipient in project" href={`/direct-mail/${next.id}?${params}`}><ChevronRight size={16} /></Link> : null}</div> : null}</header><div className={styles.body}><div className={styles.content}>
    {!c.enabled ? <div className={styles.empty}><h1 className={styles.title}>Direct Mail isn’t connected yet</h1><p className={styles.subtle}>This workspace will show mailers when the Direct Mail service is connected.</p></div> : <>
      {c.error ? <div className={`${styles.notice} ${styles.error}`} role="alert">{c.error} <Button variant="transparent" size="sm" onClick={() => void c.reload()}>Reload data</Button></div> : null}
      {c.data?.pilotLoadError ? <div className={styles.notice} role="status">{c.data.pilotLoadError} <Button variant="transparent" size="sm" onClick={() => void c.reload()}>Retry pilot import</Button></div> : null}
      {mailer ? <MailerAccountContext mailerId={mailer.id} /> : null}
      {!c.data ? !c.error ? <p className={`${styles.subtle} py-12`} role="status">Loading mailers…</p> : null : !recordId ? <MailerQueue controller={c} /> : recordId === "library" ? <CardLibrary controller={c} /> : recordId === "settings" ? <DirectMailSettings controller={c} /> : recordId === "project" ? <ProjectMailPlan controller={c} projectId={params.get("project") ?? c.data.mailers[0]?.projectId} /> : mailer ? isDraft(mailer) ? <MailerReview key={mailer.id} controller={c} saved={mailer} queueHref={queueHref} /> : <MailerTracking controller={c} mailer={mailer} /> : <div className={styles.empty}><h1 className={styles.title}>Mailer not found</h1><Link href="/direct-mail">Return to direct mail</Link></div>}
    </>}
  </div></div></main></ApplicationShell>;
}
