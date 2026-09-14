import assert from "node:assert/strict";
import test from "node:test";
import {
  acceptInvitationTicket,
  type ClerkTicketDriver,
} from "./onboarding-auth-driver";

const params = {
  ticket: "test-only-ticket",
  firstName: "Ada",
  lastName: "Lovelace",
};
test("ticket sign-up finalizes only after Clerk completes the attempt", async () => {
  let status = "missing_requirements";
  const calls: string[] = [];
  const driver: ClerkTicketDriver = {
    get status() {
      return status;
    },
    async ticket(received) {
      assert.deepEqual(received, params);
      calls.push("ticket");
      status = "complete";
      return { error: null };
    },
    async finalize() {
      calls.push("finalize");
      return { error: null };
    },
  };
  assert.equal(
    (await acceptInvitationTicket(driver, params)).status,
    "complete",
  );
  assert.deepEqual(calls, ["ticket", "finalize"]);
});

test("an incomplete or timed-out ticket never activates a session later", async () => {
  let finalized = false;
  let finish: (() => void) | undefined;
  const driver: ClerkTicketDriver = {
    status: "missing_requirements",
    async ticket() {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      return { error: null };
    },
    async finalize() {
      finalized = true;
      return { error: null };
    },
  };
  assert.equal(
    (await acceptInvitationTicket(driver, params, 1)).status,
    "error",
  );
  finish?.();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(finalized, false);
  driver.ticket = async () => ({ error: null });
  assert.equal((await acceptInvitationTicket(driver, params)).status, "error");
  assert.equal(finalized, false);
});
