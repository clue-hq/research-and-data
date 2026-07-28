//! The versioned platform layer: one vetted interaction runtime + component
//! base styles, inlined by the renderer ONLY when the page uses them. This
//! is the delivery guarantee's single script exception — never any
//! agent-authored code.
pub const PLATFORM_RUNTIME_VERSION: u32 = 1;
pub const PLATFORM_RUNTIME_JS: &str = include_str!("runtime/lumen-runtime.v1.js");
pub const PLATFORM_CSS: &str = include_str!("runtime/lumen-platform.v1.css");
