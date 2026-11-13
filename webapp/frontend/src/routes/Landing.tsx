import { createResource, For } from "solid-js";
import { CodeBlock } from "../components/CodeBlock";
import { CompareSlider } from "../components/CompareSlider";

async function fetchLimits() {
  try {
    const r = await fetch("/api/health");
    if (!r.ok) return null;
    const data = await r.json();
    return data?.limits ?? null;
  } catch {
    return null;
  }
}

const EXAMPLES = [
  {
    id: "letterpress",
    title: "1955 letterpress page",
    before: "/examples/letterpress-input.jpg",
    after: "/examples/letterpress-overlay.jpg",
    meta: "30 tokens, 17 flagged",
    note: "Green means accepted, amber uncertain, red a digit conflict with the alternative reading kept. Source: heiDATA, CC BY 4.0.",
  },
  {
    id: "invoice",
    title: "Invoice photo",
    before: "/examples/invoice-input.jpg",
    after: "/examples/invoice-overlay.jpg",
    meta: "27 tokens, 8 flagged, 4 conflicts",
    note: "The repository's own invoice under a simulated phone shadow. The restore removes the shadow; the flags stay where the reading was unsure.",
  },
  {
    id: "clean",
    title: "Clean invoice",
    before: "/examples/synthetic-invoice.jpg",
    after: "/examples/synthetic-invoice-overlay.jpg",
    meta: "27 tokens, 0 flagged",
    note: "A clean machine-printed page, where every token is accepted. The hard pages are what the review queue is for.",
  },
];

export function Landing() {
  const [limits] = createResource(fetchLimits);
  const limitText = () => {
    const pages = limits()?.pages_per_client;
    return pages
      ? `No account · ${pages} pages a day · files deleted after the demo`
      : "No account · files deleted after the demo";
  };

  return (
    <>
      <section class="hero">
        <div class="container hero__grid">
          <div class="hero__copy">
            <h1 class="display hero__title">It will not invent the numbers on your bill</h1>
            <p class="lede">
              VeriScript turns photos, scans and PDFs into cleaned pages, searchable PDFs and
              Markdown. Every uncertain number goes into a review queue instead of being guessed.
            </p>
            <div class="hero__cta">
              <a class="btn btn--primary" href="/studio">Try it</a>
              <a class="textlink" href="#examples">See real examples</a>
            </div>
            <p class="hero__note">{limitText()}</p>
          </div>

          <figure class="hero__figure">
            <img
              src="/examples/letterpress-overlay.jpg"
              alt="A 1955 letterpress page with review boxes around uncertain text and digits"
            />
            <figcaption>
              Real output: accepted, uncertain and conflicting readings marked on the page.
            </figcaption>
          </figure>
        </div>
      </section>

      <section class="section" id="examples">
        <div class="container">
          <div class="section__head">
            <h2 class="h2">Real pages, real output</h2>
            <p class="lede">
              These images are the pipeline's own output, including the pages it flags.
            </p>
          </div>

          <div class="examples">
            <For each={EXAMPLES}>
              {(ex) => (
                <article class="example">
                  <h3 class="h3">{ex.title}</h3>
                  <CompareSlider before={ex.before} after={ex.after} alt={ex.title} />
                  <p class="example__meta">{ex.meta}</p>
                  <p class="example__note">{ex.note}</p>
                </article>
              )}
            </For>
          </div>
        </div>
      </section>

      <section class="section slate-section" id="offline">
        <div class="container">
          <div class="section__head">
            <h2 class="h2">This demo runs here; the product runs on your machine</h2>
            <p class="lede">
              The demo processes your page on this server and deletes it after the retention
              window. The product itself makes no cloud calls, has no telemetry and needs no
              account.
            </p>
          </div>

          <CodeBlock
            label="commands"
            code={`pip install -r requirements.txt

# one page in — cleaned page, searchable PDF, transcript, Markdown, OCR JSON out
python -m veriscript --mode document --input page.jpg --output out/run1

# the same studio, locally
python webapp/server.py   # → http://127.0.0.1:8000`}
          />

          <p class="landing__note">The local pipeline runs with networking disabled.</p>
        </div>
      </section>
    </>
  );
}
