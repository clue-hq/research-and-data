"""Typed input schemas for the solo scene agent's tools (harness alignment T11, founder ruling 2026-10-18).

The model reads each tool's description AND each parameter's description from the tool's JSON schema
on every call. Before T11 the scene tools described none of their parameters, and four of them took
JSON inside a string. Each model here is bound as a tool's `args_schema` in the solo harness, so the
tool methods themselves are unchanged and keep validating as the backstop.

Rules for these schemas:
- A fixed list of allowed values only where the code already refuses every other value (for example
  `asset.action`). Where the code accepts more (`record_gap.area`, `search_assets.kind`), the field
  stays free text and its description names the usual values (founder ruling 2026-09-14: no new
  refusals for unknown kinds).
- A range or length is enforced only where the code already refuses outside it.
- The tool description says what the tool does and returns; each field says what its value means.
  Nothing is said in both places.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt

_Fraction = Annotated[float, Field(ge=0, le=1)]


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- asset --------------------------------------------------------------------------------------


class AssetInput(_ToolInput):
    action: Literal[
        "generate_image", "edit_image", "crop_image", "generate_qr", "place", "use_brand_asset"
    ] = Field(description="What to do.")
    prompt: Optional[str] = Field(
        None,
        description="generate_image and edit_image (required): what to make, or what to change "
        "in the placed image.",
    )
    target_node_id: Optional[str] = Field(
        None,
        description="generate_image: the frame the image is for. Its shape sets the image's aspect "
        "ratio and size, so the image fills it without stretching. Use this or target_slot_id.",
    )
    target_slot_id: Optional[str] = Field(
        None,
        description="generate_image: the image slot the image is for, instead of target_node_id.",
    )
    aspect_ratio: Optional[str] = Field(
        None,
        description='generate_image: width:height such as "4:5". Use it only when there is no '
        "target, or to override the target's shape. It is snapped to the nearest ratio the image "
        "model supports.",
    )
    width: Optional[int] = Field(
        None,
        description="generate_image: the width in pixels. Use it only to override the size worked "
        "out from the target.",
    )
    height: Optional[int] = Field(
        None,
        description="generate_image: the height in pixels. Use it only to override the size worked "
        "out from the target.",
    )
    brand_notes: Optional[list[str]] = Field(
        None,
        description="generate_image: short style directions added to the prompt, such as a palette "
        "or a mood.",
    )
    transparent_background: bool = Field(
        False,
        description="generate_image: make the background transparent. edit_image: remove the "
        "background.",
    )
    label: Optional[str] = Field(
        None,
        description="generate_image, edit_image, crop_image, generate_qr: a short name for the new "
        "asset.",
    )
    reference_asset_ids: Optional[list[str]] = Field(
        None,
        max_length=4,
        description="generate_image only: images to guide the new one, by id, from this turn's "
        "attachments, the brand kit, the library or the scene. Leave it out to use this turn's "
        "attachments; [] uses none. A list replaces the attachments. Viewing an image does not "
        "select it. List each id once. An unavailable id is an error, returned before anything is "
        "spent. edit_image refuses references: to change an image with references, generate a new "
        "one, view it and place it.",
    )
    reference_roles: Optional[list[Literal["source", "treatment", "composition"]]] = Field(
        None,
        description="generate_image: one role per reference id, in the same order. source: use what "
        "it shows as guidance for a new image. treatment: use its palette, texture, mood and "
        "rendering. composition: use its layout, hierarchy and framing.",
    )
    reference_framing: Optional[str] = Field(
        None,
        description="generate_image: one sentence on what to keep from the references and what to "
        "change. Needs references.",
    )
    operation: Optional[str] = Field(
        None,
        description="generate_image and edit_image: a short label for your intent, such as "
        "close_companion. It is recorded with the result and changes nothing else.",
    )
    data: Optional[str] = Field(
        None, description="generate_qr (required): the URL or text to encode."
    )
    ec_level: Optional[str] = Field(
        None,
        description="generate_qr: error correction, l, m, q or h (low to high). Default: m on "
        "screen, h for print.",
    )
    print_media: bool = Field(
        False,
        description="generate_qr: the code will be printed. Set target_width_mm too, so the "
        "print-scan checks can run.",
    )
    target_width_mm: Optional[float] = Field(
        None,
        description="generate_qr with print_media: the printed width in millimetres. Below 20 mm, "
        "phones may fail to scan it.",
    )
    asset_id: Optional[str] = Field(
        None,
        description="place and use_brand_asset (required): the image to place. For place: an image "
        "you generated or cropped this run, or a library image. For use_brand_asset: a logo or image "
        "from the brand card's inventory. crop_image (required): the original image to crop.",
    )
    node_id: Optional[str] = Field(
        None,
        description="place and use_brand_asset: the node to fill. It must be an image node or an "
        "empty leaf frame; a container with children can't be filled. edit_image (required): the "
        "node whose image to change.",
    )
    slot_id: Optional[str] = Field(
        None,
        description="place and use_brand_asset: a bound image slot to fill, instead of node_id.",
    )
    fit: Optional[Literal["cover", "contain", "crop"]] = Field(
        None,
        description="place and use_brand_asset: how the image fills the node. cover fills it and "
        "trims the edges (the default for place). contain shows the whole image (the default for "
        "use_brand_asset, so a logo is never cropped). crop looks like cover but counts as changing "
        "the image, so it is refused for an image whose licence forbids changes.",
    )
    focal_x: float = Field(
        0.5,
        description="place and use_brand_asset: the point of the image to keep in view when it is "
        "trimmed, from left (0) to right (1).",
    )
    focal_y: float = Field(
        0.5,
        description="place and use_brand_asset: the point of the image to keep in view when it is "
        "trimmed, from top (0) to bottom (1).",
    )
    alt: Optional[str] = Field(
        None, description="place and use_brand_asset: alt text for the image."
    )
    preserve_transparency: Optional[bool] = Field(
        None,
        description="place: true keeps transparent areas transparent. Leave it out for the default.",
    )
    crop_rect: Optional[Annotated[list[StrictInt], Field(min_length=4, max_length=4)]] = Field(
        None,
        description="crop_image (required): [left, top, right, bottom] in the original image's "
        "pixels, not the preview's. Right and bottom are excluded. The rectangle must be non-empty "
        "and inside the image.",
    )
    frame_index: Optional[Annotated[StrictInt, Field(ge=0)]] = Field(
        None,
        description='crop_image of an animated GIF (required there, GIF only): which frame to crop, '
        'counting from 0. View that frame first with view(target="asset:<id>", frame_index=...). '
        "The coordinates are that frame's full pixels, not a thumbnail's.",
    )


# --- view, inspect, search_assets, fetch_logo -----------------------------------------------------


class ViewInput(_ToolInput):
    target: str = Field(
        description="Which image to look at. preview: the latest rendered preview. "
        "asset:<asset_id>: a brand-kit, library or scene image, including one you just generated. "
        "reference:<n>: this turn's nth attachment, counting from 1 (or reference:<asset_id>); it "
        "exists only when the turn has attachments."
    )
    frame_index: Optional[Annotated[StrictInt, Field(ge=0)]] = Field(
        None,
        description="Animated GIFs only: which original frame to show, counting from 0, with its "
        "digest and pixel size. Not for preview. Leave it out to see the normal thumbnail. Only "
        "that one frame is shown; the animation itself isn't reviewed.",
    )


class InspectInput(_ToolInput):
    view: Literal[
        "scene", "page", "node_tree", "slots", "geometry", "slot_bindings", "copy_review",
        "image_contrast",
    ] = Field(
        description="What to read. scene: the document, pages, counts, slots and the brand in "
        "effect. page: one page's nodes with geometry and slot bindings. node_tree: one page's node "
        "hierarchy. slots: every slot key and its bound nodes. geometry: one node's computed box "
        "and its declared position and size. slot_bindings: one slot's bindings. copy_review: every "
        "native text in the current export, for the direction review, with what it couldn't "
        "observe. image_contrast: the contrast of a text colour over an image's pixels."
    )
    target: Optional[str] = Field(
        None,
        description="The id the view needs: a page id (page, node_tree), a node id (geometry), a "
        "slot key (slot_bindings) or an asset id (image_contrast). Leave it empty for scene, slots "
        "and copy_review.",
    )
    foreground_color: Optional[str] = Field(
        None, description="image_contrast only: the text colour, as #RRGGBB."
    )
    region: Optional[Annotated[list[_Fraction], Field(min_length=4, max_length=4)]] = Field(
        None,
        description="image_contrast only: [left, top, right, bottom] of the image area behind the "
        "text, as fractions of the image's own width and height. Allow for how the placement crops "
        "the image. The measurement ignores plates, glyphs, opacity and effects, so check the final "
        "render too. A transparent or colour-profiled image returns a gap instead of a number.",
    )


class SearchAssetsInput(_ToolInput):
    q: str = Field(
        description="What to look for: words about the image (its subject, use, source or the text "
        "in it), or an exact asset id."
    )
    kind: Optional[str] = Field(
        None,
        description="Only this kind: image, logo or font, or a raw kind such as document. Leave it "
        "empty for everything.",
    )
    limit: int = Field(8, ge=1, le=20, description="How many results to return.")


class FetchLogoInput(_ToolInput):
    domain: str = Field(
        description="The company's domain (goodmancampbell.com) or any URL on its site."
    )
    company_name: Optional[str] = Field(
        None,
        description="The company's name, when you know it. It sharpens the check that a logo really "
        "belongs to this company.",
    )
    force_refresh: bool = Field(
        False,
        description="Results are kept per workspace and company, so asking again costs no new "
        "fetch. Set it to true only when the person says the logo is wrong or out of date. It "
        "fetches again and replaces the kept logos.",
    )


# --- apply_structured_edit ----------------------------------------------------------------------


class EditTarget(_ToolInput):
    kind: Literal["node", "page", "slot", "slot_key", "asset", "document", "export_profile"] = Field(
        description="What the id names. Usually node (an element) or page."
    )
    id: Optional[str] = Field(None, description="Its id. Leave it out only for document.")


class ParentRef(_ToolInput):
    kind: Literal["node", "page"] = Field(description="node for a container, page for a page.")
    id: str = Field(description="The container's or the page's id.")


class _RelativePlacement(_ToolInput):
    kind: Literal["before", "after"] = Field(description="Just before or just after the anchor.")
    anchor: str = Field(description="The element the copy goes next to, in that element's parent.")


class _IndexPlacement(_ToolInput):
    kind: Literal["parent_index"] = Field(description="At a position inside a parent.")
    parent: ParentRef
    index: int = Field(ge=0, description="The position among the parent's children, 0 first.")


class _SuffixSlots(_ToolInput):
    suffix: str = Field(description='New slots are created, named with this suffix, e.g. "_2".')


_PATCH_DESCRIPTION = (
    'What to change. {"kind": "node", "value": {...}} for an element, or {"kind": "page", "value": '
    '{...}} for a page. Inside value, give only the fields you change, each one as {"kind": "set", '
    '"value": ...}. '
    'text (text elements only): {"text": {"content": {"kind": "set", "value": "New copy"}}}. These '
    "text fields work the same way: font_size, in the same units as positions; font_weight, "
    "100-900; line_height, a multiple of the font size, e.g. 1.2; letter_spacing, added between "
    "characters, a negative value tightens; align: left, center, right or justify; font_family; "
    "italic. "
    'fills: {"fills": {"kind": "set", "value": [{"id": "fill_1", "paint": {"kind": "solid", '
    '"color": {"kind": "hex", "value": "#123456"}}}]}}. The list replaces all fills. For a brand '
    'colour, use {"kind": "token", "token": "surface.accent"} as the colour, or as the whole paint. '
    'size: {"size": {"kind": "set", "value": {"width": {"kind": "fixed", "value": 640}, "height": '
    '{"kind": "hug"}}}}. Each side is fixed (with a value), hug, or {"kind": "fill", "value": '
    '{"weight": 1}}. '
    'position: {"transform": {"kind": "set", "value": {"x": 700, "y": 760, "rotation": 0, '
    '"skew_x": 0, "skew_y": 0, "flip_x": false, "flip_y": false}}}. All seven fields are required: '
    'copy the current ones from inspect(view="geometry") and change x and y. x and y are relative '
    "to the parent. Inside an auto-layout container the layout places the children, so change "
    "their order or the container instead. "
    'opacity: {"opacity": {"kind": "set", "value": 0.9}}, from 0 to 1. '
    'corners: {"corner": {"kind": "set", "value": {"top_left": 24, "top_right": 24, '
    '"bottom_right": 24, "bottom_left": 24}}}. '
    'page background: {"kind": "page", "value": {"background": {"kind": "set", "value": [fills as '
    "above]}}}. "
    "The engine checks every field and names anything it can't accept."
)


class ModifyEdit(_ToolInput):
    """Change one element's or one page's properties."""

    kind: Literal["modify"]
    target: EditTarget
    patch: dict[str, Any] = Field(description=_PATCH_DESCRIPTION)


class DeleteEdit(_ToolInput):
    """Remove an element and its children."""

    kind: Literal["delete"]
    target: EditTarget


class MoveBeforeEdit(_ToolInput):
    """Move an element to just before another element (anchor), inside the anchor's parent."""

    kind: Literal["move_before"]
    node_id: str = Field(description="The element to move.")
    anchor: str = Field(description="The element it goes just before.")


