## Follow relevant media through to its content

An interview page, recording candidate, transcript and show notes are different stages of work.
Use `read_media` for a relevant public appearance and inspect the returned state and candidates.

If the result is `ambiguous`, the recordings have not yet been attempted. Use the source page,
episode title, description and candidate type to choose a relevant recording. Pass that candidate's
URL back to `read_media`, with an exact episode hint where useful. Do not repeat the unchanged
landing-page call or stop merely because it returned multiple candidates. If audio and video may
be the same episode, start with one useful version; investigate another only when it adds value
or the first route fails. Do not assume two formats are the same recording solely from their host.

If no recording link was recognized, use the publisher page, an explicit player/download link,
feed, indexed transcript or targeted search to find a useful alternative. `unsupported` describes
this retrieval route, not proof that no recording exists. Reuse returned links and completed work.

Read the transcript when obtained. Extract substantive speaker-specific passages about the
person's reasoning, experiences, interests or work; retain URLs and supplied timing. Distinguish
their words from an interviewer, other speakers and show notes. Do not invent timestamps.

In the report, distinguish a recording not found, a candidate not yet attempted, a recording
that could not be retrieved, and a transcription attempt that failed. Inspect the saved provider
outcome before retrying a paid call with an uncertain result. Pursue useful leads without an
exhaustive crawl or a requirement to obtain a transcript before completing the investigation.
