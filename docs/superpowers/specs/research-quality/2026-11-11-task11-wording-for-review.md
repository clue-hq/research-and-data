# Task 11 — wording for founder review (2026-11-11)

Nothing here is written into a prompt or skill yet. Each item shows what the agent reads **now** and
what is **proposed**. Mark each item OK, edit it in place, or strike it. Once approved, the wording
goes into new versions only; the pinned versions stay as they are.

Where it will land:
- Job descriptions: `platform/api/clue_api/arv2/footprint_operations.py` (`DESCRIPTIONS`)
- Person prompt: new `prompts/quality-person-research/v31-person/SYSTEM.md` (copied from `v30-person`)
- Account prompt: new `prompts/quality-account-research/v42/SYSTEM.md` (copied from `v41`)
- Page-writing skill: new `skills/research-page-writing/v4/SKILL.md` (copied from `v3`)

(Paths under `platform/agents/catalog/research-quality/` unless shown in full.)

**Changed since the first draft (2026-11-11):**
1. *The agent writes the podcast and video searches* (code `4a5767196`): `find_podcasts` and `find_videos`
   take the agent's own list of searches; `find_podcasts` also searches Exa's podcast transcripts; nothing
   is ranked by name; the agent judges a garbled name from the introduction, employer, role and background.
   Touches **A** (`find_podcasts`, `find_videos`) and **B3**.
2. *Results open with an overview* (code `88a059a25`, `06f8d377e`): the receipt is one line, and the saved
   file starts with one short line per result, then the full entries (`podcasts` / `videos`), line N being
   entry N. Touches **A** (`find_podcasts`, `find_videos`) and **B3**.
3. Earlier the same day, from the social-post fixes: reposts, possibly-cut posts and full link addresses.
   Touches **A** (`linkedin_activity`, `x_posts`, `company_linkedin_posts`), **B5** and **C**.

---

## A. Job descriptions (the agent reads these in its job list)

| Job | Now (placeholder) | Proposed |
|---|---|---|
| `find_podcasts` | Podcast episodes the person may appear on, from Apple and Podcast Index, with each episode's full description, links, feed and audio link. Nothing is filtered. | Podcast episodes for the searches you write (queries). Each search is run on Apple, Podcast Index and Exa's podcast transcripts, which match what was said in an episode, so an episode whose title never names the person can still be found. Each episode comes with its full description, links, feed and audio link, the searches that found it, and, from Exa, the transcript passages that matched and the hosts and guests Exa heard. Nothing is left out or ranked: decide yourself which are this person. The answer starts with an overview, one line per episode in the order found; scan it, then open the episodes you need by number in its podcasts list. *(updated 2026-11-11)* |
| `find_videos` | YouTube videos found by the person's quoted name (and with the company), each with its full description, tags, channel and length. Nothing is filtered. | YouTube videos for the searches you write (queries). Each comes with its full description, tags, channel, length and the searches that found it. Nothing is left out or ranked. The answer starts with an overview, one line per video in the order found; scan it, then open the videos you need by number in its videos list. *(updated 2026-11-11)* |
| `find_handles` | Candidate X, Facebook and Instagram accounts for the person (PDL and a same-handle Instagram check). Each is a candidate to confirm from its bio and posts. | Possible X, Facebook and Instagram accounts for the person. Each one is only a candidate: check its bio and posts before you read it. |
| `linkedin_activity` | The person's whole LinkedIn history: their own posts (kind=posts) or the posts they reacted to (kind=reactions). Every post is saved; video links are included. | Everything the person has posted on LinkedIn (kind=posts), or every post they reacted to (kind=reactions). Every post is saved with its own link, date and any video link. A reshare comes with the original post and its author. |
| `x_posts` | The whole X timeline of a handle; reposts are marked. Video links are included. | Every post on an X account, newest first. A repost comes with the original post and its author; a quote comes with the post it quotes. Video links are included. |
| `instagram_posts` | The public Instagram posts of a handle; a private account says so. | The public posts of an Instagram account. A private account comes back as private. |
| `facebook_posts` | The public Facebook posts of a profile link; a private profile says so. | The public posts of a Facebook profile. A private profile comes back as private. |
| `company_linkedin_posts` | The whole post history of a company's LinkedIn page. | Everything a company has posted on its LinkedIn page. A reshare comes with the original post and its author. |

