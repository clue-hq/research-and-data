"use client";

import Link from "./research-link";
import { Popover } from "@base-ui/react/popover";
import { DesignIcon } from "@/components/ui/design-icon";
import {
  Check,
  Copy,
  ExternalLink,
} from "lucide-react";
import {
  Fragment,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useState,
} from "react";
import type {
  BuyingCommitteeMember,
  ResearchContactReference,
  ResearchEvidence,
  ResearchItem,
  ResearchSection,
  ResearchSentence,
} from "../model/research-display";
import type { Account } from "../model/account";
import { anySectionPending, usePendingSectionsRefresh } from "../hooks/use-pending-sections-refresh";
import { ContactAvatar } from "./contact-avatar";
import { FitBadge } from "./account-detail-primitives";
import { presentResearchItem } from "./research-item-presentation";
import { isNewResearch, researchSources } from "../model/research-presentation";
import styles from "./account-research.module.css";
import { SourceChip, SourceIcon, sourceLabel } from "./source-chip";
export { SourceChip } from "./source-chip";

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function ContactLinkedText({
  contacts,
  text,
}: {
  contacts: ResearchContactReference[];
  text: string;
}) {
  if (contacts.length === 0) return text;

  const orderedContacts = [...contacts].sort(
    (left, right) => right.name.length - left.name.length,
  );
  const byName = new Map<string, ResearchContactReference>();
  for (const contact of orderedContacts) {
    byName.set(contact.name.toLowerCase(), contact);
    const first = contact.name.split(" ")[0]!.toLowerCase();
    if (contacts.filter((entry) => entry.name.split(" ")[0]!.toLowerCase() === first).length === 1) byName.set(first, contact);
  }
  const matcher = new RegExp(
    `\\b(${[...byName.keys()].sort((a, b) => b.length - a.length).map(escapeRegExp).join("|")})\\b`,
    "gi",
  );

  return text.split(matcher).map((part, index) => {
    const contact = byName.get(part.toLowerCase());
    if (!contact) return <Fragment key={`${part}-${index}`}>{part}</Fragment>;
    return (
      <ContactLink
        contact={contact}
        className={styles.personLink}
        key={`${contact.contactId}-${index}`}
      >
        {part}
      </ContactLink>
    );
  });
}

