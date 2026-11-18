import { Show } from "solid-js";
import { isLocal } from "../lib/health";

export function Footer() {
  return (
    <footer class="footer">
      <div class="container footer__grid">
        <div class="footer__col">
          <span class="wordmark">VeriScript</span>
          <p class="footer__note">
            Offline document restoration for Nepali, Hindi and English. Photos and scans in;
            searchable PDF, transcript and Markdown out, with every uncertain number on the record.
          </p>
        </div>

        <div class="footer__col">
          <p class="footer__heading">Explore</p>
          <a class="footer__link" href="/#examples">
            Real examples
          </a>
          <a class="footer__link" href="/#offline">
            Runs offline
          </a>
          <a class="footer__link" href="/studio">
            Open the studio
          </a>
          <a class="footer__link" href="/nepali-ocr/">
            Nepali OCR
          </a>
          <a
            class="footer__link"
            href="https://github.com/DontHash/VeriScript/blob/main/docs/BENCHMARK.md"
            target="_blank"
            rel="noreferrer noopener"
          >
            Benchmark
          </a>
        </div>

        <div class="footer__col">
          <p class="footer__heading">Project</p>
          <a
            class="footer__link"
            href="https://github.com/DontHash/VeriScript"
            target="_blank"
            rel="noreferrer noopener"
          >
            GitHub repository
          </a>
          <a
            class="footer__link"
            href="https://github.com/DontHash/VeriScript/blob/main/docs/ACCESSIBILITY.md"
            target="_blank"
            rel="noreferrer noopener"
          >
            Accessibility
          </a>
          <p class="footer__note">
            MIT licensed. Third-party models keep their licenses.
          </p>
        </div>
      </div>

      <div class="container footer__meta">
        <p class="footer__note">
          <Show
            when={isLocal()}
            fallback="This demo deletes every upload after its retention window. The offline guarantee belongs to the local app."
          >
            Running locally: your pages stay on this computer.
          </Show>
        </p>
      </div>
    </footer>
  );
}
