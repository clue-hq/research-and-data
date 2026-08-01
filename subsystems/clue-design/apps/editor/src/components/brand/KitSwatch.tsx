import React from "react";

/** A color chip for the review page. The fill is kit *data* (an ingested hex),
 * not chrome — the one inline `backgroundColor` case the spec permits alongside
 * the reversed-logo backdrop and the font specimen stack. */
export function KitSwatch({
  hex,
  large = false
}: {
  hex: string;
  large?: boolean;
}): React.ReactElement {
  return (
    <span
      className={`swatch${large ? " is-large" : ""}`}
      style={{ backgroundColor: hex || "transparent" }}
      aria-hidden
    />
  );
}