---

## B. Person prompt (v30-person → v31-person)

### B1. LinkedIn routes — one sentence removed

**Now** (end of the "Their voice on LinkedIn comes first" paragraph):
> … and read the comment threads; read the activity on their profile, then search each post by its words to find its own URL. Quote them exactly, with the date. A finding about a post cites that post's URL; the profile URL is only for plain profile facts. If you saw a post only in their profile's activity, search its words to find its own URL before you save the finding. If you can't find it, say in the finding that it was seen in their profile activity and that its own URL was not found.

**Proposed:**
> … and read the comment threads. Quote them exactly, with the date. A finding about a post cites that post's URL; the profile URL is only for plain profile facts.

(Every post from `linkedin_activity` now comes with its own link, so the "search its words" routine is no longer needed.)

### B2. LinkedIn history — replaces the date-window paragraph

**Now:**
> One search returns only a small part of what someone has posted. To find more, limit the search to linkedin.com and run it over separate date windows, using both a start and an end date. Cover each of the nine months ending on the research date closely, then wider windows for the years before. If a window comes back full, split it into smaller ones and search again; if windows keep coming back empty, the person probably posts little. Use their name, and their profile name, across the windows. Open the posts that look substantive and read the full text and comments. Results vary from one search to the next, so one empty result does not prove that a post is absent.

**Proposed:**
> Read their whole LinkedIn history with linkedin_activity: kind=posts for what they wrote or shared, kind=reactions for what they reacted to. Each post comes with its own link and date. Read the saved file all the way through; for a long history, read it in parts. Use web search on linkedin.com only for what this does not cover, such as their comments on other people's posts.

### B3. Recordings — replaces "Beyond LinkedIn…" *(rewritten 2026-11-11: the agent writes the searches)*

**Now:**
> Beyond LinkedIn, work out where people in this industry and role speak: trade press, podcasts, conferences, webinars, vendor case studies that quote them, local press, earlier employers' sites, universities and associations. Transcribe every recording where they speak and pull their exact words.

**Proposed:**
> Then look for recordings with find_podcasts and find_videos. You write the searches, and you can give several at once. Search their name in quotes on its own, then with their current employer, then with each earlier employer. Add any other form of the name you have seen them use: a nickname, a maiden or married name, without the hyphen or middle initial. Add their employer and role without the name, such as "U.S. Bank chief information officer podcast", because a host may introduce them without saying the name the way you would search it. A common name needs the quotes and the employer, or namesakes will fill the results.
>
> Each answer starts with an overview, one line per result: the show or channel, title, date, length, which of your searches found it, and for podcasts the guests the transcription heard. Scan the whole overview before you open anything, then open the results you need by number.
>
> find_podcasts also searches what was said inside episodes, so it can find an episode whose title and description never name the person. Two examples:
> - Beatrice Rubini of CRIF speaks in an episode titled "The SME Cyber Shield". Neither the title nor the description names her; the host introduces her by name in the audio, and a search of her name found it in the transcripts.
> - Mike McNeil, CEO of Fleet Device Management, sits on a panel in an episode titled "Adnan Masood on AI Transformation at UST". Searching "Mike McNeil" alone returned dozens of other Mike McNeils; with the name in quotes, the transcripts found it, and a YouTube recording of the panel listed him in its description.
>
> Decide for yourself which results are this person. A transcript often spells a name wrongly (it wrote "Venkateshwari" for Dilip Venkatachari), so never judge from the spelling alone. Judge from what the episode says about the speaker: how the host introduces them, their employer and role, their background and what they talk about, against what you already know about the person. If it fits, treat it as theirs and say in the finding how you matched it. If it clearly describes someone else, skip it. If you can't tell, read more of the transcript before you decide.
>
> An episode description is not the episode. Read the transcripts of every recording where they speak, and read the whole transcript of the ones where they talk most. Also look wherever people in this industry and role speak: trade press, conferences, webinars, vendor case studies, local press, earlier employers' sites, universities and associations.

(Replaces the earlier B3 draft, which had the "check the title and description first, then transcribe" rule. That rule is folded into the paragraph on deciding which results are theirs.)

### B4. Other social accounts — new paragraph (after B3)

