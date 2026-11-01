import type { Stage } from "./direct-mail";

export const HARVEY_DEMO_ID = "mailer-harvey-benesch-jason";
export const HARVEY_PROJECT_ID = "prj_7f66ff82c4185f7789074d4555f3105e";
export const HARVEY_ACCOUNT_ID = "aae1f2fd-6762-4245-8617-7b1045ad3a7e";
export const HARVEY_RESEARCH_URL = `https://app.cluehq.ai/accounts/${HARVEY_ACCOUNT_ID}?projectId=${HARVEY_PROJECT_ID}`;
export const HARVEY_PROJECT_URL = `https://app.cluehq.ai/projects/${HARVEY_PROJECT_ID}/chats/thr_2134514622d05eddb8d34bf58bc680dc`;
export const HARVEY_DEMO_HREF = `/direct-mail/${HARVEY_DEMO_ID}`;
export const HARVEY_QUEUE_HREF = `/direct-mail?demo=harvey&project=${HARVEY_PROJECT_ID}`;

export const harveyNextLabel: Partial<Record<Stage, string>> = { approved: "Simulate order confirmation", ordered: "Simulate delivery to Clue", inbound: "Simulate arrival at Clue", received: "Simulate package preparation", preparing: "Simulate quality check", ready_to_ship: "Simulate dispatch", shipped: "Simulate delivery" };

export const HARVEY_DELIVERED_ID = "mailer-harvey-pinsent-hayley";
export const HARVEY_PINSENT_ID = "492748aa-f17d-4224-a76a-286d0abfdb59";
const media = "/direct-mail/harvey-demo";
export const harveyAccounts: Record<string, { name: string; logo: string }> = {
  [HARVEY_ACCOUNT_ID]: { name: "Benesch", logo: `${media}/benesch-logo.svg` },
  [HARVEY_PINSENT_ID]: { name: "Pinsent Masons", logo: `${media}/pinsent-logo.svg` },
};
export const harveyMaterials = [
  { id: "benesch-page", accountId: HARVEY_ACCOUNT_ID, account: "Benesch", type: "Landing page", title: "A lawyer-reviewed AI workflow", image: `${media}/benesch-page.jpg`, source: HARVEY_PROJECT_URL },
  { id: "benesch-ad", accountId: HARVEY_ACCOUNT_ID, account: "Benesch", type: "LinkedIn ad", title: "Beyond public AI. Start with diligence.", image: `${media}/benesch-ad.jpg`, source: `https://app.cluehq.ai/projects/${HARVEY_PROJECT_ID}/chats/thr_5d9e21bb6a7054889058da53fd8ee61a` },
  { id: "pinsent-page", accountId: HARVEY_PINSENT_ID, account: "Pinsent Masons", type: "Landing page", title: "Bring firm knowledge to client work", image: `${media}/pinsent-page.jpg`, source: HARVEY_PROJECT_URL },
  { id: "pinsent-ad", accountId: HARVEY_PINSENT_ID, account: "Pinsent Masons", type: "LinkedIn ad", title: "Document-scale diligence. Lawyer-led decisions.", image: `${media}/pinsent-ad.jpg`, source: `https://app.cluehq.ai/projects/${HARVEY_PROJECT_ID}/chats/thr_5d9e21bb6a7054889058da53fd8ee61a` },
];
