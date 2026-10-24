from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from clue_agents import (
    AgentCatalogError,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
    ProfileCatalog,
    PromptCatalog,
    SkillCatalog,
)

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "platform" / "agents" / "catalog"
LEGACY_STAGE0 = (
    Path(__file__).resolve().parents[2]
    / "platform"
    / "agents"
    / "skills"
    / "stage0-interview-v1"
    / "SKILL.md"
)


def test_real_folder_catalog_is_strict_versioned_and_provider_neutral() -> None:
    prompts = FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True))
    skills = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True))
    profiles = FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True))

    assert isinstance(prompts, PromptCatalog)
    assert isinstance(skills, SkillCatalog)
    assert isinstance(profiles, ProfileCatalog)
    assert [item.ref.address for item in prompts.list()] == [
        "prompt:account-research@v1",
        "prompt:account-research@v2",
        "prompt:account-research@v3",
        "prompt:content-drafter@v1",
        "prompt:content-drafter@v2",
        "prompt:design@v1",
        "prompt:head-of-abm@v1",
        # The operating manual: v9 without the specialist-delegation paragraph this surface
        # withholds, and with Stage 0 pointing at the `manual-*` chapters. Lexical, not numeric.
        "prompt:head-of-abm@v10",
        # The code sandbox: v10 with the "no code execution" clause replaced by the one route
        # that now exists — `run_python`, inside the container its manual entry describes.
        "prompt:head-of-abm@v11",
        # One ask, many artifacts: v11 with the two design paragraphs replaced by the one that
        # covers every designed page and tells the agent to list one item per artifact.
        "prompt:head-of-abm@v12",
        # The leg's first turn starts itself: v12 with one sentence changed, because opening a
        # leg now queues that leg's first design turn instead of waiting for the user to speak.
        "prompt:head-of-abm@v13",
        # Web search: v13 with the paragraph that orders the lookups — the claims for an account
        # or a contact, the seller's knowledge files for the seller, `web_search` only when those
        # come back empty, and the answer that says which facts came from a search.
        "prompt:head-of-abm@v14",
        "prompt:head-of-abm@v15",
        "prompt:head-of-abm@v16",
        "prompt:head-of-abm@v17",
        "prompt:head-of-abm@v18",
        "prompt:head-of-abm@v2",
        "prompt:head-of-abm@v3",
        "prompt:head-of-abm@v4",
        "prompt:head-of-abm@v5",
        "prompt:head-of-abm@v6",
        "prompt:head-of-abm@v7",
        "prompt:head-of-abm@v8",
        # The workspace libraries: v8 with one sentence moved from the per-turn brand seeds to the
        # mounted `brand/knowledge/`.
        "prompt:head-of-abm@v9",
        "prompt:onboarding-synthesis@v1",
        "prompt:onboarding-synthesis@v2",
        "prompt:research-specialist@v1",
        "prompt:research-specialist@v2",
        "prompt:reviewer@v1",
        "prompt:reviewer@v2",
    ]
    assert [item.ref.address for item in skills.list()] == [
        "skill:account-deep-steering@v1",
        "skill:account-deep-steering@v2",
        "skill:account-deep-steering@v3",
        "skill:account-deep-steering@v4",
        "skill:account-deep-steering@v5",
        "skill:account-deep-steering@v6",
        "skill:account-deep-steering@v7",
        "skill:account-deep-steering@v8",
        "skill:account-gap-research@v1",
        "skill:account-gap-research@v2",
        "skill:account-gap-research@v3",
        "skill:account-research-briefing@v1",
        "skill:account-research-briefing@v2",
        "skill:account-research-briefing@v3",
        "skill:artifact-review@v1",
        "skill:audience-persona@v1",
        "skill:audience-persona@v2",
        # How to open a file the framework's own tools cannot read: the `run_python@1` sandbox,
        # the container's folders, and one reading recipe per attachable document format.
        "skill:code-execution@v1",
        "skill:content-exemplar@v1",
        # The CRM sales analysis (head-of-abm@v76): connect the CRM, read the deals, compute in the
        # sandbox, write company/sales-motion.md and the closed-won customers.
        "skill:crm-sales-analysis@v1",
        # v2 (head-of-abm@v77): the read-only sentence points to crm-writing.
        "skill:crm-sales-analysis@v2",
        # The CRM writes (head-of-abm@v77): what Clue writes, one proposal per decision, the
        # permission card's answer, repairing failed rows, and undo through the write log.
        "skill:crm-writing@v1",
        # v2 (head-of-abm@v78): v1 plus section 3b, writing a project's research into the CRM.
        "skill:crm-writing@v2",
        # v3 (head-of-abm@v79): v2 plus the two founder-approved lines on records a card creates.
        "skill:crm-writing@v3",
        "skill:crm-writing@v4",
        # The three document skills. Each one carries the whole procedure for one document
        # the Head of ABM now writes as a file under `project/`, and grants no tool;
        # stage0-interview v33 §5b, §5c and §6b are one-line pointers at them. They are here
        # twice: the free-flowing `project/` writer moved the procedures, so each re-minted at v2
        # while `head-of-abm@v55` keeps the v1 bytes it pins.
        "skill:icp-authoring@v1",
        "skill:icp-authoring@v2",
        # Automatic project targeting (head-of-abm@v61, base): the authoring skill re-minted at v3.
        "skill:icp-authoring@v3",
        "skill:icp-synthesis@v1",
        "skill:icp-synthesis@v2",
        "skill:icp-synthesis@v3",
        "skill:icp-synthesis@v4",
        # The operating manual's chapters. Each is an ordinary skill so the profile pins it like
        # any other and the capability map discloses it with its path. Four of them (errors,
        # fields, limits, tools) are generated, and the builder (`python -m clue_api.manual_build`)
        # is their only writer; the other eleven are hand written and founder reviewed. Every
        # chapter is here SEVEN times: `head-of-abm@v55` and `@v56` each changed the grant the
        # manual describes, `@v57` changed the two limits its generated `limits` chapter renders,
        # `@v58` grants `run_python@1` and mounts `attachments/`, `@v59` moves `open_design_leg`
        # to `@5`, and `@v60` mints a version its generated chapters render into their title. A
        # catalog version is immutable, so the library re-minted at v2 through v7 while v54 keeps
        # the v1 bytes, v55 the v2 bytes, v56 the v3, v57 the v4, v58 the v5 and v59 the v6.
        "skill:manual-accounts-research@v1",
        "skill:manual-accounts-research@v10",
        "skill:manual-accounts-research@v11",
        "skill:manual-accounts-research@v12",
        "skill:manual-accounts-research@v13",
        "skill:manual-accounts-research@v14",
        "skill:manual-accounts-research@v15",
        "skill:manual-accounts-research@v16",
        "skill:manual-accounts-research@v17",
        "skill:manual-accounts-research@v18",
        "skill:manual-accounts-research@v19",
        "skill:manual-accounts-research@v2",
        "skill:manual-accounts-research@v20",
        "skill:manual-accounts-research@v21",
        "skill:manual-accounts-research@v22",
        "skill:manual-accounts-research@v23",
        "skill:manual-accounts-research@v24",
        "skill:manual-accounts-research@v25",
        "skill:manual-accounts-research@v26",
        "skill:manual-accounts-research@v27",
        "skill:manual-accounts-research@v3",
        "skill:manual-accounts-research@v4",
        "skill:manual-accounts-research@v5",
        "skill:manual-accounts-research@v6",
        "skill:manual-accounts-research@v7",
        "skill:manual-accounts-research@v8",
        "skill:manual-accounts-research@v9",
        "skill:manual-claims@v1",
        "skill:manual-claims@v10",
        "skill:manual-claims@v11",
        "skill:manual-claims@v12",
        "skill:manual-claims@v13",
        "skill:manual-claims@v14",
        "skill:manual-claims@v15",
        "skill:manual-claims@v16",
        "skill:manual-claims@v17",
        "skill:manual-claims@v18",
        "skill:manual-claims@v19",
        "skill:manual-claims@v2",
        "skill:manual-claims@v20",
        "skill:manual-claims@v21",
        "skill:manual-claims@v22",
        "skill:manual-claims@v23",
        "skill:manual-claims@v24",
        "skill:manual-claims@v25",
        "skill:manual-claims@v26",
        "skill:manual-claims@v27",
        "skill:manual-claims@v3",
        "skill:manual-claims@v4",
        "skill:manual-claims@v5",
        "skill:manual-claims@v6",
        "skill:manual-claims@v7",
        "skill:manual-claims@v8",
        "skill:manual-claims@v9",
        "skill:manual-discovery@v1",
        "skill:manual-discovery@v10",
        "skill:manual-discovery@v11",
        "skill:manual-discovery@v12",
        "skill:manual-discovery@v13",
        "skill:manual-discovery@v14",
        "skill:manual-discovery@v15",
        "skill:manual-discovery@v16",
        "skill:manual-discovery@v17",
        "skill:manual-discovery@v18",
        "skill:manual-discovery@v19",
        "skill:manual-discovery@v2",
        "skill:manual-discovery@v20",
        "skill:manual-discovery@v21",
        "skill:manual-discovery@v22",
        "skill:manual-discovery@v23",
        "skill:manual-discovery@v24",
        "skill:manual-discovery@v25",
        "skill:manual-discovery@v26",
        "skill:manual-discovery@v27",
        "skill:manual-discovery@v3",
        "skill:manual-discovery@v4",
        "skill:manual-discovery@v5",
        "skill:manual-discovery@v6",
        "skill:manual-discovery@v7",
        "skill:manual-discovery@v8",
        "skill:manual-discovery@v9",
        "skill:manual-documents-decisions@v1",
        "skill:manual-documents-decisions@v10",
        "skill:manual-documents-decisions@v11",
        "skill:manual-documents-decisions@v12",
        "skill:manual-documents-decisions@v13",
        "skill:manual-documents-decisions@v14",
        "skill:manual-documents-decisions@v15",
        "skill:manual-documents-decisions@v16",
        "skill:manual-documents-decisions@v17",
        "skill:manual-documents-decisions@v18",
        "skill:manual-documents-decisions@v19",
        "skill:manual-documents-decisions@v2",
        "skill:manual-documents-decisions@v20",
        "skill:manual-documents-decisions@v21",
        "skill:manual-documents-decisions@v22",
        "skill:manual-documents-decisions@v23",
        "skill:manual-documents-decisions@v24",
        "skill:manual-documents-decisions@v25",
        "skill:manual-documents-decisions@v26",
        "skill:manual-documents-decisions@v27",
        "skill:manual-documents-decisions@v3",
        "skill:manual-documents-decisions@v4",
        "skill:manual-documents-decisions@v5",
        "skill:manual-documents-decisions@v6",
        "skill:manual-documents-decisions@v7",
        "skill:manual-documents-decisions@v8",
        "skill:manual-documents-decisions@v9",
        "skill:manual-errors@v1",
        "skill:manual-errors@v10",
        "skill:manual-errors@v11",
        "skill:manual-errors@v12",
        "skill:manual-errors@v13",
        "skill:manual-errors@v14",
        "skill:manual-errors@v15",
        "skill:manual-errors@v16",
        "skill:manual-errors@v17",
        "skill:manual-errors@v18",
        "skill:manual-errors@v19",
        "skill:manual-errors@v2",
        "skill:manual-errors@v20",
        "skill:manual-errors@v21",
        "skill:manual-errors@v22",
        "skill:manual-errors@v23",
        "skill:manual-errors@v24",
        "skill:manual-errors@v25",
        "skill:manual-errors@v26",
        "skill:manual-errors@v27",
        "skill:manual-errors@v3",
        "skill:manual-errors@v4",
        "skill:manual-errors@v5",
        "skill:manual-errors@v6",
        "skill:manual-errors@v7",
        "skill:manual-errors@v8",
        "skill:manual-errors@v9",
        "skill:manual-fields@v1",
        "skill:manual-fields@v10",
        "skill:manual-fields@v11",
        "skill:manual-fields@v12",
        "skill:manual-fields@v13",
        "skill:manual-fields@v14",
        "skill:manual-fields@v15",
        "skill:manual-fields@v16",
        "skill:manual-fields@v17",
        "skill:manual-fields@v18",
        "skill:manual-fields@v19",
        "skill:manual-fields@v2",
        "skill:manual-fields@v20",
        "skill:manual-fields@v21",
        "skill:manual-fields@v22",
        "skill:manual-fields@v23",
        "skill:manual-fields@v24",
        "skill:manual-fields@v25",
        "skill:manual-fields@v26",
        "skill:manual-fields@v27",
        "skill:manual-fields@v3",
        "skill:manual-fields@v4",
        "skill:manual-fields@v5",
        "skill:manual-fields@v6",
        "skill:manual-fields@v7",
        "skill:manual-fields@v8",
        "skill:manual-fields@v9",
        "skill:manual-gates-authority@v1",
        "skill:manual-gates-authority@v10",
        "skill:manual-gates-authority@v11",
        "skill:manual-gates-authority@v12",
        "skill:manual-gates-authority@v13",
        "skill:manual-gates-authority@v14",
        "skill:manual-gates-authority@v15",
        "skill:manual-gates-authority@v16",
        "skill:manual-gates-authority@v17",
        "skill:manual-gates-authority@v18",
        "skill:manual-gates-authority@v19",
        "skill:manual-gates-authority@v2",
        "skill:manual-gates-authority@v20",
        "skill:manual-gates-authority@v21",
        "skill:manual-gates-authority@v22",
        "skill:manual-gates-authority@v23",
        "skill:manual-gates-authority@v24",
        "skill:manual-gates-authority@v25",
        "skill:manual-gates-authority@v26",
        "skill:manual-gates-authority@v27",
        "skill:manual-gates-authority@v3",
        "skill:manual-gates-authority@v4",
        "skill:manual-gates-authority@v5",
        "skill:manual-gates-authority@v6",
        "skill:manual-gates-authority@v7",
        "skill:manual-gates-authority@v8",
        "skill:manual-gates-authority@v9",
        "skill:manual-glossary@v1",
        "skill:manual-glossary@v10",
        "skill:manual-glossary@v11",
        "skill:manual-glossary@v12",
        "skill:manual-glossary@v13",
        "skill:manual-glossary@v14",
        "skill:manual-glossary@v15",
        "skill:manual-glossary@v16",
        "skill:manual-glossary@v17",
        "skill:manual-glossary@v18",
        "skill:manual-glossary@v19",
        "skill:manual-glossary@v2",
        "skill:manual-glossary@v20",
        "skill:manual-glossary@v21",
        "skill:manual-glossary@v22",
        "skill:manual-glossary@v23",
        "skill:manual-glossary@v24",
        "skill:manual-glossary@v25",
        "skill:manual-glossary@v26",
        "skill:manual-glossary@v27",
        "skill:manual-glossary@v3",
        "skill:manual-glossary@v4",
        "skill:manual-glossary@v5",
        "skill:manual-glossary@v6",
        "skill:manual-glossary@v7",
        "skill:manual-glossary@v8",
        "skill:manual-glossary@v9",
        "skill:manual-humans-screens@v1",
        "skill:manual-humans-screens@v10",
        "skill:manual-humans-screens@v11",
        "skill:manual-humans-screens@v12",
        "skill:manual-humans-screens@v13",
        "skill:manual-humans-screens@v14",
        "skill:manual-humans-screens@v15",
        "skill:manual-humans-screens@v16",
        "skill:manual-humans-screens@v17",
        "skill:manual-humans-screens@v18",
        "skill:manual-humans-screens@v19",
        "skill:manual-humans-screens@v2",
        "skill:manual-humans-screens@v20",
        "skill:manual-humans-screens@v21",
        "skill:manual-humans-screens@v22",
        "skill:manual-humans-screens@v23",
        "skill:manual-humans-screens@v24",
        "skill:manual-humans-screens@v25",
        "skill:manual-humans-screens@v26",
        "skill:manual-humans-screens@v27",
        "skill:manual-humans-screens@v3",
        "skill:manual-humans-screens@v4",
        "skill:manual-humans-screens@v5",
        "skill:manual-humans-screens@v6",
        "skill:manual-humans-screens@v7",
        "skill:manual-humans-screens@v8",
        "skill:manual-humans-screens@v9",
        "skill:manual-index@v1",
        "skill:manual-index@v10",
        "skill:manual-index@v11",
        "skill:manual-index@v12",
        "skill:manual-index@v13",
        "skill:manual-index@v14",
        "skill:manual-index@v15",
        "skill:manual-index@v16",
        "skill:manual-index@v17",
        "skill:manual-index@v18",
        "skill:manual-index@v19",
        "skill:manual-index@v2",
        "skill:manual-index@v20",
        "skill:manual-index@v21",
        "skill:manual-index@v22",
        "skill:manual-index@v23",
        "skill:manual-index@v24",
        "skill:manual-index@v25",
        "skill:manual-index@v26",
        "skill:manual-index@v27",
        "skill:manual-index@v3",
        "skill:manual-index@v4",
        "skill:manual-index@v5",
        "skill:manual-index@v6",
        "skill:manual-index@v7",
        "skill:manual-index@v8",
        "skill:manual-index@v9",
        "skill:manual-limits@v1",
        "skill:manual-limits@v10",
        "skill:manual-limits@v11",
        "skill:manual-limits@v12",
        "skill:manual-limits@v13",
        "skill:manual-limits@v14",
        "skill:manual-limits@v15",
        "skill:manual-limits@v16",
        "skill:manual-limits@v17",
        "skill:manual-limits@v18",
        "skill:manual-limits@v19",
        "skill:manual-limits@v2",
        "skill:manual-limits@v20",
        "skill:manual-limits@v21",
        "skill:manual-limits@v22",
        "skill:manual-limits@v23",
        "skill:manual-limits@v24",
        "skill:manual-limits@v25",
        "skill:manual-limits@v26",
        "skill:manual-limits@v27",
        "skill:manual-limits@v3",
        "skill:manual-limits@v4",
        "skill:manual-limits@v5",
        "skill:manual-limits@v6",
        "skill:manual-limits@v7",
        "skill:manual-limits@v8",
        "skill:manual-limits@v9",
        "skill:manual-siblings@v1",
        "skill:manual-siblings@v10",
        "skill:manual-siblings@v11",
        "skill:manual-siblings@v12",
        "skill:manual-siblings@v13",
        "skill:manual-siblings@v14",
        "skill:manual-siblings@v15",
        "skill:manual-siblings@v16",
        "skill:manual-siblings@v17",
        "skill:manual-siblings@v18",
        "skill:manual-siblings@v19",
        "skill:manual-siblings@v2",
        "skill:manual-siblings@v20",
        "skill:manual-siblings@v21",
        "skill:manual-siblings@v22",
        "skill:manual-siblings@v23",
        "skill:manual-siblings@v24",
        "skill:manual-siblings@v25",
        "skill:manual-siblings@v26",
        "skill:manual-siblings@v27",
        "skill:manual-siblings@v3",
        "skill:manual-siblings@v4",
        "skill:manual-siblings@v5",
        "skill:manual-siblings@v6",
        "skill:manual-siblings@v7",
        "skill:manual-siblings@v8",
        "skill:manual-siblings@v9",
        "skill:manual-tools@v1",
        "skill:manual-tools@v10",
        "skill:manual-tools@v11",
        "skill:manual-tools@v12",
        "skill:manual-tools@v13",
        "skill:manual-tools@v14",
        "skill:manual-tools@v15",
        "skill:manual-tools@v16",
        "skill:manual-tools@v17",
        "skill:manual-tools@v18",
        "skill:manual-tools@v19",
        "skill:manual-tools@v2",
        "skill:manual-tools@v20",
        "skill:manual-tools@v21",
        "skill:manual-tools@v22",
        "skill:manual-tools@v23",
        "skill:manual-tools@v24",
        "skill:manual-tools@v25",
        "skill:manual-tools@v26",
        "skill:manual-tools@v27",
        "skill:manual-tools@v3",
        "skill:manual-tools@v4",
        "skill:manual-tools@v5",
        "skill:manual-tools@v6",
        "skill:manual-tools@v7",
        "skill:manual-tools@v8",
        "skill:manual-tools@v9",
        "skill:manual-turn@v1",
        "skill:manual-turn@v10",
        "skill:manual-turn@v11",
        "skill:manual-turn@v12",
        "skill:manual-turn@v13",
        "skill:manual-turn@v14",
        "skill:manual-turn@v15",
        "skill:manual-turn@v16",
        "skill:manual-turn@v17",
        "skill:manual-turn@v18",
        "skill:manual-turn@v19",
        "skill:manual-turn@v2",
        "skill:manual-turn@v20",
        "skill:manual-turn@v21",
        "skill:manual-turn@v22",
        "skill:manual-turn@v23",
        "skill:manual-turn@v24",
        "skill:manual-turn@v25",
        "skill:manual-turn@v26",
        "skill:manual-turn@v27",
        "skill:manual-turn@v3",
        "skill:manual-turn@v4",
        "skill:manual-turn@v5",
        "skill:manual-turn@v6",
        "skill:manual-turn@v7",
        "skill:manual-turn@v8",
        "skill:manual-turn@v9",
        "skill:manual-workspace@v1",
        "skill:manual-workspace@v10",
        "skill:manual-workspace@v11",
        "skill:manual-workspace@v12",
        "skill:manual-workspace@v13",
        "skill:manual-workspace@v14",
        "skill:manual-workspace@v15",
        "skill:manual-workspace@v16",
        "skill:manual-workspace@v17",
        "skill:manual-workspace@v18",
        "skill:manual-workspace@v19",
        "skill:manual-workspace@v2",
        "skill:manual-workspace@v20",
        "skill:manual-workspace@v21",
        "skill:manual-workspace@v22",
        "skill:manual-workspace@v23",
        "skill:manual-workspace@v24",
        "skill:manual-workspace@v25",
        "skill:manual-workspace@v26",
        "skill:manual-workspace@v27",
        "skill:manual-workspace@v3",
        "skill:manual-workspace@v4",
        # The attachments mount: v4 plus the `attachments/` row, the chapter that says what is in
        # that folder and which tool opens each kind of file, and what a sandboxed script may
        # write. The other fourteen chapters re-mint at v5 alongside it, because
        # `head-of-abm@v58` grants `run_python@1` and one profile version pins one manual
        # version for every chapter.
        "skill:manual-workspace@v5",
        "skill:manual-workspace@v6",
        "skill:manual-workspace@v7",
        "skill:manual-workspace@v8",
        "skill:manual-workspace@v9",
        "skill:persona-authoring@v1",
        "skill:persona-authoring@v2",
        "skill:plan-authoring@v1",
        "skill:plan-authoring@v2",
        "skill:research-task@v1",
        "skill:research-task@v2",
        "skill:research-task@v3",
        "skill:research-task@v4",
        # Lexical, not numeric: the folder catalog sorts by address, so v10 sits beside v1.
        "skill:stage0-interview@v10",
        "skill:stage0-interview@v11",
        "skill:stage0-interview@v12",
        "skill:stage0-interview@v13",
        "skill:stage0-interview@v14",
        "skill:stage0-interview@v15",
        "skill:stage0-interview@v16",
        "skill:stage0-interview@v17",
        "skill:stage0-interview@v18",
        "skill:stage0-interview@v19",
        "skill:stage0-interview@v2",
        "skill:stage0-interview@v20",
        "skill:stage0-interview@v21",
        "skill:stage0-interview@v22",
        "skill:stage0-interview@v23",
        "skill:stage0-interview@v24",
        "skill:stage0-interview@v25",
        # The read tools' contract repairs: v25 with the three reads' output digests (and
        # `read_project_accounts`' input digest) re-measured off the typed descriptors.
        "skill:stage0-interview@v26",
        # The read tools' hotfix: v26 with `read_account_research`'s paged/prefixed contract and
        # `read_discovery_run`'s repaired input re-measured, and the §7c/§1 text they need.
        "skill:stage0-interview@v27",
        # The thread workspace: v27 with the §1 bullet that names `scratch/` as the notebook that
        # persists across the turns of one chat.
        "skill:stage0-interview@v28",
        # The workspace libraries: v28 with §1 rewritten around the two read-only mounts —
        # `brand/knowledge/` and the project library at `project/` — instead of the per-turn seeds.
        "skill:stage0-interview@v29",
        "skill:stage0-interview@v3",
        # The brand index path: v29 with §1 naming the brand library's manifest where it is
        # actually mounted — `brand/index.json`, the tree root, beside `knowledge/`.
        "skill:stage0-interview@v30",
        # The operating manual: v30 with §1, §6, §7c and §10 naming the chapter that answers the
        # question the step raises, and §6 no longer claiming an unrouted finalization is refused.
        "skill:stage0-interview@v31",
        # The versioned project root: v31 with §5b, §5c and §6b reduced to pointers at the
        # three document skills, §10 saying the documents are written under `project/`, and
        # the three retired tools gone from its front matter.
        "skill:stage0-interview@v32",
        # Paged and spilled reads: v32 with §7c rewritten as the read map — which read answers
        # which question, pages read to their `next_offset`, a `field_prefix` taken from
        # `prefixes`, and a `spilled_to` receipt read from its own file in chunks — and the four
        # read addresses `head-of-abm@v56` grants in its front matter.
        "skill:stage0-interview@v33",
        # Attached files: v33 with the §1 bullet that names `attachments/` and sends the agent to
        # the code-execution skill before it opens one, and the §7c read-map line for a file.
        "skill:stage0-interview@v34",
        "skill:stage0-interview@v35",
        "skill:stage0-interview@v36",
        "skill:stage0-interview@v37",
        "skill:stage0-interview@v38",
        "skill:stage0-interview@v39",
        "skill:stage0-interview@v4",
        "skill:stage0-interview@v40",
        "skill:stage0-interview@v41",
        "skill:stage0-interview@v42",
        "skill:stage0-interview@v43",
        "skill:stage0-interview@v44",
        "skill:stage0-interview@v45",
        "skill:stage0-interview@v46",
        "skill:stage0-interview@v47",
        "skill:stage0-interview@v48",
        "skill:stage0-interview@v49",
        "skill:stage0-interview@v5",
        "skill:stage0-interview@v50",
        "skill:stage0-interview@v51",
        "skill:stage0-interview@v52",
        "skill:stage0-interview@v53",
        "skill:stage0-interview@v54",
        "skill:stage0-interview@v6",
        "skill:stage0-interview@v7",
        "skill:stage0-interview@v8",
        "skill:stage0-interview@v9",
    ]
    assert [item.ref.address for item in profiles.list()] == [
        "profile:account-research@v1",
        "profile:account-research@v2",
        "profile:account-research@v3",
        "profile:account-research@v4",
        "profile:account-research@v5",
        "profile:content-drafter@v1",
        "profile:content-drafter@v2",
        "profile:content-drafter@v3",
        "profile:content-drafter@v4",
        "profile:content-drafter@v5",
        "profile:design@v1",
        # The account reads: v1 plus `read_project_accounts@1`, `read_account_research@2` and
        # `read_claims@1`, so a 1:1 creative opens the target account's research itself. Nothing
        # else moves — same prompt, same 50 v1 pins, same model and workspace policy.
        "profile:design@v2",
        # web_search@1: v2 plus the open-web search. Nothing else moves.
        "profile:design@v3",
        # read_account_research @2 -> @3: the insights page and the committee. Nothing else moves.
        "profile:design@v4",
        # Wave 2 Lane B: read_cited_claims@1 and design_record_site_section@1. Nothing else moves.
        "profile:design@v5",
        "profile:head-of-abm@v1",
        # Lexical, not numeric: the folder catalog sorts by address, so v10 sits beside v1.
        "profile:head-of-abm@v10",
        "profile:head-of-abm@v11",
        "profile:head-of-abm@v12",
        "profile:head-of-abm@v13",
        "profile:head-of-abm@v14",
        "profile:head-of-abm@v15",
        "profile:head-of-abm@v16",
        "profile:head-of-abm@v17",
        "profile:head-of-abm@v18",
        "profile:head-of-abm@v19",
        "profile:head-of-abm@v2",
        "profile:head-of-abm@v20",
        "profile:head-of-abm@v21",
        "profile:head-of-abm@v22",
        "profile:head-of-abm@v23",
        "profile:head-of-abm@v24",
        "profile:head-of-abm@v25",
        "profile:head-of-abm@v26",
        "profile:head-of-abm@v27",
        "profile:head-of-abm@v28",
        "profile:head-of-abm@v29",
        "profile:head-of-abm@v3",
        "profile:head-of-abm@v30",
        "profile:head-of-abm@v31",
        "profile:head-of-abm@v32",
        "profile:head-of-abm@v33",
        "profile:head-of-abm@v34",
        "profile:head-of-abm@v35",
        "profile:head-of-abm@v36",
        "profile:head-of-abm@v37",
        "profile:head-of-abm@v38",
        "profile:head-of-abm@v39",
        "profile:head-of-abm@v4",
        # v40 (2026-08-27 demo-night model correction) shipped without this line; the list is
        # exhaustive, so its absence was a red assertion, not an omission this catalog tolerates.
        "profile:head-of-abm@v40",
        "profile:head-of-abm@v41",
        "profile:head-of-abm@v42",
        "profile:head-of-abm@v43",
        "profile:head-of-abm@v44",
        # ARV2 Track R, R4: v44 plus `launch_arv2_discovery@1` and stage0-interview v22.
        "profile:head-of-abm@v45",
        # ARV2 context and authoring: v45 plus `author_icp_document@1` and
        # `request_persona_synthesis@1`, and stage0-interview v23.
        "profile:head-of-abm@v46",
        # The project plan: v46 plus `write_project_document@1`, and stage0-interview v24.
        "profile:head-of-abm@v47",
        # The ARV2 reads: v47 plus `read_project_accounts@1`, `read_account_research@1` and
        # `read_discovery_run@1`, and stage0-interview v25.
        "profile:head-of-abm@v48",
        # The read tools' contract repairs: v48 with the three reads re-pinned and
        # stage0-interview v26.
        "profile:head-of-abm@v49",
        "profile:head-of-abm@v5",
        # The read tools' hotfix: v49 with the three reads re-pinned and stage0-interview v27.
        "profile:head-of-abm@v50",
        # The thread workspace: v50 with `scratch/`/`reads/` granted, `work/` dropped, the quota
        # raised for a notebook that persists, and stage0-interview v28.
        "profile:head-of-abm@v51",
        # The workspace libraries: v51 plus the `brand/` and `project/` read-only mounts, with
        # stage0-interview v29 and prompt head-of-abm v9.
        "profile:head-of-abm@v52",
        # The brand index path: v52 with stage0-interview v30.
        "profile:head-of-abm@v53",
        # The operating manual: v53 plus the fifteen `manual-*@v1` chapter pins, with
        # stage0-interview v31 and prompt head-of-abm v10.
        "profile:head-of-abm@v54",
        # The versioned project root: v54 with `project` writable, the three document tools
        # ungranted, the three document skills pinned, stage0-interview v32 and the manual
        # at `manual-*@v2`.
        "profile:head-of-abm@v55",
        # Paged and spilled reads: v55 with `read_account_research@2` / `read_discovery_run@2`
        # replacing their `@1`s, `read_claims@1` and `read_artifact@1` granted, stage0-interview
        # v33, the document skills at v2 and the manual at `manual-*@v3`.
        "profile:head-of-abm@v56",
        # The turn caps move to the founder's numbers: v56's exact surface with `turn_timeout_s`
        # 1800 and `max_model_rounds` 100, and the manual at `manual-*@v4` because its generated
        # `limits` chapter renders both.
        "profile:head-of-abm@v57",
        # The code sandbox and the project's attachments: v57 with `run_python@1` granted,
        # `attachments` on the readable prefixes, `code-execution@v1` pinned, stage0-interview
        # v34, prompt head-of-abm v11 and the manual at `manual-*@v5`.
        "profile:head-of-abm@v58",
        # One ask, many artifacts: v58's exact surface with `open_design_leg@5` (an `artifacts`
        # list in place of the one `title`), prompt head-of-abm v12 and the manual at
        # `manual-*@v6` because its generated `tools` chapter renders the grant.
        "profile:head-of-abm@v59",
        "profile:head-of-abm@v6",
        # The leg's first turn starts itself: v59's exact surface with prompt head-of-abm v13,
        # which no longer tells the user to speak before generation begins, and the manual at
        # `manual-*@v7` because its generated chapters render the profile version in their title.
        "profile:head-of-abm@v60",
        # web_search@1 granted; prompt v14; manual v8.
        "profile:head-of-abm@v61",
        # web_search@1 granted; prompt v15; manual v9 (re-minted on the research-streaming merge).
        "profile:head-of-abm@v62",
        "profile:head-of-abm@v63",
        "profile:head-of-abm@v64",
        # Turn limits become operator settings; prompt v17; manual v11.
        "profile:head-of-abm@v65",
        # Discovery rebuild: exact count, top-up websets, find more is a new run; manual v12.
        "profile:head-of-abm@v66",
        # Briefing v3 drops the one-person trial scope; prompt v18; stage0 v40; manual v13.
        "profile:head-of-abm@v67",
        # Drops three retired-lane tools; stage0 v41; manual v14.
        "profile:head-of-abm@v68",
        # 4 MB workspace files for offloaded history; stage0 v42; manual v15.
        "profile:head-of-abm@v69",
        "profile:head-of-abm@v7",
        # The agent writes the discovery brief: launch_arv2_discovery@2, read_discovery_run@3;
        # stage0 v43; manual v16; recipe 33.
        "profile:head-of-abm@v70",
        # Product management: manage_products@1; stage0 v44; manual v17; recipe 34 (main).
        "profile:head-of-abm@v71",
        # The website line, never in production (its own v71 was the design leg's first turn and
        # overview paging): page briefs give Design direction, not copy; stage0 v45; manual v18.
        "profile:head-of-abm@v72",
        # The website line: for an ad, a suggested headline is only a suggestion; stage0 v46;
        # manual v19.
        "profile:head-of-abm@v73",
        # The website release on main's v71: v73's surface plus manage_products@1; stage0 v47;
        # manual v20; recipe 34.
        "profile:head-of-abm@v74",
        "profile:head-of-abm@v75",
        "profile:head-of-abm@v76",
        "profile:head-of-abm@v77",
        "profile:head-of-abm@v78",
        "profile:head-of-abm@v79",
        "profile:head-of-abm@v8",
        "profile:head-of-abm@v80",
        "profile:head-of-abm@v81",
        "profile:head-of-abm@v9",
        "profile:onboarding-synthesis@v1",
        "profile:onboarding-synthesis@v2",
        "profile:onboarding-synthesis@v3",
        "profile:onboarding-synthesis@v4",
        "profile:research-specialist@v1",
        "profile:research-specialist@v2",
        "profile:research-specialist@v3",
        "profile:research-specialist@v4",
        "profile:research-specialist@v5",
        "profile:research-specialist@v6",
        "profile:research-specialist@v7",
        "profile:reviewer@v1",
        "profile:reviewer@v2",
        "profile:reviewer@v3",
        "profile:reviewer@v4",
        "profile:reviewer@v5",
    ]
    stage0 = skills.get("stage0-interview", "v2")
    assert "Only a human confirms" in stage0.body
    assert "confirm_project_product@1" not in {pin.address for pin in stage0.required_tools}
    assert "override_stage0_readiness@1" not in {pin.address for pin in stage0.required_tools}
    with pytest.raises(AgentCatalogError, match="unavailable"):
        prompts.get("head-of-abm", "latest")
    with pytest.raises(AgentCatalogError, match="digest changed"):
        prompts.get("head-of-abm", "v1", expected_sha256="0" * 64)


