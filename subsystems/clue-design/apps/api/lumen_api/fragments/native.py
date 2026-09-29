"""Declared platform dependencies of a checked vocabulary repair.

This is an internal custody seam, never a model/tool argument. Captured HTML,
classes and scripts cannot opt into a controller. The first supported native
dependency is tabs; other built-ins refuse library minting until their instance
identity and style/behavior preservation are qualified.
"""
from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from .refs import FragmentRefused

_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")


def _refuse(message: str) -> None:
    raise FragmentRefused("fragment.native_dependency_unsupported", message)


def native_dependencies_for_subtree(
    doc: dict[str, Any], page_id: str, root_id: str,
) -> dict[str, Any] | None:
    """Read only the subtree accepted by the engine, not the submitted HTML."""
    page = next((p for p in doc.get("pages", []) if p.get("id") == page_id), None)
    nodes = page.get("nodes", {}) if page else {}
    pending, seen, tabs = [root_id], set(), []
    while pending:
        node_id = pending.pop()
        if node_id in seen or node_id not in nodes:
            _refuse("native repair requires one complete, nonduplicated typed subtree")
        seen.add(node_id)
        node = nodes[node_id]
        pending.extend(reversed(node.get("children", [])))
        kind = node.get("kind")
        if kind in {"custom_component", "embed", "fragment"} or (
            kind == "button" and ("command" in node or "command_target" in node)
        ):
            _refuse(f"{kind} dependencies cannot yet be preserved in a reusable native repair")
        if kind != "component":
            continue
        if node.get("component") != "tabs":
            _refuse(f"native {node.get('component')} is not yet supported in reusable repairs")
        items = []
        for child_id in node.get("children", []):
            child = nodes.get(child_id, {})
            children = child.get("children", [])
            if (child.get("kind") == "container" and len(children) >= 2
                    and nodes.get(children[0], {}).get("kind") == "text"):
                items.append({"tab_id": f"{child_id}_tab", "panel_id": f"{child_id}_panel"})
        tabs.append({"root_id": f"lumen-tabs-{node_id}", "items": items})
    return {"version": 1, "platform_runtime": 2, "tabs": tabs} if tabs else None


def validate_native_dependencies(html: str, value: Any) -> dict[str, Any]:
    """Validate exact owned targets after sanitization, and again at read time.

    Duplicate IDs, nested foreign controls and broken ARIA links refuse. Nested
    *declared* tabs are allowed; ownership is their closest declared root.
    """
    if not isinstance(value, dict) or set(value) != {"version", "platform_runtime", "tabs"}:
        _refuse("unknown native dependency descriptor")
    if value["version"] != 1 or value["platform_runtime"] != 2:
        _refuse("unsupported native dependency/runtime version")
    tabs = value["tabs"]
    if not isinstance(tabs, list) or not 1 <= len(tabs) <= 32:
        _refuse("native repair requires 1–32 declared tab groups")
    expected: set[str] = set()
    for group in tabs:
        if not isinstance(group, dict) or set(group) != {"root_id", "items"}:
            _refuse("invalid native tab group")
        items = group["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 64:
            _refuse("native tab group requires 1–64 items")
        ids = [group["root_id"]]
        for item in items:
            if not isinstance(item, dict) or set(item) != {"tab_id", "panel_id"}:
                _refuse("invalid native tab item")
            ids.extend([item["tab_id"], item["panel_id"]])
        for identity in ids:
            if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in expected:
                _refuse("native target IDs must be safe and unique")
            expected.add(identity)
    tree = HTMLParser(html)
    by_id: dict[str, Any] = {}
    for node in tree.css("[id]"):
        identity = node.attributes["id"]
        if identity in expected:
            if identity in by_id:
                _refuse(f"native target {identity} is duplicated")
            by_id[identity] = node
    if set(by_id) != expected:
        _refuse("native repair lost one or more declared targets")
    root_ids = {g["root_id"] for g in tabs}

    def owner(node):
        parent = node.parent
        while parent is not None:
            if parent.attributes.get("id") in root_ids:
                return parent.attributes["id"]
            parent = parent.parent
        return None

    for group in tabs:
        root = by_id[group["root_id"]]
        if root.tag != "div" or "lumen-tabs" not in root.attributes.get("class", "").split():
            _refuse("declared native tab root has changed shape")
        owned = [n for n in root.css('[role="tab"], [role="tabpanel"]')
                 if owner(n) == group["root_id"]]
        if {n.attributes.get("id") for n in owned} != {
            v for item in group["items"] for v in item.values()
        }:
            _refuse("undeclared controls appeared in a native tab group")
        for item in group["items"]:
            tab, panel = by_id[item["tab_id"]], by_id[item["panel_id"]]
            if (tab.tag != "button" or tab.attributes.get("role") != "tab"
                    or panel.attributes.get("role") != "tabpanel"
                    or tab.attributes.get("aria-controls") != item["panel_id"]
                    or panel.attributes.get("aria-labelledby") != item["tab_id"]
                    or tab.parent.attributes.get("role") != "tablist"
                    or tab.parent.parent != root or panel.parent != root):
                _refuse("native tab controls/panels lost their local relationship")
    return value


def native_render_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Carry validated dependencies through every existing render/package seam."""
    value = payload.get("native_dependencies")
    if value is None:
        return {}
    return {"native_dependencies": validate_native_dependencies(payload["html"], value)}
