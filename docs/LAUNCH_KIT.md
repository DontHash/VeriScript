# Launch kit - v1.6.0 (2026-10-10)

Everything the launch needs is live: `pip install veriscript` 1.6.0 on PyPI,
the GitHub release, and <https://veriscript.live> with the digit-first queue
and adopted validators. This file is the copy, the demo script, the
sequencing, and the answers - written to be used, not admired.

The one-sentence wedge, everywhere: **offline OCR for Devanagari documents
that tells you which numbers not to trust - instead of quietly inventing
them.**

## 0. Proof points (all from frozen sets; quote these, link these)

| Claim | Number | Source |
|---|---|---|
| Real digit errors surfaced in the top-10 review queue | **27 of 29 (93%)** on the owner-audited residual of the government-PDF set | PLAN.md Appendix AQ |
| Queue digit-content recall@10 (metric v3) | **0.85** government PDFs / **0.91** letterpress | Appendix AN/AO |
| Precision@10 after the digit-first queue | **0.10 -> 0.21** PDFs, **0.15 -> 0.36** letterpress | Appendix AO |
| What the engine invents | Tesseract invents **5,080 tokens** on the letterpress set; ours ships an honesty gate instead | BENCHMARK.md |
| Cost of self-hosting | ~**$0.0003/page** vs $1.00-1.50/1k cloud read tier | MARKET.md |
| Correction loop (data channel) | **317 owner-audited** target-domain digit labels collected from normal review sessions | Appendix AR |

Honest weak points to volunteer before anyone finds them: handwriting is out
of scope; real phone-photo numbers are still proxy-only (CER 0.37 medium on
the synthetic proxy); letterpress stays at 0.373 under the default reader;
our small-model verifier path was tested three times and **stopped** each
time by its gate (Appendices AC/AF/AS) - the queue layer, not a bigger
model, is the product's accuracy story.

## 1. Show HN

**Title options** (lead with 1):
1. `Show HN: VeriScript - offline OCR that flags uncertain digits instead of inventing them`
2. `Show HN: Devanagari OCR that tells you which numbers not to trust`
3. `Show HN: An offline OCR with a review queue for the numbers it can't read`

**Post body** (HN voice: facts, no pitch, invite scrutiny):

> OCR is fine until the number it reads is wrong. On Devanagari documents -
> court registers, land papers, bills - a silently wrong digit is the whole
> failure. VeriScript is an offline OCR pipeline (photo/scan/PDF in;
> searchable PDF, transcript, Markdown, JSON out) that re-reads digit
> tokens, flags provable faults (impossible dates), and puts the risky ones
> in a ranked review queue with the alternative reading kept. A human
> confirms or corrects; corrections re-export with provenance.
>
> Measured on hash-frozen sets with the owner of the data auditing the
> residual: **27 of 29 real digit errors land in the top-10 queue (93%)**.
> The average review page is now half the length it was - precision@10
> doubled after the queue split into numbers-vs-text sections.
>
> It runs on CPU, no account, no telemetry, MIT code (engine Apache-2.0).
> Everything is local: `pip install veriscript`, or the demo at
> https://veriscript.live (one page, deleted after 60 minutes).
>
> What it doesn't do: handwriting, and real phone photos are still pending
> real ground truth. The letterpress numbers (CER 0.37) are honest, not
> good. The review layer is the part I'd like feedback on - especially from
> anyone who digitizes Nepali/Hindi registers for a living.

**First comment** (post immediately; long, numbers, links):

> Numbers, since HN will ask. Frozen sets, bootstrap CIs, raw JSON in the
> repo.
>
> - Modern government PDFs: engine CER 0.135 [0.097-0.186]; digit-content
>   queue recall@10 0.85; **0.93 on the audited real errors** (I classified
>   all flagged tokens with the dataset owner - 29 real, 12 metric edges).
> - Letterpress (the honest bar): CER 0.373 under the default reader;
>   queue recall@10 0.91.
> - Tesseract as the comparison: page CER 0.353 but 5,080 invented tokens
>   on 69 letterpress pages - that is the failure mode this project exists
>   to refuse. Surya: CER 0.166 at 172 s/page on a 4 GB laptop GPU; Qwen3-
>   VL: CER 0.176 at 153 s/page with 224 invented tokens.
> - The queue metric itself was corrected this release: the old number
>   (0.38) was ~80% a measurement artifact (line-level tokens scored
>   against word-level ground truth). Both numbers are on record in the
>   changelog; the corrected definition, the attribution script and the
>   audit are all in the repo.
> - Negative results are kept: three separate attempts to train a small
>   digit verifier were stopped by their pre-registered gates
>   (precision 0.5 -> 0.0 -> 0.0). The writeups are in docs/PLAN.md.
>
> Reproduce anything: docs/BENCHMARK.md, docs/EVALUATION.md, `evals/` in the
> repo. Happy to answer anything, including where it fails.

**Q&A prep** (answer fast, link, never argue):

- *"Isn't this just RapidOCR/PaddleOCR?"* - Yes as the recognizer, plus the
  part that matters: layout/reading order fixes, the digit re-pass,
  calibration, validators, and the queue. The engine alone has no way to
  tell you to check a number.
- *"0.85 recall - so 15% are still missed?"* - On the audited residual the
  misses are two specific glyph confusions (1-vs-9, 5-vs-4 in the print
  font) in correctly-boxed fields. Those need a better reader; the queue
  can't flag what every reader agrees on. That's disclosed, not hidden.
