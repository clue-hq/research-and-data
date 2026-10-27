"""Capture the exact first-call system prompt + tool descriptions of the site agent, offline
(scripted model, no model spend), plus the workspace files it starts with.
Run from subsystems/clue-design/apps/agent_runtime:
  PYTHONPATH=.:../api:tests ../../../../.venv/bin/python ../../../../docs/site-harness-alignment/capture.py <out_dir> <tmp_dir>
Captures the live-site variant (production publishes live sites) with research/claims.md present;
the no-claims variant's two swapped lines are ledgered from harness.py.
"""
import json, sys
from pathlib import Path
from langchain_core.messages import AIMessage
from site_fixtures import ScriptedModel, garner_site, inputs_for
from lumen_agent.site.harness import build_site_agent
from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace

out, tmp = Path(sys.argv[1]), Path(sys.argv[2])
seen, bound = [], []

class Recording(ScriptedModel):
    def bind_tools(self, tools, **kwargs):
        bound.extend(tools)
        return self
    def _generate(self, messages, *a, **k):
        seen.append(messages)
        return super()._generate(messages, *a, **k)

ws = tmp / "workspace"
inputs = inputs_for(live_sites=True)
site = garner_site()
materialize_workspace(ws, inputs, site=site)
(ws / "research").mkdir(exist_ok=True)
(ws / "research" / "claims.md").write_text("# claims\n")
tools = SiteTools(workspace=ws, inputs=inputs, base_site=site, retry_delay_s=0)
agent, _, _ = build_site_agent(tools, model=Recording(messages=iter([AIMessage(content="done")])),
                               model_id="openai:openai/gpt-6.1-sol", live=True)
agent.invoke({"messages": [{"role": "user", "content": "build"}]}, {"configurable": {"thread_id": "cap"}})
system = seen[0][0].text
(out / "system_prompt_first_call.txt").write_text(system)
schemas = []
for t in bound:
    if hasattr(t, "name"):
        args = getattr(t, "args", {}) or {}
        schemas.append({"name": t.name, "description": t.description,
                        "args": {k: (v or {}).get("description") for k, v in args.items()}})
    else:
        schemas.append(t)
(out / "tool_schemas.json").write_text(json.dumps(schemas, indent=1))
files = sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file())
(out / "workspace_files.txt").write_text("\n".join(files) + "\n")
print(len(system), len(schemas), sum(len(s.get("description") or "") for s in schemas), len(files))
