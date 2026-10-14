import type { BrandData } from "@clue/site-kit";
import type {
  AppToFrameMessage,
  AppToFramePayloads,
  EditorMode,
  FieldDescription,
  FrameToAppPayloads,
  FrameToAppType,
  SiteGeometry,
} from "@clue/site-kit/editor-protocol";
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

export type FrameStatus = "booting" | "loading" | "ready" | "failed";

export interface FrameSelection {
  componentId: string;
  target: SiteTarget;
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
  select(componentId: string | null): void;
  setMode(mode: EditorMode): void;
  showPage(page: SitePage): void;
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
  private shellFields: ShellFields | null = null;
  private timer: unknown = null;
  private changePending = false;
  private initGeneration = 0;
  /** While an init loads its agent sections, the copy it will show: every update that arrives
   * meanwhile is applied here instead of being dropped (review finding K3-5). */
  private loading: { site: SiteDocument; rev: number; route: string } | null = null;

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
        return this.select(message.payload.route, message.payload.componentId);
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

  /** Puck reports a page section as selected (a click on the canvas, or the app's `select`). */
  componentSelected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void {
    if (this.state.mode !== "edit") return;
    const current = this.state.selection;
    if (current && current.target === this.state.route && current.componentId === componentId) return;
    this.set({ selection: { componentId, target: this.state.route } });
    this.post("selected", { componentId, componentType, fields, props, route: this.state.route });
  }

  /** Puck reports nothing selected. The shell's selection is not Puck's to clear. */
  componentDeselected(): void {
    const current = this.state.selection;
    if (!current || current.target === SHELL_TARGET) return;
    this.set({ selection: null });
    this.post("deselected", {});
  }

  shellSelected(part: "header" | "footer"): void {
    const site = this.state.site;
    if (this.state.mode !== "edit" || !site?.shell || !this.shellFields) return;
    this.puck?.select(null);
    this.set({ selection: { componentId: part, target: SHELL_TARGET } });
    this.post("selected", {
      componentId: part,
      componentType: part === "header" ? "SiteHeader" : "SiteFooter",
      fields: this.shellFields[part],
      props: site.shell[part],
      route: SHELL_TARGET,
    });
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

  linkClicked(href: string): void {
    const site = this.state.site;
    if (!site) return;
    const route = internalRoute(href, site);
    if (route) this.navigate(route);
  }

  /** Puck's onChange: the user edited the page shown. An echo of the page as stored is ignored. */
  pageEdited(route: string, page: SitePage): void {
    const site = this.state.site;
    if (!site || this.state.mode !== "edit" || route !== this.state.route) return;
    const current = pageFor(site, route);
    if (current && canonicalJson(withoutEmptyZones(current)) === canonicalJson(withoutEmptyZones(page))) return;
    this.set({ site: withPage(site, route, page) });
    this.scheduleChange();
  }

  flushChange(): void {
    if (!this.changePending) return;
    this.cancelChange();
    if (this.state.site) this.post("changed", { site: this.state.site, baseRev: this.state.rev });
  }

  private async init(documentId: string, payload: AppToFramePayloads["init"]): Promise<void> {
    const generation = ++this.initGeneration;
    this.cancelChange();
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
    // The copy already on screen (the marketer's unsent typing included): only the revision moves.
    if (canonicalJson(site) === canonicalJson(this.state.site)) {
      this.set({ rev });
      return;
    }
    // A different copy wins over an unsent edit, exactly as the web lane's 409 drops one.
    this.cancelChange();
    const route = pageFor(site, this.state.route) ? this.state.route : "/";
    const previous = this.state.selection;
    const selection = previous && componentProps(site, previous.target, previous.componentId) ? previous : null;
    if (route !== this.state.route) {
      this.set({ mountKey: this.state.mountKey + 1, rev, route, selection, site });
      this.post("navigated", { route });
    } else {
      this.set({ rev, selection, site });
      const page = pageFor(site, route);
      if (page) this.puck?.showPage(page);
    }
    if (previous && !selection) this.post("deselected", {});
  }

  private setMode(mode: EditorMode): void {
    if (mode === this.state.mode) return;
    if (this.state.mode === "edit") this.flushChange();
    const hadSelection = this.state.selection !== null;
    this.set({ mode, selection: mode === "edit" ? this.state.selection : null });
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

  private select(target: SiteTarget, componentId: string | null): void {
    if (this.state.mode !== "edit" || !this.state.site) return;
    if (componentId === null) {
      this.puck?.select(null);
      if (this.state.selection) {
        this.set({ selection: null });
        this.post("deselected", {});
      }
      return;
    }
    if (target === SHELL_TARGET) {
      if (componentId === "header" || componentId === "footer") this.shellSelected(componentId);
      return;
    }
    if (target === this.state.route) this.puck?.select(componentId);
  }

  /** A dock patch: applied over the copy on screen, so the marketer's unsent typing is kept and
   * the next proposal carries both, from the patch's revision. */
  private applyOutsideEdit(site: SiteDocument, target: SiteTarget, rev: number): void {
    if (site === this.state.site) {
      this.set({ rev });
      return;
    }
    this.set({ rev, site });
    if (target === this.state.route) {
      const page = pageFor(site, target);
      if (page) this.puck?.showPage(page);
    }
  }

  private scheduleChange(): void {
    this.cancelTimer();
    this.changePending = true;
    const schedule = this.deps.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
    this.timer = schedule(() => this.flushChange(), CHANGE_DEBOUNCE_MS);
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
