import assert from "node:assert/strict";
import test from "node:test";
import { AccountContactDetailSchema } from "./account-contact";
import { AccountDetailSchema } from "./account-detail";
import {
  formatJsonScalar,
  formatSemanticToken,
  formatSemanticValue,
} from "./formatting";

test("stable labels format backend enum tokens without changing ordinary prose", () => {
  assert.equal(formatJsonScalar("1b_plus"), "$1B+");
  assert.equal(formatJsonScalar("product_led"), "Product-led");
  assert.equal(formatSemanticToken("c_level"), "C-level");
  assert.equal(formatSemanticToken("economic_buyer"), "Economic buyer");
  assert.equal(
    formatSemanticValue("Dana leads Acme's economic buyer evaluation."),
    "Dana leads Acme's economic buyer evaluation.",
  );
});

test("Account and Contact models retain raw machine values from the wire", () => {
  const account = AccountDetailSchema.parse({
    id: "account-1",
    name: "Acme",
    neutralFacts: [
      {
        fieldKey: "core.revenue_band",
        value: "1b_plus",
      },
      {
        fieldKey: "fi2read.growth_model",
        value: "product_led",
      },
    ],
  });
  assert.equal(account.neutralFacts[0]?.value, "1b_plus");
  assert.equal(account.neutralFacts[1]?.value, "product_led");

  const contact = AccountContactDetailSchema.parse({
    id: "contact-1",
    accountId: "account-1",
    persona: "economic_buyer",
    roleOnCommittee: { value: "economic_buyer" },
    professionalFacts: [
      { fieldKey: "contact.job_level", value: "c_level" },
    ],
  });
  assert.equal(contact.persona, "economic_buyer");
  assert.equal(contact.roleOnCommittee.value, "economic_buyer");
  assert.equal(contact.professionalFacts[0]?.value, "c_level");
});
