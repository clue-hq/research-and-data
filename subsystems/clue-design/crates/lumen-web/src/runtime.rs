//! The versioned platform layer: one vetted interaction runtime + component
//! base styles, inlined by the renderer ONLY when the page uses them. This
//! is the delivery guarantee's single script exception — never any
//! agent-authored code.
pub const PLATFORM_RUNTIME_VERSION: u32 = 2;
pub const PLATFORM_RUNTIME_JS: &str = include_str!("runtime/lumen-runtime.v2.js");
pub const PLATFORM_CSS: &str = include_str!("runtime/lumen-platform.v2.css");
pub const TABS_CSS: &str = include_str!("runtime/lumen-tabs.v2.css");
