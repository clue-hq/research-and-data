"""H19 — record the definitive wall clock. Zero provider calls.

Two numbers, both measured, because they answer different questions:
  * research wall clock  = run start -> the last provider call in the ledger. What the pipeline
    would take if it ran unattended.
  * total wall clock     = run start -> now, i.e. including writing the two deliverables.
"""
import calendar
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

RUN_START_EPOCH = 1790058847  # 2026-09-22T06:34:07Z, recorded before the first call
rows = json.load(open(C.LEDGER_PATH))
ts = [calendar.timegm(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ")) for r in rows if r.get("ts")]
last, now = max(ts), int(time.time())


def hms(s):
    return f"{int(s)//3600}h {(int(s)%3600)//60}m {int(s)%60}s"


wc = {
    "run_started_utc": "2026-09-22T06:34:07Z",
    "last_provider_call_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last)),
    "research_wall_clock_seconds": last - RUN_START_EPOCH,
    "research_wall_clock_hms": hms(last - RUN_START_EPOCH),
    "total_wall_clock_seconds": now - RUN_START_EPOCH,
    "total_wall_clock_hms": hms(now - RUN_START_EPOCH),
    "sum_of_phase_seconds": round(sum(p["seconds"] for p in
                                      json.load(open(C.TIMING_PATH))["phases"]), 1),
    "total_calls": len(rows),
    "total_cash_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
    "ai_ark_credits_actual": round(sum(float(r.get("credits") or 0) for r in rows), 2),
    "apollo_calls": 0, "firecrawl_calls": 0,
    "ceilings_hit": [],
}
wc["parallelism_factor"] = round(wc["sum_of_phase_seconds"] / wc["research_wall_clock_seconds"], 2)

t = json.load(open(C.TIMING_PATH))
t["wall_clock"] = wc
json.dump(t, open(C.TIMING_PATH, "w"), indent=2)
tb = json.load(open("h17_tables.json"))
tb["run"].update(wc)
json.dump(tb, open("h17_tables.json", "w"), indent=2)
print(json.dumps(wc, indent=2))
