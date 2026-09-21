"""Review coverage must remain truthful when source bands share a layout envelope."""
from lumen_api.fragments.render import web_doc_page_section_count


def _doc(nodes):
    return {"pages": [{"id": "page", "root": "root", "nodes": nodes}]}


def test_nested_source_flow_does_not_collapse_eight_bands_into_one():
    nodes = {
        "root": {"kind": "container", "children": ["envelope", "authored"]},
        "envelope": {"kind": "section", "children": ["context"]},
        "context": {"kind": "container", "children": [f"s{i}" for i in range(8)]},
        "authored": {"kind": "section", "children": ["text"]},
        "text": {"kind": "text"},
    }
    for i in range(8):
        nodes[f"s{i}"] = {"kind": "section", "children": [f"f{i}"]}
        nodes[f"f{i}"] = {"kind": "fragment", "fragment_id": f"artifact{i}"}
    assert web_doc_page_section_count(_doc(nodes), "page") == 9


def test_plain_sections_and_direct_fragments_keep_their_counts():
    nodes = {
        "root": {"kind": "container", "children": ["a", "b", "f"]},
        "a": {"kind": "section", "children": []},
        "b": {"kind": "section", "children": ["content"]},
        "content": {"kind": "container", "children": ["text"]},
        "text": {"kind": "text"},
        "f": {"kind": "fragment"},
    }
    assert web_doc_page_section_count(_doc(nodes), "page") == 3


def test_invalid_graph_is_bounded_and_does_not_double_count_pins():
    nodes = {
        "root": {"kind": "container", "children": ["a", "a", "missing", None]},
        "a": {"kind": "section", "children": ["root", "a", "f", "f"]},
        "f": {"kind": "fragment", "children": ["a"]},
    }
    assert web_doc_page_section_count(_doc(nodes), "page") == 1
    assert web_doc_page_section_count({"pages": []}, "absent") == 0


def test_deep_container_envelope_does_not_recurse():
    nodes = {str(i): {"kind": "container", "children": [str(i + 1)]} for i in range(1500)}
    nodes["root"] = {"kind": "container", "children": ["0"]}
    nodes["1500"] = {"kind": "fragment"}
    assert web_doc_page_section_count(_doc(nodes), "page") == 1
