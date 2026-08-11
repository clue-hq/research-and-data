import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ContactAvatar } from "./contact-avatar";

test("an adjacent fallback avatar is absent from the accessibility tree", () => {
  const html = renderToStaticMarkup(
    createElement(ContactAvatar, {
      decorative: true,
      name: "Dana Buyer",
      size: 24,
    }),
  );

  assert.match(html, /aria-hidden="true"/);
  assert.doesNotMatch(html, /aria-label=/);
  assert.doesNotMatch(html, /role="img"/);
});

test("a standalone fallback avatar retains one useful accessible name", () => {
  const html = renderToStaticMarkup(
    createElement(ContactAvatar, { name: null, size: 24 }),
  );

  assert.match(html, /aria-label="Unnamed contact"/);
  assert.match(html, /role="img"/);
});

test("an adjacent image avatar is decorative too", () => {
  const html = renderToStaticMarkup(
    createElement(ContactAvatar, {
      decorative: true,
      name: "Dana Buyer",
      size: 24,
      src: "https://cdn.example.test/dana.jpg",
    }),
  );

  assert.match(html, /alt=""/);
  assert.match(html, /aria-hidden="true"/);
  assert.doesNotMatch(html, /alt="Dana Buyer"/);
});
