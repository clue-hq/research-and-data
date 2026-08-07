//! Phase G binding contracts (slice G1, plan section B2).
//!
//! A binding set is the per-recipient input to instance derivation. It is
//! data, never operations: instances derive from
//! `finalized snapshot + binding set + asset store`, never op-log replay.
//! This module stays wasm-clean — validation consumes only scene semantics.
//!
//! Diagnostic namespace: `LUMG00xx` (binding contracts), `LUMG01xx`
//! (conditional grammar), `LUMG02xx` (generated asset specs).

use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{AssetId, SlotKey, TemplateRevisionId};
use crate::scene::{DocumentStatus, Scene};
use crate::slots::{Cardinality, ContentType, ReflowPolicy, Slot};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Per-recipient binding set (plan section B2, implemented verbatim).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BindingSet {
    pub schema_version: u32,
    pub binding_set_id: String,
    pub template_revision_id: TemplateRevisionId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub audience: Option<BindingAudience>,
    #[serde(default)]
    pub values: BTreeMap<String, BoundValue>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub links: BTreeMap<String, InstanceLink>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub generated: BTreeMap<String, GeneratedAssetSpec>,
}

pub const BINDING_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct BindingAudience {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub account_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub contact_id: Option<String>,
}

/// One bound value, kind-tagged per the slot `ContentType` it must match.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum BoundValue {
    Text { value: String },
    Asset { asset_id: AssetId },
    List { items: Vec<BoundValue> },
}

impl BoundValue {
    pub fn kind_name(&self) -> &'static str {
        match self {
            Self::Text { .. } => "text",
            Self::Asset { .. } => "asset",
            Self::List { .. } => "list",
        }
    }

    /// Presence semantics for conditional evaluation: text must be
    /// non-blank, lists non-empty; assets are present by construction.
    pub fn is_present(&self) -> bool {
        match self {
            Self::Text { value } => !value.trim().is_empty(),
            Self::Asset { .. } => true,
            Self::List { items } => !items.is_empty(),
        }
    }
}

/// The entire landing-page coupling surface (decision B1): the engine
/// allocates URLs, encodes them in QR assets, and exposes binding values.
/// Nothing here may assume landing pages render through the scene model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InstanceLink {
    pub url: String,
}

/// A per-instance generated asset request, executed through the Phase E
/// provider registry at derivation time. Digest-stable: same input bytes
/// produce the same stored asset.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GeneratedAssetSpec {
    pub provider: String,
    #[serde(default)]
    pub input: GeneratedAssetInput,
    pub bind_to_slot: SlotKey,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct GeneratedAssetInput {
    /// Dotted path into the binding set's links: `links.{name}.url`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url_from: Option<String>,
    /// QR error-correction level: one of `l`, `m`, `q`, `h`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ec_level: Option<String>,
    /// Free-form prompt for generation providers that take one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prompt: Option<String>,
}

impl BindingSet {
    pub fn from_json(source: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(source)
    }

    /// Resolve a `links.{name}.url` path against this binding set.
    pub fn resolve_link_path(&self, path: &str) -> Option<&str> {
        let rest = path.strip_prefix("links.")?;
        let name = rest.strip_suffix(".url")?;
        self.links.get(name).map(|link| link.url.as_str())
    }
}

// ---------------------------------------------------------------------------
// Conditional grammar (FROZEN for V0)
// ---------------------------------------------------------------------------

/// The complete V0 conditional vocabulary: `has(slot_key)`,
/// `missing(slot_key)`, `eq(slot_key,"literal")`. Anything else is a
/// validation error naming the unsupported form — no general expression
/// language.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConditionalExpr {
    Has(SlotKey),
    Missing(SlotKey),
    Eq(SlotKey, String),
}

