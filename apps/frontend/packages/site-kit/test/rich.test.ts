// Plan 2, Task 2: the rich text grammar (inline only: strong em u s br, a, span[data-s]) and the pure
// functions that read, check, draw, style and link it.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  linkAt,
  linkWords,
  normalizeRich,
  parseRich,
  richHtml,
  richProblems,
  richText,
  serializeRich,
  styleWords,
} from "../src/rich";

const same = (html: string) => serializeRich(parseRich(html) as never);

test("every mark round-trips, nested in one canonical order", () => {
  for (const html of [
    "plain words",
    "a <strong>bold</strong> word",
    "<em>italic</em>, <u>under</u>, <s>struck</s>",
    "one<br>two",
    '<a href="https://example.com/x">a link</a>',
    '<a href="/analysis" data-new-tab="">new tab</a>',
    '<span data-s="heading~1">styled</span> words',
    '<a href="/a"><span data-s="body~2"><strong><em>all</em></strong></span></a>',
  ]) {
    assert.equal(same(html), html, html);
  }
  assert.equal(same("<em><strong>x</strong></em>"), "<strong><em>x</em></strong>", "marks nest in one order");
  assert.equal(same("<b>x</b> <i>y</i>"), "<strong>x</strong> <em>y</em>", "b and i read as strong and em");
  assert.equal(same("<strong>a</strong><strong>b</strong>"), "<strong>ab</strong>", "equal neighbours merge");
});

test("entities are decoded to text and written back escaped", () => {
  assert.equal(richText("Care &amp; coverage &lt;3 &#8212; &nbsp;x"), "Care & coverage <3 —  x");
  assert.equal(same("Care &amp; coverage"), "Care &amp; coverage");
  assert.equal(same('<a href="/x?a=1&amp;b=2">x</a>'), '<a href="/x?a=1&amp;b=2">x</a>');
  assert.equal(richText("a bare & stays"), "a bare & stays");
});

test("one outer paragraph (what the editor writes) is read as its content", () => {
  assert.equal(same("<p>Top <strong>x</strong></p>"), "Top <strong>x</strong>");
  assert.deepEqual(richProblems("<p>Top</p>"), []);
  assert.equal(richText("<p>Top</p>"), "Top");
});

