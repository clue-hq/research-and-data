import type { Stage } from "./direct-mail";

/** This isolated checkout's recording context. No production workspace is mutated. */
export const DEMO_ID = "mailer-illumio-usbank-ann";
export const DEMO_PROJECT_ID = "prj_f9574afe6def584da9ff7ba3cd3f35d3";
export const DEMO_ACCOUNT_ID = "4f443b25-643b-4e64-b76d-da4bb0194d62";
export const DEMO_RESEARCH_URL = `https://app.cluehq.ai/accounts/${DEMO_ACCOUNT_ID}?projectId=${DEMO_PROJECT_ID}`;
export const DEMO_PROJECT_URL = `https://app.cluehq.ai/projects/${DEMO_PROJECT_ID}/chats/thr_a84254ae478e5e38b63b743c31fd89fb?surface=site`;
export const DEMO_QUEUE_HREF = `/direct-mail?demo=illumio&project=${DEMO_PROJECT_ID}`;
export const demoNextLabel: Partial<Record<Stage, string>> = { approved: "Simulate order confirmation", ordered: "Simulate delivery to Clue", inbound: "Simulate arrival at Clue", received: "Simulate package preparation", preparing: "Simulate quality check", ready_to_ship: "Simulate dispatch", shipped: "Simulate delivery" };
const media = "/direct-mail/illumio-demo";
export const demoAccounts: Record<string, { name: string; logo: string }> = {
  [DEMO_ACCOUNT_ID]: { name: "U.S. Bank", logo: `${media}/usbank-logo.svg` },
};
export const demoMaterials = [
  { id: "usbank-page", accountId: DEMO_ACCOUNT_ID, account: "U.S. Bank", type: "Landing page", title: "Breach containment for U.S. Bank’s hybrid move", image: `${media}/usbank-page.png`, source: DEMO_PROJECT_URL },
  { id: "usbank-ad", accountId: DEMO_ACCOUNT_ID, account: "U.S. Bank", type: "LinkedIn ad", title: "Move to AWS. Keep breaches contained.", image: `${media}/usbank-ad.png`, source: `https://app.cluehq.ai/projects/${DEMO_PROJECT_ID}/chats/thr_bd27d233d4ab5885ac956f5c2327deac?surface=ad` },
];
