import {
  setNodePropsOp,
  type CustomComponentArtifact,
  type CustomComponentPropSchema,
  type CustomComponentPropValue,
  type LoadedWebDocument,
  type WebCustomComponentProps,
  type WebNode,
  type WebOperation,
} from "../engine/webDocuments";
import { pageIdForNode } from "./page-address";

/**
 * W4.7 — the pure decisions behind the custom-component props form
 * (`web-inspector.tsx`, the ContainerControls region).
 *
 * The binding contract, item 34: "Custom component → props form | manifest
 * `props_schema` → `set_custom_component_props` | the existing schema-driven
 * form, shown when a custom component is selected."
 *
 * Ported from the source inspector's `CustomPropControl`
 * (`subsystems/clue-design/apps/editor/src/components/web/
 * WebCustomComponentInspector.tsx:41-154`) and its props `<section>`
 * (`:269-298`) — the form ONLY. The source's first section (status pill,
 * metrics, compile warnings, republish, Edit with AI) is chrome and is out of
 * item 34's scope, so none of its decisions live here either.
 *
 * Every function is pure so it is testable under this repo's renderer-free
 * runner (`tsx --test`, node:test) — the same extraction pattern as
 * `components/web-rich-text-toolbar.logic.ts` (W4.8a) and
 * `adapter/rich-text-link-section.ts` (W4.8b).
 */

/** Which control a `props_schema` field gets. The source's dispatch order is
 * load-bearing and preserved exactly: boolean first, then a string carrying a
 * NON-EMPTY enum, then number, and text as the fallback — so a string with an
 * empty enum (or an unknown type) still gets an editable text field rather than
 * a dead select. */
export type CustomComponentControlKind =
  | "checkbox"
  | "number"
  | "select"
  | "text";

export function customComponentControlKind(
  schema: CustomComponentPropSchema,
): CustomComponentControlKind {
  if (schema.type === "boolean") return "checkbox";
  if (schema.type === "string" && schema.enum && schema.enum.length > 0) {
    return "select";
  }
  if (schema.type === "number") return "number";
  return "text";
}

/** Source `:56`: everything outside `[A-Za-z0-9_-]` folds to a dash, so a prop
 * name straight off the manifest is safe as a DOM id / `htmlFor`. */
