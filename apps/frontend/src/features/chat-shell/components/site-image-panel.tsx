"use client";

import { useState, type ReactNode } from "react";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { getAtPath } from "@clue/site-kit/editor-site";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { InspectorField, InspectorInput, InspectorSection, SegmentedControl } from "./inspector-primitives";
import { SiteArrangeSection, SiteHideSection } from "./site-arrange-section";
import { SiteBoxPanel } from "./site-box-panel";
import { FIT_SAME_NOTE, imageFitPatch, imagePanelValues, type ImageFit } from "./site-image-panel.logic";
import styles from "./chat-shell.module.css";

const FIT_OPTIONS: { label: string; value: ImageFit }[] = [
  { label: "Fill", value: "fill" },
  { label: "Fit", value: "fit" },
];

function Note({ children }: { children: ReactNode }) {
  return (
    <p className={styles.inspectorStatusNote} role="status">
      {children}
    </p>
  );
}

/**
 * The site element inspector's image panel (plan 5, spec §2 mockup 3): Image (the picture and Replace,
 * through the dock's own image field: Upload, Library, Generate, Edit), Fit (Fill · Fit), Alt text,
 * Stroke (the box panel's), then Arrange and Visibility (plan 4). Every change is one save; a control
 * the image cannot take shows disabled with its note. While the agent-run lock holds, everything is
 * disabled.
 */
export function SiteImagePanel({
  binding,
  renderImageField,
}: {
  binding: SiteInspectorBinding;
  renderImageField?: (field: FieldDescription, path: string, value: string) => ReactNode;
}) {
  const element = binding.element!;
  const image = element.image;
  const [imageOpen, setImageOpen] = useState(true);
  const [fitOpen, setFitOpen] = useState(true);
  const [altOpen, setAltOpen] = useState(true);
  const [altNote, setAltNote] = useState<string | null>(null);
  if (!image) return null;
  const fit = imagePanelValues(binding.elementOverride, image);
  const replace = binding.imageReplace;
  // The file as stored where Replace writes it; a copied slot never set shows the picture as drawn.
  const stored = replace && binding.values ? getAtPath(binding.values, replace.prop) : undefined;
  const current = typeof stored === "string" && stored ? stored : image.src;
  const imageNote = element.imageSource?.kind === "fixed" ? element.imageSource.reason : null;
  const altSourceNote = element.altSource?.kind === "fixed" ? element.altSource.reason : null;
  const commitFit = (value: ImageFit) => {
    if (binding.disabled) return;
    const next = imageFitPatch(binding.elementOverride, value, image);
    if (next && JSON.stringify(next) !== JSON.stringify(binding.elementOverride ?? {})) binding.onStyleCommit(element.key, next);
  };
  const commitAlt = (text: string) => setAltNote(binding.onImageAltCommit(text));
  return (
    <>
      <InspectorSection label="Image" onOpenChange={setImageOpen} open={imageOpen}>
        {replace && renderImageField ? (
          renderImageField({ kind: "image", label: "Image", name: replace.prop }, replace.prop, current)
        ) : (
          <Note>{imageNote ?? "This image cannot be replaced here."}</Note>
        )}
        {replace && replace.uses > 1 ? <Note>{`This picture appears ${replace.uses} times on this section; replacing it changes all of them.`}</Note> : null}
      </InspectorSection>
      {image.media === "svg" ? null : (
        <InspectorSection label="Fit" onOpenChange={setFitOpen} open={fitOpen}>
          <SegmentedControl
            ariaLabel="Image fit"
            disabled={binding.disabled || !fit.fitLive}
            onChange={commitFit}
            options={FIT_OPTIONS}
            value={fit.fit ?? ("" as ImageFit)}
          />
          {fit.fitLive ? null : <Note>{FIT_SAME_NOTE}</Note>}
        </InspectorSection>
      )}
      <InspectorSection label="Alt text" onOpenChange={setAltOpen} open={altOpen}>
        {binding.imageAlt === null ? (
          <Note>{altSourceNote ?? "This image's alt text cannot be changed here."}</Note>
        ) : (
          <>
            <InspectorField label="Describe the image">
              <InspectorInput ariaLabel="Alt text" disabled={binding.disabled} onCommitValue={commitAlt} value={binding.imageAlt} />
            </InspectorField>
            {altNote ? <Note>{altNote}</Note> : null}
          </>
        )}
      </InspectorSection>
      {image.media === "svg" ? null : <SiteBoxPanel binding={binding} mode="image" />}
      <SiteArrangeSection binding={binding} />
      <SiteHideSection binding={binding} />
    </>
  );
}
