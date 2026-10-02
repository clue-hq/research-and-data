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
  password: " test-only password with spaces ",
};
test("invitation sign-up supplies the required password with the ticket before finalizing", async () => {
  let status = "missing_requirements";
  const calls: string[] = [];
  const driver: ClerkTicketDriver = {
    missingFields: ["password"],
    unverifiedFields: [],
    get status() {
      return status;
    },
    async create(received) {
      assert.deepEqual(received, { ...params, strategy: "ticket" });
      calls.push("create");
      // Mirrors the live instance: a verified invitation email and names alone are
      // insufficient. The password must be supplied, without trimming its value.
      status = received.password === params.password ? "complete" : "missing_requirements";
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
  assert.deepEqual(calls, ["create", "finalize"]);
});

test("an incomplete or timed-out ticket never activates a session later", async () => {
  let finalized = false;
  let finish: (() => void) | undefined;
  const driver: ClerkTicketDriver = {
    status: "missing_requirements",
    missingFields: ["password"],
    unverifiedFields: [],
    async create() {
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
  driver.create = async () => ({ error: null });
  assert.equal((await acceptInvitationTicket(driver, params)).status, "error");
  assert.equal(finalized, false);
});

test("a blank invitation password is explained before starting a Clerk attempt", async () => {
  const driver: ClerkTicketDriver = {
    status: null,
    missingFields: [],
    unverifiedFields: [],
    async create() { assert.fail("must not start an incomplete sign-up"); },
    async finalize() { assert.fail("must not activate an incomplete sign-up"); },
  };
  assert.deepEqual(await acceptInvitationTicket(driver, { ...params, password: "" }), {
    status: "error",
    message: "Set a password to finish creating your account.",
  });
});

test("Clerk password policy errors are shown without activating a session", async () => {
  const driver: ClerkTicketDriver = {
    status: "missing_requirements",
    missingFields: ["password"],
    unverifiedFields: [],
    async create() {
      return { error: { message: "Password rejected", longMessage: "Choose a stronger password." } };
    },
    async finalize() { assert.fail("rejected passwords must not activate a session"); },
  };
  assert.deepEqual(await acceptInvitationTicket(driver, params), {
    status: "error",
    message: "Choose a stronger password.",
  });
});

test("other missing requirements and unverified identities never finalize", async () => {
  for (const requirements of [
    { missingFields: ["legal_accepted"], unverifiedFields: [] },
    { missingFields: [], unverifiedFields: ["email_address"] },
  ]) {
    const driver: ClerkTicketDriver = {
      status: "missing_requirements",
      ...requirements,
      async create() { return { error: null }; },
      async finalize() { assert.fail("unmet requirements must not activate a session"); },
    };
    const result = await acceptInvitationTicket(driver, params);
    assert.equal(result.status, "error");
    if (result.status === "error") assert.match(result.message, /additional sign-up requirements/);
  }
});

test("retrying completed sign-up retries session activation without consuming the ticket again", async () => {
  let attempts = 0;
  const driver: ClerkTicketDriver = {
    status: "complete",
    missingFields: [],
    unverifiedFields: [],
    async create() { assert.fail("a completed sign-up must not be recreated"); },
    async finalize() {
      attempts++;
      return { error: attempts === 1 ? { message: "Session activation failed." } : null };
    },
  };
  assert.deepEqual(await acceptInvitationTicket(driver, params), {
    status: "error", message: "Session activation failed.",
  });
  assert.deepEqual(await acceptInvitationTicket(driver, params), {
    status: "complete", flow: "sign-up",
  });
  assert.equal(attempts, 2);
});
