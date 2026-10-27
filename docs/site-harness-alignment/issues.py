"""Curated conflict groups over the ledger, one family at a time. Each ref is (source_id, substring
of the row text); the build fails loudly if a ref matches no row or more than one row of that source.
Family 1 (page argument): what kind of page, for whom, what it argues, how long, and what the visitor does next."""
import json, sys
from pathlib import Path

HERE = Path(__file__).parent
ROWS = [json.loads(l) for f in sorted((HERE / "ledger").glob("*.jsonl")) for l in open(f)]

def find(sid, sub):
    hits = [r["id"] for r in ROWS if r["id"].rsplit("-", 1)[0] == sid and sub.lower() in r["text"].lower()]
    exact = [r["id"] for r in ROWS if r["id"].rsplit("-", 1)[0] == sid and r["text"].strip().lower() == sub.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    if len(hits) != 1:
        sys.exit(f"ref ({sid!r}, {sub!r}) matched {hits}")
    return hits[0]

ISSUES = [
 {"id": "P1", "family": 1, "topic": "KIND", "severity": "high", "status": "RULED 2026-10-27 (R1, R1.1–R1.4)",
  "title": "The site agent is told every page is for one named account",
  "what": "The system prompt's first line, the only argument skill and its final check all assume one company and one reader. A campaign page reaches the agent with the artifact's title standing in for the account name and a research file that says 'no written research for this account yet'. Nothing names the page kind; only the Head of ABM's brief can say it. The legacy skills cover six kinds: one account, one person, a few accounts, a whole segment, an event, a product page. The site's own header rules already know about 'a site for several accounts'.",
  "why": "Founder ruling R1 (2026-10-27): the site agent must handle every kind of landing page. Still open: how the page kind reaches the agent, and which kinds it supports (see P10 for pages about one person).",
  "groups": [
   {"label": "Site: one named account", "refs": [
     ("A1", "You build landing pages for one named account"), ("D1", "a landing page for one named account (a 1:1 page)"),
     ("D1", "A 1:1 page is written for one company"), ("D1", "Audience dilution"), ("D1", "Swap test"),
     ("H1", "There is no written research for this account yet")]},
   {"label": "Site: the few places a group is mentioned", "refs": [
     ("D2", "On a site for several accounts"), ("D2", "or the site is for several accounts"), ("D2", "Use it only on a site made for several accounts")]},
   {"label": "Legacy candidates: every page kind", "refs": [
     ("L1", "Use when creating a campaign, event, product or account landing page"),
     ("L3", "to choose the actual unit of relevance"),
     ("L3b", "Select the supported capability that matters to the supplied team"),
     ("L3b", "Use a documented shared problem"), ("L3b", "Explain an evidenced product capability for the defined audience"),
     ("L3b", "Explain the real event's value"), ("L3b", "Follow product purpose, traffic and buyer questions"),
     ("L3b", "For every mode, state the visitor's job")]}]},

 {"id": "P2", "family": 1, "topic": "ARGUMENT", "severity": "high", "status": "RULED 2026-10-27 (R2.1–R2.4)",
  "title": "The message plan only fits a researched account",
  "ruled": "R2.1–R2.4",
  "what": "The site's plan block asks for one insight 'in the account's own words' and two or three priorities 'tied to the research'. A campaign page, an event or a page with no research has nothing to put there. The legacy skills plan from the visitor instead: where they arrive from, what they already know (awareness stage), what single action closes the decision, which argument pattern fits, and a reader → context → mechanism → application → proof → action chain.",
  "why": "This decides what the agent writes in plan.md before anything else, for every page kind.",
  "groups": [
   {"label": "Site: the message plan", "refs": [
     ("D1", "Before you build or write any visible words"), ("D1", "**Reader:**"), ("D1", "**Insight:**"),
     ("D1", "**Priorities:**"), ("D1", "**Offer and action:**"), ("D1", "**Proof:** the case studies"), ("D1", "**Sections:**"), ("D1", "**Left out:**"),
     ("D1", "An insight is something the account has said or done")]},
   {"label": "Legacy candidates: plan from the visitor", "refs": [
     ("L1b", "Construct the argument first"), ("L1b", "establish five things"), ("L1b", "stages of awareness"),
     ("L1b", "Traffic source is your best clue"), ("L1b", "A pattern is a theory of why this visitor converts"),
     ("L3a", "Write one compact chain in the plan"), ("L2", "Write the supported account context → seller mechanism"),
     ("L1", "Establish the arriving audience and traffic context")]}]},

 {"id": "P3", "family": 1, "topic": "STRUCTURE", "severity": "high", "status": "RULED 2026-10-27 (R3.1–R3.4)",
  "title": "Five sections and 600 words, or as long as the decision needs?",
  "what": "The site sets a ceiling: up to five sections, usually five, rarely more than 600 words, each with a word budget. The legacy skills say length follows the decision: seven sections for a considered enterprise purchase, three for a giveaway, never pad and never cut what the decision needs; their five questions are 'responsibilities, not mandatory sections'.",
  "why": "The 10-26 Pallet production page stopped at 5 sections and about 440 words, and read as shallow.",
  "groups": [
   {"label": "Site: a fixed shape", "refs": [
     ("D1", "**Sections:** up to five"), ("D1", "The usual shape is five sections"), ("D1", "stays within its word budget"),
     ("D1", "Short beats complete")]},
   {"label": "Legacy candidates: length follows the decision", "refs": [
     ("L1b", "Page length follows decision complexity"), ("L1b", "not guaranteed conversion lifts or universal numerical rules"),
     ("L1b", "Shell choice is independent of page LENGTH"), ("L3a", "content responsibilities, not mandatory sections"),
     ("L5", "This is a reasoning sequence, not a required section order or count")]},
   {"label": "Both agree: one question per section", "refs": [
     ("D1", "**Hero:**"), ("L1b", "Each section must answer exactly one visitor question"), ("L1b", "Order the survivors by the awareness stage")]}]},

 {"id": "P4", "family": 1, "topic": "SUBSTANCE", "severity": "high", "status": "RULED 2026-10-27 (R4.1–R4.7)",
  "title": "How much must a page explain, and may substance outgrow a clone's slots?",
  "what": "The site asks for short, clear pages and rewrites that match the original slot ('a slot that held six words wants about six words back'). Its only substance checks are 'feature dumping' and the swap test. The legacy decision-material skill asks for a concrete worked application (trigger, product action, handoff), a decision map whose every item shows up visibly on the page, and says a shortage of slots is never a reason to drop the substance.",
  "why": "This is the 'thin page' problem: the site agent fills slots at the original length, so the page carries little the buyer can use.",
  "groups": [
   {"label": "Site: short, slot-sized", "refs": [
     ("D1", "Clear beats clever. Short beats complete"), ("D1", "A slot that held six words"), ("D1", "Feature dumping"), ("D1", "Swap test")]},
   {"label": "Legacy candidates: decision material", "refs": [
     ("L5", "Research is an input to an argument"), ("L5", "A shortage of slots is not a reason"),
     ("L5", "How would the work change?"), ("L5", "Supply a concrete worked application"), ("L5", "**Utility:**"),
     ("L5", "The added depth comes from a concrete task"),
     ("L3a", "For each retained insight, record the visible explanation"), ("L3a", "Why this is relevant here"),
     ("L1b", "research must change the visible explanation"), ("L3", "Without target research, write an invitation")]}]},

 {"id": "P5", "family": 1, "topic": "ACTION", "severity": "high", "status": "RULED 2026-10-27 (R5.1–R5.5)",
  "title": "One destination for every button, or one primary action plus useful secondary links?",
  "what": "The site sends every button, including the header's, to the one destination the brief names, and flags any second destination as 'CTA competition'. The legacy skills choose the action from the reader's decision (explore, compare, register, buy), allow relevant secondary resources, place actions at decision points rather than in every band, and warn that a booking link or the seller's homepage button does not decide the page's purpose.",
  "why": "Founder 2026-10-18: the one-destination rule is guidance only. The question is what the guidance should say, especially for segment, event and product pages.",
  "groups": [
   {"label": "Site: one destination", "refs": [
     ("D1", "**Offer and action:**"), ("D1", "goes to the same checked link"), ("D1", "CTA competition"),
     ("D2", "Every button goes to the one destination"), ("D2", "Point it at the one destination"), ("D2", "Never on a site for one account"), ("D6", "One button, with")]},
   {"label": "Legacy candidates: action from the decision", "refs": [
     ("L1a", "Select the page's purpose before copying its source CTA"), ("L1a", "Understand relevance"),
     ("L1a", "One page can have a coherent primary action"), ("L1b", "**One primary conversion action.**"),
     ("L1b", "Place actions at natural decision points"), ("L1a", "Do not fix a mismatch merely by relabeling"),
     ("L5", "The existence of a booking URL"), ("L1", "do not invent an offer, default to a pilot/demo")]}]},

 {"id": "P6", "family": 1, "topic": "IDENTITY", "severity": "medium", "status": "RULED 2026-10-27 (R6.1–R6.4)",
  "title": "Where do the account's name and logo go?",
  "what": "The site puts the account in the header: 'Prepared for <account>' and the account's logo beside the seller's, and forbids the account's logo anywhere else. The legacy skills say the opposite: target identity belongs in the opening content (an eyebrow, account bar or lockup above the headline), never as a navigation item. For segment and product pages the legacy skills say no account markers at all.",
  "why": "Every site today carries 'Prepared for …' in the header; a segment or product page has no single account to name.",
  "groups": [
   {"label": "Site: in the header", "refs": [
     ("D2", "write the account's full name after \"Prepared for\""), ("D2", "a line for the account and one button"),
     ("D3", "The account's logo goes in the header"), ("D3", "Never put the account's logo anywhere else"),
     ("D4", "On mobile, the header still shows the account's name"), ("D6", "The account's logo and line")]},
   {"label": "Legacy candidates: in the opening content, not the navigation", "refs": [
     ("L1b", "Target identity belongs in the opening content"), ("L2", "Target identity belongs in opening content"),
     ("L3c", "Keep seller and target identity independently placeable")]},
   {"label": "Legacy candidates: no markers on shared pages", "refs": [
     ("L3b", "no invented per-visitor facts or account markers"), ("L3b", "Neither an ABM identity treatment nor a booking dialog")]}]},

 {"id": "P7", "family": 1, "topic": "SHELL", "severity": "medium", "status": "RULED 2026-10-27 (R7.1–R7.5)",
  "title": "A fixed header and footer, or a choice from the page's traffic and trust?",
  "what": "The site starts every page from the brand's account header template (or a plain header) and the plain footer, and uses the seller's own footer only when asked. The legacy skills make it a judgement each time: keep the seller's real navigation when the visitor will vet the seller or forward the page, strip it to a minimal campaign shell when the page serves one offer from one campaign.",
  "why": "Product and segment pages often need the seller's real navigation for trust; a 1:1 outbound page usually does not.",
  "groups": [
   {"label": "Site: fixed templates", "refs": [
     ("D2", "Use \"Header template, one page\""), ("D2", "Every site starts with the plain footer"), ("D6", "Keep it short. A header is one row")]},
   {"label": "Legacy candidates: decide per page", "refs": [
     ("L1", "Choose native navigation or available campaign chrome"), ("L1b", "Choose the amount of chrome from the page's task"),
     ("L1b", "the native shell almost always stays"), ("L1b", "Account-personalized (ABM) pages get no automatic answer"),
     ("L3b", "Follow product purpose, traffic and buyer questions")]}]},

 {"id": "P8", "family": 1, "topic": "PLAN", "severity": "medium", "status": "RULED 2026-10-27 (R8: no change)",
  "title": "Is the brief binding, or an agent's summary to read critically?",
  "what": "The site treats the brief's goal, reader and offer as fixed and its facts, proof and structure as suggestions. The legacy skills say a delegation brief is an agent-authored summary: quote the person's actual words, keep user requirements apart from working choices, and do not read a pilot, demo or section count into a short request. The site agent does receive the person's own message (last, after the brief and the session history), and the brief's wrapper already calls it 'an agent-authored summary' — which contradicts the system prompt's 'keep to those'.",
  "why": "When the brief picks a weak offer or the wrong page kind, the site agent has no permission to question it.",
  "groups": [
   {"label": "Site: the brief sets goal, reader, offer", "refs": [
     ("A1", "The brief sets the goal, the reader and the offer"), ("D1", "The brief may suggest a proof or a structure"),
     ("H1", "the delegation brief, then this artifact's line")]},
   {"label": "Site message wrapper: the brief is a summary; the person's message comes last", "refs": [
     ("G1", "This is an agent-authored summary"), ("G1", "the person's own message last")]},
   {"label": "Legacy candidates: the person's words outrank the brief", "refs": [
     ("L2", "Quote the actual user message, not the delegation brief"), ("L6", "A delegation brief is an agent-authored summary"),
     ("L6", "A simple request for an account page does not specify a pilot"), ("L2", "A short account-page request does not mandate"),
     ("L6", "an explicit user offer cannot silently become a different one")]}]},

 {"id": "P9", "family": 1, "topic": "ASK", "severity": "medium", "status": "RULED 2026-10-27 (R9.1–R9.4)",
  "title": "When may the agent ask before building a new page?",
  "what": "The site agent may only ask on an edit, when the request names something that is not on the page. The legacy skills allow one consequential question before a costly build when the purpose would change the argument, but otherwise make reversible assumptions and say so; a plan is never an approval gate. The site agent has no clarification tool today.",
  "why": "A campaign request with no clear reader, offer or destination is built on a guess.",
  "groups": [
   {"label": "Site: ask only on edits", "refs": [("A1", "say so and ask before adding anything")]},
   {"label": "Legacy candidates: one question before a costly build", "refs": [
     ("L1a", "ask one consequential question before a costly build"), ("L1b", "Ask only for a missing decision that changes the argument"),
     ("L6", "never an approval gate")]}]},

 {"id": "P10", "family": 1, "topic": "PEOPLE", "severity": "medium", "status": "RULED 2026-10-27 (R10.1–R10.4)",
  "title": "Pages for one person",
  "what": "The site forbids naming or describing anyone at the account, and its workspace carries no contact research. The legacy skills support a page for one buying-committee member: resolve the person, use their own sourced professional criterion, change the material compared with the account page, keep their name discreet, never use private or sensitive facets.",
  "why": "Decides whether 'contact page' is one of the page kinds in P1.",
  "groups": [
   {"label": "Site: never name people", "refs": [
     ("A1", "Never name people at the account"), ("D1", "Never name or describe individual people")]},
   {"label": "Legacy candidates: contact pages", "refs": [
     ("L4", "targets a named professional or buying-committee member"), ("L4", "Prefer the person's own eligible"),
     ("L4", "something substantive must change"), ("L4", "Their name need not be the headline"),
     ("L3a", "Read **contacts**"), ("L3b", "Tie the account argument to that person's"), ("L4", "Do not use private or sensitive interests")]}]},

 {"id": "P11", "family": 1, "topic": "STRUCTURE", "severity": "low", "status": "RULED 2026-10-27 (R11.1–R11.4)",
  "title": "Video sections: remove them, or lead with them?",
  "what": "The site lists brand videos among the sections to remove. The legacy argument patterns include a video-led page, as long as the headline states the promise and the page works without pressing play.",
  "why": "Pallet's homepage leads with video; the 10-26 page dropped all of it. How the video is carried belongs to the imagery family; whether it may stay is decided here.",
  "groups": [
   {"label": "Site", "refs": [("D1", "Remove sections that do not help this reader decide"), ("D5", "If the original shows a video")]},
   {"label": "Legacy candidates", "refs": [("L1b", "**Video-led**")]}]},

 {"id": "P12", "family": 1, "topic": "SCOPE", "severity": "low", "status": "RULED 2026-10-27 (R12.1–R12.3)",
  "title": "Re-aiming an existing page at a new audience or offer",
  "what": "On an existing page the site changes only what was asked. The legacy skills cover changing a page's audience, offer or argument as its own case, where sections that no longer answer a question may be removed, while a scoped edit keeps everything else.",
  "why": "'Make this page work for the logistics segment' is neither a small edit nor a new page.",
  "groups": [
   {"label": "Site", "refs": [("A1", "Change only what was asked")]},
   {"label": "Legacy candidates", "refs": [
     ("L1", "changing an existing page's audience, offer or argument"), ("L1b", "When a whole-page campaign adaptation authorizes"),
     ("L1", "Adding account markers is not a reason")]}]},

 {"id": "P13", "family": 1, "topic": "STRUCTURE", "severity": "low", "status": "RULED 2026-10-27 (R13.1–R13.4)",
  "title": "Several directions for the same page",
  "what": "The site has no rule for a request for several concepts or layouts. The legacy skill plans one row per direction, keeps brand invariants fixed, says three centred heroes with different headlines are still one composition, and reports honestly when only one page is finished.",
  "why": "A gap, not a conflict.",
  "groups": [
   {"label": "Legacy candidates", "refs": [
     ("L1c", "For each requested page, write one row"), ("L1c", "For argument alternatives, give each page"),
     ("L1c", "For layout-only alternatives"), ("L1c", "Three centered heroes")]}]},
 {"id": "W1", "family": 2, "topic": "SOURCING", "severity": "high", "status": "RULED 2026-10-28 (W1.1–W1.5)",
  "title": "Which words and facts may the page use?",
  "what": "The site allows only three sources for a number or a quote: the research, the seller's files, a page the agent fetched. It does not name the seller's own captured sections, although every clone keeps the seller's published words, stats, customer names and quotes unless changed; nor the brief's facts, which the Head of ABM sends with their sources; nor the audience context R1.3a now allows from web searches. The legacy skills treat the clone's own copy and proof strips as captured evidence, and supplied facts as usable at their stated scope without upgrading them to verified.",
  "why": "Under the site rule, keeping a clone's stat strip or testimonial is technically unsupported, and so is a fact the brief carries.",
  "cases": "One-to-one leans on account research; general, event and product pages lean on the seller's files and clones; R1.3a adds audience context for untagged pages.",
  "groups": [
   {"label": "Site: three sources", "refs": [
     ("A1", "Use only the facts in your workspace"), ("B1", "Use it before you put a number or a quote"),
     ("D1", "Open the page with `fetch_page`"), ("D1", "Use only pages the seller published"),
     ("A1", "for the seller's own published case studies and other pages")]},
   {"label": "Site data: what the clones already carry", "refs": [("H3", "Other visible text (no slot)")]},
   {"label": "Legacy: captured copy and supplied facts are evidence at their scope", "refs": [
     ("L7a", "The clone's original copy is evidence"), ("L1b", "what the cloned page itself already carries"),
     ("L6", "Never invent named customers"), ("L1b", "Supplied facts can be used as supplied assertions"),
     ("L3c", "Use source scope faithfully")]}]},

 {"id": "W2", "family": 2, "topic": "CLAIMS", "severity": "high", "status": "RULED 2026-10-28 (W2.1–W2.5)",
  "title": "May the page say what the product 'could' do for this reader?",
  "what": "Both sides use a claim ladder from product fact to forecast, and both forbid a forecast. They differ on the step below it. The site allows 'what it could mean for this account (\"could\")'. The legacy one-account shape uses 'would'. The legacy copy skill says could, may and helps still assert an outcome and supply no evidence; its fourth step is an invitation such as 'Explore how usage-based billing fits your expansion plans', a capability joined to the reader's task with no invented outcome.",
  "why": "This decides how every benefit sentence on a personalised page is phrased.",
  "cases": "Mainly one-to-one, one-to-few and contact pages; general and product pages speak about the audience, not one account.",
  "groups": [
   {"label": "Site: 'could' for what it might mean", "refs": [
     ("D1", "Keep claims at the strength the evidence allows"), ("D1", "Use \"will\" only for what certainly happens")]},
   {"label": "Legacy: 'would' in the one-account shape", "refs": [("L3a", "This is a proposal, so it \"would\" help")]},
   {"label": "Legacy: no outcome without evidence, whatever the verb", "refs": [
     ("L7a", "2. Capability"), ("L7a", "**Could / may / helps** still assert"), ("L3c", "adding could, helps or up to is not proof"),
     ("L7a", "the transformation-word test")]},
   {"label": "Both: the same checks", "refs": [("D1", "Benefit inflation"), ("D1", "Metric mutation")]}]},

 {"id": "W3", "family": 2, "topic": "CLAIMS", "severity": "high", "status": "RULED 2026-10-28 (W3.1–W3.4)",
  "title": "A number that needs a condition: drop it, or keep the condition beside it?",
  "what": "The site drops any figure that needs a condition to be true ('leave it out rather than explain it'). The legacy skills keep the number with its subject, unit, time window and material conditions in the same visible sentence. Both agree that naming whose result it is is the qualification, with no disclaimer sentence.",
  "why": "The site rule removes strong but conditional proof; the legacy rule makes sentences longer, against R4.7's 20-word paragraphs.",
  "cases": "Proof-heavy cases (product campaign, general campaign) feel this most.",
  "groups": [
   {"label": "Site: drop it", "refs": [("D1", "If a figure needs a condition to be true"), ("D1", "Use at most one or two of their own figures")]},
   {"label": "Legacy: keep the condition in the sentence", "refs": [
     ("L7a", "Name the customer and give the result as theirs"), ("L7a", "A number keeps its metric, subject, comparator"),
     ("L3c", "Retain quantitative context in visible copy")]},
   {"label": "Both: attribution is the qualification", "refs": [
     ("D1", "Say whose result it is in the kicker"), ("L1b", "analogous proof stays attributed"), ("D1", "Unattributed proof")]}]},

 {"id": "W4", "family": 2, "topic": "OFFPAGE", "severity": "medium", "status": "RULED 2026-10-28 (W4.1–W4.6)",
  "title": "What never reaches the page, and do product limits count as caveats?",
  "what": "Both sides keep notes off the page: the brief's Notes for Design, the research's Watch-outs and Context only, approach notes, claim ids, caveats and strategy. The legacy skills add three things: never lift the brief's or research's sentences onto the page (write your own); a test for a leaked note ('a sentence that says what the page is not… is almost always a note that leaked'); and an exception — genuine product limits and proof conditions that affect the reader's choice stay visible. The site says caveats go to plan.md, never the page.",
  "why": "The rule is repeated in eight places today; the product-limits exception is the one real disagreement.",
  "cases": "",
  "groups": [
   {"label": "Site: off the page", "refs": [
     ("A1", "The brief's \"Notes for Design\" are for you"), ("A1", "The \"Watch-outs\" and \"Context only\" sections"),
     ("D1", "Never put file names, line codes or claim ids"), ("D1", "The research's notes on how to approach"),
     ("D1", "Notes, caveats, strategy and reasons go in plan.md"), ("H2", "(background only, never on the page)")]},
   {"label": "Legacy: write your own words; spot leaked notes", "refs": [
     ("L7a", "Do not lift sentences from the brief or the research"), ("L7a", "A sentence that says what the page is not"),
     ("L7b", "its analyst headlines and internal notes are not page copy"), ("L3a", "Maintain two outputs")]},
   {"label": "Legacy: genuine limits stay visible", "refs": [
     ("L7b", "Retain genuine product limits and proof conditions"), ("L3a", "Keep material proof conditions and genuine product limits visible"),
     ("L5", "retain material product limitations")]}]},

 {"id": "W5", "family": 2, "topic": "EVIDENCE", "severity": "medium", "status": "RULED 2026-10-28 (W5.1–W5.4)",
  "title": "Reading research: facts, inferences and the research lane's own arguments",
  "what": "The research files tag statements as (inference), (quote), (qualified) or (gap), with notes, and claims.md includes value-narrative claims that are the research lane's own argument for a persona. The site prompt never says what these mean. The legacy skills say: separate sourced facts from analyst interpretations — job openings do not prove a staffing problem, an initiative does not prove budget, a technology fingerprint does not prove an integration; a report saying 'verified' does not make it so.",
  "why": "An inference written up as a fact is the fastest way to a false claim about the account.",
  "cases": "One-to-one, one-to-few and contact pages (the cases with research).",
  "groups": [
   {"label": "Site data: what the research files contain", "refs": [
     ("H2", "tag is \"(inference) \""), ("H2", "Says: {argument}"), ("H2", "held back by a real rule"),
     ("A1", "For a number or a quote from the research, check its claim")]},
   {"label": "Legacy: facts versus interpretations", "refs": [
     ("L7b", "Separate sourced facts from analyst interpretations"), ("L3a", "Separate source facts from analyst interpretations"),
     ("L3a", "Job openings do not establish staffing failure"), ("L3a", "A report's word \"verified\"")]}]},

 {"id": "W6", "family": 2, "topic": "SOURCING", "severity": "medium", "status": "RULED 2026-10-28 (W6.1–W6.4)",
  "title": "How much evidence bookkeeping goes into plan.md?",
  "what": "The site's plan lists proof as case studies with links. The legacy skills ask for an evidence map: every prominent factual sentence paired in the plan with its supporting excerpt, subject, units, time window and status, and 'never fill it from memory'.",
  "why": "More bookkeeping catches mutated numbers; it also costs time on every page.",
  "cases": "",
  "groups": [
   {"label": "Site", "refs": [("D1", "**Proof:** the case studies")]},
   {"label": "Legacy: an evidence map", "refs": [
     ("L7", "Before you write a prominent fact or outcome"), ("L7b", "pair each material factual sentence"),
     ("L3c", "For each factual claim keep the actual value"), ("L6", "Record accessible values/excerpts")]}]},

 {"id": "W7", "family": 2, "topic": "VOICE", "severity": "medium", "status": "RULED 2026-10-28 (W7.1–W7.5)",
  "title": "Whose voice, and whose words?",
  "what": "The site asks the agent to write like the clone's author and in the reader's words, with at most one or two of the account's own figures. The legacy skills rank voice sources — a brand voice or style guide when one exists, then the brand card, then the clone's own copy — and allow the reader's own phrases verbatim ('recognition is persuasion'). The site has no rule for a voice document in seller/.",
  "why": "The seller's pinned documents may hold a voice guide the agent never consults.",
  "cases": "Event and product pages may follow the ad's or invite's own wording (conversion scent).",
  "groups": [
   {"label": "Site", "refs": [
     ("D1", "Write each rewrite like the same author"), ("D1", "Use the reader's words for their world"),
     ("D1", "Use their words. Use at most"), ("D1", "Investor pitch"), ("D1", "Jargon stacking")]},
   {"label": "Legacy", "refs": [
     ("L7a", "In order of authority"), ("L7a", "Seller capability language"), ("L7a", "you can use them verbatim"),
     ("L7", "Match the brand's observed voice")]}]},

 {"id": "W8", "family": 2, "topic": "COPY", "severity": "medium", "status": "RULED 2026-10-28 (W8.1–W8.4)",
  "title": "Concise statements, not slogans",
  "what": "R4.6 (no over-explaining) and R4.7 (no paragraph over 20 words) now set the length. The legacy skills warn the other way: do not shrink copy into slogans, write the explanation and not just headings and buttons, and cash out words like 'unlock' into something checkable. The two fit together if 'concise' means short specific statements, not short vague ones.",
  "why": "Family 1 left this to be reconciled here.",
  "cases": "",
  "groups": [
   {"label": "Site", "refs": [("D1", "Clear beats clever.")]},
   {"label": "Legacy", "refs": [
     ("L3a", "Do not shrink copy into slogans"), ("L7b", "Then write the explanation, not just headings and CTAs"),
     ("L7a", "Prefer specific, evidence-backed statements to platitudes"), ("L7a", "Short paragraphs, meaningful headings"),
     ("L7a", "the transformation-word test")]}]},

 {"id": "W9", "family": 2, "topic": "HEADLINE", "severity": "low", "status": "RULED 2026-10-28 (W9.1–W9.4)",
  "title": "Headlines",
  "what": "The site's hero rule and two checks (mystery box, redundant subheadline) agree with the legacy skills, which add five tests (one-read meaning, reader ownership, specificity, evidence, fit), a formula (outcome or system + reader context + qualifier), and 'product nouns and verbs, not category slogans, forced puns or repeated account names'.",
  "why": "Agreement; the question is how much of the legacy craft to bring over.",
  "cases": "",
  "groups": [
   {"label": "Site", "refs": [("D1", "**Hero:**"), ("D1", "Mystery-box headline"), ("D1", "Redundant subheadline")]},
   {"label": "Legacy", "refs": [("L7a", "Judge every headline on five things"), ("L7a", "A working headline formula"), ("L7b", "a concrete idea followed by mechanism/scope")]}]},

 {"id": "W10", "family": 2, "topic": "COPY", "severity": "low", "status": "RULED 2026-10-28 (W10.1–W10.6)",
  "title": "Buttons, forms and promises",
  "what": "Both say a button names what happens. The legacy skills add: two to five words, field labels as plain nouns, success and error copy, and never promise a response time, consent handling or delivery the page does not actually provide.",
  "why": "Small additions.",
  "cases": "Event pages: registration wording; product pages: the ad's offer.",
  "groups": [
   {"label": "Site", "refs": [("D1", "Generic CTA"), ("D1", "Form creep"), ("D1", "Every button says what happens")]},
   {"label": "Legacy", "refs": [("L7a", "Prefer a label describing **what the reader receives**"), ("L7a", "Field labels are plain nouns"), ("L7", "Never promise form delivery")]}]},

 {"id": "W11", "family": 2, "topic": "VOICE", "severity": "low", "status": "RULED 2026-10-28 (W11.1–W11.5)",
  "title": "Talking about the prospect",
  "what": "Both say: frame toward what improves, never tell them their setup is broken. The legacy skills add: never show buying-committee labels, and never describe the prospect's own product negatively (the Head of ABM's brief template already says this).",
  "why": "Small additions.",
  "cases": "One-to-one, one-to-few and contact pages.",
  "groups": [
   {"label": "Site", "refs": [("D1", "Say what stays and what improves"), ("D1", "Negative assumption"), ("D1", "False relationship")]},
   {"label": "Legacy", "refs": [("L7a", "Lead with the operating state the reader gains"), ("L7a", "never show buying-committee labels"), ("L7a", "\"Trusted by\" needs actual use")]}]},

 {"id": "W12", "family": 2, "topic": "COPY", "severity": "low", "status": "RULED 2026-10-28 (W12: no rule)",
  "title": "Wording the person asked for exactly",
  "what": "The site has no rule. The legacy skills keep wording the person asked for exactly (a headline, a tagline, a button), and when that wording claims something unsupported, they say so instead of silently rewriting it.",
  "why": "A gap.",
  "cases": "",
  "groups": [
   {"label": "Legacy", "refs": [("L7a", "The one exception is wording the user asked for exactly"), ("L7a", "Preserve supported exact copy")]}]},
 {"id": "M1", "family": 3, "topic": "MOTION", "severity": "high", "status": "RULED 2026-10-28 (M1.1–M1.6)",
  "title": "The seller's moving parts: copy them, rebuild them, or leave them still?",
  "what": "brand/brand.md tells the agent that the seller's videos, canvas and scripted animations 'need a script… Do not imitate them', and that nothing moves except the kit's buttons, links and cards ('write no transition or animation of your own'). That text predates two changes: published sites now run JavaScript (founder 2026-10-15), and R11.1 keeps the seller's ambient video. The live-site skill now lets a section run React effects (tabs, carousels, scroll reveals). Clone cards list images but not videos, so the agent cannot see a clone's video. The legacy motion skill uses a ladder: reuse the source's own CSS and media when it works; else a supported equivalent (tabs, carousel, accordion); else a custom-built component; else a compact still version with no dead space or dead controls — and every moving region needs a usable reduced-motion state.",
  "why": "This is half of why the 10-26 Pallet page lost all its motion; R11 decided what may stay, this decides how.",
  "cases": "Product and general campaign pages lean on the seller's motion most; one-to-one pages keep it as part of the seller's look.",
  "groups": [
   {"label": "Site data: brand.md motion text", "refs": [
     ("H4", "Do not imitate them"), ("H4", "write no transition or animation of your own"), ("H4", "nothing moves except the kit's buttons")]},
   {"label": "Site: what the agent can see and do", "refs": [
     ("H3", "each `<img src>` with its slot"), ("D7", "This site's published pages run your section's React code"),
     ("D7", "tabs, an accordion, a carousel"), ("D5", "If the original shows a video")]},
   {"label": "Legacy: the motion ladder", "refs": [
     ("L10", "Reuse supported source CSS/media when it survives custody"), ("L10", "1. Supported source reuse"),
     ("L10", "Choose a visible, usable reduced-motion state"), ("L10", "Do not introduce sound autoplay"),
     ("L10", "Never replay arbitrary source scripts")]}]},

 {"id": "M2", "family": 3, "topic": "GENERATE", "severity": "high", "status": "RULED 2026-10-28 (M2.1–M2.7)",
  "title": "When to generate an image, and how well",
  "what": "The site generates only as a last resort ('only when a section needs one and none of the brand's images fits'), only a scene or a mood, never anything presented as real, styled from one to three brand photos, one retry, else no image. The legacy web media skill agrees ('generation is optional… authentic reused imagery is a complete valid outcome'). The legacy generative-imagery skill, written mainly for ads, says the opposite: generation 'is not a fallback… it is one of your two hands' for atmosphere — and it carries real craft the site lacks: a five-question prompt (what, style, exact brand colours, composition with a calm area, what must not appear), describing the brand's own imagery in plain words, the test 'would the brand's own design team have made this?', and text on an image only over a calm area or a scrim.",
  "why": "Decides how often site pages carry generated imagery, and how good it is when they do.",
  "cases": "Pages with no account (general, event, product) have fewer authentic images to draw on.",
  "groups": [
   {"label": "Site: last resort, scene or mood only", "refs": [
     ("D3", "Generate an image only when a section needs one"), ("D3", "A generated image may show a scene or a mood"),
     ("D3", "To keep it in the brand's style"), ("D3", "Anything real comes only from these images"), ("D3", "If nothing fits and a generated image")]},
   {"label": "Legacy web: generation is optional", "refs": [
     ("L8", "Choose existing source imagery, a justified generated derivative"), ("L8", "Use **reuse** when an existing asset"),
     ("L8", "Never claim it was captured")]},
   {"label": "Legacy (ads): one of two hands, with prompt craft", "refs": [
     ("L11", "It is not a fallback for missing assets"), ("L11", "A strong prompt answers five questions"),
     ("L11", "The brand's existing imagery"), ("L11", "Text over any generated image gets a scrim"), ("L11", "That placeholder is not real imagery")]}]},

 {"id": "M3", "family": 3, "topic": "IMAGERY", "severity": "medium", "status": "RULED 2026-10-28 (M3.1–M3.3)",
  "title": "Keeping the seller's image composition",
  "what": "The site says keep a clone's layout, images and rhythm. The legacy skills spell out what that means for images: keep crop, focal point, transparency, corners already baked into the image, and layer order; separate what is inside an image from what the page adds (double rounding cuts controls; a panel behind a cut-out destroys it); never replace characteristic scenery or a photographic background with a flat colour because finding the asset was inconvenient.",
  "why": "Rebuilt sections and brand sections are where images get flattened or re-cropped.",
  "cases": "",
  "groups": [
   {"label": "Site", "refs": [("D1", "Keep its layout, images and rhythm")]},
   {"label": "Legacy", "refs": [
     ("L8", "Preserve what the source image means"), ("L8", "Reuse a suitable original. Preserve crop"),
     ("L8", "Separate what is **inside the image**"), ("L8", "A landscape hero replaced with a flat color")]}]},

 {"id": "M4", "family": 3, "topic": "PRODUCTUI", "severity": "medium", "status": "RULED 2026-10-28 (M4.0–M4.5)",
  "title": "Product screenshots that carry the story",
  "what": "The site has two lines: a screenshot must show what the copy says, and product screens are never generated. The legacy product-story skill adds: pair each screenshot with the task it shows and the explanation beside it; keep the brand background behind the interface and never cover the interface; keep the interface readable on a phone ('a surviving background with no UI is failure'); never edit its numbers or crop out the feature the copy describes; a product switcher is one linked component.",
  "why": "W8.3 (explain the actual product) depends on product visuals doing their job.",
  "cases": "Product and general campaign pages carry the most product imagery.",
  "groups": [
   {"label": "Site", "refs": [("D3", "Check that the image fits the words beside it"), ("D3", "Anything real comes only from these images")]},
   {"label": "Legacy", "refs": [
     ("L9", "For each demonstration write one short internal row"), ("L9", "branded background behind"),
     ("L9", "On phone, confirm the interface itself"), ("L8", "Keep product UI readable and recognizable"),
     ("L10", "Treat a product switcher as one linked component")]}]},

 {"id": "M5", "family": 3, "topic": "ASSETS", "severity": "medium", "status": "open",
  "title": "Which images a page may use, and finding them",
  "what": "Three site texts say images come only from brand/brand.md or generation ('the only images and logos a page may use'), while the images skill and two tool descriptions also allow the seller's uploads and earlier pages' images found with search_assets. The legacy skills add: state each image's role before using it; one empty search does not mean the brand has no imagery (try other words); if nothing fits, a smaller honest placement or no image.",
  "why": "An internal inconsistency in what the agent is told.",
  "cases": "",
  "groups": [
   {"label": "Site: brand.md or generated only", "refs": [
     ("D2", "Images come only from `brand/brand.md` or from `generate_image`"), ("D2", "An image slot takes a file"),
     ("H4", "the only images and logos a page may use"), ("D6", "images from brand/brand.md")]},
   {"label": "Site: search_assets images too", "refs": [
     ("D3", "The seller's other images (uploads"), ("B1", "files from brand/brand.md, images you generated, or images search_assets found"),
     ("B1", "Search the seller's images by what they show")]},
   {"label": "Legacy", "refs": [
     ("L8", "State each asset's role"), ("L8", "A failed semantic query may reflect poor labels"), ("L8", "If inadequate, choose in order")]}]},

 {"id": "M6", "family": 3, "topic": "ASSETS", "severity": "low", "status": "open",
  "title": "Image sharpness",
  "what": "The site has no rule beyond 'no broken image'. The legacy skill gives the arithmetic: an image painted 600 × 400 on a 2× screen needs 1200 × 800 real pixels; a better same-role source, a smaller honest placement, or no image beats a blurry one.",
  "why": "A gap.",
  "cases": "",
  "groups": [
   {"label": "Site", "refs": [("D4", "no broken image")]},
   {"label": "Legacy", "refs": [("L8", "For a raster painted at W by H")]}]},

 {"id": "M7", "family": 3, "topic": "LOGOS", "severity": "low", "status": "open",
  "title": "Logos",
  "what": "Mostly agreement: the site fetches the account's logo by domain, looks before placing, hides it when none is found, skips look-alike companies, and shows logos whole. The legacy skills add: tell a full lockup from a bare mark; pick the light or dark version for its background; when identity is unclear leave the logo out; never draw, recolour or generate a logo; don't repeat the seller's wordmark as proof.",
  "why": "Small additions; placement was ruled in R6.",
  "cases": "One-to-one, one-to-few and contact pages place the account's logo; others don't (R6.3).",
  "groups": [
   {"label": "Site", "refs": [
     ("D3", "If `brand/brand.md` has no logo for the account"), ("D3", "Leave out a logo of a company with the same"),
     ("H4", "shows a logo whole"), ("H4", "## The account's logo (header only)")]},
   {"label": "Legacy", "refs": [
     ("L8", "Distinguish a full wordmark/lockup"), ("L8", "returns proven family cells"), ("L8", "If identity is ambiguous")]}]},
]

out = []
for issue in ISSUES:
    groups = [{"label": g["label"], "rows": [find(s, t) for s, t in g["refs"]]} for g in issue["groups"]]
    out.append({**{k: v for k, v in issue.items() if k != "groups"}, "groups": groups})
(HERE / "issues.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(len(out), "issues,", sum(len(g["rows"]) for i in out for g in i["groups"]), "row refs")
