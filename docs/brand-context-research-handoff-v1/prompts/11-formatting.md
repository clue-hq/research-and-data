# Meaning-preserving formatting contract

Default executor: Python, extending the existing `KnowledgeDocument` mappers and `render_markdown`. No model is needed to add headings, render Markdown tables or write front matter.

Input is a schema-valid, evidence-reviewed document with a key, friendly title, summary, ordered sections, evidence references, questions and any approved structured ICP fields. Render one Markdown artifact. Preserve wording, numbers, units, negation, dates, attribution, hypothesis markers and the association between a claim and its citation. Escape table delimiters and retain readable three-to-five-column tables. Resolve internal document references through the stable registry. Do not expose internal filenames as display titles. Do not add a second agent-context document or panel.

If an inexpensive model is explicitly configured for malformed-output repair, it receives only the malformed candidate plus the intended format. It has no research tools. Return `repaired_document` and `changes` listing only structural edits: quoting/escaping, JSON syntax, heading hierarchy, table separators or resolved known link syntax. Do not paraphrase sentences, complete sections, reconcile facts, change titles semantically, adjust gate logic or invent IDs. Failure to repair without changing meaning returns `cannot_repair` with the exact issue.

The host compares semantic payload fields before/after. A change to a statement, number, unit, source ID, uncertainty, exclusion or evidence link rejects the repair and retains the prior version. A repair model cannot be used as an untracked content writer. Its actual configured provider/model, usage and request/output hashes must be recorded.
