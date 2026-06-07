export type StableId = string;

export type DocumentId = StableId;
export type PageId = StableId;
export type NodeId = StableId;
export type SlotId = StableId;
export type SlotKey = string;
export type PaintId = StableId;
export type AssetId = StableId;
export type BrandKitId = StableId;
export type TemplateRevisionId = StableId;

export interface Scene {
  schema_version: number;
  meta: DocumentMeta;
  pages: Record<PageId, Page>;
  nodes: Record<NodeId, Node>;
  slots: Record<SlotId, Slot>;
  export_profiles: ExportProfile[];
}

export interface DocumentMeta {
  id: DocumentId;
  title: string;
  artifact_type: string | null;
  medium: Medium | null;
  brand_kit: BrandKitRef | null;
  status: DocumentStatus;
}

export type Medium = "print" | "digital" | "email" | "direct_mail" | "ad";

export interface BrandKitRef {
  id: BrandKitId;
  version: number;
}

export type DocumentStatus =
  | {
      kind: "draft";
    }
  | {
      kind: "finalized";
      template_revision_id: TemplateRevisionId;
    };

export interface Page {
  id: PageId;
  name: string;
  size: PageSize;
  children: NodeId[];
  bleed: Rect | null;
  safe_area: Rect | null;
  background: Fill[];
}

export interface PageSize {
  width: number;
  height: number;
  unit: Unit;
  preset: PagePreset | null;
  orientation: Orientation;
}

export type Unit = "px" | "mm" | "in";
export type PagePreset = "a4" | "us_letter" | "custom" | "linkedin_ad" | "envelope_dl";
export type Orientation = "portrait" | "landscape";

export interface Node {
  id: NodeId;
  name: string | null;
  kind: NodeKind;
  transform: Transform;
  size: SizeSpec;
  children: NodeId[];
  fills: Fill[];
  strokes: Stroke[];
  corner: CornerRadii;
  opacity: number;
  opacity_token?: string | null;
  clip: boolean;
  layout: AutoLayoutProps | null;
  computed: ComputedGeometry | null;
  locked: boolean;
}

export type NodeKind =
  | {
      kind: "frame";
    }
  | {
      kind: "group";
    }
  | {
      kind: "rect";
    }
  | {
      kind: "ellipse";
    }
  | ({
      kind: "line";
    } & LineNode)
  | ({
      kind: "text";
    } & TextNode)
  | ({
      kind: "image";
    } & ImageNode)
  | ({
      kind: "vector";
    } & VectorNode)
  | ({
      kind: "auto_layout";
    } & AutoLayoutNode)
  | {
      kind: "instance";
      source_node_id: NodeId;
    };

export interface TextNode {
  content: string;
  font_family: string;
  font_size: number;
  font_weight: number;
  align: TextAlign;
  style_token?: string | null;
}

export type TextAlign = "left" | "center" | "right" | "justify";

export interface ImageNode {
  asset_id: AssetId;
  alt: string | null;
}

export interface VectorNode {
  path_data: string;
}

export interface LineNode {
  x2: number;
  y2: number;
}

export interface AutoLayoutNode {
  direction: "row" | "column";
  wrap: boolean;
}

export interface AutoLayoutProps {
  gap: number;
  gap_token?: string | null;
  padding: [number, number, number, number];
  padding_token?: string | null;
  grow: number;
}

export interface Transform {
  x: number;
  y: number;
  rotation: number;
  skew_x: number;
  skew_y: number;
  flip_x: boolean;
  flip_y: boolean;
}

export interface SizeSpec {
  width: Dimension;
  height: Dimension;
}

export type Dimension =
  | {
      kind: "fixed";
      value: number;
    }
  | {
      kind: "hug";
    }
  | {
      kind: "fill";
      value: {
        weight: number;
      };
    }
  | {
      kind: "token";
      value: {
        token: string;
      };
    };

export interface Fill {
  id: PaintId;
  paint: Paint;
}

export interface Stroke {
  id: PaintId;
  paint: Paint;
  width: number;
  width_token?: string | null;
}

export type Paint =
  | {
      kind: "solid";
      color: Color;
    }
  | {
      kind: "linear_gradient";
      angle: number;
      stops: ColorStop[];
    }
  | {
      kind: "radial_gradient";
      stops: ColorStop[];
    }
  | {
      kind: "token";
      token: string;
    };

export interface ColorStop {
  color: Color;
  position: number;
}

export type Color =
  | {
      kind: "hex";
      value: string;
    }
  | {
      kind: "token";
      token: string;
    }
  | {
      kind: "oklch";
      l: number;
      c: number;
      h: number;
      alpha: number;
    };

export interface CornerRadii {
  top_left: number;
  top_right: number;
  bottom_right: number;
  bottom_left: number;
  token?: string | null;
}

