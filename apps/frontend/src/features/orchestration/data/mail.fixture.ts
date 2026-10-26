import { createDirectMailFixture } from "@/features/direct-mail/data/direct-mail.fixture";
import { estimate, StateSchema } from "@/features/direct-mail/model/direct-mail";
import { createWorkspaceFixture } from "./workspace.fixture";
export function createV2MailFixture() {
  const state = createDirectMailFixture(), workspace = createWorkspaceFixture();
  state.mailers = state.mailers.filter((m) => workspace.accounts.some((a) => a.mailerId === m.id));
  state.creditEntries = []; state.creditBalanceCents = 200000;
  for (const mailer of state.mailers) {
    const account = workspace.accounts.find((a) => a.mailerId === mailer.id)!;
    mailer.projectId = workspace.project.id; mailer.projectName = workspace.project.name;
    mailer.threadId = "thread-primary"; mailer.campaign = "A thoughtful introduction";
    mailer.signature = `${workspace.people.find((p) => p.id === account.senderId)!.name}\nClue`;
    mailer.budgetCents = 16000;
    mailer.gifts.forEach((g, i) => { g.priceCents = [5800, 7400, 6800][i]; });
    mailer.selectedGiftId ??= mailer.gifts[0].id;
    if (mailer.id === "mailer-avery") mailer.addressConfirmed = true;
    if (mailer.approval) {
      mailer.approval = { ...mailer.approval, signature: mailer.signature, gift: structuredClone(mailer.gifts.find((g) => g.id === mailer.selectedGiftId)!), estimatedCents: estimate(mailer)!, budgetCents: mailer.budgetCents };
      state.creditEntries.push({ id: `approval-${mailer.id}-${mailer.approval.revision}`, kind: "mailer", amountCents: -estimate(mailer)!, mailerId: mailer.id, at: mailer.approval.at, description: `Approved mailer · ${mailer.recipient.name}` });
      state.creditBalanceCents -= estimate(mailer)!;
    }
  }
  state.giftBudgets = [{ projectId: workspace.project.id, revision: 1, minimumCents: 5000, preferredCents: 10000, ceilingCents: 12000, locked: true }];
  return StateSchema.parse(state);
}
