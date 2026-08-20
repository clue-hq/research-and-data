"use client";

import Image from "next/image";
import { Popover } from "@base-ui/react/popover";
import { Select } from "@base-ui/react/select";
import { MinusIcon, PlusIcon } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";
import type { InspectorBackgroundFill, InspectorFillType } from "../hooks/use-inspector-controller";
import {
  INSPECTOR_THEME_COLORS,
  resolveInspectorThemeColors,
} from "../model/inspector-theme-colors";
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
            <button
              aria-label={visible ? "Hide element" : "Show element"}
              aria-pressed={!visible}
              className={`${styles.inspectorIconButton} ${!visible ? styles.inspectorIconButtonActive : ""}`}
              onClick={onVisibilityToggle}
              type="button"
            >
              <InspectorIcon name="eye" size={12} />
            </button>
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
  prefix,
  readOnly = false,
  suffix,
  value,
}: {
  ariaLabel: string;
  className?: string;
  leading?: ReactNode;
  onChange: (value: string) => void;
  /** W4.2 (the ratified R3 commit model): when supplied, the caller drafts the
   * typed value locally and this fires on blur/Enter — the one moment a typed
   * field becomes a write. Omitted leaves the field exactly as it shipped
   * (per-keystroke `onChange` only); either way the DOM is unchanged. */
  onCommit?: () => void;
  prefix?: string;
  readOnly?: boolean;
  suffix?: string;
  value: string;
}) {
  return (
    <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${className ?? ""}`}>
      {leading}
      {prefix ? <span className={styles.fieldPrefix}>{prefix}</span> : null}
      <input
        aria-label={ariaLabel}
        inputMode="text"
        onBlur={onCommit ? () => onCommit() : undefined}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={
          onCommit
            ? (event) => {
                if (event.key === "Enter") onCommit();
              }
            : undefined
        }
        readOnly={readOnly}
        value={value}
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

/** W4.2 (ruling R-B2): the five radius fields adopt the ratified R3 commit
 * model — typed values draft locally and COMMIT on blur/Enter, so the write
 * path never sees a per-keystroke event. Behavioral only: same DOM, classes,
 * icons and aria-labels as the dummy ships. */
export function RadiusControls({
  onApplyAll,
  onChange,
  values,
}: {
  /** W4.2/F2 (the web image schema): the all-corners commit — ONE `radius.all`
   * change, `clearsCorners` true when that write also clears the four corner
   * overrides. Absent (the scene/ad image inspector, whose radius is dummy
   * state and carries no F2 ruling) keeps the dummy's fan-out-to-four
   * behaviour for the scan button. */
  onApplyAll?: (value: string, clearsCorners: boolean) => void;
  onChange: (corner: RadiusCorner, value: string) => void;
  values: RadiusValues;
}) {
  const [drafts, setDrafts] = useState<RadiusValues>(values);
  const setDraft = (corner: RadiusCorner, value: string) =>
    setDrafts((current) => ({ ...current, [corner]: value }));

  const commitAll = (value: string) => {
    if (!onApplyAll) {
      onChange("all", value);
      return;
    }
    const clearsCorners = NUMERIC_RADIUS.test(value.trim());
    onApplyAll(value, clearsCorners);
    if (clearsCorners) {
      setDrafts((current) => ({
        ...current,
        bottomLeft: "",
        bottomRight: "",
        topLeft: "",
        topRight: "",
      }));
    }
  };

  const applyAll = () => {
    if (!onApplyAll) {
      // The dummy's own meaning, kept for the scene inspector.
      (["topLeft", "topRight", "bottomLeft", "bottomRight"] as const).forEach((corner) =>
        onChange(corner, values.all),
      );
      return;
    }
    // F2: the scan button's meaning IS the all-corners write, so it commits
    // the all field's current draft even when unchanged — but an empty draft
    // would clear the radius rather than apply one, so it is a no-op.
    if (drafts.all.trim() === "") return;
    commitAll(drafts.all);
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
            if (drafts.all !== values.all) commitAll(drafts.all);
          }}
          value={drafts.all}
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
            if (drafts[corner] !== values[corner]) onChange(corner, drafts[corner]);
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
                value={drafts[corner]}
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
  const themeColors = resolveInspectorThemeColors(options);
  const [draftColor, setDraftColor] = useState(color.toUpperCase());
  const [pickerMode, setPickerMode] = useState<"custom" | "theme">("theme");
  const [customColor, setCustomColor] = useState<HsvColor>(() => hexToHsv(color));
  const colorControlRef = useRef<HTMLSpanElement>(null);

  const commitColor = (nextColor: string) => {
    const normalized = nextColor.startsWith("#") ? nextColor : `#${nextColor}`;
    if (/^#[0-9A-F]{6}$/i.test(normalized)) {
      const upper = normalized.toUpperCase();
      setDraftColor(upper);
      setCustomColor(hexToHsv(upper));
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
                          commitColor(option.value);
                          // W3.2 (R2): a theme-tab pick also reports the
                          // TOKEN label — the live write path; the hex
                          // continues to drive the visual state only.
                          onTokenChange?.(option.label);
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
                  {/* The hex footer's recent-colors strip belongs to the §3-inert
                      custom path (it commits a hex, never a token) and keeps the
                      dummy's fixture swatches. */}
                  {INSPECTOR_THEME_COLORS.slice(0, 4).map((option) => (
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
  onFillChange,
  onSolidColorChange,
  solidColor,
}: {
  fill: InspectorBackgroundFill;
  onFillChange: (fill: InspectorBackgroundFill) => void;
  onSolidColorChange: (color: string) => void;
  solidColor: string;
}) {
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
        <ColorControl color={solidColor} onColorChange={onSolidColorChange} />
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
                onChange={(value) => onFillChange({ ...fill, angle: clamp(Number(value) || 0, 0, 360) })}
                suffix="°"
                value={String(fill.angle)}
              />
            </label>
          ) : null}

          <div className={styles.backgroundGradientStops}>
            {fill.stops.map((stop, index) => (
              <div className={styles.backgroundGradientStop} key={`${index}-${stop.color}`}>
                <ColorControl
                  color={stop.color}
                  onColorChange={(color) => updateStop(index, { color })}
                  showOpacity={false}
                />
                <InspectorInput
                  ariaLabel={`Gradient stop ${index + 1} position`}
                  className={styles.backgroundGradientPosition}
                  onChange={(value) => updateStop(index, { position: clamp(Number(value) || 0, 0, 100) })}
                  suffix="%"
                  value={String(stop.position)}
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
  onFileSelect?: (file: File) => void;
  src: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [previewSrc, setPreviewSrc] = useState(src);

  const selectFile = (file: File) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") setPreviewSrc(reader.result);
    });
    reader.readAsDataURL(file);
    onFileSelect?.(file);
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
  onClick?: () => void;
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
