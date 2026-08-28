import {
  DormantFragmentListWireSchema,
  FragmentCardSchema,
  FragmentCardWireSchema,
  type FragmentCard,
} from "../model/fragment-card";

/**
 * F3.2: the cloned-section inspector's read/write seam, in the frontend's own shape.
 *
 * Four operations, and every one of them is a decision a human makes about a section the
 * platform cloned from a real website:
 *
 * * `get` — the card (status, condition, repair lineage, hidden-on-source provenance, slots);
 * * `listDormant` — every section the source site HIDES. They are on no page, so nothing can
 *   select one, and founder ruling D-F8 makes the inspector the ONE place a human sees them;
 * * `generatePreview` — an isolation render of the section's own harvested bytes (ruling P-7).
 *   A hidden section was never rendered and a composed repair was never photographed, so this
 *   is the only way either of them ever has a picture;
 * * `activate` / `retire` — the two lifecycle moves a human owns. Activation is refused, with
 *   its reason, until a preview exists; retire is scoped to REPAIRS, because the harvested
 *   original is the evidence a repair is judged against (ruling R17-3).
 *
 * Presentation stays transport-free: a component takes a `FragmentCard` and these callbacks and
 * never knows whether they came from a fixture or from HTTP.
 *
 * **Refusals carry their reason.** Every "no" on this seam is a sentence a human has to act on
 * — "there is no picture of this section yet", "retire the repair instead" — and the design
 * backend is careful to send a code and a message in `detail`. A layer that collapsed those
 * into an HTTP status would throw the whole mapping away, so `FragmentCardError` keeps both.
 */

export class FragmentCardError extends Error {
  readonly code: string;
  readonly status: number;
  /** The backend's own machine-readable reason (`no_preview`, `not_a_repair`, …). */
  readonly reason: string | null;

  constructor(
    message: string,
    options: { code: string; status: number; reason?: string | null },
  ) {
    super(message);
    this.name = "FragmentCardError";
    this.code = options.code;
    this.status = options.status;
    this.reason = options.reason ?? null;
  }
}

export interface FragmentCardRepository {
  get(fragmentId: string): Promise<FragmentCard>;
  listDormant(): Promise<FragmentCard[]>;
  generatePreview(fragmentId: string): Promise<FragmentCard>;
  activate(fragmentId: string): Promise<FragmentCard>;
  retire(fragmentId: string): Promise<FragmentCard>;
}

const FIXTURE_ORIGINAL = FragmentCardSchema.parse({
  fragmentId: "frag_00000000products",
  label: "Products",
  sectionRole: "other",
  status: "approved",
  pageUrl: "https://insighthealth.example/",
  // Where the band sat in DOCUMENT order — the hidden section below is index 7, so the visible
  // indices have a gap. That is the truth about the page, not a list offset (F3.0 M3).
  sectionIndex: 4,
  previewPath: "/asset-store/aaaaaaaa",
  previewBasis: "measured",
  slots: [
    { key: "headline", kind: "text", fallback: "Products" },
    { key: "body", kind: "text", fallback: "Three products, one referral loop." },
    { key: "art", kind: "image", fallback: null },
    { key: "cta", kind: "href", fallback: "https://insighthealth.example/demo" },
    { key: "visible", kind: "visibility", fallback: true },
  ],
  degraded: true,
  degradedReason: "dead_height",
  degradedNote:
    "the captured band is mostly artificial scroll height — a screenful of content followed " +
    "by dead space. The repair must remove the empty height entirely.",
  repairs: [
    {
      fragmentId: "frag_00000000repair1",
      label: "Repaired — Products",
      status: "draft",
      degraded: false,
      derivedReason:
        "repair rung 3 (a deliberate, compact static fallback with the artificial height " +
        "removed entirely); trigger dead_height; same three products at natural height",
      createdAt: "2026-08-28T09:00:00+00:00",
    },
  ],
  activation: { allowed: false, reason: "not_dormant", message: null },
  retirement: {
    allowed: false,
    reason: "not_a_repair",
    message:
      "the harvested original is the evidence a repair is judged against and is never retired; " +
      "retire the repair you do not want instead.",
  },
});

