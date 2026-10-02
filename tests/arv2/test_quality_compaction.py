"""Deep Agents' own middleware archives and reopens history on the real workspace."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from clue_agents import ScriptedAgentChatModel
from clue_api.arv2.quality_views import research_backend
from clue_storage.fs import FsStorage
from tests.agents.workspace_helpers import make_workspace, policy
from tests.arv2.test_account_exa_brief import scope


def test_native_compaction_appends_recoverable_history_and_preserves_permissions(
    tmp_path, monkeypatch
):
    async def case():
        harness = make_workspace(
            tmp_path,
            active_policy=policy(
                max_total_bytes=10485760,
                max_file_bytes=1048576,
                max_file_count=200,
                readable=("work", "outputs", "context", "evidence", "research"),
                writable=("work", "outputs"),
            ),
        )

        @asynccontextmanager
        async def no_database():
            raise AssertionError("work files should not require evidence DB access")
            yield

        backend = research_backend(
            harness.lease.backend, no_database, FsStorage(tmp_path / "blobs"), scope(14), uuid4()
        )
        model = ScriptedAgentChatModel(
            responses=[AIMessage(content="First summary"), AIMessage(content="Second summary")]
        )
        middleware = SummarizationMiddleware(
            model, backend=backend, trigger=("messages", 3), keep=("messages", 1)
        )
        monkeypatch.setattr(middleware, "_get_thread_id", lambda: "test-thread")
        seen = []

        async def handler(request):
            seen.extend(request.messages)
            return ModelResponse(result=[AIMessage(content="Continue")])

        messages = [
            HumanMessage(content="Original source detail A"),
            AIMessage(content="Original analysis A"),
            HumanMessage(content="Recent question"),
        ]
        try:
            first = await middleware.awrap_model_call(
                ModelRequest(
                    model=model, messages=messages, state={"messages": messages}, tools=[]
                ),
                handler,
            )
            event = first.command.update["_summarization_event"]
            path = "/work/conversation_history/test-thread.md"
            assert event["file_path"] == path
            assert path in str(event["summary_message"].content)
            archive = await backend.aread(path)
            assert archive.error is None
            original = archive.file_data["content"]
            assert "Original source detail A" in original and "Original analysis A" in original
            messages += [
                AIMessage(content="New source detail B"),
                HumanMessage(content="Next question"),
            ]
            second = await middleware.awrap_model_call(
                ModelRequest(
                    model=model,
                    messages=messages,
                    state={"messages": messages, "_summarization_event": event},
                    tools=[],
                ),
                handler,
            )
            assert second.command.update["_summarization_event"]["file_path"] == path
            appended = (await backend.aread(path)).file_data["content"]
            assert appended.startswith(original) and "New source detail B" in appended
            tool = FilesystemMiddleware(backend=backend)._create_read_file_tool()
            read = await tool.coroutine(
                file_path=path,
                runtime=SimpleNamespace(tool_call_id="recover-history"),
                offset=0,
                limit=2000,
            )
            assert read.status == "success" and "Original source detail A" in read.content
            assert not (await backend.awrite("/work/notes.md", "First note")).error
            assert not (await backend.aedit("/work/notes.md", "First", "Updated")).error
            assert not (await backend.awrite("/outputs/report.md", "Research output")).error
            for bad in [
                "/conversation_history/blocked.md",
                "/etc/passwd",
                "/work/../../outside.md",
                "/context/injected.md",
            ]:
                assert (await backend.awrite(bad, "blocked")).error
            assert (await backend.aread("/etc/passwd")).error
        finally:
            harness.close()

    asyncio.run(case())