def test_stage0_v2_is_additive_and_does_not_mutate_the_used_v1_resource() -> None:
    assert hashlib.sha256(LEGACY_STAGE0.read_bytes()).hexdigest() == (
        "15576f389fb328dfc519d3b497584581181df281f80c9c6ef66cd2acd7e65461"
    )
    stage0_v2 = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v2"
    )
    assert stage0_v2.ref.sha256 == (
        "9ad718c63c913eea88ad1dd566e56a0ace4d8226341ce2072ec9cb06d4959b4f"
    )
    stage0_v3 = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v3"
    )
    assert stage0_v3.ref.sha256 == (
        "f9d069be847cfd972316a76c57f234c70c57157d13947efd55a38014abc447b7"
    )


def test_integration_preserves_pilot_history_and_mints_combined_resources() -> None:
    historical_hashes = {
        "profiles/head-of-abm/v24/profile.yaml": (
            "709e1d88715aed50220111a1e9025d78f53c97ae61096f869ac3cb1b8eb441de"
        ),
        "profiles/head-of-abm/v25/profile.yaml": (
            "ad088f21c29c1d4399ef75c17963a43d6d6051f36540864ef162dab580cae5f2"
        ),
        "skills/stage0-interview/v11/SKILL.md": (
            "aa9ad3f354bcc40b6b8ff85a2ed1cb7b4c7d7c9e1501b86fa9c68766ec1012bd"
        ),
        "skills/stage0-interview/v12/SKILL.md": (
            "2209ba1daac992285d608fbf287f82604355bf876c700d2e15b46df945fc6ea1"
        ),
    }
    for relative_path, expected_sha256 in historical_hashes.items():
        assert hashlib.sha256((CATALOG_ROOT / relative_path).read_bytes()).hexdigest() == (
            expected_sha256
        )

    recipe_root = CATALOG_ROOT.parents[1] / "execution" / "recipes"
    for filename, expected_sha256 in {
        "recipe0-stage0-v7.json": (
            "67d86848497a9f6e884961eb31f127d70a32578c10e5c07cc80272fb7a539c7a"
        ),
        "recipe0-stage0-v8.json": (
            "cbe23f9a48caa5e7672c0ddbbad9f7f5604b4c84d6b2030da0661784e771fe8e"
        ),
    }.items():
        assert hashlib.sha256((recipe_root / filename).read_bytes()).hexdigest() == expected_sha256

    profiles = FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True))
    profile = profiles.get("head-of-abm", "v35").definition
    assert [(item.name, item.version) for item in profile.skills] == [
        ("stage0-interview", "v20"),
        ("account-deep-steering", "v6"),
    ]
    required_tools = {
        "evaluate_stage0_readiness@2",
        "synthesize_icps@3",
        "open_icp_confirmation_gate@1",
        "launch_selected_account_research@1",
        "list_client_knowledge@2",
        "inspect_client_claim@2",
        "list_product_knowledge@1",
        "inspect_product_claim@1",
        "open_product_selection_gate@1",
        "open_discovery_configuration_gate@1",
        "start_confirmed_project_run@3",
    }
    assert required_tools <= {f"{item.name}@{item.version}" for item in profile.tools}

    recipe = json.loads((recipe_root / "recipe0-stage0-v15.json").read_text())
    assert recipe["version"] == 15
    assert required_tools <= set(recipe["graph"]["tool_allowlist"])

    skill = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v20"
    )
    assert "`finalize_turn.user_message`" in skill.body
    assert "normal assistant response" in skill.body
    assert "Do not place that synthesis inside the approval" in skill.body
    assert "explicitly requests a different bounded account count" in skill.body
    assert "newest approved exact scope overrides" in skill.body