impl ConditionalExpr {
    /// Parse the frozen V0 grammar. Errors carry a message naming the
    /// unsupported form so agents and authors see exactly what was
    /// rejected.
    pub fn parse(expression: &str) -> Result<Self, String> {
        let trimmed = expression.trim();
        if trimmed.is_empty() {
            return Err("conditional expression is empty; expected has(slot_key), missing(slot_key), or eq(slot_key,\"literal\")".to_owned());
        }
        let Some(open) = trimmed.find('(') else {
            return Err(format!(
                "unsupported conditional form {trimmed:?}; V0 supports has(slot_key), missing(slot_key), and eq(slot_key,\"literal\")"
            ));
        };
        if !trimmed.ends_with(')') {
            return Err(format!(
                "unsupported conditional form {trimmed:?}: missing closing parenthesis"
            ));
        }
        let function = trimmed[..open].trim();
        let arguments = &trimmed[open + 1..trimmed.len() - 1];

        match function {
            "has" => Ok(Self::Has(parse_slot_key_argument(arguments, trimmed)?)),
            "missing" => Ok(Self::Missing(parse_slot_key_argument(arguments, trimmed)?)),
            "eq" => {
                let Some(comma) = arguments.find(',') else {
                    return Err(format!(
                        "unsupported conditional form {trimmed:?}: eq takes (slot_key,\"literal\")"
                    ));
                };
                let slot_key = parse_slot_key_argument(&arguments[..comma], trimmed)?;
                let literal_raw = arguments[comma + 1..].trim();
                let literal = literal_raw
                    .strip_prefix('"')
                    .and_then(|rest| rest.strip_suffix('"'))
                    .ok_or_else(|| {
                        format!(
                            "unsupported conditional form {trimmed:?}: eq literal must be double-quoted"
                        )
                    })?;
                if literal.contains('"') {
                    return Err(format!(
                        "unsupported conditional form {trimmed:?}: eq literal cannot contain quotes"
                    ));
                }
                Ok(Self::Eq(slot_key, literal.to_owned()))
            }
            other => Err(format!(
                "unsupported conditional function {other:?} in {trimmed:?}; V0 supports has, missing, and eq"
            )),
        }
    }

    pub fn slot_key(&self) -> &SlotKey {
        match self {
            Self::Has(key) | Self::Missing(key) | Self::Eq(key, _) => key,
        }
    }

    /// Evaluate against a binding set's values using the presence
    /// semantics of [`BoundValue::is_present`].
    pub fn evaluate(&self, binding: &BindingSet) -> bool {
        match self {
            Self::Has(key) => binding
                .values
                .get(key.as_str())
                .is_some_and(BoundValue::is_present),
            Self::Missing(key) => !binding
                .values
                .get(key.as_str())
                .is_some_and(BoundValue::is_present),
            Self::Eq(key, literal) => match binding.values.get(key.as_str()) {
                Some(BoundValue::Text { value }) => value == literal,
                _ => false,
            },
        }
    }
}

fn parse_slot_key_argument(raw: &str, whole: &str) -> Result<SlotKey, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(format!(
            "unsupported conditional form {whole:?}: slot key argument is empty"
        ));
    }
    if trimmed.contains('"') || trimmed.contains('(') || trimmed.contains(',') {
        return Err(format!(
            "unsupported conditional form {whole:?}: slot key {trimmed:?} must be a bare key"
        ));
    }
    Ok(SlotKey::from(trimmed))
}

// ---------------------------------------------------------------------------
// Validation against a revision snapshot
// ---------------------------------------------------------------------------

