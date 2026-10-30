# Design agents read what was attached — design

Date: 2026-10-30. Branch: `fix/leg-turn-attachments` (from `main` at `6a1ff081`, the code production runs).
Status: draft for the founder's review. Nothing is built yet.

## 1. Why

On 2026-10-29 a marketer attached two images to messages in a chat that had an ad design session
open. The uploads were stored and attached to the messages, but:

- the ad agent never received them (it recorded "the user's latest original-message content is
  empty", and two runs ended "Response failed");
- the chips on the sent messages disappeared;
- on the third try the ad agent placed a *different* image from the library, uploaded by someone
  else the day before, and told him it was his upload.

The founder's own message the day before seemed to work, but only because the same file was
already in the image library (uploaded six minutes earlier as a reference image), and the Head of
ABM's brief described it closely enough for the ad agent to find it there.

Evidence (production database, read-only, 2026-10-30): the attachment rows exist for every one of
those messages; every design-session turn, every session's first turn and every hand-back carries
zero; only the Head of ABM's path writes a message's attachment refs; the ad run that "used his
upload" placed `asset_38fea03f68c8`, whose bytes differ from both of his files.

Root cause: an attachment is carried by one route only. `ProjectConversationTurnRunner.run` reads
the message's attachments and passes them to the Head of ABM; the design-session route
(`run_leg_turn`), the session's first turn (`_queue_first_turn`) and the hand-back (out-of-scope
redelivery) do not carry them. The composer adds a second, conditional route: images become design
references only when an ad is the item open in the panel.

## 2. What we want (founder, 2026-10-30)

- A design agent deals with attachments as well as the Head of ABM does: text, images and
  documents (PDF, Word, PowerPoint, Excel, CSV, JSON).
- Whether a message is design work is the agent's judgement, never a rule. "Make an ad from the
  analysis in this Excel" stays with design; "calculate the ROI from this Excel" goes back to the
  Head of ABM — with the Excel still attached.
- A design agent sees the files sent in **this chat thread**, not every file in the project.
- Design agents get their own `run_python` sandbox, like the Head of ABM's, so they can open PDFs,
  decks and spreadsheets.
- Attached images become permanent library images, labelled as attached in chat, so they can be
  placed on a design.

Non-goals: changing what the Head of ABM can read; converting documents to text at upload (ruling
2026-09-19: no conversion step, no second mechanism); letting any agent modify a person's file.

## 3. The design

### 3.1 The files belong to the message (every route carries them)

- `run_leg_turn` takes the turn's attachments (the rows `submission_attachment_refs` already
  reads) and passes them on as `AgentTurnRequest.attachment_refs`, so the journal writes the same
  `agent_artifact_ref` rows (`ref_role='attachment'`) the Head of ABM path writes. The saved message
  keeps its chips on every route.
- `_queue_first_turn` and the out-of-scope redelivery copy the source message's attachment rows
  into the derived submission (`insert_submission(..., attachment_refs=...)`), exactly as they copy
  its context refs today.

### 3.2 The exit judgement sees the files and decides by reasoning

The exit check is already a model call (`clue_design/exit_judgment.py`, prompt v4) that reads the
brief, the history, the message and its tagged items. It gains the message's files, one line each:
filename and kind (text, image, PDF, spreadsheet…). The prompt (v5) says, in substance: files do not
decide where a message belongs; what the person asks of them does. Golden fixtures add the two Excel
cases above and a "here is the brief" message that carries only a PDF.

### 3.3 Design agents get the thread's files

- A new read on the existing platform-to-design pipe (`DesignPlatformReads`, which already writes
  `project-context/` files): `thread_attachments(thread_id, current_turn_id)` returns each file
  attached in this thread — filename, media type, bytes, which message sent it, and whether it is on
  the current message. Duplicate filenames: the newest wins, as in the Head of ABM's folder.
- Each design agent (scene/ad, site, web) gets `attachments/<filename>` in its workspace, rebuilt
  every turn from durable storage (so a redeploy or another worker sees the same files — AW-8),
  read-only to the agent.
- The turn's prompt names the files sent with this message ("Attached with this message: …"), so
  the agent knows what is new without searching.

### 3.4 Images become library images and references

- At the start of a design turn, each attached image is registered once in the workspace's image
  library through the existing server-side path (`ingest_asset` → `register_engine_write` →
  `design_register_asset_record`, as `site_turn_ports.register_generated` already does), keyed by
  its sha256 so a re-attached file is one library image. Label: its filename; tag: attached in chat.
