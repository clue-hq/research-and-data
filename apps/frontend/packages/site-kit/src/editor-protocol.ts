// Contract 6 (Wave 2): every message between app.cluehq.ai and the site editor frame on the
// editor domain. Both sides parse with these schemas and drop anything that does not match;
// neither side ever posts to "*". The two acceptors below are the ONLY way a side may trust a
// message: origin, source window, nonce and document id, then the schema.
//
// Refinements recorded in the master plan (Lane C plan K6): frame → app `shortcut`; the
// "shell" target in place of a route for the header/footer; `navigated` after an applied init.
//
// v2 (the sync fix, 2026-10-14): the app holds the only working copy of the site and the frame only
// displays it. Every copy the app sends (`init`, `replace_site`, and the `set_props` / `insert_asset`
// patches) carries the app's revision of it; every canvas edit the frame proposes (`changed`) names
// the revision it started from, and the app refuses one made over an older copy. Revisions belong to
// the app's working copy, not to the server's version numbers.
//
// `pending` (2026-10-14): the frame says whenever it starts or stops holding work it has not sent to
// the app yet (typing not yet written into the page, an edit waiting out its pause), so the app can
// ask before the page is reloaded or closed. An app that does not know it drops it, like any message.
//
// `open_link` (2026-10-14, founder): a link to another website clicked in the preview. The frame may
// not open tabs (no popups in its sandbox) and never navigates itself; the app opens it in a new tab.
//
// Element selection (site element inspector, 2026-10-17): `selected` may name one text element inside
// the section (`element`, with its computed typography) and lists the section's text elements
// (`elements`, for Layers); the app's `select` may name an `elementKey`. Additive: absent means the
// whole section, as before.
import { z } from "zod";
import { ElementKeySchema } from "./edits";
import {
  BrandDataSchema,
  ComponentIdSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
  SiteRouteSchema,
  SiteTargetSchema,
} from "./site-document";

export const EDITOR_CHANNEL = "clue-site-editor";
export const EDITOR_PROTOCOL_VERSION = 2;

export const EditorModeSchema = z.enum(["edit", "preview"]);
export type EditorMode = z.infer<typeof EditorModeSchema>;
export const PreviewDeviceSchema = z.enum(["Desktop", "Tablet", "Mobile"]);
export type PreviewDevice = z.infer<typeof PreviewDeviceSchema>;

/** A dotted prop path: "heading", "slots.headline", "stats.0.value". */
export const PropPathSchema = z
  .string()
  .max(300)
  .regex(/^[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+))*$/);
/** Contract 1: every image in a site is a blob of this workspace's asset store. */
export const AssetStoreUrlSchema = z.string().regex(/^\/asset-store\/[0-9a-f]{64}$/);

const RectSchema = z.object({
  x: z.number(),
  y: z.number(),
  top: z.number(),
  right: z.number(),
  bottom: z.number(),
  left: z.number(),
  width: z.number(),
  height: z.number(),
});
/** The element's box in the frame's viewport and document coordinates (the web bridge's shape). */
export const GeometrySchema = z.object({ viewport: RectSchema, document: RectSchema });
export type SiteGeometry = z.infer<typeof GeometrySchema>;

/** "richtext": words edited on the canvas only (plan 2); the dock shows them read-only. */
export type FieldKind = "text" | "textarea" | "richtext" | "select" | "image" | "link" | "number" | "boolean" | "list";
export type FieldOption = { label: string; value: string | number | boolean };
export type FieldDescription = {
  name: string;
  label: string;
  kind: FieldKind;
  options?: FieldOption[];
  item?: FieldDescription[];
};
export const FieldDescriptionSchema: z.ZodType<FieldDescription> = z.lazy(() =>
  z.object({
    name: PropPathSchema,
    label: z.string().max(200),
    kind: z.enum(["text", "textarea", "richtext", "select", "image", "link", "number", "boolean", "list"]),
    options: z
      .array(z.object({ label: z.string().max(200), value: z.union([z.string(), z.number(), z.boolean()]) }))
      .optional(),
    item: z.array(FieldDescriptionSchema).optional(),
  }),
);

/** What a text element looks like now, as the browser draws it (the panel shows it where `_edits`
 * sets nothing). The colour is always #RRGGBB, so it can never carry anything but a colour. */
