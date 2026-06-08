use crate::assets::{AssetPlacement, AssetRecord};
use crate::export_contract::ExportProfile;
use crate::ids::{
    AssetId, BrandKitId, DocumentId, NodeId, PageId, PaintId, SlotId, SlotKey, TemplateRevisionId,
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
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Unit {
    Px,
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
    pub corner: CornerRadii,
    pub opacity: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub opacity_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_asset_id: Option<AssetId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub asset_placement: Option<AssetPlacement>,
    pub clip: bool,
    pub layout: Option<AutoLayoutProps>,
    pub computed: Option<ComputedGeometry>,
    pub locked: bool,
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
            corner: CornerRadii::default(),
            opacity: 1.0,
            opacity_token: None,
            source_asset_id: None,
            asset_placement: None,
            clip: false,
            layout: None,
            computed: None,
            locked: false,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style_token: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TextAlign {
    Left,
    Center,
    Right,
    Justify,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImageNode {
    pub asset_id: AssetId,
    pub alt: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VectorNode {
    pub path_data: String,
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

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AutoLayoutProps {
    pub gap: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gap_token: Option<String>,
    pub padding: [f64; 4],
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub padding_token: Option<String>,
    pub grow: f64,
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
}