- Ad turns: the current message's images ride as `reference_asset_ids` (the existing reference
  pipeline: `view("reference:<n>")`, crop, place, generate-from), up to the existing cap; any beyond
  the cap stay in `attachments/` and the library.
- Site turns: `SiteTurnRequest` gains reference images; the site agent's `view_asset` accepts them,
  so it can look at and place an attached image on a page. (Today site pages accept no reference
  images at all.)

### 3.5 Design agents get `run_python`

- The sandbox (`clue_api/sandbox/`: docker runner, workspace mounts, policy sweep) moves to a shared
  package both sides may import (it depends only on `clue_agents` and `clue_core`), so there is one
  sandbox, not two. The Head of ABM's `run_python@1` keeps working unchanged.
- The scene, site and web agents get a `run_python` tool over their own workspace: `attachments/`
  and the agent's inputs read-only; its scratch and outputs read-write; no network; the same limits
  and post-run sweep. Design jobs run on the `chat` and `design` workers, which already mount the
  Docker socket.

### 3.6 How each kind of file is read

| Attached | How a design agent reads it | Sandbox |
|---|---|---|
| PNG, JPEG, WebP, GIF | a library image, seen with the agent's view tool (ads: `view("reference:<n>")`); crop, place, generate from it. An animated image is seen at its first frame, and the agent is told so. | no |
| HEIC/HEIF, AVIF, TIFF, BMP, ICO | the same, through a PNG copy made when the image is registered (vision models and the design library take none of these); the original stays in `attachments/` under its own name. HEIC needs the `pillow-heif` dependency; the rest Pillow already reads. | no |
| SVG | a library vector image (the design engine already renders a preview of every SVG it stores), placeable as a vector; its markup is also readable as text. | no |
| `.md`, `.txt`, CSV, JSON | `read_file` | no |
| PDF, Word, PowerPoint, Excel | `run_python`: extract text and tables, compute; a visual PDF or deck can be rendered to page images in `outputs/` and then viewed. | yes |
| PSD, AI, EPS | a file, not an image: in `attachments/`, openable with `run_python` if it can; if not, the agent says so. | yes |

The composer's accepted list and the Head of ABM's image handling gain the same formats (the Head
of ABM sees the PNG copy), so one rule covers every agent. SVG reaches the Head of ABM as a file.

### 3.7 Read-only originals, honest answers

- A person's file is never modified: the agent may open, read, analyse and copy it, but what it
  makes from it is new work in its own places — a script's results in its `outputs/`, crops and
  generated images as new library images, page and ad changes as new versions. So the chips keep
  pointing at what was sent, the next turn (or the Head of ABM after a hand-back) sees the same
  file, and a mistake can always be redone from the original. An edited copy of a document is a new
  file the agent offers, never a replacement.
- Prompt guidance for every design agent: when a message names an attachment, use that exact file;
  if a file cannot be opened, say so in plain words; never stand in a similar-looking library image
  for an attached one.

### 3.8 The composer stops guessing

Every file goes up as a chat attachment, whatever the panel shows; the server decides how it
reaches the agent. The design-reference route in the composer (`attachment-routing.ts`,
`useDesignReferenceAttachments` in `chat-surface.tsx`) is removed. Past messages that carry
`design_asset` chips keep rendering them.

## 4. Open points for the founder

Decided 2026-10-30: SVG is added to chat attachments (§3.6); HEIC/HEIF, AVIF, TIFF, BMP and ICO are
in scope with a PNG copy (§3.6).

1. **"Response failed".** A design run that stops because it needs something (a file it cannot open)
   ends `failed`, and the chat shows only "Response failed". Show the agent's own reason instead —
   in this change or separately?
2. **Wording.** The new prompt and tool text (exit judgement v5, the attachments paragraph and the
   `run_python` description for the three design agents) will be shown to you before it is written
   into any skill or prompt.

## 5. How we prove it

DB tests through the real turn worker, each failing before the change:

- an image sent into an open ad session reaches the ad run as a reference, and the saved message
  keeps its chip;
- a `.md` brief sent into a site session is readable at `attachments/` in the site agent's workspace;
- a PDF is opened through the design agent's `run_python`;
- a session's first turn and an out-of-scope hand-back both carry the source message's files;
- the exit judgement goldens: Excel → ad stays with design; Excel → ROI goes back with the file;
- a file the agent cannot open produces a plain message, not a substituted image.

Live on the trenton lane: the cofounder's exact flow (ad session open, a different item in the
panel, two images attached), and a PDF brief into a site session.

## 6. What is left to the builder

Exact module names for the moved sandbox; how the design workspace (not an `AgentWorkspaceLease`)
is mapped to sandbox mounts; the order of steps inside a design turn; test fixtures.