test("anything outside the grammar is refused with a sentence the writer can act on", () => {
  const cases: [string, RegExp][] = [
    ["<div>x</div>", /<div> is not allowed in text/],
    ['<p style="text-align:center">x</p>', /attribute "style" is not allowed on <p>/],
    ['<a href="javascript:alert(1)">x</a>', /a link must be an https:\/\/ address, a \/page of this site, a #anchor or mailto:/],
    ['<a href="/x" target="_blank">x</a>', /attribute "target" is not allowed on <a>; write data-new-tab/],
    ["<span>x</span>", /<span> needs data-s/],
    ['<span data-s="a b">x</span>', /data-s must be an element key/],
    ["<strong>open", /<strong> is not closed/],
    ["x</em>", /<\/em> closes nothing/],
    ["<p>a</p><p>b</p>", /one paragraph only: use <br> for a new line/],
    ['<a href="/a"><a href="/b">x</a></a>', /a link may not hold another link/],
    ['<span data-s="k~1"><span data-s="k~2">x</span></span>', /a styled span may not hold another/],
    ["5 < 10", /write &lt; for a "<" in text/],
  ];
  for (const [html, message] of cases) {
    const problems = richProblems(html);
    assert.equal(problems.length, 1, `${html}: ${JSON.stringify(problems)}`);
    assert.match(problems[0], message, html);
  }
  assert.ok("error" in (parseRich("<div>x</div>") as object));
});

test("normalizeRich turns anything into the grammar, keeping the words", () => {
  assert.equal(normalizeRich("<p>Lower <em>clinical</em> spend</p>"), "Lower <em>clinical</em> spend");
  assert.equal(normalizeRich('<p style="text-align: center;">Centred</p>'), "Centred");
  assert.equal(normalizeRich("<p>one</p><p>two</p>"), "one<br>two");
  assert.equal(normalizeRich('<div class="x">a<script>alert(1)</script></div>'), "a");
  assert.equal(normalizeRich('<a href="https://x.com" target="_blank" rel="noopener noreferrer nofollow">x</a>'), '<a href="https://x.com">x</a>');
  assert.equal(normalizeRich('<a href="javascript:x">bad</a>'), "bad");
  assert.equal(normalizeRich("5 < 10 & more"), "5 &lt; 10 &amp; more");
  assert.equal(normalizeRich('<span style="color:red">x</span>'), "x");
  for (const html of ["", "plain", '<a href="/a" data-new-tab=""><span data-s="h~1">x</span></a>']) {
    assert.equal(normalizeRich(html), html, "canonical text is left as it is");
    assert.equal(normalizeRich(normalizeRich(html)), normalizeRich(html));
  }
});

test("richHtml draws the published markup: new tab, base path, no outer paragraph, never raw markup", () => {
  const href = (value: string) => (value.startsWith("/") ? `/s/garner${value}` : value);
  assert.equal(
    richHtml('<p>See <a href="/analysis" data-new-tab="">the analysis</a></p>', href),
    'See <a href="/s/garner/analysis" target="_blank" rel="noopener">the analysis</a>',
  );
  assert.equal(richHtml('<a href="https://x.com">x</a>', href), '<a href="https://x.com">x</a>');
  assert.equal(richHtml("<script>alert(1)</script>words", href), "words");
});

test("richText counts characters as the browser's textContent does (a line break is no character)", () => {
  assert.equal(richText("one<br>two <strong>three</strong>"), "onetwo three");
});

const bold = () => ({ fontWeight: 700 });

test("styling words in plain text wraps them in a new styled span", () => {
  const out = styleWords("Top providers win", 4, 13, bold, {}, "heading");
  assert.equal(out.html, 'Top <span data-s="heading~1">providers</span> win');
  assert.deepEqual(out.edits, { "heading~1": { fontWeight: 700 } });
});

test("styling exactly an already styled run updates its own entry", () => {
  const html = 'Top <span data-s="heading~1">providers</span> win';
  const out = styleWords(html, 4, 13, (old) => ({ ...old, italic: true }), { "heading~1": { fontWeight: 700 } }, "heading");
  assert.equal(out.html, html);
  assert.deepEqual(out.edits, { "heading~1": { fontWeight: 700, italic: true } });
});

test("styling across a styled run's edge gives every highlighted word the property and keeps the rest", () => {
  const html = 'Top <span data-s="heading~1">providers</span> win';
  const edits = { "heading~1": { color: { token: "text.heading" } } };
  const out = styleWords(html, 8, 17, (old) => ({ ...old, fontSize: 40 }), edits, "heading");
  assert.equal(out.html, 'Top <span data-s="heading~1">prov</span><span data-s="heading~2">iders</span><span data-s="heading~3"> win</span>');
  assert.deepEqual(out.edits, {
    "heading~1": { color: { token: "text.heading" } },
    "heading~2": { color: { token: "text.heading" }, fontSize: 40 },
    "heading~3": { fontSize: 40 },
  });
});

test("an override that ends up empty unwraps its words; keys no longer used are dropped", () => {
  const html = 'Top <span data-s="heading~1">providers</span> win';
  const out = styleWords(html, 4, 13, () => ({}), { "heading~1": { italic: true }, other: { italic: true } }, "heading");
  assert.equal(out.html, "Top providers win");
  assert.deepEqual(out.edits, { other: { italic: true } });
});

test("styling keeps the text's other marks and links", () => {
  const out = styleWords('<a href="/x">read <strong>more</strong></a>', 0, 9, bold, {}, "body");
  assert.equal(out.html, '<a href="/x"><span data-s="body~1">read <strong>more</strong></span></a>');
});

test("linking words adds a link; a range inside a link edits that whole link; null removes it", () => {
  assert.equal(linkWords("see the analysis now", 4, 16, { href: "/analysis", newTab: false }), 'see <a href="/analysis">the analysis</a> now');
  const linked = 'see <a href="/analysis">the analysis</a> now';
  assert.equal(linkWords(linked, 8, 10, { href: "https://x.com", newTab: true }), 'see <a href="https://x.com" data-new-tab="">the analysis</a> now');
  assert.equal(linkWords(linked, 8, 10, null), "see the analysis now");
  assert.deepEqual(linkAt(linked, 8, 10), { href: "/analysis", newTab: false, start: 4, end: 16 });
  assert.deepEqual(linkAt(linked, 9, 9), { href: "/analysis", newTab: false, start: 4, end: 16 }, "a caret inside a link");
  assert.equal(linkAt(linked, 0, 3), null);
  assert.equal(linkAt(linked, 0, 10), null, "a range only partly in the link");
});

// End-of-plan review findings 3, 6 and 7.
import { isRichLink } from "../src/rich";

test("a named character reference the grammar does not know is refused, not drawn literally", () => {
  assert.deepEqual(richProblems("Fast &mdash; simple"), ['write the character itself instead of "&mdash;"']);
  assert.deepEqual(richProblems("Fast &#8212; simple &amp; &nbsp;"), []);
  assert.equal(richText("Tom &mdash"), "Tom &mdash", "a bare & that names nothing is text");
});

test("one link rule: no protocol-relative address and no spaces", () => {
  for (const ok of ["/", "/analysis", "#top", "https://x.com/a?b=1", "http://x.com", "mailto:a@b.com"]) assert.ok(isRichLink(ok), ok);
  for (const bad of ["//evil.example", "/ evil", "javascript:x", "example.com", "https://x.com/a b"]) assert.equal(isRichLink(bad), false, bad);
  assert.match(richProblems('<a href="//evil.example">x</a>')[0], /a link must be/);
});

test("reading long malformed text takes linear time", () => {
  const hostile = "<a b".repeat(50_000);
  const started = Date.now();
  normalizeRich(hostile);
  richProblems(hostile);
  assert.ok(Date.now() - started < 1500, `took ${Date.now() - started} ms`);
});

// Plan 3: a button's words are rich text without links.
test("rich text without links refuses and drops a link, keeping its words", () => {
  assert.deepEqual(richProblems('Book <a href="/x">now</a>', { links: false }), ["a button's words may not hold a link"]);
  assert.deepEqual(richProblems("Book <strong>now</strong>", { links: false }), []);
  assert.equal(normalizeRich('Book <a href="/x"><em>now</em></a>', { links: false }), "Book <em>now</em>");
});
