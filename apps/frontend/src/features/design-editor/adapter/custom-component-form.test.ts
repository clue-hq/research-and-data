import assert from "node:assert/strict";
import test from "node:test";
import type {
  CustomComponentPropSchema,
  LoadedWebDocument,
  WebNode,
} from "../engine/webDocuments";
import {
  CUSTOM_COMPONENT_ARTIFACT,
  CUSTOM_COMPONENT_NODE,
  CUSTOM_COMPONENT_PAGE,
  CUSTOM_COMPONENT_PAGE_ID,
} from "./__fixtures__/web-custom-component";
import {
  CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL,
  customComponentControlKind,
  customComponentDraft,
  customComponentDraftCommit,
  customComponentDraftKeyAction,
  customComponentDraftKeySuppressesBlur,
  customComponentFields,
  customComponentPropInputId,
  customComponentPropLabel,
  customComponentPropsToOperation,
  customComponentPropsUpdate,
  customComponentSelectCommit,
  customComponentSelectLabel,
  customComponentSelectOptions,
} from "./custom-component-form";

// W4.7 (contract item 34): the pure decisions behind the custom-component
// props form — which control a schema field gets, what it is labelled, what one
// settled draft commits, and the whole-props payload that reaches
// `set_node_props`. The form itself is presentation (`web-inspector.tsx`'s
// ContainerControls region) and this repo's runner has no React renderer
// (`tsx --test`, node:test), so the decisions live here where they are
// testable — the same extraction pattern W4.8a/b used for the rich-text
// toolbar and the range-bound Link-to.
//
// Every case runs against the wire-true artifact/node harvested from the seeded
// lane-C doc, so a schema shape the real compiler never emits cannot pass here.

const properties = CUSTOM_COMPONENT_ARTIFACT.manifest.props_schema.properties;

// --- control dispatch (source `CustomPropControl`, the scout §6 table) -------

test("a boolean schema field takes the checkbox", () => {
  assert.equal(customComponentControlKind(properties.showBadge), "checkbox");
});

test("a string field with a non-empty enum takes the select", () => {
  assert.equal(customComponentControlKind(properties.accent), "select");
});

test("a number field takes the number input", () => {
  assert.equal(customComponentControlKind(properties.planCount), "number");
});

test("a plain string field takes the text input", () => {
  assert.equal(customComponentControlKind(properties.headline), "text");
});

test("a string field with an EMPTY enum falls back to the text input", () => {
  const schema: CustomComponentPropSchema = { type: "string", enum: [] };
  assert.equal(customComponentControlKind(schema), "text");
});

// --- label + input id (source :56-59) ---------------------------------------

test("a camelCase prop name splits into words", () => {
  assert.equal(customComponentPropLabel("planCount"), "plan Count");
});

test("underscores and dashes collapse to single spaces", () => {
  assert.equal(customComponentPropLabel("cta__label-text"), "cta label text");
});

test("the input id sanitises everything outside [A-Za-z0-9_-]", () => {
  assert.equal(
    customComponentPropInputId("plan.count value"),
    "custom-component-prop-plan-count-value",
  );
});

// --- the field list the section iterates ------------------------------------

test("the fields follow props_schema order, one per property", () => {
  const fields = customComponentFields(
    CUSTOM_COMPONENT_ARTIFACT,
    CUSTOM_COMPONENT_NODE.props ?? {},
  );
  assert.deepEqual(
    fields.map((field) => `${field.name}:${field.kind}`),
    [
      "accent:select",
      "headline:text",
      "planCount:number",
      "showBadge:checkbox",
    ],
  );
});

test("each field carries the node's live value and its string draft", () => {
  const fields = customComponentFields(
    CUSTOM_COMPONENT_ARTIFACT,
    CUSTOM_COMPONENT_NODE.props ?? {},
  );
  const planCount = fields.find((field) => field.name === "planCount");
  assert.equal(planCount?.value, 3);
  assert.equal(planCount?.draft, "3");
  const showBadge = fields.find((field) => field.name === "showBadge");
  assert.equal(showBadge?.value, true);
});

