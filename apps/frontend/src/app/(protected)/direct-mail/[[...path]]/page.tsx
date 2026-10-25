import { Suspense } from "react";
import { DirectMailScreen } from "@/features/direct-mail/components/direct-mail-screen";

export default async function DirectMailPage({ params }: { params: Promise<{ path?: string[] }> }) {
  const { path } = await params;
  return <Suspense><DirectMailScreen recordId={path?.join("/")} /></Suspense>;
}
