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

export function useHealth() {
  if (!requested) {
    requested = true;
    void fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
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