test("a prop absent from the node has no value and an empty draft — the manifest default is NOT substituted", () => {
  const fields = customComponentFields(CUSTOM_COMPONENT_ARTIFACT, {});
  const headline = fields.find((field) => field.name === "headline");
  assert.equal(headline?.value, undefined);
  assert.equal(headline?.draft, "");
});

test("required comes from props_schema.required, and only it earns the star", () => {
  const artifact = {
    ...CUSTOM_COMPONENT_ARTIFACT,
    manifest: {
      ...CUSTOM_COMPONENT_ARTIFACT.manifest,
      props_schema: {
        ...CUSTOM_COMPONENT_ARTIFACT.manifest.props_schema,
        required: ["headline"],
      },
    },
  };
  const fields = customComponentFields(artifact, {});
  const headline = fields.find((field) => field.name === "headline");
  const accent = fields.find((field) => field.name === "accent");
  assert.equal(headline?.required, true);
  assert.equal(headline?.displayLabel, "headline *");
  assert.equal(headline?.ariaLabel, "headline custom component prop");
  assert.equal(accent?.required, false);
  assert.equal(accent?.displayLabel, "accent");
});

test("an artifact with no editable properties yields no fields", () => {
  const artifact = {
    ...CUSTOM_COMPONENT_ARTIFACT,
    manifest: {
      ...CUSTOM_COMPONENT_ARTIFACT.manifest,
      props_schema: {
        ...CUSTOM_COMPONENT_ARTIFACT.manifest.props_schema,
        properties: {},
      },
    },
  };
  assert.deepEqual(customComponentFields(artifact, {}), []);
});

// --- the enum select (source :86-110) ---------------------------------------

test("an OPTIONAL enum with no value on the node offers Default ahead of the enum", () => {
  assert.deepEqual(
    customComponentSelectOptions(properties.accent, undefined, false),
    [
      { label: CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL, value: "" },
      { label: "blue", value: "blue" },
      { label: "green", value: "green" },
    ],
  );
});

test("a value already set drops the Default option", () => {
  assert.deepEqual(customComponentSelectOptions(properties.accent, "blue", false), [
    { label: "blue", value: "blue" },
    { label: "green", value: "green" },
  ]);
});

test("a REQUIRED enum never offers Default, even unset", () => {
  assert.deepEqual(customComponentSelectOptions(properties.accent, undefined, true), [
    { label: "blue", value: "blue" },
    { label: "green", value: "green" },
  ]);
});

test("an enum that already contains 'Default' is not given a colliding sentinel", () => {
  const schema: CustomComponentPropSchema = {
    type: "string",
    enum: ["Default", "Loud"],
  };
  assert.deepEqual(customComponentSelectOptions(schema, undefined, false), [
    { label: "Default", value: "Default" },
    { label: "Loud", value: "Loud" },
  ]);
});

test("the shown label is the current value, or Default when it is offered", () => {
  const unset = customComponentSelectOptions(properties.accent, undefined, false);
  assert.equal(
    customComponentSelectLabel(unset, undefined),
    CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL,
  );
  const set = customComponentSelectOptions(properties.accent, "green", false);
  assert.equal(customComponentSelectLabel(set, "green"), "green");
});

test("a value the pinned enum no longer carries shows nothing rather than inventing an option", () => {
  const options = customComponentSelectOptions(properties.accent, "amber", false);
  assert.equal(customComponentSelectLabel(options, "amber"), "");
});

test("picking an enum option commits that string; picking Default commits the empty string", () => {
  const options = customComponentSelectOptions(properties.accent, undefined, false);
  assert.equal(customComponentSelectCommit(options, "green"), "green");
  assert.equal(
    customComponentSelectCommit(options, CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL),
    "",
  );
});

test("a label that is not on offer commits nothing", () => {
  const options = customComponentSelectOptions(properties.accent, undefined, false);
  assert.equal(customComponentSelectCommit(options, "amber"), null);
});

// --- the number/text draft guards (source `commitDraft`, :112-123) ----------

test("a value's draft is its string form; an unset value drafts empty", () => {
  assert.equal(customComponentDraft(3), "3");
  assert.equal(customComponentDraft(false), "false");
  assert.equal(customComponentDraft(undefined), "");
});