def test_catalog_rejects_unknown_metadata_and_mutable_aliases(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    prompt = copied / "prompts/head-of-abm/v1/SYSTEM.md"
    prompt.write_text(
        prompt.read_text().replace(
            "framework: deepagents",
            "unexpected_policy: true\nframework: deepagents",
        )
    )
    with pytest.raises(AgentCatalogError, match="metadata is invalid"):
        FolderPromptCatalog((copied / "prompts").resolve(strict=True))

    shutil.rmtree(copied)
    shutil.copytree(CATALOG_ROOT, copied)
    shutil.copytree(
        copied / "skills/stage0-interview/v2",
        copied / "skills/stage0-interview/latest",
    )
    with pytest.raises(AgentCatalogError, match="not immutable"):
        FolderSkillCatalog((copied / "skills").resolve(strict=True))


@pytest.mark.parametrize("attack", ["symlink", "executable", "extra"])
def test_catalog_rejects_link_executable_and_extra_files(
    tmp_path: Path,
    attack: str,
) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    resource = copied / "prompts/head-of-abm/v1/SYSTEM.md"
    if attack == "symlink":
        target = tmp_path / "outside.md"
        target.write_text("outside")
        resource.unlink()
        resource.symlink_to(target)
    elif attack == "executable":
        resource.chmod(0o755)
    else:
        (resource.parent / "unexpected.txt").write_text("extra")

    with pytest.raises(AgentCatalogError):
        FolderPromptCatalog((copied / "prompts").resolve(strict=True))


def test_profile_and_resource_folder_identity_must_match(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    profile = copied / "profiles/reviewer/v1/profile.yaml"
    profile.write_text(profile.read_text().replace("name: reviewer", "name: other"))
    with pytest.raises(AgentCatalogError, match="differs from its folder"):
        FolderProfileCatalog((copied / "profiles").resolve(strict=True))
