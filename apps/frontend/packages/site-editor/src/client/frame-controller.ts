import { normalizeRichIn, type BrandData } from "@clue/site-kit";
import { ExternalHrefSchema } from "@clue/site-kit/editor-protocol";
import type { AppToFrameMessage, AppToFramePayloads, EditorMode, ElementSelection, ElementSummary, FieldDescription, FrameToAppPayloads, FrameToAppType, SectionBox, SiteGeometry, Words } from "@clue/site-kit/editor-protocol";
import {
  canonicalJson,
  componentProps,
  internalRoute,
  pageFor,
  withAssetAt,
  withComponentProps,
  withPage,
} from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SectionLink, type SiteDocument, type SitePage, type SiteTarget } from "@clue/site-kit/site-document";
import type { LoadedSection } from "./sections";

/** The pause after the last keystroke before an edit is sent (blur, a mode change, a page switch
 * and a shortcut send it at once). Each send is one save, and one save is one undo step. */
export const CHANGE_DEBOUNCE_MS = 600;

/** How long leaving a piece of text waits before sending what was typed: Puck's rich text editor
 * reports its text up to 200 ms after the last keystroke (plan 2), and what is sent must include it. */
export const LEAVE_SETTLE_MS = 250;

/** How long after the last keystroke typing counts as possibly not yet written into the page (a
 * cloned text slot writes after its own short pause; see site-kit's CloneEditor). */
export const TYPING_SETTLE_MS = 1500;

export type FrameStatus = "booting" | "loading" | "ready" | "failed";

export interface FrameSelection {
  componentId: string;
  /** One text element of the section (site element inspector), or null for the whole section. */
  elementKey: string | null;
  target: SiteTarget;
}

/** Reads the canvas (editor-app wires it): the section's text elements, and the one with this key as
 * the `selected` message carries it (null when the section has no such element any more). The
 * controller itself never touches the DOM, so it is tested in Node. */
export type ElementDescriber = (
  target: SiteTarget,
  componentId: string,
  elementKey: string | null,
) => { element: ElementSelection | null; elements: ElementSummary[]; sectionBox?: SectionBox | null };

const NO_ELEMENTS: ElementDescriber = () => ({ element: null, elements: [] });
/** How many re-describes after a new copy of the site may post a changed look (the redraw may take
 * more than one). */
const LOOK_WATCH = 3;

/** Highlighted words the controller keeps through a redraw (plan 2). */
export type KeptWords = { target: SiteTarget; componentId: string; key: string; words: Words };

/** Which elements a description shows (keys and labels), without their computed look. */
/** How the selected element (its computed type, box or container, its words' type) and the section's
 * own box are drawn, as JSON, for spotting a change after a new copy of the site arrives. */
function lookOf(element: ElementSelection | null, sectionBox: SectionBox | null | undefined): string {
  return JSON.stringify([element?.computed ?? null, element?.box ?? null, element?.container ?? null, element?.labelElement?.computed ?? null, sectionBox ?? null]);
}

function shownElements(element: ElementSelection | null, elements: ElementSummary[]): string {
  return JSON.stringify([element?.key ?? null, elements.map((item) => [item.key, item.label, item.kind, item.parent ?? null, item.hidden ?? false])]);
}

export interface FrameState {
  brand: BrandData | null;
  documentId: string;
  mode: EditorMode;
  /** Bumps whenever Puck must remount: a new document, another page. */
  mountKey: number;
  /** The app's revision of the copy shown (protocol v2): every proposal names it as its base. */
  rev: number;
  route: string;
  sections: LoadedSection[];
  selection: FrameSelection | null;
  site: SiteDocument | null;
  status: FrameStatus;
}

/** What the controller may ask of the mounted Puck (wired by editor-app.tsx's PuckBridge). */
export interface PuckHandle {
  /** `scroll: false` for a click: the section is already where the marketer is looking. */
  select(componentId: string | null, options?: { scroll?: boolean }): void;
  setMode(mode: EditorMode): void;
  /** Show a page that came from outside Puck (the app's copy). `selectedId` is the page section the
   * marketer has selected, which Puck must point at by id: Puck keeps a selection by position, so a
   * section added or removed above it would otherwise move the dock to another section (S2a-4). */
  showPage(page: SitePage, selectedId: string | null): void;
}

export type FramePost = <T extends FrameToAppType>(type: T, payload: FrameToAppPayloads[T], documentId: string) => void;

