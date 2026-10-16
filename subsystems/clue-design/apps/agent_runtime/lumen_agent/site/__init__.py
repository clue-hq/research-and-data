"""The Puck site agent (website agent on Puck, Lane B): harness, tools, workspace, prompt, skills.

Ported from the spike in trials/puck-spike/agent/. The runtime never reads the database: the
design API builds a `SiteTurnInputs` (inputs.py) and hands it to `harness.run_site_turn`.
"""
