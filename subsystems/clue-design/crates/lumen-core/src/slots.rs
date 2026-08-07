use crate::ids::{NodeId, PageId, SlotId, SlotKey};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Slot {
    pub id: SlotId,
    pub key: SlotKey,
    pub label: String,
    pub content_type: ContentType,
    pub scope: SlotScope,
    pub bound_nodes: Vec<NodeId>,
    pub required: bool,
    pub placeholder: Option<String>,
    pub overflow: OverflowPolicy,
    pub formatting: FormattingConstraints,
    pub cardinality: Cardinality,
    pub conditional: Option<ConditionalRule>,
    pub repeater: Option<RepeaterRule>,
    pub validation: ValidationFixtures,
    pub image_policy: Option<ImagePolicy>,
    pub editability: Editability,
    pub binding_hints: Vec<BindingHint>,
}

impl Slot {
    pub fn text_short(id: SlotId, key: SlotKey, label: impl Into<String>) -> Self {
        Self {
            id,
            key,
            label: label.into(),
            content_type: ContentType::TextShort,
            scope: SlotScope::Document,
            bound_nodes: Vec::new(),
            required: true,
            placeholder: None,
            overflow: OverflowPolicy::Error,
            formatting: FormattingConstraints::default(),
            cardinality: Cardinality::single(),
            conditional: None,
            repeater: None,
            validation: ValidationFixtures::default(),
            image_policy: None,
            editability: Editability::TemplateAndInstance,
            binding_hints: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContentType {
    TextShort,
    TextLong,
    RichTextLimited,
    NumberStat,
    Date,
    Image,
    Logo,
    UrlQr,
    List,
    RepeaterGroup,
    TableLike,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum SlotScope {
    Document,
    Page(PageId),
    Node(NodeId),
    Group(NodeId),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum OverflowPolicy {
    ShrinkFont {
        min_font_size: f64,
        max_font_size: Option<f64>,
    },
    Wrap {
        max_lines: Option<u16>,
    },
    Clip,
    Ellipsis,
    ExpandContainer,
    Error,
    AskAgentToRepair,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FormattingConstraints {
    pub max_length: Option<usize>,
    pub allowed_pattern: Option<String>,
    pub preserve_case: bool,
}

impl Default for FormattingConstraints {
    fn default() -> Self {
        Self {
            max_length: None,
            allowed_pattern: None,
            preserve_case: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Cardinality {
    pub min_items: u16,
    pub max_items: Option<u16>,
}

impl Cardinality {
    pub fn single() -> Self {
        Self {
            min_items: 1,
            max_items: Some(1),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConditionalRule {
    pub expression: String,
    pub when_false: EmptyBehavior,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmptyBehavior {
    HideRegion,
    PreservePlaceholder,
    UseFallback,
    ValidationError,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RepeaterRule {
    pub template_node_id: NodeId,
    pub item_slot_key: SlotKey,
    pub min_items: u16,
    pub max_items: Option<u16>,
    pub reflow: ReflowPolicy,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReflowPolicy {
    Stack,
    Wrap,
    Paginate,
    ErrorIfOverflow,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Default)]
pub struct ValidationFixtures {
    pub samples: Vec<String>,
    pub worst_case: Option<String>,
    pub max_length: Option<usize>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImagePolicy {
    pub fit: ImageFitMode,
    pub focal_point: Option<FocalPoint>,
    pub min_dpi: Option<u16>,
    pub preserve_transparency: bool,
    pub aspect_ratio: Option<f64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageFitMode {
    Contain,
    Cover,
    Crop,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FocalPoint {
    pub x: f64,
    pub y: f64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Editability {
    TemplateOnly,
    InstanceOnly,
    TemplateAndInstance,
    LockedAfterFinalization,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BindingHint {
    pub source_path: String,
    pub confidence: Option<f64>,
}