function ContactLink({ contact, children, className }: { contact: ResearchContactReference; children: ReactNode; className: string }) {
  return (
    <Popover.Root>
      <Popover.Trigger nativeButton={false} role="link" openOnHover delay={180} closeDelay={180} className={className}
        render={<Link href={`/accounts/${contact.accountId}/contacts/${contact.contactId}`} />}>
        {children}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={8} collisionPadding={16} className={styles.sourcePositioner}>
          <Popover.Popup initialFocus={false} className={styles.sourcePopover} aria-label={`${contact.name} contact details`}>
            <span className={styles.popoverBody}>
              <span className={styles.popoverTitle}>{contact.name}</span>
              <span>{contact.title}</span><span>{contact.persona}</span>
              <span className={styles.popoverMeta}>{contact.emailState === "verified" ? "Email verified" : contact.emailState === "not_requested" ? "Email not requested" : "Email not verified"}</span>
            </span>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function ResearchContactChip({
  contact,
}: {
  contact: ResearchContactReference;
}) {
  return (
    <ContactLink
      contact={contact}
      className={styles.contactChip}
    >
      <ContactAvatar name={contact.name} size={20} src={contact.avatarUrl} />
      <span>{contact.name}</span>
      {contact.title ? (
        <span className={styles.contactRole}>· {contact.title}</span>
      ) : null}
    </ContactLink>
  );
}

function EvidenceRun({
  claimIds,
  evidenceById,
}: {
  claimIds: string[];
  evidenceById: Map<string, ResearchEvidence>;
}) {
  const evidence = claimIds
    .map((claimId) => evidenceById.get(claimId))
    .filter((item): item is ResearchEvidence => Boolean(item));
  if (evidence.length === 0) return null;

  return evidence.map((record) => (
    <span className={styles.evidenceRun} key={record.claimId}>
      <SourceChip evidence={record} relatedEvidence={[record, ...(record.supportingClaimIds ?? []).map((id) => evidenceById.get(id)).filter((entry): entry is ResearchEvidence => Boolean(entry))]} />
    </span>
  ));
}

function SentenceContent({
  contacts,
  evidenceById,
  leadText,
  sentence,
}: {
  contacts: ResearchContactReference[];
  evidenceById: Map<string, ResearchEvidence>;
  leadText?: string;
  sentence: ResearchSentence;
}) {
  const segments = sentence.segments ?? [
    { text: sentence.text, claimIds: sentence.claimIds },
  ];

  return segments.map((segment, index) => {
    const activeLead =
      index === 0 && leadText && segment.text.startsWith(leadText)
        ? leadText
        : null;
    const remainder = activeLead
      ? segment.text.slice(activeLead.length)
      : segment.text;

    return (
      <Fragment key={`${index}-${segment.text}`}>
        {activeLead ? (
          <span className={styles.inlineLeadTitle}>{activeLead}</span>
        ) : null}
        <ContactLinkedText contacts={contacts} text={remainder} />
        <EvidenceRun
          claimIds={segment.claimIds}
          evidenceById={evidenceById}
        />
      </Fragment>
    );
  });
}

function CopyLine({
  evidenceById,
  item,
}: {
  evidenceById: Map<string, ResearchEvidence>;
  item: ResearchItem;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  if (!item.sendLine) return null;

  const onCopy = async () => {
    const text = item.sendLine?.text ?? "";
    setCopyError(false);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const success = document.execCommand("copy");
      textarea.remove();
      if (!success) { setCopyError(true); return; }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className={styles.sendLine}>
      <div>
        <span className={styles.sendLineChannel}>{item.sendLine.channel}</span>
        <span className={styles.sendLineText}>
          <ContactLinkedText contacts={item.contactRefs} text={item.sendLine.text} />
          <EvidenceRun
            claimIds={item.sendLine.claimIds}
            evidenceById={evidenceById}
          />
        </span>
      </div>
      <button
        aria-label={copied ? "Copied" : "Copy line"}
        className={styles.copyButton}
        onClick={onCopy}
        title={copied ? "Copied" : "Copy line"}
        type="button"
      >
        {copied ? (
          <Check aria-hidden="true" size={13} strokeWidth={1.5} />
        ) : (
          <Copy aria-hidden="true" size={13} strokeWidth={1.5} />
        )}
        <span>{copied ? "Copied" : "Copy"}</span>
      </button>
      {copyError ? <span role="status">Copy unavailable. Select the line to copy it.</span> : null}
    </div>
  );
}

function ResearchItemView({
  compact = false,
  reading = false,
  evidenceById,
  item,
}: {
  compact?: boolean;
  reading?: boolean;
  evidenceById: Map<string, ResearchEvidence>;
  item: ResearchItem;
}) {
  const presentation = presentResearchItem(item);
  const usesInlineLead = item.inlineLead === true;
  const firstBodySentence = presentation.body[0] ?? {
    text: "",
    claimIds: [],
  };
  const firstBodySegments = firstBodySentence.segments?.length
    ? firstBodySentence.segments
    : [
        {
          text: firstBodySentence.text,
          claimIds: firstBodySentence.claimIds,
        },
      ];
  const inlineLeadSentence: ResearchSentence = {
    ...firstBodySentence,
    text: `${item.h2}${firstBodySentence.text}`,
    segments: [
      {
        ...firstBodySegments[0]!,
        text: `${item.h2}${firstBodySegments[0]!.text}`,
      },
      ...firstBodySegments.slice(1),
    ],
  };
  const displayedSentences = usesInlineLead
    ? [inlineLeadSentence, ...presentation.body.slice(1)]
    : presentation.body;
  const articleText = [item.h2, ...item.body.map((sentence) => sentence.text), item.sendLine?.text ?? ""].join(" ");
  const unmentionedContacts = item.contactRefs.filter((contact) =>
    contact.contactId !== item.subject?.contactId && (!reading || !new RegExp(`\\b${escapeRegExp(contact.name.split(" ")[0]!)}\\b`, "i").test(articleText)),
  );

  return (
    <article
      className={`${styles.researchItem} ${
        compact ? styles.researchItemCompact : ""
      } ${item.priority === 1 ? styles.priorityOne : ""}`}
      id={item.id}
      data-research-item
      data-priority={item.priority}
    >
      {item.subject ? <div className={styles.personContext}>
        <ResearchContactChip contact={item.subject} />
        <span className={styles.contactRole}>{item.subject.persona}</span>
      </div> : null}
      {reading && unmentionedContacts.length > 0 ? (
        <div className={styles.itemPeople}>
          {unmentionedContacts.map((contact) => <ResearchContactChip contact={contact} key={contact.contactId} />)}
        </div>
      ) : null}
      {usesInlineLead ? null : (
        <h3 className={styles.itemTitle}>
          <ContactLinkedText contacts={item.contactRefs} text={item.h2} />
          <EvidenceRun claimIds={presentation.headingClaimIds} evidenceById={evidenceById} />
        </h3>
      )}
      <div className={styles.sentences}>
        {displayedSentences.map((sentence, index) => {
          const meaningPrefix = "What it means for us:";
          const isMeaning = sentence.text.startsWith(meaningPrefix);
          const text = isMeaning
            ? sentence.text.slice(meaningPrefix.length).trim()
            : sentence.text;
          const displaySentence = isMeaning
            ? {
                ...sentence,
                text,
                segments: sentence.segments?.map((segment, segmentIndex) =>
                  segmentIndex === 0
                    ? {
                        ...segment,
                        text: segment.text
                          .replace(/^What it means for us:\s*/, "")
                          .trimStart(),
                      }
                    : segment,
                ),
              }
            : sentence;

          if (isMeaning) {
            return (
              <p
                className={`${styles.sentence} ${styles.meaningSentence}`}
                key={`${item.id}-sentence-${index}`}
              >
                <span className={styles.meaningLabel}>What it means for us: </span>
                <SentenceContent
                  contacts={item.contactRefs}
                  evidenceById={evidenceById}
                  sentence={displaySentence}
                />
              </p>
            );
          }

          if (usesInlineLead && index === 0) {
            return (
              <h3
                className={`${styles.sentence} ${styles.inlineLeadSentence}`}
                key={`${item.id}-sentence-${index}`}
              >
                <SentenceContent
                  contacts={item.contactRefs}
                  evidenceById={evidenceById}
                  leadText={item.h2}
                  sentence={displaySentence}
                />
              </h3>
            );
          }

          return (
            <p className={styles.sentence} key={`${item.id}-sentence-${index}`}>
              <SentenceContent
                contacts={item.contactRefs}
                evidenceById={evidenceById}
                sentence={displaySentence}
              />
            </p>
          );
        })}
      </div>
      {!reading && unmentionedContacts.length > 0 ? (
        <div className={styles.contactLinks}>
          {unmentionedContacts.map((contact) => (
            <ResearchContactChip contact={contact} key={contact.contactId} />
          ))}
        </div>
      ) : null}
      <CopyLine evidenceById={evidenceById} item={item} />
    </article>
  );
}

const sectionPresentation: Record<
  string,
  { tone: string }
> = {
  "buying-signals": {
    tone: styles.toneOrange,
  },
  "money-and-momentum": {
    tone: styles.toneGreen,
  },
  "tools-they-already-use": {
    tone: styles.toneCyan,
  },
  "how-they-sell": {
    tone: styles.toneBlue,
  },
  "contact-insights": {
    tone: styles.tonePink,
  },
  "context-only": {
    tone: styles.toneRed,
  },
  "why-this-person": {
    tone: styles.toneOrange,
  },
  "problem-right-now": {
    tone: styles.toneBlue,
  },
  openers: {
    tone: styles.toneCyan,
  },
  angles: {
    tone: styles.toneGreen,
  },
  "do-not-mention": {
    tone: styles.toneRed,
  },
};

const fallbackTones = [
  styles.toneOrange,
  styles.toneBlue,
  styles.toneCyan,
  styles.toneGreen,
  styles.tonePink,
  styles.toneRed,
];

function presentationFor(section: ResearchSection, index: number) {
  return (
    {
      label: section.h1,
      tone:
        sectionPresentation[section.key]?.tone ??
        fallbackTones[index % fallbackTones.length]!,
    }
  );
}

function ReadingSection({
  evidenceById, section, prefix, lastVisit = null, name = "this account",
}: {
  evidenceById: Map<string, ResearchEvidence>;
  section: ResearchSection;
  prefix: string;
  lastVisit?: string | null;
  name?: string;
}) {
  return (
    <details className={styles.readingSection} id={`${prefix}-${section.key}`}>
      <summary className={styles.sectionToggle}>
        <h2 className={styles.readingHeading} id={`${prefix}-${section.key}-heading`}>
          <DesignIcon name="chevron-down" size={12} className={styles.sectionChevron} />
          {section.h1}
        </h2>
      </summary>
      <div className={styles.sectionContent}>
        {section.intro?.map((sentence, index) => (
          <p className={styles.sentence} key={index}>
            <SentenceContent contacts={[]} evidenceById={evidenceById} sentence={sentence} />
          </p>
        ))}
        {!section.items.length && !section.intro?.length ? <p className={styles.emptyState}>{section.emptyMessage ?? `No ${section.h1.toLowerCase()} information found for ${name}.`}</p> : null}
        {section.items.map((item) => (
          <Fragment key={item.id}>
            {isNewResearch(item, evidenceById, lastVisit) ? <span className={styles.newLabel}>New since your last visit</span> : null}
            <ResearchItemView reading evidenceById={evidenceById} item={item} />
          </Fragment>
        ))}
      </div>
    </details>
  );
}

function ResearchTools({
  sections, evidence, evidenceById, prefix, summary = [],
}: {
  sections: ResearchSection[];
  evidence: ResearchEvidence[];
  evidenceById: Map<string, ResearchEvidence>;
  prefix: string;
  summary?: string[];
}) {
  const [panel, setPanel] = useState<"sources" | "notes" | null>(null);
  const notes = sections.filter((section) => section.restricted);
  const sources = researchSources(sections, evidence);
  const noteCount = notes.reduce((total, section) => total + section.items.length, 0);
  const togglePanel = (next: "sources" | "notes") => setPanel((current) => current === next ? null : next);

  return (
    <div className={styles.researchTools}>
      <div className={styles.researchToolbar}>
        <div className={styles.researchActions}>
          {sources.length ? <button className={styles.researchAction} type="button" aria-expanded={panel === "sources"} aria-controls={`${prefix}-sources`} onClick={() => togglePanel("sources")}>Sources <span>{sources.length}</span></button> : null}
          {noteCount ? <button className={styles.researchAction} type="button" aria-expanded={panel === "notes"} aria-controls={`${prefix}-notes`} onClick={() => togglePanel("notes")}>Internal notes <span>{noteCount}</span></button> : null}
        </div>
      </div>
      <section className={styles.researchPanel} hidden={panel !== "sources"} id={`${prefix}-sources`} aria-label="Sources">
        <div className={styles.sourceInventory}>
          {summary.length ? <p className={styles.sourceRecordMeta}>{summary.join(" · ")}</p> : null}
          <ul>
            {sources.map((record) => (
              <li key={record.sourceUrl ?? record.claimId}>
                {record.researchFieldKey ? <SourceChip evidence={record} relatedEvidence={[record, ...(record.supportingClaimIds ?? []).map((id) => evidenceById.get(id)).filter((entry): entry is ResearchEvidence => Boolean(entry))]} /> : <a href={record.sourceUrl!} target="_blank" rel="noreferrer">
                  <SourceIcon evidence={record} />
                  <span className={styles.inventoryTitle}>{record.title ?? record.sourceDomain}</span>
                  <span className={styles.inventoryDomain}>{sourceLabel(record.sourceDomain)}</span>
                  <ExternalLink size={12} aria-hidden="true" />
                </a>}
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section className={`${styles.researchPanel} ${styles.internalNotes}`} hidden={panel !== "notes"} id={`${prefix}-notes`} aria-label="Internal notes">
        <p className={styles.notesLabel}>Do not use in outreach</p>
        {notes.map((section) => <div key={section.key}>
          {section.intro?.map((sentence, index) => <p className={styles.sentence} key={index}><SentenceContent contacts={[]} evidenceById={evidenceById} sentence={sentence} /></p>)}
          {section.items.map((item) => <ResearchItemView reading evidenceById={evidenceById} item={item} key={item.id} />)}
        </div>)}
      </section>
    </div>
  );
}

export function ResearchDocument({
  evidence, sections, accountId, summary = [],
}: {
  evidence: ResearchEvidence[];
  sections: ResearchSection[];
  accountId?: string;
  summary?: string[];
}) {
  usePendingSectionsRefresh(anySectionPending(sections));
  const prefix = useId();
  const [lastVisit, setLastVisit] = useState<string | null>(null);
  useEffect(() => {
    if (!accountId) return;
    const storageKey = `clue:research-last-visit:${accountId}`;
    try {
      const previous = localStorage.getItem(storageKey);
      let visited = false;
      const frame = requestAnimationFrame(() => { visited = true; setLastVisit(previous); });
      const saveVisit = () => { if (visited) { try { localStorage.setItem(storageKey, new Date().toISOString()); } catch { /* Storage may be disabled. */ } } };
      window.addEventListener("pagehide", saveVisit);
      return () => { cancelAnimationFrame(frame); window.removeEventListener("pagehide", saveVisit); saveVisit(); };
    } catch { /* No invented freshness when storage is unavailable. */ }
  }, [accountId]);
  const evidenceById = useMemo(() => new Map(evidence.map((item) => [item.claimId, item])), [evidence]);
  return (
    <div className={styles.readingDocument}>
      <ResearchTools evidence={evidence} evidenceById={evidenceById} sections={sections} prefix={prefix} summary={summary} />
      {sections.filter((section) => !section.restricted).map((section) => (
        <ReadingSection evidenceById={evidenceById} section={section} prefix={prefix} lastVisit={lastVisit} key={section.key} />
      ))}
    </div>
  );
}

export function ResearchStack({
  evidence, sections, contactId, name = "this contact",
}: {
  evidence: ResearchEvidence[];
  sections: ResearchSection[];
  /** The contact whose page this is; its own chips are not shown back to it. */
  contactId?: string;
  name?: string;
}) {
  usePendingSectionsRefresh(anySectionPending(sections));
  const prefix = useId();
  const evidenceById = useMemo(() => new Map(evidence.map((item) => [item.claimId, item])), [evidence]);
  const displaySections = sections.map((section) => ({
    ...section,
    items: section.items.map((item) => ({ ...item,
      contactRefs: item.contactRefs.filter((contact) => contact.contactId !== contactId),
      subject: item.subject?.contactId === contactId ? undefined : item.subject,
    })),
  }));
  return (
    <div className={styles.readingDocument}>
      <ResearchTools evidence={evidence} evidenceById={evidenceById} sections={displaySections} prefix={prefix} />
      {displaySections.filter((section) => !section.restricted).map((section) => (
        <ReadingSection evidenceById={evidenceById} section={section} prefix={prefix} name={name} key={section.key} />
      ))}
    </div>
  );
}

export function ResearchOverview({
  accountId,
  contacts = [],
  evidence,
  overallFit = null,
  sections,
}: {
  accountId?: string;
  contacts?: ResearchContactReference[];
  evidence: ResearchEvidence[];
  /** The account's served fit band; `null` until the account is scored. */
  overallFit?: Account["overallFit"];
  sections: ResearchSection[];
}) {
  usePendingSectionsRefresh(anySectionPending(sections));
  const sourcesId = useId();
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.claimId, item])),
    [evidence],
  );

  return (
    <div className={styles.overviewDocument}>
      {sections.map((section, sectionIndex) => {
        const presentation = presentationFor(section, sectionIndex);
        const isWhyNow = section.key === "why-now";
        const isFit = section.key === "why-they-fit";
        const stacked = isWhyNow || section.key === "how-to-approach";
        const Section = stacked ? "details" : "section";
        const Heading = stacked ? "summary" : "div";
        return (
          <Section
            className={`${stacked ? styles.readingSection : styles.overviewStaticSection} ${styles.overviewSection} ${presentation.tone}`}
            key={section.key}
          >
            <Heading className={stacked ? styles.sectionToggle : undefined}>
              <h2 className={styles.readingHeading}>
                {stacked ? <DesignIcon name="chevron-down" size={12} className={styles.sectionChevron} /> : null}
                {section.h1}
                {isFit ? (
                  <span className={styles.overviewFit}>
                    <span>Overall fit:</span>
                    <FitBadge fit={overallFit} />
                  </span>
                ) : null}
              </h2>
            </Heading>
            <div className={stacked ? styles.sectionContent : undefined}>
            {section.intro?.length ? (
              <div className={styles.overviewIntro}>
                {section.intro.map((sentence, sentenceIndex) => (
                  <p className={styles.sentence} key={`${section.key}-intro-${sentenceIndex}`}>
                    <SentenceContent
                      contacts={contacts}
                      evidenceById={evidenceById}
                      sentence={sentence}
                    />
                  </p>
                ))}
              </div>
            ) : null}
            {isFit ? (
              <table className={styles.fitTable}>
                <caption className="sr-only">{section.h1}: reasons and evidence</caption>
                <thead>
                  <tr><th scope="col">Reason</th><th scope="col">Evidence</th></tr>
                </thead>
                <tbody>
                  {section.items.map((item, index) => (
                    <Fragment key={item.id}>
                    {index === 0 || item.fitDisposition !== section.items[index - 1]?.fitDisposition ? (
                      <tr className={styles.fitGroup}><th scope="colgroup" colSpan={2}>{item.fitDisposition === "caveat" ? "Caveats" : "Supporting fit"}</th></tr>
                    ) : null}
                    <tr id={item.id} key={item.id}>
                      <th scope="row">{item.h2}</th>
                      <td>
                        {item.body.map((sentence, index) => (
                          <p className={styles.sentence} key={`${item.id}-${index}`}>
                            <SentenceContent
                              contacts={item.contactRefs}
                              evidenceById={evidenceById}
                              sentence={sentence}
                            />
                          </p>
                        ))}
                      </td>
                    </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            ) : section.items.map((item) => (
              <ResearchItemView
                compact
                evidenceById={evidenceById}
                item={item}
                key={item.id}
              />
            ))}
            {isWhyNow && accountId ? (
              <Link
                className={styles.overviewSectionAction}
                href={`/accounts/${accountId}/insights`}
              >
                See all insights
              </Link>
            ) : null}
            </div>
          </Section>
        );
      })}
      {evidence.some((record) => record.researchFieldKey) ? (
        <ResearchTools evidence={evidence} evidenceById={evidenceById} sections={sections} prefix={sourcesId} />
      ) : null}
    </div>
  );
}

export function ResearchDigest({
  evidence,
  items,
  title,
}: {
  evidence: ResearchEvidence[];
  items: ResearchItem[];
  title: string;
}) {
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.claimId, item])),
    [evidence],
  );

  return (
    <section className={styles.digestSection}>
      <h2 className={styles.digestHeading}>{title}</h2>
      <div className={styles.digestList}>
        {items.slice(0, 3).map((item) => {
          const sentence =
            item.body.find(
              (entry) => !entry.text.startsWith("What it means for us:"),
            ) ?? item.body[0];
          return (
            <article className={styles.digestItem} key={item.id}>
              <h3 className={styles.digestTitle}>{item.h2}</h3>
              {sentence ? (
                <p className={styles.digestBody}>
                  <ContactLinkedText
                    contacts={item.contactRefs}
                    text={sentence.text}
                  />
                  <EvidenceRun
                    claimIds={sentence.claimIds}
                    evidenceById={evidenceById}
                  />
                </p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function BuyingCommitteeTable({
  accountId,
  members,
}: {
  accountId: string;
  members: BuyingCommitteeMember[];
}) {
  return (
    <details className={`${styles.readingSection} ${styles.committeeSection}`}>
      <summary className={styles.sectionToggle}>
        <h2 className={styles.readingHeading}>
          <DesignIcon name="chevron-down" size={12} className={styles.sectionChevron} />
          Buying committee
        </h2>
      </summary>
      <div className={`${styles.sectionContent} ${styles.committeeTableWrap}`}>
        <table className={styles.committeeTable}>
          <colgroup>
            <col style={{ width: "19%" }} />
            <col style={{ width: "17%" }} />
            <col style={{ width: "17%" }} />
            <col style={{ width: "21%" }} />
            <col style={{ width: "26%" }} />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Title</th>
              <th scope="col">Persona</th>
              <th scope="col">Reach</th>
              <th scope="col">Why they matter</th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.contactId}>
                <td>
                  <Link
                    className={styles.committeePerson}
                    href={`/accounts/${accountId}/contacts/${member.contactId}`}
                  >
                    <ContactAvatar name={member.name} size={22} />
                    <span>{member.name}</span>
                  </Link>
                </td>
                <td>
                  <span>{member.title}</span>
                </td>
                <td>{member.persona}</td>
                <td>
                  <span className={styles.committeeLinks}>
                    {member.email && member.outreachEligible === false ? <span>{member.email}</span> : member.email ? (
                      <a
                        className={styles.committeeLink}
                        href={`mailto:${member.email}`}
                      >
                        {member.email}
                      </a>
                    ) : (
                      <span className={styles.committeeRole}>Not requested</span>
                    )}
                    {/* D3 ruling: a member resolved from a coverage row may have no
                        LinkedIn URL; the link renders only when one is served. */}
                    {member.linkedinUrl ? (
                      <a
                        className={styles.committeeLink}
                        href={member.linkedinUrl}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          alt=""
                          aria-hidden="true"
                          className="mr-1 inline-block size-[11px]"
                          src="/logos/linkedin.svg"
                        />
                        LinkedIn
                      </a>
                    ) : null}
                  </span>
                </td>
                <td className={styles.committeeWhy}>{member.whyTheyMatter}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
