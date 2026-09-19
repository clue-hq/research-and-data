//! Shared SVG asset preparation for native painting. Skia parses inline styles
//! but ignores embedded stylesheets, silently painting class-filled paths black.
//! Resolve those rules into a transient inline style; never mutate stored bytes.
//!
//! This supports simplecss's static CSS 2.1 selector/declaration subset, not full
//! browser CSS: at-rules (including imports/font-face/media), escaped selectors,
//! CSS variables and interactive pseudo-classes are not implemented. No external
//! stylesheets/resources are fetched. Skia still owns property-value support,
//! inheritance, geometry, text and drawing; this is not a second SVG renderer.

use quick_xml::events::{BytesStart, Event};
use quick_xml::{Reader, Writer};
use simplecss::{AttributeOperator, DeclarationTokenizer, Element, PseudoClass, StyleSheet};
use std::borrow::Cow;

pub(crate) fn parse(svg_bytes: &[u8]) -> Result<skia_safe::svg::Dom, String> {
    let prepared = inline_stylesheets(svg_bytes)?;
    skia_safe::svg::Dom::from_bytes(&prepared, skia_safe::FontMgr::new())
        .map_err(|error| error.to_string())
}

fn inline_stylesheets(bytes: &[u8]) -> Result<Cow<'_, [u8]>, String> {
    // Fast path keeps ordinary SVGs on the original parser and preserves its
    // accepted inputs. A false positive merely causes an XML inspection below.
    if !bytes.windows(5).any(|window| window == b"style") {
        return Ok(Cow::Borrowed(bytes));
    }
    let source = std::str::from_utf8(bytes).map_err(|error| error.to_string())?;
    // roxmltree performs no I/O, so legacy SVG DOCTYPE declarations do not
    // fetch an external DTD. Its built-in entity limits remain in effect.
    let document = roxmltree::Document::parse_with_options(
        source,
        roxmltree::ParsingOptions {
            allow_dtd: true,
            ..Default::default()
        },
    )
    .map_err(|error| error.to_string())?;
    let css = document
        .descendants()
        .filter(|node| {
            node.tag_name().name() == "style"
                && matches!(
                    node.tag_name().namespace(),
                    None | Some("http://www.w3.org/2000/svg")
                )
                && node.attribute("type").is_none_or(|kind| kind == "text/css")
                && node
                    .attribute("media")
                    .is_none_or(|media| matches!(media.trim(), "" | "all" | "screen"))
        })
        .flat_map(|node| node.children().filter_map(|child| child.text()))
        .collect::<Vec<_>>()
        .join("\n");
    let stylesheet = StyleSheet::parse(&css);
    if stylesheet.rules.is_empty() {
        return Ok(Cow::Borrowed(bytes));
    }

    let mut elements = document.descendants().filter(|node| node.is_element());
    let mut reader = Reader::from_reader(bytes);
    let mut writer = Writer::new(Vec::with_capacity(bytes.len()));
    loop {
        let event = reader.read_event().map_err(|error| error.to_string())?;
        let event = match event {
            Event::Start(start) => Event::Start(styled_element(
                start,
                elements.next().ok_or("SVG element traversal mismatch")?,
                &stylesheet,
            )?),
            Event::Empty(start) => Event::Empty(styled_element(
                start,
                elements.next().ok_or("SVG element traversal mismatch")?,
                &stylesheet,
            )?),
            Event::Eof => break,
            event => event,
        };
        writer
            .write_event(event)
            .map_err(|error| error.to_string())?;
    }
    Ok(Cow::Owned(writer.into_inner()))
}

fn styled_element<'a>(
    start: BytesStart<'a>,
    node: roxmltree::Node<'_, '_>,
    stylesheet: &StyleSheet<'_>,
) -> Result<BytesStart<'a>, String> {
    // simplecss sorts rules stably by specificity. Inline declarations follow
    // those rules, then !important declarations form the final priority band.
    let mut declarations = stylesheet
        .rules
        .iter()
        .filter(|rule| rule.selector.matches(&SvgElement(node)))
        .flat_map(|rule| rule.declarations.iter().cloned())
        .collect::<Vec<_>>();
    if declarations.is_empty() {
        return Ok(start);
    }
    declarations.extend(DeclarationTokenizer::from(
        node.attribute("style").unwrap_or(""),
    ));
    let mut style = String::new();
    for important in [false, true] {
        for declaration in declarations.iter().filter(|d| d.important == important) {
            // Retain duplicate declarations: Skia rejecting a later invalid
            // value must leave the preceding valid value in effect.
            style.push_str(declaration.name);
            style.push(':');
            style.push_str(declaration.value);
            style.push(';');
        }
    }
    let mut rebuilt = BytesStart::new(String::from_utf8_lossy(start.name().as_ref()).into_owned());
    for attribute in start.attributes() {
        let attribute = attribute.map_err(|error| error.to_string())?;
        if attribute.key.as_ref() != b"style" {
            rebuilt.push_attribute(attribute);
        }
    }
    // Appending after presentation attributes also removes Skia's dependence
    // on XML attribute order: CSS always outranks those presentation values.
    rebuilt.push_attribute(("style", style.as_str()));
    Ok(rebuilt.into_owned())
}

#[derive(Clone, Copy)]
struct SvgElement<'a, 'input>(roxmltree::Node<'a, 'input>);

impl Element for SvgElement<'_, '_> {
    fn parent_element(&self) -> Option<Self> {
        self.0.parent_element().map(Self)
    }

    fn prev_sibling_element(&self) -> Option<Self> {
        self.0
            .prev_siblings()
            .skip(1)
            .find(|node| node.is_element())
            .map(Self)
    }

    fn has_local_name(&self, name: &str) -> bool {
        self.0.tag_name().name() == name
    }

    fn attribute_matches(&self, name: &str, operator: AttributeOperator<'_>) -> bool {
        self.0
            .attribute(name)
            .is_some_and(|value| operator.matches(value))
    }

    fn pseudo_class_matches(&self, class: PseudoClass<'_>) -> bool {
        matches!(class, PseudoClass::FirstChild) && self.prev_sibling_element().is_none()
    }
}
