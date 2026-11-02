"use client";
import { useState } from "react";
import { Menu } from "@base-ui/react/menu";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DEMO_RESEARCH_URL, demoNextLabel } from "../model/recording-demo-context";
import type { Mailer } from "../model/direct-mail";
import type { DirectMailController } from "../hooks/use-direct-mail";
import { MailDialog } from "./mail-ui";
import styles from "./direct-mail.module.css";

export function RecordingControls({ mailer, controller: c, onReset }: { mailer: Mailer; controller: DirectMailController; onReset: () => void }) {
  const [reset, setReset] = useState(false);
  const next = demoNextLabel[mailer.stage];
  return <>
    <Menu.Root>
      <Menu.Trigger render={<Button size="icon-sm" variant="transparent" />} aria-label="Recording controls"><MoreHorizontal size={16} /></Menu.Trigger>
      <Menu.Portal><Menu.Positioner sideOffset={6} align="end" className={styles.demoMenuPositioner}><Menu.Popup className={styles.demoMenu}>
        <p className={`${styles.caption} px-2 py-2`}>Local demo · Orders and delivery are simulated.</p>
        {next && c.repository.advanceDemo ? <Menu.Item className={styles.demoMenuItem} disabled={c.pending} onClick={() => void c.run(() => c.repository.advanceDemo!(mailer.id, mailer.revision))}>{next}</Menu.Item> : null}
        <Menu.Item className={styles.demoMenuItem} render={<a href={DEMO_RESEARCH_URL} target="_blank" rel="noreferrer" />}>Open deployed research</Menu.Item>
        <Menu.Item className={styles.demoMenuItem} disabled={c.pending} onClick={() => setReset(true)}>Reset demo</Menu.Item>
      </Menu.Popup></Menu.Positioner></Menu.Portal>
    </Menu.Root>
    {reset ? <MailDialog title="Reset this recording?" description="Restore Ann’s original gift options and note, clear this demo’s tracking, and restore its demo credits. Other mailers stay unchanged." close={() => setReset(false)} busy={c.pending}>
      <div className={styles.actions}><Button variant="transparent" size="md" onClick={() => setReset(false)}>Keep current take</Button><Button variant="primary" size="md" disabled={c.pending} onClick={async () => { if (await c.run(() => c.repository.resetDemo!(mailer.id, mailer.revision))) { setReset(false); onReset(); } }}>Reset recording</Button></div>
    </MailDialog> : null}
  </>;
}
