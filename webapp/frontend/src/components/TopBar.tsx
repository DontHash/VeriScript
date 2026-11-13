import { A, useLocation } from "@solidjs/router";
import { announce } from "../lib/announce";
import { cycleTheme, themeChoice, themeLabel } from "../lib/theme";

export function TopBar() {
  const location = useLocation();
  const isStudio = () => location.pathname.startsWith("/studio");

  return (
    <header class="topbar">
      <div class="container topbar__inner">
        <A href="/" class="wordmark" aria-label="VeriScript home">
          VeriScript
        </A>

        <nav class="topbar__nav" aria-label="Primary">
          <a class="nav-link" href="/#examples">
            Examples
          </a>
          <a class="nav-link" href="/#offline">
            Offline
          </a>
        </nav>

        <div class="topbar__actions">
          <button
            type="button"
            class="nav-link topbar__theme"
            title="Switch between the system theme, light and dark"
            onClick={() => {
              cycleTheme();
              announce(`Theme: ${themeLabel(themeChoice())}`);
            }}
          >
            Theme: {themeLabel(themeChoice())}
          </button>
          <a
            class="nav-link topbar__gh"
            href="https://github.com/DontHash/VeriScript"
            rel="noreferrer noopener"
            target="_blank"
          >
            GitHub
          </a>
          <A
            class="btn btn--ghost btn--small"
            href="/studio"
            aria-current={isStudio() ? "page" : undefined}
          >
            Open studio
          </A>
        </div>
      </div>
    </header>
  );
}
