"""C6.0 proof of isolated, durable, artifact-backed deepagent file behavior."""

from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from tests.agents.artifact_backend_spike import (
    ArtifactBackedDeepagentsSpikeBackend,
    InMemoryArtifactStore,
)
from tests.agents.test_deepagents_spike import ScriptedToolCallingModel


def test_deepagent_uses_relative_model_paths_in_artifact_backed_isolated_scope() -> None:
    store = InMemoryArtifactStore()
    backend = ArtifactBackedDeepagentsSpikeBackend(store, root_id="ws-1/project-1/execution-1")
    tool_messages: list[str] = []

    def respond(messages: list[BaseMessage]) -> AIMessage:
        observed_tools = [message for message in messages if isinstance(message, ToolMessage)]
        tool_messages[:] = [str(message.content) for message in observed_tools]
        if not observed_tools:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "work/report.md",
                            "content": "artifact-backed result",
                        },
                        "id": "write-1",
                        "type": "tool_call",
                    }
                ],
            )
        if len(observed_tools) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "work/report.md"},
                        "id": "read-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="Workspace artifact verified.")

    model = ScriptedToolCallingModel(respond)
    graph = create_deep_agent(
        model=model,
        tools=[],
        system_prompt="Use relative virtual paths only.",
        backend=backend,
        name="c6-artifact-workspace-spike",
    )

    result = graph.invoke({"messages": [{"role": "user", "content": "Write the result."}]})

    assert backend.virtual_mode is True
    assert {"write_file", "read_file"}.issubset(model.bound_tool_names)
    assert result["messages"][-1].content == "Workspace artifact verified."
    assert any("artifact-backed result" in message for message in tool_messages)
    assert not hasattr(backend, "execute")

    # A new backend instance over the same artifact namespace recovers the durable work.
    resumed = ArtifactBackedDeepagentsSpikeBackend(
        store,
        root_id="ws-1/project-1/execution-1",
    )
    recovered = resumed.read("work/report.md")
    assert recovered.file_data is not None
    assert recovered.file_data["content"] == "artifact-backed result"

    # Another execution over the same content store cannot observe the scoped index.
    isolated = ArtifactBackedDeepagentsSpikeBackend(
        store,
        root_id="ws-1/project-1/execution-2",
    )
    assert isolated.read("work/report.md").error == "file_not_found"


def test_artifact_backend_rejects_read_only_code_and_traversal_writes() -> None:
    backend = ArtifactBackedDeepagentsSpikeBackend(
        InMemoryArtifactStore(),
        root_id="ws-1/project-1/execution-1",
    )

    assert backend.write("context/project.json", "{}").error.startswith("permission_denied")
    assert backend.write("work/exploit.py", "print('no')").error.startswith("permission_denied")
    assert backend.write("../outside/report.md", "no").error.startswith("invalid_path")