export interface FrameControllerDeps {
  cancel?: (handle: unknown) => void;
  loadSections: (links: readonly SectionLink[]) => Promise<LoadedSection[]>;
  post: FramePost;
  schedule?: (run: () => void, ms: number) => unknown;
}

export interface ShellFields {
  footer: FieldDescription[];
  header: FieldDescription[];
}

const INITIAL: FrameState = {
  brand: null,
  documentId: "",
  mode: "preview",
  mountKey: 0,
  rev: 0,
  route: "/",
  sections: [],
  selection: null,
  site: null,
  status: "booting",
};

export class FrameController {
  private state: FrameState = INITIAL;
  private readonly listeners = new Set<() => void>();
  private puck: PuckHandle | null = null;
  private describe: ElementDescriber = NO_ELEMENTS;
  /** A text element a click (or the app's select) named before Puck selected its section. */
  private pendingElement: { target: SiteTarget; componentId: string; key: string | null } | null = null;
  /** The selected section as last described: its type and fields (to re-post them for another
   * element), the element key that was asked for, and what the canvas showed (to re-describe it). */
  private described: {
    componentType: string;
    fields: FieldDescription[];
    askedKey: string | null;
    shown: string;
    /** The words last posted, as JSON ("null" for none). */
    words: string;
    /** How the element and the section's box were drawn when last posted, as JSON. */
    look: string;
  } | null = null;
  /** Re-describes left in which a changed look is posted: set when the app sends a new copy of the
   * site (an undo, a redo, a save), so the panel never keeps showing an undone value; otherwise a
   * look that changes on its own (an animation) is never posted. */
  private lookWatch = 0;
  /** The highlighted words last seen on the canvas (plan 2), kept until the marketer clicks or types:
   * a redraw (an outside edit, a save) drops the browser's selection, but the panel goes on acting on
   * those words. */
  private kept: KeptWords | null = null;
  /** A pointer or key press in the frame since the words were last seen. */
  private acted = false;
  private shellFields: ShellFields | null = null;
  private timer: unknown = null;
  private changePending = false;
  private initGeneration = 0;
  /** While an init loads its agent sections, the copy it will show: every update that arrives
   * meanwhile is applied here instead of being dropped (review finding K3-5). */
  private loading: { site: SiteDocument; rev: number; route: string } | null = null;
  /** The base revision of the last proposal sent, until a replaced copy ends it: the app may have
   * refused it because its own patch overtook it (sync-fix review F2). */
  private proposedFrom: number | null = null;
  /** Keystrokes not yet known to be in the page (unsaved work the app must ask about on leaving). */
  private typing = false;
  private typingGeneration = 0;
  /** What the app was last told about unsent work. */
  private toldPending = false;

  constructor(private readonly deps: FrameControllerDeps) {}

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getState = (): FrameState => this.state;

  announceReady(): void {
    this.deps.post("ready", {}, "");
  }

  attachPuck(handle: PuckHandle | null): void {
    this.puck = handle;
  }

  setShellFields(fields: ShellFields | null): void {
    this.shellFields = fields;
  }

  async receive(message: AppToFrameMessage): Promise<void> {
    switch (message.type) {
      case "init":
        return this.init(message.documentId, message.payload);
      case "replace_site":
        if (this.loading) {
          this.loading = { ...this.loading, rev: message.payload.rev, site: message.payload.site };
          return;
        }
        return this.replaceSite(message.payload.site, message.payload.rev);
      case "set_mode":
        return this.setMode(message.payload.mode);
      case "navigate":
        if (this.loading) {
          if (pageFor(this.loading.site, message.payload.route)) this.loading = { ...this.loading, route: message.payload.route };
          return;
        }
        return this.navigate(message.payload.route);
      case "select":
        return this.select(message.payload.route, message.payload.componentId, message.payload.elementKey ?? null);
      case "set_props": {
        const { componentId, props, route, rev } = message.payload;
        if (this.loading) {
          this.loading = { ...this.loading, rev, site: withComponentProps(this.loading.site, route, componentId, props) };
          return;
        }
        if (this.state.site) this.applyOutsideEdit(withComponentProps(this.state.site, route, componentId, props), route, rev);
        return;
      }
      case "insert_asset": {
        const { componentId, prop, route, url, rev } = message.payload;
        if (this.loading) {
          this.loading = { ...this.loading, rev, site: withAssetAt(this.loading.site, route, componentId, prop, url) };
          return;
        }
        if (this.state.site) this.applyOutsideEdit(withAssetAt(this.state.site, route, componentId, prop, url), route, rev);
        return;
      }
    }
  }

