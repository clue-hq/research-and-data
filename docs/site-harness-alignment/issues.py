"""Curated conflict groups over the ledger, one family at a time. Each ref is (source_id, substring
of the row text); the build fails loudly if a ref matches no row or more than one row of that source.
Family 1 (page argument): what kind of page, for whom, what it argues, how long, and what the visitor does next."""
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
     ("D1", "Clear beats clever"), ("D1", "A slot that held six words"), ("D1", "Feature dumping"), ("D1", "Swap test")]},
   {"label": "Legacy candidates: decision material", "refs": [
     ("L5", "Research is an input to an argument"), ("L5", "A shortage of slots is not a reason"),
     ("L5", "How would the work change?"), ("L5", "Supply a concrete worked application"), ("L5", "**Utility:**"),
     ("L5", "The added depth comes from a concrete task"),
     ("L3a", "For each retained insight, record the visible explanation"), ("L3a", "Why this is relevant here"),
     ("L1b", "research must change the visible explanation"), ("L3", "Without target research, write an invitation")]}]},

 {"id": "P5", "family": 1, "topic": "ACTION", "severity": "high", "status": "open",
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

 {"id": "P6", "family": 1, "topic": "IDENTITY", "severity": "medium", "status": "open",
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

 {"id": "P7", "family": 1, "topic": "SHELL", "severity": "medium", "status": "open",
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

 {"id": "P8", "family": 1, "topic": "PLAN", "severity": "medium", "status": "open",
  "title": "Is the brief binding, or an agent's summary to read critically?",
  "what": "The site treats the brief's goal, reader and offer as fixed and its facts, proof and structure as suggestions. The legacy skills say a delegation brief is an agent-authored summary: quote the person's actual words, keep user requirements apart from working choices, and do not read a pilot, demo or section count into a short request. The site agent never sees the person's own message, only the Head of ABM's brief and the session history.",
  "why": "When the brief picks a weak offer or the wrong page kind, the site agent has no permission to question it.",
  "groups": [
   {"label": "Site: the brief sets goal, reader, offer", "refs": [
     ("A1", "The brief sets the goal, the reader and the offer"), ("D1", "The brief may suggest a proof or a structure"),
     ("H1", "the delegation brief, then this artifact's line")]},
   {"label": "Legacy candidates: the person's words outrank the brief", "refs": [
     ("L2", "Quote the actual user message, not the delegation brief"), ("L6", "A delegation brief is an agent-authored summary"),
     ("L6", "A simple request for an account page does not specify a pilot"), ("L2", "A short account-page request does not mandate"),
     ("L6", "an explicit user offer cannot silently become a different one")]}]},

 {"id": "P9", "family": 1, "topic": "ASK", "severity": "medium", "status": "open",
  "title": "When may the agent ask before building a new page?",
  "what": "The site agent may only ask on an edit, when the request names something that is not on the page. The legacy skills allow one consequential question before a costly build when the purpose would change the argument, but otherwise make reversible assumptions and say so; a plan is never an approval gate. The site agent has no clarification tool today.",
  "why": "A campaign request with no clear reader, offer or destination is built on a guess.",
  "groups": [
   {"label": "Site: ask only on edits", "refs": [("A1", "say so and ask before adding anything")]},
   {"label": "Legacy candidates: one question before a costly build", "refs": [
     ("L1a", "ask one consequential question before a costly build"), ("L1b", "Ask only for a missing decision that changes the argument"),
     ("L6", "never an approval gate")]}]},

 {"id": "P10", "family": 1, "topic": "PEOPLE", "severity": "medium", "status": "open",
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

 {"id": "P11", "family": 1, "topic": "STRUCTURE", "severity": "low", "status": "open",
  "title": "Video sections: remove them, or lead with them?",
  "what": "The site lists brand videos among the sections to remove. The legacy argument patterns include a video-led page, as long as the headline states the promise and the page works without pressing play.",
  "why": "Pallet's homepage leads with video; the 10-26 page dropped all of it. How the video is carried belongs to the imagery family; whether it may stay is decided here.",
  "groups": [
   {"label": "Site", "refs": [("D1", "Remove sections that do not help this reader decide"), ("D5", "If the original shows a video")]},
   {"label": "Legacy candidates", "refs": [("L1b", "**Video-led**")]}]},

 {"id": "P12", "family": 1, "topic": "SCOPE", "severity": "low", "status": "open",
  "title": "Re-aiming an existing page at a new audience or offer",
  "what": "On an existing page the site changes only what was asked. The legacy skills cover changing a page's audience, offer or argument as its own case, where sections that no longer answer a question may be removed, while a scoped edit keeps everything else.",
  "why": "'Make this page work for the logistics segment' is neither a small edit nor a new page.",
  "groups": [
   {"label": "Site", "refs": [("A1", "Change only what was asked")]},
   {"label": "Legacy candidates", "refs": [
     ("L1", "changing an existing page's audience, offer or argument"), ("L1b", "When a whole-page campaign adaptation authorizes"),
     ("L1", "Adding account markers is not a reason")]}]},

 {"id": "P13", "family": 1, "topic": "STRUCTURE", "severity": "low", "status": "open",
  "title": "Several directions for the same page",
  "what": "The site has no rule for a request for several concepts or layouts. The legacy skill plans one row per direction, keeps brand invariants fixed, says three centred heroes with different headlines are still one composition, and reports honestly when only one page is finished.",
  "why": "A gap, not a conflict.",
  "groups": [
   {"label": "Legacy candidates", "refs": [
     ("L1c", "For each requested page, write one row"), ("L1c", "For argument alternatives, give each page"),
     ("L1c", "For layout-only alternatives"), ("L1c", "Three centered heroes")]}]},
]

out = []
for issue in ISSUES:
    groups = [{"label": g["label"], "rows": [find(s, t) for s, t in g["refs"]]} for g in issue["groups"]]
    out.append({**{k: v for k, v in issue.items() if k != "groups"}, "groups": groups})
(HERE / "issues.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(len(out), "issues,", sum(len(g["rows"]) for i in out for g in i["groups"]), "row refs")
