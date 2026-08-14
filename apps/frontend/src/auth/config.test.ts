import assert from "node:assert/strict";
import test from "node:test";
import {
  clueAppOrigin,
  isAuthenticationEnabled,
  requireAuthenticationConfiguration,
} from "./config";

test("authentication remains an explicit opt-in before B5", () => {
  const previous = process.env.CLUE_AUTH_ENABLED;
  delete process.env.CLUE_AUTH_ENABLED;
  try {
    assert.equal(isAuthenticationEnabled(), false);
    assert.doesNotThrow(requireAuthenticationConfiguration);
  } finally {
    if (previous === undefined) delete process.env.CLUE_AUTH_ENABLED;
    else process.env.CLUE_AUTH_ENABLED = previous;
  }
});

test("local authentication uses localhost as its one canonical browser origin", () => {
  const previous = process.env.CLUE_APP_ORIGIN;
  delete process.env.CLUE_APP_ORIGIN;
  try {
    assert.equal(clueAppOrigin(), "http://localhost:3000");
  } finally {
    if (previous === undefined) delete process.env.CLUE_APP_ORIGIN;
    else process.env.CLUE_APP_ORIGIN = previous;
  }
});

test("authentication preflight refuses origin and Clerk authorized-party drift", () => {
  const names = [
    "CLUE_AUTH_ENABLED",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "CLUE_API_BASE_URL",
    "CLUE_APP_ORIGIN",
    "CLUE_AUTH_CLERK_AUTHORIZED_PARTIES",
  ] as const;
  const previous = Object.fromEntries(names.map((name) => [name, process.env[name]]));
  Object.assign(process.env, {
    CLUE_AUTH_ENABLED: "true",
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_placeholder",
    CLERK_SECRET_KEY: "sk_test_placeholder",
    CLUE_API_BASE_URL: "http://127.0.0.1:8000",
    CLUE_APP_ORIGIN: "http://localhost:3000",
    CLUE_AUTH_CLERK_AUTHORIZED_PARTIES: "http://127.0.0.1:3000",
  });
  try {
    assert.throws(
      requireAuthenticationConfiguration,
      /must be listed in CLUE_AUTH_CLERK_AUTHORIZED_PARTIES/,
    );
  } finally {
    for (const name of names) {
      const value = previous[name];
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test("enabled authentication refuses missing provider/API configuration", () => {
  const names = [
    "CLUE_AUTH_ENABLED",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "CLUE_API_BASE_URL",
  ] as const;
  const previous = Object.fromEntries(names.map((name) => [name, process.env[name]]));
  process.env.CLUE_AUTH_ENABLED = "true";
  delete process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  delete process.env.CLERK_SECRET_KEY;
  delete process.env.CLUE_API_BASE_URL;
  try {
    assert.throws(
      requireAuthenticationConfiguration,
      /NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, CLUE_API_BASE_URL/,
    );
  } finally {
    for (const name of names) {
      const value = previous[name];
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