export const ComputedTypographySchema = z.object({
  color: z.string().regex(/^#[0-9A-F]{6}$/),
  fontFamily: z.string().max(200),
  fontSize: z.number().nonnegative(),
  fontWeight: z.number().int().min(1).max(1000),
  italic: z.boolean(),
  underline: z.boolean(),
  textAlign: z.enum(["left", "center", "right", "justify"]),
});
export type ComputedTypography = z.infer<typeof ComputedTypographySchema>;
/** One element of the selected section the inspector can select (plan 1: text only). */
export const ElementSummarySchema = z.object({
  key: ElementKeySchema,
  kind: z.literal("text"),
  label: z.string().max(80),
});
export type ElementSummary = z.infer<typeof ElementSummarySchema>;
/** Plan 2. Where the element's words are stored when they are rich text (a prop path: `heading`,
 * `slots.headline`); for a clone slot never set, `fallback` is its captured words as rich text. */
export const RichSourceSchema = z.object({ prop: PropPathSchema, fallback: z.string().max(100_000).optional() });
/** Highlighted words inside the element: character offsets as the browser's textContent counts them,
 * the words themselves (the app checks them against its own copy), and how the first of them is drawn. */
export const WordsSchema = z
  .object({
    start: z.number().int().nonnegative(),
    end: z.number().int().nonnegative(),
    count: z.number().int().nonnegative(),
    text: z.string().max(100_000),
    computed: ComputedTypographySchema,
  })
  .refine((words) => words.end > words.start, { message: "highlighted words are a range" });
/** Where the element's own link is written: a prop and its new-tab prop (our sections, the shell), a
 * clone's href slot, a clone's link replacement (by the captured address; `shared` when other links in
 * the section have it too), or nowhere the marketer can change (`fixed`, with why). */
export const LinkSourceSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("prop"), href: PropPathSchema, newTab: PropPathSchema }),
  z.object({ kind: z.literal("slot"), slot: z.string().min(1).max(200) }),
  z.object({ kind: z.literal("replacement"), find: z.string().min(1).max(2048), shared: z.boolean() }),
  z.object({ kind: z.literal("fixed"), reason: z.string().max(300) }),
]);
export type RichSource = z.infer<typeof RichSourceSchema>;
export type Words = z.infer<typeof WordsSchema>;
export type LinkSource = z.infer<typeof LinkSourceSchema>;
export const ElementSelectionSchema = ElementSummarySchema.extend({
  computed: ComputedTypographySchema,
  rich: RichSourceSchema.nullable().optional(),
  words: WordsSchema.nullable().optional(),
  /** The element's own link: where it is written, and the address it goes to on the canvas now. */
  link: z.object({ source: LinkSourceSchema, href: z.string().max(2048).optional() }).nullable().optional(),
});
export type ElementSelection = z.infer<typeof ElementSelectionSchema>;