/// Validate a binding set against the revision snapshot's slot contracts:
/// keys resolve, kinds match `ContentType`, required slots are covered (or
/// carry a conditional/fallback), cardinality holds, `max_length` is
/// enforced, the conditional grammar parses, and generated specs chain
/// `links.*.url -> provider -> UrlQr slot`.
pub fn validate_binding_set(scene: &Scene, binding: &BindingSet) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    if binding.schema_version != BINDING_SCHEMA_VERSION {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0003",
            format!(
                "binding set {} has schema_version {}; this runtime supports {}",
                binding.binding_set_id, binding.schema_version, BINDING_SCHEMA_VERSION
            ),
            Some(DiagnosticSubject::Document),
        ));
    }

    match &scene.meta.status {
        DocumentStatus::Finalized {
            template_revision_id,
        } => {
            if template_revision_id != &binding.template_revision_id {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0002",
                    format!(
                        "binding set {} targets revision {} but the snapshot is revision {}",
                        binding.binding_set_id, binding.template_revision_id, template_revision_id
                    ),
                    Some(DiagnosticSubject::Document),
                ));
            }
        }
        DocumentStatus::Draft => {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0001",
                format!(
                    "binding set {} requires a finalized template revision; the snapshot is a draft",
                    binding.binding_set_id
                ),
                Some(DiagnosticSubject::Document),
            ));
        }
    }

    // Slot keys owned by a repeater (item slots) bind through the
    // repeater's list, never directly.
    let item_slot_keys: Vec<&SlotKey> = scene
        .slots
        .values()
        .filter_map(|slot| slot.repeater.as_ref())
        .map(|repeater| &repeater.item_slot_key)
        .collect();

    for (key, value) in &binding.values {
        let slot_key = SlotKey::from(key.as_str());
        let Some(slot) = scene.slot_by_key(&slot_key) else {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0010",
                format!("binding value key {key:?} does not resolve to a slot on the revision"),
                Some(DiagnosticSubject::Document),
            ));
            continue;
        };

        if item_slot_keys.contains(&&slot_key) {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0016",
                format!(
                    "slot {key} is a repeater item slot; bind items through the repeater group list"
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
            continue;
        }

        validate_value_against_slot(slot, key, value, scene, &mut diagnostics);
    }

    // Required coverage: every required slot needs a value, a conditional
    // rule that legitimizes absence, or (for UrlQr) a generated entry.
    for slot in scene.slots.values() {
        if !slot.required || item_slot_keys.contains(&&slot.key) {
            continue;
        }
        let has_value = binding
            .values
            .get(slot.key.as_str())
            .is_some_and(BoundValue::is_present);
        let generated_covers = matches!(slot.content_type, ContentType::UrlQr)
            && binding
                .generated
                .values()
                .any(|spec| spec.bind_to_slot == slot.key);
        if !has_value && !generated_covers && slot.conditional.is_none() {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0012",
                format!(
                    "required slot {} has no bound value in binding set {}",
                    slot.key, binding.binding_set_id
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }
    }

    // Conditional grammar is frozen; parse every rule the revision carries.
    for slot in scene.slots.values() {
        let Some(rule) = &slot.conditional else {
            continue;
        };
        match ConditionalExpr::parse(&rule.expression) {
            Ok(expression) => {
                if scene.slot_by_key(expression.slot_key()).is_none() {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMG0101",
                        format!(
                            "conditional on slot {} references unknown slot key {}",
                            slot.key,
                            expression.slot_key()
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
            }
            Err(message) => {
                diagnostics.push(
                    Diagnostic::error(
                        Phase::Validation,
                        "LUMG0100",
                        format!("conditional on slot {}: {message}", slot.key),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    )
                    .with_hint(
                        "V0 conditional grammar is frozen: has(slot_key), missing(slot_key), eq(slot_key,\"literal\").",
                    ),
                );
            }
        }
    }

    // Paginate is owned by the print workstream; V0 refuses it loudly.
    for slot in scene.slots.values() {
        if let Some(repeater) = &slot.repeater {
            if matches!(repeater.reflow, ReflowPolicy::Paginate)
                && binding.values.contains_key(slot.key.as_str())
            {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0018",
                    format!(
                        "repeater slot {} requests paginate reflow, which V0 does not execute",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }
    }

    for (name, spec) in &binding.generated {
        validate_generated_spec(scene, binding, name, spec, &mut diagnostics);
    }

    diagnostics
}

fn validate_value_against_slot(
    slot: &Slot,
    key: &str,
    value: &BoundValue,
    scene: &Scene,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let subject = Some(DiagnosticSubject::Slot(slot.id.clone()));
    let mismatch = |expected: &str, diagnostics: &mut Vec<Diagnostic>| {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0011",
            format!(
                "slot {key} ({:?}) expects a {expected} value; binding provides kind {}",
                slot.content_type,
                value.kind_name()
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
    };

    match (&slot.content_type, value) {
        (
            ContentType::TextShort
            | ContentType::TextLong
            | ContentType::RichTextLimited
            | ContentType::NumberStat
            | ContentType::Date,
            BoundValue::Text { value: text },
        ) => {
            let max_length = slot.formatting.max_length.or(slot.validation.max_length);
            if let Some(max_length) = max_length {
                let length = text.chars().count();
                if length > max_length {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMG0014",
                        format!(
                            "slot {key} value is {length} characters; max_length is {max_length}"
                        ),
                        subject,
                    ));
                }
            }
        }
        (ContentType::Image | ContentType::Logo, BoundValue::Asset { .. }) => {}
        (ContentType::List | ContentType::RepeaterGroup, BoundValue::List { items }) => {
            let cardinality = effective_cardinality(slot);
            let count = items.len();
            if count < cardinality.min_items as usize
                || cardinality
                    .max_items
                    .is_some_and(|max_items| count > max_items as usize)
            {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0013",
                    format!(
                        "slot {key} received {count} items; cardinality allows {}..{}",
                        cardinality.min_items,
                        cardinality
                            .max_items
                            .map(|max_items| max_items.to_string())
                            .unwrap_or_else(|| "unbounded".to_owned())
                    ),
                    subject.clone(),
                ));
            }

            let item_max_length = slot
                .repeater
                .as_ref()
                .and_then(|repeater| scene.slot_by_key(&repeater.item_slot_key))
                .and_then(|item_slot| {
                    item_slot
                        .formatting
                        .max_length
                        .or(item_slot.validation.max_length)
                });
            for (index, item) in items.iter().enumerate() {
                match item {
                    BoundValue::Text { value: text } => {
                        if let Some(max_length) = item_max_length {
                            let length = text.chars().count();
                            if length > max_length {
                                diagnostics.push(Diagnostic::error(
                                    Phase::Validation,
                                    "LUMG0014",
                                    format!(
                                        "slot {key} item {index} is {length} characters; max_length is {max_length}"
                                    ),
                                    subject.clone(),
                                ));
                            }
                        }
                    }
                    other => {
                        diagnostics.push(Diagnostic::error(
                            Phase::Validation,
                            "LUMG0015",
                            format!(
                                "slot {key} item {index} has kind {}; V0 lists carry text items only",
                                other.kind_name()
                            ),
                            subject.clone(),
                        ));
                    }
                }
            }
        }
        (ContentType::UrlQr, _) => {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0011",
                format!(
                    "slot {key} is a url_qr slot; bind it through a generated entry (links.*.url -> provider qr), not a direct value"
                ),
                subject,
            ));
        }
        (ContentType::TableLike, _) => {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMG0011",
                format!("slot {key} is table_like, which the V0 runtime does not bind"),
                subject,
            ));
        }
        (ContentType::TextShort, _)
        | (ContentType::TextLong, _)
        | (ContentType::RichTextLimited, _)
        | (ContentType::NumberStat, _)
        | (ContentType::Date, _) => mismatch("text", diagnostics),
        (ContentType::Image | ContentType::Logo, _) => mismatch("asset", diagnostics),
        (ContentType::List | ContentType::RepeaterGroup, _) => mismatch("list", diagnostics),
    }
}

