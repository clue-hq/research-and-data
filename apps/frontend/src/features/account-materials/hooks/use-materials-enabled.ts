"use client";
import { useWorkspaceRepository } from "@/features/orchestration/data/workspace-provider";
export function useMaterialsEnabled() { return Boolean(useWorkspaceRepository()); }
