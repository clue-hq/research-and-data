"use client";

import Image from "next/image";
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
import { radiusCommitText } from "@/features/design-editor/adapter/scene-hydrate";
import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";
import {
  commitInspectorNumber,
  type InspectorBackgroundFill,
  type InspectorFillType,
} from "../hooks/use-inspector-controller";
import { resolveInspectorThemeColors } from "../model/inspector-theme-colors";
import { fieldCommit, fieldDisplay } from "./inspector-field-draft";
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
      <span>{title}</span>
      <div className={styles.inspectorHeaderActions}>
        {elementActions ? (
          <>
            <button
              aria-label={locked ? "Unlock element" : "Lock element"}
              aria-pressed={locked}
              className={`${styles.inspectorIconButton} ${locked ? styles.inspectorIconButtonActive : ""}`}
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
                className={`${styles.inspectorIconButton} ${!visible ? styles.inspectorIconButtonActive : ""}`}
                onClick={onVisibilityToggle}
                type="button"
              >
                <InspectorIcon name="eye" size={12} />
              </button>
            ) : null}
          </>
        ) : null}
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

  useLayoutEffect(() => {
    const region = regionRef.current;
    const inner = regionInnerRef.current;

    if (!region || !inner) return;

    const syncHeight = () => {
      region.style.height = open ? `${inner.scrollHeight}px` : "0px";
    };

    syncHeight();
    const observer = new ResizeObserver(syncHeight);
    observer.observe(inner);

    return () => observer.disconnect();
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
  label,
  onChange,
  options,
  value,
}: {
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
        className={`${styles.inspectorControl} ${styles.inspectorSelectControl}`}
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
    const commit = fieldCommit(draft, value);
    setDraft(null);
    if (commit !== null) onCommitValue?.(commit);
  };
  return (
    <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${className ?? ""}`}>
      {leading}
      {prefix ? <span className={styles.fieldPrefix}>{prefix}</span> : null}
      <input
        aria-label={ariaLabel}
        inputMode="text"
        onBlur={selfDrafting ? commitSelf : onCommit ? () => onCommit() : undefined}
        onChange={(event) => {
          if (selfDrafting) setDraft(event.target.value);
          onChange?.(event.target.value);
        }}
        onKeyDown={
          selfDrafting
            ? (event) => {
                if (event.key === "Enter") commitSelf();
              }
            : onCommit
              ? (event) => {
                  if (event.key === "Enter") onCommit();
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

type RadiusCorner = "all" | "bottomLeft" | "bottomRight" | "topLeft" | "topRight";
type RadiusValues = Record<RadiusCorner, string>;

/** W4.2 (ruling R-B1): only a numeric commit writes (`N` → `rounded-[Npx]`) —
 * and under founder ruling F2 that all-corners write also clears the per-corner
 * overrides, which is what the corner fields mirror below. An empty commit
 * clears the all-corners family only; a named scale value the field displays
 * verbatim (`lg`) is no write at all, so nothing is mirrored for it either. */
const NUMERIC_RADIUS = /^\d+$/;

/**
 * RULING A29 (review): what the `all` box reads once one CORNER has moved — the
 * SCENE lane's rule, which is hydrate's own, by name.
 *
 * `scene-hydrate.ts` derives `all` from the four corners: "the uniform value,
 * or empty when the corners differ (no single number is true)". `all` is not a
 * stored field there, so after a single-corner commit the box must re-derive or
 * it states a number the document does not have — and worse, the dirty check
 * then swallows the edit that would put it right. Browser-shaped repro: on a
 * uniformly-5 node, typing 9 into top-left makes the document `{9,5,5,5}`
 * (hydrate: `all` is `""`) while the box still reads 5; the user who types 5
 * into All to restore it is refused as unchanged, and only the scan button
 * still works — applying whatever stale number the box is showing.
 *
 * The WEB lane does NOT share this rule and is deliberately excluded at the one
 * call site: there `all` is its own Tailwind class (`rounded-[Npx]`), parsed
 * independently of the four corner classes (`design-editor/adapter/hydrate.ts:259-266`),
 * and a node legitimately carries `rounded-[8px]` beside a `rounded-tl-[2px]`
 * override. Deriving there would erase a real class from the panel. The two
 * lanes' `all` are different facts, so one rule cannot serve both — the same
 * split A28 made for the mirror.
 */
function uniformRadius(corners: RadiusValues): string {
  const { bottomLeft, bottomRight, topLeft, topRight } = corners;
  return topLeft === topRight &&
    topRight === bottomRight &&
    bottomRight === bottomLeft
    ? topLeft
    : "";
}

/** W4.2 (ruling R-B2): the five radius fields adopt the ratified R3 commit
 * model — typed values draft locally and COMMIT on blur/Enter, so the write
 * path never sees a per-keystroke event. Behavioral only: same DOM, classes,
 * icons and aria-labels as the dummy ships. */
export function RadiusControls({
  locked = false,
  onApplyAll,
  onChange,
  values,
}: {
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
   * RULING A27: the five fields keep BOTH the text being typed and the value
   * each field last COMMITTED — in ONE state object, because the second is what
   * decides whether a blur is a write at all, and a shape that let them drift
   * apart would just relocate the trap below. The `AdCanvasInspector` Custom
   * W/H pair (AD4.0 step 1) is the same shape for the same reason.
   *
   * THE DIRTY CHECK READS `committed`, NEVER THE `values` PROP.
   *
   *   • In the WEB lane the two are identical by construction, verified against
   *     the code: the only writers of `state.radius` are `setNestedValue` and
   *     `setRadiusAll` (`use-inspector-controller.ts:260-336`), and the web
   *     inspector dispatches both exclusively from this component
   *     (`web-inspector.tsx:893`). Each commit below sets `committed` to
   *     exactly what the controller is about to hold — a corner to its typed
   *     value, F2's clearing all-write to `{all, four: ""}` — and a remount
   *     re-seeds both halves from the fresh prop. The check gives the same
   *     answers there as it always did.
   *   • In the SCENE lane they deliberately differ, and that difference is the
   *     whole point. An ad all-corners commit writes all four corners to the
   *     DOCUMENT but dispatches one `radius.all`, so the controller's four
   *     corner entries stay where they were. Comparing against those made every
   *     re-type of a corner's pre-commit number compare EQUAL and commit
   *     nothing, while the box kept the number the user typed — a silent no-op
   *     and a lying field at once. Browser-proven at the A26 review, where it
   *     blocked restoring the seeded document's own corners by hand.
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

  /** Every radius field re-states itself after a commit that moved it — both
   * halves at once (A27's lockstep), which is free in one state object. */
  const restate = (next: RadiusValues) =>
    setRadius({ committed: next, draft: next });

  const commitAll = (value: string) => {
    // A29: a locked node refuses every write (§4), so a commit against one
    // records NOTHING — not the mirror, and not `committed` either. Recording it
    // would leave the boxes stating a document the adapter never wrote, and
    // would swallow the same edit again once the node is unlocked.
    if (locked) {
      return;
    }
    // BOTH lanes: an all-corners write REPLACES what the four corner fields are
    // stating, so both re-state them — but under DIFFERENT conditions, because
    // they are different questions (RULING A28). They were one condition until
    // a fractional radius wrote all four corners while the boxes kept the old
    // numbers.
    if (!onApplyAll) {
      // ── The SCENE lane ────────────────────────────────────────────────────
      // The question is "did this commit produce a WRITE?", which is the
      // adapter's own rule — imported, never restated here, so the mirror and
      // the write can never diverge again. `radiusCommitText` answers with the
      // canonical text of the number the document now holds (`007` → `7`), so
      // the boxes state exactly what a re-hydrate would state.
      onChange("all", value);
      const written = radiusCommitText(value);
      if (written === null) {
        // Nothing was written, so nothing may be re-stated — only this field's
        // own committed text moves, which is what keeps a re-blur quiet.
        setRadius((current) => ({
          ...current,
          committed: { ...current.committed, all: value },
        }));
        return;
      }
      // The scene lane's all-write SETS all four corners (`scene-apply.ts`
      // writes the whole `CornerRadii`), so every one of the five fields now
      // reads that one number.
      restate({
        all: written,
        bottomLeft: written,
        bottomRight: written,
        topLeft: written,
        topRight: written,
      });
      return;
    }
    // ── The WEB lane (F2), untouched ─────────────────────────────────────────
    // Its question is "does this write CLEAR the per-corner overrides?", which
    // is R-B1's integer rule and is not this lane's to move.
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

  const applyAll = () => {
    // The scan button's meaning IS the all-corners write, in BOTH lanes, so it
    // commits the all field's current draft even when unchanged — but an empty
    // draft would clear the radius rather than apply one, so it is a no-op.
    //
    // RULING A26 retired the scene lane's fan-out-to-four here. Those four
    // synchronous `onChange(corner, …)` calls each dispatched their own event,
    // and the write listener's scene is a passive-effect ref over React state
    // (`use-scene-inspector-writes.ts`), so all four read the SAME pre-burst
    // node — while every radius operation writes the whole `CornerRadii`. The
    // fourth clobbered the first three: a scan of 24 over the seeded ad's
    // 32/32/96/32 image landed 32/32/96/24, one corner, four undo steps.
    // `commitAll` already forks correctly, so this needs no branch of its own.
    if (radius.draft.all.trim() === "") return;
    commitAll(radius.draft.all);
  };

  return (
    <>
      <div className={styles.radiusMainRow}>
        <InspectorInput
          ariaLabel="All corner radius"
          className={styles.radiusValue}
          leading={<InspectorIcon name="radius-all" size={16} />}
          onChange={(value) => setDraft("all", value)}
          onCommit={() => {
            if (radius.draft.all !== radius.committed.all) commitAll(radius.draft.all);
          }}
          value={radius.draft.all}
        />
        <button aria-label="Apply radius to all corners" className={styles.scanButton} onClick={applyAll} type="button">
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
          const commit = () => {
            // A29: nothing a locked node refuses may be recorded (see
            // `commitAll`).
            if (locked) return;
            // Read this render's draft and dispatch OUTSIDE the updater — a
            // `onChange` inside one would be a side effect React is free to run
            // twice (the `commitCustomSize` rule, AD4.0 step 1).
            const typed = radius.draft[corner];
            if (typed === radius.committed[corner]) return;
            onChange(corner, typed);
            setRadius((current) => {
              // WEB lane: the raw text, and `all` is its own class and is not
              // derived from the corners, so it keeps what it had (see
              // `uniformRadius`). Unchanged since A27.
              if (onApplyAll) {
                return {
                  ...current,
                  committed: { ...current.committed, [corner]: typed },
                };
              }
              // SCENE lane / RULING A31: store what the WRITE PRODUCED, not what
              // was typed. `uniformRadius` compares these four as STRINGS, so a
              // raw `5.0` (or `007`, or ` 5 `) on a uniformly-5 node wrote a
              // correctly uniform document — `radiusCommit` canonicalizes on the
              // way out — while the derived `all` saw `"5.0" !== "5"` and blanked
              // the box. Canonicalizing here closes that gap and its root cause
              // in one line, because these two now speak the same spelling as
              // hydrate.
              const written = radiusCommitText(typed);
              if (written === null) {
                // REFUSED: the document did not move, so nothing else may. Only
                // this field's own committed text advances — which keeps a
                // re-blur quiet, and must NOT be blanked or A27's trap reopens
                // from the other side. (The box keeps the refused text until
                // reselection: the ratified `commitCustomSize` posture, recorded
                // with the A19 family.) Re-deriving `all` here would have blanked
                // it over a document nothing had written.
                return {
                  ...current,
                  committed: { ...current.committed, [corner]: typed },
                };
              }
              const committed = { ...current.committed, [corner]: written };
              // SCENE lane: `all` IS the four corners, so it re-derives — in
              // both halves, keeping A27's lockstep.
              const all = uniformRadius(committed);
              return {
                committed: { ...committed, all },
                // The box reads what the document GOT, which is the same
                // canonical text `restate` already writes into these four on an
                // all-commit (A28) — one behaviour, not two. On Enter that
                // rewrites the field under the cursor, which is what a numeric
                // field does; on blur the cursor has already left. The
                // alternative leaves the box stating a spelling the document
                // does not have AND re-dispatching a refused write on every
                // re-blur.
                draft: { ...current.draft, [corner]: written, all },
              };
            });
          };
          return (
            <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${styles.cornerRadiusField}`} key={corner}>
              <InspectorIcon name={icon} size={16} />
              <input
                aria-label={`${corner} radius`}
                onBlur={commit}
                onChange={(event) => setDraft(corner, event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commit();
                }}
                value={radius.draft[corner]}
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
  color = "#00F59B",
  fixtureFallback = true,
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
  /** RULING A23: `false` says `options` is the whole truth — with no palette
   * the Theme tab renders NOTHING rather than the dummy's six fixture colours,
   * which on a live write path are a fabrication the user can commit. The ad
   * lane passes it; the web lane keeps the default, so nothing it shows
   * changes (`model/inspector-theme-colors.ts` states why it is a parameter). */
  fixtureFallback?: boolean;
  none?: boolean;
  noneAriaLabel?: string;
  onColorChange?: (color: string) => void;
  onOpacityChange?: (opacity: string) => void;
  /** W3.2 (R2): fired with the token LABEL on a theme-tab pick — the live
   * write path; hex (custom tab) stays visual-only per §3. */
  onTokenChange?: (label: string) => void;
  opacity?: string;
  /** W4.0: the document's real theme tokens for the Theme tab. Omitted (or
   * empty) keeps the dummy's fixture palette — this control's design is
   * unchanged either way, only the data is real. */
  options?: readonly ThemeColorOption[];
  showOpacity?: boolean;
}) {
  const themeColors = resolveInspectorThemeColors(options, fixtureFallback);
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

  const commitColor = (nextColor: string) => {
    const upper = previewColor(nextColor);
    if (upper !== null) {
      onColorChange?.(upper);
    }
  };

  const commitCustomColor = (nextColor: HsvColor) => {
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
    <span className={styles.colorControl} ref={colorControlRef}>
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
            onChange={(event) => onOpacityChange?.(event.target.value)}
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
  fill,
  fixtureFallback = true,
  onFillChange,
  onSolidColorChange,
  onTokenChange,
  options,
  solidColor,
}: {
  fill: InspectorBackgroundFill;
  /** RULING A23, forwarded to both nested pickers with `options` — this
   * section's swatches must not offer a fixture palette either. */
  fixtureFallback?: boolean;
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
    onFillChange({
      ...fill,
      stops: fill.stops.map((stop, stopIndex) => stopIndex === index ? { ...stop, ...update } : stop),
    });
  };

  const addStop = () => {
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
        label="Background fill type"
        onChange={(label) => onFillChange({ ...fill, type: BACKGROUND_FILL_TYPES[label as keyof typeof BACKGROUND_FILL_TYPES] })}
        options={BACKGROUND_FILL_LABELS}
        value={BACKGROUND_FILL_TYPE_LABELS[fill.type]}
      />

      {fill.type === "solid" ? (
        <ColorControl
          color={solidColor}
          fixtureFallback={fixtureFallback}
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
              <InspectorInput
                ariaLabel="Gradient angle"
                onChange={(value) => setDraft({ field: "angle", value })}
                onCommit={() =>
                  commitDraft("angle", 360, (angle) => onFillChange({ ...fill, angle }))
                }
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
                  fixtureFallback={fixtureFallback}
                  onColorChange={(color) => updateStop(index, { color })}
                  options={options}
                  showOpacity={false}
                />
                <InspectorInput
                  ariaLabel={`Gradient stop ${index + 1} position`}
                  className={styles.backgroundGradientPosition}
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
                  disabled={fill.stops.length <= 2}
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
            disabled={fill.stops.length >= 6}
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
  onFileSelect,
  src,
}: {
  /** AD4.A step 2: a handler may REPORT that the document did not take the
   * file, by returning a promise that rejects — the preview then goes back to
   * what the panel was showing. A `void` handler (the dummy fixture path, and
   * the website lane's own, which swallows its failures into the inspector's
   * error slot) behaves exactly as it always has. */
  onFileSelect?: (file: File) => void | Promise<void>;
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

  return (
    <>
      <button
        aria-label="Replace image"
        className={styles.imageReplaceField}
        onClick={() => inputRef.current?.click()}
        type="button"
      >
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
        <span>Replace image</span>
      </button>
      <input
        accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
        className={styles.visuallyHiddenInput}
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
          <span>{label}</span>
        </span>
        {trailing ? <InspectorIcon name="layer-ellipsis" size={16} /> : null}
      </span>
    </button>
  );
}