const FIXTURE_REPAIR = FragmentCardSchema.parse({
  fragmentId: "frag_00000000repair1",
  label: "Repaired — Products",
  sectionRole: "other",
  status: "draft",
  pageUrl: "https://insighthealth.example/",
  sectionIndex: 4,
  slots: FIXTURE_ORIGINAL.slots,
  derivedFrom: FIXTURE_ORIGINAL.fragmentId,
  derivedReason: FIXTURE_ORIGINAL.repairs[0]?.derivedReason ?? null,
  repairsWhat: {
    fragmentId: FIXTURE_ORIGINAL.fragmentId,
    label: "Products",
    status: "approved",
    degraded: true,
    degradedReason: "dead_height",
  },
  activation: { allowed: false, reason: "not_dormant", message: null },
  retirement: { allowed: true, reason: null, message: null },
});

const FIXTURE_DORMANT = FragmentCardSchema.parse({
  fragmentId: "frag_00000000pricing",
  label: "Proof — Pricing",
  sectionRole: "proof",
  status: "dormant",
  pageUrl: "https://insighthealth.example/",
  sectionIndex: 7,
  slots: [{ key: "headline", kind: "text", fallback: "Pricing" }],
  hiddenOnSource: {
    hidden: true,
    evidence: [
      "class token 'w-condition-invisible'",
      "the probe recorded skipping this child",
    ],
  },
  activation: {
    allowed: false,
    reason: "no_preview",
    message:
      "this section was never rendered on the source site, so there is no picture of it yet. " +
      "Generate an isolation render — our engine drawing the section's own harvested bytes — " +
      "and then decide.",
  },
  retirement: { allowed: false, reason: "not_a_repair", message: null },
});

export const FIXTURE_FRAGMENT_CARDS: readonly FragmentCard[] = [
  FIXTURE_ORIGINAL,
  FIXTURE_REPAIR,
  FIXTURE_DORMANT,
];

/**
 * The in-memory adapter. It does not merely echo cards back — it enforces the same three rules
 * the backend does, because a fixture that let a previewless section activate would teach a
 * component the wrong shape of the world:
 *
 * 1. activation needs a preview (D-F8) and only applies to a dormant section;
 * 2. an isolation render gives a section its picture, and only once (P-7);
 * 3. only a REPAIR is retirable (R17-3).
 */