class MoveAfterEdit(_ToolInput):
    """Move an element to just after another element (anchor), inside the anchor's parent."""

    kind: Literal["move_after"]
    node_id: str = Field(description="The element to move.")
    anchor: str = Field(description="The element it goes just after.")


class MoveToParentEdit(_ToolInput):
    """Move an element into a container or onto a page."""

    kind: Literal["move_to_parent"]
    node_id: str = Field(description="The element to move.")
    parent: ParentRef
    index: int = Field(ge=0, description="Its position among the parent's children, 0 first.")


class CloneRequest(_ToolInput):
    source: str = Field(description="The element to duplicate, with everything inside it.")
    new_root_id: str = Field(description="The new id for the copy.")
    placement: Union[_RelativePlacement, _IndexPlacement] = Field(
        description='Where the copy goes: {"kind": "before" or "after", "anchor": id}, or '
        '{"kind": "parent_index", "parent": {...}, "index": n}.'
    )
    slot_policy: Union[Literal["detach", "copy"], _SuffixSlots] = Field(
        "detach",
        description="What the copy does with the original's slots (named placeholders the platform "
        "fills per account). detach: the copy fills no slot, so it is the same for every account; "
        "the usual choice. copy: the copy joins the same slots, so each account's value appears in "
        'both places. {"suffix": "_2"}: new slots are created with that suffix, so the copy gets '
        "its own value per account.",
    )
    computed_policy: Literal["clear", "preserve"] = Field(
        "clear",
        description="Every element stores the box the layout engine last gave it. clear drops that "
        "box from the copy, so the next preflight lays the copy out fresh in its new position; the "
        "usual choice. preserve keeps the original's box on the copy until the layout runs again.",
    )


