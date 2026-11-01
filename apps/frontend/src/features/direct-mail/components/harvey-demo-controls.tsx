"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { HARVEY_RESEARCH_URL, harveyNextLabel } from "../model/harvey-demo-context";
import type { Mailer } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { MailDialog } from "./mail-ui";
import styles from "./direct-mail.module.css";

export function HarveyDemoControls({ mailer, controller: c, onReset }: { mailer: Mailer; controller: DirectMailController; onReset: () => void }) {
  const [reset, setReset] = useState(false);
  const next = harveyNextLabel[mailer.stage];
  return <>
    <section className={`${styles.notice} ${styles.between} mb-6`} aria-label="Recording demo controls">
      <div><p className={styles.small}>Recording demo · Order and delivery updates are simulated</p><a href={HARVEY_RESEARCH_URL} target="_blank" rel="noreferrer" className={`${styles.caption} ${styles.textLink}`}>Benesch research in the deployed app</a></div>
      <div className={styles.row}>
        {next && c.repository.advanceDemo ? <Button size="sm" variant="outline" disabled={c.pending} onClick={() => void c.run(() => c.repository.advanceDemo!(mailer.id, mailer.revision))}>{next}</Button> : null}
        <Button size="sm" variant="transparent" disabled={c.pending} onClick={() => setReset(true)}>Reset demo</Button>
      </div>
    </section>
    {reset ? <MailDialog title="Reset this recording?" description="Restore Jason’s original gift options and note, clear this demo’s tracking, and restore its demo credits. Other mailers stay unchanged." close={() => setReset(false)} busy={c.pending}>
      <div className={styles.actions}><Button variant="transparent" size="md" onClick={() => setReset(false)}>Keep current take</Button><Button variant="primary" size="md" disabled={c.pending} onClick={async () => { if (await c.run(() => c.repository.resetDemo!(mailer.id, mailer.revision))) { setReset(false); onReset(); } }}>Reset recording</Button></div>
    </MailDialog> : null}
  </>;
}
