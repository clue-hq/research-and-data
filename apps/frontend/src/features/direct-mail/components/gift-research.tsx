"use client";

import { useState } from "react";
import { ArrowUpRight, BookOpen, Check, Lightbulb, Puzzle, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { money, type GiftInsight, type Mailer } from "../model/direct-mail";
import { MailDialog } from "./mail-ui";
import { ProductImage } from "./product-image";
import styles from "./gift-research.module.css";
import mail from "./direct-mail.module.css";

const icons = [Puzzle, BookOpen, Lightbulb, Users];

export function GiftResearch({ name, insights, onOpen }: { name: string; insights: GiftInsight[]; onOpen: (insight: GiftInsight) => void }) {
  return <section className={styles.research} aria-label="Insights behind the gifts">
    <div className={styles.sectionHeading}><h2>What we learned about {name}</h2><span>Public research · {insights.length} insights</span></div>
    <div className={styles.insightGrid}>{insights.map((insight, i) => {
      const Icon = icons[i % icons.length];
      return <button key={insight.id} className={styles.insight} onClick={() => onOpen(insight)}>
        <div className={styles.insightTitle}><Icon size={15} aria-hidden="true" /><h3>{insight.title}</h3>{insight.kind === "conversation" ? <span className={styles.contextLabel}>Context</span> : null}</div>
        <p>{insight.detail}</p><span className={styles.source}>{insight.source} · {insight.sourceDate}<ArrowUpRight size={12} aria-hidden="true" /></span>
      </button>;
    })}</div>
  </section>;
}

export function GiftInsightDialog({ insight, close }: { insight: GiftInsight; close: () => void }) {
  return <MailDialog title={insight.title} description={`${insight.source} · ${insight.sourceDate}`} close={close}>
    <p className={styles.insightDetail}>{insight.detail}</p>
    {insight.excerpt ? <blockquote className={styles.excerpt}>“{insight.excerpt}”</blockquote> : null}
    <p className={`${mail.caption} mt-4`}>{insight.kind === "gift" ? "This public statement informs the suggestion. It does not establish a personal hobby or gift preference." : "Business context for the note and conversation; not a personal gift preference."}</p>
    <div className={mail.actions}><Button variant="transparent" size="md" onClick={close}>Back to gifts</Button><a className={mail.textLink} href={insight.sourceUrl} target="_blank" rel="noreferrer">Read source ↗</a></div>
  </MailDialog>;
}

export function GiftAlternatives({ mailer, disabled, error, onSelect, onRequest }: { mailer: Mailer; disabled: boolean; error?: string | null; onSelect: (id: string) => Promise<boolean>; onRequest: () => void }) {
  const [open, setOpen] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [message, setMessage] = useState("");
  const alternatives = mailer.alternativeGifts ?? [];
  async function choose(id: string) {
    setChoosing(true);
    try {
      if (await onSelect(id)) { setOpen(false); setMessage("Gift options updated. Unselected gifts remain available in More options."); }
    } finally { setChoosing(false); }
  }
  return <>
    <section className={styles.alternatives} aria-label="Explore other gifts"><div><h2>Not quite the right gift?</h2><p>Explore other options, or give Clue a different direction.</p></div><div className={styles.alternativeActions}>
      <Button variant="outline" size="md" disabled={disabled} onClick={() => setOpen(true)}>More options <span className={styles.count}>{alternatives.length}</span></Button>
      <Button variant="transparent" size="md" disabled={disabled} onClick={onRequest}>Ask for different gifts</Button>
    </div></section>
    <p className={styles.selectionMessage} role="status">{message}</p>
    {open ? <MailDialog title="More gift options" description="Your current choice stays selected until you choose a replacement. All three original directions remain available." close={() => setOpen(false)} busy={disabled || choosing} wide>
      <div className={styles.alternativeList}>{alternatives.map(g => {
        const insight = mailer.giftInsights?.find(i => i.id === g.insightId);
        return <article key={g.id} className={styles.alternativeItem}><ProductImage src={g.image} alt={g.name} /><div className={styles.alternativeBody}><div className={styles.alternativeTitle}><h3>{g.name}</h3><span>{money(g.priceCents)}</span></div><p>{g.rationale}</p>{insight ? <span className={mail.caption}>{insight.title}</span> : null}<div className={styles.alternativeFooter}><a href={g.productUrl} target="_blank" rel="noreferrer">View at {g.merchant} ↗</a><Button variant="outline" size="sm" disabled={disabled || choosing || !g.available} onClick={() => void choose(g.id)}><Check size={13} />Choose gift</Button></div></div></article>;
      })}</div>
      {error ? <p role="alert" className="mt-3">{error}</p> : null}
      <div className={mail.actions}><Button variant="transparent" size="md" onClick={() => setOpen(false)} disabled={choosing}>Keep current choice</Button><Button variant="primary" size="md" disabled={choosing} onClick={() => { setOpen(false); onRequest(); }}>Try another direction</Button></div>
    </MailDialog> : null}
  </>;
}
