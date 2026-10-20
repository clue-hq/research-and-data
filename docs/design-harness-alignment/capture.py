"""Capture the exact first-call system prompt + tool schemas of the solo scene agent, offline.
Run from subsystems/clue-design/apps/agent_runtime:
  PYTHONPATH=.:../api ../../../../.venv/bin/python ../../../../docs/design-harness-alignment/capture.py <out_dir> <tmp_dir>
"""
import json, sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, "tests")
import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from langchain_core.messages import AIMessage
from test_scene_catalog_runtime import ScriptedModel
from lumen_agent import harness
from lumen_agent.workspace import initial_turn_state
from lumen_agent import llm, tools as _t
import lumen_agent.tools.substrate as substrate

out = Path(sys.argv[1]); tmp = Path(sys.argv[2])
substrate.CoreClient = FakeCoreClient
built = []
def build(model_id, **kw):
    m = ScriptedModel(responses=[AIMessage(content="done")]); m.seen = []; built.append(m); return m
llm.init_model = build
llm.assert_model_supports_image_input = lambda *a, **k: None
config = replace(runtime_config(tmp), scene_solo=True, scene_skill_bundle="candidate", fast_loop=True)
prompt = "Make the whole ad feel more premium."
graph, tools = harness.create_design_deepagent(prompt, config)
graph.invoke(initial_turn_state(tools, prompt) | {"messages": [("human", prompt)]}, {"configurable": {"thread_id": "cap"}})
m = built[0]
system = m.seen[0][0].text
(out / "system_prompt_first_call.txt").write_text(system)
schemas = []
for t in m.first_bound_tools:
    if hasattr(t, "name"):
        args = getattr(t, "args", {}) or {}
        schemas.append({"name": t.name, "description": t.description,
                        "args": {k: v.get("description") for k, v in args.items()}})
    else:
        schemas.append(t)
(out / "tool_schemas.json").write_text(json.dumps(schemas, indent=1))
print(len(system), len(schemas), sum(len(s.get("description") or "") for s in schemas))
