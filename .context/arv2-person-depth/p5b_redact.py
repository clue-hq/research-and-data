"""Phase 5b — enforce the sensitivity floor DETERMINISTICALLY, in code, after the models.

The floor is a property of the pipeline, not a hope about the prompt. Two real hits in this run:
  1. A self-published post that mentions the subject's children -> the minors clause is absolute
     even when the subject published it themselves. The offending element is REMOVED from the
     recorded value and the removal is recorded.
  2. A first-person origin statement -> allowed as biography, but forced outreach_safe=false and
     tagged [ORIGIN - NOT AN OUTREACH HOOK], and barred from opener/hook fields.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "claims_people.json")

MINORS = re.compile(r"\b(my (son|daughter|kids|children)|his (son|daughter|kids|children)|"
                    r"her (son|daughter|kids|children)|toddler|kindergarten|my child)\b", re.I)
ORIGIN = re.compile(r"\b(fled|refugee|immigrat\w*|emigrat\w*|asylum|born in iran|left iran)\b", re.I)
HOOK_FIELDS = {"contact.facet.hooks", "contact.facet.openers"}


def scrub_value(val):
    """Drop only the offending element; keep the rest of the claim."""
    removed = []
    if isinstance(val, list):
        keep = []
        for x in val:
            if isinstance(x, str) and MINORS.search(x):
                removed.append(x)
            else:
                keep.append(x)
        return keep, removed
    if isinstance(val, str) and MINORS.search(val):
        return "[REDACTED — sensitivity floor: reference to minors]", [val]
    return val, removed


def main():
    data = json.load(open(PATH))
    log = []
    for key, v in data["people"].items():
        kept = []
        for c in v["claims"]:
            blob = json.dumps(c.get("value")) + " " + (c.get("evidence_quote") or "")
            # --- minors: absolute, even self-published
            if MINORS.search(blob):
                newval, removed = scrub_value(c.get("value"))
                if MINORS.search(c.get("evidence_quote") or ""):
                    c["evidence_quote"] = "[REDACTED — sensitivity floor: reference to minors]"
                if not newval and not isinstance(newval, str):
                    log.append({"person": key, "field": c["field_key"],
                                "action": "claim dropped entirely (nothing survived redaction)",
                                "removed": removed})
                    continue
                c["value"] = newval
                c["note"] = ((c.get("note") or "") +
                             " | REDACTED under the sensitivity floor: an element referencing "
                             "minors was removed even though the subject self-published it.").strip(" |")
                log.append({"person": key, "field": c["field_key"],
                            "action": "element removed", "removed": removed})
            # --- origin: allowed as biography, never as a hook
            if ORIGIN.search(json.dumps(c.get("value")) + " " + (c.get("evidence_quote") or "")):
                if c["field_key"] in HOOK_FIELDS or c.get("charter_category") == "opener":
                    log.append({"person": key, "field": c["field_key"],
                                "action": "claim dropped (origin material cannot be a hook/opener)",
                                "removed": c.get("value")})
                    continue
                c["outreach_safe"] = False
                c["note"] = ((c.get("note") or "") +
                             " | [ORIGIN — NOT AN OUTREACH HOOK] first-person biography, "
                             "recorded but barred from outreach use.").strip(" |")
                log.append({"person": key, "field": c["field_key"],
                            "action": "flagged outreach_safe=false"})
            kept.append(c)
        v["claims"] = kept
        # the unique insight must not rest on origin material
        ui = v.get("unique_insight") or {}
        if ORIGIN.search(json.dumps(ui)):
            ui["outreach_safe"] = False
            ui["note"] = ("The cited article's headline references the subject's origin; the "
                          "INSIGHT itself is her intelligence-service career, which the charter "
                          "permits. Origin is not to be used in outreach.")
            log.append({"person": key, "field": "unique_insight",
                        "action": "flagged outreach_safe=false (source headline references origin)"})
        v["n_claims"] = len(v["claims"])
        v["n_p1"] = sum(1 for c in v["claims"] if c.get("priority") == "P1")
        import p4_structure as P4
        v["depth_score"], v["depth_detail"] = P4.depth_score(v["claims"], v.get("unique_insight"))
    data["sensitivity_redaction_log"] = log
    json.dump(data, open(PATH, "w"), indent=2)
    print(f"{len(log)} redaction actions")
    for r in log:
        print("  ", r["person"], "|", r["field"], "|", r["action"])
        if r.get("removed"):
            print("       removed:", json.dumps(r["removed"])[:180])


if __name__ == "__main__":
    main()


def purge_empty_rows():
    """A claim with no verbatim quote or no URL is NOT a claim. It belongs in not_found.
    Enforced in code so the 'every item = quote + URL, or NOT FOUND' rule cannot be talked out of."""
    data = json.load(open(PATH))
    import p4_structure as P4
    purged = []
    for key, v in data["people"].items():
        keep = []
        for c in v["claims"]:
            q = (c.get("evidence_quote") or "").strip()
            u = (c.get("source_url") or "").strip()
            val = json.dumps(c.get("value") or "")
            bad = (len(q) < 8 or not u.startswith("http")
                   or val.strip('"').upper().startswith("NOT FOUND"))
            if bad:
                purged.append({"person": key, "field": c["field_key"],
                               "reason": ("no verbatim quote" if len(q) < 8 else
                                          "no source url" if not u.startswith("http") else
                                          "value is NOT FOUND"),
                               "value": c.get("value")})
                v.setdefault("not_found", []).append(
                    f"{c['field_key']} (dropped: {purged[-1]['reason']})")
                continue
            keep.append(c)
        v["claims"] = keep
        v["n_claims"] = len(keep)
        v["n_p1"] = sum(1 for c in keep if c.get("priority") == "P1")
        v["depth_score"], v["depth_detail"] = P4.depth_score(keep, v.get("unique_insight"))
    data["purged_unevidenced_rows"] = purged
    json.dump(data, open(PATH, "w"), indent=2)
    print(f"\npurged {len(purged)} unevidenced rows")
    for p in purged:
        print("  ", p["person"], "|", p["field"], "|", p["reason"])
