import type { Metadata } from "next";
import { BrandContextScreen } from "@/features/brand-context/components/brand-context-screen";
import { getBrandContextWorkspace } from "@/features/brand-context/data/brand-context.repository";
import {
  BrandAssetViewSchema,
  BrandColorModeSchema,
  BrandContextSectionSchema,
  BrandDocumentModeSchema,
} from "@/features/brand-context/model/brand-context";

export const metadata: Metadata = {
  title: "Brand context",
};

interface BrandContextPageProps {
  searchParams: Promise<{
    asset?: string;
    file?: string;
    mode?: string;
    section?: string;
    theme?: string;
    view?: string;
  }>;
}

export default async function BrandContextPage({ searchParams }: BrandContextPageProps) {
  const [workspace, query] = await Promise.all([
    getBrandContextWorkspace(),
    searchParams,
  ]);

  const section = BrandContextSectionSchema.safeParse(query.section);
  const assetView = BrandAssetViewSchema.safeParse(query.view);
  const colorMode = BrandColorModeSchema.safeParse(query.theme);
  const documentMode = BrandDocumentModeSchema.safeParse(query.mode);

  return (
    <BrandContextScreen
      initial={{
        assetId: query.asset,
        assetView: assetView.success ? assetView.data : "grid",
        colorMode: colorMode.success ? colorMode.data : "light",
        documentMode: documentMode.success ? documentMode.data : "preview",
        filePath: query.file,
        section: section.success ? section.data : "colors",
      }}
      workspace={workspace}
    />
  );
}
