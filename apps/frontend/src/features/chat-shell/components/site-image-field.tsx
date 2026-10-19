"use client";

import type { SiteImageFieldBinding } from "@/features/site-editor/hooks/use-site-images";
import { AdImageAiRows } from "./image-inspector";
import { InspectorField, InspectorImageUpload } from "./inspector-primitives";

/**
 * DESIGN REVIEW (DR7): a site image field — the designed "Replace image" pill with its Upload /
 * Library menu, then the ad inspector's designed generate rows, unchanged. Both are disabled while
 * the agent-run lock holds (G-H: every control here is an operation or a spend).
 */
export function SiteImageField({
  binding,
  disabled,
  label,
}: {
  binding: SiteImageFieldBinding;
  disabled: boolean;
  label: string;
}) {
  return (
    <>
      <InspectorField label={label}>
        <InspectorImageUpload
          disabled={disabled}
          onFileSelect={binding.onFileSelect}
          onOpenLibrary={binding.onOpenLibrary}
          src={binding.previewSrc}
        />
      </InspectorField>
      <AdImageAiRows disabled={disabled} imageAi={binding.ai} />
    </>
  );
}
