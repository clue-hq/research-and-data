// The kit a section written by the agent (E5) builds with: the same Shell, Button and Eyebrow our
// own sections use, so a new section takes the brand's surfaces, text colours and button exactly
// as they do. Image takes only files from the brand's assets (the validator checks the path).
import type { ReactNode } from "react";
import { Button as BrandButton, Eyebrow, Shell, type Href, type Surface } from "./sections";

export type Kit = {
  Shell: (props: { surface: Surface; children: ReactNode }) => ReactNode;
  Button: (props: { label: string; href: string; surface: Surface }) => ReactNode;
  Eyebrow: (props: { children: ReactNode }) => ReactNode;
  Image: (props: { src: string; alt?: string; className?: never }) => ReactNode;
};

export type AgentSectionModule = {
  schema: { safeParse: (value: unknown) => { success: boolean } };
  render: (props: never, kit: Kit) => ReactNode;
};

export function makeKit(href: Href): Kit {
  return {
    Shell,
    Button: ({ label, href: target, surface }) => <BrandButton label={label} href={href(target)} surface={surface} />,
    Eyebrow,
    // eslint-disable-next-line @next/next/no-img-element
    Image: ({ src, alt }) => (src ? <img src={src} alt={alt ?? ""} className="w-full rounded-card object-cover" /> : null),
  };
}
