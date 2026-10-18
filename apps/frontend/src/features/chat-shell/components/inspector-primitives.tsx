"use client";

import Image from "next/image";
import { Menu } from "@base-ui/react/menu";
import { Popover } from "@base-ui/react/popover";
import { Select } from "@base-ui/react/select";
import { MinusIcon, PlusIcon } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type {
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";
import {
  commitInspectorNumber,
  type HorizontalAlignment,
  type InspectorBackgroundFill,
  type InspectorFillType,
} from "../hooks/use-inspector-controller";
import { resolveInspectorThemeColors } from "../model/inspector-theme-colors";
import { ArtifactTitle } from "./artifact-title";
import { fieldCommit, fieldDisplay, textareaCommitKey } from "./inspector-field-draft";
import { REPLACE_IMAGE_MENU_ROWS, replaceImageMenuAction } from "./replace-image-menu.logic";
import styles from "./chat-shell.module.css";

const INSPECTOR_ICON_ROOT = "/icons/chat-shell/inspector";

export type InspectorIconName =
  | "apple"
  | "align-bottom"
  | "align-center"
  | "align-center-horizontal"
  | "align-center-vertical"
  | "align-end-horizontal"
  | "align-end-vertical"
  | "align-horizontal-distribute-center"
  // §2 delta (contract row 2): the ad text schema's fourth H-alignment toggle.
  // The dummy set carries no justify glyph, so this one is authored in the
  // existing align-* family's export style (AD0.4 ruling 3).
  | "align-justify"
  | "align-left"
  | "align-middle"
  | "align-right"
  | "align-start-horizontal"
  | "align-start-vertical"
  | "align-top"
  | "align-vertical-distribute-center"
  | "chevron-down"
  | "chevron-right"
  | "div"
  | "ellipse"
  | "ellipsis"
  | "eye"
  | "gap"
  | "group"
  | "image"
  | "layer-ellipsis"
  | "layer-back"
  | "layer-down"
  | "layer-front"
  | "layer-up"
  | "layout-template"
  | "lock-open"
  | "move-horizontal"
  | "move-vertical"
  | "radius-all"
  | "radius-bottom-left"
  | "radius-bottom-right"
  | "radius-scan"
  | "radius-top-left"
  | "radius-top-right"
  | "rectangle"
  | "scan"
  | "select-chevron"
  | "square-dashed"
  | "ungroup"
  | "type";

export function InspectorIcon({
  className,
  name,
  size = 16,
}: {
  className?: string;
  name: InspectorIconName;
  size?: number;
}) {
  return (
    <span
      aria-hidden="true"
      className={`${styles.inspectorIcon} ${className ?? ""}`}
      style={{ height: size, width: size }}
    >
      <Image
        alt=""
        fill
        sizes={`${size}px`}
        src={`${INSPECTOR_ICON_ROOT}/shared/${name}.svg`}
        style={{ objectFit: "contain" }}
      />
    </span>
  );
}

export function InspectorHeader({
  actionMenu,
  disabled = false,
  elementActions = true,
  locked = false,
  moreActionsExpanded,
  moreActionsHasPopup = false,
  onLockToggle,
  onMoreActions,
  onVisibilityToggle,
  title,
  visible = true,
}: {
  actionMenu?: ReactNode;
  /** AD4.R-10 (G-H): the lock and visibility toggles are OPERATIONS on the
   * document, so they go dark with the rest of the panel while an agent turn is
   * in flight. Absent (the web inspector, the dummy fixture path) is `false`,
   * i.e. exactly what this header has always rendered.
   *
   * DELIBERATELY NOT FOLDED TOGETHER WITH `locked`: locking is the one write
   * whose own outcome this button states, so a locked node must keep an ENABLED
   * lock button or the user could never unlock it. The ellipsis is untouched
   * either way — it opens a menu, and G-H gates operations, not navigation. */
  disabled?: boolean;
  elementActions?: boolean;
  locked?: boolean;
  moreActionsExpanded?: boolean;
  moreActionsHasPopup?: boolean;
  onLockToggle?: () => void;
  onMoreActions?: () => void;
  onVisibilityToggle?: () => void;
  title: string;
  visible?: boolean;
}) {
  return (
    <div className={styles.inspectorHeader}>
      {/* One line, cut with an ellipsis, scrolling through on hover: the artifact header's title
          (founder 2026-10-19). Keyed on the title so a new selection starts fresh. */}
      <ArtifactTitle key={title} title={title} />
      <div className={styles.inspectorHeaderActions}>
        {elementActions ? (
          <>
            <button
              aria-label={locked ? "Unlock element" : "Lock element"}
              aria-pressed={locked}
              className={`${styles.inspectorIconButton} ${locked ? styles.inspectorIconButtonActive : ""} ${disabled ? styles.inspectorControlDisabled : ""}`}
              disabled={disabled}
              onClick={onLockToggle}
              type="button"
            >
              <InspectorIcon name="lock-open" size={12} />
            </button>
            {/* §2 delta (contract row 7): the ad schemas drop the header eye,
                so the toggle renders only where a caller actually wires
                visibility (the web inspector always does — unchanged there). */}
            {onVisibilityToggle ? (
              <button
                aria-label={visible ? "Hide element" : "Show element"}
                aria-pressed={!visible}
                className={`${styles.inspectorIconButton} ${!visible ? styles.inspectorIconButtonActive : ""} ${disabled ? styles.inspectorControlDisabled : ""}`}
                disabled={disabled}
                onClick={onVisibilityToggle}
                type="button"
              >
                <InspectorIcon name="eye" size={12} />
              </button>
            ) : null}
          </>
        ) : null}
        {/* The "…" button only where it opens something (founder 2026-10-19: no empty button). */}
        {onMoreActions || actionMenu ? (
          <button
            aria-expanded={moreActionsExpanded}
            aria-haspopup={moreActionsHasPopup ? "menu" : undefined}
            aria-label={moreActionsHasPopup ? "Preview inspector element types" : "More inspector actions"}
            className={styles.inspectorIconButton}
            onClick={onMoreActions}
            type="button"
          >
            <InspectorIcon name="ellipsis" size={12} />
          </button>
        ) : null}
        {actionMenu}
      </div>
    </div>
  );
}

export function InspectorSection({
  children,
  compact = false,
  label,
  onOpenChange,
  open,
}: {
  children?: ReactNode;
  compact?: boolean;
  label: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const regionId = useId();
  const regionRef = useRef<HTMLDivElement>(null);
  const regionInnerRef = useRef<HTMLDivElement>(null);

  // Only a person opening or closing the section animates (founder 2026-10-19): a section that appears
  // (a new selection) is simply there, and an open section follows its content's height directly, so
  // the panel never replays when the selection changes.
  // The open state this section last showed: only a change of it animates (a section that appears, or
  // runs its effect again in development, is simply set).
  const shownOpenRef = useRef<boolean | null>(null);
  useLayoutEffect(() => {
    const region = regionRef.current;
    const inner = regionInnerRef.current;
    if (!region || !inner) return;
    const previous = shownOpenRef.current;
    shownOpenRef.current = open;

    if (previous === null || previous === open) {
      const transition = region.style.transition;
      region.style.transition = "none";
      region.style.height = open ? "auto" : "0px";
      void region.offsetHeight;
      region.style.transition = transition;
      return;
    }

    if (open) {
      region.style.height = `${inner.scrollHeight}px`;
      // The fade ends before the height does: wait for the height, then follow the content.
      const settle = (event: TransitionEvent) => {
        if (event.target !== region || event.propertyName !== "height") return;
        region.style.height = "auto";
        region.removeEventListener("transitionend", settle);
      };
      region.addEventListener("transitionend", settle);
      return () => region.removeEventListener("transitionend", settle);
    }
    region.style.height = `${region.scrollHeight}px`;
    void region.offsetHeight;
    region.style.height = "0px";
  }, [open]);

  return (
    <section className={`${styles.inspectorSection} ${compact ? styles.inspectorSectionCompact : ""}`}>
      <button
        aria-controls={regionId}
        aria-expanded={open}
        className={styles.inspectorSectionTitle}
        onClick={() => onOpenChange(!open)}
        type="button"
      >
        <span>{label}</span>
        <span
          aria-hidden="true"
          className={`${styles.inspectorSectionChevron} ${open ? styles.inspectorSectionChevronOpen : ""}`}
        >
          <Image
            alt=""
            height={7}
            src={`${INSPECTOR_ICON_ROOT}/shared/chevron-right.svg`}
            width={4}
          />
        </span>
      </button>
      <div
        aria-hidden={!open}
        className={`${styles.inspectorSectionRegion} ${open ? styles.inspectorSectionRegionOpen : ""}`}
        id={regionId}
        inert={!open}
        ref={regionRef}
      >
        <div className={styles.inspectorSectionRegionInner} ref={regionInnerRef}>
          <div className={styles.inspectorSectionContent}>{children}</div>
        </div>
      </div>
    </section>
  );
}

export function InspectorField({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <div className={styles.inspectorField}>
      <span className={styles.inspectorFieldLabel}>{label}</span>
      {children}
    </div>
  );
}

export function InspectorControl({
  children,
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return <span className={`${styles.inspectorControl} ${className ?? ""}`}>{children}</span>;
}

export function InspectorSelect({
  disabled = false,
  label,
  onChange,
  options,
  value,
}: {
  /** AD4.R-10 (G-H): this select may not produce a document operation — a
   * locked node, or an agent turn in flight. Absent is `false`, so every
   * existing caller (the web inspector, the dummy fixture path) renders and
   * behaves exactly as it always has. The refusal is stated TWICE on purpose:
   * `Select.Root` closes the popup path, and the guard in `onValueChange` means
   * even a programmatic value change cannot dispatch a write. */
  disabled?: boolean;
  label: string;
  onChange: (value: string) => void;
  options: readonly string[];
  value: string;
}) {
  const items = options.map((option) => ({ label: option, value: option }));

  return (
    <Select.Root
      disabled={disabled}
      items={items}
      onValueChange={(nextValue) => {
        if (disabled) return;
        if (typeof nextValue === "string") onChange(nextValue);
      }}
      value={value}
    >
      <Select.Trigger
        aria-label={label}
        className={`${styles.inspectorControl} ${styles.inspectorSelectControl} ${disabled ? styles.inspectorControlDisabled : ""}`}
      >
        <Select.Value className={styles.inspectorSelectValue} />
        <Select.Icon className={styles.inputChevron}>
          <InspectorIcon name="select-chevron" size={12} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner className={styles.inspectorSelectPositioner} sideOffset={4}>
          <Select.Popup className={styles.inspectorSelectPopup}>
            <Select.List className={styles.inspectorSelectList}>
              {items.map((option) => (
                <Select.Item
                  className={styles.inspectorSelectItem}
                  key={option.value}
                  label={option.label}
                  value={option.value}
                >
                  <Select.ItemText className={styles.inspectorSelectItemText}>
                    {option.label}
                  </Select.ItemText>
                  <Select.ItemIndicator className={styles.inspectorSelectIndicator}>
                    <Image alt="" height={7} src="/icons/check.svg" width={9} />
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}

export function InspectorDecoratedSelect({
  icon,
  label,
  onChange,
  options,
  value,
}: {
  icon: InspectorIconName;
  label: string;
  onChange: (value: string) => void;
  options: readonly string[];
  value: string;
}) {
  const items = options.map((option) => ({ label: option, value: option }));

  return (
    <Select.Root
      items={items}
      onValueChange={(nextValue) => {
        if (typeof nextValue === "string") onChange(nextValue);
      }}
      value={value}
    >
      <Select.Trigger
        aria-label={label}
        className={`${styles.inspectorControl} ${styles.inspectorDecoratedSelect}`}
      >
        <InspectorIcon name={icon} size={12} />
        <Select.Value className={styles.inspectorDecoratedSelectValue} />
        <Select.Icon className={styles.inputChevron}>
          <InspectorIcon name="select-chevron" size={12} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner className={styles.inspectorSelectPositioner} sideOffset={4}>
          <Select.Popup className={styles.inspectorSelectPopup}>
            <Select.List className={styles.inspectorSelectList}>
              {items.map((option) => (
                <Select.Item
                  className={styles.inspectorSelectItem}
                  key={option.value}
                  label={option.label}
                  value={option.value}
                >
                  <Select.ItemText className={styles.inspectorSelectItemText}>
                    {option.label}
                  </Select.ItemText>
                  <Select.ItemIndicator className={styles.inspectorSelectIndicator}>
                    <Image alt="" height={7} src="/icons/check.svg" width={9} />
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}

export function InspectorTokenControl({
  label,
  onClick,
  onTokenSelect,
  options,
  swatch,
}: {
  label: string;
  onClick?: () => void;
  /** W4.4 (rows 19/17): a token pick from the theme list — reports the token
   * LABEL, exactly like `ColorControl`'s Theme tab, which is the live write
   * path. Omitted (or no `options`) keeps the dummy's plain button. */
  onTokenSelect?: (label: string) => void;
  /** W4.4: the document's real theme tokens (already `palette-*`-filtered per
   * ruling F3). */
  options?: readonly ThemeColorOption[];
  swatch: string;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const trigger = (
    <>
      <span className={styles.inspectorTokenSwatch} style={{ background: swatch }} />
      <span>{label}</span>
    </>
  );
  const triggerClassName = `${styles.inspectorControl} ${styles.inspectorTokenControl}`;

  if (!onTokenSelect || !options || options.length === 0) {
    return (
      <button className={triggerClassName} onClick={onClick} type="button">
        {trigger}
      </button>
    );
  }

  // Ruling 17 (and 19, "same pattern as 17"): the dummy's token button gets a
  // real token list — the ColorControl Theme tab's own markup and classes, so
  // the popover is the picker the marketer already knows.
  return (
    <span className={styles.colorControl} ref={anchorRef}>
      <Popover.Root onOpenChange={setOpen} open={open}>
        <Popover.Trigger className={triggerClassName} onClick={onClick}>
          {trigger}
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner
            align="start"
            anchor={anchorRef}
            className={styles.inspectorColorPositioner}
            side="right"
            sideOffset={8}
          >
            <Popover.Popup className={styles.inspectorColorPopup}>
              <div aria-label="Theme colors" className={styles.inspectorThemeColors} role="group">
                {options.map((option) => (
                  <button
                    aria-label={`Use ${option.label} color ${option.value}`}
                    aria-pressed={option.label.toLowerCase() === label.toLowerCase()}
                    className={styles.inspectorThemeColor}
                    key={option.label}
                    onClick={() => {
                      onTokenSelect(option.label);
                      setOpen(false);
                    }}
                    type="button"
                  >
                    <span className={styles.inspectorThemeSwatch} style={{ background: option.value }} />
                    <span>{option.label}</span>
                    <span className={styles.inspectorThemeValue}>{option.value}</span>
                  </button>
                ))}
              </div>
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
    </span>
  );
}

export function InspectorInput({
  ariaLabel,
  className,
  disabled = false,
  leading,
  onChange,
  onCommit,
  onCommitValue,
  placeholder,
  prefix,
  readOnly = false,
  suffix,
  value,
}: {
  ariaLabel: string;
  className?: string;
  /** AD4.R-10 (G-H): this field may not produce a document operation — a locked
   * node, or an agent turn in flight. Absent is `false`: every existing caller
   * is byte-for-byte unchanged.
   *
   * DISTINCT FROM `readOnly`, which is a display posture (the value is real but
   * this panel does not author it) and carries no treatment. This one says the
   * write path is closed right now, and it is what the G-H opacity states.
   *
   * BOTH the draft and the commit are guarded, in both protocols. A natively
   * disabled input fires no blur/keydown of its own, but a PROGRAMMATIC blur —
   * a focused field whose panel disables underneath it — is exactly the shape
   * that would slip a write through. Refusing here means a field that goes dark
   * mid-edit holds a draft it cannot commit, which is the point of the ruling:
   * the refusal touches nothing, so the typed text survives the turn. */
  disabled?: boolean;
  leading?: ReactNode;
  /** Optional once `onCommitValue` exists: a self-drafting field needs no
   * per-keystroke channel. Every existing caller keeps passing it. */
  onChange?: (value: string) => void;
  /** W4.2 (the ratified R3 commit model): when supplied, the caller drafts the
   * typed value locally and this fires on blur/Enter — the one moment a typed
   * field becomes a write. Omitted leaves the field exactly as it shipped
   * (per-keystroke `onChange` only); either way the DOM is unchanged. */
  onCommit?: () => void;
  /**
   * AD4.R (the MVP state model): when supplied, the input drafts locally while
   * being typed in and commits ONCE on blur/Enter — `fieldCommit` suppresses
   * the no-op re-type, and the draft clears on commit either way. `value` must
   * then be the LIVE document value (the live-hydrated controller state): the
   * accepted write lands in the same React batch (the Task-1 mirror), so the
   * cleared draft reveals the just-written value with no frame in between; a
   * refused write reveals the unchanged one, which is the honest display.
   * Mutually exclusive with `onCommit` (the caller-managed draft protocol) —
   * supplying both is a programming error and `onCommitValue` wins.
   */
  onCommitValue?: (value: string) => void;
  /** AD4.A step 3 (§1.3 row 2): the native hint. Additive and inert for every
   * existing caller (the same shape as `onCommit`'s W4.2 addition), and it
   * exists because the AI suite's two free-text fields are the first controls
   * in this panel that ask for a SENTENCE rather than a number — upstream ships
   * a placeholder on both, and porting its words is the alternative to
   * authoring an empty box with no hint at all. */
  placeholder?: string;
  prefix?: string;
  readOnly?: boolean;
  suffix?: string;
  value: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const selfDrafting = onCommitValue !== undefined;
  const shown = selfDrafting ? fieldDisplay(draft, value) : value;
  const commitSelf = () => {
    // G-H (AD4.R-10): ABOVE the draft clear. A refused commit must touch
    // nothing at all — clearing the draft would throw away text the user typed
    // for a write that never happened, which is the same "a refusal touches
    // nothing" posture the AI suite's instruction box keeps.
    if (disabled) return;
    const commit = fieldCommit(draft, value);
    setDraft(null);
    if (commit !== null) onCommitValue?.(commit);
  };
  /** The caller-draft protocol's commit (W4.2), behind the same refusal. */
  const commitCaller = onCommit
    ? () => {
        if (disabled) return;
        onCommit();
      }
    : undefined;
  return (
    <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${className ?? ""} ${disabled ? styles.inspectorControlDisabled : ""}`}>
      {leading}
      {prefix ? <span className={styles.fieldPrefix}>{prefix}</span> : null}
      <input
        aria-label={ariaLabel}
        disabled={disabled}
        inputMode="text"
        onBlur={selfDrafting ? commitSelf : commitCaller ? () => commitCaller() : undefined}
        onChange={(event) => {
          // A disabled field may not mutate its own draft either: the draft is
          // what a later blur would commit, so a write refused at the commit
          // but accepted into the draft is the same write, one moment later.
          if (disabled) return;
          if (selfDrafting) setDraft(event.target.value);
          onChange?.(event.target.value);
        }}
        onKeyDown={
          selfDrafting
            ? (event) => {
                if (event.key === "Enter") commitSelf();
              }
            : commitCaller
              ? (event) => {
                  if (event.key === "Enter") commitCaller();
                }
              : undefined
        }
        placeholder={placeholder}
        readOnly={readOnly}
        value={shown}
      />
      {suffix ? <span className={styles.fieldPrefix}>{suffix}</span> : null}
    </span>
  );
}

/**
 * The MULTILINE sibling of `InspectorInput` — a text node's own content is the
 * first inspector value that can legitimately hold a newline.
 *
 * Same AD4.R state model, unchanged: self-drafting through `fieldDisplay` /
 * `fieldCommit`, so the box holds a draft only while it is being typed in,
 * `value` is the LIVE document value, and a no-op re-type commits nothing.
 *
 * ONE contract differs from `InspectorInput`: Enter inserts a newline and the
 * commit chord is ⌘/Ctrl+Enter (`textareaCommitKey`). A field whose value may
 * contain newlines cannot spend Enter on committing. Blur commits either way.
 */
export function InspectorTextArea({
  ariaLabel,
  className,
  disabled = false,
  onCommitValue,
  placeholder,
  rows = 3,
  value,
}: {
  ariaLabel: string;
  className?: string;
  /** AD4.R-10 (G-H), exactly as `InspectorInput` states it: BOTH the draft and
   * the commit are guarded. A natively disabled textarea fires no blur of its
   * own, but a PROGRAMMATIC blur — a focused field whose panel disables
   * underneath it — is the shape that would slip a write through. */
  disabled?: boolean;
  onCommitValue: (value: string) => void;
  placeholder?: string;
  rows?: number;
  value: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = fieldDisplay(draft, value);
  const commitSelf = () => {
    // ABOVE the draft clear: a refused commit must touch nothing at all, so the
    // text typed for a write that never happened survives the turn.
    if (disabled) return;
    const commit = fieldCommit(draft, value);
    setDraft(null);
    if (commit !== null) onCommitValue(commit);
  };
  return (
    <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${styles.inspectorTextAreaControl} ${className ?? ""} ${disabled ? styles.inspectorControlDisabled : ""}`}>
      <textarea
        aria-label={ariaLabel}
        disabled={disabled}
        onBlur={commitSelf}
        onChange={(event) => {
          // A disabled field may not mutate its own draft either: the draft is
          // what a later blur would commit.
          if (disabled) return;
          setDraft(event.target.value);
        }}
        onKeyDown={(event) => {
          if (!textareaCommitKey(event)) return;
          // Otherwise the chord also types the newline it is committing past.
          event.preventDefault();
          commitSelf();
        }}
        placeholder={placeholder}
        rows={rows}
        value={shown}
      />
    </span>
  );
}

type RadiusCorner = "all" | "bottomLeft" | "bottomRight" | "topLeft" | "topRight";
type RadiusValues = Record<RadiusCorner, string>;

/** W4.2 (ruling R-B1): only a numeric commit writes (`N` → `rounded-[Npx]`) —
 * and under founder ruling F2 that all-corners write also clears the per-corner
 * overrides, which is what the corner fields mirror below. An empty commit
 * clears the all-corners family only; a named scale value the field displays
 * verbatim (`lg`) is no write at all, so nothing is mirrored for it either. */
const NUMERIC_RADIUS = /^\d+$/;

/**
 * RULING A29's `uniformRadius` derivation — RETIRED in AD4.R Task 7 (see
 * `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
 * §"Rulings superseded").
 *
 * A29 asked: what does the `all` box read once one CORNER has moved? In the
 * SCENE lane `all` is not a stored field — `scene-hydrate.ts` derives it from
 * the four corners ("the uniform value, or empty when the corners differ"). So
 * a component holding its own copy of the five boxes had to re-derive `all`
 * after every corner commit, or state a number the document does not have.
 *
 * That copy is gone. The scene lane's five boxes are now projections of the
 * LIVE `values` prop, so the derived `all` arrives from hydrate itself, in the
 * same batch as the corner that moved — the mirror it replaces cannot lag or
 * disagree with it, because there is nothing left to disagree.
 *
 * The lane split A29 recorded still stands and still matters, which is why the
 * WEB lane keeps its mount-seeded model below: there `all` is its own Tailwind
 * class (`rounded-[Npx]`), parsed independently of the four corner classes
 * (`design-editor/adapter/hydrate.ts:259-266`), and a node legitimately carries
 * `rounded-[8px]` beside a `rounded-tl-[2px]` override. Deriving there would
 * erase a real class from the panel. The two lanes' `all` are different facts.
 */

/** W4.2 (ruling R-B2): the five radius fields adopt the ratified R3 commit
 * model — typed values draft locally and COMMIT on blur/Enter, so the write
 * path never sees a per-keystroke event. Behavioral only: same DOM, classes,
 * icons and aria-labels as the dummy ships. */
export function RadiusControls({
  disabled = false,
  locked = false,
  onApplyAll,
  onChange,
  values,
}: {
  /** AD4.R-10 (G-H): an agent turn is in flight, so none of these five fields
   * may produce a document operation. It COMPOSES with `locked` rather than
   * replacing it — `locked` is a fact about the NODE and A29 owns what a commit
   * against one records; this is a fact about the moment. Absent is `false`, so
   * the web lane (which passes neither) renders and behaves byte-for-byte as it
   * always has, and a locked ad node now simply looks as refused as it already
   * behaved. */
  disabled?: boolean;
  /** RULING A29 (review): the selected node's LOCK, as data — the one refusal
   * this component can actually know.
   *
   * Every other refusal belongs to the adapter and stays there, but the lock is
   * different in kind: it gates every write path (§4) and it is the one whose
   * outcome the panel must reflect. Without it the scene branch below asked only
   * "would this text write?", never "did the write LAND?", so on a locked node a
   * commit re-stated all five boxes and their `committed` snapshot over a
   * document the adapter had refused to touch — a five-field lie that only
   * reselecting the node could clear, and A27's trap re-opened behind the lock
   * (after unlocking, the same number compared equal and committed nothing).
   *
   * Default `false` keeps every existing caller — the web inspector and the
   * unbound dummy schemas — exactly as it was. Markup, classes and labels are
   * untouched: this changes what a commit RECORDS, not what is rendered. (A
   * disabled treatment for locked controls is upstream's own posture
   * — `disabled={selectedNode.locked}` throughout `RawStyleSection` — and is a
   * founder ruling, not this slice's; the report says what the primitives can
   * already support.) */
  locked?: boolean;
  /** W4.2/F2 (the web image schema): the all-corners commit — ONE `radius.all`
   * change, `clearsCorners` true when that write also clears the four corner
   * overrides.
   *
   * Absent is the SCENE (ad) image inspector, whose `radius.all` is bound to a
   * real write that sets all four corners (AD4.A, `scene-apply.ts`). It dispatches
   * through `onChange("all", …)` instead, which is one event either way —
   * ruling A26 retired the fan-out-to-four this branch used to do, because four
   * events could not compose into one document (see `applyAll`). The two lanes
   * now differ only in WHICH call carries the all-write and in what the four
   * corner fields read afterwards. */
  onApplyAll?: (value: string, clearsCorners: boolean) => void;
  onChange: (corner: RadiusCorner, value: string) => void;
  values: RadiusValues;
}) {
  /**
   * TWO LANES, TWO STATE MODELS — and the split is the whole of this component.
   *
   * WEB lane (`onApplyAll` PRESENT): the mount-seeded model, unchanged. Its
   * `committed`/`draft` snapshot (ruling A27) stays exactly as it was until the
   * web lane runs its own live-hydration migration; the web inspector still
   * seeds `state.radius` once at mount, so the snapshot is the only thing there
   * that knows what the document holds.
   *
   * SCENE lane (`onApplyAll` ABSENT, AD4.R Task 7): `values` is LIVE — the ad
   * panel's live-hydrated state — so the five fields are self-drafting
   * projections of it: a draft while being typed, a dirty check against the
   * document itself (`fieldCommit`), and NO post-commit mirrors. The document's
   * own corners, including the derived `all`, arrive through hydration in the
   * same batch as the write.
   *
   * RULING A27, superseded for the scene lane only (plan §"Rulings
   * superseded"): its premise was that the dirty check could not read the
   * `values` prop, because an ad all-corners commit writes all four corners to
   * the DOCUMENT while dispatching one `radius.all` — so the controller's four
   * corner entries stayed where they were, every re-type of a corner's
   * pre-commit number compared EQUAL and committed nothing, and the box kept a
   * number the document did not have. Live hydration removes the premise: the
   * prop now moves with the document, so comparing against it is not merely
   * safe, it is the only comparison that cannot go stale. The WEB lane's
   * premise is untouched, so its snapshot is untouched.
   */
  const [radius, setRadius] = useState(() => ({
    committed: values,
    draft: values,
  }));
  const setDraft = (corner: RadiusCorner, value: string) =>
    setRadius((current) => ({
      ...current,
      draft: { ...current.draft, [corner]: value },
    }));

  /** ── The WEB lane's all-corners commit (F2), untouched ────────────────────
   *
   * RULING A28's scene arm lived here and is RETIRED in AD4.R Task 7 (plan
   * §"Rulings superseded"). A28 split one post-commit mirror into two, because
   * the two lanes were asking different questions of the same commit: the web
   * lane's "does this write CLEAR the per-corner overrides?" (R-B1's integer
   * rule) versus the scene lane's "did this commit produce a WRITE, and with
   * what canonical spelling?" (the adapter's own commit rule, so a fractional
   * all-commit could not leave the four boxes reading the old numbers, and so
   * the mirror could not disagree with the write). The scene lane no
   * longer asks: it does not mirror at all, so it cannot mirror wrongly. Only
   * the web lane's question — and its answer — remain, exactly as ratified. */
  const commitAll = (value: string) => {
    // A29: a locked node refuses every write (§4), so a commit against one
    // records NOTHING — not the mirror, and not `committed` either. Recording it
    // would leave the boxes stating a document the adapter never wrote, and
    // would swallow the same edit again once the node is unlocked.
    if (locked) {
      return;
    }
    // TS NARROWING ONLY, not a behaviour branch — the scene lane never reaches
    // `commitAll` (it commits through `sceneCommit` / `sceneApplyAll`, and both
    // callers below are already behind `scene`), so this is unreachable by
    // construction. It exists because deleting the scene arm removed the
    // `if (!onApplyAll) {…}` that used to narrow `onApplyAll` for the call.
    if (!onApplyAll) return;
    const clearsCorners = NUMERIC_RADIUS.test(value.trim());
    onApplyAll(value, clearsCorners);
    setRadius((current) => ({
      committed: clearsCorners
        ? {
            all: value,
            bottomLeft: "",
            bottomRight: "",
            topLeft: "",
            topRight: "",
          }
        : { ...current.committed, all: value },
      draft: clearsCorners
        ? {
            ...current.draft,
            bottomLeft: "",
            bottomRight: "",
            topLeft: "",
            topRight: "",
          }
        : current.draft,
    }));
  };

  /** The WEB lane's scan button. Its meaning IS the all-corners write, so it
   * commits the all field's current draft even when unchanged — but an empty
   * draft would clear the radius rather than apply one, so it is a no-op. */
  const applyAll = () => {
    if (radius.draft.all.trim() === "") return;
    commitAll(radius.draft.all);
  };

  // ── The SCENE lane (AD4.R Task 7) ─────────────────────────────────────────
  // Five self-drafting projections of the live `values` prop. There is no
  // `committed` here and no post-commit mirror of any kind: what the boxes read
  // after a write is what hydration says the document now holds.
  const scene = !onApplyAll;
  const [drafts, setDrafts] = useState<
    Partial<Record<RadiusCorner, string | undefined>>
  >({});
  const sceneShown = (corner: RadiusCorner) =>
    fieldDisplay(drafts[corner] ?? null, values[corner]);
  const sceneCommit = (corner: RadiusCorner) => {
    // The dirty check compares the draft against the LIVE document value, so it
    // cannot go stale the way A27's snapshot could. Dispatch happens OUTSIDE
    // the state updater — an `onChange` inside one would be a side effect React
    // is free to run twice (the AD4.0 step-1 commit-on-blur rule).
    const commit = fieldCommit(drafts[corner] ?? null, values[corner]);
    setDrafts((current) => ({ ...current, [corner]: undefined }));
    // G-H (AD4.R-10): the in-flight agent turn, on the same terms as the lock.
    // Its own line, BELOW the draft drop and beside rather than inside the
    // guard below — this lane's ratified posture is clear-before-refuse (a
    // refused scan that kept typed text was the latent defect A26/A29 closed),
    // so a refusal here re-states the document rather than holding text.
    // DELIBERATELY THE OPPOSITE of `BackgroundFillControl.commitDraft`, whose
    // ruled posture is keep-the-text: each lane follows its own ratified,
    // test-pinned rule and neither should be "fixed" to match the other.
    // The fields are natively disabled, so this is the programmatic-blur
    // backstop.
    if (disabled) return;
    if (commit === null || locked) return;
    onChange(corner, commit);
  };
  const sceneApplyAll = () => {
    // The scan button's meaning IS the all-corners write (both lanes' ruling),
    // so it commits the shown value even when unchanged — but an empty value
    // would clear rather than apply, so it is a no-op.
    //
    // RULING A26 retired this lane's fan-out-to-four. Those four synchronous
    // per-corner `onChange` calls each dispatched their own event, and the
    // write listener's scene is a passive-effect ref over React state
    // (`use-scene-inspector-writes.ts`), so all four read the SAME pre-burst
    // node — while every radius operation writes the whole `CornerRadii`. The
    // fourth clobbered the first three: a scan of 24 over the seeded ad's
    // 32/32/96/32 image landed 32/32/96/24, one write, four undo steps. One
    // event is still the rule here.
    const value = sceneShown("all");
    // Dropping the draft is UNCONDITIONAL, exactly as in `sceneCommit`: it is
    // what makes the box re-state the document on a scan that dispatched
    // nothing. On a locked node the write is refused, so keeping the typed text
    // would leave the box stating a number the document does not have — the
    // panel-lie class this whole task exists to close.
    setDrafts((current) => ({ ...current, all: undefined }));
    // G-H (AD4.R-10), below the drop for the same reason `sceneCommit` puts it
    // there — this lane clears first and refuses second.
    if (disabled) return;
    if (value.trim() === "" || locked) return;
    onChange("all", value);
  };

  // G-H (AD4.R-10): what the five fields and the scan button LOOK like and
  // whether they accept a pointer at all. One expression so no control in this
  // component can drift from another — the lock and the in-flight window are
  // two reasons for one state.
  const inert = disabled || locked;

  return (
    <>
      <div className={styles.radiusMainRow}>
        <InspectorInput
          ariaLabel="All corner radius"
          className={styles.radiusValue}
          disabled={inert}
          leading={<InspectorIcon name="radius-all" size={16} />}
          onChange={(value) =>
            scene
              ? setDrafts((current) => ({ ...current, all: value }))
              : setDraft("all", value)
          }
          onCommit={() => {
            if (scene) {
              sceneCommit("all");
              return;
            }
            if (radius.draft.all !== radius.committed.all) commitAll(radius.draft.all);
          }}
          value={scene ? sceneShown("all") : radius.draft.all}
        />
        <button aria-label="Apply radius to all corners" className={`${styles.scanButton} ${inert ? styles.inspectorControlDisabled : ""}`} disabled={inert} onClick={scene ? sceneApplyAll : applyAll} type="button">
          <InspectorIcon name="radius-scan" size={12} />
        </button>
      </div>
      <div className={styles.cornerRadiusGrid}>
        {([
          ["topLeft", "radius-top-left"],
          ["topRight", "radius-top-right"],
          ["bottomLeft", "radius-bottom-left"],
          ["bottomRight", "radius-bottom-right"],
        ] as const).map(([corner, icon]) => {
          // The WEB lane's corner commit, unchanged. RULING A31's canonicalizing
          // mirror lived in its scene arm and is RETIRED in AD4.R Task 7 (plan
          // §"Rulings superseded"): A31 stored what the WRITE produced rather
          // than what was typed, because a raw `5.0` on a uniformly-5 node wrote
          // a correctly uniform document while the component's own string
          // comparison of the four corners saw `"5.0" !== "5"` and blanked the
          // derived `all`. Nothing in this lane stores typed text any more —
          // hydrate supplies the spelling AND the derivation — so the mismatch
          // has no surface left to occur on.
          const commit = () => {
            // A29: nothing a locked node refuses may be recorded (see
            // `commitAll`).
            if (locked) return;
            // Read this render's draft and dispatch OUTSIDE the updater — a
            // `onChange` inside one would be a side effect React is free to run
            // twice (the AD4.0 step-1 commit-on-blur rule).
            const typed = radius.draft[corner];
            if (typed === radius.committed[corner]) return;
            onChange(corner, typed);
            // The raw text, and `all` is its own class and is not derived from
            // the corners, so it keeps what it had. Unchanged since A27.
            setRadius((current) => ({
              ...current,
              committed: { ...current.committed, [corner]: typed },
            }));
          };
          return (
            <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${styles.cornerRadiusField} ${inert ? styles.inspectorControlDisabled : ""}`} key={corner}>
              <InspectorIcon name={icon} size={16} />
              <input
                aria-label={`${corner} radius`}
                disabled={inert}
                onBlur={scene ? () => sceneCommit(corner) : commit}
                onChange={(event) =>
                  scene
                    ? setDrafts((current) => ({
                        ...current,
                        [corner]: event.target.value,
                      }))
                    : setDraft(corner, event.target.value)
                }
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  if (scene) sceneCommit(corner);
                  else commit();
                }}
                value={scene ? sceneShown(corner) : radius.draft[corner]}
              />
            </span>
          );
        })}
      </div>
    </>
  );
}

type HsvColor = { h: number; s: number; v: number };

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function hexToHsv(hex: string): HsvColor {
  const normalized = hex.replace("#", "").padEnd(6, "0").slice(0, 6);
  // A value that is not a hex — the `none` sentinel, or a brand token's
  // `$name`, which A16 put on swatches users open often — parses to NaN, and
  // the picker then rendered `NaN%` into the plane's thumb and the hue slider.
  // Nothing chose that; a colour the picker cannot place starts at black,
  // which is defined, and the first drag replaces it. (Pre-existing: the
  // stroke row has hydrated token names since AD2.4.)
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    return { h: 0, s: 0, v: 0 };
  }
  const red = Number.parseInt(normalized.slice(0, 2), 16) / 255;
  const green = Number.parseInt(normalized.slice(2, 4), 16) / 255;
  const blue = Number.parseInt(normalized.slice(4, 6), 16) / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  let hue = 0;

  if (delta !== 0) {
    if (max === red) hue = 60 * (((green - blue) / delta) % 6);
    else if (max === green) hue = 60 * ((blue - red) / delta + 2);
    else hue = 60 * ((red - green) / delta + 4);
  }

  return {
    h: hue < 0 ? hue + 360 : hue,
    s: max === 0 ? 0 : (delta / max) * 100,
    v: max * 100,
  };
}

function hsvToHex({ h, s, v }: HsvColor) {
  const saturation = clamp(s, 0, 100) / 100;
  const value = clamp(v, 0, 100) / 100;
  const chroma = value * saturation;
  const hueSegment = ((h % 360) + 360) % 360 / 60;
  const x = chroma * (1 - Math.abs((hueSegment % 2) - 1));
  const match = value - chroma;
  const [red, green, blue] =
    hueSegment < 1 ? [chroma, x, 0]
      : hueSegment < 2 ? [x, chroma, 0]
        : hueSegment < 3 ? [0, chroma, x]
          : hueSegment < 4 ? [0, x, chroma]
            : hueSegment < 5 ? [x, 0, chroma]
              : [chroma, 0, x];
  const channel = (value: number) => Math.round((value + match) * 255).toString(16).padStart(2, "0");
  return `#${channel(red)}${channel(green)}${channel(blue)}`.toUpperCase();
}

export function ColorControl({
  color = "#FFFFFF",
  disabled = false,
  none = false,
  noneAriaLabel = "Color is none",
  onColorChange,
  onOpacityChange,
  onTokenChange,
  opacity = "100%",
  options,
  showOpacity = true,
}: {
  color?: string;
  /** AD4.R-10 (G-H): the swatch may not produce a document operation — a locked
   * node, or an agent turn in flight. Absent is `false` (the web lane, the
   * dummy fixture path), unchanged.
   *
   * The picker cannot be OPENED rather than opening dead: every write this
   * control makes happens inside the popover (a theme pick, the hex field, the
   * plane, the hue slider, the recent strip), so disabling the trigger closes
   * all of them at once — and a picker you can open but cannot commit from is a
   * worse lie than one that visibly will not open. The three commits below are
   * guarded ANYWAY, because a popover that was already open when the flag
   * flipped survives the flip (see `commitColor`). */
  disabled?: boolean;
  none?: boolean;
  noneAriaLabel?: string;
  onColorChange?: (color: string) => void;
  onOpacityChange?: (opacity: string) => void;
  /** W3.2 (R2): fired with the token LABEL on a theme-tab pick — the live
   * write path; hex (custom tab) stays visual-only per §3. */
  onTokenChange?: (label: string) => void;
  opacity?: string;
  /** W4.0: the document's real theme tokens for the Theme tab. Omitted (or
   * empty) means an EMPTY Theme tab — there is no fixture palette to fall
   * back to (founder ruling 2026-09-04). */
  options?: readonly ThemeColorOption[];
  showOpacity?: boolean;
}) {
  const themeColors = resolveInspectorThemeColors(options);
  const [draftColor, setDraftColor] = useState(color.toUpperCase());
  const [pickerMode, setPickerMode] = useState<"custom" | "theme">("theme");
  const [customColor, setCustomColor] = useState<HsvColor>(() => hexToHsv(color));
  const colorControlRef = useRef<HTMLSpanElement>(null);

  /** The control's OWN state moved to a colour it can hold, and the colour it
   * moved to (or `null` when the value is not one — the hex field's mid-typing
   * text, a theme value that is not a hex). Split out of `commitColor` by
   * AD4.0 step 3 so a theme pick can move the swatch WITHOUT reporting a hex
   * to the caller; the acceptance rule is unchanged and still lives in one
   * place. */
  const previewColor = (nextColor: string): string | null => {
    const normalized = nextColor.startsWith("#") ? nextColor : `#${nextColor}`;
    if (!/^#[0-9A-F]{6}$/i.test(normalized)) {
      return null;
    }
    const upper = normalized.toUpperCase();
    setDraftColor(upper);
    setCustomColor(hexToHsv(upper));
    return upper;
  };

  /**
   * G-H (AD4.R-10): every write this control makes is funnelled through the
   * three commit paths below, and each one refuses while the control is
   * disabled.
   *
   * WHY THE TRIGGER GUARD IS NOT ENOUGH. Disabling `Popover.Trigger` stops the
   * picker being OPENED, but a popover that was ALREADY OPEN when the flag
   * flipped — an agent turn starting while the marketer has the swatch open,
   * the ordinary case — survives the flip, and every control inside it (the
   * theme swatches, the hex field, the saturation plane, the hue slider, the
   * recent strip) would go on writing. Refusing at the commits closes all of
   * them at once without new popover-state plumbing, which is why closing the
   * popover on flip is deliberately NOT done here.
   *
   * THE LOCAL PREVIEW IS REFUSED TOO, not just the callback: `previewColor`
   * moves this control's own swatch, and moving it over a document the write
   * path refused is the panel-lie class this whole slice exists to close.
   */
  const commitColor = (nextColor: string) => {
    if (disabled) return;
    const upper = previewColor(nextColor);
    if (upper !== null) {
      onColorChange?.(upper);
    }
  };

  const commitCustomColor = (nextColor: HsvColor) => {
    if (disabled) return;
    const nextHex = hsvToHex(nextColor);
    setCustomColor(nextColor);
    setDraftColor(nextHex);
    onColorChange?.(nextHex);
  };

  const updateSaturationAndValue = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    commitCustomColor({
      ...customColor,
      s: clamp(((event.clientX - bounds.left) / bounds.width) * 100, 0, 100),
      v: 100 - clamp(((event.clientY - bounds.top) / bounds.height) * 100, 0, 100),
    });
  };

  return (
    <span
      className={`${styles.colorControl} ${disabled ? styles.inspectorControlDisabled : ""}`}
      ref={colorControlRef}
    >
      {none ? (
        <button
          aria-label={noneAriaLabel}
          className={`${styles.colorValue} ${styles.colorValueSingle}`}
          disabled
          type="button"
        >
          <span className={`${styles.colorSwatch} ${styles.colorSwatchNone}`} />
          <span>None</span>
        </button>
      ) : (
        <Popover.Root
          onOpenChange={(open) => {
            if (open) {
              setDraftColor(color.toUpperCase());
              setCustomColor(hexToHsv(color));
            }
          }}
        >
          <Popover.Trigger
            aria-label={`Choose color ${color}`}
            className={`${styles.colorValue} ${!showOpacity ? styles.colorValueSingle : ""}`}
            disabled={disabled}
          >
            <span className={styles.colorSwatch} style={{ background: color }} />
            <span>{color.toUpperCase()}</span>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Positioner
              align="start"
              anchor={colorControlRef}
              className={styles.inspectorColorPositioner}
              side="right"
              sideOffset={8}
            >
              <Popover.Popup className={styles.inspectorColorPopup}>
                <div aria-label="Color picker mode" className={styles.inspectorColorTabs} role="tablist">
                  <button
                    aria-selected={pickerMode === "theme"}
                    className={pickerMode === "theme" ? styles.inspectorColorTabActive : ""}
                    onClick={() => setPickerMode("theme")}
                    role="tab"
                    type="button"
                  >
                    Theme
                  </button>
                  <button
                    aria-selected={pickerMode === "custom"}
                    className={pickerMode === "custom" ? styles.inspectorColorTabActive : ""}
                    onClick={() => setPickerMode("custom")}
                    role="tab"
                    type="button"
                  >
                    Custom
                  </button>
                </div>

                {pickerMode === "theme" ? (
                  <div aria-label="Theme colors" className={styles.inspectorThemeColors} role="tabpanel">
                    {themeColors.map((option) => (
                      <button
                        aria-label={`Use ${option.label} color ${option.value}`}
                        aria-pressed={color.toUpperCase() === option.value.toUpperCase()}
                        className={styles.inspectorThemeColor}
                        key={option.label}
                        onClick={() => {
                          // W3.2 (R2): a theme-tab pick reports the TOKEN
                          // label — the live write path; the hex drives the
                          // visual state only.
                          //
                          // AD4.0 step 3 makes that division TRUE for a lane
                          // whose hex path also writes. On the website lane
                          // `onColorChange`'s `textColor`/`backgroundColor`
                          // events map to no operation (`adapter/apply.ts`
                          // maps only the `token*` properties), so calling
                          // both was free. §1.6 makes the ad lane's custom hex
                          // a REAL write, so one theme pick would have
                          // persisted TWO document versions — a solid hex,
                          // then the token that replaces it — leaving an undo
                          // step on a detached state the user never asked for.
                          // A caller that takes tokens therefore gets the
                          // token alone; the swatch's own draft state is still
                          // moved, so the popover shows the pick either way.
                          //
                          // G-H (AD4.R-10): the token branch is the one write
                          // path that does NOT run through `commitColor`, so it
                          // carries the refusal itself — an already-open
                          // popover outlives the flag flip (see `commitColor`),
                          // and this is the branch the ad lane actually takes.
                          if (disabled) return;
                          if (onTokenChange) {
                            previewColor(option.value);
                            onTokenChange(option.label);
                            return;
                          }
                          commitColor(option.value);
                        }}
                        type="button"
                      >
                        <span className={styles.inspectorThemeSwatch} style={{ background: option.value }} />
                        <span>{option.label}</span>
                        <span className={styles.inspectorThemeValue}>{option.value}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div
                    className={styles.inspectorCustomColor}
                    role="tabpanel"
                    style={{ "--inspector-picker-hue": `${customColor.h}` } as CSSProperties}
                  >
                    <button
                      aria-label="Color saturation and brightness"
                      className={styles.inspectorColorPlane}
                      onPointerDown={(event) => {
                        event.currentTarget.setPointerCapture(event.pointerId);
                        updateSaturationAndValue(event);
                      }}
                      onPointerMove={(event) => {
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) updateSaturationAndValue(event);
                      }}
                      onPointerUp={(event) => {
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                          event.currentTarget.releasePointerCapture(event.pointerId);
                        }
                      }}
                      type="button"
                    >
                      <span
                        className={styles.inspectorColorPlaneThumb}
                        style={{ left: `${customColor.s}%`, top: `${100 - customColor.v}%` }}
                      />
                    </button>
                    <label className={styles.inspectorHueField}>
                      <span className={styles.srOnly}>Hue</span>
                      <input
                        aria-label="Color hue"
                        max="360"
                        min="0"
                        onChange={(event) => commitCustomColor({ ...customColor, h: Number(event.target.value) })}
                        type="range"
                        value={Math.round(customColor.h)}
                      />
                    </label>
                  </div>
                )}

                <label className={styles.inspectorHexField}>
                  <span>Hex</span>
                  <input
                    aria-label="Hex color"
                    maxLength={7}
                    onBlur={() => commitColor(draftColor)}
                    onChange={(event) => setDraftColor(event.target.value.toUpperCase())}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitColor(draftColor);
                    }}
                    value={draftColor}
                  />
                </label>
                <div aria-label="Recent colors" className={styles.inspectorColorSwatches} role="group">
                  {/* RULING A21 (2026-08-21): the strip's EXISTENCE is dummy
                      truth and stays, but its CONTENTS are now the palette's
                      first four rather than four hardcoded fixture colours —
                      it commits a real hex on a live write path, so inside the
                      one control §1.6 governs it was offering off-brand
                      colours the document has never seen. `themeColors` is
                      already "the palette, else the fixture, else (A23)
                      nothing", so the whole rule is that one expression.
                      (The "Recent" LABEL is wrong either way; relabelling is
                      founder copy and is on the founder's list, not here.) */}
                  {themeColors.slice(0, 4).map((option) => (
                    <button
                      aria-label={`Use color ${option.value}`}
                      aria-pressed={color.toUpperCase() === option.value}
                      className={styles.inspectorColorSwatchButton}
                      key={option.label}
                      onClick={() => commitColor(option.value)}
                      style={{ "--inspector-swatch": option.value } as CSSProperties}
                      type="button"
                    />
                  ))}
                </div>
              </Popover.Popup>
            </Popover.Positioner>
          </Popover.Portal>
        </Popover.Root>
      )}
      {!none && showOpacity ? (
        <span className={`${styles.opacityValue} ${styles.inspectorInputControl}`}>
          <input
            aria-label="Color opacity"
            disabled={disabled}
            onChange={(event) => {
              if (disabled) return;
              onOpacityChange?.(event.target.value);
            }}
            value={opacity}
          />
        </span>
      ) : null}
    </span>
  );
}

const BACKGROUND_FILL_LABELS = ["Solid", "Linear gradient", "Radial gradient"] as const;

const BACKGROUND_FILL_TYPES: Record<(typeof BACKGROUND_FILL_LABELS)[number], InspectorFillType> = {
  "Linear gradient": "linear-gradient",
  "Radial gradient": "radial-gradient",
  Solid: "solid",
};

const BACKGROUND_FILL_TYPE_LABELS: Record<InspectorFillType, (typeof BACKGROUND_FILL_LABELS)[number]> = {
  "linear-gradient": "Linear gradient",
  "radial-gradient": "Radial gradient",
  solid: "Solid",
};

function backgroundFillCss(fill: InspectorBackgroundFill, solidColor: string) {
  if (fill.type === "solid") return solidColor;

  const stops = [...fill.stops]
    .sort((left, right) => left.position - right.position)
    .map((stop) => `${stop.color} ${stop.position}%`)
    .join(", ");

  return fill.type === "radial-gradient"
    ? `radial-gradient(circle at center, ${stops})`
    : `linear-gradient(${fill.angle}deg, ${stops})`;
}

export function BackgroundFillControl({
  disabled = false,
  fill,
  onFillChange,
  onSolidColorChange,
  onTokenChange,
  options,
  solidColor,
}: {
  /** AD4.R-10 (G-H): forwarded to every control this section owns — the mode
   * select, both nested pickers, the angle and stop-position fields, and the
   * add/remove stop buttons. Absent is `false`, so the web lane is unchanged.
   * The gradient PREVIEW is not a control and keeps its full opacity: it states
   * the document, and the document is not what went dark. */
  disabled?: boolean;
  fill: InspectorBackgroundFill;
  onFillChange: (fill: InspectorBackgroundFill) => void;
  onSolidColorChange: (color: string) => void;
  /** AD4.0 step 3 (§1.6): a brand pick on the SOLID swatch, reported as the
   * token's label. The gradient stops deliberately do not take it — a stop has
   * no token row in the write table, so a brand pick there commits the colour
   * it paints, which is what this control has always done. */
  onTokenChange?: (label: string) => void;
  /** AD4.0 step 3 (§1.6): the document's brand palette, forwarded to BOTH
   * nested pickers so every swatch in this section offers it. A data prop on a
   * lifted presentation component — the W4.0 precedent — and nothing rendered
   * changes: `ColorControl` already takes `options` and falls back to the
   * dummy's fixture palette when it is absent or empty. */
  options?: readonly ThemeColorOption[];
  solidColor: string;
}) {
  // Ruling A7 (AD4.0 step 2): the angle and the stop positions COMMIT ON
  // BLUR/ENTER, not per keystroke — the same model, and the same defect, that
  // step 1 settled for the Custom W/H boxes. Typing `137` into a cleared angle
  // box used to persist four document versions and four undo steps, the first
  // of them a spurious `angle: 0`.
  //
  // ONE draft is enough for both fields: only one input can hold focus, and
  // `onCommit` fires on blur before the next field can change. The draft is
  // what the user sees while typing; only the commit reaches `onFillChange`.
  // Markup, classes, labels and layout are untouched — this is the same
  // data/behaviour-prop binding `InspectorInput` already ships for W/H.
  const [draft, setDraft] = useState<{ field: string; value: string } | null>(null);
  const draftValue = (field: string, committed: number) =>
    draft?.field === field ? draft.value : String(committed);
  const commitDraft = (
    field: string,
    max: number,
    write: (value: number) => void,
  ) => {
    const typed = draft?.field === field ? draft.value : null;
    // G-H (AD4.R-10): the fields are natively disabled, so this is the
    // programmatic-blur backstop — and IT MUST SIT ABOVE `setDraft(null)`.
    // Clearing the draft is itself a change the user did not ask for: a refused
    // commit that also wiped the typed text would throw the angle/position away
    // and snap the box back to the document. This lane's ruled posture is
    // keep-the-text, DELIBERATELY THE OPPOSITE of `RadiusControls`' scene lane
    // (clear-before-refuse, F4-pinned there because a locked scan holding typed
    // text was a latent defect). Each follows its own ratified rule; neither
    // should be "fixed" to match the other.
    if (disabled) {
      return;
    }
    setDraft(null);
    if (typed === null) {
      return;
    }
    // `null` is mid-edit text ("", "-", "1e"): nothing to commit, and the field
    // falls back to what the document says rather than to a guessed 0.
    const value = commitInspectorNumber(typed, max);
    if (value !== null) {
      write(value);
    }
  };
  const updateStop = (index: number, update: Partial<InspectorBackgroundFill["stops"][number]>) => {
    if (disabled) return;
    onFillChange({
      ...fill,
      stops: fill.stops.map((stop, stopIndex) => stopIndex === index ? { ...stop, ...update } : stop),
    });
  };

  const addStop = () => {
    if (disabled) return;
    if (fill.stops.length >= 6) return;
    const sorted = [...fill.stops].sort((left, right) => left.position - right.position);
    let largestGapIndex = 0;
    let largestGap = -1;
    for (let index = 0; index < sorted.length - 1; index += 1) {
      const gap = sorted[index + 1].position - sorted[index].position;
      if (gap > largestGap) {
        largestGap = gap;
        largestGapIndex = index;
      }
    }
    const before = sorted[largestGapIndex];
    const after = sorted[largestGapIndex + 1] ?? before;
    const nextStop = {
      color: before.color,
      position: Math.round((before.position + after.position) / 2),
    };
    onFillChange({
      ...fill,
      stops: [...fill.stops, nextStop].sort((left, right) => left.position - right.position),
    });
  };

  return (
    <div className={styles.backgroundFillControl}>
      <InspectorSelect
        disabled={disabled}
        label="Background fill type"
        onChange={(label) => onFillChange({ ...fill, type: BACKGROUND_FILL_TYPES[label as keyof typeof BACKGROUND_FILL_TYPES] })}
        options={BACKGROUND_FILL_LABELS}
        value={BACKGROUND_FILL_TYPE_LABELS[fill.type]}
      />

      {fill.type === "solid" ? (
        <ColorControl
          color={solidColor}
          disabled={disabled}
          onColorChange={onSolidColorChange}
          onTokenChange={onTokenChange}
          options={options}
        />
      ) : (
        <>
          <div
            aria-label={`${BACKGROUND_FILL_TYPE_LABELS[fill.type]} preview`}
            className={styles.backgroundGradientPreview}
            style={{ background: backgroundFillCss(fill, solidColor) }}
          />

          {fill.type === "linear-gradient" ? (
            <label className={styles.backgroundGradientAngle}>
              <span>Angle</span>
              {/* `disabled` is deliberately NOT in alphabetical position here:
                  the A7 wiring guard (`inspector-commit-model.test.ts`) pins
                  this field's `ariaLabel → onChange → onCommit` shape as proof
                  the angle commits on blur rather than per keystroke, and that
                  guard is worth more than the ordering convention. */}
              <InspectorInput
                ariaLabel="Gradient angle"
                onChange={(value) => setDraft({ field: "angle", value })}
                onCommit={() =>
                  commitDraft("angle", 360, (angle) => onFillChange({ ...fill, angle }))
                }
                disabled={disabled}
                suffix="°"
                value={draftValue("angle", fill.angle)}
              />
            </label>
          ) : null}

          <div className={styles.backgroundGradientStops}>
            {fill.stops.map((stop, index) => (
              <div className={styles.backgroundGradientStop} key={`${index}-${stop.color}`}>
                <ColorControl
                  color={stop.color}
                  disabled={disabled}
                  onColorChange={(color) => updateStop(index, { color })}
                  options={options}
                  showOpacity={false}
                />
                <InspectorInput
                  ariaLabel={`Gradient stop ${index + 1} position`}
                  className={styles.backgroundGradientPosition}
                  disabled={disabled}
                  onChange={(value) => setDraft({ field: `stop-${index}`, value })}
                  onCommit={() =>
                    commitDraft(`stop-${index}`, 100, (position) =>
                      updateStop(index, { position }),
                    )
                  }
                  suffix="%"
                  value={draftValue(`stop-${index}`, stop.position)}
                />
                <button
                  aria-label={`Remove gradient stop ${index + 1}`}
                  className={styles.backgroundGradientRemove}
                  disabled={disabled || fill.stops.length <= 2}
                  onClick={() => onFillChange({ ...fill, stops: fill.stops.filter((_, stopIndex) => stopIndex !== index) })}
                  type="button"
                >
                  <MinusIcon aria-hidden="true" absoluteStrokeWidth size={14} strokeWidth={1.5} />
                </button>
              </div>
            ))}
          </div>

          <button
            className={styles.backgroundGradientAdd}
            disabled={disabled || fill.stops.length >= 6}
            onClick={addStop}
            type="button"
          >
            <PlusIcon aria-hidden="true" absoluteStrokeWidth size={13} strokeWidth={1.5} />
            <span>Add color stop</span>
          </button>
        </>
      )}
    </div>
  );
}

export function InspectorImageUpload({
  disabled = false,
  onFileSelect,
  onOpenLibrary,
  src,
}: {
  /** AD4.R-10 (G-H): Replace image is an OPERATION — a locked node, or an agent
   * turn in flight, may not start one. Absent is `false` (the web lane, the
   * dummy fixture path), unchanged. The tile still shows the node's picture at
   * the ruled opacity: it is the panel's statement of the document, and a
   * blanked thumbnail would be a different (and false) statement. */
  disabled?: boolean;
  /** AD4.A step 2: a handler may REPORT that the document did not take the
   * file, by returning a promise that rejects — the preview then goes back to
   * what the panel was showing. A `void` handler (the dummy fixture path, and
   * the website lane's own, which swallows its failures into the inspector's
   * error slot) behaves exactly as it always has. */
  onFileSelect?: (file: File) => void | Promise<void>;
  /** Replace-image lane (option A, founder ruling R-C): when present the pill
   * opens a two-row menu — upload from the computer, or pick from the
   * workspace asset library. ABSENT keeps the dummy fixture path's direct file
   * dialog, byte for byte: same button, same aria-label, same classes. */
  onOpenLibrary?: () => void;
  src: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [previewSrc, setPreviewSrc] = useState(src);

  // AD4.A step 2 review (FIX 2): the DOCUMENT's own asset outranks whatever
  // this control put on screen. `src` is a fact about the selected node, so a
  // NEW value means the node now carries a different picture and the local
  // preview — a data: URL of a file the user picked a moment ago — is stale.
  //
  // Without this, one sequence froze the thumbnail on the old image: a reload
  // landing INSIDE the upload window (a CAS conflict on an earlier edit)
  // remounts the panel, the new mount seeds `previewSrc` from the pre-upload
  // asset, and the upload then lands with nothing left to update it — the
  // artboard repainting with the new picture beside a thumbnail still showing
  // the old one.
  //
  // React's own adjust-state-on-prop-change (a render-time comparison, the
  // pattern `use-scene-manual-edits.ts` and `scene-artifact-canvas.tsx` already
  // use), never an effect: an effect would render one frame of the stale value
  // first, and this repo's react-hooks lint bars set-state in an effect. It is
  // NOT a general re-hydrate mechanism — it tracks exactly one string, and an
  // unchanged `src` (the website lane, whose value is mount-frozen, and the
  // dummy fixture path) never triggers it.
  const [lastSrc, setLastSrc] = useState(src);
  if (lastSrc !== src) {
    setLastSrc(src);
    setPreviewSrc(src);
  }

  const selectFile = (file: File) => {
    // G-H (AD4.R-10): the picker cannot be opened while this control is
    // disabled, so this is the backstop for a file event that arrives any other
    // way — a preview swap is itself a claim about the document.
    if (disabled) return;
    // What the panel is showing RIGHT NOW — the node's own asset, or the
    // picture a previous pick put there. A refused upload must land back on it:
    // a preview of an image the document does not have is the panel lying about
    // the document, and the file picker is the one control that changes its own
    // display before any write has happened.
    const restore = previewSrc;
    let refused = false;
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      // The read can finish AFTER the refusal (a locked node refuses before the
      // transport, in the same tick), so the outcome wins over the preview.
      if (refused) return;
      if (typeof reader.result === "string") setPreviewSrc(reader.result);
    });
    reader.readAsDataURL(file);
    void Promise.resolve(onFileSelect?.(file)).catch(() => {
      refused = true;
      setPreviewSrc(restore);
    });
  };

  const openFileDialog = () => inputRef.current?.click();

  // The pill's face is the SAME in both branches — the node's picture and its
  // label — so the menu path cannot drift from the dummy path's appearance.
  // The caret is the only difference, and it renders only when there is a menu
  // behind it to open.
  const pill = (
    <>
      <Image
        alt=""
        fill
        sizes="248px"
        src={previewSrc}
        // W4.2 (§1 row 12): a local FileReader preview is a data: URL the
        // optimizer cannot fetch, and a `/api/clue/` src is an AUTHENTICATED
        // BFF route — the optimizer fetches server-side without the session
        // cookies, so an optimized pass would 401. Both go through unchanged.
        unoptimized={
          previewSrc.startsWith("data:") || previewSrc.startsWith("/api/clue/")
        }
      />
      <span>
        Replace image
        {onOpenLibrary ? <span aria-hidden className={styles.imageReplaceCaret}>▾</span> : null}
      </span>
    </>
  );

  return (
    <>
      {onOpenLibrary ? (
        <Menu.Root>
          <Menu.Trigger
            aria-label="Replace image"
            className={`${styles.imageReplaceField} ${disabled ? styles.inspectorControlDisabled : ""}`}
            disabled={disabled}
          >
            {pill}
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Positioner align="center" className={styles.inspectorSelectPositioner} side="bottom" sideOffset={6}>
              <Menu.Popup className={styles.replaceImageMenu}>
                {REPLACE_IMAGE_MENU_ROWS.map((row) => (
                  <Menu.Item
                    className={styles.replaceImageMenuItem}
                    key={row.id}
                    onClick={() => {
                      const action = replaceImageMenuAction(row.id);
                      if (action.kind === "open-file-dialog") openFileDialog();
                      else onOpenLibrary();
                    }}
                  >
                    <ReplaceImageMenuIcon row={row.id} />
                    {row.label}
                  </Menu.Item>
                ))}
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      ) : (
        <button
          aria-label="Replace image"
          className={`${styles.imageReplaceField} ${disabled ? styles.inspectorControlDisabled : ""}`}
          disabled={disabled}
          onClick={openFileDialog}
          type="button"
        >
          {pill}
        </button>
      )}
      <input
        // No GIF: the design API sniffs the bytes and refuses it, so offering it
        // in the dialog only buys the user a rejected upload.
        accept="image/png,image/jpeg,image/webp,image/svg+xml"
        className={styles.visuallyHiddenInput}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) selectFile(file);
          event.target.value = "";
        }}
        ref={inputRef}
        type="file"
      />
    </>
  );
}

function ReplaceImageMenuIcon({ row }: { row: "upload" | "library" }) {
  // 1.1px strokes (founder ruling R-C), currentColor.
  return row === "upload" ? (
    <svg aria-hidden className={styles.replaceImageMenuIcon} fill="none" stroke="currentColor" strokeWidth="1.1" viewBox="0 0 16 16"><path d="M8 11V3M4.5 6.5 8 3l3.5 3.5M3 12.5h10" /></svg>
  ) : (
    <svg aria-hidden className={styles.replaceImageMenuIcon} fill="none" stroke="currentColor" strokeWidth="1.1" viewBox="0 0 16 16"><rect height="5" rx="1" width="5" x="2" y="2" /><rect height="5" rx="1" width="5" x="9" y="2" /><rect height="5" rx="1" width="5" x="2" y="9" /><rect height="5" rx="1" width="5" x="9" y="9" /></svg>
  );
}

export function InspectorLayerRow({
  accented = false,
  active,
  depth = 0,
  expanded,
  expandable = false,
  icon,
  label,
  onClick,
  trailing = false,
}: {
  accented?: boolean;
  active?: boolean;
  depth?: number;
  expanded?: boolean;
  expandable?: boolean;
  icon: Extract<InspectorIconName, "apple" | "div" | "ellipse" | "image" | "layout-template" | "rectangle" | "square-dashed" | "type">;
  label: string;
  /** AD2.6: type-only widening (the handler is still passed straight to the
   * button, so nothing rendered changes). §1.7's additive multi-select needs
   * the click's shift/⌘ modifiers, and every existing zero-argument caller
   * stays assignable. */
  onClick?: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  trailing?: boolean;
}) {
  const rowRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (active) {
      rowRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [active]);

  return (
    <button
      className={`${styles.layerRow} ${depth ? styles.layerRowNested : ""} ${active ? styles.layerRowActive : ""} ${accented ? styles.layerRowAccented : ""}`}
      aria-expanded={expandable ? expanded : undefined}
      onClick={onClick}
      ref={rowRef}
      style={{ "--layer-depth": depth } as CSSProperties}
      type="button"
    >
      {depth ? <span className={styles.layerTreeRule} /> : null}
      <span className={styles.layerRowContent}>
        <span className={styles.layerRowLabel}>
          <InspectorIcon name={icon} size={16} />
          <span className={styles.layerRowLabelText} title={label}>
            {label}
          </span>
        </span>
        {trailing ? <InspectorIcon name="layer-ellipsis" size={16} /> : null}
      </span>
    </button>
  );
}

/**
 * Text alignment toggles, shared by the ad, web and site panels (it was two private copies). The ad
 * panel offers four horizontal options and the vertical group; the web panel three, with its vertical
 * group hidden; the site panel four and no vertical group (a web text box hugs its text). `vertical`
 * absent means no vertical group.
 */
export function TextAlignment({
  disabled = false,
  horizontal,
  onHorizontalChange,
  onVerticalChange,
  options,
  vertical,
}: {
  /** G-H (AD4.R-10): these toggles write an alignment, so they go dark with the rest of the panel. */
  disabled?: boolean;
  horizontal: HorizontalAlignment;
  onHorizontalChange: (value: HorizontalAlignment) => void;
  onVerticalChange?: (value: "bottom" | "middle" | "top") => void;
  options: "three" | "four";
  vertical?: "bottom" | "middle" | "top";
}) {
  const horizontalOptions = (
    [
      ["left", "align-left"],
      ["center", "align-center"],
      ["right", "align-right"],
      ["justify", "align-justify"],
    ] as const
  ).slice(0, options === "four" ? 4 : 3);
  const verticalOptions = [
    ["top", "align-top"],
    ["middle", "align-middle"],
    ["bottom", "align-bottom"],
  ] as const;
  const groupClass = (...names: (string | false)[]) =>
    [...names, disabled && styles.inspectorControlDisabled].filter(Boolean).join(" ");

  return (
    <div className={styles.alignmentGroups}>
      <div aria-label="Horizontal alignment" className={groupClass(styles.alignmentControl, options === "four" && styles.alignmentControlQuad)} role="group">
        {horizontalOptions.map(([value, icon]) => (
          <button aria-label={`Align ${value}`} aria-pressed={horizontal === value} className={horizontal === value ? styles.alignmentActive : ""} disabled={disabled} key={value} onClick={() => onHorizontalChange(value)} type="button">
            <InspectorIcon name={icon} size={12} />
          </button>
        ))}
      </div>
      {vertical === undefined ? null : (
        <div aria-label="Vertical alignment" className={groupClass(styles.alignmentControl, styles.verticalAlignment)} role="group">
          {verticalOptions.map(([value, icon]) => (
            <button aria-label={`Align ${value}`} aria-pressed={vertical === value} className={vertical === value ? styles.alignmentActive : ""} disabled={disabled} key={value} onClick={() => onVerticalChange?.(value)} type="button">
              <InspectorIcon name={icon} size={12} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Bold, italic and underline as three toggles in the alignment control's segmented style (the site
 * element inspector's Style row). Each shows its letter in its own style and says whether it is on.
 */
export function TextStyleToggles({
  bold,
  boldDisabled = false,
  disabled = false,
  italic,
  onBoldChange,
  onItalicChange,
  onUnderlineChange,
  underline,
}: {
  bold: boolean;
  /** Bold alone cannot act (a font with nothing heavier than regular); the panel says why. */
  boldDisabled?: boolean;
  disabled?: boolean;
  italic: boolean;
  onBoldChange: (on: boolean) => void;
  onItalicChange: (on: boolean) => void;
  onUnderlineChange: (on: boolean) => void;
  underline: boolean;
}) {
  const toggles = [
    { label: "Bold", on: bold, change: onBoldChange, glyph: <b>B</b>, off: boldDisabled },
    { label: "Italic", on: italic, change: onItalicChange, glyph: <i>I</i>, off: false },
    { label: "Underline", on: underline, change: onUnderlineChange, glyph: <u>U</u>, off: false },
  ];
  return (
    <div aria-label="Text style" className={[styles.alignmentControl, disabled && styles.inspectorControlDisabled].filter(Boolean).join(" ")} role="group">
      {toggles.map((toggle) => (
        <button aria-label={toggle.label} aria-pressed={toggle.on} className={toggle.on ? styles.alignmentActive : ""} disabled={disabled || toggle.off} key={toggle.label} onClick={() => toggle.change(!toggle.on)} type="button">
          {toggle.glyph}
        </button>
      ))}
    </div>
  );
}

/** A row of choices, one pressed (shared by the web inspector and the site inspector). */
export function SegmentedControl<Value extends string>({
  ariaLabel,
  disabled = false,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  disabled?: boolean;
  onChange: (value: Value) => void;
  options: readonly { label: ReactNode; value: Value }[];
  value: Value;
}) {
  return (
    <div aria-label={ariaLabel} className={styles.inspectorSegmentedControl} role="group">
      {options.map((option) => (
        <button
          aria-pressed={option.value === value}
          className={option.value === value ? styles.inspectorSegmentActive : ""}
          disabled={disabled}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