- *"Why not a VLM? They're better at tables."* - Measured: 20-170x the cost
  per page, hallucinated tokens, and GPU-class hardware. The product
  constraint is a CPU, offline, 8-10 s/page.
- *"Handwriting?"* - Not supported; explicit. Detection-as-a-flag is a
  maybe; recognition is a different product.
- *"How do you get training data privately?"* - The review loop itself, with
  an explicit export: only the crops the user ticks leave the machine.
- *"Business model?"* - MIT core now; a signed offline installer for the
  archives/courts segment is the plan; no telemetry, ever.
- *"Devanagari-only?"* - First-class Devanagari, English works, same
  pipeline; other scripts are honest no-ops, not silent garbage.

## 2. Product Hunt / DevHunt

**Tagline** (<=60): `Offline OCR that won't invent the numbers on your bill`

**Description**: Devanagari-first OCR that runs on your machine and shows
its work: digits are re-read, impossible values are flagged, and risky
numbers go into a ranked review queue with the alternative reading kept.
Correct them once - the PDF, text and Markdown re-export with provenance.
No cloud, no account, no telemetry. Free core, open source.

**Maker's first comment**: the story (court registers + a wrong digit = a
wrong case number), the 93% number, the honest list (handwriting out,
letterpress 0.37), the ask (try it on your own documents - the demo deletes
uploads after 60 minutes).

**Gallery order**: 1) before/after with the numbered queue [existing
asset: docs/assets/before_after.png], 2) studio review mode with suggestion
chips, 3) the correction loop re-export (before/after file tree), 4) the
benchmark table, 5) offline/no-telemetry statement card.

**Topics**: Developer Tools, Open Source, Privacy, Productivity.

## 3. Reddit (staggered, framed per community - not the same post)

- **r/selfhosted** (T+2d): self-hosting angle. Docker/CLI, cost math
  (~$0.0003/page vs cloud read tier), no telemetry, offline by default.
  One screenshot of the studio; link the repo, not the demo first.
- **r/LocalLLaMA** (T+3d): "I ran the VLM stack against a CPU-first OCR
  pipeline on Devanagari" - the measured bake-off (Surya 172 s/page, Qwen
  153 s/page + invented tokens vs this), where the VLM actually wins
  (table text), and why the product still ships CPU. This audience reads
  methodology; lead with the harness, not the app.
- **r/Nepal** (T+5d): the practical one. Citizenship/lalpurja/court
  register examples, Nepali demo link, ask which document types to test
  next. No benchmark tables in the post - they're linked.
- **r/opensource / r/DataHoarder** (T+1w, only if the first wave lands):
  license-clean stack, no AGPL, the negative results kept in-repo.

## 4. The 90-second demo (screen recording, 1080p, captions > voice)

| Time | On screen | Overlay text |
|---|---|---|
| 0:00-0:08 | Zoomed court-register date cell; printed `२०८१-०४-३२` | "The page says ३२. The OCR says ३९." |
| 0:08-0:25 | Drop `supreme` page into studio; processing beats | "One command. Offline. 8-10 s/page on CPU." |
| 0:25-0:38 | Numbers queue appears; the day-39 flag on top with its chip | "Every uncertain number, ranked - not guessed" |
| 0:38-0:55 | Correct it (type `३२`, Enter); "apply to identical"; queue shrinks | "Fix once, apply to every repeat" |
| 0:55-1:10 | Re-export; open corrected PDF; browser Ctrl+F the corrected date | "Re-exported with provenance - PDF, text, Markdown" |
| 1:10-1:22 | Freeze frame: `27/29 real errors in the top-10`; `precision@10 x2` | "Measured on frozen, audited data" |
| 1:22-1:30 | veriscript.live + `pip install veriscript` + GitHub logo | "Free. Offline. Open source." |

Recording notes: use the v1.6 studio (numbers/text sections visible); the
register page used in the beta is internal-only - record with the synthetic
or heiDATA demo page (`scripts/make_demo_image.py`), or blur the source.
No music; captions carry it. Export GIF (<=8 MB) for HN and a 1080p MP4 for
PH.

## 5. Sequencing

1. **T-2d**: record the demo, finish README/BENCHMARK refresh, verify the
   quickstart from a clean environment (`pip install veriscript` in a fresh
   venv, one command), prepare the Q&A answers as browser bookmarks.
2. **T0, Tuesday 08:30-10:00 ET**: Show HN. Maker in the thread all day -
   speed of honest answers is the ranking strategy.
3. **T0+2d**: Product Hunt (12:01am PT) with the gallery; same-day reply
   effort.
4. **T+2/3/5d**: Reddit, one community per slot, unique framing each.
5. **T+1w**: awesome-ocr/self-hosted lists + alternativeto entries (honest
   entries, where-we-lose included); then the "State of Devanagari OCR"
   write-up if energy remains - that is the ongoing citation engine.
6. **Each launch moment**: log GSC, stars, PyPI downloads (pypistats), demo
   `daily_used` before/after.

## 6. Do not

- No bought upvotes, no review swaps, no copy-paste cross-posts.
- No overclaiming: every number links to its frozen set; "0.93" always
  comes with "audited residual, 29 errors" in the same sentence.
- Don't block AI crawlers (Cloudflare defaults!) - AI visibility is the
  point; the SEO_AEO doc has the checklist.
- Don't argue benchmarks in comments; link and move on.
- Don't launch the demo to HN before checking the rate limits (200
  runs/day, 20 pages/visitor) - the shedding behavior is deliberate and
  documented.
