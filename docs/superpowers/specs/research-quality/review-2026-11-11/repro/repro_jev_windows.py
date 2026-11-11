"""A 3-window recording where the person speaks only in window 3 (e.g. a panel / keynote slot)."""
import sys
sys.path.insert(0, "tests/footprint")
from test_jev_client import wire, answer, run

labels = ["Speaker 0", "Speaker 1", "Speaker 2"]
lines = [f"[00:{i:02d}] Speaker {i%3}: " + "x" * 50 for i in range(9)]
# window answers: w1,w2 say "none"/only_mentioned-ish; w3 says Speaker 2 is the person, speaking 0.97
caller, transport, _ = wire(
    answer(label="none", p_label=0.0, presence="different_person", is_speaking=0.05, labels=labels),
    answer(label="none", p_label=0.0, presence="different_person", is_speaking=0.05, labels=labels),
    answer(label="Speaker 2", p_label=0.95, presence="speaking", is_speaking=0.97, labels=labels),
)
check = run(caller, lines=lines, max_chars=3 * 70)
print("windows:", check.windows)
print("presence:", check.presence, check.presence_probabilities)
print("is_speaking:", check.is_speaking)
print("label:", check.label, check.label_probabilities)