**Proposed:**
> Find their other accounts with find_handles. Each result is only a candidate. Before you read an account, confirm from its bio and posts that it is this person: their employer, role, location, the people they mention. Then read x_posts, instagram_posts or facebook_posts. Personal accounts are often private. That is an answer, not a gap to work around. From Instagram and Facebook, keep only what fits the personal side above, and never the topics it rules out.

### B5. Reposts, cut posts and links — new paragraph (after B4; from the 2026-11-10/11 fixes)

**Proposed:**
> A repost's or reshare's words belong to its original author, which comes with it. Never quote them as the person's words; at most, record that the person shared it, as you would a like. When a shared post is marked as possibly cut, open its link and read it in full before you quote it. To cite a link from a post, use the full address listed with the post, not its t.co or lnkd.in short link.

### B6. Speaker check — new paragraph (after B5)

**Proposed:**
> When read_media transcribes a recording, it also returns a speaker check. This is a model's answer to whether this person speaks in it and which speaker label is them, with a probability for each answer. Treat it as one piece of evidence, together with what you read in the transcript. Every line under that label counts as theirs unless the transcript shows the labels mixed people up. If the check says it's a different person or no one, read the transcript before you decide.

### B7. Quotes from recordings — new sentence (after "For each quote, note why it matters to the seller.")

**Proposed:**
> When you save a quote from a recording, save the transcript line exactly as it is, transcription mistakes included. It is the proof.

### B8. Stopping — added to the "Keep going while you are still learning" paragraph

**Now** (first sentences):
> Keep going while you are still learning something new. Stop only when several new routes in a row add nothing. You cannot ask anyone for help, so when a route fails, try others.

**Proposed** (added after them):
> If a tool fails, use the others. Before you finish, make sure you have searched every kind of source: LinkedIn, podcasts, videos, X, Instagram, Facebook and the web. In the gaps, say which ones turned up nothing.

### B9. `discover_media` mention — line 65

**Now:**
> Follow relevant media candidates with read_media, then open/search the acquired transcript.

**Proposed:**
> Follow relevant recordings from find_podcasts, find_videos and the posts you read with read_media, then open and search the transcript.

(`discover_media` is not in version 3 of the evidence tool. Checked 2026-11-11: this line is the only mention in the person prompt, the account prompt and the skills the person profile pins, so nothing else needs changing. The person-dossier skill (v7) also says "The same search over different date windows is not a cosmetic variation." That is about web search in general, still true, and is left as it is unless you want it gone.)

---

## C. Account prompt (v41 → v42) — new paragraph (after the people-search paragraph)

**Proposed:**
> Read the company's own voice: its LinkedIn page with company_linkedin_posts, and its X account with x_posts. For the leaders who matter to the seller, read what they post with linkedin_activity. A company post speaks for the company. A leader's post speaks for that leader. A reshare's words belong to its original author, never to the company or the leader who shared it. Cite each one by its own link.

---

## D. Page-writing skill (v3 → v4) — section 6 "Quote people when their words carry the point"

**Now:**
> When a person's own words make the point, name them, give their role, say where and when they said it, and quote the words that matter exactly. Quotation marks contain only exact words from the finding. Shorten your own explanation before you shorten the quote.

**Proposed** (one sentence added at the end):
> When you quote a recording, write the person's words as the transcript has them. Fix only spelling and punctuation the transcription got wrong. Never change the meaning, add words, or join separate lines.

---

## Your answers

| Item | OK / edit / strike |
|---|---|
| A (8 descriptions) | OK (founder, 2026-11-11) |
| B1 | OK (founder, 2026-11-11) |
| B2 | OK (founder, 2026-11-11) |
| B3 | OK (founder, 2026-11-11) |
| B4 | OK (founder, 2026-11-11) |
| B5 | OK (founder, 2026-11-11) |
| B6 | OK (founder, 2026-11-11) |
| B7 | OK (founder, 2026-11-11) |
| B8 | OK (founder, 2026-11-11) |
| B9 | OK (founder, 2026-11-11) |
| C | OK (founder, 2026-11-11) |
| D | OK (founder, 2026-11-11) |
| A2 (argument descriptions and example calls, drafted in chat) | OK (founder, 2026-11-11) |
