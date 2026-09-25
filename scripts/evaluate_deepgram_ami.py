"""Offline AMI/Deepgram comparison. Requires MeetEval in a separate evaluation environment.

Reads AMI manual word XML and saved Deepgram words. Never sends references to a provider.
cpWER includes both wording and speaker errors; timing diagnostics score exact aligned words only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
from importlib.metadata import version
from pathlib import Path


def tokens(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text.lower().replace("’", "'"))


def references(folder, meeting):
    speakers = {}
    sources = []
    for path in sorted(folder.glob(f"{meeting}.*.words.xml")):
        speaker = path.name.split(".")[1]
        rows = []
        for word in ET.fromstring(path.read_bytes()).iter("w"):
            if word.get("punc") == "true":
                continue
            for token in tokens(word.text or ""):
                rows.append(
                    {
                        "text": token,
                        "start": float(word.attrib["starttime"])
                        if "starttime" in word.attrib
                        else None,
                        "end": float(word.attrib["endtime"]) if "endtime" in word.attrib else None,
                    }
                )
        # XML order is the transcript order; retain untimed lexical words for cpWER.
        speakers[speaker] = rows
        sources.append(
            {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    if not speakers:
        raise ValueError("No matching manual word annotations")
    return speakers, sources


def hypothesis(path):
    speakers = defaultdict(list)
    for word in json.loads(path.read_text()):
        speaker = str(word.get("speaker", "unknown"))
        for token in tokens(word["word"]):
            speakers[speaker].append(
                {"text": token, "start": word.get("start"), "end": word.get("end")}
            )
    return dict(speakers)


def timing_diagnostic(reference, hypothesis_rows):
    matches = []
    matcher = SequenceMatcher(
        None, [w["text"] for w in reference], [w["text"] for w in hypothesis_rows], autojunk=False
    )
    # Short, repeated interjections are poor anchors. Do not score those as precise alignment.
    for block in matcher.get_matching_blocks():
        if block.size < 3:
            continue
        for offset in range(block.size):
            ref, hyp = reference[block.a + offset], hypothesis_rows[block.b + offset]
            if any(w[k] is None for w in (ref, hyp) for k in ("start", "end")):
                continue
            matches.append(
                {
                    "word": ref["text"],
                    "reference_start": ref["start"],
                    "hypothesis_start": hyp["start"],
                    "start_offset_s": hyp["start"] - ref["start"],
                    "end_offset_s": hyp["end"] - ref["end"],
                }
            )
    return matches


def reference_overlap(speakers):
    # Word-interval overlap is a conservative diagnostic, not annotated interruption detection.
    events = []
    for speaker, words in speakers.items():
        for word in words:
            if (
                word["start"] is not None
                and word["end"] is not None
                and word["end"] > word["start"]
            ):
                events.extend([(word["start"], speaker, 1), (word["end"], speaker, -1)])
    active = defaultdict(int)
    previous = 0
    overlap = 0
    for time, speaker, delta in sorted(events):
        if sum(count > 0 for count in active.values()) > 1:
            overlap += time - previous
        active[speaker] += delta
        previous = time
    return overlap


def evaluate(reference_dir, meeting, run):
    from meeteval.wer.wer.cp import cp_word_error_rate

    ref, source_files = references(reference_dir, meeting)
    hyp_path = run / "words.json"
    hyp = hypothesis(hyp_path)
    ref_text = {s: " ".join(w["text"] for w in words) for s, words in ref.items()}
    hyp_text = {s: " ".join(w["text"] for w in words) for s, words in hyp.items()}
    metric = cp_word_error_rate(
        reference=ref_text, hypothesis=hyp_text, reference_sort=False, hypothesis_sort=False
    )
    matches = []
    for ref_speaker, hyp_speaker in metric.assignment:
        if ref_speaker is not None and hyp_speaker is not None:
            matches.extend(
                {"reference_speaker": ref_speaker, "hypothesis_speaker": hyp_speaker, **row}
                for row in timing_diagnostic(ref[ref_speaker], hyp[hyp_speaker])
            )
    absolute = sorted(abs(m["start_offset_s"]) for m in matches)
    summary = {
        "meeting": meeting,
        "meeteval_version": version("meeteval"),
        "reference_sources": source_files,
        "hypothesis_sha256": hashlib.sha256(hyp_path.read_bytes()).hexdigest(),
        "normalization": "lowercase; curly apostrophe normalized; punctuation removed; "
        "fillers and contractions retained; no numeral or vocabulary rewriting",
        "reference_words_by_speaker": {s: len(w) for s, w in ref.items()},
        "reference_untimed_words": sum(
            w["start"] is None or w["end"] is None for rows in ref.values() for w in rows
        ),
        "hypothesis_words_by_speaker": {s: len(w) for s, w in hyp.items()},
        "reference_word_interval_overlap_seconds": reference_overlap(ref),
        "cpwer": asdict(metric),
        "timing_diagnostic": {
            "method": "exact matching sequences of >=3 words within cpWER-matched speakers; "
            "not all words and not independently listened ground truth",
            "matched_words": len(matches),
            "median_abs_start_offset_s": statistics.median(absolute) if absolute else None,
            "p90_abs_start_offset_s": absolute[int(0.9 * (len(absolute) - 1))]
            if absolute
            else None,
            "matched_words_start_offset_over_1s": sum(x > 1 for x in absolute),
        },
        "limits": [
            "cpWER combines transcription and speaker attribution errors; it is not DER",
            "AMI manual transcript conventions differ from raw ASR formatting",
            "One public meeting in two microphone conditions is not a broad accuracy benchmark",
            "Reference annotations were not given to Deepgram",
        ],
    }
    (run / "reference-evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
    (run / "timing-matches.json").write_text(json.dumps(matches, indent=2) + "\n")
    print(
        json.dumps(
            {"run": str(run), "cpwer": asdict(metric), "timing": summary["timing_diagnostic"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--meeting", required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.reference, args.meeting, args.run)