test("a finite number that differs from the value commits as a NUMBER", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "5",
      schema: properties.planCount,
      value: 3,
    }),
    { kind: "commit", value: 5 },
  );
});

test("an unchanged number commits nothing and leaves the draft as typed", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "3",
      schema: properties.planCount,
      value: 3,
    }),
    { kind: "none" },
  );
});

test("an emptied number field reverts to the live value — it never commits a blank", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "   ",
      schema: properties.planCount,
      value: 3,
    }),
    { kind: "revert", draft: "3" },
  );
});

test("an unparseable number reverts", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "three",
      schema: properties.planCount,
      value: 3,
    }),
    { kind: "revert", draft: "3" },
  );
});

test("a number typed over an unset prop commits, and an emptied one reverts to blank", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "2",
      schema: properties.planCount,
      value: undefined,
    }),
    { kind: "commit", value: 2 },
  );
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "",
      schema: properties.planCount,
      value: undefined,
    }),
    { kind: "revert", draft: "" },
  );
});

test("changed text commits; unchanged text does not", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "Plans",
      schema: properties.headline,
      value: "Pricing",
    }),
    { kind: "commit", value: "Plans" },
  );
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "Pricing",
      schema: properties.headline,
      value: "Pricing",
    }),
    { kind: "none" },
  );
});

test("an emptied TEXT field commits the empty string — only numbers revert", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "",
      schema: properties.headline,
      value: "Pricing",
    }),
    { kind: "commit", value: "" },
  );
});

test("an UNSET text prop, focused and left alone, commits nothing", () => {
  // The defect this pins (reviewed 2026-08-18): an unset optional prop drafts
  // `""` while its value is `undefined`, so a raw `draft === value` compared
  // "" against undefined → false → a plain focus-blur wrote `""` over the
  // manifest default with zero user intent. Compare against the DERIVED draft
  // and the untouched field is silent, exactly as an untouched field must be.
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "",
      schema: properties.headline,
      value: undefined,
    }),
    { kind: "none" },
  );
});

test("an unset text prop the user actually TYPES into commits that string", () => {
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "Plans",
      schema: properties.headline,
      value: undefined,
    }),
    { kind: "commit", value: "Plans" },
  );
});

test("a '3.0' draft over a value of 3 commits nothing — the equal-number branch", () => {
  // Upstream's own behaviour: the draft is left on screen as typed, and no
  // write is sent, because `Number("3.0") === 3`. Pinned so the number
  // branch's parsed comparison can never regress into a string one.
  assert.deepEqual(
    customComponentDraftCommit({
      draft: "3.0",
      schema: properties.planCount,
      value: 3,
    }),
    { kind: "none" },
  );
});

// --- what a key press means to a draft field --------------------------------
//
// Browser-verified defect (2026-08-18): Escape COMMITTED the abandoned draft.
// Both keys end the field's focus, and the wrapping span's `onBlur` settle then
// ran with the pre-Escape closure, writing the garbage to the wire. The rule
// below is the binding one — Escape restores and sends NOTHING (brief; source
// intent :146-149) — and it names the blur that must be suppressed, which is
// the half the event wiring gets wrong.

test("Enter settles the draft; Escape abandons it; anything else does nothing", () => {
  assert.equal(customComponentDraftKeyAction("Enter"), "settle");
  assert.equal(customComponentDraftKeyAction("Escape"), "abandon");
  assert.equal(customComponentDraftKeyAction("a"), "none");
  assert.equal(customComponentDraftKeyAction("Tab"), "none");
});

test("both handled keys end focus, so the blur they cause must NOT settle again", () => {
  // Enter has already settled and Escape must never settle at all — either way
  // the follow-on blur is a duplicate, and for Escape a corrupting one.
  assert.equal(customComponentDraftKeySuppressesBlur("settle"), true);
  assert.equal(customComponentDraftKeySuppressesBlur("abandon"), true);
  // An ordinary keystroke leaves focus alone; a later real blur still settles.
  assert.equal(customComponentDraftKeySuppressesBlur("none"), false);
});