  attachDescriber(describe: ElementDescriber | null): void {
    this.describe = describe ?? NO_ELEMENTS;
  }

  /** Puck reports a page section as selected (a click on the canvas, or the app's `select`). */
  componentSelected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void {
    if (this.state.mode !== "edit") return;
    const target = this.state.route;
    const key = this.takePendingElement(target, componentId);
    const current = this.state.selection;
    if (current && current.target === target && current.componentId === componentId && current.elementKey === key) return;
    this.postSelected(target, componentId, componentType, fields, props, key);
  }

  /** Puck reports nothing selected. The shell's selection is not Puck's to clear. */
  componentDeselected(): void {
    const current = this.state.selection;
    if (!current || current.target === SHELL_TARGET) return;
    this.set({ selection: null });
    this.described = null;
    this.post("deselected", {});
  }

  /** After an outside page, the bridge re-describes the selected section: same id, but its type,
   * fields and values may be new, so `selected` is posted again even though the id did not move.
   * The selected text element stays selected when the section still has it. */
  reselected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void {
    if (this.state.mode !== "edit") return;
    const current = this.state.selection;
    const key = current && current.target === this.state.route && current.componentId === componentId ? current.elementKey : null;
    this.postSelected(this.state.route, componentId, componentType, fields, props, key);
  }

  shellSelected(part: "header" | "footer"): void {
    const site = this.state.site;
    if (this.state.mode !== "edit" || !site?.shell || !this.shellFields) return;
    const current = this.state.selection;
    const samePart = current?.target === SHELL_TARGET && current.componentId === part;
    const pending = this.pendingElement;
    const key = pending ? this.takePendingElement(SHELL_TARGET, part) : samePart ? current!.elementKey : null;
    if (samePart && current!.elementKey === key) return;
    this.puck?.select(null);
    this.postSelected(SHELL_TARGET, part, part === "header" ? "SiteHeader" : "SiteFooter", this.shellFields[part], site.shell[part], key);
  }

  /** A click on the canvas named this text element (or none) of this section or shell part. In the
   * section already selected it is posted at once; otherwise it waits for Puck (or the shell click)
   * to select the section, which then carries it. */
  elementClicked(target: SiteTarget, componentId: string, key: string | null): void {
    if (this.state.mode !== "edit") return;
    const current = this.state.selection;
    if (current && current.target === target && current.componentId === componentId && this.described) {
      this.pendingElement = null;
      if (current.elementKey === key) return;
      const props = this.state.site ? (componentProps(this.state.site, target, componentId) ?? {}) : {};
      this.postSelected(target, componentId, this.described.componentType, this.described.fields, props, key);
      return;
    }
    this.pendingElement = { componentId, key, target };
    // Puck does not select a section for a click on its own editable text (a clone's text slot takes
    // its pointer events), so the section is selected here; on an ordinary click this repeats what
    // Puck does anyway. The shell's selection is the click handler's (shellSelected).
    if (target === this.state.route) this.puck?.select(componentId, { scroll: false });
  }

  /** One `selected`, with the element as the canvas has it now: a key the section no longer has is
   * the whole section. */
  private postSelected(
    target: SiteTarget,
    componentId: string,
    componentType: string,
    fields: FieldDescription[],
    props: Record<string, unknown>,
    key: string | null,
  ): void {
    const described = this.describe(target, componentId, key);
    const element = described.element ? this.withKeptWords(target, componentId, described.element) : null;
    const { elements } = described;
    // Plan 4: the section's own box rides along when the section itself is selected.
    const sectionBox = element ? null : (described.sectionBox ?? null);
    this.set({ selection: { componentId, elementKey: element?.key ?? null, target } });
    this.described = { askedKey: key, componentType, fields, look: lookOf(element, sectionBox), shown: shownElements(element, elements), words: JSON.stringify(element?.words ?? null) };
    this.post("selected", { componentId, componentType, element, elements, fields, props, route: target, ...(sectionBox ? { sectionBox } : {}) });
  }