class CloneSubtreeEdit(_ToolInput):
    """Duplicate an element and its children under a new id."""

    kind: Literal["clone_subtree"]
    request: CloneRequest


class ReplaceRequest(_ToolInput):
    target: str = Field(description="The element to replace. It is removed.")
    replacement: str = Field(description="An element that already exists, which takes its place.")
    slot_policy: Literal["detach", "preserve_compatible"] = Field(
        "detach",
        description="detach: the removed element's slots are dropped. preserve_compatible: the "
        "replacement takes them over where the content type matches.",
    )


class ReplaceNodeEdit(_ToolInput):
    """Put an existing element where another one is; the other one is removed."""

    kind: Literal["replace_node"]
    request: ReplaceRequest


class GroupEdit(_ToolInput):
    """Wrap sibling elements in a new group with an id you choose."""

    kind: Literal["group"]
    node_ids: list[str] = Field(min_length=1, description="The sibling elements to wrap.")
    group_id: str = Field(description="The new group's id.")
    name: Optional[str] = Field(None, description="Optional: the group's name.")


class UngroupEdit(_ToolInput):
    """Dissolve a group into its parent; the children keep their order."""

    kind: Literal["ungroup"]
    node_id: str = Field(description="The group to dissolve.")
    allow_layout: bool = Field(
        False,
        description="An auto-layout container is refused unless this is true, because dissolving "
        "it loses its layout. Preflight recomputes the children's positions.",
    )


