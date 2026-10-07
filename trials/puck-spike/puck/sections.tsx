// Our own sections. Every style choice is a brand-token choice (surface, heading role, button
// variant); there are no free colours or pixel values, so a page stays on brand however it is
// edited. Text fields are `contentEditable`, so they edit in place on the canvas.
import type { ComponentConfig } from "@puckeditor/core";
import type { ReactNode } from "react";
import type { BrandData } from "@/lib/brands";
import { HEADING_ROLES, SURFACES, SURFACE_LABELS } from "./schemas";

export type Surface = "page" | "card" | "muted" | "brandSubtle" | "brand" | "inverse";
export type HeadingRole = "display" | "headline" | "title";
type Text = string | ReactNode;

export const SURFACE_CLASS: Record<Surface, string> = {
  page: "bg-surface-page text-on-surface-page",
  card: "bg-surface-card text-on-surface-card",
  muted: "bg-surface-muted text-on-surface-muted",
  brandSubtle: "bg-surface-brand-subtle text-on-surface-brand-subtle",
  brand: "bg-surface-brand text-on-surface-brand",
  inverse: "bg-surface-inverse text-on-surface-inverse",
};

const HEADING_CLASS: Record<HeadingRole, string> = {
  display: "font-display text-display",
  headline: "font-headline text-headline",
  title: "font-title text-title",
};

const surfaceField = {
  type: "select" as const,
  label: "Surface",
  options: SURFACES.map((value) => ({ label: SURFACE_LABELS[value], value })),
};
const headingRoleField = {
  type: "select" as const,
  label: "Heading size",
  options: HEADING_ROLES.map((value) => ({ label: value[0].toUpperCase() + value.slice(1), value })),
};
const text = (label: string) => ({ type: "text" as const, label, contentEditable: true });
const area = (label: string) => ({ type: "textarea" as const, label, contentEditable: true });

const Shell = ({ surface, children }: { surface: Surface; children: ReactNode }) => (
  <section className={SURFACE_CLASS[surface]}>
    <div className="mx-auto max-w-[75rem] px-6 py-16 md:px-10 md:py-24">{children}</div>
  </section>
);

const Eyebrow = ({ children }: { children: Text }) =>
  children ? <p className="font-eyebrow text-eyebrow uppercase opacity-80">{children}</p> : null;

export function Button({ label, href, surface }: { label: Text; href: string; surface: Surface }) {
  if (!label) return null;
  return (
    <a href={href || "#"} className="brand-btn" data-surface={surface}>
      {label}
      <span aria-hidden>→</span>
    </a>
  );
}

export type Href = (value: string) => string;