  /** The element with the words to show: the ones on the canvas now (kept from here on), else the ones
   * kept for this element when the canvas lost them without the marketer doing anything. */
  private withKeptWords(target: SiteTarget, componentId: string, element: ElementSelection): ElementSelection {
    if (element.words) {
      this.kept = { componentId, key: element.key, target, words: element.words };
      this.acted = false;
      return element;
    }
    const kept = this.kept;
    if (kept && !this.acted && kept.target === target && kept.componentId === componentId && kept.key === element.key) {
      return { ...element, words: kept.words };
    }
    this.kept = null;
    return element;
  }

  /** The words kept for the selected element (editor-app highlights them again after a redraw). */
  keptWords(): KeptWords | null {
    return this.kept;
  }

  /** A pointer or key press in the frame: the next time the highlight goes, it is the marketer's doing. */
  userActed(): void {
    this.acted = true;
  }

  /** The canvas's text selection changed (plan 2): `at` is the text element holding highlighted words,
   * or null for none. Words in the selected element are posted when they change; words in another
   * element select it; losing the highlight clears the words only after the marketer's own click or
   * key (a redraw drops the browser's selection too). */
  selectionChanged(at: { target: SiteTarget; componentId: string; key: string } | null): void {
    if (this.state.mode !== "edit" || !this.state.site) return;
    const current = this.state.selection;
    const described = this.described;
    if (!at) {
      if (!this.acted || !current || !described || described.words === "null") return;
      this.kept = null;
      this.repost(current, described);
      return;
    }
    if (current && described && current.target === at.target && current.componentId === at.componentId && current.elementKey === at.key) {
      const { element } = this.describe(at.target, at.componentId, at.key);
      if (!element?.words || JSON.stringify(element.words) === described.words) return;
      this.repost(current, described);
      return;
    }
    this.elementClicked(at.target, at.componentId, at.key);
  }

  private repost(selection: FrameSelection, described: NonNullable<FrameController["described"]>): void {
    const props = this.state.site ? (componentProps(this.state.site, selection.target, selection.componentId) ?? {}) : {};
    this.postSelected(selection.target, selection.componentId, described.componentType, described.fields, props, selection.elementKey);
  }

  /** Describe the selection again once the canvas has settled (editor-app calls it a frame after a
   * selection or a redraw): Puck reports a click's selection while it is still redrawing the section,
   * when its text may not be on the page yet. Posts `selected` again only when WHICH elements the
   * canvas shows changed — the element asked for found now, elements added or gone — never for a look
   * that keeps changing (an animated colour would otherwise post on every frame). */
  refreshSelection(): void {
    const selection = this.state.selection;
    const described = this.described;
    if (this.state.mode !== "edit" || !selection || !described || !this.state.site) return;
    const { element, elements, sectionBox } = this.describe(selection.target, selection.componentId, described.askedKey);
    const watching = this.lookWatch > 0;
    if (watching) this.lookWatch -= 1;
    const lookChanged = watching && lookOf(element, element ? null : (sectionBox ?? null)) !== described.look;
    if (shownElements(element, elements) === described.shown && !lookChanged) return;
    if (lookChanged) this.lookWatch = 0;
    const props = componentProps(this.state.site, selection.target, selection.componentId) ?? {};
    this.postSelected(selection.target, selection.componentId, described.componentType, described.fields, props, described.askedKey);
  }

  private takePendingElement(target: SiteTarget, componentId: string): string | null {
    const pending = this.pendingElement;
    this.pendingElement = null;
    return pending && pending.target === target && pending.componentId === componentId ? pending.key : null;
  }

  annotate(target: SiteTarget, componentId: string, geometry: SiteGeometry): void {
    if (this.state.mode !== "edit") return;
    this.post("annotate", { componentId, geometry, route: target });
  }

  requestAsset(target: SiteTarget, componentId: string, prop: string): void {
    if (this.state.mode !== "edit") return;
    this.post("request_asset", { componentId, prop, route: target });
  }

  shortcut(action: "undo" | "redo"): void {
    this.flushChange();
    this.post("shortcut", { action });
  }

  /** A link clicked in the preview: a page of this site switches page; a link to another website
   * is handed to the app, which opens it in a new tab (the frame may not open tabs, and never
   * navigates itself). Anything else (javascript:, mailto:, an unknown path) does nothing. */
  linkClicked(href: string): void {
    const site = this.state.site;
    if (!site) return;
    const route = internalRoute(href, site);
    if (route) {
      this.navigate(route);
      return;
    }
    if (ExternalHrefSchema.safeParse(href).success) this.post("open_link", { href });
  }

