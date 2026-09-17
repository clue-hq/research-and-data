import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CHAT_SHELL_INSPECTOR_SELECTIONS,
  type ChatShellArtifactKind,
} from "./chat-shell";
import {
  chatSurfacePaneParams,
  chatSurfaceUrlState,
  type ChatSurfacePaneState,
  type ChatSurfaceUrlState,
} from "./chat-surface-params";

test("no surface param leaves the panel closed on the conversation", () => {
  assert.deepEqual(chatSurfaceUrlState({}), {
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: false,
    surface: undefined,
  });
});

test("surface=gallery opens the rail on the gallery", () => {
  const state = chatSurfaceUrlState({ surface: "gallery" });
  assert.equal(state.panelOpen, true);
  assert.equal(state.surface, "gallery");
  assert.equal(state.editing, false);
});

test("Plan round-trips without artifact editing vocabulary", () => {
  assert.deepEqual(chatSurfaceUrlState({ surface: "plan", edit: "1" }), {
    surface: "plan", panelOpen: true, editing: false, inspectorSelection: "canvas",
  });
  assert.deepEqual(chatSurfacePaneParams(paneState({ surface: "plan", panelOpen: true, editing: true, inspectorSelection: "text" })), {
    surface: "plan", edit: undefined, selection: undefined,
  });
});

test("surface=target-accounts opens the rail on the target-accounts surface", () => {
  const state = chatSurfaceUrlState({ edit: "1", surface: "target-accounts" });
  assert.equal(state.panelOpen, true);
  assert.equal(state.surface, "target-accounts");
  // edit/selection are artifact-surface vocabulary and are ignored here.
  assert.equal(state.editing, false);
});

test("surface=web|ad opens the artifact surface; edit=1 enters editing", () => {
  const web = chatSurfaceUrlState({ edit: "1", surface: "web" });
  assert.equal(web.panelOpen, true);
  assert.equal(web.surface, "artifact");
  assert.equal(web.editing, true);

  const ad = chatSurfaceUrlState({ surface: "ad" });
  assert.equal(ad.surface, "artifact");
  assert.equal(ad.editing, false);
});

test("selection parses through the inspector vocabulary with canvas fallback", () => {
  assert.equal(
    chatSurfaceUrlState({ selection: "text", surface: "web" }).inspectorSelection,
    "text",
  );
  assert.equal(
    chatSurfaceUrlState({ selection: "bogus", surface: "web" }).inspectorSelection,
    "canvas",
  );
});

test("edit with an unknown or absent surface never opens the rail or enters editing", () => {
  const unknown = chatSurfaceUrlState({ edit: "1", surface: "bogus" });
  assert.equal(unknown.panelOpen, false);
  assert.equal(unknown.editing, false);

  const absent = chatSurfaceUrlState({ edit: "1" });
  assert.equal(absent.panelOpen, false);
  assert.equal(absent.editing, false);
});

test("surface=chat is the accepted alias of the conversation-only resting state", () => {
  assert.deepEqual(chatSurfaceUrlState({ surface: "chat" }), chatSurfaceUrlState({}));
  assert.deepEqual(
    chatSurfaceUrlState({ edit: "1", selection: "text", surface: "chat" }),
    chatSurfaceUrlState({ edit: "1", selection: "text" }),
  );
});

// --- write-back (slice 5): the pane state a user reaches serializes back into
// the same ?surface=/edit=/selection= vocabulary the parse above reads.

function paneState(
  overrides: Partial<ChatSurfacePaneState> = {},
): ChatSurfacePaneState {
  return {
    artifactKind: null,
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: false,
    rawSurface: undefined,
    surface: "gallery",
    ...overrides,
  };
}

/** state → params → state, the plan's named round-trip gate. */
function roundTrip(state: ChatSurfacePaneState): ChatSurfaceUrlState {
  const params = chatSurfacePaneParams(state);
  return chatSurfaceUrlState({
    edit: params.edit,
    selection: params.selection,
    surface: params.surface,
  });
}

test("a closed rail canonicalizes to the clean URL and round-trips", () => {
  const closed = paneState({
    // Even a remembered selection/editing flag stays out of the URL while the
    // rail is closed: the resting state IS the bare pathname.
    editing: true,
    inspectorSelection: "text",
    rawSurface: "web",
  });
  assert.deepEqual(chatSurfacePaneParams(closed), {
    edit: undefined,
    selection: undefined,
    surface: undefined,
  });
  assert.deepEqual(roundTrip(closed), {
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: false,
    surface: undefined,
  });
  // …and the inbound alias parses to exactly that same state.
  assert.deepEqual(chatSurfaceUrlState({ surface: "chat" }), roundTrip(closed));
});

