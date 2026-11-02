import { MailerSchema, StateSchema, type CardAsset, type HandwritingStyle } from "../model/direct-mail";
import { DEMO_ID, DEMO_PROJECT_ID, DEMO_ACCOUNT_ID, DEMO_PROJECT_URL } from "../model/recording-demo-context";
import { advanceRecordingDemo, resetRecordingDemo } from "./recording-simulation";
import { annGiftCatalog, annGiftInsights, annPuzzleNote, previousAnnNotes } from "./illumio-gift-research";

const media = "/direct-mail/illumio-demo";
export const annMessage = {
  note: annPuzzleNote,
  signature: "The Illumio team",
};
const handwriting: HandwritingStyle = { id: "style-illumio-handprint", name: "Card handwriting", version: 1, family: "Clue Handprint", sourceUrl: "/direct-mail/patrick-hand.ttf", productionReady: true };
const card: CardAsset = {
  id: "card-illumio-demo", name: "Illumio · Personal note", version: 3,
  frontUrl: `${media}/card-front-office-v3.png`, backUrl: null, paper: "cream",
  writingArea: { x: 7, y: 18, width: 84, height: 67 }, productionReady: true,
  branding: { name: "Illumio", logoUrl: `${media}/illumio-logo.svg`, markUrl: `${media}/illumio-mark.png`, line: "Stop breaches from spreading.", qrImageUrl: `${media}/illumio-qr.svg`, qrDestination: "https://www.illumio.com/illumio-platform" },
  messageArtworks: [
    { note: previousAnnNotes[0], signature: annMessage.signature, styleId: handwriting.id, url: `${media}/card-message-ann-puzzle.png` },
    ...annGiftCatalog.map(g => ({ note: g.suggestedNote!, signature: annMessage.signature, styleId: handwriting.id, url: `${media}/card-message-${g.id}-v2.png` })),
  ],
};

/** Publicly sourced research and retail products; approval and fulfillment remain local. */
export function createIllumioMailer() {
  return MailerSchema.parse({
    id: DEMO_ID, revision: 1, reviewedRevision: null,
    projectId: DEMO_PROJECT_ID, projectName: "Illumio platform marketing",
    campaignId: "illumio-usbank-introduction", campaign: "U.S. Bank · A personal introduction",
    threadId: "thr_a84254ae478e5e38b63b743c31fd89fb",
    accountId: DEMO_ACCOUNT_ID, contactId: "4f99acfb-d6ef-4909-a9c0-2fcf5f3106be",
    recipient: { name: "Ann Barron-DiCamillo", role: "EVP & Global Chief Information Security Officer", company: "U.S. Bank", initials: "AB" },
    insight: {
      title: "A new puzzle every day",
      detail: "Ann described cybersecurity as solving new puzzles every day at a 2014 STEM event. These mechanical puzzles connect to that public remark.",
      source: "WashingtonExec · K–12 STEM symposium, 2014", sourceUrl: "https://washingtonexec.com/exec-profiles/open-possibilities-around-stem-google-homeland-security-leaders-encourage-students-k-12-stem-symposium", date: "2026-11-02",
      excerpt: "The most exciting thing for cybersecurity professionals in our field is getting to work on new puzzles every day.",
    },
    gifts: annGiftCatalog.slice(0, 3),
    alternativeGifts: annGiftCatalog.slice(3), giftInsights: annGiftInsights,
    selectedGiftId: "craighill-jack-brass", ...annMessage, cardId: card.id, styleId: handwriting.id,
    address: { name: "Ann Barron-DiCamillo", company: "U.S. Bank", line1: "800 Nicollet Mall", line2: "", city: "Minneapolis", region: "MN", postalCode: "55402", country: "United States" },
    addressConfirmed: false, budgetCents: 15000, inboundCents: 800, preparationCents: 1500, outboundCents: 1200, taxCents: 900,
    stage: "needs_review", updatedAt: "2026-11-02T08:00:00Z", deliveryEstimate: "Shown after merchant confirmation",
    approval: null, priorApprovals: [], inbound: null, outbound: null, events: [], photos: [], exception: null, proposalRequest: null,
    sourceLabel: "Real account research and retailer products · Ordering, costs beyond the gift price, and delivery are simulated.",
    assets: [{ id: "illumio-usbank-landing-page", kind: "microsite", title: "U.S. Bank · Existing landing page", url: DEMO_PROJECT_URL, status: "review", scope: "account", source: "Saved design preview from the deployed project. The card’s QR opens the public Illumio Platform page; the draft account page has not been published or routed to this QR." }],
  });
}

export function createIllumioDemo() {
  return StateSchema.parse({ schemaVersion: 1, cards: [card], styles: [handwriting], mailers: [createIllumioMailer()], creditBalanceCents: 200000, creditEntries: [],
    giftBudgets: [{ projectId: DEMO_PROJECT_ID, revision: 1, minimumCents: 2500, preferredCents: 10000, ceilingCents: 12000, locked: true }],
  });
}