StructuredEdit = Union[
    ModifyEdit, DeleteEdit, MoveBeforeEdit, MoveAfterEdit, MoveToParentEdit, CloneSubtreeEdit,
    ReplaceNodeEdit, GroupEdit, UngroupEdit,
]
# The engine accepts 16 kinds. Left out for the scene agent (founder rulings 2026-10-18, T11 D2/E1):
# archive_asset and hard_delete_asset (a design turn must not delete library assets);
# detach_to_freehand, reattach_to_layout, convert_container_layout and freeze_layout (the editor's
# drag-and-freeze tools: they replace auto-layout with fixed positions); delete_export_profile
# (export setup, not design).
SCENE_EDIT_KINDS = (
    "modify", "delete", "move_before", "move_after", "move_to_parent", "clone_subtree",
    "replace_node", "group", "ungroup",
)


class EditScope(_ToolInput):
    mode: Literal["strict", "advisory"] = Field(
        description="strict: the engine refuses the whole edit, before anything changes, if it "
        "would touch anything outside allowed; an allowed element's children count as inside. "
        "advisory: the edit is applied, and anything outside allowed is reported as a warning."
    )
    allowed: list[EditTarget] = Field(description="The elements the edit may touch.")


class ApplyStructuredEditInput(_ToolInput):
    edit: StructuredEdit = Field(
        description="The edit. An element is a node in the scene. kind picks the shape; "
        "clone_subtree and replace_node take their fields inside \"request\": {...}, the other "
        "kinds don't."
    )
    scope: Optional[EditScope] = Field(
        None,
        description='Optional: {"mode": "strict", "allowed": [{"kind": "node", "id": "headline"}]}. '
        "Give every repair of a specific review issue a strict scope.",
    )


