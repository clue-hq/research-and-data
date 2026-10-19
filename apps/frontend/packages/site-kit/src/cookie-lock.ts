// Review K3-7, founder option 1 (2026-10-19). Every workspace's editor shares one registrable domain
// (edit.deeppresence.ai) and every workspace's published pages another (cluehq.page); neither is on the
// Public Suffix List. A cookie that one workspace's section code sets on the shared domain would reach
// every other workspace's editor or pages in that browser (enough of them and those requests are
// refused). Our servers never set cookies there, so the page takes the ability away from the code it
// runs: lockCookies() runs before any section loads, and from then on writing a cookie does nothing
// and reading one gives "".
//
// It covers this page and every same-origin frame or window the code can reach: a new frame has its
// own untouched `document.cookie`, so each one is locked the moment it is added to the page, read
// through `contentWindow` / `contentDocument`, finishes loading, or opened with `window.open`.

type Realm = Window & typeof globalThis;

const NO_COOKIE: PropertyDescriptor = { configurable: false, enumerable: true, get: () => "", set: () => undefined };
const locked = new WeakSet<object>();

/** Lock this window and every frame it can reach. Safe to call more than once. */
export function lockCookies(realm: Realm = window): void {
  lockRealm(realm);
}

function lockRealm(realm: Realm | null | undefined): void {
  if (!realm) return;
  try {
    if (locked.has(realm)) {
      lockFrames(realm);
      return;
    }
    // A cross-origin window throws here; it cannot set this domain's cookies anyway.
    const documentProto = realm.Document.prototype;
    Object.defineProperty(documentProto, "cookie", NO_COOKIE);
    try {
      Object.defineProperty(realm, "cookieStore", { configurable: false, enumerable: true, value: undefined, writable: false });
    } catch {
      // Already locked or not there.
    }
    locked.add(realm);
    guardFrames(realm);
    lockFrames(realm);
  } catch {
    // Not reachable from here (another origin, or a window already gone).
  }
}

/** Lock every frame the window has now. */
function lockFrames(realm: Realm): void {
  try {
    for (let index = 0; index < realm.frames.length; index += 1) lockRealm(realm.frames[index] as Realm);
  } catch {
    // A frame went away mid-loop.
  }
}

function wrapMethod(proto: object | undefined, name: string, after: (self: unknown, result: unknown) => void): void {
  if (!proto) return;
  const descriptor = Object.getOwnPropertyDescriptor(proto, name);
  const original = descriptor?.value;
  if (typeof original !== "function") return;
  Object.defineProperty(proto, name, {
    ...descriptor,
    value: function wrapped(this: unknown, ...args: unknown[]) {
      const result = original.apply(this, args);
      after(this, result);
      return result;
    },
  });
}

function wrapSetter(proto: object | undefined, name: string, after: () => void): void {
  if (!proto) return;
  const descriptor = Object.getOwnPropertyDescriptor(proto, name);
  const set = descriptor?.set;
  if (!descriptor || !set) return;
  Object.defineProperty(proto, name, {
    ...descriptor,
    set(this: unknown, value: unknown) {
      set.call(this, value);
      after();
    },
  });
}

function wrapGetter(proto: object | undefined, name: string, after: (value: unknown) => void): void {
  if (!proto) return;
  const descriptor = Object.getOwnPropertyDescriptor(proto, name);
  const get = descriptor?.get;
  if (!descriptor || !get) return;
  Object.defineProperty(proto, name, {
    ...descriptor,
    get(this: unknown) {
      const value = get.call(this);
      after(value);
      return value;
    },
  });
}

/** Every way this window's code adds a frame, reaches one, or opens a window locks it at once. */
function guardFrames(realm: Realm): void {
  const relock = () => lockFrames(realm);
  for (const name of ["appendChild", "insertBefore", "replaceChild"]) wrapMethod(realm.Node?.prototype, name, relock);
  for (const name of ["append", "prepend", "after", "before", "replaceWith", "replaceChildren", "insertAdjacentElement", "insertAdjacentHTML", "setHTMLUnsafe"]) {
    wrapMethod(realm.Element?.prototype, name, relock);
  }
  for (const name of ["append", "prepend", "replaceChildren"]) wrapMethod(realm.Document?.prototype, name, relock);
  for (const name of ["write", "writeln"]) wrapMethod(realm.Document?.prototype, name, relock);
  for (const name of ["insertNode", "surroundContents"]) wrapMethod(realm.Range?.prototype, name, relock);
  for (const name of ["innerHTML", "outerHTML"]) wrapSetter(realm.Element?.prototype, name, relock);
  wrapSetter(realm.ShadowRoot?.prototype, "innerHTML", relock);
  const lockValue = (value: unknown) => {
    if (!value || typeof value !== "object") return;
    lockRealm(("defaultView" in value ? (value as Document).defaultView : value) as Realm);
  };
  for (const element of [realm.HTMLIFrameElement, realm.HTMLFrameElement, realm.HTMLObjectElement]) {
    wrapGetter(element?.prototype, "contentWindow", lockValue);
    wrapGetter(element?.prototype, "contentDocument", lockValue);
  }
  wrapMethod(realm, "open", (_self, opened) => lockRealm(opened as Realm));
  // A frame that loads a new document gets a new window: locked when it has loaded, before the
  // frame's own load listeners run (capture on this window comes first).
  realm.addEventListener("load", relock, true);
}
