"""Curated conflict groups over the ledger. Each ref is (source_id, substring of the row text);
build fails loudly if a ref matches no row or more than one row of that source."""
import json, sys
from pathlib import Path

HERE = Path(__file__).parent
ROWS = [json.loads(l) for f in sorted((HERE / "ledger").glob("*.jsonl")) for l in open(f)]

def find(sid, sub):
    hits = [r["id"] for r in ROWS if r["id"].rsplit("-", 1)[0] == sid and sub.lower() in r["text"].lower()]
    if len(hits) != 1:
        sys.exit(f"ref ({sid!r}, {sub!r}) matched {hits}")
    return hits[0]

ISSUES = [
 {"id": "I1", "topic": "SCOPE", "severity": "high",
  "title": "Nine 'keep it small' rules, and nothing that lets a revamp recompose",
  "what": "Every turn on an existing ad carries rules that say change as little as possible and keep the layout. They come from the system prompt, the operating note, a skill, two guides and the attached editor instruction. The follow-up routine sends a revamp to the 'full routine', but the full routine still contains the preserve rule. No rule anywhere says a revamp may change the composition, and the direction record has no intent value for it.",
  "why": "This is why 'Make the whole ad feel more premium' kept the layout and only swapped the image.",
  "groups": [
   {"label": "Keep it small (every turn on an existing ad)", "refs": [
     ("A1", "For a seeded edit, inspect the current scene"),
     ("A2", "4. Proportionality"), ("A2", "UNRELATED content stays untouched"),
     ("C1", "For an edit, preserve the request's subject"),
     ("D5", "Change the smallest coherent part"), ("D5", "Preserve successful unrelated content"),
     ("E2", "keep unrelated existing content intact"),
     ("E4", "Preserve successful user-edited groups"),
     ("G1", "Prefer targeted repairs"), ("G1", "surrounding layout must be preserved")]},
   {"label": "What the revamp is told instead", "refs": [
     ("A1", "a revamp such as"),
     ("A2", "3. Existing elements implicated by the request")]},
   {"label": "No place to record a revamp", "refs": [
     ("E1", "intent: native, reuse, edit"), ("E3", "Choose intent explicitly")]}]},
 {"id": "I2", "topic": "SCOPE", "severity": "high",
  "title": "Is a selected element the subject or a fence?",
  "what": "When the person has elements selected, the attached editor instruction says touch nothing else and keep every other node byte-identical. The system prompt's shared-surface rules say the selection is the subject of the request, never a fence, and that neighbours may be restyled, resized or moved, with small announced collateral changes allowed.",
  "why": "The agent gets both on the same turn. The third follow-up (image selected) followed the fence.",
  "groups": [
   {"label": "Fence (attached to the message)", "refs": [("G1", "Scope every change to these target")]},
   {"label": "Subject (system prompt)", "refs": [
     ("A2", "1. The request defines the goal"), ("A2", "3. Existing elements implicated"), ("A2", "4. Proportionality")]}]},
 {"id": "I3", "topic": "PRECEDENCE", "severity": "high",
  "title": "The brand's observed look is ranked below the request, and only binds in account skills",
  "what": "The only text that describes how the brand's ads look is labelled 'advisory … nothing here overrides what the person actually asked for'. The imagery skill and the references guide keep the brand's material and texture only 'when the chosen direction requires it', and the agent chooses the direction. The clear rule ('preserve the advertiser's voice, palette and visual system unless a departure is requested') lives only in the two account skills and the account part of review. Playbooks disagree on whether continuity is the default or only on request. Conduit's kit has no imagery rules at all, and the token guides define on-brand as using tokens.",
  "why": "This is why the revamp replaced Conduit's pastel bokeh with warm wood, stone and lamp light: 'premium' counted as what the person asked for.",
  "groups": [
   {"label": "Brand look is advisory / below the request", "refs": [
     ("A4", "It is context, not a rule"), ("H3", "It is context, not a rule"),
     ("A3", "published-ad context is advisory"),
     ("D9", "Preserve the inspected reference's material"),
     ("E3", "Preserve those qualities where the direction requires them"),
     ("E3", "A new subject does not authorize invented lighting"),
     ("E3", "rather than deriving the style from labels or an ad-DNA summary")]},
   {"label": "Brand look binds (account skills only)", "refs": [
     ("D13", "Preserve the advertiser's voice, palette and visual system"),
     ("D14", "The advertiser's references determine the visual system"),
     ("D14", "Preserve the advertiser's observed material"),
     ("E4", "preserve advertiser voice, type, palette and approved groups")]},
   {"label": "Playbooks: continuity only when asked", "refs": [
     ("D15", "when the request asks for continuity"), ("D18", "when the request calls for continuity"),
     ("D18", "when continuity is requested"), ("D17", "where continuity matters")]},
   {"label": "Playbooks: keep the look", "refs": [
     ("D17", "Do not remove observed texture"), ("D17", "A flat palette match does not preserve"),
     ("E2", "An inspected reference's soft material")]},
   {"label": "What 'brand' means elsewhere", "refs": [
     ("C1", "The request, current scene, supplied brand kit"),
     ("A7", "binding brand context take precedence"),
     ("A4", "imagery_rules"), ("F9", "Lumen designs look on-brand because they reference role tokens")]}]},
 {"id": "I4", "topic": "REVIEW", "severity": "high",
  "title": "The self-check grades the agent's own plan",
  "what": "Acceptance requires every 'preserve' and 'review_needs' item to be met. The agent writes both lists itself in its direction. The review guide says the direction cannot certify its own choices, and the framework says to check against what was asked, but the anti-circular rule that actually names the user's request exists only for account adaptation.",
  "why": "The revamp accepted itself because 'warmer atmosphere' was on its own checklist.",
  "groups": [
   {"label": "Acceptance = own checklist", "refs": [
     ("A1", "Use that contract, including direction_review"),
     ("E4", "Acceptance requires every preserve and review_needs item"),
     ("E4", "Use the tool's indexed requirements"),
     ("E1", "review_needs: nonempty list"),
     ("D4", "Judge current pixels against the validated direction")]},
   {"label": "Check against the request (weak or account-only)", "refs": [
     ("E4", "The direction is a plan to assess"),
     ("A5", "check your work against what was asked"),
     ("D14", "Review against the original request"),
     ("E4", "For account adaptation, first read the original request")]}]},
 {"id": "I5", "topic": "ROUTINE", "severity": "high",
  "title": "The follow-up routine and the edit skills give opposite instructions",
  "what": "The follow-up routine says: use apply_structured_edit, don't re-validate the direction, don't write critique.json or round notes, finish edit_applied. repair-design (whose description covers 'a scoped edit') says: use compile_dsl_block modify lines, keep the direction current and re-validate it, record the repair delta in the round. The review guide says edit_applied rests on a scoped_edit critique. The components guide, grammar and steering note never mention apply_structured_edit; the directives guide recommends it and points to two skills that don't mention it.",
  "why": "A targeted edit that opens repair-design or review.md is pulled back into the slow path.",
  "groups": [
   {"label": "Follow-up routine (system prompt)", "refs": [
     ("A1", "Make the change with apply_structured_edit"),
     ("A1", "do not rewrite or re-validate creative-direction.json"),
     ("A1", "Do not write critique.json or round notes")]},
   {"label": "repair-design skill", "refs": [
     ("D5", "or an existing design needs a scoped edit"),
     ("D5", "Use compile_dsl_block with modify lines"),
     ("D5", "Keep the shared creative direction current"),
     ("D5", "Record the repair delta once")]},
   {"label": "Review guide and tools", "refs": [
     ("E4", "scoped_edit requires a seeded validated intent=edit"),
     ("E4", "scope=\"scoped_edit\" may review only"),
     ("B3", "Write the current review to the active round")]},
   {"label": "Where apply_structured_edit is missing or misreferenced", "refs": [
     ("E2", "Author through compile_dsl_block"), ("F1", "1. Continuation"),
     ("F2", "prefer the tool apply_structured_edit"), ("D6", "Use only tools registered"),
     ("G3", "Once the page has content")]}]},
 {"id": "I6", "topic": "ASK", "severity": "medium",
  "title": "Five different policies on when to ask the user",
  "what": "The scene prompt says infer from a short request and never make the user write copy. The framework says ask the minimum follow-up; its memory wrapper says 'it is preferred for you to ask … don't assume anything'. The clarification tool says ask only as an opening move and points to a skill that isn't delivered. The brand-kit guides say ask for missing brand facts or ask for kit generation, which the agent cannot do.",
  "why": "The agent can justify asking or not asking from text it was given on the same turn.",
  "groups": [
   {"label": "Infer, don't ask", "refs": [
     ("A1", "Do not make the user provide a headline"), ("D1", "Do not ask the user to become the copywriter"),
     ("D1", "ask only for a missing decision")]},
   {"label": "Ask", "refs": [
     ("A1", "If you genuinely cannot tell"), ("A5", "ask only the minimum followup"),
     ("A6", "It is preferred for you to ask"), ("F9", "ask for missing brand facts"),
     ("F9", "ask for Brand Kit validation")]},
   {"label": "The clarification tool", "refs": [
     ("B3", "Ask the user up to FOUR"), ("B3", "Ask ONLY for decision-critical"),
     ("B3", "Read the clarify-design-brief skill")]}]},
 {"id": "I7", "topic": "READING", "severity": "medium",
  "title": "Six instructions on how much to read",
  "what": "One line says follow each file to its end; the framework says pass limit=1000; the read_file tool says scan 100 lines first and 'speculatively read multiple files'; ls says list before every read. The follow-up routine says read only what the request needs, and the context block says the pinned guides are already inline. Meanwhile pointer skills tell the agent to read the components guide that is already pasted into its prompt.",
  "why": "Reading is where follow-up turns lost most of their time and tokens.",
  "groups": [
   {"label": "Read more", "refs": [
     ("A5", "Pass limit=1000"), ("B1", "speculatively read multiple files"),
     ("B1", "You should almost ALWAYS use this tool"), ("A5", "When in doubt, check if a skill exists"),
     ("A2", "follow read_file's continuation offsets")]},
   {"label": "Read less", "refs": [
     ("A1", "Read only the skills, guides and files this request needs"),
     ("A4", "Reuse them instead of hunting"), ("A4", "do not go read these again")]},
   {"label": "Asked to re-read what is already inline", "refs": [
     ("A1", "read reference guides and the checked DSL grammar"), ("D3", "Read the validated creative-direction.json"),
     ("D9", "Read components.md for native text"), ("A3", "Read {workspace}/ad-assets.md")]}]},
 {"id": "I8", "topic": "TOOLS", "severity": "medium",
  "title": "Broken references and impossible instructions",
  "what": "Text that points at files, tools or permissions the scene agent does not have.",
  "why": "Each one costs a failed call or leaves a rule the agent cannot follow.",
  "groups": [
   {"label": "Points at files not delivered to the scene agent", "refs": [
     ("B3", "Read the clarify-design-brief skill"), ("F3", "Pair case(upper)"), ("F3", "Rules of thumb"),
     ("F3", "must sit on a scrim"), ("F9", "Approved kits are stricter"), ("F10", "skills/print-bleed-marks")]},
   {"label": "Points at tools or abilities it lacks", "refs": [
     ("A6", "call edit_file to update memory"), ("A2", "NEVER batch"),
     ("F9", "generate_brand_kit"), ("F9", "generate a draft kit when the user gives"),
     ("B2", "asset(action='use_brand_asset'")]},
   {"label": "Cross-reference that says the opposite", "refs": [
     ("F2", "prefer the tool apply_structured_edit")]}]},
 {"id": "I9", "topic": "MULTIAGENT", "severity": "low",
  "title": "Leftovers: helper agents, test probes and evaluation wording",
  "what": "Text written for the old three-agent setup, for test runs, or for the evaluation harness, still shipped to every solo production turn.",
  "why": "Noise the agent has to read and decide to ignore; some of it changes behaviour (the review profile floor).",
  "groups": [
   {"label": "Helper-agent leftovers", "refs": [
     ("C1", "when the configured runtime delegates"), ("D1", "When delegating"), ("D6", "Delegate only when"),
     ("F11", "Feedback To The Author"), ("F10", "The visual reviewer should reject")]},
   {"label": "Test probes inside skills", "refs": [
     ("D15", "Probe"), ("D16", "Probe"), ("D17", "Probe \"Make an ad about"), ("D17", "Probe \"Make a useful ad"),
     ("D18", "Probe \"Make an ad for our trial"), ("D18", "Probe \"Promote our webinar"), ("E4", "The earlier controls")]},
   {"label": "Evaluation wording on production turns", "refs": [
     ("H1", "Caller-selected native-copy review"), ("H1", "explicit internal evaluation condition"),
     ("E4", "When a caller-selected native_copy_review_profile")]},
   {"label": "Generic framework text", "refs": [
     ("A5", "For monitoring or alerting requests"), ("A5", "When to Use Skills"), ("A6", "When to update / not update"),
     ("A5", "When you finish all work"), ("B1", "Use this tool to create and manage")]}]},
 {"id": "I10", "topic": "LAYOUT", "severity": "medium",
  "title": "Specific rules that contradict each other",
  "what": "Smaller, concrete contradictions between guides.",
  "why": "Each is a coin-flip for the agent.",
  "groups": [
   {"label": "Scrim required vs not", "refs": [("F3", "must sit on a scrim"), ("E6", "no scrim or fixed frame pattern")]},
   {"label": "Type ratios", "refs": [("F3", "Rules of thumb"), ("E2", "No fixed width, line count, type ratio")]},
   {"label": "Preferred structure", "refs": [("F7", "Preferred generated structure"), ("F5", "Prefer systematic structure"),
     ("E2", "no full-page skeleton is binding"), ("E2", "Components are reusable mechanics")]},
   {"label": "Font-size floor", "refs": [("E4", "There is no universal font-size threshold"), ("H1", "every native text fragment must meet")]},
   {"label": "CTA example", "refs": [("F3", "Book a Demo"), ("D1", "Do not default every creative to a pill")]},
   {"label": "Inter", "refs": [("F8", "Defaulting everything to Inter"), ("F8", "never a risk")]},
   {"label": "Who the agent is / how a turn ends", "refs": [("A1", "You are the design agent"), ("A5", "You are a deep agent"),
     ("A1", "Unresolved deviations remain drafts"), ("A5", "When you finish all work")]},
   {"label": "What counts as instructions", "refs": [("G2", "DELEGATION BRIEF"), ("A6", "Treat it as reference material")]}]},
 {"id": "I11", "topic": "ROUTINE", "severity": "medium",
  "title": "The same rule in three to six places",
  "what": "Rules repeated across the system prompt, the operating note, skills, guides and tool descriptions, often with slightly different wording.",
  "why": "Every copy costs tokens on every turn, and any edit to one copy leaves the others disagreeing.",
  "groups": [
   {"label": "Write and validate the direction (5)", "refs": [("A1", "Write creative-direction.json using"), ("C1", "The canonical direction is"),
     ("D1", "Write creative-direction.json using"), ("E1", "Write one compact JSON record"), ("D3", "Compile real copy")]},
   {"label": "Page-only logo preparation (5)", "refs": [("A1", "allow page-only source preparation"), ("C1", "Page-only preparation"),
     ("D14", "On a pageless scene"), ("E1", "For a required authentic target logo"), ("E2", "Page before spend")]},
   {"label": "New imagery needs generation (6)", "refs": [("A1", "A request for new imagery needs"), ("D1", "If the user asks for new imagery"),
     ("D9", "Start with the request's imagery requirement"), ("E2", "Type-only is a valid finished direction"),
     ("E3", "For a creation or change request that asks for new imagery"), ("Z1", "Requested new artwork needs a real inspected output")]},
   {"label": "CTA (5+)", "refs": [("D1", "For a CTA, decide"), ("D13", "CTA presence follows"), ("D14", "For a no-CTA request"),
     ("E2", "If the direction includes a CTA"), ("E4", "A missing CTA is not a defect")]},
   {"label": "Logo fetching (2 full copies)", "refs": [("A2", "ANOTHER COMPANY'S LOGO IS FETCHED"), ("B4", "Use this whenever the design shows")]},
   {"label": "Review profile floor (4)", "refs": [("E2", "The diagnostic resolved_font_size"), ("E4", "When a caller-selected native_copy_review_profile"),
     ("E5", "Direction validation may report"), ("H1", "every native text fragment must meet")]},
   {"label": "Your message, three times", "refs": [("G1", "scene_summary"), ("H1", "Design turn brief"), ("H5", "turn_request")]},
   {"label": "Published-ad description, twice", "refs": [("A4", "It is context, not a rule"), ("H3", "It is context, not a rule")]}]},
]

out = []
for issue in ISSUES:
    groups = [{"label": g["label"], "rows": [find(s, t) for s, t in g["refs"]]} for g in issue["groups"]]
    out.append({**{k: v for k, v in issue.items() if k != "groups"}, "groups": groups})
(HERE / "issues.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(len(out), "issues,", sum(len(g["rows"]) for i in out for g in i["groups"]), "row refs")
