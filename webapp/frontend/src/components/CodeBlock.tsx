import { createSignal } from "solid-js";
import { announce } from "../lib/announce";

/** Mono block with a copy-to-clipboard button.
 *  `label` names what is copied: the button reads "Copy <label>". */
export function CodeBlock(props: { code: string; label?: string }) {
  const [copied, setCopied] = createSignal(false);
  const what = () => props.label ?? "code";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(props.code);
      setCopied(true);
      announce(`Copied the ${what()} to the clipboard.`);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      announce("Could not copy. Select the text and copy it instead.");
    }
  };

  return (
    <div class="codeblock">
      <button class="copy" type="button" onClick={copy}>
        {copied() ? "Copied" : `Copy ${what()}`}
      </button>
      <pre>
        <code>{props.code}</code>
      </pre>
    </div>
  );
}
