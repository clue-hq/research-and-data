"""Launch-pinned research behavior; quality assessments are advisory from revision six.

This changes research processing and presentation, not tenant access or source retention.
Earlier launches keep their recorded behavior for replay.
"""

from clue_api.arv2.account_research_claims import JobScope


def advisory_research(scope: JobScope) -> bool:
    return int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 6