export function fixtureFragmentCardRepository(
  seed: readonly FragmentCard[] = FIXTURE_FRAGMENT_CARDS,
): FragmentCardRepository {
  const cards = new Map(seed.map((card) => [card.fragmentId, { ...card }]));

  const require = (fragmentId: string): FragmentCard => {
    const card = cards.get(fragmentId);
    if (!card) {
      throw new FragmentCardError("no such cloned section", {
        code: "FRAGMENT_NOT_FOUND",
        status: 404,
      });
    }
    return card;
  };

  return {
    async get(fragmentId) {
      return { ...require(fragmentId) };
    },
    async listDormant() {
      return [...cards.values()]
        .filter((card) => card.status === "dormant")
        .sort((left, right) => (left.sectionIndex ?? 0) - (right.sectionIndex ?? 0))
        .map((card) => ({ ...card }));
    },
    async generatePreview(fragmentId) {
      const card = require(fragmentId);
      if (card.previewPath) {
        throw new FragmentCardError(
          "this section already carries a preview: a preview is attached once and never replaced",
          { code: "fragment.preview_preview_present", status: 409, reason: "preview_present" },
        );
      }
      const next: FragmentCard = {
        ...card,
        previewPath: `/asset-store/isolation-${card.fragmentId}`,
        previewBasis: "isolation_render",
        activation:
          card.status === "dormant"
            ? { allowed: true, reason: null, message: null }
            : card.activation,
      };
      cards.set(fragmentId, next);
      return { ...next };
    },
    async activate(fragmentId) {
      const card = require(fragmentId);
      if (card.status !== "dormant") {
        throw new FragmentCardError(
          `this section is ${card.status}, not one the source site hides — there is nothing to activate.`,
          { code: "fragment.not_dormant", status: 409, reason: "not_dormant" },
        );
      }
      if (!card.previewPath) {
        throw new FragmentCardError(card.activation.message ?? "no preview", {
          code: "fragment.activation_no_preview",
          status: 409,
          reason: "no_preview",
        });
      }
      const next: FragmentCard = {
        ...card,
        status: "approved",
        activation: { allowed: false, reason: "not_dormant", message: null },
      };
      cards.set(fragmentId, next);
      return { ...next };
    },
    async retire(fragmentId) {
      const card = require(fragmentId);
      if (!card.derivedFrom) {
        throw new FragmentCardError(
          "the harvested original is the evidence a repair is judged against and is never " +
            "retired; retire the repair you do not want instead.",
          { code: "fragment.not_a_repair", status: 409, reason: "not_a_repair" },
        );
      }
      const next: FragmentCard = {
        ...card,
        status: "deprecated",
        retirement: { allowed: false, reason: "already_retired", message: null },
      };
      cards.set(fragmentId, next);
      // The original stops being contested by this repair.
      const original = cards.get(card.derivedFrom);
      if (original) {
        cards.set(card.derivedFrom, {
          ...original,
          lineageAmbiguous: original.lineageAmbiguous.filter((id) => id !== fragmentId),
          repairs: original.repairs.map((entry) =>
            entry.fragmentId === fragmentId ? { ...entry, status: "deprecated" } : entry,
          ),
        });
      }
      return { ...next };
    },
  };
}

export function httpFragmentCardRepository({
  baseUrl = "/api/clue",
  fetchImpl,
}: {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
} = {}): FragmentCardRepository {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));

  const call = async (path: string, init?: RequestInit): Promise<unknown> => {
    const response = await doFetch(`${baseUrl}${path}`, { cache: "no-store", ...init });
    if (!response.ok) {
      let code = "FRAGMENT_READ_FAILED";
      let message = `cloned-section read failed (${response.status})`;
      let reason: string | null = null;
      try {
        // The design backend words its refusals under `detail` (code / reason / message); the
        // platform BFF wraps its own under `error`. Both are read, because the sentence is the
        // point and it must survive whichever wrapper it arrived in.
        const envelope = (await response.json()) as {
          detail?: { code?: string; message?: string; reason?: string };
          error?: { code?: string; message?: string };
        };
        const detail = envelope.detail ?? envelope.error;
        if (detail?.code) code = detail.code;
        if (detail?.message) message = detail.message;
        if (envelope.detail?.reason) reason = envelope.detail.reason;
      } catch {
        // A non-JSON refusal keeps the generic message.
      }
      throw new FragmentCardError(message, { code, status: response.status, reason });
    }
    return response.json();
  };

  const card = async (path: string, init?: RequestInit): Promise<FragmentCard> =>
    FragmentCardWireSchema.parse(await call(path, init));

  const encoded = (fragmentId: string) => encodeURIComponent(fragmentId);

  return {
    async get(fragmentId) {
      return card(`/web/fragments/${encoded(fragmentId)}`);
    },
    async listDormant() {
      return DormantFragmentListWireSchema.parse(await call("/web/fragments/dormant"));
    },
    async generatePreview(fragmentId) {
      return card(`/web/fragments/${encoded(fragmentId)}/preview`, { method: "POST" });
    },
    async activate(fragmentId) {
      return card(`/web/fragments/${encoded(fragmentId)}/activate`, { method: "POST" });
    },
    async retire(fragmentId) {
      return card(`/web/fragments/${encoded(fragmentId)}/retire`, { method: "POST" });
    },
  };
}
