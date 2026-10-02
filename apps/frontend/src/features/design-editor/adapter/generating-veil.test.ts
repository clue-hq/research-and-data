import assert from "node:assert/strict";
import { it } from "node:test";
import {
  initialVeilState,
  nextVeilState,
  type VeilRenderKind,
  type VeilState,
} from "./generating-veil";

/**
 * The hold rule, exercised the way the stage actually drives it: a SEQUENCE of
 * render passes, each carrying the busy signal, the reload token, the render
 * state, and the document open in the pane at that moment. Every case asserts
 * the `active` trajectory across the sequence — a single-pass assertion could
 * not tell "held through the refetch" apart from "lifted and came back", which
 * is precisely the flash the rule exists to prevent.
 */

interface Pass {
  generating: boolean;
  reloadToken: number;
  renderKind: VeilRenderKind;
  documentId: string | null;
}

/** Fold a sequence, returning the `active` value each pass settled on. Every
 * pass is applied TWICE — the second application must be an exact no-op, which
 * is the idempotency the render-time adjust-state pattern needs to converge. */
function trajectory(passes: Pass[]): boolean[] {
  let state: VeilState = initialVeilState;
  const active: boolean[] = [];
  for (const pass of passes) {
    state = nextVeilState(state, pass);
    assert.equal(
      nextVeilState(state, pass),
      state,
      "re-applying the same input must return the same object",
    );
    active.push(state.active);
  }
  return active;
}

const DOC = "doc_a";