  /** A keystroke in the canvas. Until it reaches the page (and the page reaches the app) the app is
   * told there is unsent work, so a reload asks first. */
  noteTyping(): void {
    if (this.state.mode !== "edit" || !this.state.site) return;
    this.typing = true;
    const generation = ++this.typingGeneration;
    const schedule = this.deps.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
    schedule(() => {
      if (generation !== this.typingGeneration) return;
      this.typing = false;
      this.tellPending();
    }, TYPING_SETTLE_MS);
    this.tellPending();
  }

  /** Puck's onChange: the user edited the page shown. Its rich text is taken in the grammar's form
   * (what TipTap or a paste wrote, cleaned: plan 2), so the save never fails on it. An echo of the page
   * as stored is ignored. */
  pageEdited(route: string, edited: SitePage): void {
    const site = this.state.site;
    if (!site || this.state.mode !== "edit" || route !== this.state.route) return;
    const brand = this.state.brand;
    const page = brand
      ? normalizeRichIn(edited, brand, (type) => this.state.sections.find((section) => section.name === type)?.propsSchema, pageFor(site, route))
      : edited;
    const current = pageFor(site, route);
    if (current && canonicalJson(withoutEmptyZones(current)) === canonicalJson(withoutEmptyZones(page))) return;
    this.set({ site: withPage(site, route, page) });
    this.scheduleChange();
  }

  /** The marketer left a piece of text (focusout): what they typed is sent once the editor has
   * reported it (LEAVE_SETTLE_MS), or at once by anything that flushes sooner. */
  leftText(): void {
    const schedule = this.deps.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
    schedule(() => this.flushChange(), LEAVE_SETTLE_MS);
  }

  flushChange(): void {
    if (!this.changePending) return;
    this.cancelChange();
    if (this.state.site) {
      this.proposedFrom = this.state.rev;
      this.post("changed", { site: this.state.site, baseRev: this.state.rev });
    }
    this.tellPending();
  }

  private async init(documentId: string, payload: AppToFramePayloads["init"]): Promise<void> {
    const generation = ++this.initGeneration;
    this.cancelChange();
    this.dropTyping();
    // The app forgets what it was told when it sends an init, so nothing is said here.
    this.toldPending = false;
    this.proposedFrom = null;
    this.loading = { route: payload.route, rev: payload.rev, site: payload.site };
    this.set({ brand: null, documentId, mode: payload.mode, sections: [], selection: null, site: null, status: "loading" });
    let sections: LoadedSection[];
    try {
      sections = await this.deps.loadSections(payload.sections);
    } catch (error) {
      if (generation !== this.initGeneration) return;
      this.loading = null;
      this.set({ status: "failed" });
      this.post("error", { code: "section_load_failed", message: error instanceof Error ? error.message : String(error) });
      return;
    }
    if (generation !== this.initGeneration || !this.loading) return;
    const shown = this.loading;
    this.loading = null;
    const route = pageFor(shown.site, shown.route) ? shown.route : "/";
    this.set({ brand: payload.brand, mountKey: this.state.mountKey + 1, rev: shown.rev, route, sections, site: shown.site, status: "ready" });
    this.post("navigated", { route });
  }

  private replaceSite(site: SiteDocument, rev: number): void {
    if (!this.state.site) return;
    this.lookWatch = LOOK_WATCH;
    // The copy already on screen (the marketer's unsent typing included): only the revision moves.
    if (canonicalJson(site) === canonicalJson(this.state.site)) {
      this.set({ rev });
      return;
    }
    // A different copy wins over an unsent edit, exactly as the web lane's 409 drops one.
    this.cancelChange();
    this.dropTyping();
    this.tellPending();
    this.proposedFrom = null;
    const route = pageFor(site, this.state.route) ? this.state.route : "/";
    const previous = this.state.selection;
    const selection = previous && componentProps(site, previous.target, previous.componentId) ? previous : null;
    if (route !== this.state.route) {
      this.set({ mountKey: this.state.mountKey + 1, rev, route, selection, site });
      this.post("navigated", { route });
    } else {
      this.set({ rev, selection, site });
      const page = pageFor(site, route);
      if (page) this.puck?.showPage(page, this.selectedPageSection());
    }
    if (previous && !selection) this.post("deselected", {});
  }

