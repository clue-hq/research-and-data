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
   toolbelt with **no gateway argument at all**, so the *tool registry it serves a turn from*
   cannot spend on a model even if a route asked it to. Asserted against the call site's AST rather
   than by running it.

The boundary this test deliberately does *not* claim: ``clue_toolbelt`` itself imports
``clue_gateway`` (its LLM-backed tools are typed against it), so ``clue_gateway`` is present in the
web process's module graph today and a "not in ``sys.modules``" assertion would be false. That is
pre-existing and not D2's to change.

**Nor — since slice 3 — does it claim that the web process composes no gateway instance at all.**
The D2 acceptance criterion was written as "the HTTP process never touches the gateway"
(``docs/specs/FI-lane-D-production-chat-and-launch.md:248``), and that was literally true until the
Stage-0 recon exception landed: ``projections_main`` now builds one gateway for the Stage-0 scrape
resolver's claim extractor (:func:`clue_api.run_composition.build_optional_platform_gateway` →
:class:`clue_api.claim_extraction.LlmClaimExtractor`), because ratified slice-3 scope runs recon's
fast lane in this process — ``start_recon`` is invocable through the projections ``/tools`` route.
So the prose here is narrowed to the two things these guards actually enforce, both still true and
both still what the D2 *rationale* protects (a turn is executed by the fleet worker, not inline in
the web process):

* the toolbelt seam carries no ``gateway=`` — no *tool* the turn path can invoke holds one;
* no turn-serving module reaches a gateway, a model provider, or the turn engine — the
  ``_ENTRYPOINTS`` walk never reaches ``projections_main``, so the Stage-0 exception is
  unreachable from a turn.

A *second* gateway consumer in this process would need the same explicit treatment: name it here,
or the guard is documenting a lie again.

To be exact about what guard 1 is: it is a **lexical** reachability guard over the import
statements turn-serving code writes, not a claim about ``sys.modules``. ``clue_api/__init__.py`` is
an eager re-export package — importing *anything* under ``clue_api`` executes ~38 submodule
imports, two of which (``run_composition``, ``head_of_abm_wiring``) are on the forbidden list
below. That is the same pre-existing condition the ``clue_gateway`` paragraph above concedes, and
it is why the enforceable version of "no path to a model" is "no turn-serving module *names* one",
which is exactly what stops the next slice from calling one.

**Type-only edges are not traversed (reconciled with Lane E, comprehensive-research merge).**
An ``if TYPE_CHECKING:`` block is a leaf in the walk: nothing in it is executed, so no code a turn
runs can reach *through* it. This matters because the turn route legitimately reaches
:mod:`clue_api.account_research_fleet` (via :mod:`clue_api.transactional_account_launch`, the
one-act approval+launch transaction, which composes no gateway/provider/agent), and that module
annotates Lane E's ``ProseSynthesisStep`` under ``TYPE_CHECKING`` precisely because the runtime
edge would be circular — the real dependency runs the other way, ``prose_synthesis_step`` imports
the fleet projection. Traversing that annotation charged the turn path with Lane E's
``prose_synthesis_tools``/``value_narrative_tools`` (both merely *typed* against ``LLMGateway``,
both handed their gateway by the *fleet* composition root), which no turn code can call.

The narrowing is only in *traversal*. A forbidden module or a gateway-shaped name imported by a
module the walk does reach is still a violation wherever it appears — including inside that
module's own ``TYPE_CHECKING`` block, because turn-serving code that needs to *name* a gateway is
already the thing this guard is looking for. And a function-local ``import`` is not type-only, so
the "import the turn engine inside the handler" dodge is still caught.
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
    # FI Lane D D3: the turn stream serves attach/stop/retry/cold-load from the same web process.
    # It reads a durable outbox the *worker* writes, so the same rule binds it: nothing on this
    # side of the seam may reach a gateway, a model provider, or the turn engine.
    "clue_api.chat.stream",
    "clue_api.chat.turn_events",
    "clue_api.chat.turn_controls",
    "clue_api.chat.message_bodies",
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
    """Every module and imported name an AST references, including inside functions.

    Deliberately includes ``if TYPE_CHECKING:`` bodies: naming a gateway is itself the signal.
    """

    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            names.update(alias.name for alias in node.names)
    return modules, names


def _is_type_checking_test(test: ast.expr) -> bool:
    """``TYPE_CHECKING`` or ``typing.TYPE_CHECKING`` — the two ways the repo spells the guard."""

    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _runtime_imported_modules(tree: ast.AST) -> set[str]:
    """The modules a module actually imports *when it runs* — ``TYPE_CHECKING`` bodies excluded.

    This is what the graph walk follows, so a type-only edge is a leaf (see the module docstring).
    The ``else:`` branch of a ``TYPE_CHECKING`` guard *is* runtime code, so it is still descended.
    """

    modules: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            # The body is erased at runtime; the ``else:`` branch is what actually executes.
            for fallback in node.orelse:
                visit(fallback)
            return
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return modules


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
        # Only runtime edges extend the graph: a ``TYPE_CHECKING`` import is never executed by
        # the web process, so nothing behind it is reachable from a turn.
        for imported in sorted(_runtime_imported_modules(tree)):
            if imported.startswith("clue_api"):
                frontier.append(imported)
        for name in sorted(names & _FORBIDDEN_NAMES):
            violations.append(f"{module} imports the name {name}")

    assert violations == [], violations
    # The walk must actually have gone somewhere — an empty graph would pass vacuously.
    assert "clue_api.agent_turn_wiring" in seen
    # And it must have gone through the comprehensive-research merge's one-act launch
    # transaction, stopping exactly at Lane E's type-only annotation edge. If the first of these
    # ever fails the exclusion below has become vacuous; if the second fails, something made the
    # prose/value-narrative synthesis modules genuinely loadable from a turn.
    assert "clue_api.account_research_fleet" in seen
    assert "clue_api.prose_synthesis_step" not in seen


def test_the_http_composition_root_builds_a_toolbelt_with_no_gateway() -> None:
    """The web process's *tool registry* holds no gateway, so no route can spend through a tool.

    Not "the web process composes no gateway instance" — since slice 3 it composes exactly one, for
    the Stage-0 scrape resolver's claim extractor (see the module docstring). What is pinned is the
    seam a turn would have to travel: ``build_toolbelt`` is called with no ``gateway=``.
    """

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
        assert "gateway" not in supplied, (
            "the HTTP process's toolbelt must not be handed a model gateway (the Stage-0 scrape "
            "extractor is the one sanctioned gateway consumer here, and it is not a tool seam)"
        )
        assert not any(keyword.arg is None for keyword in call.keywords), (
            "a **kwargs splat could smuggle a gateway past this guard"
        )


def test_the_walk_follows_runtime_edges_only_and_still_sees_function_local_imports() -> None:
    """Guard the guard: the ``TYPE_CHECKING`` carve-out is exactly that and nothing wider."""

    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "import runtime_top_level\n"
        "if TYPE_CHECKING:\n"
        "    import type_only\n"
        "else:\n"
        "    import runtime_fallback\n"
        "def handler():\n"
        "    import runtime_local\n"
    )

    runtime = _runtime_imported_modules(tree)
    assert "type_only" not in runtime
    # A function body is executed, so the "import it inside the handler" dodge is still followed.
    assert {"runtime_top_level", "runtime_fallback", "runtime_local"} <= runtime
    # Detection is still total: naming something forbidden under ``TYPE_CHECKING`` is a violation.
    modules, _ = _imports(tree)
    assert "type_only" in modules