// --- the whole-props payload (source :286-291; the W3.2 wholesale lesson) ----

test("one changed prop resends EVERY prop, under the node's own artifact pin", () => {
  assert.deepEqual(
    customComponentPropsUpdate({
      name: "headline",
      node: CUSTOM_COMPONENT_NODE,
      value: "Plans",
    }),
    {
      kind: "custom_component",
      slug: "lane-c-pricing-card",
      artifact_id:
        "ccart_765fe726e17be4859452c9ff3293ec8d1149689f7b786f9834a2ec20c210925c",
      props: {
        accent: "blue",
        headline: "Plans",
        planCount: 3,
        showBadge: true,
      },
    },
  );
});

test("a prop the node did not carry is ADDED, the rest untouched", () => {
  const node: WebNode = {
    ...CUSTOM_COMPONENT_NODE,
    props: { headline: "Pricing" },
  };
  assert.deepEqual(
    customComponentPropsUpdate({ name: "showBadge", node, value: false }),
    {
      kind: "custom_component",
      slug: "lane-c-pricing-card",
      artifact_id:
        "ccart_765fe726e17be4859452c9ff3293ec8d1149689f7b786f9834a2ec20c210925c",
      props: { headline: "Pricing", showBadge: false },
    },
  );
});

test("a node missing its pin sends empty strings rather than undefined — the source's own shape", () => {
  const node: WebNode = { id: "cc1", kind: "custom_component", classes: "" };
  assert.deepEqual(
    customComponentPropsUpdate({ name: "headline", node, value: "Hi" }),
    {
      kind: "custom_component",
      slug: "",
      artifact_id: "",
      props: { headline: "Hi" },
    },
  );
});

// --- the addressed operation (source `WebInspectorPanel.tsx:539-541`) --------
//
// The op below is WIRE-TRUE: the identical batch (intent
// `set_custom_component_props` + `base_version`) was accepted by the lane
// design API against the harvested document (200, version 1 → 2), and the
// re-read scene showed exactly the whole-props object it carried.

const loadedDocument: LoadedWebDocument = {
  documentId: "doc_b778a805381c4831844c490e30701719",
  docKind: "web",
  title: "Lane C custom-component test doc",
  webDoc: {
    pages: [
      {
        id: "other",
        name: "Other",
        route: "/other",
        root: "r2",
        nodes: { r2: { id: "r2", kind: "container", classes: "" } },
      },
      {
        id: CUSTOM_COMPONENT_PAGE_ID,
        name: "Home",
        route: "/",
        root: CUSTOM_COMPONENT_PAGE.page_root,
        nodes: CUSTOM_COMPONENT_PAGE.nodes,
      },
    ],
  },
  currentVersion: 1,
  undoDepth: 0,
  redoDepth: 0,
  isTemplate: false,
  templateDocumentId: null,
  accountId: "acc_403fa12213464a9cbb2a9a1dab3663db",
  fragmentMeta: {},
};

test("a committed prop becomes ONE set_node_props op on the node's own page", () => {
  assert.deepEqual(
    customComponentPropsToOperation(
      loadedDocument,
      CUSTOM_COMPONENT_NODE,
      "planCount",
      4,
    ),
    {
      kind: "set_node_props",
      page_id: CUSTOM_COMPONENT_PAGE_ID,
      id: "cclanec1",
      props: {
        kind: "custom_component",
        slug: "lane-c-pricing-card",
        artifact_id:
          "ccart_765fe726e17be4859452c9ff3293ec8d1149689f7b786f9834a2ec20c210925c",
        props: {
          accent: "blue",
          headline: "Pricing",
          planCount: 4,
          showBadge: true,
        },
      },
    },
  );
});

test("a node on no loaded page yields no operation rather than a guessed address", () => {
  assert.equal(
    customComponentPropsToOperation(
      loadedDocument,
      { ...CUSTOM_COMPONENT_NODE, id: "stray" },
      "planCount",
      4,
    ),
    null,
  );
  assert.equal(
    customComponentPropsToOperation(null, CUSTOM_COMPONENT_NODE, "planCount", 4),
    null,
  );
});