export interface ComputedGeometry {
  layout_bounds: Rect;
  render_bounds: Rect;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Slot {
  id: SlotId;
  key: SlotKey;
  label: string;
  content_type: ContentType;
  scope: SlotScope;
  bound_nodes: NodeId[];
  required: boolean;
  placeholder: string | null;
  overflow: OverflowPolicy;
  formatting: FormattingConstraints;
  cardinality: Cardinality;
  conditional: ConditionalRule | null;
  repeater: RepeaterRule | null;
  validation: ValidationFixtures;
  image_policy: ImagePolicy | null;
  editability: Editability;
  binding_hints: BindingHint[];
}

export type ContentType =
  | "text_short"
  | "text_long"
  | "rich_text_limited"
  | "number_stat"
  | "date"
  | "image"
  | "logo"
  | "url_qr"
  | "list"
  | "repeater_group"
  | "table_like";

export type SlotScope =
  | {
      kind: "document";
    }
  | {
      kind: "page";
      id: PageId;
    }
  | {
      kind: "node";
      id: NodeId;
    }
  | {
      kind: "group";
      id: NodeId;
    };

export type OverflowPolicy =
  | {
      kind: "shrink_font";
      min_font_size: number;
      max_font_size: number | null;
    }
  | {
      kind: "wrap";
      max_lines: number | null;
    }
  | {
      kind: "clip";
    }
  | {
      kind: "ellipsis";
    }
  | {
      kind: "expand_container";
    }
  | {
      kind: "error";
    }
  | {
      kind: "ask_agent_to_repair";
    };

export interface FormattingConstraints {
  max_length: number | null;
  allowed_pattern: string | null;
  preserve_case: boolean;
}

export interface Cardinality {
  min_items: number;
  max_items: number | null;
}

export interface ConditionalRule {
  expression: string;
  when_false: EmptyBehavior;
}

export type EmptyBehavior =
  | "hide_region"
  | "preserve_placeholder"
  | "use_fallback"
  | "validation_error";

export interface RepeaterRule {
  template_node_id: NodeId;
  item_slot_key: SlotKey;
  min_items: number;
  max_items: number | null;
  reflow: ReflowPolicy;
}

export type ReflowPolicy = "stack" | "wrap" | "paginate" | "error_if_overflow";

export interface ValidationFixtures {
  samples: string[];
  worst_case: string | null;
  max_length: number | null;
}

export interface ImagePolicy {
  fit: ImageFitMode;
  focal_point: FocalPoint | null;
  min_dpi: number | null;
  preserve_transparency: boolean;
  aspect_ratio: number | null;
}

export type ImageFitMode = "contain" | "cover" | "crop";

export interface FocalPoint {
  x: number;
  y: number;
}

export type Editability =
  | "template_only"
  | "instance_only"
  | "template_and_instance"
  | "locked_after_finalization";

export interface BindingHint {
  source_path: string;
  confidence: number | null;
}

export interface ExportProfile {
  name: string;
  format: "svg" | "png" | "pdf" | "figma_manifest";
  pdf_intent: "preview" | "print" | null;
  raster: RasterScale | null;
  include_bleed: boolean;
  embed_fonts: boolean;
}

export interface RasterScale {
  scale: number;
  dpi: number | null;
}

export type FieldPatch<T> =
  | {
      kind: "unchanged";
    }
  | {
      kind: "set";
      value: T;
    };

export type OptionalFieldPatch<T> =
  | {
      kind: "unchanged";
    }
  | {
      kind: "set";
      value: T;
    }
  | {
      kind: "clear";
    };

export interface NodePatch {
  name: OptionalFieldPatch<string>;
  kind: FieldPatch<NodeKind>;
  transform: FieldPatch<Transform>;
  size: FieldPatch<SizeSpec>;
  fills: FieldPatch<Fill[]>;
  strokes: FieldPatch<Stroke[]>;
  corner: FieldPatch<CornerRadii>;
  opacity: FieldPatch<number>;
  opacity_token: OptionalFieldPatch<string>;
  clip: FieldPatch<boolean>;
  layout: OptionalFieldPatch<AutoLayoutProps>;
  computed: OptionalFieldPatch<ComputedGeometry>;
  locked: FieldPatch<boolean>;
}

export type ParentRef =
  | {
      kind: "page";
      id: PageId;
    }
  | {
      kind: "node";
      id: NodeId;
    };

export type Operation =
  | {
      kind: "update_node";
      node_id: NodeId;
      patch: NodePatch;
    }
  | {
      kind: "move_node";
      node_id: NodeId;
      new_parent: ParentRef;
      index: number;
    }
  | {
      kind: "upsert_slot";
      slot: Slot;
    }
  | {
      kind: "remove_slot";
      slot_id: SlotId;
    }
  | {
      kind: "bind_node_to_slot";
      slot_id: SlotId;
      node_id: NodeId;
    }
  | {
      kind: "unbind_node_from_slot";
      slot_id: SlotId;
      node_id: NodeId;
    };

export interface Diagnostic {
  severity: "error" | "warning" | "advice";
  phase: "contract" | "operation" | "validation" | "dsl" | "layout" | "export";
  code: string;
  message: string;
  subject: DiagnosticSubject | null;
  hint: string | null;
}

export type DiagnosticSubject =
  | {
      kind: "document";
    }
  | {
      kind: "page";
      id: PageId;
    }
  | {
      kind: "node";
      id: NodeId;
    }
  | {
      kind: "slot";
      id: SlotId;
    };
