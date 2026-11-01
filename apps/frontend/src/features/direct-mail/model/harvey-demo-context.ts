import type { Stage } from "./direct-mail";

export const HARVEY_DEMO_ID = "mailer-harvey-benesch-jason";
export const HARVEY_PROJECT_ID = "prj_7f66ff82c4185f7789074d4555f3105e";
export const HARVEY_ACCOUNT_ID = "aae1f2fd-6762-4245-8617-7b1045ad3a7e";
export const HARVEY_RESEARCH_URL = `https://app.cluehq.ai/accounts/${HARVEY_ACCOUNT_ID}?projectId=${HARVEY_PROJECT_ID}`;
export const HARVEY_PROJECT_URL = `https://app.cluehq.ai/projects/${HARVEY_PROJECT_ID}/chats/thr_2134514622d05eddb8d34bf58bc680dc`;
export const HARVEY_DEMO_HREF = `/direct-mail/${HARVEY_DEMO_ID}`;
export const HARVEY_QUEUE_HREF = `/direct-mail?demo=harvey&project=${HARVEY_PROJECT_ID}`;

export const harveyNextLabel: Partial<Record<Stage, string>> = { approved: "Simulate order confirmation", ordered: "Simulate delivery to Clue", inbound: "Simulate arrival at Clue", received: "Simulate package preparation", preparing: "Simulate quality check", ready_to_ship: "Simulate dispatch", shipped: "Simulate delivery" };
