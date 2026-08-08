"""Lane D slice D2: the HTTP process cannot reach the model gateway.

Ratified §6-D1 rejected gateway-in-HTTP: a production turn is executed by the fleet worker, and the
web process only captures and queues it. That is a *structural* claim, so this is a structural
test — not "we didn't mean to", but "the code that serves a turn has no path to a gateway, a model
provider, or the deepagent runtime that uses them".

Two independent guards, because they fail differently:

1. **Import reachability.** Starting from the chat surface and the two modules its turn route
   depends on, follow every first-party ``clue_api`` import transitively and assert none of them
   names anything model-shaped. This is what stops the next slice from "just importing" the turn
   engine into the route and running the model inline.
2. **Composition.** The HTTP composition root (:mod:`clue_api.projections_main`) builds the
   toolbelt with **no gateway argument at all**, so the registry it serves cannot spend on a model
   even if a route asked it to. Asserted against the call site's AST rather than by running it.

The boundary this test deliberately does *not* claim: ``clue_toolbelt`` itself imports
``clue_gateway`` (its LLM-backed tools are typed against it), so ``clue_gateway`` is present in the
web process's module graph today and a "not in ``sys.modules``" assertion would be false. That is
pre-existing and not D2's to change; what D2 owns — and what this pins — is that no *gateway
instance* is composed and no chat-surface module reaches for one.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import clue_api
from clue_api.toolbelt_wiring import build_toolbelt

_API_ROOT = Path(clue_api.__file__).resolve().parent

#: Where a turn request actually goes: the chat package plus the two modules its POST route calls.
_ENTRYPOINTS = (
    "clue_api.chat.router",
    "clue_api.chat.schemas",
    "clue_api.chat.principal",
    "clue_api.conversation_capture",
    "clue_api.agent_turn_submission",
)

#: Modules that own, build, or run a model. None of them may be reachable from a turn route.
_FORBIDDEN_MODULES = frozenset(
    {
        "clue_gateway",
        "clue_api.agent_model_wiring",
        "clue_api.agent_platform_wiring",
        "clue_api.agent_runtime_wiring",
        "clue_api.agent_turn_fleet_wiring",
        "clue_api.conversation_turns",
        "clue_api.head_of_abm_wiring",
        "clue_api.run_composition",
        "clue_api.stage0_trial",
        "clue_api.toolbelt_wiring",
    }
)

#: Names that mean "a gateway is being built or held", wherever they are imported from.
_FORBIDDEN_NAMES = frozenset(
    {
        "AgentModelProvider",
        "LLMGateway",
        "build_agent_model_provider",
        "build_conversation_turn_engine",
        "build_platform_gateway",
        "build_toolbelt",
    }
)


def _module_path(module: str) -> Path | None:
    if not module.startswith("clue_api"):
        return None
    relative = module.removeprefix("clue_api").lstrip(".").replace(".", "/")
    candidate = _API_ROOT / f"{relative}.py"
    return candidate if candidate.exists() else None


def _imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Every module and imported name an AST references, including inside functions."""

    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            names.update(alias.name for alias in node.names)
    return modules, names


def test_no_module_serving_a_turn_can_reach_a_model() -> None:
    """Follow the turn route's whole first-party import graph and find nothing model-shaped."""

    seen: set[str] = set()
    frontier = list(_ENTRYPOINTS)
    violations: list[str] = []
    while frontier:
        module = frontier.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(module)
        if path is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules, names = _imports(tree)
        for imported in sorted(modules):
            if imported in _FORBIDDEN_MODULES:
                violations.append(f"{module} imports {imported}")
            if imported.startswith("clue_api"):
                frontier.append(imported)
        for name in sorted(names & _FORBIDDEN_NAMES):
            violations.append(f"{module} imports the name {name}")

    assert violations == [], violations
    # The walk must actually have gone somewhere — an empty graph would pass vacuously.
    assert "clue_api.agent_turn_wiring" in seen


def test_the_http_composition_root_builds_a_toolbelt_with_no_gateway() -> None:
    """The web process composes no gateway instance, so no route can spend through one."""

    # A gateway is opt-in at the toolbelt seam; the default is genuinely "there isn't one".
    assert inspect.signature(build_toolbelt).parameters["gateway"].default is None

    source = (_API_ROOT / "projections_main.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_toolbelt"
    ]
    assert calls, "projections_main must still compose the toolbelt"
    for call in calls:
        supplied = {keyword.arg for keyword in call.keywords}
        assert "gateway" not in supplied, "the HTTP process must not compose a model gateway"
        assert not any(keyword.arg is None for keyword in call.keywords), (
            "a **kwargs splat could smuggle a gateway past this guard"
        )
