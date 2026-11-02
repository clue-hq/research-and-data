"use client";
import { useState } from "react";
import { ExternalLink, Globe, ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { demoMaterials } from "../model/recording-demo-context";
import { MailDialog } from "./mail-ui";
import styles from "./direct-mail.module.css";

type Material = typeof demoMaterials[number];
/** Read-only captures of the customer's existing designs. Approval stays in its own flow. */
export function CampaignMaterials({ accountId, compact = false }: { accountId?: string; compact?: boolean }) {
  const [selected, setSelected] = useState<Material | null>(null);
  const materials = demoMaterials.filter(m => !accountId || m.accountId === accountId);
  if (!materials.length) return null;
  return <>
    {compact ? <div className={styles.assetLinks}>{materials.map(m => <button key={m.id} className={styles.assetChip} data-type={m.type} onClick={() => setSelected(m)} aria-label={`Preview ${m.account} ${m.type.toLowerCase()}`}>{m.type === "Landing page" ? <Globe size={12} /> : <ImageIcon size={12} />}{m.type}</button>)}</div> : <section className={styles.campaignMaterials}>
      <div className={styles.heading}><div><h2 className={styles.sectionTitle}>Campaign materials</h2><p className={styles.caption}>Account-specific pages and ads from your Illumio project.</p></div><span className={styles.caption}>{materials.length} materials</span></div>
      <div className={styles.materialGrid}>{materials.map(m => <button className={styles.materialCard} key={m.id} onClick={() => setSelected(m)} aria-label={`Preview ${m.account} ${m.type.toLowerCase()}`}>
        <div className={styles.materialImage} data-type={m.type}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={m.image} alt={`${m.account} ${m.type.toLowerCase()}`} />
        </div><div className={styles.materialInfo}><span className={styles.caption}>{m.type} · {m.account}</span><strong>{m.title}</strong><span className={styles.caption}>Saved design preview</span></div>
      </button>)}</div>
    </section>}
    {selected ? <MailDialog wide title={`${selected.account} · ${selected.type}`} description="Saved preview from your existing Clue project. Publication and ad delivery are managed separately from the gift." close={() => setSelected(null)}>
      <div className={styles.materialFull} data-type={selected.type}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={selected.image} alt={`${selected.account}: ${selected.title}`} />
      </div><div className={styles.actions}><a className={styles.textLink} href={selected.source} target="_blank" rel="noreferrer">Open original in Clue <ExternalLink size={13}/></a><Button variant="outline" size="md" onClick={() => setSelected(null)}>Done</Button></div>
    </MailDialog> : null}
  </>;
}
