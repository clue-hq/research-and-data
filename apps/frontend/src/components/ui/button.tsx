import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// ARV2 D4 (accounts re-lift): the design build's `transparent` variant and `md`
// size, copied verbatim from that build's Button so the lifted account screens
// keep their designed presentation. They are ADDITIVE — every pre-existing
// variant and size below is untouched, so the frozen onboarding screens and the
// AI-elements buttons render exactly as before. Porting the design build's whole
// Button (which also re-points `default`/`outline`/`ghost`/`destructive`/`lg` at
// these tokens) is a separate, app-wide decision.
const transparentVariant = [
  "border-transparent bg-transparent",
  "[color:var(--clue-ds-color-content-neutral)]",
  "hover:[background-color:var(--clue-ds-color-components-button-bg-neutral-hover)]",
  "active:[background-color:var(--clue-ds-color-components-button-bg-neutral-pressed)]",
  "focus-visible:[background-color:var(--clue-ds-color-bg-neutral)]",
  "focus-visible:[box-shadow:var(--clue-ds-product-component-button-effect-focus-transparent)]",
  "disabled:bg-transparent",
  "disabled:[color:var(--clue-ds-color-content-disabled)]",
  "disabled:shadow-none",
].join(" ")

// Settings design lift: additive so existing button variants keep their appearance.
const primaryVariant = [
  "[background-color:var(--clue-ds-color-components-button-bg-brand-default)]",
  "[border-color:var(--clue-ds-color-components-button-border-brand-default)]",
  "[color:var(--clue-ds-color-content-knockout)]",
  "[box-shadow:var(--clue-ds-product-component-button-effect-resting-primary)]",
  "hover:[background-color:var(--clue-ds-color-components-button-bg-brand-hover)]",
  "active:[background-color:var(--clue-ds-color-components-button-bg-brand-pressed)]",
  "active:shadow-none",
  "focus-visible:[background-color:var(--clue-ds-color-components-button-bg-brand-default)]",
  "focus-visible:[box-shadow:var(--clue-ds-product-component-button-effect-focus-primary)]",
  "disabled:border-transparent",
  "disabled:[background-color:var(--clue-ds-color-components-button-bg-brand-disabled)]",
  "disabled:[color:var(--clue-ds-color-content-disabled)]",
  "disabled:shadow-none",
].join(" ")

// Settings → Integrations lift (Figma "Action / …" button-sm/secondary): additive, like the two
// above, so every existing variant keeps its appearance.
const neutralVariant = [
  "border-[0.5px]",
  "[background-color:var(--clue-ds-color-components-button-bg-neutral-default)]",
  "[border-color:var(--clue-ds-color-components-button-border-neutral-default)]",
  "[color:var(--clue-ds-color-content-neutral)]",
  "[box-shadow:0_1px_0_rgb(0_0_0/5%),inset_0_1.5px_0_rgb(255_255_255)]",
  "hover:[background-color:var(--clue-ds-color-components-button-bg-neutral-hover)]",
  "active:[background-color:var(--clue-ds-color-components-button-bg-neutral-pressed)]",
  "active:shadow-none",
  "disabled:[color:var(--clue-ds-color-content-disabled)]",
  "disabled:shadow-none",
].join(" ")

// Settings → Integrations' destructive confirm (Figma "Action / Disconnect", button-sm/critical):
// additive, like `neutral`.
const criticalVariant = [
  "border-[0.5px]",
  "[background-color:var(--clue-ds-color-components-button-bg-critical-default)]",
  "[border-color:var(--clue-ds-color-components-button-border-critical-default)]",
  "[color:var(--clue-ds-color-content-utility-critical)]",
  "[box-shadow:0_1px_0_rgb(0_0_0/5%),inset_0_1.5px_0_rgb(255_255_255)]",
  "hover:[background-color:var(--clue-ds-color-components-button-bg-critical-hover)]",
  "active:[background-color:var(--clue-ds-color-components-button-bg-critical-pressed)]",
  "active:shadow-none",
  "disabled:[background-color:var(--clue-ds-color-components-button-bg-critical-disabled)]",
  "disabled:[color:var(--clue-ds-color-content-disabled)]",
  "disabled:shadow-none",
].join(" ")

// The design's small button (26px; its label sits in a 2px container, hence the +2px).
const designSmSize = [
  "h-[var(--clue-ds-product-component-button-sm-height)]",
  "gap-[var(--clue-ds-product-component-button-gap)]",
  "rounded-[var(--clue-ds-product-component-button-sm-radius)]",
  "px-[calc(var(--clue-ds-product-component-button-sm-padding-inline)+2px)]",
  "py-[var(--clue-ds-product-component-button-sm-padding-block)]",
  "[font-family:var(--clue-ds-typography-text-sm-medium-font-family)]",
  "[font-size:var(--clue-ds-typography-text-sm-medium-font-size)]",
  "[font-weight:var(--clue-ds-typography-text-sm-medium-font-weight)]",
  "[line-height:var(--clue-ds-typography-text-sm-medium-line-height)]",
  "[&_svg:not([class*='size-'])]:size-[var(--clue-ds-product-component-button-sm-icon-size)]",
].join(" ")

const mdSize = [
  "h-[var(--clue-ds-product-component-button-md-height)]",
  "gap-[var(--clue-ds-product-component-button-gap)]",
  "rounded-[var(--clue-ds-product-component-button-md-radius)]",
  "px-[var(--clue-ds-product-component-button-md-padding-inline)]",
  "py-[var(--clue-ds-product-component-button-md-padding-block)]",
  "[font-family:var(--clue-ds-typography-text-default-medium-font-family)]",
  "[font-size:var(--clue-ds-typography-text-default-medium-font-size)]",
  "[font-weight:var(--clue-ds-typography-text-default-medium-font-weight)]",
  "[line-height:var(--clue-ds-typography-text-default-medium-line-height)]",
  "[&_svg:not([class*='size-'])]:size-[var(--clue-ds-product-component-button-md-icon-size)]",
].join(" ")

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/80",
        outline:
          "border-border bg-background hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)] aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost:
          "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:hover:bg-muted/50",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40",
        link: "text-primary underline-offset-4 hover:underline",
        transparent: transparentVariant,
        primary: primaryVariant,
        neutral: neutralVariant,
        critical: criticalVariant,
      },
      size: {
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
        md: mdSize,
        "design-sm": designSmSize,
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
