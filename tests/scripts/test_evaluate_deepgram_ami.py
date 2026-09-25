from scripts.evaluate_deepgram_ami import reference_overlap, references, timing_diagnostic, tokens


def test_reference_keeps_untimed_words_but_not_punctuation_or_vocal_events(tmp_path):
    (tmp_path / "ES0001a.A.words.xml").write_text(
        '<root><w starttime="1" endtime="2">I’m</w><w>okay</w>'
        '<w punc="true">.</w><vocalsound type="laugh"/></root>'
    )
    ref, sources = references(tmp_path, "ES0001a")
    assert [w["text"] for w in ref["A"]] == ["i'm", "okay"]
    assert ref["A"][1]["start"] is None
    assert len(sources) == 1
    assert tokens("Um, TWO—2.") == ["um", "two", "2"]


def test_overlap_counts_distinct_speakers_not_overlapping_same_speaker_words():
    ref = {
        "A": [{"start": 1, "end": 3}, {"start": 2, "end": 3}],
        "B": [{"start": 2, "end": 4}, {"start": None, "end": None}],
    }
    assert reference_overlap(ref) == 1


def test_timing_keeps_known_offsets_and_excludes_untimed_anchors():
    ref = [
        {"text": t, "start": float(i), "end": i + 0.5}
        for i, t in enumerate(["this", "is", "a", "sentence"])
    ]
    hyp = [{**w, "start": w["start"] + 0.1, "end": w["end"] + 0.1} for w in ref]
    ref[-1]["start"] = None
    matches = timing_diagnostic(ref, hyp)
    assert len(matches) == 3
    assert all(abs(m["start_offset_s"] - 0.1) < 1e-8 for m in matches)
