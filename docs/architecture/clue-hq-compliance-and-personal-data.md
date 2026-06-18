# Clue-HQ — Compliance & Personal-Data Governance

### Doc D. Extends the substrate doc §6 (verification) and the staged-flow doc §6, §8 (contact profiling, identity-binding).

> **Not legal advice.** The legal characterizations below are stable fundamentals for orientation. Before this is operationalized, the 2026 specifics — current US state privacy laws, EU AI Act touchpoints, and data-protection-authority stances on web scraping — must be verified by whoever owns the data/compliance decision (and can be re-researched on request). Tracked as **D8**.

The original architecture is **silent** on personal-data governance. That silence is the single most dangerous gap once the product does deep personal research on named individuals "to any lengths," because the system targets real people, many outside the US, and the artifacts land on real desks. This doc adds the missing layer: a way to be powerful about resonance **and** lawful and tasteful about people.

The core realization: **a personal fact can be true, well-sourced, and correctly attributed to the right person — and still be unlawful or reputation-destroying to use.** The existing identity-binding gate (staged-flow §6) protects against *wrongness*. Nothing yet protects against *inappropriateness or unlawfulness*. Those are different gates.

---

## 1. Jurisdiction as a first-class, per-client switch (resolved — D4: mixed/global)

Because target contacts are mixed/global, jurisdiction is not an afterthought:

- **Every contact entity carries a resolved jurisdiction** (from location claims), and every personal claim inherits it.
- **Policy is parameterized by jurisdiction.** The use-gate (§3) reads `(use_class, jurisdiction, client_policy)` to decide whether a claim may drive outreach.
- **Design for the strict case, switch down.** Default behavior assumes GDPR-grade obligations (the strictest common case); lighter regimes (US B2B) are a relaxation of the same machinery, never a separate code path. Building US-only-first and bolting on GDPR later would mean retrofitting lawful-basis tracking and data-subject rights across an existing store — exactly the kind of base-layer rework the substrate doc warns against.

---

## 2. The use-class taxonomy (tag at extraction)

Every personal claim is tagged with a **use-class** the moment it is extracted, independent of whether it's accurate:

- **`professional-public`** — role history, public posts, talks, publications, company affiliations, professional activity. The backbone of legitimate B2B research.
- **`personal-public-non-sensitive`** — publicly stated, low-sensitivity personal facts: a hobby, alma mater, a sports team, a marathon finish.
- **`sensitive`** — anything in (or adjacent to) GDPR **special categories** (health, religious/philosophical beliefs, political opinions, sexual orientation, racial/ethnic origin, trade-union membership, biometric/genetic data) **or** that a reasonable person treats as private (family/children, financial status, health, religion-adjacent hobbies). Note that some "interests" the deep research surfaces can quietly fall here — a hobby tied to a religious or political cause is special-category-adjacent.

The taxonomy is the hinge the three postures (§6) turn on.

---

## 3. Two gates, kept distinct

| Gate | Question it answers | Mechanism | Where defined |
|---|---|---|---|
| **Accuracy / identity-binding** | Is this true, and is it *this* person? | evidence span + faithfulness judge + identity-binding strength (strong vs. weak) | substrate §6, staged-flow §6 |
| **Appropriateness / use** *(new)* | May we lawfully and tastefully *use* it? | `(use_class × jurisdiction × client_policy)` policy | this doc |

A `contact.facet.*` claim drives outreach **only if it clears both**: strong identity-binding *and* an allowed use-class for its jurisdiction under the client's policy. Weak-binding claims never promote (the same-name trap); disallowed-use-class claims never promote (the unlawful/creepy trap). Either failure leaves the field empty — which, per the universal rule, is a correct output.

---

## 4. Lawful basis, retention, and data-subject rights

- **Lawful basis recorded as provenance.** For `professional-public` B2B signals, the working basis is typically *legitimate interest* (GDPR Art. 6(1)(f)), which requires a documented balancing test (an LIA). The basis is stored alongside the claim, so "why were we allowed to hold this" is queryable, not assumed.
- **Special-category data needs more than legitimate interest** (GDPR Art. 9) — effectively explicit consent you will not have in cold outreach. The practical consequence: `sensitive` claims are **excluded from outreach by default** regardless of posture, and (depending on posture) may not be stored at all.
- **Transparency.** When personal data is collected from sources other than the person (Art. 14), notice obligations can attach. Flag this for the compliance owner; it shapes whether/what the client must disclose.
- **Retention TTLs on personal claims.** Personal claims carry a shorter freshness/retention TTL than firmographic facts — both because people change and because minimizing retained personal data shrinks risk. Expired personal claims age out.
- **Data-subject rights surface.** Access, rectification, **erasure**, and objection (the right to object to direct-marketing processing under Art. 21 is near-absolute) must be serviceable. Because the claim store is append-only and keyed on a resolved `contact_entity_id`, an erasure request resolves to a deterministic set of claims to tombstone — the provenance model that makes research verifiable also makes erasure tractable.