fn effective_cardinality(slot: &Slot) -> Cardinality {
    match &slot.repeater {
        Some(repeater) => Cardinality {
            min_items: repeater.min_items.max(slot.cardinality.min_items),
            max_items: match (repeater.max_items, slot.cardinality.max_items) {
                (Some(a), Some(b)) => Some(a.min(b)),
                (Some(a), None) => Some(a),
                (None, Some(b)) => Some(b),
                (None, None) => None,
            },
        },
        None => slot.cardinality.clone(),
    }
}

fn validate_generated_spec(
    scene: &Scene,
    binding: &BindingSet,
    name: &str,
    spec: &GeneratedAssetSpec,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(slot) = scene.slot_by_key(&spec.bind_to_slot) else {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0200",
            format!(
                "generated entry {name:?} binds to unknown slot key {}",
                spec.bind_to_slot
            ),
            Some(DiagnosticSubject::Document),
        ));
        return;
    };

    if !matches!(slot.content_type, ContentType::UrlQr) {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMG0201",
            format!(
                "generated entry {name:?} binds to slot {} ({:?}); V0 generated bindings target url_qr slots",
                slot.key, slot.content_type
            ),
            Some(DiagnosticSubject::Slot(slot.id.clone())),
        ));
    }

    if spec.provider == "qr" {
        match &spec.input.url_from {
            Some(path) => {
                if binding.resolve_link_path(path).is_none() {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMG0202",
                        format!(
                            "generated entry {name:?} url_from {path:?} does not resolve to a link; expected links.{{name}}.url"
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
            }
            None => {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0202",
                    format!("generated entry {name:?} (provider qr) requires input.url_from"),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }
        if let Some(ec_level) = &spec.input.ec_level {
            if !matches!(
                ec_level.to_ascii_lowercase().as_str(),
                "l" | "m" | "q" | "h"
            ) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMG0203",
                    format!(
                        "generated entry {name:?} has invalid ec_level {ec_level:?}; expected l, m, q, or h"
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frozen_grammar_parses_the_three_forms() {
        assert_eq!(
            ConditionalExpr::parse("has(research.quote)"),
            Ok(ConditionalExpr::Has(SlotKey::from("research.quote")))
        );
        assert_eq!(
            ConditionalExpr::parse("  missing( research.quote ) "),
            Ok(ConditionalExpr::Missing(SlotKey::from("research.quote")))
        );
        assert_eq!(
            ConditionalExpr::parse("eq(campaign.cta,\"Book your demo\")"),
            Ok(ConditionalExpr::Eq(
                SlotKey::from("campaign.cta"),
                "Book your demo".to_owned()
            ))
        );
    }

    #[test]
    fn frozen_grammar_rejects_everything_else_naming_the_form() {
        for unsupported in [
            "research.quote",
            "not(has(research.quote))",
            "has(research.quote) && has(campaign.cta)",
            "eq(campaign.cta,unquoted)",
            "contains(research.quote,\"x\")",
            "",
        ] {
            let error = ConditionalExpr::parse(unsupported)
                .expect_err("unsupported forms must be rejected");
            assert!(
                error.contains("unsupported conditional")
                    || error.contains("conditional expression is empty"),
                "error must name the unsupported form: {error}"
            );
        }
    }
}