export function customComponentPropInputId(name: string): string {
  return `custom-component-prop-${name.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

/** Source `:57-59`: `camelCase` splits into words and `_`/`-` runs become
 * single spaces. Deliberately no capitalisation pass — the source has none, and
 * a manifest author's own casing is the honest label. The required star is NOT
 * part of this string: it is display-only, and the aria label must not carry
 * it. */
export function customComponentPropLabel(name: string): string {
  return name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
}

/** The string form of a live prop value — the initial (and reverted) draft of
 * a text/number field. Source `:60`, `:63`, `:118`, `:147`. */
export function customComponentDraft(
  value: CustomComponentPropValue | undefined,
): string {
  return value == null ? "" : String(value);
}

export interface CustomComponentSelectOption {
  label: string;
  value: string;
}

/** The label the source gives its `<option value="">` (`:101`). */
export const CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL = "Default";

/**
 * Source `:101-106`: the enum's own options, preceded by a "Default" entry —
 * whose value is the EMPTY STRING — only when the prop is optional and the node
 * carries no value for it. Once a value is set (or the prop is required), the
 * escape hatch is gone, exactly as upstream.
 *
 * One addition the source does not need: an enum that itself contains
 * "Default" is left alone, so the sentinel can never collide with a real
 * option in a list keyed by label.
 */
export function customComponentSelectOptions(
  schema: CustomComponentPropSchema,
  value: CustomComponentPropValue | undefined,
  required: boolean,
): CustomComponentSelectOption[] {
  const options = (schema.enum ?? []).map((option) => ({
    label: option,
    value: option,
  }));
  const offersDefault =
    !required &&
    value == null &&
    !options.some(
      (option) => option.label === CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL,
    );
  return offersDefault
    ? [{ label: CUSTOM_COMPONENT_SELECT_DEFAULT_LABEL, value: "" }, ...options]
    : options;
}

/**
 * What the closed select shows. Source `:95`: a string value displays itself,
 * anything else displays the empty value — which is the Default entry when it
 * is on offer, and simply nothing when it is not (a value the pinned enum no
 * longer carries shows blank rather than inventing an option for itself).
 */
export function customComponentSelectLabel(
  options: CustomComponentSelectOption[],
  value: CustomComponentPropValue | undefined,
): string {
  const current = typeof value === "string" ? value : "";
  return options.find((option) => option.value === current)?.label ?? "";
}

/**
 * Source `:99` — `onChange` commits the picked option's value as-is, which for
 * the Default entry is the empty string. The prop is NOT removed: the source
 * has no removal path, and `set_node_props` replaces props wholesale, so
 * "unset" is not expressible on this wire without dropping the key from the
 * whole-props payload, which upstream never does.
 *
 * A label that is not on offer commits nothing (`null`) — a select can only
 * return what it was given, so this is a guard, not a user-reachable branch.
 */
export function customComponentSelectCommit(
  options: CustomComponentSelectOption[],
  label: string,
): CustomComponentPropValue | null {
  const picked = options.find((option) => option.label === label);
  return picked ? picked.value : null;
}

export type CustomComponentDraftDecision =
  /** Send this value (a number for a number field, the raw string otherwise). */
  | { kind: "commit"; value: CustomComponentPropValue }
  /** The draft is not a usable value — put this string back in the field. */
  | { kind: "revert"; draft: string }
  /** Nothing changed; leave the field exactly as the user typed it. */
  | { kind: "none" };

/**
 * Source `commitDraft` (`:112-123`), branch for branch — the settle (blur /
 * Enter) decision for the number and text controls:
 *
 * - number: a non-blank, finite draft that differs from the live value commits
 *   as a NUMBER; a blank or unparseable draft REVERTS to the live value (a
 *   number field can never commit a blank); a finite draft equal to the value
 *   does nothing at all — note that this deliberately leaves "3.0" on screen
 *   over a value of 3, upstream's own behaviour.
 * - text (and every fallback): commits whenever the draft differs from the
 *   value, INCLUDING an empty one — for a string, "" is a value, not an absence.
 *
 * Escape does not come through here: it restores {@link customComponentDraft}
 * of the live value and blurs (`:146-149`), sending nothing.
 */
export function customComponentDraftCommit({
  draft,
  schema,
  value,
}: {
  draft: string;
  schema: CustomComponentPropSchema;
  value: CustomComponentPropValue | undefined;
}): CustomComponentDraftDecision {
  if (schema.type === "number") {
    const parsed = Number(draft);
    if (draft.trim() !== "" && Number.isFinite(parsed) && parsed !== value) {
      return { kind: "commit", value: parsed };
    }
    if (draft.trim() === "" || !Number.isFinite(parsed)) {
      return { kind: "revert", draft: customComponentDraft(value) };
    }
    return { kind: "none" };
  }
  return draft === value ? { kind: "none" } : { kind: "commit", value: draft };
}

/** What a key press does to a text/number draft. */
export type CustomComponentDraftKeyAction =
  /** Enter — settle the draft through {@link customComponentDraftCommit}. */
  | "settle"
  /** Escape — restore the live value and send NOTHING. */
  | "abandon"
  /** An ordinary keystroke; the draft just keeps typing. */
  | "none";

export function customComponentDraftKeyAction(
  key: string,
): CustomComponentDraftKeyAction {
  if (key === "Enter") return "settle";
  if (key === "Escape") return "abandon";
  return "none";
}

/**
 * Whether the blur that a handled key causes must skip its settle.
 *
 * Browser-verified defect (2026-08-18): Escape COMMITTED the very draft it was
 * supposed to abandon. Both handled keys end the field's focus, and the
 * wrapping element's blur-settle then ran in the same browser task holding the
 * PRE-key draft — so Escape wrote the abandoned garbage to the wire, and Enter
 * settled a second time (harmless today only because the manual-edits
 * controller drops an apply while one is in flight).
 *
 * So the follow-on blur is always a duplicate: after `settle` it has already
 * happened, and after `abandon` it must never happen at all. An ordinary
 * keystroke suppresses nothing — a later, real blur still settles the field.
 *
 * This is a deliberate deviation from the source's event WIRING, which carries
 * the same structural hazard (`WebCustomComponentInspector.tsx:141-150`: both
 * branches call `.blur()` under an `onBlur={commitDraft}` input). The binding
 * semantics are the brief's and the source's INTENT — Escape restores and sends
 * nothing — not its handler arrangement.
 */
export function customComponentDraftKeySuppressesBlur(
  action: CustomComponentDraftKeyAction,
): boolean {
  return action !== "none";
}

/** One row of the form: the schema decisions above, resolved against the live
 * node props, in the order `props_schema.properties` declares them. */
export interface CustomComponentField {
  name: string;
  schema: CustomComponentPropSchema;
  kind: CustomComponentControlKind;
  /** DOM id shared by the control and its `<label for>`. */
  inputId: string;
  /** The bare, humanised name — what the aria label is built from. */
  label: string;
  /** The visible label: {@link label} plus `" *"` when required (`:80`). */
  displayLabel: string;
  /** Source `:74`, `:98`, `:137` — the same phrasing on every control. */
  ariaLabel: string;
  required: boolean;
  /** The node's live value for this prop, or `undefined` when it carries none.
   * The manifest `default` is NOT substituted: the form shows what the document
   * actually holds, and an unset optional prop is honestly empty. */
  value: CustomComponentPropValue | undefined;
  /** Initial draft for the text/number controls. */
  draft: string;
  /** Populated for `kind === "select"` only. */
  selectOptions: CustomComponentSelectOption[];
}

/**
 * The rows the props section iterates — source `:274-295` plus the required set
 * from `:169`. `Object.entries` preserves the manifest's declaration order, so
 * the form reads in the order the component author wrote.
 */
export function customComponentFields(
  artifact: CustomComponentArtifact,
  props: Record<string, CustomComponentPropValue>,
): CustomComponentField[] {
  const schema = artifact.manifest.props_schema;
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties).map(([name, fieldSchema]) => {
    const isRequired = required.has(name);
    const label = customComponentPropLabel(name);
    const value = props[name];
    const kind = customComponentControlKind(fieldSchema);
    return {
      ariaLabel: `${label} custom component prop`,
      displayLabel: isRequired ? `${label} *` : label,
      draft: customComponentDraft(value),
      inputId: customComponentPropInputId(name),
      kind,
      label,
      name,
      required: isRequired,
      schema: fieldSchema,
      selectOptions:
        kind === "select"
          ? customComponentSelectOptions(fieldSchema, value, isRequired)
          : [],
      value,
    };
  });
}

/**
 * The commit payload — source `:286-291`. One changed field RESENDS the node's
 * whole props object with that one key replaced, because `set_node_props`
 * replaces props wholesale on the wire (the W3.2 lesson); sending only the
 * changed key would silently drop every other prop.
 *
 * The artifact pin rides along unchanged: editing a prop must never repoint the
 * node at a different `artifact_id`. A node missing `slug`/`artifact_id` sends
 * empty strings, upstream's own shape (`WebInspectorPanel.tsx:573-595`) — the
 * server rejects that loudly rather than this layer inventing a pin.
 */
export function customComponentPropsUpdate({
  name,
  node,
  value,
}: {
  name: string;
  node: WebNode;
  value: CustomComponentPropValue;
}): WebCustomComponentProps {
  return {
    kind: "custom_component",
    slug: node.slug ?? "",
    artifact_id: node.artifact_id ?? "",
    props: { ...(node.props ?? {}), [name]: value },
  };
}

/**
 * One settled field → exactly ONE canonical `set_node_props` operation, which
 * the shell persists through the SAME manual-edits controller every inspector
 * write uses (one in-flight mutation, `base_version` on every apply, 409 →
 * quiet reload, 422 → inline diagnostic). There is deliberately no second write
 * path — the intent string `set_custom_component_props` is the caller's, as
 * upstream (`WebInspectorPanel.tsx:539-541,573-595`).
 *
 * The page is resolved by node membership through the shared
 * {@link pageIdForNode}; a node on no loaded page yields `null` (no operation)
 * rather than a guessed address.
 */
export function customComponentPropsToOperation(
  document: LoadedWebDocument | null,
  node: WebNode,
  name: string,
  value: CustomComponentPropValue,
): WebOperation | null {
  const pageId = pageIdForNode(document, node.id);
  if (!pageId) return null;
  return setNodePropsOp(
    pageId,
    node.id,
    customComponentPropsUpdate({ name, node, value }),
  );
}

/** One settled field → one whole-props write. Named here so presentation can
 * type its handlers without importing the engine (the repo's seam rule:
 * components speak to `adapter/`, never to `engine/` or `data/`). */
export type CustomComponentPropCommit = (
  name: string,
  value: CustomComponentPropValue,
) => void;

/**
 * What the inspector needs to render and drive the form, shaped so presentation
 * stays transport-free: a value snapshot in, one callback out (the W4.8b
 * pattern). The fetch lives in `use-custom-component-artifact.ts` and the write
 * in the shell, which owns the manual-edits controller.
 *
 * The binding EXISTS only once the artifact is in hand: while it loads, or if
 * its fetch failed, the caller passes null and the props section is simply
 * ABSENT (ledgered ruling, 2026-08-18) — item 34's scope is the form, not a
 * loading shell or an error surface.
 */
export interface CustomComponentFormBinding {
  artifact: CustomComponentArtifact;
  /** A write is in flight — every control is disabled (source `:73`, `:96`,
   * `:135`; the manual-edits controller allows one mutation at a time). */
  busy: boolean;
  /** The node's live props, the base of every whole-props resend. */
  props: Record<string, CustomComponentPropValue>;
  onCommitProp: CustomComponentPropCommit;
}