test("an open gallery serializes surface=gallery and carries no edit or selection", () => {
  const gallery = paneState({
    editing: true,
    inspectorSelection: "image",
    panelOpen: true,
    surface: "gallery",
  });
  assert.deepEqual(chatSurfacePaneParams(gallery), {
    edit: undefined,
    selection: undefined,
    surface: "gallery",
  });
  assert.deepEqual(roundTrip(gallery), {
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: true,
    surface: "gallery",
  });
});

test("the target-accounts surface serializes its own name and round-trips", () => {
  const targetAccounts = paneState({
    editing: true,
    inspectorSelection: "image",
    panelOpen: true,
    rawSurface: "web",
    surface: "target-accounts",
  });
  assert.deepEqual(chatSurfacePaneParams(targetAccounts), {
    edit: undefined,
    selection: undefined,
    surface: "target-accounts",
  });
  assert.deepEqual(roundTrip(targetAccounts), {
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: true,
    surface: "target-accounts",
  });
});

test("an open artifact serializes its own kind and round-trips (web and ad)", () => {
  for (const kind of ["web", "ad"] as ChatShellArtifactKind[]) {
    const open = paneState({ artifactKind: kind, panelOpen: true, surface: "artifact" });
    assert.deepEqual(chatSurfacePaneParams(open), {
      edit: undefined,
      selection: undefined,
      surface: kind,
    });
    assert.deepEqual(roundTrip(open), {
      editing: false,
      inspectorSelection: "canvas",
      panelOpen: true,
      surface: "artifact",
    });
  }
});

test("editing an artifact serializes edit=1", () => {
  const editing = paneState({
    artifactKind: "web",
    editing: true,
    panelOpen: true,
    surface: "artifact",
  });
  assert.deepEqual(chatSurfacePaneParams(editing), {
    edit: "1",
    selection: undefined,
    surface: "web",
  });
  assert.deepEqual(roundTrip(editing), {
    editing: true,
    inspectorSelection: "canvas",
    panelOpen: true,
    surface: "artifact",
  });
});

test("every non-default inspector selection round-trips while editing", () => {
  for (const selection of CHAT_SHELL_INSPECTOR_SELECTIONS) {
    if (selection === "canvas") continue;
    const state = paneState({
      artifactKind: "web",
      editing: true,
      inspectorSelection: selection,
      panelOpen: true,
      surface: "artifact",
    });
    assert.deepEqual(chatSurfacePaneParams(state), {
      edit: "1",
      selection,
      surface: "web",
    });
    assert.deepEqual(roundTrip(state), {
      editing: true,
      inspectorSelection: selection,
      panelOpen: true,
      surface: "artifact",
    });
  }
});

test("the canvas selection is the parse default and stays out of the URL", () => {
  assert.equal(
    chatSurfacePaneParams(
      paneState({
        artifactKind: "web",
        editing: true,
        inspectorSelection: "canvas",
        panelOpen: true,
        surface: "artifact",
      }),
    ).selection,
    undefined,
  );
});

test("a selection without editing never reaches the URL", () => {
  assert.deepEqual(
    chatSurfacePaneParams(
      paneState({
        artifactKind: "web",
        editing: false,
        inspectorSelection: "button",
        panelOpen: true,
        surface: "artifact",
      }),
    ),
    { edit: undefined, selection: undefined, surface: "web" },
  );
});

test("an artifact surface with no open artifact keeps the incoming kind, else web", () => {
  const withRawAd = paneState({
    editing: true,
    panelOpen: true,
    rawSurface: "ad",
    surface: "artifact",
  });
  assert.equal(chatSurfacePaneParams(withRawAd).surface, "ad");

  const withRawGarbage = paneState({
    panelOpen: true,
    rawSurface: "gallery",
    surface: "artifact",
  });
  assert.equal(chatSurfacePaneParams(withRawGarbage).surface, "web");

  const withNoRaw = paneState({ panelOpen: true, surface: "artifact" });
  assert.equal(chatSurfacePaneParams(withNoRaw).surface, "web");

  // A real open artifact always wins over the incoming raw value.
  assert.equal(
    chatSurfacePaneParams(
      paneState({
        artifactKind: "web",
        panelOpen: true,
        rawSurface: "ad",
        surface: "artifact",
      }),
    ).surface,
    "web",
  );
});

test("the superseded ?artifact= param is never emitted", () => {
  const params = chatSurfacePaneParams(
    paneState({
      artifactKind: "web",
      editing: true,
      inspectorSelection: "text",
      panelOpen: true,
      surface: "artifact",
    }),
  );
  assert.deepEqual(Object.keys(params).sort(), ["edit", "selection", "surface"]);
});