const envelope = {
  channel: z.literal(EDITOR_CHANNEL),
  v: z.literal(EDITOR_PROTOCOL_VERSION),
  documentId: z.string().max(200),
  nonce: z.string().min(16).max(128),
};
const Props = z.record(z.string(), z.unknown());
/** The app's revision of its working copy (see the v2 note above). */
export const RevisionSchema = z.number().int().nonnegative();
/** A link to another website: an absolute http(s) address, nothing else (no javascript:, data:, …). */
export const ExternalHrefSchema = z.string().max(2048).regex(/^https?:\/\/[^\s/?#]+/i);

export const AppToFrameMessageSchema = z.discriminatedUnion("type", [
  z.object({
    ...envelope,
    type: z.literal("init"),
    payload: z.object({
      site: SiteDocumentSchema,
      brand: BrandDataSchema,
      sections: z.array(SectionLinkSchema),
      mode: EditorModeSchema,
      route: SiteRouteSchema,
      device: PreviewDeviceSchema,
      rev: RevisionSchema,
    }),
  }),
  z.object({
    ...envelope,
    type: z.literal("replace_site"),
    payload: z.object({ site: SiteDocumentSchema, rev: RevisionSchema }),
  }),
  z.object({ ...envelope, type: z.literal("set_mode"), payload: z.object({ mode: EditorModeSchema }) }),
  z.object({ ...envelope, type: z.literal("navigate"), payload: z.object({ route: SiteRouteSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("set_props"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, props: Props, rev: RevisionSchema }),
  }),
  z.object({
    ...envelope,
    type: z.literal("select"),
    payload: z.object({
      route: SiteTargetSchema,
      componentId: ComponentIdSchema.nullable(),
      elementKey: ElementKeySchema.nullable().optional(),
    }),
  }),
  z.object({
    ...envelope,
    type: z.literal("insert_asset"),
    payload: z.object({
      route: SiteTargetSchema,
      componentId: ComponentIdSchema,
      prop: PropPathSchema,
      url: AssetStoreUrlSchema,
      rev: RevisionSchema,
    }),
  }),
]);

export const FrameToAppMessageSchema = z.discriminatedUnion("type", [
  z.object({ ...envelope, type: z.literal("ready"), payload: z.object({}).strict() }),
  z.object({ ...envelope, type: z.literal("changed"), payload: z.object({ site: SiteDocumentSchema, baseRev: RevisionSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("selected"),
    payload: z.object({
      route: SiteTargetSchema,
      componentId: ComponentIdSchema,
      componentType: z.string().min(1).max(200),
      fields: z.array(FieldDescriptionSchema),
      props: Props,
      element: ElementSelectionSchema.nullable().optional(),
      elements: z.array(ElementSummarySchema).max(500).optional(),
    }),
  }),
  z.object({ ...envelope, type: z.literal("deselected"), payload: z.object({}).strict() }),
  z.object({ ...envelope, type: z.literal("navigated"), payload: z.object({ route: SiteRouteSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("request_asset"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, prop: PropPathSchema }),
  }),
  z.object({
    ...envelope,
    type: z.literal("annotate"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, geometry: GeometrySchema }),
  }),
  z.object({
    ...envelope,
    type: z.literal("error"),
    payload: z.object({ code: z.string().min(1).max(100), message: z.string().max(2000) }),
  }),
  z.object({
    ...envelope,
    type: z.literal("shortcut"),
    payload: z.object({ action: z.enum(["undo", "redo"]) }),
  }),
  z.object({
    ...envelope,
    type: z.literal("open_link"),
    payload: z.object({ href: ExternalHrefSchema }).strict(),
  }),
  z.object({
    ...envelope,
    type: z.literal("pending"),
    payload: z.object({ pending: z.boolean() }).strict(),
  }),
]);

export type AppToFrameMessage = z.infer<typeof AppToFrameMessageSchema>;
export type FrameToAppMessage = z.infer<typeof FrameToAppMessageSchema>;
export type AppToFrameType = AppToFrameMessage["type"];
export type FrameToAppType = FrameToAppMessage["type"];
export type AppToFramePayloads = { [K in AppToFrameType]: Extract<AppToFrameMessage, { type: K }>["payload"] };
export type FrameToAppPayloads = { [K in FrameToAppType]: Extract<FrameToAppMessage, { type: K }>["payload"] };

interface EnvelopeContext {
  documentId: string;
  nonce: string;
}

export function appToFrame<T extends AppToFrameType>(
  type: T,
  payload: AppToFramePayloads[T],
  context: EnvelopeContext,
): AppToFrameMessage {
  return {
    channel: EDITOR_CHANNEL,
    v: EDITOR_PROTOCOL_VERSION,
    documentId: context.documentId,
    nonce: context.nonce,
    type,
    payload,
  } as AppToFrameMessage;
}

export function frameToApp<T extends FrameToAppType>(
  type: T,
  payload: FrameToAppPayloads[T],
  context: EnvelopeContext,
): FrameToAppMessage {
  return {
    channel: EDITOR_CHANNEL,
    v: EDITOR_PROTOCOL_VERSION,
    documentId: context.documentId,
    nonce: context.nonce,
    type,
    payload,
  } as FrameToAppMessage;
}

export function parseAppToFrame(data: unknown): AppToFrameMessage | null {
  const parsed = AppToFrameMessageSchema.safeParse(data);
  return parsed.success ? parsed.data : null;
}

export function parseFrameToApp(data: unknown): FrameToAppMessage | null {
  const parsed = FrameToAppMessageSchema.safeParse(data);
  return parsed.success ? parsed.data : null;
}

export interface MessageEventLike {
  origin: string;
  source: unknown;
  data: unknown;
}

/** The frame's rule: from its own parent, from the app origin, with its nonce. `init` names the
 * document the frame then belongs to; every other message must name that document. */
export function acceptAppMessage(
  event: MessageEventLike,
  expected: { appOrigin: string; documentId: string; nonce: string; parent: unknown },
): AppToFrameMessage | null {
  if (expected.parent == null || event.source !== expected.parent) return null;
  if (event.origin !== expected.appOrigin) return null;
  const message = parseAppToFrame(event.data);
  if (!message || message.nonce !== expected.nonce) return null;
  if (message.type === "init") return message.documentId === "" ? null : message;
  if (expected.documentId === "" || message.documentId !== expected.documentId) return null;
  return message;
}

/** The app's rule: from the iframe it mounted, from the workspace's exact editor origin, with
 * that frame's nonce. `ready` (the frame's boot) carries no document; everything else must
 * name the document the app last initialised the frame with. */
export function acceptFrameMessage(
  event: MessageEventLike,
  expected: { documentId: string | null; editorOrigin: string | null; nonce: string | null; source: unknown },
): FrameToAppMessage | null {
  if (!expected.editorOrigin || event.origin !== expected.editorOrigin) return null;
  if (expected.source == null || event.source !== expected.source) return null;
  const message = parseFrameToApp(event.data);
  if (!message || !expected.nonce || message.nonce !== expected.nonce) return null;
  if (message.type === "ready") return message.documentId === "" ? message : null;
  if (expected.documentId === null || message.documentId !== expected.documentId) return null;
  return message;
}
