/** One app-wide polite live region (rendered by <LiveRegion/> in App.tsx).
 *
 *  Screen readers only speak a live region when its text changes, so the
 *  message is cleared first and set on the next frame: announcing the same
 *  sentence twice ("Copied") is still heard twice. */
import { createSignal } from "solid-js";

const [message, setMessage] = createSignal("");
let pending: number | undefined;

export function announce(text: string) {
  if (pending !== undefined) window.cancelAnimationFrame(pending);
  setMessage("");
  pending = window.requestAnimationFrame(() => {
    pending = undefined;
    setMessage(text);
  });
}

export const liveMessage = message;