it("rule 1: the veil goes on with the busy signal and stays on through the turn", () => {
  const active = trajectory([
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    { generating: true, reloadToken: 4, renderKind: "loading", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, true, true]);
});

it("rule 1: the start token is the one the turn began against, not a later one", () => {
  // A mid-turn refresh bumps the token while the agent is still working. The
  // remembered token must stay the one generating first saw, or rule 2 would
  // read the turn's own refresh as "nothing landed".
  let state = nextVeilState(initialVeilState, {
    generating: true,
    reloadToken: 4,
    renderKind: "ready",
    documentId: DOC,
  });
  state = nextVeilState(state, {
    generating: true,
    reloadToken: 5,
    renderKind: "loading",
    documentId: DOC,
  });
  assert.equal(state.startToken, 4);
  assert.equal(state.active, true);
});

it("rule 2a: a turn that produced no canvas refresh lifts the veil at once", () => {
  const active = trajectory([
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    // Terminal frame. Neither the token nor the document moved: the turn failed
    // or only spoke.
    { generating: false, reloadToken: 4, renderKind: "ready", documentId: DOC },
    { generating: false, reloadToken: 4, renderKind: "ready", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, true, false, false]);
});

it("rule 2a: no refresh lifts even while the render is loading for its own reasons", () => {
  // The canvas identity is the tell, never the render state. A render can be
  // `loading` for reasons that have nothing to do with the turn (the first
  // open, an Edit toggle refetching into the same iframe), and a turn that
  // wrote nothing has no refresh coming — waiting on this load would strand the
  // blur until the NEXT turn.
  const active = trajectory([
    { generating: true, reloadToken: 4, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 4, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 4, renderKind: "loading", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, false, false]);
});

it("rule 2b: with a refresh in flight the veil holds until the new render is done", () => {
  const active = trajectory([
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    // The canvas-refresh frame lands mid-turn: new token, render restarts.
    { generating: true, reloadToken: 5, renderKind: "loading", documentId: DOC },
    // Terminal frame arrives while the new page is still fetching — the veil
    // must NOT lift here, or the old page flashes through.
    { generating: false, reloadToken: 5, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 5, renderKind: "loading", documentId: DOC },
    // The new page is up. Only now does the blur come off.
    { generating: false, reloadToken: 5, renderKind: "ready", documentId: DOC },
    { generating: false, reloadToken: 5, renderKind: "ready", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, true, true, true, false, false]);
});

it("rule 2b: an error or empty render lifts the veil just as ready does", () => {
  for (const kind of ["error", "empty"] as const) {
    const active = trajectory([
      { generating: true, reloadToken: 1, renderKind: "ready", documentId: DOC },
      { generating: false, reloadToken: 2, renderKind: "loading", documentId: DOC },
      { generating: false, reloadToken: 2, renderKind: kind, documentId: DOC },
    ]);
    assert.deepEqual(active, [true, true, false], kind);
  }
});

it("rule 2b: settling ends and the veil is fully disarmed", () => {
  let state = nextVeilState(initialVeilState, {
    generating: true,
    reloadToken: 1,
    renderKind: "ready",
    documentId: DOC,
  });
  state = nextVeilState(state, {
    generating: false,
    reloadToken: 2,
    renderKind: "loading",
    documentId: DOC,
  });
  assert.deepEqual(state, {
    active: true,
    startToken: 1,
    startDocumentId: DOC,
    settling: true,
  });
  state = nextVeilState(state, {
    generating: false,
    reloadToken: 2,
    renderKind: "ready",
    documentId: DOC,
  });
  assert.deepEqual(state, initialVeilState);
});

it("rule 3: an idle stage never raises the veil, whatever the render is doing", () => {
  const active = trajectory([
    { generating: false, reloadToken: 0, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 0, renderKind: "ready", documentId: DOC },
    // An inspector write bumps the token with no turn in flight: still nothing.
    { generating: false, reloadToken: 1, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 1, renderKind: "ready", documentId: DOC },
    // Nor does opening a document out of the gallery.
    { generating: false, reloadToken: 1, renderKind: "loading", documentId: "doc_b" },
  ]);
  assert.deepEqual(active, [false, false, false, false, false]);
});

it("edge: a refresh that finished before the turn ended lifts on the next pass", () => {
  const active = trajectory([
    { generating: true, reloadToken: 4, renderKind: "ready", documentId: DOC },
    { generating: true, reloadToken: 5, renderKind: "loading", documentId: DOC },
    // The page is already up while the agent is still wrapping up.
    { generating: true, reloadToken: 5, renderKind: "ready", documentId: DOC },
    // Terminal frame: the canvas moved and the render is done — lift, no hold,
    // and no flash, because the sharp page underneath is the NEW one.
    { generating: false, reloadToken: 5, renderKind: "ready", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, true, true, false]);
});

it("a second turn starting while the first settles re-arms against the new canvas", () => {
  let state = nextVeilState(initialVeilState, {
    generating: true,
    reloadToken: 1,
    renderKind: "ready",
    documentId: DOC,
  });
  state = nextVeilState(state, {
    generating: false,
    reloadToken: 2,
    renderKind: "loading",
    documentId: DOC,
  });
  assert.equal(state.settling, true);
  state = nextVeilState(state, {
    generating: true,
    reloadToken: 2,
    renderKind: "loading",
    documentId: DOC,
  });
  assert.deepEqual(state, {
    active: true,
    startToken: 2,
    startDocumentId: DOC,
    settling: false,
  });
  // ...and that new turn's own no-refresh ending lifts cleanly.
  state = nextVeilState(state, {
    generating: false,
    reloadToken: 2,
    renderKind: "ready",
    documentId: DOC,
  });
  assert.deepEqual(state, initialVeilState);
});

it("the FIRST landing page: a document born during the turn is a refresh to wait out", () => {
  // The handover's done-when #1, and the whole reason the veil is hosted on the
  // stage rather than inside the canvas: at leg-open there is no web document
  // at all, so there is no reload token to move. The document being BORN is the
  // refresh, and its first render must be waited out exactly like a reload —
  // otherwise the blur lifts onto the empty state a beat before the page lands.
  const active = trajectory([
    { generating: true, reloadToken: 0, renderKind: "empty", documentId: null },
    { generating: true, reloadToken: 0, renderKind: "empty", documentId: null },
    // The artifact appears mid-turn and its first render starts.
    { generating: true, reloadToken: 0, renderKind: "loading", documentId: DOC },
    // Terminal frame while the page is still rendering: hold.
    { generating: false, reloadToken: 0, renderKind: "loading", documentId: DOC },
    { generating: false, reloadToken: 0, renderKind: "loading", documentId: DOC },
    // The page is up.
    { generating: false, reloadToken: 0, renderKind: "ready", documentId: DOC },
  ]);
  assert.deepEqual(active, [true, true, true, true, true, false]);
});

it("a turn that never produced a document lifts the veil immediately", () => {
  // The same first-request shape, but the turn failed or only spoke: no
  // document was ever born, so nothing is coming and the empty state must come
  // back at once rather than staying blurred behind a permanent veil.
  const active = trajectory([
    { generating: true, reloadToken: 0, renderKind: "empty", documentId: null },
    { generating: true, reloadToken: 0, renderKind: "empty", documentId: null },
    { generating: false, reloadToken: 0, renderKind: "empty", documentId: null },
    { generating: false, reloadToken: 0, renderKind: "empty", documentId: null },
  ]);
  assert.deepEqual(active, [true, true, false, false]);
});
