'use client';
import { useState } from 'react';
import type { WorkspaceController } from '@/features/orchestration/hooks/use-workspace';
import { contentApprovalRequest, type CampaignArtifact } from '@/features/orchestration/model/workspace';

export function useContentApproval(asset:CampaignArtifact|undefined,c:WorkspaceController) {
 const [confirmation,setConfirmation]=useState<ReturnType<typeof contentApprovalRequest>|null>(null);
 async function confirm() {
  if(!confirmation||!c.repository)return;
  const request=confirmation;
  if(await c.run(()=>c.repository!.approveContent(request.id,request.version)))setConfirmation(null);
 }
 return {
  confirmation,confirm,
  begin(){if(asset)setConfirmation(contentApprovalRequest(asset));},
  close(){setConfirmation(null);},
 };
}
