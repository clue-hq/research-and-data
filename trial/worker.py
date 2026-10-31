"""The trial's fleet worker: the platform's own worker, started from this worktree.

    set -a; source .env; set +a
    TRIAL_HOLD_PERSON_JOBS=1 uv run python trial/worker.py

It reads prompts and skills from this worktree's platform/agents/catalog/research-quality.
With TRIAL_HOLD_PERSON_JOBS=1, nominated people get their job rows as usual but no person job is
offered to the queue, so only account research (and its pages) runs. Nothing else is changed.
"""
import logging
import os
import sys

from clue_api import fleet_main
from clue_api.arv2 import quality_catalog, quality_person_release
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler

URL = os.environ["CLUE_DATABASE_URL"]
if not URL.endswith("/clue_addis-ababa"):
    sys.exit("refused: the trial worker only runs against the addis-ababa lane database")

log = logging.getLogger("trial.worker")
print(f"trial worker: prompts from {quality_catalog.ROOT}", flush=True)
print(f"trial worker: recipe version {quality_catalog.CURRENT_RECIPE_VERSION}", flush=True)
print(f"trial worker: account model {os.environ.get('ARV2_ACCOUNT_AGENT_MODEL')}", flush=True)

if os.environ.get("TRIAL_HOLD_PERSON_JOBS") == "1":
    async def _no_person_jobs(*args, **kwargs):
        return []

    async def _hold_committee(self, composition, committee):
        print(f"trial worker: holding {len(committee.jobs)} person job(s) of "
              f"{composition.job.job_id}", flush=True)

    quality_person_release.ready_person_jobs = _no_person_jobs
    Arv2AccountResearchWorkHandler._offer_committee = _hold_committee
    print("trial worker: person jobs are HELD", flush=True)

fleet_main.main()