  private setMode(mode: EditorMode): void {
    if (mode === this.state.mode) return;
    if (this.state.mode === "edit") this.flushChange();
    const hadSelection = this.state.selection !== null;
    this.set({ mode, selection: mode === "edit" ? this.state.selection : null });
    if (mode !== "edit") this.dropTyping();
    this.tellPending();
    this.puck?.setMode(mode);
    if (mode !== "edit" && hadSelection) this.post("deselected", {});
  }

  private navigate(route: string): void {
    const site = this.state.site;
    if (!site || !pageFor(site, route)) return;
    if (route === this.state.route) {
      this.post("navigated", { route });
      return;
    }
    this.flushChange();
    const hadSelection = this.state.selection !== null;
    this.set({ mountKey: this.state.mountKey + 1, route, selection: null });
    this.post("navigated", { route });
    if (hadSelection) this.post("deselected", {});
  }

  private select(target: SiteTarget, componentId: string | null, elementKey: string | null): void {
    if (this.state.mode !== "edit" || !this.state.site) return;
    if (componentId === null) {
      this.puck?.select(null);
      this.pendingElement = null;
      if (this.state.selection) {
        this.set({ selection: null });
        this.described = null;
        this.post("deselected", {});
      }
      return;
    }
    // The element rides the click path: in the section already selected it is posted at once,
    // otherwise the section's selection (Puck's, or the shell's) carries it.
    this.elementClicked(target, componentId, elementKey);
    if (target === SHELL_TARGET) {
      if (componentId === "header" || componentId === "footer") this.shellSelected(componentId);
      return;
    }
    if (target === this.state.route) this.puck?.select(componentId);
  }

  /** A dock patch: applied over the copy on screen, so the marketer's unsent typing is kept and
   * the next proposal carries both, from the patch's revision. */
  private applyOutsideEdit(site: SiteDocument, target: SiteTarget, rev: number): void {
    this.reproposeOver(rev);
    this.lookWatch = LOOK_WATCH;
    if (site === this.state.site) {
      this.set({ rev });
      return;
    }
    this.set({ rev, site });
    if (target === this.state.route) {
      const page = pageFor(site, target);
      if (page) this.puck?.showPage(page, this.selectedPageSection());
    }
  }

  /** A patch at a newer revision than the last proposal's base: the app refuses a proposal its own
   * patch overtook, but the patch was applied over the canvas, which still shows that typing. So the
   * frame proposes again (debounced), from the patch's revision; if the app had already taken it, the
   * repeat is the app's own copy and changes nothing. */
  private reproposeOver(rev: number): void {
    if (this.proposedFrom === null || this.proposedFrom >= rev || this.state.mode !== "edit") return;
    this.proposedFrom = null;
    this.scheduleChange();
  }

  private selectedPageSection(): string | null {
    const selection = this.state.selection;
    return selection && selection.target !== SHELL_TARGET ? selection.componentId : null;
  }

  private scheduleChange(): void {
    this.cancelTimer();
    this.changePending = true;
    const schedule = this.deps.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
    this.timer = schedule(() => this.flushChange(), CHANGE_DEBOUNCE_MS);
    this.tellPending();
  }

  private dropTyping(): void {
    this.typing = false;
    this.typingGeneration += 1;
  }

  /** Tell the app when unsent work starts or stops (only on a change, so not once per keystroke). */
  private tellPending(): void {
    const pending = this.state.mode === "edit" && (this.typing || this.changePending);
    if (pending === this.toldPending) return;
    this.toldPending = pending;
    this.post("pending", { pending });
  }

  private cancelTimer(): void {
    if (this.timer === null) return;
    (this.deps.cancel ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>)))(this.timer);
    this.timer = null;
  }

  private cancelChange(): void {
    this.cancelTimer();
    this.changePending = false;
  }

  private post<T extends FrameToAppType>(type: T, payload: FrameToAppPayloads[T]): void {
    this.deps.post(type, payload, this.state.documentId);
  }

  private set(patch: Partial<FrameState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}

/** Puck reports `zones: {}` for a page stored without zones; the two are the same page. */
function withoutEmptyZones(page: SitePage): SitePage {
  if (page.zones && Object.keys(page.zones).length === 0) {
    const copy = { ...page };
    delete copy.zones;
    return copy;
  }
  return page;
}