export function makeSections(
  brand: BrandData,
  href: Href,
  AssetPicker?: (props: { assets: BrandData["assets"]; value: string; onChange: (v: string) => void }) => ReactNode,
) {
  const imageField = {
    type: "custom" as const,
    label: "Image (brand assets)",
    render: ({ value, onChange }: { value: string; onChange: (v: string) => void }) =>
      AssetPicker ? <AssetPicker assets={brand.assets} value={value} onChange={onChange} /> : <span />,
  };

  const StatsBand: ComponentConfig<{
    surface: Surface; align: "left" | "center"; eyebrow: Text; heading: Text; intro: Text;
    stats: { value: string; label: string }[]; source: Text;
  }> = {
    label: "Stats band",
    fields: {
      surface: surfaceField,
      align: { type: "radio", label: "Alignment", options: [{ label: "Left", value: "left" }, { label: "Centre", value: "center" }] },
      eyebrow: text("Eyebrow"), heading: text("Heading"), intro: area("Intro"),
      stats: {
        type: "array", label: "Stats", max: 4,
        arrayFields: { value: { type: "text" }, label: { type: "textarea" } },
        getItemSummary: (item: { value?: string }) => item.value || "Stat",
      },
      source: text("Source line"),
    } as never,
    defaultProps: {
      surface: "brandSubtle", align: "left", eyebrow: "", heading: "A headline about the result", intro: "",
      stats: [{ value: "7.4%", label: "What the number means" }], source: "",
    },
    render: ({ surface, align, eyebrow, heading, intro, stats, source }) => {
      const centered = align === "center";
      const columns = ["", "sm:grid-cols-1", "sm:grid-cols-2", "sm:grid-cols-3", "sm:grid-cols-2 lg:grid-cols-4"][stats.length] ?? "sm:grid-cols-3";
      return (
        <Shell surface={surface}>
          <div className={centered ? "mx-auto text-center [&>*]:mx-auto" : ""}>
            <Eyebrow>{eyebrow}</Eyebrow>
            <h2 className="brand-heading mt-3 max-w-[24ch] font-title text-title">{heading}</h2>
            {intro ? <p className="mt-5 max-w-[60ch] font-body text-body opacity-85">{intro}</p> : null}
          </div>
          <dl className={`mt-12 grid gap-8 ${columns} ${centered ? "text-center [&_dd]:mx-auto" : ""}`}>
            {stats.map((stat, index) => (
              <div key={index} className="border-t border-current/20 pt-6">
                <dt className="brand-heading font-headline text-headline">{stat.value}</dt>
                <dd className="mt-3 max-w-[32ch] font-body text-body opacity-85">{stat.label}</dd>
              </div>
            ))}
          </dl>
          {source ? <p className={`mt-10 font-caption text-caption opacity-70 ${centered ? "text-center" : ""}`}>{source}</p> : null}
        </Shell>
      );
    },
  };

  const FeatureSplit: ComponentConfig<{
    surface: Surface; eyebrow: Text; heading: Text; headingRole: HeadingRole; body: Text;
    image: string; imageSide: "left" | "right"; buttonLabel: Text; buttonHref: string;
  }> = {
    label: "Feature split",
    fields: {
      surface: surfaceField, eyebrow: text("Eyebrow"), heading: text("Heading"),
      headingRole: headingRoleField, body: area("Body"), image: imageField,
      imageSide: { type: "radio", label: "Image side", options: [{ label: "Left", value: "left" }, { label: "Right", value: "right" }] },
      buttonLabel: text("Button label"), buttonHref: { type: "text", label: "Button link" },
    } as never,
    defaultProps: {
      surface: "page", eyebrow: "", heading: "What this does for them", headingRole: "title",
      body: "One or two plain sentences.", image: "", imageSide: "left", buttonLabel: "", buttonHref: "",
    },
    render: ({ surface, eyebrow, heading, headingRole, body, image, imageSide, buttonLabel, buttonHref }) => (
      <Shell surface={surface}>
        <div className="grid items-center gap-10 md:grid-cols-2 md:gap-16">
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image} alt="" className={`w-full rounded-card object-cover ${imageSide === "right" ? "md:order-2" : ""}`} />
          ) : (
            <div className={`aspect-[4/3] w-full rounded-card bg-surface-muted ${imageSide === "right" ? "md:order-2" : ""}`} />
          )}
          <div>
            <Eyebrow>{eyebrow}</Eyebrow>
            <h2 className={`brand-heading mt-3 ${HEADING_CLASS[headingRole]}`}>{heading}</h2>
            <p className="mt-5 max-w-[52ch] font-body text-body opacity-85">{body}</p>
            <div className="mt-8"><Button label={buttonLabel} href={href(buttonHref)} surface={surface} /></div>
          </div>
        </div>
      </Shell>
    ),
  };

  const ProofCard: ComponentConfig<{
    surface: Surface; kicker: Text; metric: Text; metricLabel: Text; heading: Text; body: Text;
    source: Text; linkLabel: Text; linkHref: string;
  }> = {
    label: "Proof card",
    fields: {
      surface: surfaceField, kicker: text("Kicker (whose result)"), metric: text("Metric"),
      metricLabel: text("Metric label"), heading: text("Heading"), body: area("Body"),
      source: text("Source line"), linkLabel: text("Link label"), linkHref: { type: "text", label: "Link" },
    } as never,
    defaultProps: {
      surface: "card", kicker: "Customer or study", metric: "13%", metricLabel: "what changed",
      heading: "What they did", body: "", source: "", linkLabel: "", linkHref: "",
    },
    render: ({ surface, kicker, metric, metricLabel, heading, body, source, linkLabel, linkHref }) => (
      <Shell surface="page">
        <div className={`grid gap-10 rounded-card p-8 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:p-14 ${SURFACE_CLASS[surface]}`}>
          <div>
            <Eyebrow>{kicker}</Eyebrow>
            <p className="brand-heading mt-4 font-display text-display">{metric}</p>
            <p className="mt-2 font-body text-body opacity-85">{metricLabel}</p>
          </div>
          <div className="self-end">
            <h3 className="brand-heading font-title text-title">{heading}</h3>
            {body ? <p className="mt-5 font-body text-body opacity-85">{body}</p> : null}
            {source ? <p className="mt-6 font-caption text-caption opacity-70">{source}</p> : null}
            {linkLabel ? (
              <a href={href(linkHref) || "#"} className="mt-6 inline-block font-cta text-cta underline underline-offset-4">{linkLabel}</a>
            ) : null}
          </div>
        </div>
      </Shell>
    ),
  };

  const CtaBand: ComponentConfig<{
    surface: Surface; heading: Text; body: Text; buttonLabel: Text; buttonHref: string;
  }> = {
    label: "Call to action band",
    fields: {
      surface: surfaceField, heading: text("Heading"), body: area("Body"),
      buttonLabel: text("Button label"), buttonHref: { type: "text", label: "Button link" },
    } as never,
    defaultProps: { surface: "brand", heading: "The one next step", body: "", buttonLabel: "Get started", buttonHref: "" },
    render: ({ surface, heading, body, buttonLabel, buttonHref }) => (
      <Shell surface={surface}>
        <div className="mx-auto max-w-[44rem] text-center">
          <h2 className="brand-heading font-headline text-headline">{heading}</h2>
          {body ? <p className="mt-5 font-body text-body opacity-85">{body}</p> : null}
          <div className="mt-8"><Button label={buttonLabel} href={href(buttonHref)} surface={surface} /></div>
        </div>
      </Shell>
    ),
  };

  return { StatsBand, FeatureSplit, ProofCard, CtaBand };
}
