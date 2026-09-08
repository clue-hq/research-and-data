use crate::assets::{AssetPlacement, AssetRecord};
use crate::export_contract::ExportProfile;
use crate::ids::{
    AssetId, BrandKitId, DocumentId, EffectId, NodeId, PageId, PaintId, SlotId, SlotKey,
    TemplateRevisionId,
};
use crate::slots::Slot;
use crate::SCHEMA_VERSION;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Scene {
    pub schema_version: u32,
    pub meta: DocumentMeta,
    pub pages: BTreeMap<PageId, Page>,
    pub nodes: BTreeMap<NodeId, Node>,
    pub slots: BTreeMap<crate::ids::SlotId, Slot>,
    #[serde(default)]
    pub assets: BTreeMap<AssetId, AssetRecord>,
    pub export_profiles: Vec<ExportProfile>,
}

impl Scene {
    pub fn new(document_id: DocumentId, title: impl Into<String>) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            meta: DocumentMeta {
                id: document_id,
                title: title.into(),
                artifact_type: None,
                medium: None,
                brand_kit: None,
                status: DocumentStatus::Draft,
            },
            pages: BTreeMap::new(),
            nodes: BTreeMap::new(),
            slots: BTreeMap::new(),
            assets: BTreeMap::new(),
            export_profiles: Vec::new(),
        }
    }

    pub fn node_can_have_children(&self, node_id: &NodeId) -> bool {
        self.nodes
            .get(node_id)
            .map(|node| node.kind.can_have_children())
            .unwrap_or(false)
    }

    pub fn is_finalized(&self) -> bool {
        matches!(self.meta.status, DocumentStatus::Finalized { .. })
    }

    pub fn page(&self, page_id: &PageId) -> Option<&Page> {
        self.pages.get(page_id)
    }

    pub fn node(&self, node_id: &NodeId) -> Option<&Node> {
        self.nodes.get(node_id)
    }

    pub fn slot(&self, slot_id: &SlotId) -> Option<&Slot> {
        self.slots.get(slot_id)
    }

    pub fn asset(&self, asset_id: &AssetId) -> Option<&AssetRecord> {
        self.assets.get(asset_id)
    }

    pub fn slot_by_key(&self, slot_key: &SlotKey) -> Option<&Slot> {
        self.slots.values().find(|slot| &slot.key == slot_key)
    }

    pub fn export_profile(&self, name: &str) -> Option<&ExportProfile> {
        self.export_profiles
            .iter()
            .find(|profile| profile.name == name)
    }

    pub fn parent_of(&self, node_id: &NodeId) -> Option<ParentRef> {
        for page in self.pages.values() {
            if page.children.contains(node_id) {
                return Some(ParentRef::Page(page.id.clone()));
            }
        }

        for node in self.nodes.values() {
            if node.children.contains(node_id) {
                return Some(ParentRef::Node(node.id.clone()));
            }
        }

        None
    }

    pub fn descendants_of(&self, node_id: &NodeId) -> Vec<NodeId> {
        let mut descendants = Vec::new();
        let mut seen = BTreeSet::new();
        self.collect_descendants(node_id, &mut seen, &mut descendants);
        descendants
    }

    pub fn slots_for_node(&self, node_id: &NodeId) -> Vec<&Slot> {
        self.slots
            .values()
            .filter(|slot| slot.bound_nodes.contains(node_id))
            .collect()
    }

    pub fn bound_nodes_for_slot(&self, slot_id: &SlotId) -> Vec<&Node> {
        let Some(slot) = self.slots.get(slot_id) else {
            return Vec::new();
        };

        slot.bound_nodes
            .iter()
            .filter_map(|node_id| self.nodes.get(node_id))
            .collect()
    }

    fn collect_descendants(
        &self,
        node_id: &NodeId,
        seen: &mut BTreeSet<NodeId>,
        descendants: &mut Vec<NodeId>,
    ) {
        let Some(node) = self.nodes.get(node_id) else {
            return;
        };

        for child_id in &node.children {
            if seen.insert(child_id.clone()) {
                descendants.push(child_id.clone());
                self.collect_descendants(child_id, seen, descendants);
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum ParentRef {
    Page(PageId),
    Node(NodeId),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DocumentMeta {
    pub id: DocumentId,
    pub title: String,
    pub artifact_type: Option<String>,
    pub medium: Option<Medium>,
    pub brand_kit: Option<BrandKitRef>,
    pub status: DocumentStatus,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Medium {
    Print,
    Digital,
    Email,
    DirectMail,
    Ad,
    Web,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BrandKitRef {
    pub id: BrandKitId,
    pub version: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DocumentStatus {
    Draft,
    Finalized {
        template_revision_id: TemplateRevisionId,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Page {
    pub id: PageId,
    pub name: String,
    pub size: PageSize,
    pub children: Vec<NodeId>,
    pub bleed: Option<Rect>,
    pub safe_area: Option<Rect>,
    pub background: Vec<Fill>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageSize {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
    pub preset: Option<PagePreset>,
    pub orientation: Orientation,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<PageSizeSource>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output: Option<PageOutputSize>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageSizeSource {
    pub width: f64,
    pub height: f64,
    pub unit: Unit,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PageOutputSize {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub physical: Option<PhysicalPageSize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub raster: Option<RasterPageSize>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PhysicalPageSize {
    pub width: f64,
    pub height: f64,
    pub unit: PhysicalUnit,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RasterPageSize {
    pub width_px: u32,
    pub height_px: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Unit {
    Pt,
    Px,
    Mm,
    In,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhysicalUnit {
    Mm,
    In,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PagePreset {
    A4,
    UsLetter,
    Custom,
    LinkedinAd,
    EnvelopeDl,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Orientation {
    Portrait,
    Landscape,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Node {
    pub id: NodeId,
    pub name: Option<String>,
    pub kind: NodeKind,
    pub transform: Transform,
    pub size: SizeSpec,
    pub children: Vec<NodeId>,
    pub fills: Vec<Fill>,
    pub strokes: Vec<Stroke>,
    /// Stacked, individually addressable effects (Effects Contract V0).
    /// Serde-defaulted and omitted when empty so pre-effects scene JSON
    /// round-trips byte-identically.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub effects: Vec<Effect>,
    pub corner: CornerRadii,
    pub opacity: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub opacity_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_asset_id: Option<AssetId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub asset_placement: Option<AssetPlacement>,
    pub clip: bool,
    /// Declared intent that this node deliberately extends past the page/parent
    /// bounds (a full-bleed wash). Purely a preflight signal: it downgrades the
    /// off-canvas overflow errors (LUMV0800/LUMV0801) to warnings — it never
    /// changes what is exported. Serde-defaulted and omitted when false so
    /// pre-A4 scene JSON round-trips byte-identically (mirrors `effects`).
    #[serde(default, skip_serializing_if = "is_false")]
    pub bleed: bool,
    pub layout: Option<AutoLayoutProps>,
    pub computed: Option<ComputedGeometry>,
    pub locked: bool,
    /// Phase 1 freehand: who owns this node's position. `Managed` (default) =
    /// the layout solver; `Absolute` = a human pinned it — the solver lays it
    /// out at `absolute_box`, out of flow (the deliberate generalization of
    /// the rotation out-of-flow seam). Serde-defaulted and omitted when
    /// Managed so pre-freehand scene JSON round-trips byte-identically
    /// (mirrors `effects`).
    #[serde(default, skip_serializing_if = "position_mode_is_managed")]
    pub position_mode: PositionMode,
    /// Page-space box an `Absolute` node is laid out at. None while Managed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub absolute_box: Option<Rect>,
    /// The solved box captured at detach time — the reconciliation signal
    /// that lets the agent see "the human nudged this N px off where the
    /// solver put it" and preserve the offset instead of clobbering or
    /// blindly pinning.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_anchor: Option<Rect>,
}

/// See [`Node::position_mode`].
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PositionMode {
    #[default]
    Managed,
    Absolute,
}

fn position_mode_is_managed(mode: &PositionMode) -> bool {
    *mode == PositionMode::Managed
}

/// Phase 1 freehand: how an auto-layout container places its children.
/// `Stack` (default) = the flex solve; `Free` = children lay out at their own
/// baked transforms through the absolute path ("free this whole section").
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LayoutMode {
    #[default]
    Stack,
    Free,
}

fn layout_mode_is_stack(mode: &LayoutMode) -> bool {
    *mode == LayoutMode::Stack
}

impl Node {
    pub fn new(id: NodeId, kind: NodeKind) -> Self {
        Self {
            id,
            name: None,
            kind,
            transform: Transform::default(),
            size: SizeSpec::fixed(0.0, 0.0),
            children: Vec::new(),
            fills: Vec::new(),
            strokes: Vec::new(),
            effects: Vec::new(),
            corner: CornerRadii::default(),
            opacity: 1.0,
            opacity_token: None,
            source_asset_id: None,
            asset_placement: None,
            clip: false,
            bleed: false,
            layout: None,
            computed: None,
            locked: false,
            position_mode: PositionMode::Managed,
            absolute_box: None,
            base_anchor: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NodeKind {
    Frame,
    Group,
    Rect,
    Ellipse,
    Line(LineNode),
    Text(TextNode),
    Image(ImageNode),
    Vector(VectorNode),
    AutoLayout(AutoLayoutNode),
    Instance { source_node_id: NodeId },
}

impl NodeKind {
    pub fn can_have_children(&self) -> bool {
        matches!(self, Self::Frame | Self::Group | Self::AutoLayout(_))
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TextNode {
    pub content: String,
    pub font_family: String,
    pub font_size: f64,
    pub font_weight: u16,
    pub align: TextAlign,
    #[serde(default = "default_text_line_height")]
    pub line_height: f64,
    #[serde(default)]
    pub letter_spacing: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_lines: Option<u16>,
    #[serde(default = "default_text_wrap")]
    pub wrap: TextWrap,
    #[serde(default = "default_text_direction")]
    pub direction: TextDirection,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style_token: Option<String>,
    /// Explicit size-step token (e.g. `$type.size.7xl`) that overrides the
    /// `style_token` role's default size. Resolved AFTER the role so an author's
    /// per-surface size choice wins — the role still supplies weight/color/lh.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub font_size_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub line_height_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub letter_spacing_token: Option<String>,
    /// Display-time case transform (A6a D1). The `content` string is NEVER
    /// mutated — every consumer calls [`TextNode::transformed_content`] before
    /// shaping/measuring/emitting. Absent (`None`) leaves content verbatim, so
    /// old scenes are bit-for-bit unchanged.
    #[serde(default, skip_serializing_if = "is_enum_default")]
    pub text_transform: TextTransform,
    /// Underline decoration (A6a D2). Independent of `strikethrough`.
    #[serde(default, skip_serializing_if = "is_false")]
    pub underline: bool,
    /// Strikethrough decoration (A6a D2). Independent of `underline`.
    #[serde(default, skip_serializing_if = "is_false")]
    pub strikethrough: bool,
    /// Italic style (A7b D1). Unlike underline/strikethrough this is a
    /// MEASUREMENT input — it selects the italic face (`Slant::Italic`), which
    /// changes glyph shapes and advances, so it enters `measure_key` and both
    /// measurers (like `font_weight`, unlike the decoration channels). No
    /// synthetic slant: if the resolved family has no italic face the shaper
    /// snaps to upright and emits the LUMS0105 advisory (D2). Serde-defaulted
    /// and omitted when `false` so pre-A7b scenes — and every default node —
    /// round-trip byte-identically.
    #[serde(default, skip_serializing_if = "is_false")]
    pub italic: bool,
    /// Ellipsis truncation (A6a D3): when the measurer cuts lines (max_lines
    /// exceeded, or NoWrap width overflow) the last visible line ends with
    /// U+2026 "…". No effect when nothing is cut.
    #[serde(default, skip_serializing_if = "is_false")]
    pub truncate: bool,
    /// Extra vertical gap (px) inserted at each `\n` paragraph break (A6a D4),
    /// on top of the normal line advance. `0.0` is today's behavior, bit-for-bit.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub paragraph_spacing: f64,
    /// Vertical alignment of the painted text within its own box (A7a D1/D3).
    /// Positions text inside a Fixed/Fill-height box; a Hug box has zero slack
    /// so it is a silent no-op (D6). Never a measurement input (D4) — it only
    /// shifts paint position. Serde-defaulted and omitted when `Top` so pre-A7a
    /// scenes — and every default node — deserialize to `Top` and re-serialize
    /// byte-identically (mirrors `text_transform`).
    #[serde(default, skip_serializing_if = "is_enum_default")]
    pub valign: VerticalAlign,
    /// Rich-text spans (A6b D1): sub-ranges of `content` styled differently —
    /// the two-color headline move. Byte offsets index the STORED `content`
    /// string (never the transformed one). Validated (LUMV0906) before
    /// measurement. Serde-defaulted and omitted when empty so pre-A6b scenes —
    /// and every default node — round-trip byte-identically (mirrors `effects`),
    /// and every measurer/renderer keeps its A6a fast path when `spans` is empty.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub spans: Vec<TextSpan>,
}

/// One rich-text span (A6b D1): a sub-range of a [`TextNode`]'s `content` with
/// override channels. `None` channels inherit the node. Fill is restricted to
/// `Solid` or `Token` — gradient span fills are rejected at validation
/// (LUMV0908). A span whose every channel is `None` is legal but pointless
/// (it renders base).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TextSpan {
    /// Byte offset into `content` where the run starts (inclusive),
    /// char-boundary aligned.
    pub start: usize,
    /// Byte offset into `content` where the run ends (exclusive),
    /// char-boundary aligned, `> start`.
    pub end: usize,
    /// Override fill — `Solid` or `Token` only (gradients rejected, D3).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fill: Option<Paint>,
    /// Override font weight (CSS 100..900).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub font_weight: Option<u16>,
    /// Override underline decoration.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub underline: Option<bool>,
    /// Override strikethrough decoration.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub strikethrough: Option<bool>,
    /// Override italic (A7b D1). Merge is OVERRIDE, not union like the
    /// decoration channels: `span.italic.unwrap_or(node.italic)`, so
    /// `italic(false)` de-italicizes one run inside an italic block. Measured
    /// per-run (enters `spans_digest`), mirroring `font_weight`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub italic: Option<bool>,
}

impl Default for TextNode {
    fn default() -> Self {
        Self {
            content: String::new(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 400,
            align: TextAlign::Left,
            line_height: default_text_line_height(),
            letter_spacing: 0.0,
            max_lines: None,
            wrap: TextWrap::NoWrap,
            direction: TextDirection::Ltr,
            style_token: None,
            font_size_token: None,
            line_height_token: None,
            letter_spacing_token: None,
            text_transform: TextTransform::None,
            underline: false,
            strikethrough: false,
            italic: false,
            truncate: false,
            paragraph_spacing: 0.0,
            valign: VerticalAlign::Top,
            spans: Vec::new(),
        }
    }
}

/// Display-time case transform (A6a D1). Serialized snake_case like the
/// sibling text enums.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextTransform {
    /// Content shapes verbatim (the default; absent in serialized old scenes).
    #[default]
    None,
    Uppercase,
    Lowercase,
    /// Uppercase the first alphabetic char of each whitespace-separated word;
    /// the rest of each word is left untouched.
    Title,
}

impl TextTransform {
    /// Apply the transform to a source string, Unicode-correctly. Returns
    /// [`Cow::Borrowed`] for [`TextTransform::None`] so the common path never
    /// allocates.
    pub fn apply<'a>(&self, content: &'a str) -> std::borrow::Cow<'a, str> {
        use std::borrow::Cow;
        match self {
            TextTransform::None => Cow::Borrowed(content),
            TextTransform::Uppercase => Cow::Owned(content.to_uppercase()),
            TextTransform::Lowercase => Cow::Owned(content.to_lowercase()),
            TextTransform::Title => Cow::Owned(title_case(content)),
        }
    }
}

/// Title-case: uppercase the first alphabetic char of each whitespace-separated
/// word, leaving the remainder of the word untouched. Whitespace runs are
/// preserved verbatim so line/word structure is stable.
fn title_case(content: &str) -> String {
    let mut out = String::with_capacity(content.len());
    let mut at_word_start = true;
    for ch in content.chars() {
        if ch.is_whitespace() {
            at_word_start = true;
            out.push(ch);
        } else if at_word_start && ch.is_alphabetic() {
            for upper in ch.to_uppercase() {
                out.push(upper);
            }
            at_word_start = false;
        } else {
            out.push(ch);
            at_word_start = false;
        }
    }
    out
}

/// One contiguous piece of transformed content (A6b D5/D6), tagged with the
/// span it belongs to (`None` = base style). Concatenating every segment's
/// `text` reproduces the fully transformed content, so a measurer can build
/// one paragraph over the pieces and a renderer can style each run.
#[derive(Clone, Debug, PartialEq)]
pub struct SpanSegment {
    pub text: String,
    /// Index into the node's `spans`, or `None` for the base run.
    pub span: Option<usize>,
}

/// Normalize raw text content — DSL literal `\n` and `\r\n` collapse to a real
/// newline, a trailing newline is trimmed (`normalize_content` semantics) — AND
/// build a raw-byte → normalized-byte offset map so span offsets that index the
/// STORED content string (A6b D1) can be relocated onto the normalized string
/// both measurers case-fold and shape. `map[i]` is the normalized offset of raw
/// byte `i`, for every `i` in `0..=raw.len()`.
pub fn normalize_content_mapped(raw: &str) -> (String, Vec<usize>) {
    let mut out = String::with_capacity(raw.len());
    let mut map = vec![0usize; raw.len() + 1];
    let mut chars = raw.char_indices().peekable();
    while let Some((idx, ch)) = chars.next() {
        map[idx] = out.len();
        // Literal "\n" (two chars) → one newline; the escaped 'n' collapses
        // onto the newline offset.
        if ch == '\\' {
            if let Some((n_idx, 'n')) = chars.peek().copied() {
                map[n_idx] = out.len();
                out.push('\n');
                chars.next();
                continue;
            }
        }
        // CRLF → one newline.
        if ch == '\r' {
            if let Some((n_idx, '\n')) = chars.peek().copied() {
                map[n_idx] = out.len();
                out.push('\n');
                chars.next();
                continue;
            }
        }
        let start = out.len();
        out.push(ch);
        // Point any UTF-8 continuation bytes at the char's start (they are
        // never span boundaries — validation requires char alignment).
        for cont in (idx + 1)..(idx + ch.len_utf8()) {
            map[cont] = start;
        }
    }
    map[raw.len()] = out.len();

    // Trim a trailing newline (mirrors `normalize_content`'s
    // `trim_end_matches('\n')`) and clamp every mapped offset into the trim.
    let trimmed_len = out.trim_end_matches('\n').len();
    out.truncate(trimmed_len);
    for offset in map.iter_mut() {
        *offset = (*offset).min(trimmed_len);
    }
    (out, map)
}

/// Split `normalized` content at `boundaries` (already-normalized `(start,end)`
/// span ranges, in order, non-overlapping) and apply `transform` to each piece
/// with a STATEFUL title-case cursor that carries word-start state across
/// segment boundaries (A6b D5) — a span starting mid-word never re-capitalizes.
/// Uppercase/lowercase are per-char and safe regardless. The Nth boundary maps
/// to `Some(N)`; gaps and the tail map to `None`.
pub fn transform_segments(
    normalized: &str,
    boundaries: &[(usize, usize)],
    transform: TextTransform,
) -> Vec<SpanSegment> {
    let mut pieces: Vec<(usize, usize, Option<usize>)> = Vec::new();
    let mut cursor = 0usize;
    for (index, (start, end)) in boundaries.iter().enumerate() {
        let (start, end) = (*start, *end);
        if start > cursor {
            pieces.push((cursor, start, None));
        }
        if end > start {
            pieces.push((start, end, Some(index)));
        }
        cursor = cursor.max(end);
    }
    if cursor < normalized.len() {
        pieces.push((cursor, normalized.len(), None));
    }

    let mut at_word_start = true;
    pieces
        .into_iter()
        .map(|(start, end, span)| {
            let slice = normalized.get(start..end).unwrap_or("");
            let text = transform_slice_stateful(slice, transform, &mut at_word_start);
            SpanSegment { text, span }
        })
        .collect()
}

/// Case-transform one slice, threading the title-case word-start cursor so the
/// caller can continue it across the next segment (A6b D5).
fn transform_slice_stateful(
    slice: &str,
    transform: TextTransform,
    at_word_start: &mut bool,
) -> String {
    match transform {
        TextTransform::None => {
            for ch in slice.chars() {
                *at_word_start = ch.is_whitespace();
            }
            slice.to_owned()
        }
        TextTransform::Uppercase => {
            for ch in slice.chars() {
                *at_word_start = ch.is_whitespace();
            }
            slice.to_uppercase()
        }
        TextTransform::Lowercase => {
            for ch in slice.chars() {
                *at_word_start = ch.is_whitespace();
            }
            slice.to_lowercase()
        }
        TextTransform::Title => {
            let mut out = String::with_capacity(slice.len());
            for ch in slice.chars() {
                if ch.is_whitespace() {
                    *at_word_start = true;
                    out.push(ch);
                } else if *at_word_start && ch.is_alphabetic() {
                    for upper in ch.to_uppercase() {
                        out.push(upper);
                    }
                    *at_word_start = false;
                } else {
                    out.push(ch);
                    *at_word_start = false;
                }
            }
            out
        }
    }
}

/// One span validation failure (A6b D3): the offending span index and a
/// human-readable reason. The layout gate turns each into a LUMV0906 error
/// before measurement, so an ops-injected scene with invalid spans never
/// reaches partial rendering.
#[derive(Clone, Debug, PartialEq)]
pub struct SpanValidationError {
    pub index: usize,
    pub reason: String,
}

/// Validate a node's spans against its `content` (A6b D3). Errors: a span that
/// is out of bounds, has `start >= end`, starts or ends off a char boundary, is
/// unsorted or overlaps its predecessor, or carries a gradient fill (Solid/Token
/// only). Empty spans validate clean. DSL-authored spans are valid by
/// construction; this gate exists for ops-injected spans.
pub fn span_validation_errors(content: &str, spans: &[TextSpan]) -> Vec<SpanValidationError> {
    let mut errors = Vec::new();
    let len = content.len();
    let mut prev_end: Option<usize> = None;
    for (index, span) in spans.iter().enumerate() {
        if span.start >= span.end {
            errors.push(SpanValidationError {
                index,
                reason: format!(
                    "start {} is not before end {} (empty or inverted range)",
                    span.start, span.end
                ),
            });
        }
        if span.start > len || span.end > len {
            errors.push(SpanValidationError {
                index,
                reason: format!(
                    "range {}..{} is out of bounds for content of {} bytes",
                    span.start, span.end, len
                ),
            });
        } else {
            if !content.is_char_boundary(span.start) {
                errors.push(SpanValidationError {
                    index,
                    reason: format!("start {} is not on a UTF-8 char boundary", span.start),
                });
            }
            if !content.is_char_boundary(span.end) {
                errors.push(SpanValidationError {
                    index,
                    reason: format!("end {} is not on a UTF-8 char boundary", span.end),
                });
            }
        }
        if let Some(prev_end) = prev_end {
            if span.start < prev_end {
                errors.push(SpanValidationError {
                    index,
                    reason: format!(
                        "start {} overlaps or is unsorted against the previous span ending at {}",
                        span.start, prev_end
                    ),
                });
            }
        }
        prev_end = Some(span.end.max(prev_end.unwrap_or(0)));
        if matches!(
            span.fill,
            Some(Paint::LinearGradient { .. }) | Some(Paint::RadialGradient { .. })
        ) {
            errors.push(SpanValidationError {
                index,
                reason: "span fill must be a solid color or token, not a gradient".to_owned(),
            });
        }
    }
    errors
}

/// Which token bindings an edit explicitly authored. Explicit tokens are
/// never cleared by [`TextNode::clear_stale_tokens`].
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ExplicitTextTokens {
    pub style: bool,
    pub font_size: bool,
    pub line_height: bool,
    pub letter_spacing: bool,
}

impl ExplicitTextTokens {
    pub fn is_empty(&self) -> bool {
        !self.style && !self.font_size && !self.line_height && !self.letter_spacing
    }
}

impl TextNode {
    /// Token honesty: a raw edit to a typography channel detaches any token
    /// that would later re-resolve over it (export preflight, brand apply)
    /// and silently clobber the edit. A channel token is cleared when its raw
    /// sibling changed; `style_token` — the role supplying family/size/weight
    /// and optionally line-height/letter-spacing/color — is cleared when any
    /// of those channels changed. Tokens the edit itself authored survive,
    /// which is also how inverse operations restore bindings on undo.
    /// The content string after the display-time case transform (A6a D1). The
    /// single helper EVERY consumer — both measurers, SVG, Skia, PDF — calls
    /// before shaping/measuring/emitting, so measure and render can never
    /// disagree on the cased string. Never mutates `content`.
    pub fn transformed_content(&self) -> std::borrow::Cow<'_, str> {
        self.text_transform.apply(&self.content)
    }

    pub fn clear_stale_tokens(&mut self, before: &TextNode, explicit: ExplicitTextTokens) {
        if !explicit.font_size && self.font_size != before.font_size {
            self.font_size_token = None;
        }
        if !explicit.line_height && self.line_height != before.line_height {
            self.line_height_token = None;
        }
        if !explicit.letter_spacing && self.letter_spacing != before.letter_spacing {
            self.letter_spacing_token = None;
        }
        let role_channel_changed = self.font_family != before.font_family
            || self.font_size != before.font_size
            || self.font_weight != before.font_weight
            || self.line_height != before.line_height
            || self.letter_spacing != before.letter_spacing;
        if !explicit.style && role_channel_changed {
            self.style_token = None;
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextAlign {
    Left,
    Center,
    Right,
    Justify,
}

/// Vertical alignment of text within its box (A7a D2). Serialized snake_case
/// like the sibling text enums. `Top` is the default (absent in serialized old
/// scenes).
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VerticalAlign {
    #[default]
    Top,
    Center,
    Bottom,
}

/// A7a D3: the single shared vertical-alignment formula. Slack (box height
/// minus painted content height) is clamped at zero so an overflowing box
/// never paints text above its top edge — valign degrades to a no-op and
/// LUMV0903 (vertical overflow) fires unchanged, because validation compares
/// measured height vs bounds and never sees this paint offset. Factor:
/// top=0.0, center=0.5, bottom=1.0. EVERY paint site (skia fast/stacked/
/// spanned, SVG, PDF, and the editor's CanvasKit + DOM legs) derives its
/// offset from this one function so the eight backends cannot drift.
pub fn valign_offset(box_height: f64, content_height: f64, valign: VerticalAlign) -> f64 {
    let factor = match valign {
        VerticalAlign::Top => 0.0,
        VerticalAlign::Center => 0.5,
        VerticalAlign::Bottom => 1.0,
    };
    (box_height - content_height).max(0.0) * factor
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextWrap {
    NoWrap,
    Wrap,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextDirection {
    Ltr,
    Rtl,
    Auto,
}

fn default_text_line_height() -> f64 {
    1.2
}

fn default_text_wrap() -> TextWrap {
    TextWrap::NoWrap
}

fn default_text_direction() -> TextDirection {
    TextDirection::Ltr
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImageNode {
    pub asset_id: AssetId,
    pub alt: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VectorNode {
    pub path_data: String,
    /// Source viewBox `[width, height]` the path was authored against. When present
    /// (e.g. a `svg(icon:name)` library icon at 24×24), renderers scale the path
    /// uniformly and center it within the node's box. `None` (a hand-authored
    /// `vector path(...)`) draws the path at its raw coordinates, unchanged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub view_box: Option<[f64; 2]>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LineNode {
    pub x2: f64,
    pub y2: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AutoLayoutNode {
    pub direction: AutoLayoutDirection,
    pub wrap: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AutoLayoutDirection {
    Row,
    Column,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LayoutAnchor {
    Start,
    Center,
    End,
    SpaceBetween,
    Stretch,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AutoLayoutProps {
    pub gap: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gap_token: Option<String>,
    pub padding: [f64; 4],
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub padding_token: Option<String>,
    pub grow: f64,
    #[serde(default = "default_layout_anchor_start")]
    pub align_x: LayoutAnchor,
    #[serde(default = "default_layout_anchor_start")]
    pub align_y: LayoutAnchor,
    /// Phase 1 freehand: Stack (default) keeps the flex solve; Free lays the
    /// container's children out at their own baked transforms. Serde-defaulted
    /// and omitted when Stack so pre-freehand JSON round-trips byte-identically.
    #[serde(default, skip_serializing_if = "layout_mode_is_stack")]
    pub layout_mode: LayoutMode,
}

impl Default for AutoLayoutProps {
    fn default() -> Self {
        Self {
            gap: 0.0,
            gap_token: None,
            padding: [0.0; 4],
            padding_token: None,
            grow: 0.0,
            align_x: LayoutAnchor::Start,
            align_y: LayoutAnchor::Start,
            layout_mode: LayoutMode::Stack,
        }
    }
}

fn default_layout_anchor_start() -> LayoutAnchor {
    LayoutAnchor::Start
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Transform {
    pub x: f64,
    pub y: f64,
    pub rotation: f64,
    pub skew_x: f64,
    pub skew_y: f64,
    pub flip_x: bool,
    pub flip_y: bool,
}

impl Default for Transform {
    fn default() -> Self {
        Self {
            x: 0.0,
            y: 0.0,
            rotation: 0.0,
            skew_x: 0.0,
            skew_y: 0.0,
            flip_x: false,
            flip_y: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SizeSpec {
    pub width: Dimension,
    pub height: Dimension,
}

impl SizeSpec {
    pub fn fixed(width: f64, height: f64) -> Self {
        Self {
            width: Dimension::Fixed(width),
            height: Dimension::Fixed(height),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum Dimension {
    Fixed(f64),
    Hug,
    Fill { weight: f64 },
    Token { token: String },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Fill {
    pub id: PaintId,
    pub paint: Paint,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Stroke {
    pub id: PaintId,
    pub paint: Paint,
    pub width: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub width_token: Option<String>,
    /// Dash pattern in scene units; `None` renders a solid stroke.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dash: Option<Vec<f64>>,
    #[serde(default, skip_serializing_if = "is_enum_default")]
    pub cap: StrokeCap,
    #[serde(default, skip_serializing_if = "is_enum_default")]
    pub join: StrokeJoin,
    #[serde(default, skip_serializing_if = "is_enum_default")]
    pub align: StrokeAlign,
}

impl Stroke {
    pub fn solid(id: impl Into<PaintId>, paint: Paint, width: f64) -> Self {
        Self {
            id: id.into(),
            paint,
            width,
            width_token: None,
            dash: None,
            cap: StrokeCap::default(),
            join: StrokeJoin::default(),
            align: StrokeAlign::default(),
        }
    }
}

/// Serde helper: skip serializing enum fields that still hold their default
/// so pre-effects JSON fixtures and pinned parity operations stay
/// byte-identical.
fn is_enum_default<T: Default + PartialEq>(value: &T) -> bool {
    value == &T::default()
}

/// Serde helper: skip serializing a `bool` field that still holds `false`,
/// keeping pre-A4 scene JSON byte-identical (used by `Node.bleed`).
fn is_false(value: &bool) -> bool {
    !*value
}

/// Serde helper: skip serializing an `f64` field that still holds `0.0`, so
/// pre-A6a scenes serialize `paragraph_spacing`-free and stay byte-identical.
fn is_zero(value: &f64) -> bool {
    *value == 0.0
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StrokeCap {
    #[default]
    Butt,
    Round,
    Square,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StrokeJoin {
    #[default]
    Miter,
    Round,
    Bevel,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StrokeAlign {
    #[default]
    Center,
    Inside,
    Outside,
}

/// A single entry in a node's effect stack. The id is the edit contract:
/// every entry is individually addressable by Phase D per-entry patches.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Effect {
    pub id: EffectId,
    pub kind: EffectKind,
}

/// Effects v1 vocabulary: outer drop shadow, outer glow, layer blur, and
/// inner shadow. The enum stays open (serde tag `kind`, snake_case) for later
/// kinds (backdrop blur, inner glow, ...) which belong to effects-v2+.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EffectKind {
    DropShadow {
        color: Color,
        opacity: f64,
        x: f64,
        y: f64,
        blur: f64,
        spread: f64,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        color_token: Option<String>,
    },
    /// Outer glow: zero-offset shadow semantics (dilate by `spread`, gaussian
    /// `blur`, merged beneath the source). Inner glow is not in v1.
    Glow {
        color: Color,
        opacity: f64,
        blur: f64,
        spread: f64,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        color_token: Option<String>,
    },
    /// Gaussian blur of the node's own rendering. Serde tag `layer_blur`
    /// reserves `backdrop_blur` for a later effects wave.
    LayerBlur {
        radius: f64,
    },
    /// Inner shadow: drawn over the node's rendering and clipped to its alpha;
    /// `spread` erodes the shape inward before the shadow is computed.
    InnerShadow {
        color: Color,
        opacity: f64,
        x: f64,
        y: f64,
        blur: f64,
        spread: f64,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        color_token: Option<String>,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Paint {
    Solid { color: Color },
    LinearGradient { angle: f64, stops: Vec<ColorStop> },
    RadialGradient { stops: Vec<ColorStop> },
    Token { token: String },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ColorStop {
    pub color: Color,
    pub position: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Color {
    Hex { value: String },
    Token { token: String },
    Oklch { l: f64, c: f64, h: f64, alpha: f64 },
}

/// Parse a CSS-style hex color (`#RGB`, `#RGBA`, `#RRGGBB`, `#RRGGBBAA`,
/// leading `#` optional) into RGBA bytes. The single hex-literal parser for
/// the whole engine — DSL literals and paint predicates both resolve
/// through here.
pub fn parse_hex_rgba(value: &str) -> Option<(u8, u8, u8, u8)> {
    let hex = value.trim().trim_start_matches('#');
    let h = |s: &str| u8::from_str_radix(s, 16).ok();
    match hex.len() {
        3 | 4 => {
            let mut ch = hex.chars();
            let d = |c: char| c.to_digit(16).map(|v| (v * 17) as u8);
            let r = d(ch.next()?)?;
            let g = d(ch.next()?)?;
            let b = d(ch.next()?)?;
            let a = match ch.next() {
                Some(c) => d(c)?,
                None => 255,
            };
            Some((r, g, b, a))
        }
        6 => Some((h(&hex[0..2])?, h(&hex[2..4])?, h(&hex[4..6])?, 255)),
        8 => Some((
            h(&hex[0..2])?,
            h(&hex[2..4])?,
            h(&hex[4..6])?,
            h(&hex[6..8])?,
        )),
        _ => None,
    }
}

impl Color {
    /// Whether this color PROVABLY carries full alpha. Unresolved tokens and
    /// unparseable hex return `false` — callers that gate print guarantees on
    /// opacity must never treat an unknown as opaque.
    pub fn is_opaque(&self) -> bool {
        match self {
            Color::Hex { value } => {
                parse_hex_rgba(value).is_some_and(|(_, _, _, alpha)| alpha == 255)
            }
            Color::Token { .. } => false,
            Color::Oklch { alpha, .. } => *alpha >= 1.0,
        }
    }
}

impl Paint {
    /// Whether this paint PROVABLY covers its region with full alpha:
    /// an opaque solid, or a gradient whose every stop is opaque.
    /// Token paints and empty gradients return `false` (not provably
    /// opaque), never `true`-by-assumption.
    pub fn is_provably_opaque(&self) -> bool {
        match self {
            Paint::Solid { color } => color.is_opaque(),
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
                !stops.is_empty() && stops.iter().all(|stop| stop.color.is_opaque())
            }
            Paint::Token { .. } => false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CornerRadii {
    pub top_left: f64,
    pub top_right: f64,
    pub bottom_right: f64,
    pub bottom_left: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
}

impl Default for CornerRadii {
    fn default() -> Self {
        Self {
            top_left: 0.0,
            top_right: 0.0,
            bottom_right: 0.0,
            bottom_left: 0.0,
            token: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ComputedGeometry {
    pub layout_bounds: Rect,
    pub render_bounds: Rect,
    /// Editor Quality Plan 4 (item F): the PAINTED line boxes of a text node —
    /// page-space and unrotated, the frame `layout_bounds` is in — one per
    /// measured line, placed where the renderers put the glyphs (`align`
    /// across the box's horizontal slack, `valign` across its vertical slack;
    /// `layout::painted_text_lines`). Empty for every non-text node and for a
    /// text node no layout pass has placed. Never serialized when empty, so
    /// pre-Plan-4 scene JSON and every non-text node stay byte-identical.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub text_lines: Vec<Rect>,
}

#[cfg(test)]
mod a6_typography_tests {
    use super::*;

    #[test]
    fn transformed_content_is_unicode_correct_and_never_mutates() {
        let base = TextNode {
            content: "hello WORLD ßtraße".to_owned(),
            ..TextNode::default()
        };
        assert!(matches!(base.transformed_content(), std::borrow::Cow::Borrowed(_)));
        assert_eq!(base.transformed_content(), "hello WORLD ßtraße");

        let upper = TextNode { text_transform: TextTransform::Uppercase, ..base.clone() };
        assert_eq!(upper.transformed_content(), "HELLO WORLD SSTRASSE");

        let lower = TextNode { text_transform: TextTransform::Lowercase, ..base.clone() };
        assert_eq!(lower.transformed_content(), "hello world ßtraße");

        let title = TextNode {
            content: "the quick brown-fox 3rd".to_owned(),
            text_transform: TextTransform::Title,
            ..TextNode::default()
        };
        // First alphabetic char of each whitespace word uppercased; the rest of
        // the word (incl. the char after the hyphen) untouched; whitespace kept.
        assert_eq!(title.transformed_content(), "The Quick Brown-fox 3rd");

        // The stored content is never mutated by any transform.
        assert_eq!(upper.content, "hello WORLD ßtraße");
    }

    #[test]
    fn old_scene_json_deserializes_with_a6_defaults() {
        // A pre-A6a text node carries none of the five new keys.
        let json = r#"{
            "content": "Legacy",
            "font_family": "Inter",
            "font_size": 16.0,
            "font_weight": 400,
            "align": "left"
        }"#;
        let node: TextNode = serde_json::from_str(json).expect("legacy text node deserializes");
        assert_eq!(node.text_transform, TextTransform::None);
        assert!(!node.underline);
        assert!(!node.strikethrough);
        assert!(!node.italic);
        assert!(!node.truncate);
        assert_eq!(node.paragraph_spacing, 0.0);
        // A7a: a pre-valign node deserializes to Top.
        assert_eq!(node.valign, VerticalAlign::Top);
    }

    #[test]
    fn default_text_node_serializes_without_valign_key() {
        // A7a: a default (Top) valign must not emit a key, so golden scene JSON
        // stays byte-identical; a non-default value round-trips.
        let value = serde_json::to_value(TextNode::default()).expect("serializes");
        assert!(!value.as_object().unwrap().contains_key("valign"));

        let centered = TextNode {
            valign: VerticalAlign::Center,
            ..TextNode::default()
        };
        let value = serde_json::to_value(&centered).expect("serializes");
        assert_eq!(value["valign"], serde_json::json!("center"));
        let back: TextNode = serde_json::from_value(value).expect("round-trips");
        assert_eq!(back.valign, VerticalAlign::Center);
    }

    #[test]
    fn default_text_node_serializes_without_a6_keys() {
        // Bit-for-bit: a default node must not emit the new fields, so existing
        // golden scene JSON stays byte-identical.
        let value = serde_json::to_value(TextNode::default()).expect("serializes");
        let obj = value.as_object().expect("object");
        assert!(!obj.contains_key("text_transform"));
        assert!(!obj.contains_key("underline"));
        assert!(!obj.contains_key("strikethrough"));
        assert!(!obj.contains_key("italic"));
        assert!(!obj.contains_key("truncate"));
        assert!(!obj.contains_key("paragraph_spacing"));
    }
}
