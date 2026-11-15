import { createEffect } from "solid-js";
import { Route, Router, useLocation } from "@solidjs/router";
import { Footer } from "./components/Footer";
import { liveMessage } from "./lib/announce";
import { TopBar } from "./components/TopBar";
import { Landing } from "./routes/Landing";
import { Studio } from "./routes/Studio";
import { Library } from "./routes/Library";

function Layout(props: { children?: unknown }) {
  const location = useLocation();
  createEffect(() => {
    // scroll to top on route change; let in-page anchors alone
    void location.pathname;
    window.scrollTo({ top: 0, behavior: "auto" });
  });

  return (
    <>
      <a class="skip-link" href="#main">
        Skip to content
      </a>
      <TopBar />
      <main id="main">{props.children as never}</main>
      <Footer />
      <div class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {liveMessage()}
      </div>
    </>
  );
}

export function App() {
  return (
    <Router root={Layout}>
      <Route path="/" component={Landing} />
      <Route path="/studio" component={Studio} />
      <Route path="/library" component={Library} />
    </Router>
  );
}
