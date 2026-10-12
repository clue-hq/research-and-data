import { Component, type ReactNode } from "react";
import type { Config, Fields } from "@puckeditor/core";
import { makeConfig, type BrandData, type ShellData } from "@clue/site-kit";
import { AssetPicker, CloneEditor } from "@clue/site-kit/editor";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import type { SiteShell } from "@clue/site-kit/site-document";
import { describeFields, puckFieldsFromJsonSchema } from "./fields";
import type { LoadedSection } from "./sections";

type RenderFn = (props: Record<string, unknown>) => ReactNode;
type MutableConfig = Config & { components: Record<string, { fields?: Fields; render?: RenderFn }> };

/** A broken agent section — one that throws while rendering, for example because the editor's
 * policy refused something it tried — is left out on its own. It never takes the rest of the page,
 * or the editor, down with it (an uncaught render error unmounts a whole React root). */
class SectionBoundary extends Component<{ children: ReactNode; name: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    return this.state.failed ? <div data-agent-section-failed={this.props.name} /> : this.props.children;
  }
}

/** Calls the section's render INSIDE the boundary (a render function called outside it would throw
 * past it). */
function GuardedRender({ props, render }: { props: Record<string, unknown>; render: RenderFn }) {
  return <>{render(props)}</>;
}

/** The page config: site-kit's sections, the seller's clones, the shell drawn around every page,
 * and this site's agent sections with fields from their own props schema, each behind its own
 * error boundary. No basePath: internal links stay "/analysis", and the editor intercepts them and
 * switches pages itself. */
export function buildPageConfig(brand: BrandData, shell: SiteShell | null, sections: readonly LoadedSection[]): Config {
  const config = makeConfig(brand, {
    agentSections: Object.fromEntries(sections.map((section) => [section.name, section.module])),
    editor: { AssetPicker, CloneEditor },
    mode: "page",
    shell: (shell ?? undefined) as ShellData | undefined,
  }) as MutableConfig;
  for (const section of sections) {
    const component = config.components[section.name];
    if (!component) continue;
    component.fields = puckFieldsFromJsonSchema(section.propsSchema);
    const render = component.render;
    if (render) {
      component.render = (props) => (
        <SectionBoundary name={section.name}>
          <GuardedRender props={props} render={render} />
        </SectionBoundary>
      );
    }
  }
  return config;
}

/** The header's and footer's fields, from site-kit's shell config. */
export function shellFieldDescriptions(brand: BrandData): { footer: FieldDescription[]; header: FieldDescription[] } {
  const config = makeConfig(brand, { mode: "shell" }) as MutableConfig;
  return {
    footer: describeFields(config.components.SiteFooter?.fields ?? {}),
    header: describeFields(config.components.SiteHeader?.fields ?? {}),
  };
}
