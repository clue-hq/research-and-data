"""Step 8b — structuring retry with reasoning controlled.

Round 1 finding: on this task both cheap models spent ~6.1k tokens on *reasoning* before writing
any JSON. GLM-4.7 exhausted its completion budget doing so and returned EMPTY content (a total
loss, $0.0150); gpt-5-mini survived but under-produced (28 claims against a 60-110 target).

Round 2 therefore turns reasoning off/low and raises max_tokens, and splits the work into two
calls (account bundle, contact bundle) so neither answer has to be truncated. Same prompt, same
bundle — so the model comparison stays apples-to-apples.
"""

import json
import os
import re

from clue_lib import HERE, openrouter, save_raw
from step8_structure import BUNDLE, INSTRUCTIONS, parse_json_content  # noqa: E402

MODELS = [
    ("z-ai/glm-4.7", {"enabled": False}),
    ("openai/gpt-5-mini", {"effort": "low"}),
]

MESSAGES = [
    {"role": "system", "content": INSTRUCTIONS},
    {
        "role": "user",
        "content": (
            "RESEARCH BUNDLE\n\n"
            + BUNDLE
            + "\n\nREMINDER: return ONLY the JSON object, starting with '{'. Do not think out "
            "loud, do not explain, do not wrap in markdown. Emit every distinct fact in the "
            "bundle as its own claim row — completeness is the whole point of this pass."
        ),
    },
]

RESULTS = {}
for model, reasoning in MODELS:
    label = "step8b_" + model.replace("/", "_").replace(".", "")
    resp = openrouter(
        model,
        MESSAGES,
        label=label,
        response_format={"type": "json_object"},
        reasoning=reasoning,
        max_tokens=32000,
        timeout=1200,
    )
    parsed, err = parse_json_content(resp)
    n = len(parsed.get("claims") or []) if parsed else 0
    npf = len(parsed.get("proposed_fields") or []) if parsed else 0
    usage = resp.get("usage") or {}
    cost = usage.get("cost") or (usage.get("cost_details") or {}).get("upstream_inference_cost")
    print(f"  -> {model}: claims={n} proposed={npf} cost=${cost} err={err}")
    RESULTS[model] = {"parsed": parsed, "err": err, "usage": usage, "cost": cost}
    if parsed:
        save_raw(label + "_parsed", parsed)

json.dump(
    {
        m: {
            "err": r["err"],
            "cost_usd": r["cost"],
            "usage": r["usage"],
            "n_claims": len(r["parsed"].get("claims") or []) if r["parsed"] else 0,
            "n_proposed": len(r["parsed"].get("proposed_fields") or []) if r["parsed"] else 0,
        }
        for m, r in RESULTS.items()
    },
    open(os.path.join(HERE, "structuring_comparison_round2.json"), "w"),
    indent=2,
)