# --- finalize_run, record_gap, validate_creative_direction, compile_dsl_block ---------------------


class FinalizeRunInput(_ToolInput):
    status: str = Field(
        description="How the turn ended. accepted: a new ad or a revamp that passed your review. "
        "edit_applied: a targeted edit. completed_with_warnings: a valid draft that wasn't "
        "accepted. failed: the request couldn't be met."
    )
    stop_reason: str = Field(
        description='A few words on why you stopped, such as "request met" or "account logo '
        'unavailable". The detail goes in summary.'
    )
    summary: str = Field(
        description="What the person reads in the chat about this turn. For a targeted edit: what "
        "was asked, what changed, what else moved and anything not done. For a new ad or a revamp: "
        "what you made and any remaining defects. Say plainly what isn't fixed."
    )


class RecordGapInput(_ToolInput):
    area: str = Field(
        description="Which part of the product. Usually one of: agent_protocol (the tools or the "
        "turn's rules got in the way); knowledge_loading (a guide or skill was missing or "
        "unreadable); dsl_edit_language (the DSL or edit tools can't express the change); layout "
        "(the layout engine can't produce the arrangement); text_typography (a type need the engine "
        "can't meet); design_system (a brand-kit or token problem); rendering_export_preview "
        "(rendering, preview or export failed or came out wrong); assets (an asset was missing, "
        "wrong or couldn't be placed); scene_model (the scene data can't represent what's needed); "
        "model_provider (the image or model provider failed). Another word is kept, filed under "
        "agent_protocol."
    )
    summary: str = Field(description="One sentence: what you couldn't do.")
    evidence: str = Field(description="What showed it: the tool, the input, and the error or result.")


class ValidateCreativeDirectionInput(_ToolInput):
    revision_reason: str = Field(
        "",
        description="Needed only when you change the file after it already passed: one sentence on "
        "why. If the content is unchanged apart from formatting, the earlier result and review "
        "stand.",
    )


class CompileDslBlockInput(_ToolInput):
    source: str = Field(
        description="The DSL text, following the grammar in your instructions. Don't repeat an "
        "existing page line; that is refused (LUMA0200)."
    )

