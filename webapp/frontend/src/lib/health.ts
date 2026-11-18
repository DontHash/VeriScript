/** Server health, fetched once per page load and shared by every view.
 *
 *  `mode` decides the wording: "local" means this studio runs on the
 *  person's own computer (the desktop app, or `python webapp/server.py`),
 *  "demo" means a shared hosted server. */
import { createSignal } from "solid-js";
import { fetchHealth } from "./api";
import type { Health } from "./types";

const [health, setHealth] = createSignal<Health | null>(null);
let requested = false;
let pollTimer: number | undefined;

/** Fetch now; while the server reports busy (e.g. warming the OCR engine
 *  after launch), check again every few seconds so "busy" never goes stale. */
export function refreshHealth() {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer);
  pollTimer = undefined;
  void fetchHealth()
    .then((h) => {
      setHealth(h);
      if (h.busy) pollTimer = window.setTimeout(refreshHealth, 3000);
    })
    .catch(() => setHealth(null));
}

export function useHealth() {
  if (!requested) {
    requested = true;
    refreshHealth();
  }
  return health;
}

/** True when the server says it runs on this computer. */
export const isLocal = () => useHealth()()?.mode === "local";

/** "60 minutes", "6 hours", "7 days". */
export function retentionText(minutes: number): string {
  if (minutes < 120) return `${minutes} minutes`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} hours`;
  return `${Math.round(minutes / (24 * 60))} days`;
}
