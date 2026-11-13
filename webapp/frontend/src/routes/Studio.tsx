import { createSignal, Show } from "solid-js";
import { TabPanel, Tabs } from "../components/Tabs";
import { VideoScanner } from "../components/VideoScanner";
import { StudioPanel } from "../components/StudioPanel";
import { StudioResults } from "../components/StudioResults";
import { createStudioState } from "../lib/studio-state";
import { isLocal } from "../lib/health";

export function Studio() {
  const studio = createStudioState();
  const [mode, setMode] = createSignal<"page" | "video">("page");

  return (
    <div class="studio">
      <div class="container">
        <div class="studio__head">
          <h1 class="h2">Restore a page, or capture a book</h1>
          <p class="lede">
            <Show
              when={isLocal()}
              fallback={
                <>
                  Photos, PDFs and page-turning videos. This demo processes pages on its server;
                  the app itself runs offline, on your machine.
                </>
              }
            >
              Photos, PDFs and page-turning videos. Everything is processed on this computer;
              nothing is uploaded.
            </Show>
          </p>
        </div>

        <Tabs
          label="Scan mode"
          idPrefix="mode"
          items={[
            { id: "page", label: "Photo or PDF" },
            { id: "video", label: "Book video" },
          ]}
          selected={mode()}
          onSelect={setMode}
          disabled={studio.phase() === "running"}
        />
        <TabPanel idPrefix="mode" id="video" selected={mode() === "video"} keepMounted>
          <VideoScanner />
        </TabPanel>
        <TabPanel
          idPrefix="mode"
          id="page"
          selected={mode() === "page"}
          keepMounted
          class="studio__grid"
        >
          <div class="studio__panel">
            <StudioPanel state={studio} />
          </div>

          <div class="results">
            <Show
              when={studio.phase() === "done" && studio.result()}
              fallback={<IdleStage />}
            >
              <StudioResults state={studio} />
            </Show>
          </div>
        </TabPanel>
      </div>
    </div>
  );
}

/** Empty state: real input pages and what a run will produce. */
function IdleStage() {
  return (
    <div class="stack-16">
      <figure class="studio-figure">
        <div class="studio-figure__images">
          <img src="/examples/letterpress-hero.jpg" alt="1955 letterpress page, real scan" />
          <img
            src="/examples/invoice-hero.jpg"
            alt="Invoice photo under a simulated phone shadow"
          />
        </div>
        <figcaption>Real pipeline input, nothing staged</figcaption>
      </figure>

      <div class="expect">
        <h2 class="h3">What you will get</h2>
        <ul>
          <li>the cleaned page, side by side with your input</li>
          <li>the numbered review overlay, with every uncertain token boxed</li>
          <li>the review queue with alternative readings kept</li>
          <li>a searchable PDF, transcript and OCR JSON to download</li>
        </ul>
        <p class="field__hint">
          The first run on a fresh server also warms the OCR engine, so it can take a little
          longer.
        </p>
      </div>
    </div>
  );
}
