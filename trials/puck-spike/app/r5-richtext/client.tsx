"use client";

import { useState, type ReactNode } from "react";
import { Puck, RichTextMenu, type Config, type Data } from "@puckeditor/core";
import styles from "./r5-menu.module.css";

const BODY = "<p>Lower medical spend in year one. No plan changes.</p>";

// The editor's real constraints: Puck.Preview only, Puck's own canvas iframe off.
const config = {
  components: {
    RichTextProbe: {
      defaultProps: { body: BODY },
      fields: {
        body: {
          contentEditable: true,
          options: { blockquote: false, codeBlock: false, horizontalRule: false },
          // `data-puck-rte-menu` is load-bearing: Puck's editor onBlur (EditorInner, chunk-WF6I3XOL.mjs)
          // keeps focus only when the blur target sits inside `[data-puck-rte-menu]`. Without it, a click on
          // a button here (Chromium focuses buttons on mousedown) blurs the editor, Puck clears
          // `currentRichText`, the menu unmounts and the command never runs (RICHTEXT-R5.md, row 1).
          renderInlineMenu: () => (
            <div className={styles.row} data-puck-rte-menu="" data-r5-inline-menu="true">
              <RichTextMenu.Group>
                <RichTextMenu.Bold />
                <RichTextMenu.Italic />
                <RichTextMenu.Underline />
                <RichTextMenu.Strikethrough />
              </RichTextMenu.Group>
              <span aria-hidden="true" className={styles.divider} />
              <RichTextMenu.Group>
                <RichTextMenu.BulletList />
                <RichTextMenu.OrderedList />
              </RichTextMenu.Group>
            </div>
          ),
          type: "richtext",
        },
      },
      render: ({ body }: { body: ReactNode }) => <section style={{ fontSize: 24, padding: 48 }}>{body}</section>,
    },
  },
} as unknown as Config;

const INITIAL: Data = {
  content: [{ props: { body: BODY, id: "probe" }, type: "RichTextProbe" }],
  root: { props: {} },
};

export function RichTextSpike() {
  const [data, setData] = useState<Data>(INITIAL);
  return (
    <>
      <Puck config={config} data={INITIAL} iframe={{ enabled: false }} onChange={setData}>
        <Puck.Preview />
      </Puck>
      <pre data-r5-data="true" style={{ fontSize: 11, padding: 16 }}>
        {JSON.stringify(data.content[0]?.props ?? null)}
      </pre>
    </>
  );
}