// Exact previous seed copy only; custom research and approved records stay intact.
const previousDemoCopy = [
  "At a K–12 STEM symposium in 2014, Ann described the appeal of cybersecurity as working on new puzzles every day. This brass mechanical puzzle is a creative response to that public remark, not evidence of a private hobby. The business conversation remains U.S. Bank’s AWS migration and consistent breach containment across cloud and data-center applications.",
  "A crafted brass puzzle inspired by Ann’s own description of cyber work: a new puzzle every day. Six precision-machined pieces make a memorable desk object, with a personal note connecting the idea to her words.",
  "A compact mechanical challenge at a lower price. Its hidden magnetic mechanism offers another way to bring Ann’s public puzzle-solving remark into the gift.",
  "A collection that can be shared with the team, with several different challenges in one box. Choose it for a shared break rather than an individual desk piece."
];

/** Refresh built-in artwork and display copy without replacing user edits or approvals. */
export function parseIllumioDemo(value: unknown) {
  const state = StateSchema.parse(value);
  const demo = state.mailers.find(m => m.id === DEMO_ID);
  if (demo && !demo.approval) {
    const latest = createIllumioMailer();
    if (demo.insight.detail === previousDemoCopy[0]) demo.insight.detail = latest.insight.detail;
    for (const gift of [...demo.gifts, ...(demo.alternativeGifts ?? [])]) {
      const originalIndex = ["craighill-jack-brass", "archimedes-gear", "museum-puzzles"].indexOf(gift.id);
      const current = annGiftCatalog.find(g => g.id === gift.id);
      if (current && originalIndex >= 0 && gift.rationale === previousDemoCopy[originalIndex + 1]) gift.rationale = current.rationale;
      // Suggested copy is a catalog template; never overwrite the recipient's actual note.
      if (current && gift.insightId === current.insightId) gift.suggestedNote = current.suggestedNote;
    }
    for (const insight of demo.giftInsights ?? []) {
      const verified = annGiftInsights.find(i => i.id === insight.id);
      if (verified && ["I volunteered for the assignment", "Take risks and grab opportunities when you see them"].includes(insight.excerpt)) insight.excerpt = verified.excerpt;
      if (verified && insight.detail === "Ann has spoken to K–12 students about STEM and encouraged women to explore technical roles and learn by doing.") insight.detail = verified.detail;
    }
    // Upgrade only the known initial trio. Preserve selected alternatives and edited product descriptions.
    if (!demo.giftInsights && demo.gifts.every(g => ["craighill-jack-brass", "archimedes-gear", "museum-puzzles"].includes(g.id))) {
      const existing = demo.gifts;
      const candidates = annGiftCatalog.map(g => {
        const old = existing.find(item => item.id === g.id);
        return old ? { ...g, ...old, insightId: g.insightId, suggestedNote: g.suggestedNote } : g;
      });
      const selected = candidates.find(g => g.id === demo.selectedGiftId);
      const primary = candidates.slice(0, 3);
      if (selected && !primary.some(g => g.id === selected.id)) primary[2] = selected;
      demo.gifts = primary;
      demo.alternativeGifts = candidates.filter(g => !primary.some(p => p.id === g.id));
      demo.giftInsights = structuredClone(annGiftInsights);
      demo.revision++; demo.reviewedRevision = null; demo.stage = "needs_review";
    }
    // Only replace exact superseded suggestions. A user-authored note is never migrated.
    const selectedNote = annGiftCatalog.find(g => g.id === demo.selectedGiftId)?.suggestedNote;
    if (selectedNote && previousAnnNotes.includes(demo.note)) {
      demo.note = selectedNote;
      demo.revision++; demo.reviewedRevision = null; demo.stage = "needs_review";
    }
    for (const [id, note] of Object.entries(demo.giftNotes ?? {})) {
      const replacement = annGiftCatalog.find(g => g.id === id)?.suggestedNote;
      if (replacement && previousAnnNotes.includes(note)) demo.giftNotes![id] = replacement;
    }
  }
  const previous = state.cards.find(c => c.id === card.id);
  if (previous?.version === 2 && previous.frontUrl === `${media}/illumio-hq.webp`) {
    previous.frontUrl = card.frontUrl;
    previous.version = card.version;
    delete previous.frontLayout;
    for (const mailer of state.mailers) {
      if (mailer.cardId === card.id && !mailer.approval && ["needs_review", "ready"].includes(mailer.stage)) {
        mailer.revision += 1;
        mailer.reviewedRevision = null;
        mailer.stage = "needs_review";
      }
    }
  }
  if (previous?.version === card.version && previous.frontUrl === card.frontUrl && demo && !demo.approval) {
    // Append exact-text renders; customized art and approved snapshots remain unchanged.
    if (previous.name === "Illumio · A new puzzle") previous.name = card.name;
    for (const artwork of card.messageArtworks!) {
      if (!previous.messageArtworks?.some(a => a.note === artwork.note && a.signature === artwork.signature && a.styleId === artwork.styleId)) {
        (previous.messageArtworks ??= []).push(artwork);
      }
    }
  }
  return state;
}

export const illumioSimulation = {
  advance: advanceRecordingDemo(DEMO_ID),
  reset: resetRecordingDemo(DEMO_ID, createIllumioMailer),
};
