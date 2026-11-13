/** Colour theme: follow the system, or force light/dark for this browser.
 *  The palette reacts to <html data-theme> (palette.generated.css). */
import { createSignal } from "solid-js";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "veriscript.theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];

function read(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
}

const [theme, setThemeSignal] = createSignal<ThemeChoice>(read());

/** Call once before the first render, so the page never flashes. */
export function applyStoredTheme() {
  apply(theme());
}

export function cycleTheme() {
  const next = ORDER[(ORDER.indexOf(theme()) + 1) % ORDER.length];
  setThemeSignal(next);
  apply(next);
  try {
    if (next === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, next);
  } catch {
    /* blocked storage: the choice lasts for this page only */
  }
}

export const themeChoice = theme;
export const themeLabel = (choice: ThemeChoice) =>
  choice === "system" ? "Auto" : choice === "light" ? "Light" : "Dark";
