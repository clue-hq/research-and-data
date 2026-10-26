import { Suspense } from "react";
import { WorkspaceScreen } from "@/features/orchestration/components/workspace-screen";
export default function AnalyticsPage() { return <Suspense><WorkspaceScreen view="results" /></Suspense>; }