---

## 5. The appropriateness gate is not the accuracy judge

Worth stating plainly so they don't collapse in implementation: the faithfulness judge asks *"is the claim entailed by its evidence?"* The appropriateness gate asks *"should this true claim be used on this person in this jurisdiction for this client?"* A claim can pass the first and fail the second (a true, sourced, correctly-attributed health detail). They run as separate steps with separate observability, so "we used something we shouldn't have" and "we fabricated something" are distinct, separately-measurable failures.

---

## 6. The three postures (per-client config; decision deferred to the data/compliance owner — D3)

These are **not** permanent forks. The recommended product shape ships **Option 1 as the default** and exposes Options 2 and 3 as per-client policy settings on the same `use_class × jurisdiction` machinery. A regulated client dials down to 3; an aggressive US client dials up to 2. The posture becomes a configuration decision per client, not a hardcoded platform choice.

### Option 1 — Configurable, conservative default *(recommended default)*
- **Gathered:** the full deep open-internet sweep is allowed; every personal claim is use-class-tagged at extraction.
- **Usable for outreach:** by default only `professional-public` + `personal-public-non-sensitive`. `sensitive` is locked (stored-but-unusable) or not stored, per client config.
- **Legal posture (mixed/global):** maps to the stricter GDPR bar — excluding special-category data by default keeps you out of the highest-risk processing; legitimate-interest (with a documented LIA) covers professional B2B. Comfortably conservative for the US too.
- **Resonance vs. brand:** keeps almost all the useful resonance (good hooks are mostly professional + light-personal) and sheds the creepy tail. **Best risk-adjusted outcome.**
- **Ops load:** moderate — maintain the taxonomy + per-client/jurisdiction policy; the default carries most clients without intervention.

### Option 2 — Gather broadly, gate at use
- **Gathered:** same broad sweep, **including `sensitive`, all stored.**
- **Usable:** nothing excluded at gather-time; the appropriateness gate decides per claim × jurisdiction × policy at the moment a claim would enter an artifact.
- **Legal posture:** riskier globally — *storing* special-category data is itself processing that needs an Art. 9 basis regardless of use, so the obligation attaches whether or not the claim is ever used; heaviest data-subject-rights, security, and erasure burden. Workable US-only, exposed in the EU/UK.
- **Resonance vs. brand:** highest ceiling (everything available, gated at the last mile) and highest downside if the gate misfires.
- **Ops load:** highest — you become a controller of sensitive personal data at scale; the use-gate must be near-perfect and retention/erasure machinery robust.

### Option 3 — Professional-public only
- **Gathered:** research is scoped at the **source level** to professional-public surfaces (LinkedIn, company pages, talks, publications, professional posts). The deep personal-life dimension (childhood, tastes, favorite band) is **never collected.**
- **Usable:** effectively everything gathered (it's all professional-public), so the use-gate is light.
- **Legal posture:** lowest risk by far — largely avoids special-category data and the creepiness problem; legitimate-interest is straightforward; smallest DSAR/erasure surface.
- **Resonance vs. brand:** loses the "they really know me" hooks — exactly what the deep dives surface — so resonance reverts toward what AI-SDR tools already do.
- **Ops load:** lowest.

---

## 7. How this binds to the rest of the system

- **Field-classes:** `contact.facet.*` (Doc C §2) is governed entirely here — it is the field-class the use-gate primarily polices.
- **Verification layer:** the use-gate is a new member of the verification layer (substrate §6), running after identity-binding and the faithfulness judge, with its own trace span.
- **Output contract:** every contact claim crossing the handoff (overview §3) carries both `identity_binding` and `use_class`, so the downstream content layer can *also* see why a hook is or isn't usable.
- **Universal rule, restated:** an empty, flagged personal field is a correct output; a fabricated, misattributed, *or inappropriate* one is the failure.

---

## 8. Open items (tracked in overview §5)

- **D3 — Posture:** decision deferred to the data/compliance owner; all three shipped as per-client config with Option 1 default.
- **D8 — 2026 legal verification:** confirm current US state laws, EU AI Act touchpoints, and DPA scraping stances before go-live; offered as a dedicated research pass.
